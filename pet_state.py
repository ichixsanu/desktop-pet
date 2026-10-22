"""Persistent state for the desktop pet.

The pet used to forget everything on restart: same skin, same scale, same spot
on the floor, full energy, as if it had never existed. This module keeps a small
JSON file so it comes back where it left off.

Deliberately conservative:
- Every field is validated on load. A corrupt or hand-edited file degrades to
  defaults instead of crashing the pet.
- Writes are atomic (temp file + rename) and rate-limited, because the pet
  saves on a timer and a half-written file that loads as "empty" would
  silently reset everything.
- Position is only restored if it is still on a connected display, so unplugging
  a monitor between sessions cannot strand the pet off-screen.
"""

import json
import os
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(BASE_DIR, "pet_state.json")

SAVE_INTERVAL = 30.0        # seconds between automatic saves
ENERGY_DECAY_PER_HOUR = 8.0  # energy lost per hour away, capped on load
GRACE_PERIOD_HOURS = 0.25     # a quick restart costs nothing

DEFAULTS = {
    "version": 1,
    "skin": None,
    "scale": 2,
    "energy": 100.0,
    "x": None,
    "y": None,
    "display": None,
    "climb_enabled": True,
    "allow_jump": True,
    "allow_chase": True,
    "click_through": False,
    "seconds_alive": 0.0,
    "milestone_days": 0,
    "treats_given": 0,
    "last_seen": 0.0,
    "pet_count": 0,
}


def _clamp(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return max(low, min(high, value))


def _as_bool(value, default):
    """Interpret a hand-edited value: bool("no") is True, which is not useful."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "on", "1"):
            return True
        if lowered in ("false", "no", "off", "0"):
            return False
    return default


class PetState:
    """Load/save the pet's persistent state."""

    def __init__(self, path=None, save_interval=SAVE_INTERVAL,
                 energy_decay_per_hour=ENERGY_DECAY_PER_HOUR):
        self.path = path or DEFAULT_PATH
        self.save_interval = save_interval
        # Configurable now: `state.energy_decay_per_hour` sat in the config
        # file doing nothing while the constant below was what actually ran.
        try:
            self.energy_decay_per_hour = max(
                0.0, float(energy_decay_per_hour))
        except (TypeError, ValueError):
            self.energy_decay_per_hour = ENERGY_DECAY_PER_HOUR
        self.data = dict(DEFAULTS)
        self.lifetime_base = 0.0
        self._last_save = 0.0
        self._dirty = False

    # ---- loading -------------------------------------------------------

    def load(self):
        """Read the file, falling back to defaults for anything invalid."""
        self.data = dict(DEFAULTS)
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
        except (OSError, ValueError):
            return self.data

        if not isinstance(stored, dict):
            return self.data

        data = self.data
        if isinstance(stored.get("skin"), str):
            data["skin"] = stored["skin"]
        scale = _clamp(stored.get("scale"), 1, 8)
        data["scale"] = int(scale) if scale is not None else DEFAULTS["scale"]
        energy = _clamp(stored.get("energy"), 0.0, 100.0)
        data["energy"] = DEFAULTS["energy"] if energy is None else energy
        data["x"] = _clamp(stored.get("x"), -100000.0, 100000.0)
        data["y"] = _clamp(stored.get("y"), -100000.0, 100000.0)
        display = stored.get("display")
        data["display"] = str(display)[:120] if isinstance(display, str) and display else None
        data["climb_enabled"] = _as_bool(stored.get("climb_enabled"), True)
        data["allow_jump"] = _as_bool(stored.get("allow_jump"), True)
        data["allow_chase"] = _as_bool(stored.get("allow_chase"), True)
        data["click_through"] = _as_bool(stored.get("click_through"), False)
        data["seconds_alive"] = _clamp(stored.get("seconds_alive"), 0.0, 1e9) or 0.0
        milestone = _clamp(stored.get("milestone_days"), 0, 1e6)
        data["milestone_days"] = int(milestone) if milestone is not None else 0
        treats = _clamp(stored.get("treats_given"), 0, 1e9)
        data["treats_given"] = int(treats) if treats is not None else 0
        data["last_seen"] = _clamp(stored.get("last_seen"), 0.0, 1e12) or 0.0
        count = _clamp(stored.get("pet_count"), 0, 1e9)
        data["pet_count"] = int(count) if count is not None else 0
        self.lifetime_base = float(data["seconds_alive"])
        return data

    def hours_away(self, now=None):
        """Hours since the pet was last running, or 0 if never."""
        last = self.data.get("last_seen") or 0.0
        if last <= 0:
            return 0.0
        return max(0.0, ((now or time.time()) - last) / 3600.0)

    def rested_energy(self, now=None):
        """Energy on startup: whatever was saved, minus time spent away.

        Short absences are free, so restarting the app repeatedly does not
        grind the pet down, and long ones are capped so coming back after a
        fortnight does not leave it permanently exhausted.
        """
        away = self.hours_away(now)
        if away <= GRACE_PERIOD_HOURS:
            return max(0.0, min(100.0, self.data.get("energy") or 0.0))
        away = min(away - GRACE_PERIOD_HOURS, 8.0)
        decay = away * self.energy_decay_per_hour
        return max(0.0, min(100.0, (self.data.get("energy") or 100.0) - decay))

    def total_seconds_alive(self, session_seconds=0.0):
        """Lifetime seconds alive, this session included.

        `seconds_alive` used to be *overwritten* with the current session's
        uptime on every save, so the counter reset to a few seconds on every
        restart and never added up to anything. The lifetime total is pinned
        when the file is loaded and only the running session is added on top,
        so repeated saves cannot double-count.
        """
        try:
            session = max(0.0, float(session_seconds))
        except (TypeError, ValueError):
            session = 0.0
        return min(1e9, self.lifetime_base + session)

    # ---- saving --------------------------------------------------------

    def touch(self, **fields):
        """Record current values; nothing is written until save() runs."""
        for key, value in fields.items():
            if key in DEFAULTS:
                self.data[key] = value
        self._dirty = True

    def save(self, force=False, now=None):
        """Write to disk, at most once per save_interval unless forced."""
        now = now or time.time()
        if not force and (now - self._last_save) < self.save_interval:
            return False
        self.data["last_seen"] = now
        self._dirty = False
        self._last_save = now
        self._write()
        return True

    def _write(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, indent=2)
            try:
                # This file records where someone was and when. It has no
                # business being world-readable.
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def forget(self):
        """Delete the saved state (used by the context menu)."""
        self.data = dict(DEFAULTS)
        self.lifetime_base = 0.0
        try:
            os.unlink(self.path)
        except OSError:
            pass


def find_focus_state(paths):
    """First readable focus/pomodoro state file among `paths`.

    Expected shape, all fields optional:
        {"mode": "focus" | "break", "remaining_minutes": 24, "label": "..."}

    Returns None when nothing is there, so the pet simply behaves normally.
    """
    for path in paths or ():
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        mode = str(data.get("mode", "")).strip().lower()
        if mode not in ("focus", "break"):
            continue
        return {
            "mode": mode,
            "remaining_minutes": _clamp(data.get("remaining_minutes"), 0.0, 600.0),
            "label": str(data.get("label", ""))[:60],
        }
    return None
