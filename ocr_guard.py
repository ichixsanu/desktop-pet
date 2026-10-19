"""OCR content filter for screen captures.

A blocklist can only black out windows it can *recognise*: an app the user
forgot to list, a password manager's unlocked vault, a terminal echoing a
token, a browser tab showing a recovery phrase. This module is the second line
of defence. It runs the already-redacted capture through a local OCR pass --
nothing leaves the machine for this -- and refuses to hand the image to the
model when the text on screen looks like something that should not be
uploaded: password fields, recovery phrases, API keys, card numbers, IBANs.

Design rules, in order of importance:

1. Nothing sensitive is ever written down. A match is reported by *rule name*
   ("card number", "api token"), never by the matched text, because the whole
   point is that this text must not leave the machine -- including into
   pet.log.
2. Fail closed by default. If the filter is on and cannot run (no tesseract,
   timeout, unreadable image) the capture is discarded rather than sent
   unscanned. `ocr.fail_closed: false` opts out.
3. Cheap and local. One subprocess, downscaled input, hard timeout, and it
   runs on the screenshot worker thread so the pet never stutters.
4. Tunable from companion_config.json: engine, language, extra keywords,
   per-line exemptions, and the full rule lists.

Config (companion_config.json, `screenshots.ocr`):

    {
      "enabled": true,
      "engine": "auto",          // auto | tesseract | none
      "fail_closed": true,
      "max_width": 1600,
      "timeout_seconds": 6,
      "languages": "eng",
      "psm": 3,
      "extra_keywords": [],
      "allowed_keywords": [],    // lines containing these skip keyword rules
      "keywords": null,          // null = built-in list, [] = none
      "patterns": null
    }

Run `python3 ocr_guard.py` for a quick self-check of the engine on this box.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

ENGINE_AUTO = "auto"
ENGINE_TESSERACT = "tesseract"
ENGINE_NONE = "none"

# Bumped when the built-in rule lists change, so a stale config can be noticed.
RULES_VERSION = 1

MAX_STDOUT_BYTES = 4 * 1024 * 1024


class Verdict(NamedTuple):
    """Outcome of a scan.

    `ok` False means "do not use this image". `reason` is safe to show and to
    log; `hits` are rule names only, never matched text.
    """
    ok: bool
    reason: str
    hits: Tuple[str, ...] = ()
    text_len: int = 0


# =====================================================================
# Built-in rules
# =====================================================================

# Phrases that are strong enough on their own. Deliberately not including
# bare "password"/"secret"/"token": those appear in code and documentation all
# the time, and a false positive silently costs the user every capture. The
# context rule below catches them where they matter -- next to a value.
STRONG_KEYWORDS = [
    "seed phrase",
    "recovery phrase",
    "mnemonic phrase",
    "private key",
    "api key",
    "api token",
    "access token",
    "refresh token",
    "auth token",
    "bearer token",
    "session token",
    "client secret",
    "one-time code",
    "one time code",
    "one-time password",
    "one time password",
    "verification code",
    "authenticator code",
    "2fa code",
    "two-factor code",
    "recovery code",
    "backup code",
    "security code",
    "cvv",
    "cvc",
    "card number",
    "credit card",
    "debit card",
    "account number",
    "routing number",
    "sort code",
    "iban",
    "swift code",
    "social security number",
    "ssn",
    "national insurance number",
    "passport number",
]

# "password: hunter2" and friends: the keyword only counts next to a value.
CONTEXT_KEYWORDS = [
    "password", "passphrase", "passwd", "passcode", "pin",
    "secret", "token", "api_key", "apikey", "access_key", "secret_key",
    "private_key", "auth", "credential", "connection string",
    "database_url", "db_password", "master password",
]

# Anything matching these is refused outright. Kept to formats with a fixed,
# recognisable shape so ordinary code and prose do not trip them.
SECRET_PATTERNS: List[Tuple[str, str]] = [
    ("private key block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("OpenAI-style key", r"\bsk-[A-Za-z0-9_\-]{16,}"),
    ("Anthropic-style key", r"\bsk-ant-[A-Za-z0-9_\-]{16,}"),
    ("Groq key", r"\bgsk_[A-Za-z0-9]{16,}"),
    ("Stripe key", r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    ("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    ("GitHub fine-grained token", r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    ("Slack token", r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    ("AWS access key id", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("Google API key", r"\bAIza[0-9A-Za-z_\-]{30,}"),
    ("Google OAuth token", r"\bya29\.[0-9A-Za-z_\-]{20,}"),
    ("SendGrid key", r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}"),
    ("Twilio key", r"\bSK[0-9a-fA-F]{32}\b"),
    ("JSON Web Token", r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\."),
    ("US social security number", r"\b\d{3}-\d{2}-\d{4}\b"),
]

# Checked separately because they need a checksum, not just a shape: a bare
# long number is a build id, a timestamp or an order number far more often
# than it is a card.
CARD_RE = re.compile(r"(?<![\d])(?:\d[ \-]?){13,19}(?![\d])")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")

DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "engine": ENGINE_AUTO,
    "fail_closed": True,
    "max_width": 1600,
    "timeout_seconds": 6,
    "languages": "eng",
    "psm": 3,
    "keywords": None,
    "context_keywords": None,
    "patterns": None,
    "extra_keywords": [],
    "allowed_keywords": [],
}


# =====================================================================
# Config
# =====================================================================

def normalize_config(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Merge user config over the defaults, tolerating anything."""
    out = dict(DEFAULTS)
    if isinstance(cfg, dict):
        for key, value in cfg.items():
            out[key] = value
    if out.get("keywords") is None:
        out["keywords"] = list(STRONG_KEYWORDS)
    if out.get("context_keywords") is None:
        out["context_keywords"] = list(CONTEXT_KEYWORDS)
    if out.get("patterns") is None:
        out["patterns"] = list(SECRET_PATTERNS)
    out["extra_keywords"] = [str(k) for k in (out.get("extra_keywords") or []) if str(k).strip()]
    out["allowed_keywords"] = [str(k) for k in (out.get("allowed_keywords") or []) if str(k).strip()]
    try:
        width = int(out.get("max_width", 1600))
    except (TypeError, ValueError):
        width = 1600
    out["max_width"] = 1600 if width <= 0 else max(320, width)
    try:
        out["timeout_seconds"] = max(1.0, min(30.0, float(out.get("timeout_seconds", 6))))
    except (TypeError, ValueError):
        out["timeout_seconds"] = 6.0
    try:
        out["psm"] = int(out.get("psm", 3))
    except (TypeError, ValueError):
        out["psm"] = 3
    return out


def _keyword_re(phrase: str) -> Optional[re.Pattern]:
    phrase = (phrase or "").strip().lower()
    if not phrase:
        return None
    parts = [re.escape(part) for part in re.split(r"[\s_]+", phrase) if part]
    if not parts:
        return None
    body = r"[\s_\-]*".join(parts)
    return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])", re.IGNORECASE)


def _context_re(word: str) -> Optional[re.Pattern]:
    word = (word or "").strip().lower()
    if not word:
        return None
    parts = [re.escape(part) for part in re.split(r"[\s_]+", word) if part]
    body = r"[\s_\-]*".join(parts)
    # keyword, optional quotes, a separator, then *a value*. A reference to a
    # secret is not a secret: `password = os.environ['PASSWORD']`,
    # `${DB_PASSWORD}`, `getenv("TOKEN")` and friends are how code is written,
    # and blocking every screenshot of a settings file would make the filter
    # useless. `password: hunter2` still matches.
    reference = (r"(?!(?:os\.|process\.env|getenv\s*\(|\$\{?[A-Za-z_]|"
                 r"env\[|<|None\b|null\b|nil\b|undefined\b|\.\.\.|\[REDACTED\]))")
    return re.compile(
        r"(?<![a-z0-9])" + body + r"(?![a-z0-9])[\"']?\s*(?:[:=]|->|=>|\bis\b)"
        r"\s*[\"']?" + reference + r"\S",
        re.IGNORECASE)


def build_rules(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, List]:
    """Compile the rule set. Pure; exposed for tests and for the menu."""
    cfg = normalize_config(cfg)

    def compiled(phrases, name_for, builder=_keyword_re):
        out = []
        for phrase in phrases:
            regex = builder(phrase)
            if regex is not None:
                out.append((regex, name_for(phrase)))
        return out

    keyword_res = compiled(cfg["keywords"], lambda k: "keyword: %s" % k)
    context_res = compiled(cfg["context_keywords"], lambda k: "%s field" % k,
                           builder=_context_re)
    extra_res = compiled(cfg["extra_keywords"], lambda k: "keyword: %s" % k)
    pattern_res = []
    for entry in cfg["patterns"]:
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            name, pattern = str(entry[0]), str(entry[1])
        else:
            name, pattern = str(entry), str(entry)
        try:
            pattern_res.append((re.compile(pattern, re.IGNORECASE), name))
        except re.error:
            continue
    return {
        "keywords": keyword_res,
        "context": context_res,
        "patterns": pattern_res,
        "extra": extra_res,
        "allowed": [a.lower() for a in cfg["allowed_keywords"]],
    }


# =====================================================================
# Matching (pure)
# =====================================================================

def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = ord(char) - 48
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return digits and total % 10 == 0


def _iban_ok(candidate: str) -> bool:
    rearranged = candidate[4:] + candidate[:4]
    try:
        numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    except ValueError:
        return False
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


def _line_is_allowed(line: str, allowed: Sequence[str]) -> bool:
    if not allowed:
        return False
    lowered = line.lower()
    return any(entry in lowered for entry in allowed)


def scan_text(text: str, cfg: Optional[Dict[str, Any]] = None) -> Verdict:
    """Run the rule set over OCR text. Returns a Verdict with rule names only.

    `allowed_keywords` exempts a line from the keyword and context rules (for
    documenting a password field, say). It never exempts anything from the
    pattern rules: a real key or card number on an allow-listed line is still
    a real key or card number.
    """
    cfg = normalize_config(cfg)
    rules = build_rules(cfg)
    text = text or ""
    hits: List[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not _line_is_allowed(line, rules["allowed"]):
            for regex, name in rules["keywords"] + rules["extra"] + rules["context"]:
                if regex.search(line):
                    hits.append(name)
        for regex, name in rules["patterns"]:
            if regex.search(line):
                hits.append(name)
        for match in CARD_RE.finditer(line):
            digits = re.sub(r"\D", "", match.group(0))
            if 13 <= len(digits) <= 19 and _luhn_ok(digits):
                hits.append("card number")
                break
        for match in IBAN_RE.finditer(line):
            if _iban_ok(match.group(0).upper()):
                hits.append("IBAN")
                break

    unique = tuple(sorted(set(hits)))
    if unique:
        shown = list(unique[:3])
        reason = "sensitive text on screen (%s%s)" % (
            ", ".join(shown), ", ..." if len(unique) > 3 else "")
        return Verdict(False, reason, unique, text_len=len(text))
    return Verdict(True, "", (), text_len=len(text))


# =====================================================================
# Engine
# =====================================================================

_engine_lock = threading.Lock()
_engine_cache: Dict[str, Any] = {"checked": False, "path": None, "version": ""}
_no_engine_warned = False


def warn_no_engine_once():
    """One-time stderr note: the filter is on but there is nothing to run.

    Refusing captures is the safe default, but "every screenshot silently does
    nothing" reads as a broken feature, so say exactly why -- once per process,
    and only on stderr, never in the pet's speech or pet.log.
    """
    global _no_engine_warned
    if _no_engine_warned:
        return
    _no_engine_warned = True
    try:
        sys.stderr.write(
            "[ocr_guard] the screenshot OCR filter is enabled but tesseract is "
            "not installed, so captures are being refused. Install tesseract "
            "(apt install tesseract-ocr, pacman -S tesseract) or set "
            "screenshots.ocr.enabled=false in companion_config.json\n")
        sys.stderr.flush()
    except Exception:
        pass


def _version_of(path: str) -> str:
    try:
        out = subprocess.run([path, "--version"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=5)
        first = out.stdout.decode("utf-8", "replace").splitlines()
        return first[0].strip() if first else ""
    except Exception:
        return ""


def find_engine(engine: str = ENGINE_AUTO) -> Optional[str]:
    """Path to the OCR binary, or None. `none` disables the filter engine."""
    if (engine or ENGINE_AUTO) == ENGINE_NONE:
        return None
    with _engine_lock:
        if not _engine_cache["checked"]:
            _engine_cache["checked"] = True
            path = shutil.which("tesseract")
            _engine_cache["path"] = path
            _engine_cache["version"] = _version_of(path) if path else ""
        return _engine_cache["path"]


def engine_status(engine: str = ENGINE_AUTO) -> Dict[str, str]:
    """{'name': ..., 'path': ...} for diagnostics and the menu."""
    if (engine or ENGINE_AUTO) == ENGINE_NONE:
        return {"name": "off", "path": ""}
    path = find_engine(engine)
    if not path:
        return {"name": "unavailable", "path": ""}
    with _engine_lock:
        version = _engine_cache.get("version") or ""
    return {"name": version or "tesseract", "path": path}


def reset_engine_cache():
    """For tests, and for a menu action after installing tesseract."""
    with _engine_lock:
        _engine_cache["checked"] = False
        _engine_cache["path"] = None
        _engine_cache["version"] = ""


def available(cfg: Optional[Dict[str, Any]] = None) -> bool:
    cfg = normalize_config(cfg)
    return bool(cfg.get("enabled")) and find_engine(str(cfg.get("engine"))) is not None


# =====================================================================
# Image scan
# =====================================================================

def _to_png_bytes(image, max_width: int) -> Optional[bytes]:
    """Encode a QImage for OCR, downscaled. GUI thread not required."""
    try:
        from PyQt5.QtCore import QBuffer, QIODevice, Qt
    except Exception:
        return None
    if image is None:
        return None
    try:
        if image.isNull():
            return None
    except Exception:
        return None

    prepared = image
    try:
        if max_width and image.width() > max_width:
            prepared = image.scaledToWidth(max_width, Qt.SmoothTransformation)
    except Exception:
        prepared = image

    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    try:
        if not prepared.save(buffer, "PNG"):
            return None
        return bytes(buffer.data())
    except Exception:
        return None
    finally:
        try:
            buffer.close()
        except Exception:
            pass


def run_engine(png_bytes: bytes, cfg: Dict[str, Any], engine_path: str) -> Optional[str]:
    """OCR bytes -> text, or None on any failure. Never raises."""
    if not png_bytes or not engine_path:
        return None
    languages = str(cfg.get("languages") or "eng")
    cmd = [engine_path, "stdin", "stdout", "--psm", str(cfg.get("psm", 3)),
           "-l", languages]
    try:
        proc = subprocess.run(
            cmd, input=png_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=float(cfg.get("timeout_seconds", 6)))
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    data = proc.stdout[:MAX_STDOUT_BYTES]
    return data.decode("utf-8", "replace")


def scan_image(image, cfg: Optional[Dict[str, Any]] = None) -> Verdict:
    """OCR a QImage and apply the rules. Safe off the GUI thread."""
    cfg = normalize_config(cfg)
    if not cfg.get("enabled", True):
        return Verdict(True, "")

    engine_path = find_engine(str(cfg.get("engine")))
    fail_closed = bool(cfg.get("fail_closed", True))
    if engine_path is None:
        if fail_closed:
            warn_no_engine_once()
            return Verdict(False, "OCR filter is on but no OCR engine is installed")
        warn_no_engine_once()
        return Verdict(True, "")

    png = _to_png_bytes(image, cfg.get("max_width"))
    if png is None:
        if fail_closed:
            return Verdict(False, "the capture could not be prepared for the OCR filter")
        return Verdict(True, "")

    text = run_engine(png, cfg, engine_path)
    if text is None:
        if fail_closed:
            return Verdict(False, "the OCR filter could not read the capture")
        return Verdict(True, "")
    return scan_text(text, cfg)


def describe(cfg: Optional[Dict[str, Any]] = None) -> str:
    """One line for the context menu."""
    cfg = normalize_config(cfg)
    if not cfg.get("enabled", True):
        return "off"
    status = engine_status(str(cfg.get("engine")))
    rules = build_rules(cfg)
    count = len(rules["keywords"]) + len(rules["extra"]) + len(rules["context"]) + len(rules["patterns"])
    mode = "fail closed" if cfg.get("fail_closed", True) else "fail open"
    return "%s, %d rules, %s" % (status["name"] or "no engine", count, mode)


if __name__ == "__main__":  # pragma: no cover - manual diagnostic
    print("engine :", engine_status())
    print("rules  :", describe())
    sample = "Password: hunter2\ncard 4111 1111 1111 1111\nnothing here\n"
    print("sample :", scan_text(sample))
