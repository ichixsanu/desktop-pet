"""Desktop Pet.

A pixel buddy that lives on the desktop: walks the taskbar, perches on window
titlebars, climbs window frames, reacts to what you are doing, and optionally
talks for itself through Groq.

Modules:
    ai_companion        model calls, rate limits, memory, screenshot policy
    window_tracker      OS window/ledge/edge geometry (cached, thread-safe)
    screen_capture      pixel grabbing + blocklist redaction
    companion_dialogue  every canned line, for every companion

Behaviour worth knowing about:
- One QTimer drives everything at 20 FPS. `game_loop` is the only writer of
  the pet's position, and every Qt slot is exception-guarded: PyQt5 turns an
  unhandled exception in a slot into qFatal()/abort(), so a bad ledge must not
  be able to take the process down.
- The pet works in Qt *logical* pixels. OS window APIs report native pixels,
  so `window_tracker` is told the display's devicePixelRatio once and does the
  conversion.
- All OS window work happens on a background poller thread. Nothing in the
  game loop touches the OS.
"""

import functools
import math
import os
import random
import sys
import threading
import time
import traceback

# HiDPI attributes must be set before QApplication exists, so this import has
# to stay above main().
from PyQt5.QtCore import Qt, QTimer, QPoint, QObject, pyqtSignal
from PyQt5.QtGui import (QPainter, QPixmap, QColor, QFont, QCursor,
                         QTransform, QFontMetrics, QPolygon, QFontDatabase)
from PyQt5.QtWidgets import QApplication, QWidget, QMenu, QAction

import ai_companion
import pet_state
import screen_capture
from focus_timer import FocusWatcher, MODE_FOCUS

try:
    import window_tracker
except Exception:
    window_tracker = None

try:
    import companion_dialogue
except Exception:
    companion_dialogue = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SKINS_DIR = os.path.join(BASE_DIR, "skins")
LOG_PATH = os.path.join(BASE_DIR, "pet.log")

# The pet's own window must never be a ledge for the pet to stand on.
PET_WINDOW_TITLE = "desktop-pet-overlay"

# Sprite state basenames, in load order. Each skin ships a subset.
STATE_FILES = [
    "sit", "idle", "blink", "groom", "spook", "stalk", "walk",
    "run", "fly", "swat", "pat", "sleep", "climb", "drag",
]

# ---- Animation: ticks between frame advances (main timer is 50ms = 20 FPS)
FRAME_SPEED = {
    "SIT": 12, "IDLE": 12, "WALK": 6, "RUN": 4, "SLEEP": 15, "GROOM": 8,
    "STALK": 7, "BLINK": 5, "SWAT": 4, "CLIMB": 5, "DRAG": 6, "FALL": 4,
    "PERCH": 12, "PAT": 3, "SPOOK": 4, "JUMP": 5, "POUNCE": 3, "CHASE": 4,
}

# ---- State durations, in ticks (20 ticks = 1s)
STATE_MIN_DURATION = {
    "SIT": 60, "IDLE": 60, "WALK": 40, "GROOM": 60, "SLEEP": 200,
    "STALK": 60, "BLINK": 6, "SWAT": 20, "PERCH": 80,
}
STATE_MAX_DURATION = {
    "SIT": 160, "IDLE": 160, "WALK": 100, "GROOM": 100, "SLEEP": 300,
    "STALK": 120, "RUN": 90, "PERCH": 200,
}

# Transitions are only rolled on this interval, so the pet is calm rather than
# twitchy.
TRANSITION_EVAL_INTERVAL = 40

# Physics
GRAVITY = 0.8          # px/tick^2
TERMINAL_VEL = 12.0    # px/tick
CLIMB_SPEED = 2.5      # px/tick upward (50 px/s)
CLIMB_GRACE_TICKS = 30  # added to the computed budget before giving up
JUMP_VELOCITY = 7.5    # px/tick upward when leaping off something
CHASE_SPEED = 3.4      # px/tick while chasing the cursor

# Energy: drained by exertion, restored by rest. Drives the pet's mood and how
# likely it is to nap instead of playing.
ENERGY_DRAIN = {
    "WALK": 0.02, "STALK": 0.09, "RUN": 0.16, "CHASE": 0.18, "CLIMB": 0.07,
    "JUMP": 0.12, "POUNCE": 0.14, "SWAT": 0.05, "GROOM": 0.01,
}
ENERGY_GAIN_IDLE = 0.05     # sitting around
ENERGY_GAIN_SLEEP = 0.55    # asleep
ENERGY_GAIN_PET = 15.0      # being petted
ENERGY_GAIN_WAKE = 40.0     # waking up startled

MOOD_SLEEPY_MAX = 30.0   # below this energy: sleepy
MOOD_HAPPY_MIN = 70.0    # above this energy and recently petted: happy

# Ticks between polls of the focused window (5s) and between unsolicited
# contextual lines (30s).
FOCUS_POLL_TICKS = 100
CONTEXT_CHECK_INTERVAL = 600
SAVE_INTERVAL_TICKS = 600   # 30s at 20 FPS
# A context check only counts as activity if the focused window actually
# changed, otherwise the "is anyone there" gate is satisfied forever.
CURSOR_ACTIVITY_PX = 3

SCALE_PRESETS = {
    "1x (Small)": 1,
    "2x (Medium)": 2,
    "3x (Large)": 3,
    "4x (Huge)": 4,
}

# FSM states that count as "exertion" for the purposes of chattiness.
CALM_STATES = ("SIT", "IDLE", "SLEEP", "PERCH")

# ---- Speech bubble
SPEECH_FONT_FAMILY = "Consolas"
SPEECH_FONT_SIZE = 9
SPEECH_MAX_LINES = 3
SPEECH_PADDING_X = 10
SPEECH_PADDING_Y = 6
SPEECH_BUBBLE_RADIUS = 6
SPEECH_TAIL_H = 4
SPEECH_MIN_WIDTH = 60
SPEECH_MAX_WIDTH = 220
SPEECH_DISPLAY_TICKS = 80  # 4 seconds
SPEECH_MAX_CHARS = 120


# =====================================================================
# Crash safety
# =====================================================================

_log_lock = threading.Lock()


def log_exception(context=""):
    """Record a handled exception to pet.log.

    PyQt5 aborts the process on an unhandled exception raised inside a slot
    (it calls qFatal), so slots are guarded and anything that still escapes
    gets written down here instead of taking the pet with it.
    """
    text = traceback.format_exc()
    try:
        with _log_lock:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write("[%s] %s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                          context or "exception", text))
    except Exception:
        pass
    if os.environ.get("PET_DEBUG"):
        sys.stderr.write(text)


def guarded(slot):
    """Wrap a Qt slot so a failure logs instead of aborting the process."""
    @functools.wraps(slot)
    def wrapper(self, *args, **kwargs):
        try:
            return slot(self, *args, **kwargs)
        except Exception:
            log_exception("%s.%s" % (type(self).__name__, slot.__name__))
            return None
    return wrapper


# =====================================================================
# System status (cached: /proc reads do not need to happen per quote)
# =====================================================================

STATUS_TTL = 30.0
_status_cache = {"at": 0.0, "mem": None, "batt": None}


def _mem_percent():
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

            stat = MS()
            stat.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.dwMemoryLoad)
        with open("/proc/meminfo") as f:
            data = f.read().splitlines()
        total = int([l for l in data if l.startswith("MemTotal")][0].split()[1])
        avail = int([l for l in data if l.startswith("MemAvailable")][0].split()[1])
        return int(100 * (1 - avail / total))
    except Exception:
        return None


def _battery_percent():
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class SPS(ctypes.Structure):
                _fields_ = [("ACLineStatus", ctypes.c_byte),
                            ("BatteryFlag", ctypes.c_byte),
                            ("BatteryLifePercent", ctypes.c_byte),
                            ("Reserved1", ctypes.c_byte),
                            ("BatteryLifeTime", ctypes.c_ulong),
                            ("BatteryFullLifeTime", ctypes.c_ulong)]

            status = SPS()
            ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))
            return status.BatteryLifePercent if 0 <= status.BatteryLifePercent <= 100 else None
        base = "/sys/class/power_supply"
        for name in os.listdir(base):
            cap_path = os.path.join(base, name, "capacity")
            if os.path.exists(cap_path):
                with open(cap_path) as f:
                    return int(f.read().strip())
    except Exception:
        return None
    return None


def system_status():
    """(mem_percent, battery_percent), recomputed at most every 30s."""
    now = time.monotonic()
    if now - _status_cache["at"] > STATUS_TTL:
        _status_cache["mem"] = _mem_percent()
        _status_cache["batt"] = _battery_percent()
        _status_cache["at"] = now
    return _status_cache["mem"], _status_cache["batt"]


def get_system_status_quote(skin):
    """Fallback line when the model is unavailable or rate-limited.

    Picks a system-state line when something notable is happening, otherwise a
    plain line from the companion's own dialogue table -- which is the single
    source of each companion's voice, shared with the contextual lines.
    """
    mem, batt = system_status()
    event = None
    if batt is not None and batt < 20:
        event = "low_battery"
    elif mem is not None and mem > 85:
        event = "low_memory"
    if event and companion_dialogue is not None:
        return companion_dialogue.get_contextual_quote(skin, event_type=event)
    if companion_dialogue is not None:
        return companion_dialogue.get_contextual_quote(skin, event_type="idle")
    return "..."


# =====================================================================
# Speech bubble layout
# =====================================================================

def _elide(text, font_metrics, max_width):
    """Trim `text` with an ellipsis so it fits `max_width`.

    Never returns empty for non-empty input: a bubble with nothing in it looks
    broken, and a single character wider than the box should still say
    something.
    """
    ellipsis = "..."
    if font_metrics.horizontalAdvance(text) <= max_width:
        return text
    trimmed = text
    while trimmed and font_metrics.horizontalAdvance(trimmed + ellipsis) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed.rstrip() + ellipsis) if trimmed else ellipsis


def _wrap_text(text, font_metrics, max_width, max_lines=SPEECH_MAX_LINES):
    """Word-wrap into at most `max_lines` lines, eliding the overflow.

    The old version rebuilt the final line with `words.index(word)`, which
    finds the *first* occurrence of a word, so any text that repeated a word
    before the cut point lost or duplicated words. This indexes by position.
    """
    words = (text or "").split()
    if not words:
        return [""]

    lines = []
    current = words[0]
    for index in range(1, len(words)):
        word = words[index]
        candidate = current + " " + word
        if font_metrics.horizontalAdvance(candidate) <= max_width:
            current = candidate
            continue
        if len(lines) == max_lines - 1:
            # Last line available: everything left over goes here, elided.
            remainder = " ".join([current] + words[index:])
            lines.append(_elide(remainder, font_metrics, max_width))
            return lines
        lines.append(current)
        current = word

    lines.append(current)
    return lines[:max_lines]


def _compute_bubble_geometry(text, font):
    """(lines, width, height) for a bubble. Height includes the tail."""
    metrics = QFontMetrics(font)
    content_max_w = SPEECH_MAX_WIDTH - 2 * SPEECH_PADDING_X
    lines = _wrap_text(text, metrics, content_max_w)

    widest = max((metrics.horizontalAdvance(line) for line in lines), default=0)
    bubble_w = max(SPEECH_MIN_WIDTH, widest + 2 * SPEECH_PADDING_X)
    bubble_w = min(bubble_w, SPEECH_MAX_WIDTH)

    bubble_h = metrics.height() * len(lines) + 2 * SPEECH_PADDING_Y + SPEECH_TAIL_H
    return lines, bubble_w, bubble_h


def discover_skins():
    """Skin directory names, sorted. Used by the widget and by main()."""
    try:
        found = [d for d in os.listdir(SKINS_DIR)
                 if os.path.isdir(os.path.join(SKINS_DIR, d))
                 and not d.startswith("_")]
        return sorted(found)
    except Exception:
        return []


class AIBridge(QObject):
    """Relays model replies from worker threads back onto the GUI thread."""

    line_ready = pyqtSignal(str, str)  # (text, status)


class DesktopPet(QWidget):
    """Transparent always-on-top widget holding the pet, its FSM and its UI."""

    def __init__(self, skin="cat", scale=2):
        super().__init__()
        self.setWindowTitle(PET_WINDOW_TITLE)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.NoFocus)

        # ---- sprites ----
        self.scale_factor = scale
        self.sprites = {}
        # Frame lists are resolved once per skin (see _build_frame_table) and
        # mirrored copies are cached, rather than rebuilt on every repaint.
        self._frame_table = {}
        self._flipped_cache = {}
        self.sprite_w = 32 * scale
        self.sprite_h = 32 * scale
        self.available_skins = discover_skins()
        self.current_skin = skin if skin in self.available_skins else (
            self.available_skins[0] if self.available_skins else "cat")
        self.load_skin(self.current_skin)
        self.heart_pixmap = self._make_heart()

        # ---- screen geometry ----
        self.screen_rect = (0, 0, 1280, 720)  # absolute, refreshed below
        self.screen_left = 0
        self.screen_top = 0
        self.screen_w = 1280
        self.screen_h = 720
        self.floor_y = 0.0
        self._refresh_screen_geometry()

        # ---- position (float internally, int for move()) ----
        self.x_pos = float(self.screen_left + self.screen_w // 2 - self.sprite_w // 2)
        self.y_pos = self.floor_y

        # ---- physics / FSM ----
        self.vy = 0.0
        self.facing = 1
        self.state = "SIT"
        self.state_timer = 0
        self.tick_count = 0
        self.energy = 100.0
        self.target_x = None
        self.petted_until_tick = None
        self.session_start = time.time()

        # ---- drag ----
        self.dragging = False
        self.drag_offset = QPoint()
        self.drag_start_y = 0.0

        # ---- speech ----
        self.speech_text = ""
        self.speech_lines = []
        self.speech_bubble_w = 0
        self.speech_bubble_h = 0  # total bubble height including tail
        self.speech_timer = 0
        self.speech_below = False  # bubble drawn under the sprite when no room above
        self.speech_font = QFont(SPEECH_FONT_FAMILY, SPEECH_FONT_SIZE, QFont.Bold)

        self.heart_timer = 0

        # ---- skin flags / hover ----
        self.is_ghost = self.current_skin == "ghost"
        self.ghost_hover_y = self.floor_y - 6.0

        # ---- climbing / perching ----
        self.climb_enabled = True
        self.climb_target_edge = None
        self.climb_budget_ticks = 0
        self.current_ledge = None
        # Movement extras, toggled from the menu.
        self.allow_jump = True
        self.allow_chase = True

        # ---- context tracking ----
        self.last_cursor = QCursor.pos()
        self.last_activity_tick = 0
        self.last_window_title = None
        self.last_window_proc = ""

        # ---- AI ----
        self.awaiting_ai = False
        self.ai_deadline = 0
        self.ai_request_kind = "idle"   # 'idle' | 'user' | 'screenshot'
        self.ai_bridge = AIBridge(self)
        self.ai_bridge.line_ready.connect(self._on_ai_line)

        # ---- window tracker ----
        self.tracker = None
        if window_tracker is not None:
            try:
                self.tracker = window_tracker.get_tracker()
                self.tracker.set_coordinate_scale(self._display_scale())
                self.tracker.set_screen_rect(self.screen_rect)
                # Never generate ledges from the pet's own window.
                self.tracker.add_excluded_pid(os.getpid())
                self.tracker.set_ignored_windows(self._behaviour().get("ignore_windows", []))
                self.tracker.start_background()
            except Exception:
                log_exception("tracker init")
                self.tracker = None

        self.interaction = (companion_dialogue.InteractionTracker()
                            if companion_dialogue is not None else None)

        # ---- screenshot state ----
        self._screenshot_inflight = False

        # ---- focus / pomodoro awareness ----
        focus_cfg = self._settings().get("focus", {})
        self.focus = FocusWatcher(
            focus_cfg.get("state_files") or [],
            focus_cfg.get("poll_seconds", 5)) if focus_cfg.get("enabled", True) \
            else FocusWatcher([], 5)
        self.focus.poll(force=True)

        # ---- persistent state ----
        self.state_store = None
        self._restore_state()

        # ---- monitor change handling ----
        app = QApplication.instance()
        if app is not None:
            for signal in ("screenAdded", "screenRemoved", "primaryScreenChanged"):
                try:
                    getattr(app, signal).connect(self._on_screen_change)
                except Exception:
                    pass

        self._sync_widget_geometry()
        self.show()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.game_loop)
        self.timer.start(50)

    # =================================================================
    # Config
    # =================================================================

    @staticmethod
    def _settings():
        return ai_companion.general_settings()

    def _behaviour(self):
        return self._settings().get("behaviour", {})

    # =================================================================
    # Persistent state
    # =================================================================

    def _state_path(self):
        cfg = self._settings().get("state", {})
        name = cfg.get("file") or "pet_state.json"
        return name if os.path.isabs(name) else os.path.join(BASE_DIR, name)

    def _restore_state(self):
        """Come back as we were, minus the energy spent while we were away."""
        cfg = self._settings().get("state", {})
        if not cfg.get("enabled", True):
            return
        try:
            store = pet_state.PetState(
                self._state_path(),
                save_interval=cfg.get("save_interval_seconds", 30))
            data = store.load()
            self.state_store = store

            skin = data.get("skin")
            if skin and skin in self.available_skins and skin != self.current_skin:
                self.load_skin(skin)
            scale = data.get("scale")
            if scale in SCALE_PRESETS.values() and scale != self.scale_factor:
                self.scale_factor = scale
                self.load_skin(self.current_skin)

            self.energy = store.rested_energy()
            self.climb_enabled = bool(data.get("climb_enabled", True))
            self.allow_jump = bool(self._behaviour().get("allow_jump", True))
            self.allow_chase = bool(self._behaviour().get("allow_chase", True))

            data["pet_count"] = (data.get("pet_count") or 0) + 1
            store.touch(pet_count=data["pet_count"])
            store.save(force=True)

            # Only resume a position that still lands on a connected display.
            x, y = data.get("x"), data.get("y")
            if x is not None and y is not None:
                screen = self._screen_for_point(x + self.sprite_w / 2,
                                               y + self.sprite_h / 2)
                if screen is not None and screen.geometry().contains(int(x), int(y)):
                    self.x_pos, self.y_pos = float(x), float(y)
                    self.current_ledge = None
                    self.vy = 0.0
                    self._enter_sit()
                    if not self._is_on_ledge():
                        self.y_pos = self.floor_y
        except Exception:
            log_exception("state restore")

    def _save_state(self, force=False):
        if self.state_store is None:
            return
        try:
            self.state_store.touch(
                skin=self.current_skin, scale=self.scale_factor,
                energy=self.energy, x=self.x_pos, y=self.y_pos,
                climb_enabled=self.climb_enabled,
                seconds_alive=time.time() - self.session_start,
            )
            self.state_store.save(force=force)
        except Exception:
            log_exception("state save")

    def forget_state(self):
        if self.state_store is not None:
            self.state_store.forget()
        self.energy = 100.0

    # =================================================================
    # Screen / monitor geometry
    # =================================================================

    def _display_scale(self):
        """devicePixelRatio of the primary screen, for HiDPI coordinate fixes."""
        try:
            screen = QApplication.primaryScreen()
            return float(screen.devicePixelRatio()) if screen else 1.0
        except Exception:
            return 1.0

    def _screen_for_point(self, x, y):
        """The screen containing a point, else the primary screen."""
        app = QApplication.instance()
        if app is None:
            return None
        for screen in app.screens():
            if screen.geometry().contains(int(x), int(y)):
                return screen
        return app.primaryScreen()

    @guarded
    def _on_screen_change(self, *_args):
        """Monitor plugged, unplugged, or resolution changed."""
        self._refresh_screen_geometry()
        if self.tracker is not None:
            self.tracker.set_coordinate_scale(self._display_scale())
            self.tracker.set_screen_rect(self.screen_rect)
            self.tracker.invalidate_cache()
        # If the pet was left off the visible desktop, bring it back.
        screen = self._screen_for_point(
            self.x_pos + self.sprite_w / 2, self.y_pos + self.sprite_h / 2)
        if screen is not None and not screen.geometry().contains(
                int(self.x_pos + self.sprite_w / 2), int(self.y_pos + self.sprite_h / 2)):
            self._reset_position()
        if self.is_ghost:
            self.ghost_hover_y = self.floor_y - 6.0
        self._sync_widget_geometry()

    def _refresh_screen_geometry(self):
        """Recompute the display box the pet lives in.

        The pet is confined to the screen it currently occupies, not the whole
        virtual desktop, so dragging it to a second monitor keeps working. The
        rect keeps its origin: treating a secondary monitor's coordinates as
        starting at zero is what used to put the pet outside its own floor.
        """
        center_x = int(getattr(self, "x_pos", 0) + self.sprite_w / 2)
        center_y = int(getattr(self, "y_pos", 0) + self.sprite_h / 2)
        screen = self._screen_for_point(center_x, center_y) or QApplication.primaryScreen()
        if screen is None:
            return

        geometry = screen.geometry()
        self.screen_left = geometry.x()
        self.screen_top = geometry.y()
        self.screen_w = geometry.width()
        self.screen_h = geometry.height()
        self.screen_rect = (self.screen_left, self.screen_top,
                            self.screen_left + self.screen_w,
                            self.screen_top + self.screen_h)
        # Stand on top of the taskbar/panel when the platform tells us where
        # the usable area ends, rather than guessing a margin.
        available = screen.availableGeometry()
        floor_bottom = available.y() + available.height()
        self.floor_y = float(floor_bottom - self.sprite_h)

    # =================================================================
    # Asset loading
    # =================================================================

    def _make_heart(self):
        path = os.path.join(SKINS_DIR, "_heart.png")
        if os.path.exists(path):
            return QPixmap(path).scaled(18, 16, Qt.KeepAspectRatio, Qt.FastTransformation)
        return None

    def _load_scaled(self, path):
        pix = QPixmap(path)
        if pix.isNull():
            return pix
        return pix.scaled(pix.width() * self.scale_factor,
                          pix.height() * self.scale_factor,
                          Qt.KeepAspectRatio, Qt.FastTransformation)

    def load_skin(self, skin_name):
        """Load every frame a skin has, and rebuild the frame lookup table."""
        skin_path = os.path.join(SKINS_DIR, skin_name)
        sprites = {}
        if os.path.isdir(skin_path):
            for state in STATE_FILES:
                frames = []
                index = 0
                while True:
                    path = os.path.join(skin_path, "%s_%d.png" % (state, index))
                    if not os.path.exists(path):
                        break
                    pix = self._load_scaled(path)
                    if not pix.isNull():
                        frames.append(pix)
                    index += 1
                if not frames:
                    path = os.path.join(skin_path, "%s.png" % state)
                    if os.path.exists(path):
                        pix = self._load_scaled(path)
                        if not pix.isNull():
                            frames.append(pix)
                if frames:
                    sprites[state] = frames

        self.sprites = sprites
        self.current_skin = skin_name
        self.is_ghost = skin_name == "ghost"
        self._flipped_cache = {}

        for frames in sprites.values():
            if frames:
                self.sprite_w = frames[0].width()
                self.sprite_h = frames[0].height()
                break

        self._build_frame_table()
        self._refresh_screen_geometry()
        if self.is_ghost:
            self.ghost_hover_y = self.floor_y - 6.0

    def _build_frame_table(self):
        """Resolve each FSM state to a concrete frame list, once."""
        sprites = self.sprites
        fallbacks = {
            "SIT":    ["sit", "idle"],
            "IDLE":   ["idle", "sit"],
            "BLINK":  ["blink", "sit", "idle"],
            "GROOM":  ["groom", "spook", "pat", "sit", "idle"],
            "STALK":  ["stalk", "fly", "run", "walk"],
            "WALK":   ["walk", "fly", "sit", "idle"],
            "RUN":    ["run", "fly", "walk"],
            "SWAT":   ["swat", "pat", "sit"],
            "SLEEP":  ["sleep", "sit", "idle"],
            "CLIMB":  ["climb", "walk", "sit"],
            "DRAG":   ["drag", "sit", "idle"],
            "FALL":   ["drag", "climb", "sit", "idle"],
            "PERCH":  ["sit", "idle", "walk"],
            "PAT":    ["pat", "sit", "idle"],
            "SPOOK":  ["spook", "sit", "idle"],
            "JUMP":   ["walk", "stalk", "climb", "sit"],
            "POUNCE": ["swat", "stalk", "walk", "sit"],
            "CHASE":  ["run", "stalk", "walk", "sit"],
        }
        table = {}
        for state, names in fallbacks.items():
            for name in names:
                frames = sprites.get(name)
                if frames:
                    table[state] = frames
                    break
            else:
                table[state] = sprites.get("sit") or sprites.get("idle") or []
        self._frame_table = table

    def get_frames(self):
        return self._frame_table.get(self.state) or []

    def get_current_frame(self):
        """Current frame, mirrored when facing left. No per-call allocation."""
        frames = self.get_frames()
        if not frames:
            return None
        speed = FRAME_SPEED.get(self.state, 6)
        frame = frames[(self.tick_count // speed) % len(frames)]
        if self.facing < 0 and self.state != "CLIMB":
            mirrored = self._flipped_cache.get(self.state)
            if mirrored is None:
                flip = QTransform().scale(-1, 1)
                mirrored = [f.transformed(flip) for f in frames]
                self._flipped_cache[self.state] = mirrored
            frame = mirrored[(self.tick_count // speed) % len(mirrored)]
        return frame

    # =================================================================
    # Widget geometry
    # =================================================================

    def _sync_widget_geometry(self):
        """Keep the sprite anchored at (x_pos, y_pos) and grow upward for the
        bubble, clamped so a bubble near a screen edge stays visible."""
        bubble_h = self.speech_bubble_h if self.speech_text else 0
        width = max(self.sprite_w, self.speech_bubble_w if self.speech_text else 0)
        height = self.sprite_h + bubble_h

        # Bubble sits above the sprite; if there is no room above, flip it
        # below rather than pushing the sprite off the top of the screen.
        y = self.y_pos - bubble_h
        if y < self.screen_top and bubble_h:
            y = self.y_pos
            self.speech_below = True
        else:
            self.speech_below = False

        x = int(self.x_pos)
        if bubble_h and not self.speech_below:
            # Keep the bubble inside the screen horizontally.
            x = max(self.screen_left,
                    min(x, self.screen_left + self.screen_w - width))

        # Avoid pointless relayout: resizing/moving a translucent always-on-top
        # window every tick is what causes repaint storms.
        if self.width() != width or self.height() != height:
            self.resize(width, height)
        target = QPoint(x, int(y))
        if self.pos() != target:
            self.move(target)

    # =================================================================
    # Speech
    # =================================================================

    def speak(self, text):
        if not text:
            return
        text = " ".join(str(text).split())[:SPEECH_MAX_CHARS]
        self.speech_text = text
        self.speech_timer = SPEECH_DISPLAY_TICKS
        lines, width, height = _compute_bubble_geometry(text, self.speech_font)
        self.speech_lines = lines
        self.speech_bubble_w = width
        self.speech_bubble_h = height
        self._sync_widget_geometry()

    def _clear_speech(self):
        self.speech_text = ""
        self.speech_lines = []
        self.speech_bubble_w = 0
        self.speech_bubble_h = 0
        self._sync_widget_geometry()

    @guarded
    def _on_ai_line(self, text, status):
        """Model reply, on the GUI thread (queued signal).

        `status` decides whether the pet speaks at all: a rate-limited or
        deliberately skipped request must stay silent instead of firing off an
        unsolicited random line, which is what used to happen every 15 minutes
        once the screenshot caps were hit.
        """
        kind = self.ai_request_kind
        self.awaiting_ai = False
        if status == ai_companion.STATUS_OK and text:
            self.speak(text)
        elif status == ai_companion.STATUS_UNAVAILABLE and kind == "user":
            # The user explicitly asked for a line; give them the canned one.
            self.speak(get_system_status_quote(self.current_skin))

    def request_dialogue(self, user_initiated=True):
        """Ask for a line: model first, then the canned fallback."""
        if ai_companion.ai_enabled():
            self.awaiting_ai = True
            self.ai_deadline = self.tick_count + 90
            self.ai_request_kind = "user" if user_initiated else "idle"
            ai_companion.maybe_idle_line(self.current_skin, self.ai_bridge.line_ready.emit)
            return
        self.speak(get_system_status_quote(self.current_skin))

    def _speak_contextual(self, event_type):
        """Speak a canned line from the companion's dialogue table."""
        if companion_dialogue is None:
            return
        self.speak(companion_dialogue.get_contextual_quote(
            self.current_skin, event_type=event_type))

    # =================================================================
    # Screenshots
    # =================================================================

    def maybe_screenshot(self, force=False):
        """Occasionally grab the screen for a comment.

        The policy (interval, hourly and daily caps, AI availability) lives in
        ai_companion so there is one implementation of it. Pixels are grabbed
        here on the GUI thread because QPixmap demands it; redaction, JPEG
        encoding and the API call all happen on a worker.

        `force` is the "Look at this" menu action: it skips the interval and
        hourly caps, but never the blocklist -- privacy is not a quota.
        """
        if self._screenshot_inflight:
            return
        settings = ai_companion.screenshot_settings()
        if not (settings.get("enabled", False) or force):
            return
        if not force:
            required = float(settings.get("require_recent_activity_minutes", 3)) * 60 * 20
            if self.tick_count - self.last_activity_tick > required:
                return
            if not ai_companion.screenshot_slot_ok():
                return
        elif not ai_companion.ai_enabled():
            # Nothing to send it to; don't grab the screen for no reason.
            return
        else:
            ai_companion.reserve_forced_screenshot()

        app = QApplication.instance()
        image, reason = screen_capture.prepare_capture(
            app, settings.get("blocklist", []), self.screen_rect)
        if image is None:
            # Blocked or unavailable: release the slot, and say so once in a
            # while so a refusal is visible rather than mysterious.
            ai_companion.record_capture_attempt(False)
            if reason:
                self._speak_contextual("screenshot_blocked")
            return

        self._screenshot_inflight = True
        skin = self.current_skin
        quality = int(settings.get("jpeg_quality", 70))
        blocklist = settings.get("blocklist", [])
        screen_rect = self.screen_rect

        def worker():
            # QImage work: safe off the GUI thread, and this is where the
            # 100-800ms used to be spent freezing the pet.
            captured = False
            try:
                screen_capture.redact(image, blocklist, screen_rect)
                encoded = screen_capture.encode_jpeg_base64(image, quality)
                captured = bool(encoded)
                if encoded:
                    ai_companion.request_screenshot_comment(
                        skin, encoded, self.ai_bridge.line_ready.emit, manual=force)
            except Exception:
                log_exception("screenshot worker")
            finally:
                ai_companion.record_capture_attempt(captured)
                self._screenshot_inflight = False

        threading.Thread(target=worker, name="screenshot", daemon=True).start()

    # =================================================================
    # Context checks
    # =================================================================

    def _poll_focus(self):
        """Track the focused window for dialogue and for 'is anyone there'.

        Only a genuine change counts as activity. Marking the pet active on
        every poll meant the recent-activity gate was always satisfied, so
        screenshots fired on an unattended machine.
        """
        if self.tracker is None:
            return
        try:
            active = self.tracker.get_active_window()
        except Exception:
            return
        if not active or not active.title:
            return
        if active.title != self.last_window_title:
            self.last_window_title = active.title
            self.last_window_proc = active.process or ""
            self.last_activity_tick = self.tick_count

    def _check_window_context(self):
        """Occasionally say something about what the user is doing."""
        if self.speech_timer > 0 or self.awaiting_ai:
            return
        if self.state in ("SLEEP", "DRAG", "FALL", "PERCH"):
            return
        if companion_dialogue is None:
            return
        # Mid-focus the pet keeps its mouth shut: that is the whole point of a
        # focus block.
        if self.in_focus():
            return

        # Mood first: a drowsy pet does not have opinions about your window.
        mood_event = self._mood_event()
        if mood_event:
            self._speak_contextual(mood_event)
            return

        if self.last_window_title and random.random() < 0.7:
            event = "window"
        else:
            event = "time"
        self.speak(companion_dialogue.get_contextual_quote(
            self.current_skin, event_type=event,
            window_title=self.last_window_title or "",
            window_proc=self.last_window_proc or ""))

    # =================================================================
    # Mood and energy
    # =================================================================

    def mood(self):
        """'sleepy', 'happy' or 'content'.

        Cheap to compute every tick: it is just energy, whether the pet was
        petted recently, and whether the user is in a focus block.
        """
        if self.state == "SLEEP" or self.energy < MOOD_SLEEPY_MAX:
            return "sleepy"
        recently_petted = (self.petted_until_tick is not None
                           and self.tick_count - self.petted_until_tick < 600)
        if self.energy >= MOOD_HAPPY_MIN and recently_petted:
            return "happy"
        return "content"

    def _drain_energy(self):
        """Account for this tick's exertion, and rest when doing nothing."""
        drain = ENERGY_DRAIN.get(self.state)
        if drain is not None:
            self.energy = max(0.0, self.energy - drain)
        elif self.state == "SLEEP":
            self.energy = min(100.0, self.energy + ENERGY_GAIN_SLEEP)
        elif self.state in CALM_STATES:
            self.energy = min(100.0, self.energy + ENERGY_GAIN_IDLE)

    def _mood_event(self):
        """The dialogue event matching the current mood, if any."""
        mood = self.mood()
        if mood == "sleepy":
            return "sleepy"
        if mood == "happy" and random.random() < 0.35:
            return "happy"
        return None

    # =================================================================
    # Focus sessions
    # =================================================================

    def _poll_focus_session(self):
        """Watch the focus timer and react when the mode changes."""
        if not self.focus.configured():
            return
        previous = self.focus.mode
        self.focus.poll()
        change = self.focus.transition(previous)
        if not change:
            return
        # Only physical states suppress this. A session ending is exactly the
        # sort of thing worth interrupting for -- the old code dropped the line
        # whenever the pet happened to still be talking, which was most of the
        # time.
        if self.state in ("DRAG", "FALL"):
            return
        if change == "started":
            self._speak_contextual("focus_start")
        elif change == "ended":
            self.energy = min(100.0, self.energy + 10.0)
            self._speak_contextual("focus_end")
        elif change == "break":
            self.energy = min(100.0, self.energy + 15.0)
            self.petted_until_tick = self.tick_count
            self._speak_contextual("happy")

    def in_focus(self):
        try:
            return self.focus.is_focus()
        except Exception:
            return False

    # =================================================================
    # Ledges
    # =================================================================

    def _is_on_ledge(self):
        return self.current_ledge is not None and not self.current_ledge.is_floor

    def _ledge_under_pet(self):
        """The ledge the pet is standing on, or None.

        Uses overlap rather than centre containment, matching
        `find_landing_y`. The two used to disagree, and the disagreement is
        what let the pet enter PERCH holding no ledge at all -- an
        AttributeError on the next tick, and PyQt5 turns exceptions in slots
        into abort().
        """
        if self.tracker is None:
            return None
        try:
            return self.tracker.find_ledge_at(
                self.y_pos + self.sprite_h, self.x_pos, self.sprite_w,
                self.screen_rect)
        except Exception:
            return None

    def _validate_current_ledge(self):
        """Whether the current ledge is still under the pet."""
        if self.current_ledge is None or self.current_ledge.is_floor:
            return True
        if self.tracker is None:
            return False
        current = self._ledge_under_pet()
        if current is None:
            return False
        # Re-seat on the fresh ledge so a window that moved drags the pet along.
        if abs(current.y - self.current_ledge.y) > 1 or current.x_min != self.current_ledge.x_min:
            self.y_pos = float(current.y - self.sprite_h)
            self.current_ledge = current
        return True

    def _clamp_to_ledge(self):
        """Keep the pet inside its ledge's horizontal bounds.

        Called by every state that moves horizontally. STALK and RUN used to
        move without this, so the pet walked off a titlebar and then hung in
        mid-air, because nothing ever corrected its y again.
        """
        if not self._is_on_ledge():
            return False
        ledge = self.current_ledge
        if self.x_pos < ledge.x_min:
            self.x_pos = float(ledge.x_min)
            return True
        if self.x_pos + self.sprite_w > ledge.x_max:
            self.x_pos = float(ledge.x_max - self.sprite_w)
            return True
        return False

    # =================================================================
    # State transitions
    # =================================================================

    def _enter_state(self, new_state):
        self.state = new_state
        self.state_timer = 0

    def _enter_fall(self):
        self._enter_state("FALL")
        self.current_ledge = None

    def _enter_sit(self):
        self._enter_state("IDLE" if self.is_ghost else "SIT")
        if not self._is_on_ledge():
            self.y_pos = self.floor_y

    # =================================================================
    # Main loop
    # =================================================================

    @guarded
    def game_loop(self):
        self.tick_count += 1

        # Cursor movement counts as activity.
        cursor = QCursor.pos()
        if (cursor - self.last_cursor).manhattanLength() > CURSOR_ACTIVITY_PX:
            self.last_activity_tick = self.tick_count
        self.last_cursor = cursor

        if self.tick_count % FOCUS_POLL_TICKS == 0:
            self._poll_focus()        # which window is focused
            self._poll_focus_session()  # whether the user is in a focus block

        if self.tick_count % CONTEXT_CHECK_INTERVAL == 0:
            self._check_window_context()

        # Model took too long: fall back to a canned line so the pet never
        # looks stuck, and let a late reply through only if nothing newer is
        # showing.
        if self.awaiting_ai and self.tick_count > self.ai_deadline:
            self.awaiting_ai = False
            if self.speech_timer == 0:
                self.speak(get_system_status_quote(self.current_skin))

        if self.speech_timer > 0:
            self.speech_timer -= 1
            if self.speech_timer == 0:
                self._clear_speech()

        if self.heart_timer > 0:
            self.heart_timer -= 1

        if not self.dragging:
            self._update_fsm(cursor)
            self.maybe_screenshot()

        if self.tick_count % SAVE_INTERVAL_TICKS == 0:
            self._save_state()

        self._sync_widget_geometry()
        self.update()

    # =================================================================
    # Finite state machine
    # =================================================================

    def _update_fsm(self, cursor):
        self.state_timer += 1
        self._drain_energy()

        center_x = self.x_pos + self.sprite_w / 2.0
        center_y = self.y_pos + self.sprite_h / 2.0
        cursor_dx = cursor.x() - center_x
        cursor_dy = cursor.y() - center_y
        cursor_dist = math.hypot(cursor_dx, cursor_dy)

        if self.state == "DRAG":
            return
        if self.state == "FALL":
            self._tick_fall()
            return
        if self.state == "CLIMB":
            self._tick_climb()
            return
        if self.state == "PERCH":
            self._tick_perch(cursor_dx, cursor_dist)
            return
        if self.state in ("JUMP", "POUNCE"):
            # Airborne: no ground-lock, no x clamp against the floor, the arc
            # handler owns the position until it lands.
            self._tick_jump()
            return

        if self.is_ghost:
            hover = self.ghost_hover_y + math.sin(self.tick_count / 25.0) * 5.0
            self.y_pos += (hover - self.y_pos) * 0.15
        elif not self._is_on_ledge():
            self.y_pos = self.floor_y

        # Horizontal bounds of the current screen, honouring its origin.
        low = float(self.screen_left)
        high = float(self.screen_left + self.screen_w - self.sprite_w)
        self.x_pos = max(low, min(high, self.x_pos))

        if self.state in ("SIT", "IDLE"):
            self._tick_idle(cursor_dx, cursor_dist)
        elif self.state == "BLINK":
            if self.state_timer > STATE_MIN_DURATION.get("BLINK", 6):
                self._enter_sit()
        elif self.state == "GROOM":
            if self.state_timer > STATE_MAX_DURATION.get("GROOM", 100):
                self._enter_sit()
        elif self.state == "CHASE":
            self._tick_chase(cursor_dx, cursor_dist)
        elif self.state == "STALK":
            self._tick_stalk(cursor_dx, cursor_dist)
        elif self.state == "WALK":
            self._tick_walk()
        elif self.state == "RUN":
            self._tick_run(cursor_dx, cursor_dist)
        elif self.state == "SWAT":
            if self.state_timer > STATE_MIN_DURATION.get("SWAT", 20):
                self.energy = min(100.0, self.energy + 8)
                self._enter_sit()
        elif self.state == "SLEEP":
            if (self.state_timer > STATE_MAX_DURATION.get("SLEEP", 300)
                    or cursor_dist < 30):
                self.energy = min(100.0, self.energy + ENERGY_GAIN_WAKE)
                self._enter_sit()

    def _tick_idle(self, cursor_dx, cursor_dist):
        key = self.state
        min_dur = STATE_MIN_DURATION.get(key, 60)
        if self.state_timer < min_dur:
            return
        if (self.state_timer - min_dur) % TRANSITION_EVAL_INTERVAL != 0:
            return
        max_dur = STATE_MAX_DURATION.get(key, 160)
        self._pick_idle_transition(cursor_dx, cursor_dist,
                                  force=self.state_timer >= max_dur)

    def _walk_target(self):
        """A walk destination clamped to the pet's current surface."""
        if self._is_on_ledge():
            ledge = self.current_ledge
            span = ledge.x_max - ledge.x_min - self.sprite_w
            if span <= 20:
                return None
            return random.uniform(ledge.x_min, ledge.x_max - self.sprite_w)
        low = float(self.screen_left + 8)
        high = float(self.screen_left + self.screen_w - self.sprite_w - 8)
        if high <= low:
            return None
        return max(low, min(high, self.x_pos
                            + random.choice([-1, 1]) * random.randint(60, 160)))

    def _pick_idle_transition(self, cursor_dx, cursor_dist, force=False):
        mood = self.mood()
        focusing = self.in_focus()

        # A tired pet sleeps, and a sleeping pet does not get excited.
        if self.energy < 15 or (mood == "sleepy" and random.random() < 0.35):
            self._enter_state("SLEEP")
            return

        roll = random.random()
        threshold = 0.0

        threshold += 0.05
        if roll < threshold:
            self._enter_state("BLINK")
            return

        threshold += 0.08
        if roll < threshold:
            self._enter_state("GROOM")
            return

        threshold += 0.12
        if roll < threshold:
            target = self._walk_target()
            if target is not None:
                self.target_x = target
                self._enter_state("WALK")
                return

        # Chasing and stalking are the energetic options: skip them when the
        # pet is worn out, and skip all of them during a focus block.
        energetic = (not focusing and mood != "sleepy"
                     and self.energy > MOOD_SLEEPY_MAX)

        threshold += 0.06
        if roll < threshold and energetic and 40 < cursor_dist < 300:
            if self.allow_chase and self.is_ghost:
                self._enter_state("CHASE")
            elif self.is_ghost:
                self._enter_state("RUN")
            elif self.allow_chase and self.energy > 55:
                self._enter_state("CHASE")
            else:
                self._enter_state("STALK")
            return

        threshold += 0.05
        if roll < threshold and energetic and self.climb_enabled and not self.is_ghost:
            if self._try_start_climb():
                return

        # A small hop, mostly for pets that have energy to burn. Ghosts hover;
        # they have nothing to push off with.
        threshold += 0.04
        if roll < threshold and energetic and self.allow_jump and not self.is_ghost \
                and self.state_timer > 20 and not self._is_on_ledge():
            self._start_jump()
            return

        if force:
            target = self._walk_target()
            if target is not None:
                self.target_x = target
                self._enter_state("WALK")

    # ---- JUMP ----------------------------------------------------------

    def _start_jump(self, toward=None):
        """Leap upwards, optionally toward a target x."""
        self._enter_state("JUMP")
        self.current_ledge = None
        if toward is not None:
            self.facing = 1 if toward >= self.x_pos else -1
        self.vy = -JUMP_VELOCITY
        if self.is_ghost:
            # A ghost has no legs to push off with; it just rises and settles.
            self.ghost_hover_y = self.y_pos - 40.0

    def _tick_jump(self):
        """JUMP is an arc: rise, then fall back under gravity."""
        self.vy = min(self.vy + GRAVITY, TERMINAL_VEL)
        self.y_pos += self.vy
        if self.vy < 0:
            return  # still going up
        # A hop is not a drop, so it must not announce itself as one.
        self._tick_fall(announce=False)

    def _tick_chase(self, cursor_dx, cursor_dist):
        """Sprint after the cursor, then pounce when close enough."""
        if cursor_dx != 0:
            self.facing = 1 if cursor_dx > 0 else -1
        self.x_pos += self.facing * CHASE_SPEED
        if self._clamp_to_ledge():
            self._enter_sit()
            return
        if cursor_dist < 40:
            self._start_jump(toward=self.x_pos + self.facing * 10)
            self._enter_state("POUNCE")
            return
        if cursor_dist > 420 or self.state_timer > 220:
            self._enter_state("SIT")
            return
        # Clamp here as well as in the dispatcher: a state handler that is only
        # safe when called from one place is a trap.
        low = float(self.screen_left)
        high = float(self.screen_left + self.screen_w - self.sprite_w)
        if self.x_pos <= low or self.x_pos >= high:
            self.x_pos = max(low, min(high, self.x_pos))
            self._enter_state("SIT")

    def _tick_pounce(self):
        """The airborne half of a pounce: same arc as JUMP."""
        self._tick_jump()

    def _tick_stalk(self, cursor_dx, cursor_dist):
        if cursor_dx != 0:
            self.facing = 1 if cursor_dx > 0 else -1
        self.x_pos += self.facing * 1.6
        # Same ledge clamp as WALK; without it the pet strolls off the
        # titlebar and then floats there forever.
        if self._clamp_to_ledge() or cursor_dist < 45:
            self._enter_state("SWAT")
            return
        if self.state_timer > STATE_MAX_DURATION.get("STALK", 120):
            self._enter_state("SWAT")

    def _tick_run(self, cursor_dx, cursor_dist):
        if cursor_dx != 0:
            self.facing = 1 if cursor_dx > 0 else -1
        self.x_pos += self.facing * (2.2 if self.is_ghost else 3.2)
        if self._clamp_to_ledge() or cursor_dist < 50:
            self._enter_state("SWAT")
            return
        if self.state_timer > STATE_MAX_DURATION.get("RUN", 90):
            self._enter_state("SWAT")

    def _tick_walk(self):
        if self.target_x is None:
            self._enter_sit()
            return
        dx = self.target_x - self.x_pos
        self.facing = 1 if dx >= 0 else -1
        self.x_pos += self.facing * 1.1

        if self._clamp_to_ledge():
            self._enter_sit()
            return

        if abs(dx) < 3 or self.state_timer > STATE_MAX_DURATION.get("WALK", 100):
            self._enter_sit()

    # ---- FALL ----------------------------------------------------------

    def _tick_fall(self, announce=True):
        self.vy = min(self.vy + GRAVITY, TERMINAL_VEL)
        self.y_pos += self.vy

        landing_y = self.floor_y
        if self.tracker is not None:
            try:
                # `step` matters: at terminal velocity the pet moves 12px in a
                # tick, and without it a thin titlebar is rejected as already
                # passed, so the pet falls straight through it to the floor.
                landing_y = self.tracker.find_landing_y(
                    self.x_pos, self.y_pos, self.sprite_w, self.sprite_h,
                    self.floor_y, self.screen_rect, step=self.vy)
            except Exception:
                landing_y = self.floor_y

        if self.y_pos >= landing_y:
            self.y_pos = landing_y
            self.vy = 0.0
            ledge = self._ledge_under_pet() if landing_y < self.floor_y - 5 else None
            if ledge is not None:
                self.current_ledge = ledge
                self._enter_state("PERCH")
            else:
                # Either the floor, or a landing surface we cannot identify.
                # Never enter PERCH without a ledge: the next tick dereferences
                # it and the process aborts.
                self.current_ledge = None
                self.y_pos = self.floor_y
                self._enter_sit()
            if announce:
                self._speak_contextual("drop")

        low = float(self.screen_left)
        high = float(self.screen_left + self.screen_w - self.sprite_w)
        self.x_pos = max(low, min(high, self.x_pos))

    # ---- CLIMB ---------------------------------------------------------

    def _try_start_climb(self):
        """Grab a nearby edge. Returns True if a climb started."""
        if self.tracker is None:
            return False
        try:
            edge = self.tracker.find_nearby_climbable(
                self.x_pos, self.y_pos, self.sprite_w, self.sprite_h,
                reach_px=35.0, screen_rect=self.screen_rect)
        except Exception:
            return False
        if edge is None or edge.height < self.sprite_h:
            return False

        self.climb_target_edge = edge
        self._enter_state("CLIMB")
        if edge.is_left_edge:
            self.x_pos = float(edge.x)
        else:
            self.x_pos = float(edge.x - self.sprite_w)

        # Hugging the edge must not teleport the pet across the screen.
        low = float(self.screen_left)
        high = float(self.screen_left + self.screen_w - self.sprite_w)
        self.x_pos = max(low, min(high, self.x_pos))

        # Budget for the whole climb, measured once from where we started.
        self.climb_budget_ticks = self._climb_budget(edge)
        self._speak_contextual("climb")
        return True

    def _tick_climb(self):
        edge = self.climb_target_edge
        if edge is None:
            self._enter_fall()
            return

        # The window we are climbing may have closed. Without this check the
        # pet scrambles up thin air for the rest of the timeout.
        if self.tracker is not None:
            try:
                if not self.tracker.edge_still_present(edge):
                    self.climb_target_edge = None
                    self._enter_fall()
                    return
            except Exception:
                pass

        self.y_pos -= CLIMB_SPEED
        target_y = float(edge.y_top) - self.sprite_h

        if self.y_pos <= target_y:
            self.y_pos = target_y
            self.climb_target_edge = None
            ledge = self._ledge_under_pet()
            if ledge is not None:
                self.current_ledge = ledge
                self._enter_state("PERCH")
                self._speak_contextual("perch")
            else:
                self.current_ledge = None
                self._enter_fall()
            return

        # Budget measured when the climb started. The old fixed 10s cap
        # (200 ticks at 1.5px/tick = 300px) was shorter than a single screen,
        # so climbs could never complete and the pet always fell off. It must
        # not be recomputed from the remaining distance either: that shrinks
        # every tick and trips the timeout just before the top.
        budget = self.climb_budget_ticks or self._climb_budget(edge)
        if self.state_timer > budget + CLIMB_GRACE_TICKS:
            self.climb_target_edge = None
            self._enter_fall()

    def _climb_budget(self, edge):
        """Ticks needed to climb from the current position to the top."""
        distance = max(0.0, self.y_pos - (float(edge.y_top) - self.sprite_h))
        return int(distance / max(0.1, CLIMB_SPEED)) + 4

    # ---- PERCH ---------------------------------------------------------

    def _tick_perch(self, cursor_dx, cursor_dist):
        if not self._validate_current_ledge():
            # The window moved or closed: fall, but not through a stale ledge.
            self.current_ledge = None
            self.vy = 0.0
            self._enter_fall()
            return

        ledge = self.current_ledge
        self.y_pos = float(ledge.y - self.sprite_h)
        self.x_pos = max(float(ledge.x_min),
                         min(float(ledge.x_max - self.sprite_w), self.x_pos))

        min_dur = STATE_MIN_DURATION.get("PERCH", 80)
        max_dur = STATE_MAX_DURATION.get("PERCH", 200)
        if self.state_timer < min_dur:
            return
        if (self.state_timer - min_dur) % TRANSITION_EVAL_INTERVAL != 0:
            return

        # Max duration used to be folded into a roll that could not win,
        # because 200 ticks is itself one of the evaluated ticks: the pet
        # always left at exactly max_dur and the probability never applied.
        if self.state_timer >= max_dur:
            self._leave_ledge()
            return

        roll = random.random()
        if roll < 0.10:
            span = ledge.x_max - ledge.x_min - self.sprite_w
            if span > 20:
                self.target_x = random.uniform(ledge.x_min, ledge.x_max - self.sprite_w)
                self._enter_state("WALK")
                return
        elif roll < 0.15:
            # Sometimes step off rather than dropping: it reads as a decision
            # rather than a glitch. The arc still ends in _tick_fall.
            if self.allow_jump and self.energy > 40:
                self._start_jump()
            else:
                self._leave_ledge()

    def _leave_ledge(self):
        self.current_ledge = None
        self.vy = 0.0
        self._enter_fall()

    # =================================================================
    # Painting
    # =================================================================

    @guarded
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        frame = self.get_current_frame()
        sprite_y = self.sprite_h if self.speech_text and self.speech_below else 0
        if frame is not None:
            painter.drawPixmap(0, sprite_y, frame)

        # Heart floats above the pet, and above the bubble when one is up.
        if self.heart_timer > 0 and self.heart_pixmap is not None:
            hx = self.sprite_w // 2 - self.heart_pixmap.width() // 2
            top = sprite_y - self.heart_pixmap.height() + 6
            if self.speech_text and not self.speech_below:
                top -= self.speech_bubble_h - SPEECH_TAIL_H
            painter.drawPixmap(hx, max(0, top), self.heart_pixmap)

        if self.speech_text and self.speech_lines:
            self._paint_speech_bubble(painter)

        painter.end()

    def _paint_speech_bubble(self, painter):
        painter.setFont(self.speech_font)
        metrics = painter.fontMetrics()

        width = self.speech_bubble_w
        body_h = self.speech_bubble_h - SPEECH_TAIL_H
        below = self.speech_below

        box_x = max(0, (self.width() - width) // 2)
        box_y = self.height() - body_h if below else 0

        bubble_color = QColor(255, 255, 255, 235)
        painter.setBrush(bubble_color)
        painter.setPen(QColor(30, 24, 30))
        painter.drawRoundedRect(box_x, box_y, width, body_h,
                                SPEECH_BUBBLE_RADIUS, SPEECH_BUBBLE_RADIUS)

        tail_x = box_x + width // 2
        if below:
            points = [QPoint(tail_x - 4, box_y), QPoint(tail_x + 4, box_y),
                      QPoint(tail_x, box_y - SPEECH_TAIL_H)]
        else:
            points = [QPoint(tail_x - 4, box_y + body_h),
                      QPoint(tail_x + 4, box_y + body_h),
                      QPoint(tail_x, box_y + body_h + SPEECH_TAIL_H)]
        painter.drawPolygon(QPolygon(points))

        painter.setPen(QColor(30, 24, 30))
        line_h = metrics.height()
        text_y = box_y + SPEECH_PADDING_Y + metrics.ascent()
        for line in self.speech_lines:
            painter.drawText(box_x + SPEECH_PADDING_X, int(text_y), line)
            text_y += line_h

    # =================================================================
    # Mouse
    # =================================================================

    @guarded
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self.dragging = False
        self.drag_offset = event.globalPos() - self.pos()
        self.drag_start_y = self.y_pos
        self._enter_state("DRAG")
        self.vy = 0.0
        # Grabbing a perched pet must clear the ledge, or the ground-lock and
        # the ledge clamp fight each other for the whole drag.
        self.current_ledge = None
        if self.interaction is not None:
            self.interaction.record_drag_start(self.y_pos)

    @guarded
    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        target = event.globalPos() - self.drag_offset
        if (target - self.pos()).manhattanLength() > 4:
            self.dragging = True
        # Clamp into the desktop: an unclamped drag could leave the pet at
        # y=-5000, which is a twenty second fall.
        self.x_pos = float(max(0, min(target.x(), self._desktop_right())))
        bubble_h = self.speech_bubble_h if self.speech_text else 0
        top = self.screen_top - bubble_h
        self.y_pos = float(max(top, min(target.y() + bubble_h, self._desktop_bottom())))
        self._sync_widget_geometry()
        self.last_activity_tick = self.tick_count

    def _desktop_right(self):
        try:
            return QApplication.instance().desktop().width()
        except Exception:
            return self.screen_left + self.screen_w

    def _desktop_bottom(self):
        try:
            return QApplication.instance().desktop().height()
        except Exception:
            return self.screen_top + self.screen_h

    @guarded
    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        was_dragging = self.dragging
        self.dragging = False

        if not was_dragging:
            self.heart_timer = 20
            self.energy = min(100.0, self.energy + ENERGY_GAIN_PET)
            self.petted_until_tick = self.tick_count
            event_type = (self.interaction.record_pet()
                          if self.interaction is not None else "pet_first")
            if self.interaction is not None:
                # A sleepy pet grumbles instead of engaging.
                if self.mood() == "sleepy" and random.random() < 0.5:
                    event_type = "sleepy"
                self._speak_contextual(event_type)
            else:
                self.request_dialogue()
            self._enter_sit()
            return

        if self.is_ghost:
            # Resume hovering from wherever it was released, then ease back
            # down. The old code assigned y_pos and then immediately
            # overwrote it with the floor value, so it snapped instead.
            self.ghost_hover_y = self.y_pos
            self._enter_sit()
            return

        self.vy = 0.0
        self._enter_fall()

    # =================================================================
    # Context menu
    # =================================================================

    @guarded
    def contextMenuEvent(self, event):
        menu = QMenu(self)

        skin_menu = menu.addMenu("Switch Companion")
        for name in discover_skins() or self.available_skins:
            action = QAction(name.capitalize(), self)
            action.setCheckable(True)
            action.setChecked(name == self.current_skin)
            action.triggered.connect(lambda _c=False, n=name: self._switch_skin(n))
            skin_menu.addAction(action)

        scale_menu = menu.addMenu("Scale")
        for label, factor in SCALE_PRESETS.items():
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(self.scale_factor == factor)
            action.triggered.connect(lambda _c=False, f=factor: self._set_scale(f))
            scale_menu.addAction(action)

        menu.addSeparator()

        self._add_toggle(menu, "Climb Windows", self.climb_enabled, self._set_climb)
        self._add_toggle(menu, "Allow Jumping", self.allow_jump,
                         lambda checked: setattr(self, "allow_jump", bool(checked)))
        self._add_toggle(menu, "Allow Chasing", self.allow_chase,
                         lambda checked: setattr(self, "allow_chase", bool(checked)))
        if self.focus.configured():
            focus_action = QAction("Focus Timer (%s)" % self.focus.describe(), self)
            focus_action.setEnabled(False)
            menu.addAction(focus_action)

        speak_action = QAction("Speak", self)
        speak_action.triggered.connect(self._menu_speak)
        menu.addAction(speak_action)

        look_action = QAction("Look At This", self)
        look_action.setToolTip("Capture the screen once and comment on it")
        look_action.triggered.connect(self._menu_look)
        menu.addAction(look_action)

        personality_action = QAction("Edit Personality...", self)
        personality_action.triggered.connect(self._menu_edit_personality)
        menu.addAction(personality_action)

        ignore_action = QAction("Ignore Windows...", self)
        ignore_action.setToolTip("Windows the pet must not stand on")
        ignore_action.triggered.connect(self._menu_edit_ignores)
        menu.addAction(ignore_action)

        reset_action = QAction("Reset Position", self)
        reset_action.triggered.connect(self._reset_position)
        menu.addAction(reset_action)

        forget_action = QAction("Forget Me", self)
        forget_action.setToolTip("Delete saved position, skin and energy")
        forget_action.triggered.connect(self._menu_forget)
        menu.addAction(forget_action)

        menu.addSeparator()
        status = QAction(self._status_text(), self)
        status.setEnabled(False)
        menu.addAction(status)
        if self._ai_problem():
            retry = QAction("Retry AI", self)
            retry.triggered.connect(self._retry_ai)
            menu.addAction(retry)

        menu.addSeparator()
        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(self.shutdown)
        menu.addAction(quit_action)

        menu.exec_(event.globalPos())

    def _add_toggle(self, menu, label, checked, handler):
        action = QAction(label, self)
        action.setCheckable(True)
        action.setChecked(bool(checked))
        action.triggered.connect(handler)
        menu.addAction(action)
        return action

    # ---- menu actions --------------------------------------------------

    def _menu_look(self):
        self.heart_timer = 20
        if self.speech_timer == 0:
            self.speak("one sec, looking.")
        self.maybe_screenshot(force=True)

    def _menu_edit_personality(self):
        """Edit this companion's system prompt without touching the JSON."""
        from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                                     QTextEdit, QVBoxLayout)

        current = ai_companion.get_system_prompt(self.current_skin)
        dialog = QDialog(self)
        dialog.setWindowTitle("%s personality" % self.current_skin.capitalize())
        dialog.resize(520, 360)

        box = QVBoxLayout(dialog)
        hint = QLabel(
            "Instructions sent to the model with every line. One short sentence "
            "of instructions is plenty. Leave empty to use the default.")
        hint.setWordWrap(True)
        box.addWidget(hint)

        editor = QTextEdit(dialog)
        editor.setPlainText(current)
        box.addWidget(editor)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)

        if dialog.exec_() == QDialog.Accepted:
            text = editor.toPlainText().strip()
            if ai_companion.set_system_prompt(self.current_skin, text):
                self._speak_contextual("happy")
            else:
                self.speak("i couldn't save that. check companion_config.json")

    def _menu_edit_ignores(self):
        from PyQt5.QtWidgets import QInputDialog

        current = ", ".join(self._behaviour().get("ignore_windows", []))
        text, ok = QInputDialog.getText(
            self, "Ignore windows",
            "Comma-separated title or process fragments the pet must not\n"
            "perch on or climb (it can still look at them):", text=current)
        if not ok:
            return
        patterns = [part.strip() for part in text.split(",") if part.strip()]
        behaviour = dict(self._behaviour())
        behaviour["ignore_windows"] = patterns
        ai_companion.CONFIG.setdefault("behaviour", {}).update(behaviour)
        ai_companion.save_config()
        if self.tracker is not None:
            self.tracker.set_ignored_windows(patterns)
        self._speak_contextual("pet_first")

    def _menu_forget(self):
        self.forget_state()
        self._speak_contextual("greeting")

    def _status_text(self):
        status = ai_companion.ai_status()
        state = "AI on" if status["enabled"] else "AI off"
        return "%s - %s" % (state, status["reason"])

    def _ai_problem(self):
        """Whether the model is configured but failing, so retry makes sense."""
        return ai_companion.ai_configured() and not ai_companion.ai_status()["enabled"]

    def _retry_ai(self):
        ai_companion.reset_failures()
        self._speak_contextual("idle")

    def _set_climb(self, checked):
        self.climb_enabled = bool(checked)

    def _menu_speak(self):
        self.heart_timer = 20
        self.request_dialogue(user_initiated=True)

    def _switch_skin(self, name):
        self.load_skin(name)
        self.available_skins = discover_skins() or self.available_skins
        self.current_ledge = None
        self._reset_position()
        self._save_state(force=True)

    def _set_scale(self, factor):
        self.scale_factor = factor
        self.load_skin(self.current_skin)
        self.current_ledge = None
        self._reset_position()
        self._save_state(force=True)

    def _reset_position(self):
        self.x_pos = float(self.screen_left + self.screen_w // 2 - self.sprite_w // 2)
        self.y_pos = self.floor_y
        self.current_ledge = None
        self.climb_target_edge = None
        self.vy = 0.0
        self._enter_sit()
        self._sync_widget_geometry()

    def shutdown(self):
        """Stop the poller, save state, and quit cleanly."""
        try:
            self.timer.stop()
            self._save_state(force=True)
            if self.tracker is not None:
                self.tracker.stop_background()
        except Exception:
            log_exception("shutdown")
        QApplication.quit()

    def _install_signal_handlers(self):
        """Save state when the process is asked to stop.

        systemd and pm2 both stop the pet with SIGTERM, and a default handler
        kills the process outright, losing the position and energy.
        """
        import signal

        def handler(signum, _frame):
            try:
                self._save_state(force=True)
            except Exception:
                pass
            os._exit(0)

        for name in ("SIGTERM", "SIGINT", "SIGHUP"):
            signum = getattr(signal, name, None)
            if signum is None:
                continue
            try:
                signal.signal(signum, handler)
            except (ValueError, OSError):
                # Not the main thread, or the platform has no such signal.
                pass

    def closeEvent(self, event):
        try:
            self._save_state(force=True)
            if self.tracker is not None:
                self.tracker.stop_background()
        except Exception:
            pass
        super().closeEvent(event)


def _installed_fonts():
    try:
        return set(QFontDatabase().families())
    except Exception:
        return set()


def _pick_speech_font():
    """Fall back to a font that actually exists on this platform.

    Consolas is Windows-only; without a fallback the bubble silently used
    whatever Qt defaulted to, with different metrics and different wrapping.
    """
    global SPEECH_FONT_FAMILY
    installed = _installed_fonts()
    for candidate in (SPEECH_FONT_FAMILY, "Consolas", "DejaVu Sans Mono",
                      "Menlo", "Liberation Mono", "monospace"):
        if candidate in installed:
            SPEECH_FONT_FAMILY = candidate
            return


def main():
    global SPEECH_FONT_FAMILY

    # HiDPI must be requested before the QApplication exists. The pet then
    # works in logical pixels and the tracker is told the devicePixelRatio so
    # window rects line up with where the pet actually is.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    # A Qt.Tool window can be excluded from the "last window" heuristic, which
    # would quit the app when the context menu closed.
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(PET_WINDOW_TITLE)
    _pick_speech_font()

    skins = discover_skins()
    start_skin = "cat" if "cat" in skins else (skins[0] if skins else "cat")
    pet = DesktopPet(skin=start_skin, scale=2)
    pet._install_signal_handlers()

    try:
        return app.exec_()
    finally:
        if pet.tracker is not None:
            pet.tracker.stop_background()


if __name__ == "__main__":
    sys.exit(main())
