"""Screen capture with blocklist redaction and an OCR content filter.

Window enumeration lives in `window_tracker`; this module only grabs pixels.
Keeping one enumeration implementation matters for privacy, not just tidiness:
the two copies disagreed about what counts as a window, and the disagreeing
copy was the one deciding what to black out.

Capture has three gates, in order, and all of them are checked *before* any
pixels are read:

1. `redaction_guarantee` -- if a blocklist is configured the desktop has to be
   fully enumerable, or the capture is refused (Wayland fails closed).
2. The focused window must not match the blocklist.
3. After the grab, `ocr_guard` scans the redacted image and discards it when
   the text on screen looks sensitive.

Threading: `QScreen.grabWindow` returns a QPixmap, which is not safe off the
GUI thread, so `grab_screen_image()` must be called from the Qt main thread.
Everything after that -- redaction, OCR, JPEG encoding, base64 -- is QImage
work and belongs on a worker, which is where the 100-800ms used to be spent.
"""

import base64
import re
import sys
from typing import List, Optional, Tuple

from PyQt5.QtCore import QBuffer, QIODevice, QRect, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPixmap

try:
    import window_tracker
except Exception:  # pragma: no cover - the pet degrades without it
    window_tracker = None

try:
    import ocr_guard
except Exception:  # pragma: no cover
    ocr_guard = None


def _tracker():
    return window_tracker.get_tracker() if window_tracker else None


# =====================================================================
# Blocklist
# =====================================================================

# Entries can be plain fragments (the original behaviour: substring match on
# title or process) or prefixed to be specific. A process blocklist that
# over-matches is worse than useless -- "code" as a fragment also matches
# "vscode-server", and a capture the user expected to be allowed disappears.
#
#   proc:keepassxc      exact process name (case-insensitive, .exe ignored)
#   proc:code*          process name prefix
#   pid:1234            exact process id
#   title:inbox         substring of the window title only
#   re:^\((\d+)\)\s    regular expression against the window title
#   keepass             plain fragment: title or process, anywhere
PROCESS_PREFIXES = ("proc:", "process:")
TITLE_PREFIXES = ("title:",)
REGEX_PREFIXES = ("re:", "regex:")
PID_PREFIXES = ("pid:",)


def _base_process(process: str) -> str:
    name = (process or "").strip().lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name


def blocklist_match(title: str, process: str, blocklist, pid=None) -> Optional[str]:
    """The first entry that matches, or None.

    Entries are matched in order, so a specific rule placed above a broad one
    wins. Matching is case-insensitive throughout.
    """
    title = (title or "").lower()
    process_l = (process or "").lower()
    process_base = _base_process(process_l)
    if pid in (0, "0", None):
        pid = None
    else:
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            pid = None

    for entry in blocklist or []:
        if entry is None:
            continue
        raw = str(entry).strip()
        if not raw:
            continue
        lowered = raw.lower()

        if lowered.startswith(PROCESS_PREFIXES):
            wanted = _base_process(raw.split(":", 1)[1])
            if not wanted:
                continue
            if wanted.endswith("*"):
                if process_base.startswith(wanted[:-1]):
                    return raw
            elif wanted == process_base or wanted == process_l:
                return raw
            continue

        if lowered.startswith(PID_PREFIXES):
            try:
                wanted_pid = int(raw.split(":", 1)[1].strip())
            except (TypeError, ValueError):
                continue
            if pid is not None and pid == wanted_pid:
                return raw
            continue

        if lowered.startswith(TITLE_PREFIXES):
            wanted = lowered.split(":", 1)[1]
            if wanted and wanted in title:
                return raw
            continue

        if lowered.startswith(REGEX_PREFIXES):
            pattern = raw.split(":", 1)[1]
            try:
                if pattern and re.search(pattern, title, re.IGNORECASE):
                    return raw
            except re.error:
                continue
            continue

        if lowered in title or lowered in process_l:
            return raw
    return None


def is_blocked(title: str, process: str, blocklist, pid=None) -> bool:
    """Whether a window matches the blocklist. See `blocklist_match`."""
    return blocklist_match(title, process, blocklist, pid) is not None


def blocked_windows(blocklist) -> List:
    """Every currently-known window that matches the blocklist."""
    tracker = _tracker()
    if not tracker or not blocklist:
        return []
    return [w for w in tracker.get_windows()
            if is_blocked(w.title, w.process, blocklist, w.pid)]


def redaction_guarantee(blocklist) -> Tuple[bool, str]:
    """(safe_to_capture, reason).

    A blocklist is a promise that blocked windows never leave the machine. That
    promise can only be kept if we can actually see every window, so anything
    less than a complete view -- no window API at all, or Wayland with its
    deliberate refusal to enumerate other clients -- means capture is refused.
    """
    if not blocklist:
        return True, ""
    if window_tracker is None:
        return False, "window detection module unavailable"
    if not window_tracker.window_detection_available():
        return False, "no window API available (Wayland, headless, or unsupported)"
    if not window_tracker.detection_is_complete():
        return False, ("Wayland session: other applications' windows cannot be "
                       "enumerated, so blocked windows cannot be redacted")
    return True, ""


# =====================================================================
# Capture
# =====================================================================

def _target_screen(app, screen_rect=None):
    """The screen to grab: the one the pet is on, else the primary one."""
    if not app:
        return None
    try:
        screens = app.screens()
    except Exception:
        screens = []
    if not screens:
        return app.primaryScreen()
    if screen_rect:
        left, top, right, bottom = screen_rect
        center_x = (left + right) // 2
        center_y = (top + bottom) // 2
        for screen in screens:
            if screen.geometry().contains(center_x, center_y):
                return screen
    return app.primaryScreen()


def grab_screen_image(app, screen_rect=None) -> Optional[QImage]:
    """Grab the screen as a QImage. GUI THREAD ONLY (QPixmap under the hood)."""
    screen = _target_screen(app, screen_rect)
    if screen is None:
        return None
    try:
        pixmap: QPixmap = screen.grabWindow(0)
    except Exception:
        return None
    if pixmap is None or pixmap.isNull():
        return None
    try:
        return pixmap.toImage()
    except Exception:
        return None


def redact(image: QImage, blocklist, screen_rect=None) -> QImage:
    """Black out every blocked window. Safe on any thread.

    Window rects are in desktop coordinates while the image starts at the
    grabbed screen's origin, so they are translated before drawing: without
    this, a second monitor to the left of the primary shifted every redaction
    by the monitor's width and could leave a blocked window unblacked.
    """
    if image is None or image.isNull() or not blocklist:
        return image

    origin_x, origin_y = 0, 0
    if screen_rect:
        origin_x, origin_y = int(screen_rect[0]), int(screen_rect[1])

    targets = blocked_windows(blocklist)
    if not targets:
        return image

    painter = QPainter(image)
    try:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0))
        for win in targets:
            rect = QRect(win.left - origin_x, win.top - origin_y,
                         win.width, win.height).intersected(image.rect())
            if rect.width() > 0 and rect.height() > 0:
                painter.fillRect(rect, QColor(0, 0, 0))
    finally:
        painter.end()
    return image


def encode_jpeg_base64(image: QImage, jpeg_quality: int = 70) -> Optional[str]:
    """Encode a QImage to base64 JPEG. Safe on any thread."""
    if image is None or image.isNull():
        return None
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    try:
        if not image.save(buffer, "JPEG", int(jpeg_quality)):
            return None
        data = bytes(buffer.data())
    finally:
        buffer.close()
    if not data:
        return None
    return base64.b64encode(data).decode("ascii")


def scan_capture(image: QImage, ocr_config=None):
    """Run the OCR content filter over a redacted capture.

    Returns (ok, reason). Everything about the filter -- engine, rules,
    fail-closed behaviour -- lives in `ocr_guard`; this is just the wiring,
    and it tolerates the module being absent.
    """
    if ocr_guard is None:
        return True, ""
    try:
        verdict = ocr_guard.scan_image(image, ocr_config)
    except Exception:
        if isinstance(ocr_config, dict) and ocr_config.get("fail_closed", True):
            return False, "the OCR filter failed"
        return True, ""
    return bool(verdict.ok), verdict.reason


def capture_with_redaction(app, blocklist, jpeg_quality=70, screen_rect=None,
                           ocr_config=None):
    """Synchronous capture, redacted, OCR-filtered and encoded. Blocks caller.

    Kept for tests and one-off use; the pet uses grab_screen_image() on the
    GUI thread and then redaction/scan/encode off it.
    """
    blocklist = blocklist or []
    safe, reason = redaction_guarantee(blocklist)
    if not safe:
        return None

    image = grab_screen_image(app, screen_rect)
    if image is None:
        return None
    redact(image, blocklist, screen_rect)
    ok, _reason = scan_capture(image, ocr_config)
    if not ok:
        return None
    return encode_jpeg_base64(image, jpeg_quality)


def prepare_capture(app, blocklist, screen_rect=None, refresh_tracker=True):
    """(image, reason).

    GUI thread: checks the foreground window against the blocklist and grabs
    the pixels. Returns (None, reason) instead of capturing when the view of
    the desktop is not provably complete or the focused window is blocked.

    `refresh_tracker` re-reads the OS window list before deciding. The
    background poller's snapshot can be up to a poll interval old, and using it
    means a window opened (or focused) a second ago is checked against stale
    data. For a privacy gate the fresh read is worth the few milliseconds.
    """
    blocklist = blocklist or []
    safe, reason = redaction_guarantee(blocklist)
    if not safe:
        return None, reason

    tracker = _tracker()
    if tracker and blocklist:
        if refresh_tracker:
            try:
                tracker.get_windows(force_refresh=True)
            except Exception:
                pass
        active = tracker.get_active_window()
        if active and blocklist_match(active.title, active.process, blocklist,
                                      active.pid):
            return None, "focused window matches the blocklist"

    return grab_screen_image(app, screen_rect), ""
