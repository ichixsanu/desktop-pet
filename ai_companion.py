import os
import re
import json
import time
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "companion_config.json")
MEMORY_PATH = os.path.join(BASE_DIR, "companion_memory.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")

CIRCUIT_COOLDOWN = 30 * 60


# ---- .env ----
def _load_env(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


_load_env(ENV_PATH)

try:
    import groq
    from groq import Groq
    _HAS_GROQ = True
except Exception:
    _HAS_GROQ = False

MODEL = os.environ.get("MODEL", "qwen/qwen3.6-27b")
_KEYS = [v for k, v in sorted(os.environ.items())
         if re.fullmatch(r"GROQ_API_KEY\d*", k) and v]
_clients = [Groq(api_key=k) for k in _KEYS] if _HAS_GROQ else []


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
            "min_seconds_between": {"idle": 45, "screenshot": 900},
            "max_per_hour": {"idle": 6, "screenshot": 4},
        },
        "screenshots": {
            "enabled": False,
            "interval_minutes": 15,
            "max_per_day": 40,
            "require_recent_activity_minutes": 3,
            "blocklist": [],
            "jpeg_quality": 70,
        },
        "memory": {"enabled": True, "max_facts": 20},
    }


def _load_config():
    cfg = _default_config()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            for k, v in user_cfg.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception:
            pass
    return cfg


CONFIG = _load_config()

_state = {"key_idx": 0, "dead_keys": set(), "disabled_until": 0}
_sent_log = {"idle": [], "screenshot": []}
_daily = {"date": "", "count": 0}
_lock = threading.Lock()


def ai_enabled():
    return bool(CONFIG.get("ai_enabled", True) and _HAS_GROQ and _clients)


def _system_prompt(skin):
    per = CONFIG.get("companions", {}).get(skin, {})
    prompt = per.get("system_prompt") or CONFIG.get("default_system_prompt", "")
    mem = _load_memory()
    if mem:
        prompt += "\nThings you remember about the user: " + "; ".join(mem[-8:])
    return prompt


def _load_memory():
    if not CONFIG.get("memory", {}).get("enabled", True):
        return []
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _remember(fact):
    if not CONFIG.get("memory", {}).get("enabled", True):
        return
    fact = fact.strip()
    if not fact:
        return
    cap = CONFIG.get("memory", {}).get("max_facts", 20)
    mem = _load_memory()
    mem.append(fact)
    mem = mem[-cap:]
    try:
        with open(MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump(mem, f)
    except Exception:
        pass


def _extract_memory(text):
    if not text:
        return text
    kept = []
    for line in text.strip().splitlines():
        if line.strip().upper().startswith("MEMORY:"):
            _remember(line.split(":", 1)[1])
        else:
            kept.append(line)
    out = " ".join(" ".join(kept).split())
    return out or None


# ---- rate limiting ----
def _rate_ok(kind):
    cfg = CONFIG.get("rate_limits", {})
    min_gap = cfg.get("min_seconds_between", {}).get(kind, 60)
    cap = cfg.get("max_per_hour", {}).get(kind, 6)
    now = time.time()
    with _lock:
        log = _sent_log[kind]
        log[:] = [t for t in log if now - t < 3600]
        if log and now - log[-1] < min_gap:
            return False
        if len(log) >= cap:
            return False
        return True


def _mark_sent(kind):
    with _lock:
        _sent_log[kind].append(time.time())


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
        _daily["count"] += 1


# ---- Groq call w/ key rotation + circuit breaker ----
def _call(messages, max_tokens=50):
    if not ai_enabled():
        return None
    with _lock:
        if time.time() < _state["disabled_until"]:
            return None
    n = len(_clients)
    for offset in range(n):
        idx = (_state["key_idx"] + offset) % n
        if idx in _state["dead_keys"]:
            continue
        try:
            resp = _clients[idx].chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.9,
                max_completion_tokens=max_tokens,
                top_p=1,
                stream=False,
            )
            with _lock:
                _state["key_idx"] = idx
                _state["disabled_until"] = 0
            return resp.choices[0].message.content
        except groq.AuthenticationError:
            _state["dead_keys"].add(idx)
            continue
        except groq.RateLimitError:
            continue
        except Exception:
            continue
    with _lock:
        _state["disabled_until"] = time.time() + CIRCUIT_COOLDOWN
    return None


def maybe_idle_line(skin, on_done):
    if not ai_enabled() or not _rate_ok("idle"):
        on_done(None)
        return

    def work():
        messages = [
            {"role": "system", "content": _system_prompt(skin)},
            {"role": "user", "content": "Say one short in-character line to the user right now."},
        ]
        text = _extract_memory(_call(messages, max_tokens=40))
        if text:
            _mark_sent("idle")
        on_done(text)

    threading.Thread(target=work, daemon=True).start()


def request_screenshot_comment(skin, image_b64, on_done):
    scfg = CONFIG.get("screenshots", {})
    if not ai_enabled() or not scfg.get("enabled", False):
        on_done(None)
        return
    if not _rate_ok("screenshot") or not screenshot_daily_ok():
        on_done(None)
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
                {"type": "text", "text": "What's the user up to? One short in-character reaction."},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_b64}},
            ]},
        ]
        text = _extract_memory(_call(messages, max_tokens=60))
        if text:
            _mark_sent("screenshot")
            _screenshot_daily_mark()
        on_done(text)

    threading.Thread(target=work, daemon=True).start()


def screenshot_settings():
    return CONFIG.get("screenshots", {})
