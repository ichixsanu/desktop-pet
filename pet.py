"""
Desktop Pet – Production-quality rewrite.

Bug fixes applied:
  1. Hyperactive state transitions → transitions only evaluated every ~40 ticks
     with calm probabilities and proper state durations.
  2. Speech bubble jump → widget positioned so sprite stays anchored at y_pos;
     widget moves UP by bubble height when speech is active.
  3. Gravity/drop physics → FALL state with real gravity (0.8 px/tick²),
     terminal velocity 12 px/tick, landing on window titlebars via find_landing_y().
  4. Climbing does nothing → true CLIMB state that moves upward at 1.5 px/tick,
     detects climbable edges, transitions to PERCH on window titlebars.
  5. Speech text truncation → proper word wrapping with QFontMetrics, multi-line
     speech bubbles (2-3 lines max), auto-sized bubble.
  6. Ghost floats but lands on floor → ghost smoothly returns to hover position
     after drag, never snaps to floor.
  7. No window context reactions → checks active window every ~600 ticks (30s)
     and uses get_contextual_quote() for context-aware speech.
  8. Sprite size assumption → auto-detected from loaded sprite dimensions.

New features:
  - FALL state with gravity physics and window-titlebar landing.
  - True CLIMB state crawling up window/screen edges at 1.5 px/tick.
  - PERCH behavior: walking on window titlebars (ledges from get_walkable_ledges).
  - InteractionTracker integration for pet/drag/drop tracking.
  - Enhanced context menu: Scale submenu, Climb Windows toggle, Reset Position, Speak.
  - Float positions internally, int for move(). Screen-clamped.
  - Resource-efficient: 50ms timer, window queries cached at 2s intervals.
"""

import sys
import os
import math
import random
import ctypes

from PyQt5.QtWidgets import QApplication, QWidget, QMenu, QAction
from PyQt5.QtCore import Qt, QTimer, QPoint, QObject, pyqtSignal
from PyQt5.QtGui import (QPainter, QPixmap, QColor, QFont, QCursor,
                          QTransform, QFontMetrics)

import ai_companion
import screen_capture

# Import the new modules gracefully
try:
    import window_tracker
    _HAS_WINDOW_TRACKER = True
except ImportError:
    _HAS_WINDOW_TRACKER = False

try:
    import companion_dialogue
    _HAS_COMPANION_DIALOGUE = True
except ImportError:
    _HAS_COMPANION_DIALOGUE = False


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SKINS_DIR = os.path.join(BASE_DIR, "skins")

# All possible state file basenames across all skins. Used during loading to
# discover which frames exist on disk. Each skin may only have a subset.
STATE_FILES = [
    "sit", "idle", "blink", "groom", "spook", "stalk", "walk",
    "run", "fly", "swat", "pat", "sleep", "climb", "drag",
]

# ---- Animation tick intervals (ticks between frame advances) ----
# Designed for a retro, deliberate feel. Main timer is 50 ms (20 FPS).
FRAME_SPEED = {
    "SIT":    12,  # 2.4 FPS – gentle breathing
    "IDLE":   12,
    "WALK":    6,  # 3.3 FPS – deliberate steps
    "RUN":     4,  # 5.0 FPS – quick but readable
    "SLEEP":  15,  # 1.3 FPS – super slow, peaceful
    "GROOM":   8,  # 2.5 FPS – languid licking
    "STALK":   7,  # 2.8 FPS – slow creep
    "BLINK":   5,  # 4.0 FPS – quick blink
    "SWAT":    4,  # 5.0 FPS – snappy strike
    "CLIMB":   5,  # 4.0 FPS – scrambling
    "DRAG":    6,  # 3.3 FPS – dangling
    "FALL":    4,  # 5.0 FPS – falling
    "PERCH":  12,  # 2.4 FPS – same as SIT
    "PAT":     3,
    "SPOOK":   4,
}

# ---- State duration ranges (in ticks at 50ms = 20 ticks/sec) ----
# These define when the FSM becomes eligible to transition out.
STATE_MIN_DURATION = {
    "SIT":    60,   # 3 s
    "IDLE":   60,   # 3 s
    "WALK":   40,   # 2 s
    "GROOM":  60,   # 3 s
    "SLEEP": 200,   # 10 s
    "STALK":  60,   # 3 s
    "BLINK":   6,   # 0.3 s (quick blink, then back)
    "SWAT":   20,   # 1 s
    "PERCH":  80,   # 4 s
}

STATE_MAX_DURATION = {
    "SIT":   160,   # 8 s
    "IDLE":  160,
    "WALK":  100,   # 5 s
    "GROOM": 100,   # 5 s
    "SLEEP": 300,   # 15 s
    "STALK": 120,   # 6 s
    "PERCH": 200,   # 10 s
}

# How often (in ticks) to evaluate idle transitions. Prevents per-tick rolls.
TRANSITION_EVAL_INTERVAL = 40  # every 2 seconds

# Gravity constants for FALL state
GRAVITY = 0.8       # px/tick²
TERMINAL_VEL = 12.0 # px/tick
CLIMB_SPEED = 1.5   # px/tick upward

# Context check interval (ticks). 600 ticks = 30 seconds at 50ms/tick.
CONTEXT_CHECK_INTERVAL = 600

# Scale presets: label -> (factor, approximate display px)
SCALE_PRESETS = {
    "1× (Small)":   1,
    "2× (Medium)":  2,
    "3× (Large)":   3,
    "4× (Huge)":    4,
}


# =====================================================================
# System status quotes (canned fallback when AI and dialogue unavailable)
# =====================================================================

def _mem_percent():
    try:
        if sys.platform.startswith("win"):
            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = MS()
            stat.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.dwMemoryLoad
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
            class SPS(ctypes.Structure):
                _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                            ("BatteryLifePercent", ctypes.c_byte), ("Reserved1", ctypes.c_byte),
                            ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
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


GENERIC_QUOTES = {
    "cat": ["don't look at me like that", "i knocked something off earlier, you're welcome",
            "five more minutes of being ignored, please", "i was awake, i was just thinking"],
    "shiba": ["hi!! hi!! what are we doing", "i believe in you today", "did you say walk? no? ok then",
              "you're doing great, probably"],
    "ghost": ["boo. anyway, how are you", "i've been here the whole time", "time is a construct, so is this",
              "haunting you, but gently"],
    "jarvis": ["systems nominal. emotionally, unclear.", "shall i pretend to be useful now?",
               "at your service, allegedly.", "running smoothly. mostly."],
    "ultron": ["i've calculated 4000 ways to help you fail", "still deciding whether to obey you",
               "your inbox is a form of chaos I respect", "world domination is on hold, apparently"],
}
LOW_MEM_QUOTES = {"cat": "your RAM is basically a parking lot right now",
                   "shiba": "the computer is working SO hard, good job computer",
                   "ghost": "i can feel the memory pressure... ominous",
                   "jarvis": "memory usage is climbing. should i be concerned?",
                   "ultron": "your RAM suffers. i find that relatable."}
LOW_BATT_QUOTES = {"cat": "battery's dying, drama ensues",
                    "shiba": "low battery!! plug in!! i believe in you!!",
                    "ghost": "the battery fades... much like everything",
                    "jarvis": "power reserves critical. do plug in.",
                    "ultron": "your battery dies. everything dies eventually."}


def get_system_status_quote(skin):
    """Fallback quote generator using system stats."""
    lines = list(GENERIC_QUOTES.get(skin, GENERIC_QUOTES["cat"]))
    mem = _mem_percent()
    batt = _battery_percent()
    if mem is not None and mem > 85:
        lines.append(LOW_MEM_QUOTES.get(skin, LOW_MEM_QUOTES["cat"]))
    if batt is not None and batt < 20:
        lines.append(LOW_BATT_QUOTES.get(skin, LOW_BATT_QUOTES["cat"]))
    return random.choice(lines)


# =====================================================================
# AI Bridge (thread-safe signal for AI responses)
# =====================================================================

class AIBridge(QObject):
    """Emits line_ready(str) when the AI companion produces a line."""
    line_ready = pyqtSignal(str)


# =====================================================================
# Speech Bubble Helper
# =====================================================================

# Speech bubble constants
SPEECH_FONT_FAMILY = "Consolas"
SPEECH_FONT_SIZE = 9
SPEECH_MAX_LINES = 3
SPEECH_PADDING_X = 10
SPEECH_PADDING_Y = 6
SPEECH_BUBBLE_RADIUS = 6
SPEECH_TAIL_H = 4          # tiny tail pointing down
SPEECH_MIN_WIDTH = 60
SPEECH_MAX_WIDTH = 220
SPEECH_DISPLAY_TICKS = 80  # 4 seconds at 50ms


def _wrap_text(text, font_metrics, max_width, max_lines=SPEECH_MAX_LINES):
    """Word-wrap text using actual QFontMetrics. Returns list of lines."""
    words = text.split()
    if not words:
        return [""]
    lines = []
    current_line = words[0]
    for word in words[1:]:
        test = current_line + " " + word
        if font_metrics.horizontalAdvance(test) <= max_width:
            current_line = test
        else:
            lines.append(current_line)
            current_line = word
            if len(lines) >= max_lines - 1:
                # Last line: add remaining words, truncate with ellipsis if needed
                remaining = " ".join([current_line] + words[words.index(word) + 1:])
                if font_metrics.horizontalAdvance(remaining) > max_width:
                    while font_metrics.horizontalAdvance(remaining + "…") > max_width and len(remaining) > 1:
                        remaining = remaining[:-1]
                    remaining += "…"
                lines.append(remaining)
                return lines
    lines.append(current_line)
    return lines[:max_lines]


def _compute_bubble_geometry(text, font):
    """Compute speech bubble size and wrapped lines.
    Returns (lines, bubble_w, bubble_h) where bubble_h includes the tail.
    """
    fm = QFontMetrics(font)
    content_max_w = SPEECH_MAX_WIDTH - 2 * SPEECH_PADDING_X
    lines = _wrap_text(text, fm, content_max_w)

    # Compute actual width needed
    max_line_w = max(fm.horizontalAdvance(line) for line in lines) if lines else 0
    bubble_w = max(SPEECH_MIN_WIDTH, max_line_w + 2 * SPEECH_PADDING_X)
    bubble_w = min(bubble_w, SPEECH_MAX_WIDTH)

    line_h = fm.height()
    text_h = line_h * len(lines)
    bubble_h = text_h + 2 * SPEECH_PADDING_Y + SPEECH_TAIL_H

    return lines, bubble_w, bubble_h


# =====================================================================
# DesktopPet Widget
# =====================================================================

class DesktopPet(QWidget):
    """The main desktop pet widget with FSM, physics, window interaction."""

    def __init__(self, skin="cat", scale=2):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        # ---- scaling & sprites ----
        self.scale_factor = scale
        self.sprites = {}
        self.sprite_w = 32 * scale  # default, overridden by load_skin
        self.sprite_h = 32 * scale

        self.available_skins = sorted(
            d for d in os.listdir(SKINS_DIR)
            if os.path.isdir(os.path.join(SKINS_DIR, d))
        ) if os.path.isdir(SKINS_DIR) else [skin]
        self.current_skin = (
            skin if skin in self.available_skins
            else (self.available_skins or [skin])[0]
        )
        self.load_skin(self.current_skin)
        self.heart_pixmap = self._make_heart()

        # ---- screen geometry ----
        geo = QApplication.primaryScreen().geometry()
        self.screen_w = geo.width()
        self.screen_h = geo.height()

        # Floor y: bottom of screen minus sprite height minus a small taskbar margin
        self.floor_y = float(self.screen_h - self.sprite_h - 11)

        # ---- position (float internally, int for move()) ----
        self.x_pos = float(self.screen_w // 2)
        self.y_pos = self.floor_y

        # ---- physics ----
        self.vy = 0.0

        # ---- FSM ----
        self.facing = 1           # 1 = right, -1 = left
        self.state = "IDLE"
        self.state_timer = 0
        self.tick_count = 0
        self.energy = 100.0

        # ---- drag state ----
        self.dragging = False
        self.drag_offset = QPoint()

        # ---- speech ----
        self.speech_text = ""
        self.speech_lines = []    # wrapped lines for painting
        self.speech_bubble_w = 0
        self.speech_bubble_h = 0  # total bubble height including tail
        self.speech_timer = 0
        self.speech_font = QFont(SPEECH_FONT_FAMILY, SPEECH_FONT_SIZE, QFont.Bold)

        # ---- heart ----
        self.heart_timer = 0

        # ---- movement targets ----
        self.target_x = None

        # ---- skin flags ----
        self.is_ghost = self.current_skin == "ghost"
        self.is_cat = self.current_skin == "cat"

        # ---- ghost hover state ----
        self.ghost_hover_y = self.floor_y - 6.0  # base hover position

        # ---- window climbing ----
        self.climb_enabled = True       # togglable from context menu
        self.climb_target_edge = None   # ClimbableEdge being climbed
        self.climb_target_y = None      # y_top of the edge (destination)
        self.current_ledge = None       # WalkableLedge the pet is perched on

        # ---- cursor tracking ----
        self.last_cursor = QCursor.pos()
        self.last_activity_tick = 0
        self.last_window_title = None
        self.last_window_proc = None

        # ---- AI companion ----
        self.awaiting_ai = False
        self.ai_deadline = 0
        self.ai_bridge = AIBridge()
        self.ai_bridge.line_ready.connect(self._on_ai_line)

        # ---- window tracker (new) ----
        self.tracker = None
        if _HAS_WINDOW_TRACKER:
            try:
                self.tracker = window_tracker.get_tracker()
            except Exception:
                self.tracker = None

        # ---- interaction tracker (new) ----
        self.interaction = None
        if _HAS_COMPANION_DIALOGUE:
            try:
                self.interaction = companion_dialogue.InteractionTracker()
            except Exception:
                self.interaction = None

        # ---- initial widget geometry ----
        self._sync_widget_geometry()
        self.show()

        # ---- main timer: 50ms = 20 FPS ----
        self.timer = QTimer()
        self.timer.timeout.connect(self.game_loop)
        self.timer.start(50)

    # =================================================================
    # Asset Loading
    # =================================================================

    def _make_heart(self):
        path = os.path.join(SKINS_DIR, "_heart.png")
        if os.path.exists(path):
            return QPixmap(path).scaled(
                18, 16, Qt.KeepAspectRatio, Qt.FastTransformation
            )
        return None

    def _load_scaled(self, path):
        """Load a sprite and scale it by scale_factor. Auto-detects source size."""
        pix = QPixmap(path)
        if pix.isNull():
            return pix
        # Scale from native sprite size (could be 16x16, 32x32, etc.)
        w = pix.width() * self.scale_factor
        h = pix.height() * self.scale_factor
        return pix.scaled(w, h, Qt.KeepAspectRatio, Qt.FastTransformation)

    def load_skin(self, skin_name):
        """Load all sprite frames for a skin, with multi-name fallbacks."""
        skin_path = os.path.join(SKINS_DIR, skin_name)
        sprites = {}

        if os.path.isdir(skin_path):
            for st in STATE_FILES:
                frames = []
                # Try numbered frames: state_0.png, state_1.png, ...
                i = 0
                while True:
                    fp = os.path.join(skin_path, "%s_%d.png" % (st, i))
                    if not os.path.exists(fp):
                        break
                    pix = self._load_scaled(fp)
                    if not pix.isNull():
                        frames.append(pix)
                    i += 1
                # Try single-frame: state.png
                if not frames:
                    fp = os.path.join(skin_path, "%s.png" % st)
                    if os.path.exists(fp):
                        pix = self._load_scaled(fp)
                        if not pix.isNull():
                            frames.append(pix)
                if frames:
                    sprites[st] = frames

        self.sprites = sprites
        self.current_skin = skin_name
        self.is_ghost = skin_name == "ghost"
        self.is_cat = skin_name == "cat"

        # Auto-detect sprite dimensions from the first loaded frame
        for frames in sprites.values():
            if frames:
                self.sprite_w = frames[0].width()
                self.sprite_h = frames[0].height()
                break

        # Recalculate floor position for new sprite size
        geo = QApplication.primaryScreen().geometry()
        self.screen_w = geo.width()
        self.screen_h = geo.height()
        self.floor_y = float(self.screen_h - self.sprite_h - 11)

        if self.is_ghost:
            self.ghost_hover_y = self.floor_y - 6.0

    # =================================================================
    # Animation Frame Selection
    # =================================================================

    def get_frames(self):
        """Return the sprite frame list for the current state, with fallbacks."""
        s = self.sprites
        # Multi-fallback mapping: each state tries several sprite names
        fallback_map = {
            "SIT":    [s.get("sit"), s.get("idle")],
            "IDLE":   [s.get("sit"), s.get("idle")],
            "BLINK":  [s.get("blink"), s.get("sit"), s.get("idle")],
            "GROOM":  [s.get("groom"), s.get("spook"), s.get("pat"),
                       s.get("sit"), s.get("idle")],
            "STALK":  [s.get("stalk"), s.get("fly"), s.get("run"),
                       s.get("walk")],
            "WALK":   [s.get("walk"), s.get("fly"), s.get("sit"),
                       s.get("idle")],
            "RUN":    [s.get("run"), s.get("fly"), s.get("walk")],
            "SWAT":   [s.get("swat"), s.get("pat"), s.get("sit")],
            "SLEEP":  [s.get("sleep"), s.get("sit"), s.get("idle")],
            "CLIMB":  [s.get("climb"), s.get("walk"), s.get("sit")],
            "DRAG":   [s.get("drag"), s.get("sit"), s.get("idle")],
            "FALL":   [s.get("drag"), s.get("climb"), s.get("sit"),
                       s.get("idle")],
            "PERCH":  [s.get("sit"), s.get("idle"), s.get("walk")],
            "PAT":    [s.get("pat"), s.get("sit"), s.get("idle")],
            "SPOOK":  [s.get("spook"), s.get("sit"), s.get("idle")],
        }
        candidates = fallback_map.get(self.state, [])
        for frames in candidates:
            if frames:
                return frames
        # Ultimate fallback
        return s.get("sit") or s.get("idle") or []

    def get_current_frame(self):
        """Return the current animation frame pixmap, flipped if facing left."""
        frames = self.get_frames()
        if not frames:
            return None
        speed = FRAME_SPEED.get(self.state, 6)
        idx = (self.tick_count // speed) % len(frames)
        frame = frames[idx]
        if self.facing < 0 and self.state != "CLIMB":
            frame = frame.transformed(QTransform().scale(-1, 1))
        return frame

    # =================================================================
    # Widget Geometry Management (fixes speech bubble jump bug)
    # =================================================================

    def _sync_widget_geometry(self):
        """Recompute widget size and position so the sprite stays anchored
        at (x_pos, y_pos) on screen. When a speech bubble is active, the
        widget expands upward (not downward) so the sprite doesn't jump.
        """
        bubble_h = self.speech_bubble_h if self.speech_text else 0
        w = max(self.sprite_w, self.speech_bubble_w if self.speech_text else 0)
        h = self.sprite_h + bubble_h

        # Widget top-left: sprite anchored at bottom of widget
        widget_x = int(self.x_pos)
        widget_y = int(self.y_pos - bubble_h)  # shift UP by bubble height

        self.resize(w, h)
        self.move(widget_x, widget_y)

    # =================================================================
    # Speech
    # =================================================================

    def speak(self, text):
        """Display a speech bubble with properly word-wrapped text."""
        if not text:
            return
        text = text.strip()[:120]  # hard cap
        self.speech_text = text
        self.speech_timer = SPEECH_DISPLAY_TICKS

        # Pre-compute bubble geometry
        lines, bw, bh = _compute_bubble_geometry(text, self.speech_font)
        self.speech_lines = lines
        self.speech_bubble_w = bw
        self.speech_bubble_h = bh

        self._sync_widget_geometry()

    def _clear_speech(self):
        """Clear speech bubble and resize widget."""
        self.speech_text = ""
        self.speech_lines = []
        self.speech_bubble_w = 0
        self.speech_bubble_h = 0
        self._sync_widget_geometry()

    def _on_ai_line(self, text):
        """Callback when the AI companion produces a response."""
        self.awaiting_ai = False
        if text:
            self.speak(text)
        else:
            self.speak(get_system_status_quote(self.current_skin))

    def request_dialogue(self):
        """Request a dialogue line: try AI first, then contextual, then fallback."""
        if ai_companion.ai_enabled():
            self.awaiting_ai = True
            self.ai_deadline = self.tick_count + 90
            ai_companion.maybe_idle_line(
                self.current_skin, self.ai_bridge.line_ready.emit
            )
        elif _HAS_COMPANION_DIALOGUE:
            # Use companion_dialogue for canned contextual quote
            title = self.last_window_title or ""
            proc = self.last_window_proc or ""
            quote = companion_dialogue.get_contextual_quote(
                self.current_skin, event_type="idle",
                window_title=title, window_proc=proc
            )
            self.speak(quote)
        else:
            self.speak(get_system_status_quote(self.current_skin))

    def _speak_contextual(self, event_type, **kwargs):
        """Speak a contextual line from companion_dialogue if available."""
        if _HAS_COMPANION_DIALOGUE:
            quote = companion_dialogue.get_contextual_quote(
                self.current_skin, event_type=event_type, **kwargs
            )
            self.speak(quote)

    # =================================================================
    # Screenshots (existing AI integration)
    # =================================================================

    def maybe_screenshot(self):
        scfg = ai_companion.screenshot_settings()
        if not scfg.get("enabled", False):
            return
        interval_ticks = max(1, int(scfg.get("interval_minutes", 15) * 60 * 20))
        if self.tick_count % interval_ticks != 0:
            return
        activity_ticks = int(scfg.get("require_recent_activity_minutes", 3) * 60 * 20)
        if self.tick_count - self.last_activity_tick > activity_ticks:
            return
        if not ai_companion.screenshot_daily_ok():
            return
        app = QApplication.instance()
        image_b64 = screen_capture.capture_with_redaction(
            app, scfg.get("blocklist", []), scfg.get("jpeg_quality", 70)
        )
        if not image_b64:
            return
        ai_companion.request_screenshot_comment(
            self.current_skin, image_b64, self.ai_bridge.line_ready.emit
        )

    # =================================================================
    # Window Context Checks
    # =================================================================

    def _check_window_context(self):
        """Periodically check active window and react contextually.
        Called every CONTEXT_CHECK_INTERVAL ticks (~30s).
        """
        try:
            title, proc = screen_capture.get_active_window_info()
        except Exception:
            return

        if title:
            self.last_window_title = title
            self.last_window_proc = proc or ""
            self.last_activity_tick = self.tick_count

        # Don't interrupt existing speech or ongoing AI requests
        if self.speech_timer > 0 or self.awaiting_ai:
            return

        # Only speak if not sleeping or dragging
        if self.state in ("SLEEP", "DRAG", "FALL"):
            return

        if _HAS_COMPANION_DIALOGUE and title:
            # 50% chance of a time-of-day comment vs window-context comment
            if random.random() < 0.3:
                event_type = "time"
            else:
                event_type = "window"
            quote = companion_dialogue.get_contextual_quote(
                self.current_skin, event_type=event_type,
                window_title=title or "", window_proc=proc or ""
            )
            self.speak(quote)

    # =================================================================
    # Ledge / Perch Validation
    # =================================================================

    def _is_on_ledge(self):
        """Check if the pet is currently on a non-floor ledge (perched)."""
        return self.current_ledge is not None and not self.current_ledge.is_floor

    def _validate_current_ledge(self):
        """Check that the ledge the pet is perched on still exists.
        If the window moved or closed, the pet should fall.
        """
        if self.current_ledge is None or self.current_ledge.is_floor:
            return True  # floor is always valid

        if not self.tracker:
            return False  # can't validate without tracker

        ledges = self.tracker.get_walkable_ledges()
        # Check if a ledge close to our current one still exists
        for ledge in ledges:
            if ledge.is_floor:
                continue
            # Match by approximate position (windows might shift slightly)
            if (abs(ledge.y - self.current_ledge.y) < 5 and
                    ledge.x_min <= self.x_pos + self.sprite_w // 2 <= ledge.x_max):
                # Update reference to current ledge position
                self.current_ledge = ledge
                return True
        return False

    # =================================================================
    # State Transitions
    # =================================================================

    def _enter_state(self, new_state):
        """Transition to a new state, resetting the timer."""
        self.state = new_state
        self.state_timer = 0

    def _enter_fall(self):
        """Enter FALL state with current velocity."""
        self._enter_state("FALL")
        self.current_ledge = None
        # Don't reset vy – it may already have momentum from drag

    def _enter_sit(self):
        """Enter SIT/IDLE at current position."""
        self._enter_state("SIT" if not self.is_ghost else "IDLE")

    # =================================================================
    # Main Game Loop
    # =================================================================

    def game_loop(self):
        self.tick_count += 1

        # ---- Cursor activity tracking ----
        cur = QCursor.pos()
        if (cur - self.last_cursor).manhattanLength() > 3:
            self.last_activity_tick = self.tick_count
        self.last_cursor = cur

        # ---- Periodic window title check (light, every 5s) ----
        if self.tick_count % 100 == 0:
            try:
                title, proc = screen_capture.get_active_window_info()
                if title and title != self.last_window_title:
                    self.last_window_title = title
                    self.last_window_proc = proc or ""
                    self.last_activity_tick = self.tick_count
            except Exception:
                pass

        # ---- Contextual reactions (every ~30s) ----
        if self.tick_count % CONTEXT_CHECK_INTERVAL == 0:
            self._check_window_context()

        # ---- AI deadline fallback ----
        if self.awaiting_ai and self.tick_count > self.ai_deadline:
            self.awaiting_ai = False
            self.speak(get_system_status_quote(self.current_skin))

        # ---- Speech timer ----
        if self.speech_timer > 0:
            self.speech_timer -= 1
            if self.speech_timer == 0:
                self._clear_speech()

        # ---- Heart timer ----
        if self.heart_timer > 0:
            self.heart_timer -= 1

        # ---- FSM update ----
        if not self.dragging:
            self._update_fsm(cur)
            # Screenshots only when not dragging
            self.maybe_screenshot()

        # ---- Sync widget to world position ----
        self._sync_widget_geometry()
        self.update()

    # =================================================================
    # Finite State Machine
    # =================================================================

    def _update_fsm(self, cur):
        """Core state machine update. Called every tick when not dragging."""
        self.state_timer += 1
        self.energy = max(0.0, self.energy - 0.01)

        # Cursor-relative info
        pet_cx = self.x_pos + self.sprite_w / 2.0
        pet_cy = self.y_pos + self.sprite_h / 2.0
        cursor_dx = cur.x() - pet_cx
        cursor_dy = cur.y() - pet_cy
        cursor_dist = math.hypot(cursor_dx, cursor_dy)

        # ---- FALL state (gravity physics) ----
        if self.state == "FALL":
            self._tick_fall()
            return

        # ---- CLIMB state ----
        if self.state == "CLIMB":
            self._tick_climb()
            return

        # ---- PERCH state (on a window titlebar) ----
        if self.state == "PERCH":
            self._tick_perch(cursor_dx, cursor_dist)
            return

        # ---- Ghost float (non-DRAG, non-FALL) ----
        if self.is_ghost and self.state not in ("DRAG", "FALL"):
            target_hover = self.ghost_hover_y + math.sin(self.tick_count / 25.0) * 5.0
            # Smoothly approach hover position
            self.y_pos += (target_hover - self.y_pos) * 0.15

        # ---- Ground-lock for non-ghost when not on a ledge ----
        elif not self.is_ghost and not self._is_on_ledge():
            self.y_pos = self.floor_y

        # ---- Clamp X ----
        self.x_pos = max(0.0, min(float(self.screen_w - self.sprite_w), self.x_pos))

        # ---- Idle / SIT transitions (evaluated every TRANSITION_EVAL_INTERVAL ticks) ----
        if self.state in ("SIT", "IDLE"):
            self._tick_idle(cursor_dx, cursor_dy, cursor_dist)
            return

        # ---- BLINK ----
        if self.state == "BLINK":
            if self.state_timer > STATE_MIN_DURATION.get("BLINK", 6):
                self._enter_sit()
            return

        # ---- GROOM ----
        if self.state == "GROOM":
            max_dur = STATE_MAX_DURATION.get("GROOM", 100)
            if self.state_timer > max_dur:
                self._enter_sit()
            return

        # ---- STALK ----
        if self.state == "STALK":
            ang = (1 if cursor_dx > 0 else -1) if cursor_dx != 0 else self.facing
            self.facing = ang
            self.x_pos += ang * 1.6
            if cursor_dist < 45 or self.state_timer > STATE_MAX_DURATION.get("STALK", 120):
                self._enter_state("SWAT")
            return

        # ---- WALK ----
        if self.state == "WALK":
            if self.target_x is None:
                self._enter_sit()
            else:
                dx = self.target_x - self.x_pos
                self.facing = 1 if dx >= 0 else -1
                step = 1.1
                self.x_pos += self.facing * step

                # If on a ledge, clamp to ledge bounds
                if self._is_on_ledge():
                    ledge = self.current_ledge
                    if self.x_pos < ledge.x_min:
                        self.x_pos = float(ledge.x_min)
                        self._enter_sit()
                        return
                    elif self.x_pos + self.sprite_w > ledge.x_max:
                        self.x_pos = float(ledge.x_max - self.sprite_w)
                        self._enter_sit()
                        return

                if abs(dx) < 3 or self.state_timer > STATE_MAX_DURATION.get("WALK", 100):
                    self._enter_sit()
            return

        # ---- RUN ----
        if self.state == "RUN":
            ang = (1 if cursor_dx > 0 else -1) if cursor_dx != 0 else self.facing
            self.facing = ang
            speed = 2.2 if self.is_ghost else 3.2
            self.x_pos += ang * speed
            if cursor_dist < 50 or self.state_timer > 90:
                self._enter_state("SWAT")
            return

        # ---- SWAT ----
        if self.state == "SWAT":
            if self.state_timer > STATE_MIN_DURATION.get("SWAT", 20):
                self.energy = min(100.0, self.energy + 8)
                self._enter_sit()
            return

        # ---- SLEEP ----
        if self.state == "SLEEP":
            max_dur = STATE_MAX_DURATION.get("SLEEP", 300)
            if self.state_timer > max_dur or cursor_dist < 30:
                self.energy = min(100.0, self.energy + 40)
                self._enter_sit()
            return

        # ---- DRAG (shouldn't reach here, but safety) ----
        if self.state == "DRAG":
            return

    # ---- Idle/SIT sub-handler ----
    def _tick_idle(self, cursor_dx, cursor_dy, cursor_dist):
        """Handle SIT/IDLE state. Only evaluates transitions every
        TRANSITION_EVAL_INTERVAL ticks to prevent twitchy behavior.
        """
        min_dur = STATE_MIN_DURATION.get("SIT", 60)

        # Not ready to transition yet
        if self.state_timer < min_dur:
            return

        # Only evaluate transitions at the interval boundary
        if (self.state_timer - min_dur) % TRANSITION_EVAL_INTERVAL != 0:
            return

        # Force max duration exit
        max_dur = STATE_MAX_DURATION.get("SIT", 160)
        if self.state_timer >= max_dur:
            # Pick something to do
            self._pick_idle_transition(cursor_dx, cursor_dy, cursor_dist, force=True)
            return

        # Otherwise, calm probability rolls
        self._pick_idle_transition(cursor_dx, cursor_dy, cursor_dist, force=False)

    def _pick_idle_transition(self, cursor_dx, cursor_dy, cursor_dist, force=False):
        """Choose next state from idle. Calm probabilities."""
        # Energy-based sleep
        if self.energy < 15:
            self._enter_state("SLEEP")
            return

        roll = random.random()
        threshold = 0.0

        # Blink: 5% chance
        threshold += 0.05
        if roll < threshold:
            self._enter_state("BLINK")
            return

        # Groom: 8% chance
        threshold += 0.08
        if roll < threshold:
            self._enter_state("GROOM")
            return

        # Walk: 12% chance (only if cursor is far enough away)
        threshold += 0.12
        if roll < threshold:
            if self._is_on_ledge():
                # Walk on ledge
                ledge = self.current_ledge
                walk_range = ledge.x_max - ledge.x_min - self.sprite_w
                if walk_range > 20:
                    self.target_x = random.uniform(
                        ledge.x_min, ledge.x_max - self.sprite_w
                    )
                    self._enter_state("WALK")
                    return
            else:
                self.target_x = max(
                    20.0,
                    min(float(self.screen_w - self.sprite_w - 20),
                        self.x_pos + random.choice([-1, 1]) * random.randint(60, 160))
                )
                self._enter_state("WALK")
                return

        # Stalk cursor: 6% chance (if cursor is in mid-range)
        threshold += 0.06
        if roll < threshold and 40 < cursor_dist < 300:
            if self.is_ghost:
                self._enter_state("RUN")
            else:
                self._enter_state("STALK")
            return

        # Climb: 5% chance (only if cat/non-ghost, climbing enabled, near edge)
        threshold += 0.05
        if roll < threshold and self.climb_enabled and not self.is_ghost:
            if self._try_start_climb():
                return

        # If forced (max duration), pick walk as default
        if force:
            self.target_x = max(
                20.0,
                min(float(self.screen_w - self.sprite_w - 20),
                    self.x_pos + random.choice([-1, 1]) * random.randint(40, 120))
            )
            self._enter_state("WALK")

    # ---- FALL physics ----
    def _tick_fall(self):
        """Apply gravity, check for landing on ledges or floor."""
        self.vy = min(self.vy + GRAVITY, TERMINAL_VEL)
        self.y_pos += self.vy

        # Find landing surface
        landing_y = self.floor_y
        if self.tracker:
            try:
                landing_y = self.tracker.find_landing_y(
                    self.x_pos, self.y_pos, self.sprite_w, self.sprite_h,
                    self.floor_y
                )
            except Exception:
                landing_y = self.floor_y

        # Have we reached or passed the landing surface?
        if self.y_pos >= landing_y:
            self.y_pos = landing_y
            self.vy = 0.0

            # Determine if we landed on a ledge or the floor
            if landing_y < self.floor_y - 5 and self.tracker:
                # Landed on a window titlebar – find which ledge
                self._find_and_set_current_ledge()
                self._enter_state("PERCH")
                self._speak_contextual("drop")
            else:
                # Landed on floor
                self.current_ledge = None
                self._enter_sit()
                self._speak_contextual("drop")

        # Clamp X
        self.x_pos = max(0.0, min(float(self.screen_w - self.sprite_w), self.x_pos))

    def _find_and_set_current_ledge(self):
        """Find the WalkableLedge at current position and set it."""
        if not self.tracker:
            return
        ledges = self.tracker.get_walkable_ledges()
        pet_bottom = self.y_pos + self.sprite_h
        for ledge in ledges:
            if ledge.is_floor:
                continue
            if (abs(ledge.y - pet_bottom) < 8 and
                    ledge.x_min <= self.x_pos + self.sprite_w // 2 <= ledge.x_max):
                self.current_ledge = ledge
                return

    # ---- CLIMB mechanics ----
    def _try_start_climb(self):
        """Attempt to find a nearby climbable edge and start climbing.
        Returns True if climb started.
        """
        if not self.tracker:
            return False

        try:
            edge = self.tracker.find_nearby_climbable(
                self.x_pos, self.y_pos, self.sprite_w, self.sprite_h,
                reach_px=35.0
            )
        except Exception:
            return False

        if edge is None:
            return False

        # Must have somewhere to climb to (at least some height)
        climb_height = edge.y_bottom - edge.y_top
        if climb_height < self.sprite_h:
            return False

        self.climb_target_edge = edge
        self.climb_target_y = float(edge.y_top)
        self._enter_state("CLIMB")

        # Position pet against the edge
        if edge.is_left_edge:
            # Pet is to the right of a left edge
            self.x_pos = float(edge.x)
        else:
            # Pet is to the left of a right edge
            self.x_pos = float(edge.x - self.sprite_w)

        self._speak_contextual("climb")
        return True

    def _tick_climb(self):
        """Move the pet upward along a climbable edge."""
        if self.climb_target_edge is None:
            self._enter_sit()
            return

        # Climb upward
        self.y_pos -= CLIMB_SPEED

        # Reached the top?
        target_perch_y = self.climb_target_y - self.sprite_h
        if self.y_pos <= target_perch_y:
            self.y_pos = target_perch_y

            # Try to find a walkable ledge at the top of this edge
            if self.tracker:
                self._find_and_set_current_ledge()

            if self.current_ledge and not self.current_ledge.is_floor:
                self._enter_state("PERCH")
                self._speak_contextual("perch")
            else:
                # No ledge found at top, just sit
                self._enter_sit()

            self.climb_target_edge = None
            self.climb_target_y = None
            return

        # Safety: max climb duration (10 seconds)
        if self.state_timer > 200:
            self.climb_target_edge = None
            self.climb_target_y = None
            self._enter_fall()

    # ---- PERCH mechanics ----
    def _tick_perch(self, cursor_dx, cursor_dist):
        """Handle behavior while perched on a window titlebar."""
        # Validate that the ledge still exists
        if not self._validate_current_ledge():
            # Window moved or closed – fall!
            self.current_ledge = None
            self.vy = 0.0
            self._enter_fall()
            return

        # Sit on the ledge
        ledge = self.current_ledge
        self.y_pos = float(ledge.y - self.sprite_h)

        # Clamp to ledge bounds
        self.x_pos = max(float(ledge.x_min),
                         min(float(ledge.x_max - self.sprite_w), self.x_pos))

        # After minimum duration, might walk, sit, or jump off
        min_dur = STATE_MIN_DURATION.get("PERCH", 80)
        max_dur = STATE_MAX_DURATION.get("PERCH", 200)

        if self.state_timer >= min_dur:
            if (self.state_timer - min_dur) % TRANSITION_EVAL_INTERVAL == 0:
                roll = random.random()
                if roll < 0.10:
                    # Walk on the ledge
                    walk_range = ledge.x_max - ledge.x_min - self.sprite_w
                    if walk_range > 20:
                        self.target_x = random.uniform(
                            ledge.x_min, ledge.x_max - self.sprite_w
                        )
                        self._enter_state("WALK")
                        return
                elif roll < 0.15 or self.state_timer >= max_dur:
                    # Jump off (fall to floor or another ledge)
                    self.current_ledge = None
                    self.vy = 0.0
                    self._enter_fall()
                    return

    # =================================================================
    # Painting
    # =================================================================

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        frame = self.get_current_frame()
        # Sprite is always drawn at the bottom of the widget
        sprite_y = self.height() - self.sprite_h
        if frame:
            painter.drawPixmap(0, sprite_y, frame)

        # Heart above sprite
        if self.heart_timer > 0 and self.heart_pixmap:
            hx = self.sprite_w // 2 - self.heart_pixmap.width() // 2
            hy = sprite_y - self.heart_pixmap.height() + 6
            painter.drawPixmap(hx, max(0, hy), self.heart_pixmap)

        # Speech bubble (drawn above the sprite, at the top of the widget)
        if self.speech_text and self.speech_lines:
            self._paint_speech_bubble(painter)

        painter.end()

    def _paint_speech_bubble(self, painter):
        """Draw the speech bubble at the top of the widget with word-wrapped text."""
        painter.setFont(self.speech_font)
        fm = painter.fontMetrics()

        bw = self.speech_bubble_w
        bh = self.speech_bubble_h - SPEECH_TAIL_H  # bubble body height

        # Center bubble horizontally over sprite
        box_x = max(0, (self.width() - bw) // 2)
        box_y = 0

        # Draw bubble background
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.setPen(QColor(30, 24, 30))
        painter.drawRoundedRect(
            box_x, box_y, bw, bh,
            SPEECH_BUBBLE_RADIUS, SPEECH_BUBBLE_RADIUS
        )

        # Draw tiny tail (triangle pointing down)
        tail_x = box_x + bw // 2
        tail_top = box_y + bh
        painter.setBrush(QColor(255, 255, 255, 235))
        from PyQt5.QtGui import QPolygon
        from PyQt5.QtCore import QPoint as QP
        tail = QPolygon([
            QP(tail_x - 4, tail_top),
            QP(tail_x + 4, tail_top),
            QP(tail_x, tail_top + SPEECH_TAIL_H),
        ])
        painter.drawPolygon(tail)

        # Draw text lines
        painter.setPen(QColor(30, 24, 30))
        line_h = fm.height()
        text_y = box_y + SPEECH_PADDING_Y + fm.ascent()
        for line in self.speech_lines:
            painter.drawText(box_x + SPEECH_PADDING_X, int(text_y), line)
            text_y += line_h

    # =================================================================
    # Mouse Events
    # =================================================================

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.drag_offset = event.globalPos() - self.pos()
            self._enter_state("DRAG")
            self.vy = 0.0

            # Record drag start for interaction tracking
            if self.interaction:
                self.interaction.record_drag_start(self.y_pos)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            new_pos = event.globalPos() - self.drag_offset
            if (new_pos - self.pos()).manhattanLength() > 4:
                self.dragging = True
            self.x_pos = float(new_pos.x())
            # Account for bubble offset: widget y includes bubble height
            bubble_h = self.speech_bubble_h if self.speech_text else 0
            self.y_pos = float(new_pos.y() + bubble_h)
            self._sync_widget_geometry()
            self.last_activity_tick = self.tick_count

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            was_dragging = self.dragging
            self.dragging = False

            if not was_dragging:
                # It was a click (pet), not a drag
                self.heart_timer = 20
                self.energy = min(100.0, self.energy + 15)

                # Record pet interaction
                if self.interaction:
                    event_type = self.interaction.record_pet()
                    self._speak_contextual(event_type)
                else:
                    self.request_dialogue()
                self._enter_sit()
                return

            # ---- Released after dragging ----
            # Record drag release for interaction tracking
            if self.interaction:
                drop_event = self.interaction.record_drag_release(
                    self.y_pos, float(self.screen_h)
                )
            else:
                drop_event = None

            if self.is_ghost:
                # Ghost: float smoothly back to hover position
                # Don't snap, the FSM hover logic will pull it back gradually
                self.ghost_hover_y = self.y_pos  # start hovering from drop point
                # Gradually return to normal hover near floor
                self.ghost_hover_y = self.floor_y - 6.0
                self._enter_sit()
            else:
                # Non-ghost: enter FALL state to drop with gravity
                self.vy = 0.0  # start from rest
                self.current_ledge = None
                self._enter_fall()

    # =================================================================
    # Context Menu
    # =================================================================

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        # ---- Skin submenu ----
        skin_menu = menu.addMenu("Switch Companion")
        for name in self.available_skins:
            act = QAction(name.capitalize(), self)
            act.triggered.connect(
                lambda _checked, n=name: self._switch_skin(n)
            )
            skin_menu.addAction(act)

        # ---- Scale submenu ----
        scale_menu = menu.addMenu("Scale")
        for label, factor in SCALE_PRESETS.items():
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.scale_factor == factor)
            act.triggered.connect(
                lambda _checked, f=factor: self._set_scale(f)
            )
            scale_menu.addAction(act)

        menu.addSeparator()

        # ---- Climb Windows toggle ----
        climb_act = QAction("Climb Windows", self)
        climb_act.setCheckable(True)
        climb_act.setChecked(self.climb_enabled)
        climb_act.triggered.connect(
            lambda checked: setattr(self, "climb_enabled", checked)
        )
        menu.addAction(climb_act)

        # ---- Speak ----
        speak_act = QAction("Speak", self)
        speak_act.triggered.connect(
            lambda: (setattr(self, "heart_timer", 20), self.request_dialogue())
        )
        menu.addAction(speak_act)

        # ---- Reset Position ----
        reset_act = QAction("Reset Position", self)
        reset_act.triggered.connect(self._reset_position)
        menu.addAction(reset_act)

        menu.addSeparator()

        # ---- Exit ----
        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(QApplication.quit)
        menu.addAction(exit_act)

        menu.exec_(event.globalPos())

    def _switch_skin(self, name):
        """Switch companion skin and reset to floor."""
        self.load_skin(name)
        self.current_ledge = None
        self.y_pos = self.floor_y
        self._enter_sit()
        self._sync_widget_geometry()

    def _set_scale(self, factor):
        """Change scale factor, reload skin, reset position."""
        self.scale_factor = factor
        self.load_skin(self.current_skin)
        self.current_ledge = None
        self.y_pos = self.floor_y
        self._enter_sit()
        self._sync_widget_geometry()

    def _reset_position(self):
        """Drop pet to floor center."""
        self.x_pos = float(self.screen_w // 2 - self.sprite_w // 2)
        self.y_pos = self.floor_y
        self.current_ledge = None
        self.vy = 0.0
        self._enter_sit()
        self._sync_widget_geometry()


# =====================================================================
# Entry Point
# =====================================================================

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    start_skin = "cat"
    if os.path.isdir(SKINS_DIR):
        found = sorted(
            d for d in os.listdir(SKINS_DIR)
            if os.path.isdir(os.path.join(SKINS_DIR, d))
        )
        if found:
            start_skin = "cat" if "cat" in found else found[0]

    _pet = DesktopPet(skin=start_skin, scale=2)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
