"""Screen capture with blocklist redaction.

Window enumeration lives in `window_tracker`; this module only grabs pixels.
Keeping one enumeration implementation matters for privacy, not just tidiness:
the two copies disagreed about what counts as a window, and the disagreeing
copy was the one deciding what to black out.

Threading: `QScreen.grabWindow` returns a QPixmap, which is not safe off the
GUI thread, so `grab_screen_image()` must be called from the Qt main thread.
Everything after that -- redaction, JPEG encoding, base64 -- is QImage work and
belongs on a worker, which is where the 100-800ms used to be spent.
"""

import base64
import sys
from typing import List, Optional, Tuple

from PyQt5.QtCore import QBuffer, QIODevice, QRect, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPixmap

try:
    import window_tracker
except Exception:  # pragma: no cover - the pet degrades without it
    window_tracker = None


def _tracker():
    return window_tracker.get_tracker() if window_tracker else None


# =====================================================================
# Blocklist
# =====================================================================

def is_blocked(title: str, process: str, blocklist) -> bool:
    """Case-insensitive substring match on window title and process name."""
    title = (title or "").lower()
    process = (process or "").lower()
    for entry in blocklist or []:
        needle = (entry or "").strip().lower()
        if needle and (needle in title or needle in process):
            return True
    return False


def blocked_windows(blocklist) -> List:
    """Every currently-known window that matches the blocklist."""
    tracker = _tracker()
    if not tracker or not blocklist:
        return []
    return [w for w in tracker.get_windows()
            if is_blocked(w.title, w.process, blocklist)]


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


def capture_with_redaction(app, blocklist, jpeg_quality=70, screen_rect=None):
    """Synchronous capture, redacted and encoded. Blocks the caller.

    Kept for tests and one-off use; the pet uses grab_screen_image() on the
    GUI thread and then encode off it.
    """
    blocklist = blocklist or []
    safe, reason = redaction_guarantee(blocklist)
    if not safe:
        return None

    image = grab_screen_image(app, screen_rect)
    if image is None:
        return None
    redact(image, blocklist, screen_rect)
    return encode_jpeg_base64(image, jpeg_quality)


def prepare_capture(app, blocklist, screen_rect=None):
    """(image, reason).

    GUI thread: checks the foreground window against the blocklist and grabs
    the pixels. Returns (None, reason) instead of capturing when the view of
    the desktop is not provably complete or the focused window is blocked.
    """
    blocklist = blocklist or []
    safe, reason = redaction_guarantee(blocklist)
    if not safe:
        return None, reason

    tracker = _tracker()
    if tracker and blocklist:
        active = tracker.get_active_window()
        if active and is_blocked(active.title, active.process, blocklist):
            return None, "focused window matches the blocklist"

    return grab_screen_image(app, screen_rect), ""
