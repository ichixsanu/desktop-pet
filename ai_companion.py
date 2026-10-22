"""AI companion bridge: Groq calls, config, memory, and rate limiting.

Everything in this module is safe to call from a worker thread. The pet's Qt
callbacks arrive on the GUI thread via a queued signal, so this module never
touches Qt.

The result of a request is reported to the caller as ``(text, status)``:

    "ok"           - `text` is a real model reply, safe to speak as-is
    "skipped"      - rate limit / daily cap / circuit breaker: say nothing
    "unavailable"  - AI is off, misconfigured, or the call failed: the caller
                     may fall back to a canned line

That distinction matters: the old code reported every failure as "no text",
so a dead API made the pet emit a random unsolicited line on every attempt.
"""

import os
import re
import json
import time
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "companion_config.json")
MEMORY_PATH = os.path.join(BASE_DIR, "companion_memory.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")

# How long to stop trying after every key has failed (dead network, bad model).
CIRCUIT_COOLDOWN = 10 * 60
# How long a single key stays sidelined after a 429, before it is retried.
KEY_COOLDOWN = 5 * 60
# Network/SDK timeout, seconds. Without this a hung socket pins a thread.
REQUEST_TIMEOUT = 20.0
# Reasoning models can burn the whole budget thinking. If that happens we
# double the budget next time rather than talking to ourselves.
MIN_TOKEN_BUDGET = 40
MAX_TOKEN_BUDGET = 1024

STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"
STATUS_UNAVAILABLE = "unavailable"

# Errors that mean "this will never work until the config changes" and so
# should not be retried on every call.
_FATAL_ERRORS = ("NotFoundError", "model_not_found", "invalid_request_error")


# =====================================================================
# .env
# =====================================================================

def _load_env(path):
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Never overrides a variable that is already set in the real environment.
    Tolerates `export ` prefixes, `#` comments, and blank lines.
    """
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.split(" #", 1)[0].strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


_load_env(ENV_PATH)

try:
    import groq
    from groq import Groq
    _HAS_GROQ = True
except Exception:
    groq = None
    _HAS_GROQ = False

MODEL = os.environ.get("MODEL", "qwen/qwen3.8-27b")


def _collect_api_keys():
    """All GROQ_API_KEY* values, with GROQ_API_KEY2 before GROQ_API_KEY10."""
    found = []
    for name, value in os.environ.items():
        if not value:
            continue
        m = re.fullmatch(r"GROQ_API_KEY(\d*)", name)
        if m:
            found.append((int(m.group(1)) if m.group(1) else 1, value))
    found.sort(key=lambda item: item[0])
    return [value for _idx, value in found]


_KEYS = _collect_api_keys()
_clients = []
if _HAS_GROQ and _KEYS:
    for _key in _KEYS:
        try:
            _clients.append(Groq(api_key=_key, timeout=REQUEST_TIMEOUT, max_retries=0))
        except Exception:
            pass


# =====================================================================
# Config
# =====================================================================

def _default_config():
    return {
        "ai_enabled": True,
        "default_system_prompt": (
            "You are a tiny pixel pet companion living on the user's desktop. "
            "Reply in first person, one short sentence, under 12 words, casual. "
            "Never mention being an AI, a model, or a screenshot."
        ),
        "companions": {},
        "rate_limits": {
            "min_seconds_between": {"idle": 45, "screenshot": 900, "user": 5},
            "max_per_hour": {"idle": 6, "screenshot": 4, "user": 60},
        },
        "screenshots": {
            "enabled": False,
            "interval_minutes": 15,
            "max_per_day": 40,
            "require_recent_activity_minutes": 3,
            "blocklist": [],
            "jpeg_quality": 70,
            "capture_log_size": 20,
            # One-shot screenshots through xdg-desktop-portal, for native
            # Wayland sessions where the blocklist cannot be honoured. The
            # portal dialog makes the user the privacy gate, and it only ever
            # runs for a manual "Look At This", never in the background.
            "wayland_portal": False,
            "ocr": {
                "enabled": True,
                "engine": "auto",
                "fail_closed": True,
                "max_width": 1600,
                "timeout_seconds": 6,
                "languages": "eng",
                "psm": 3,
                "extra_keywords": [],
                "allowed_keywords": [],
            },
        },
        "memory": {"enabled": True, "max_facts": 20},
        # ambient = sounds the pet makes on its own; they share one cooldown
        # of ambient_gap_seconds so it stays a rare, quiet presence.
        "audio": {"enabled": True, "volume": 0.3, "voice": True,
                  "ambient": True, "ambient_gap_seconds": 150},
        "state": {"enabled": True, "file": "pet_state.json",
                  "save_interval_seconds": 30, "energy_decay_per_hour": 8},
        "focus": {"enabled": True,
                  "state_files": ["~/.focus.json", "~/.config/focus/state.json"],
                  "poll_seconds": 5},
        "behaviour": {
            "ignore_windows": [],
            "allow_jump": True,
            "allow_chase": True,
            "ai_context_lines": True,
            "hide_on_fullscreen": True,
            # "strong": an unmanaged X11 window that stays above everything,
            # fullscreen windows included. "normal": a regular on-top window.
            "always_on_top": "strong",
            "sleep_when_idle_seconds": 300,
            "quiet_hours": {"enabled": False, "start": "23:00", "end": "07:00"},
        },
    }


def _deep_merge(base, override):
    """Merge nested dicts so a user config can override one leaf without
    having to restate its siblings (e.g. only `screenshots.enabled`)."""
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_config():
    cfg = _default_config()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                _deep_merge(cfg, json.load(f))
        except Exception:
            pass
    return cfg


CONFIG = _load_config()

# mtime+size of the file the live CONFIG was built from. Config edits used to
# need a restart, which meant "I turned screenshots off" was a lie until the
# next launch: the running pet kept using the values it had loaded.
_config_stamp = None


def _stamp():
    try:
        stat = os.stat(CONFIG_PATH)
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


_config_stamp = _stamp()


def reload_config_if_changed() -> bool:
    """Re-read companion_config.json when it changed on disk.

    Updates the existing CONFIG object in place, so every caller that holds a
    reference (including a test patch) keeps its identity and starts seeing the
    new values. Returns True when the config was actually reloaded.
    """
    global _config_stamp
    stamp = _stamp()
    if stamp is None or stamp == _config_stamp:
        return False
    fresh = _load_config()
    with _lock:
        CONFIG.clear()
        CONFIG.update(fresh)
        _config_stamp = stamp
    return True


# =====================================================================
# Mutable state (all access under _lock)
# =====================================================================

_lock = threading.RLock()
_state = {
    "key_idx": 0,
    "dead_keys": set(),        # auth failures: never retried this session
    "key_cooldown": {},        # 429s: retried after KEY_COOLDOWN
    "disabled_until": 0.0,
    "fatal_reason": "",        # e.g. "model_not_found"; cleared on config fix
    "token_budget": MIN_TOKEN_BUDGET,
}
_sent_log = {"idle": [], "screenshot": [], "user": []}
_daily = {"date": "", "count": 0}
_last_capture = 0.0
_warned = set()
# What happened to recent capture attempts, newest last. Rule names and
# reasons only -- never image content -- so this is safe to show in the menu.
_capture_log = []


def _warn_once(key, message):
    """Print a diagnostic at most once per process, so a misconfigured model
    is visible instead of failing silently forever."""
    with _lock:
        if key in _warned:
            return
        _warned.add(key)
    print("[ai_companion] %s" % message, flush=True)


# =====================================================================
# Public status
# =====================================================================

def ai_enabled():
    with _lock:
        if _state["fatal_reason"]:
            return False
    return bool(CONFIG.get("ai_enabled", True) and _HAS_GROQ and _clients)


def ai_configured() -> bool:
    """Whether the model is set up, regardless of whether it is working.

    Lets the UI distinguish "you never configured this" from "this is
    configured and failing", which is the difference between a hint and a
    retry button. Deliberately does not require MODEL to be set explicitly:
    the module has a working default, and demanding an override made a pet
    that talks fine report itself as unconfigured.
    """
    return bool(_HAS_GROQ and _clients and MODEL)


def reset_failures() -> None:
    """Clear the circuit breaker and key bans so the next call tries again.

    For the "Retry AI" menu item after fixing MODEL or adding a key.
    """
    with _lock:
        _state["fatal_reason"] = ""
        _state["dead_keys"].clear()
        _state["key_cooldown"].clear()
        _state["disabled_until"] = 0.0
        _state["key_idx"] = 0


def ai_status():
    """Human-readable reason the AI is on or off, for menus and diagnostics."""
    with _lock:
        fatal = _state["fatal_reason"]
    if not CONFIG.get("ai_enabled", True):
        return {"enabled": False, "reason": "disabled in companion_config.json"}
    if not _HAS_GROQ:
        return {"enabled": False, "reason": "the groq package is not installed"}
    if not _clients:
        return {"enabled": False, "reason": "no GROQ_API_KEY set in .env"}
    if fatal:
        return {"enabled": False, "reason": fatal}
    return {"enabled": True, "reason": "%s via %d key(s)" % (MODEL, len(_clients))}


def screenshot_settings():
    return CONFIG.get("screenshots", {})


def ocr_settings():
    """The OCR content filter's config (see ocr_guard for the rule set)."""
    cfg = CONFIG.get("screenshots", {}).get("ocr", {})
    return cfg if isinstance(cfg, dict) else {}


def blocklist():
    """The live screenshot blocklist. Always a list of strings."""
    entries = CONFIG.get("screenshots", {}).get("blocklist", [])
    if not isinstance(entries, list):
        return []
    return [str(e) for e in entries if str(e).strip()]


def add_blocklist_entry(entry) -> bool:
    """Add one entry to the screenshot blocklist and save. Returns True if it
    was new. Used by the "Never Capture This App" menu action."""
    entry = (entry or "").strip()
    if not entry:
        return False
    with _lock:
        entries = CONFIG.setdefault("screenshots", {}).setdefault("blocklist", [])
        if not isinstance(entries, list):
            entries = []
            CONFIG["screenshots"]["blocklist"] = entries
        if any(str(e).strip().lower() == entry.lower() for e in entries):
            return False
        entries.append(entry)
    save_config()
    return True


def set_blocklist(entries) -> bool:
    """Replace the whole blocklist (the Edit Blocklist dialog)."""
    cleaned = [str(e).strip() for e in (entries or []) if str(e).strip()]
    with _lock:
        CONFIG.setdefault("screenshots", {})["blocklist"] = cleaned
    return save_config()


def note_capture_decision(action: str, reason: str = "") -> None:
    """Record what happened to a capture attempt, for the menu.

    `action` is a short label ("sent", "discarded", "blocked", "refused",
    "off"); `reason` must never contain image content.
    """
    entry = {"at": time.time(), "action": str(action)[:24], "reason": str(reason)[:120]}
    with _lock:
        cap = int(CONFIG.get("screenshots", {}).get("capture_log_size", 20) or 20)
        _capture_log.append(entry)
        del _capture_log[:-max(1, cap)]


def capture_decisions(limit: int = 5):
    """The most recent capture decisions, newest first."""
    with _lock:
        return list(reversed(_capture_log[-max(1, limit):]))


def last_capture_decision():
    with _lock:
        return _capture_log[-1] if _capture_log else None


def screenshots_status_text() -> str:
    """One line for the context menu: whether, and how, captures are gated."""
    scfg = screenshot_settings()
    if not scfg.get("enabled", False):
        return "screenshots off"
    bits = ["screenshots on, every %s min" % scfg.get("interval_minutes", 15)]
    rules = len(blocklist())
    if rules:
        bits.append("%d blocklist rule%s" % (rules, "" if rules == 1 else "s"))
    if ocr_settings().get("enabled", True):
        bits.append("OCR filter")
    last = last_capture_decision()
    if last:
        stamp = time.strftime("%H:%M", time.localtime(last["at"]))
        bits.append("last %s %s%s" % (stamp, last["action"],
                                      (" (%s)" % last["reason"]) if last["reason"] else ""))
    return " - ".join(bits)


def general_settings():
    """Config sections the pet itself reads (not the model's)."""
    return CONFIG


def set_system_prompt(skin, prompt):
    """Set (or clear) a companion's personality and persist it.

    Passing an empty string clears the override, so the companion falls back to
    `default_system_prompt` again.
    """
    with _lock:
        companions = CONFIG.setdefault("companions", {})
        entry = companions.setdefault(skin, {})
        prompt = (prompt or "").strip()
        if prompt:
            entry["system_prompt"] = prompt
        else:
            entry.pop("system_prompt", None)
        return save_config()


def get_system_prompt(skin):
    entry = CONFIG.get("companions", {}).get(skin, {})
    if not isinstance(entry, dict):
        entry = {}
    return entry.get("system_prompt") or ""


def save_config():
    """Write CONFIG back to companion_config.json, atomically."""
    global _config_stamp
    tmp = CONFIG_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(CONFIG, handle, indent=2)
        os.replace(tmp, CONFIG_PATH)
        _config_stamp = _stamp()
        return True
    except OSError as exc:
        _warn_once("config_write", "could not save companion_config.json: %r" % (exc,))
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


# =====================================================================
# Memory
# =====================================================================

def _memory_enabled():
    return bool(CONFIG.get("memory", {}).get("enabled", True))


def memory_facts(limit: int = 20) -> list:
    """The user's remembered facts, oldest first, capped at `limit`.

    Public helper for the "What Do You Remember?" menu: the memory file is
    the pet's own, but anything shown to a human should come through one
    auditable door rather than pet.py reading a private loader.
    """
    facts = _load_memory()
    if limit and limit > 0:
        facts = facts[-limit:]
    return facts


def forget_memory() -> None:
    """Erase every remembered fact. The other resets (Forget Me, session
    state) deliberately do NOT touch the memory file: this is the only door.
    """
    with _lock:
        try:
            with open(MEMORY_PATH, "w", encoding="utf-8") as f:
                json.dump([], f)
            try:
                os.chmod(MEMORY_PATH, 0o600)
            except OSError:
                pass
        except Exception:
            pass


def _load_memory():
    if not _memory_enabled():
        return []
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [str(item) for item in data] if isinstance(data, list) else []
    except Exception:
        return []


def _remember(fact):
    fact = (fact or "").strip()
    if not fact or not _memory_enabled():
        return
    with _lock:
        mem = _load_memory()
        if fact in mem:
            return
        mem.append(fact)
        cap = int(CONFIG.get("memory", {}).get("max_facts", 20))
        mem = mem[-cap:] if cap > 0 else []
        # Write atomically: a crash mid-dump used to truncate the file, and a
        # truncated file silently loaded as "no memories".
        tmp = MEMORY_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(mem, f, indent=2)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, MEMORY_PATH)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _system_prompt(skin):
    per = CONFIG.get("companions", {}).get(skin, {})
    if not isinstance(per, dict):
        per = {}
    prompt = per.get("system_prompt") or CONFIG.get("default_system_prompt", "")
    if _memory_enabled():
        # Restated on every call so a per-companion prompt can never break the
        # memory contract: the marker is parsed off the reply before it is
        # spoken, and it has to be its own final line to survive intact.
        prompt += ("\nIf you learn something worth remembering, put it on its own "
                   "final line as 'MEMORY: <short fact about the user>' and nothing "
                   "after it. Never say the word memory otherwise.")
    mem = _load_memory()
    if mem:
        prompt += "\nThings you remember about the user: " + "; ".join(mem[-8:])
    return prompt


# =====================================================================
# MEMORY: line extraction (pure, so it is directly testable)
# =====================================================================

_MEMORY_RE = re.compile(r"(?:\A|\n|\s)MEMORY\s*:\s*", re.IGNORECASE)


def split_memory_line(text):
    """Split a raw model reply into (text_to_say, [facts]).

    The prompt asks for a final line starting with ``MEMORY: ``, but models
    routinely append it mid-sentence ("sure! MEMORY: likes dark roast") or
    inline after other prose. Everything after the marker on that line is
    treated as the fact and never spoken, and the marker is always removed
    from what the user sees.
    """
    if not text:
        return None, []

    facts = []
    kept = []
    for line in text.strip().splitlines():
        match = _MEMORY_RE.search(line)
        if match:
            fact = line[match.end():].strip()
            if fact:
                facts.append(fact)
            # Drop the marker *and* the fact from what gets spoken.
            line = line[:match.start()]
        kept.append(line)

    spoken = " ".join(" ".join(kept).split()).strip()
    return (spoken or None), facts


def _extract_memory(text):
    """Strip MEMORY: facts out of a reply, persist them, return what to say."""
    spoken, facts = split_memory_line(text)
    for fact in facts:
        _remember(fact)
    return spoken


# =====================================================================
# Rate limiting
# =====================================================================

def _reserve(kind):
    """Atomically check the limits and claim a slot.

    Check and claim must be one critical section: doing them separately let
    two threads both pass the check and both send.

    Pools are independent per kind. "user" is the one the Speak menu item and
    petting use, so a canned-fallback budget cannot be eaten by the background
    chatter pool -- which is what used to make Speak silently do nothing.
    """
    cfg = CONFIG.get("rate_limits", {})
    min_gap = cfg.get("min_seconds_between", {}).get(kind, 60)
    cap = cfg.get("max_per_hour", {}).get(kind, 6)
    now = time.time()
    with _lock:
        log = _sent_log.setdefault(kind, [])
        log[:] = [t for t in log if now - t < 3600]
        if log and now - log[-1] < min_gap:
            return False
        if len(log) >= cap:
            return False
        log.append(now)
        return True


def _release(kind):
    """Give a claimed slot back when the request produced nothing."""
    with _lock:
        log = _sent_log[kind]
        if log:
            log.pop()


def screenshot_daily_ok():
    cap = CONFIG.get("screenshots", {}).get("max_per_day", 40)
    today = time.strftime("%Y-%m-%d")
    with _lock:
        if _daily["date"] != today:
            _daily["date"] = today
            _daily["count"] = 0
        return _daily["count"] < cap


def _screenshot_daily_mark():
    with _lock:
        if _daily["date"] != time.strftime("%Y-%m-%d"):
            _daily["date"] = time.strftime("%Y-%m-%d")
            _daily["count"] = 0
        _daily["count"] += 1


def screenshot_slot_ok():
    """The whole screenshot policy in one place.

    Returns True only when a capture is both allowed and worth paying for.
    The caller should do nothing at all when this is False -- the old code
    kept re-checking the policy on a timer and then grabbed the screen before
    finding out the request would be rejected.
    """
    scfg = CONFIG.get("screenshots", {})
    if not scfg.get("enabled", False):
        return False
    if not ai_enabled():
        return False
    with _lock:
        interval = float(scfg.get("interval_minutes", 15)) * 60.0
        if _last_capture and (time.time() - _last_capture) < interval:
            return False
    if not screenshot_daily_ok():
        return False
    return _reserve("screenshot")


def reserve_forced_screenshot() -> bool:
    """Claim a screenshot slot for a user-initiated capture.

    "Look at this" bypasses the interval and hourly caps, but still goes
    through the daily cap so a curious user cannot burn a month's quota in an
    afternoon. Privacy checks are not part of this at all -- those live in
    screen_capture and are not negotiable.
    """
    if not screenshot_daily_ok():
        return False
    _reserve("screenshot")
    return True


def record_capture_attempt(captured):
    """Close out a screenshot slot after the capture was attempted.

    The interval throttle is set either way so a blocked window does not turn
    into a capture every tick, but the hourly/daily quota is only charged when
    a frame really was taken and sent.
    """
    global _last_capture
    with _lock:
        _last_capture = time.time()
        if captured:
            _screenshot_daily_mark()
        else:
            _release("screenshot")


# =====================================================================
# Groq call with key rotation + circuit breaker
# =====================================================================

def _classify_error(exc):
    """('fatal'|'cooldown'|'transient', short reason)"""
    name = type(exc).__name__
    text = str(exc)
    if any(marker in text for marker in _FATAL_ERRORS):
        if "model" in text.lower():
            return "fatal", "model_not_found: %s is not available for this key" % MODEL
        return "fatal", "invalid_request: %s" % text[:120]
    if name == "AuthenticationError":
        return "dead", "auth_failed"
    if name in ("RateLimitError", "APIConnectionError", "APITimeoutError"):
        return "cooldown", name
    return "transient", name


def _extract_content(resp):
    """Pull the spoken text out of a completion.

    Reasoning models (the Qwen3 family) can spend the entire token budget
    thinking and return an empty content string, which used to look exactly
    like "the API is down". Returns "" when there is nothing to say.
    """
    try:
        choice = resp.choices[0]
    except (AttributeError, IndexError, KeyError):
        return ""

    message = getattr(choice, "message", None)
    if message is None and isinstance(choice, dict):
        message = choice.get("message")
    if message is None:
        return ""

    if isinstance(message, dict):
        content = message.get("content")
        reasoning = message.get("reasoning")
        finish = choice.get("finish_reason") if isinstance(choice, dict) else getattr(choice, "finish_reason", None)
    else:
        content = getattr(message, "content", None)
        reasoning = getattr(message, "reasoning", None)
        finish = getattr(choice, "finish_reason", None)

    text = (content or "").strip()
    if text:
        return text

    # Out of budget mid-thought: grow the budget for next time instead of
    # silently degrading to canned lines forever.
    if reasoning and finish == "length":
        with _lock:
            if _state["token_budget"] < MAX_TOKEN_BUDGET:
                _state["token_budget"] = min(MAX_TOKEN_BUDGET, _state["token_budget"] * 2)
    return ""


def _call(messages, max_tokens=MIN_TOKEN_BUDGET):
    """Send one chat completion, rotating keys until one works.

    Returns the reply text, or None if every key failed.
    """
    if not ai_enabled():
        return None

    with _lock:
        if time.time() < _state["disabled_until"]:
            return None
        now = time.time()
        for idx in list(_state["key_cooldown"]):
            if now - _state["key_cooldown"][idx] > KEY_COOLDOWN:
                del _state["key_cooldown"][idx]
        start_idx = _state["key_idx"]
        budget = max(max_tokens, _state["token_budget"])

    reason = ""
    fatal = False
    n = len(_clients)
    for offset in range(n):
        idx = (start_idx + offset) % n
        with _lock:
            if idx in _state["dead_keys"] or idx in _state["key_cooldown"]:
                continue
        try:
            resp = _clients[idx].chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.9,
                max_completion_tokens=budget,
                top_p=1,
                stream=False,
            )
            with _lock:
                # Rotate on success too, so multiple keys share the load
                # instead of the first key taking every request forever.
                _state["key_idx"] = (idx + 1) % n
                _state["disabled_until"] = 0.0
            return _extract_content(resp)
        except Exception as exc:
            kind, why = _classify_error(exc)
            reason = why
            if kind == "fatal":
                fatal = True
                break
            with _lock:
                if kind == "dead":
                    _state["dead_keys"].add(idx)
                elif kind == "cooldown":
                    _state["key_cooldown"][idx] = time.time()

    if fatal:
        with _lock:
            _state["fatal_reason"] = reason
        _warn_once("fatal", "%s (set MODEL in .env to a model your key can use)" % reason)
    else:
        with _lock:
            all_dead = all(i in _state["dead_keys"] for i in range(n))
            _state["disabled_until"] = 0.0 if all_dead else time.time() + CIRCUIT_COOLDOWN
        _warn_once("call_failed", "every call failed (%s); retrying in %d min"
                   % (reason or "unknown", CIRCUIT_COOLDOWN // 60))
    return None


# =====================================================================
# Public request API
# =====================================================================

def _run_worker(work, on_crash=None):
    """Run `work` on a daemon thread. `on_crash` gets called if it raises, so
    a claimed rate-limit slot can be released instead of leaking."""
    def guarded():
        try:
            work()
        except Exception as exc:  # never let a worker die noisily
            _warn_once("worker", "background request crashed: %r" % (exc,))
            if on_crash is not None:
                try:
                    on_crash()
                except Exception:
                    pass
    threading.Thread(target=guarded, daemon=True).start()


def maybe_idle_line(skin, on_done, kind="idle"):
    """Ask for a spontaneous line. on_done(text, status).

    `kind` selects the rate-limit pool: "idle" for background chatter, "user"
    for a line the user explicitly asked for (the Speak menu item, petting).
    """
    if not ai_enabled():
        on_done(None, STATUS_UNAVAILABLE)
        return
    if not _reserve(kind):
        on_done(None, STATUS_SKIPPED)
        return

    def work():
        messages = [
            {"role": "system", "content": _system_prompt(skin)},
            {"role": "user", "content":
             "Say one short in-character line to the user right now."},
        ]
        raw = _call(messages, max_tokens=MIN_TOKEN_BUDGET)
        if not raw:
            _release(kind)
            on_done(None, STATUS_UNAVAILABLE)
            return
        on_done(_extract_memory(raw), STATUS_OK)

    _run_worker(work, on_crash=lambda: _release(kind))


def maybe_context_line(skin, context, on_done) -> bool:
    """Ask for one line about the focused window. True if the request started.

    Returns False (without calling `on_done`) when the idle pool is throttled
    or the AI is off, so the caller can fall back to its canned line instead of
    waiting for a reply that will never come.

    Only ever receives a window title and process name -- never pixels. That
    keeps it cheap, and keeps it outside the screenshot consent path.
    """
    if not ai_enabled():
        return False
    if not _reserve("idle"):
        return False

    def work():
        messages = [
            {"role": "system", "content": _system_prompt(skin)},
            {"role": "user", "content":
             "The user is looking at %s. Say one short in-character line about "
             "it, without quoting the whole title." % (context or "their desktop")},
        ]
        raw = _call(messages, max_tokens=MIN_TOKEN_BUDGET)
        if not raw:
            _release("idle")
            on_done(None, STATUS_UNAVAILABLE)
            return
        on_done(_extract_memory(raw), STATUS_OK)

    _run_worker(work, on_crash=lambda: _release("idle"))
    return True


def request_screenshot_comment(skin, image_b64, on_done, manual=False):
    """Ask for a reaction to an already-captured screenshot.

    The caller must have won a slot via screenshot_slot_ok() (or
    reserve_forced_screenshot()) and must call record_capture_attempt() once
    the capture actually happened.

    `manual` is a user-initiated capture from the menu: it works even when the
    automatic screenshot feature is switched off, because the user asked for it
    directly. The privacy blocklist and the OCR filter still apply -- those are
    enforced in screen_capture before any pixels are sent.
    """
    scfg = CONFIG.get("screenshots", {})
    if not ai_enabled() or (not scfg.get("enabled", False) and not manual):
        on_done(None, STATUS_UNAVAILABLE)
        return

    def work():
        sys_prompt = _system_prompt(skin) + (
            "\nYou can see a screenshot of the user's screen. React to something specific "
            "and visible, in one short in-character sentence. Never say the words "
            "screenshot or screen."
        )
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": [
                {"type": "text", "text":
                 "What's the user up to? One short in-character reaction."},
                {"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + image_b64}},
            ]},
        ]
        raw = _call(messages, max_tokens=80)
        if not raw:
            _release("screenshot")
            on_done(None, STATUS_UNAVAILABLE)
            return
        on_done(_extract_memory(raw), STATUS_OK)

    _run_worker(work, on_crash=lambda: _release("screenshot"))
