"""Focus / pomodoro awareness.

The pet stays out of the way during a focus block and perks up during a break.
It does not know anything about your timer: it reads a small JSON file that
something else writes, and ignores it when the file is absent.

    {"mode": "focus", "remaining_minutes": 24, "label": "writing docs"}

`mode` is "focus" or "break". Every field is optional. A `label` is shown by the
context menu so you can tell the pet is tracking the right thing.

Configure the paths in companion_config.json:

    "focus": {
      "enabled": true,
      "state_files": ["~/.focus.json", "~/.config/focus/state.json"],
      "poll_seconds": 5
    }

When nothing is readable, `mode` is None and the pet behaves normally.
"""

import json
import os
import time

from pet_state import find_focus_state

MODE_NONE = None
MODE_FOCUS = "focus"
MODE_BREAK = "break"

DEFAULT_PATHS = [
    os.path.expanduser("~/.focus.json"),
    os.path.expanduser("~/.config/focus/state.json"),
]


class FocusWatcher:
    """Polls a focus-state file and reports when the mode changes."""

    def __init__(self, paths=None, poll_seconds=5.0):
        # None means "use the defaults"; an explicit empty list means "no
        # focus tracking", and must not silently fall back to the defaults.
        chosen = DEFAULT_PATHS if paths is None else paths
        self.paths = [os.path.expanduser(p) for p in chosen if p]
        # 0 means "check on every poll", which is what the tests and anyone
        # driving the pet programmatically want.
        self.poll_seconds = max(0.0, float(poll_seconds))
        self.mode = MODE_NONE
        self.label = ""
        self.remaining = None
        self._last_poll = 0.0
        self._started_at = None

    def configured(self):
        return bool(self.paths)

    def poll(self, now=None, force=False):
        """Re-read the file if it is due. Returns the current mode."""
        now = now if now is not None else time.monotonic()
        if not force and (now - self._last_poll) < self.poll_seconds:
            return self.mode
        self._last_poll = now
        state = find_focus_state(self.paths)
        self.mode = state["mode"] if state else MODE_NONE
        self.label = state["label"] if state else ""
        self.remaining = state["remaining_minutes"] if state else None
        return self.mode

    def transition(self, previous):
        """What just happened: 'started', 'ended', 'break', or None."""
        if previous == MODE_FOCUS and self.mode != MODE_FOCUS:
            return "ended"
        if previous != MODE_FOCUS and self.mode == MODE_FOCUS:
            return "started"
        if self.mode == MODE_BREAK and previous != MODE_BREAK:
            return "break"
        return None

    def is_focus(self):
        return self.mode == MODE_FOCUS

    def describe(self):
        if self.mode == MODE_FOCUS:
            return "focus" + (": %s" % self.label if self.label else "")
        if self.mode == MODE_BREAK:
            return "break" + (": %s" % self.label if self.label else "")
        return "off"


def write_state(path, mode, remaining_minutes=None, label=""):
    """Helper for whatever drives your timer (and for the tests)."""
    payload = {"mode": mode}
    if remaining_minutes is not None:
        payload["remaining_minutes"] = remaining_minutes
    if label:
        payload["label"] = label
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(tmp, path)
