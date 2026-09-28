import sys
import base64
import ctypes

from PyQt5.QtCore import Qt, QBuffer, QIODevice
from PyQt5.QtGui import QPainter, QColor, QPixmap

IS_WIN = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")

try:
    import psutil
except Exception:
    psutil = None

_xdisplay = None


def _proc_name(pid):
    if not psutil or not pid:
        return ""
    try:
        return psutil.Process(pid).name()
    except Exception:
        return ""


# ---- Windows ----
def _win_active():
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return buf.value, _proc_name(pid.value)
    except Exception:
        return None, None


def _win_list():
    import ctypes.wintypes as wt
    out = []
    try:
        user32 = ctypes.windll.user32
        EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

        def cb(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            rect = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append({"title": buf.value, "process": _proc_name(pid.value),
                        "rect": (rect.left, rect.top, rect.right, rect.bottom)})
            return True

        user32.EnumWindows(EnumProc(cb), 0)
    except Exception:
        return []
    return out


# ---- Linux / X11 (best effort -- unavailable under pure Wayland) ----
def _get_xlib():
    global _xdisplay
    if _xdisplay is not None:
        return _xdisplay
    try:
        from Xlib import display
        _xdisplay = display.Display()
    except Exception:
        _xdisplay = False
    return _xdisplay or None


def _linux_active():
    d = _get_xlib()
    if not d:
        return None, None
    try:
        root = d.screen().root
        active_atom = d.intern_atom("_NET_ACTIVE_WINDOW")
        prop = root.get_full_property(active_atom, 0)
        if not prop or not prop.value:
            return None, None
        window = d.create_resource_object("window", prop.value[0])
        name = window.get_wm_name()
        pid_atom = d.intern_atom("_NET_WM_PID")
        pid_prop = window.get_full_property(pid_atom, 0)
        pid = pid_prop.value[0] if pid_prop else None
        return name, _proc_name(pid)
    except Exception:
        return None, None


def _linux_list():
    d = _get_xlib()
    if not d:
        return []
    out = []
    try:
        root = d.screen().root
        list_atom = d.intern_atom("_NET_CLIENT_LIST")
        prop = root.get_full_property(list_atom, 0)
        if not prop:
            return []
        for w_id in prop.value:
            try:
                window = d.create_resource_object("window", w_id)
                name = window.get_wm_name() or ""
                geom = window.get_geometry()
                abs_pos = root.translate_coords(window, 0, 0)
                if not abs_pos:
                    continue
                x, y = abs_pos.x, abs_pos.y
                pid_atom = d.intern_atom("_NET_WM_PID")
                pid_prop = window.get_full_property(pid_atom, 0)
                pid = pid_prop.value[0] if pid_prop else None
                out.append({"title": name, "process": _proc_name(pid),
                            "rect": (x, y, x + geom.width, y + geom.height)})
            except Exception:
                continue
    except Exception:
        return []
    return out


def get_active_window_info():
    if IS_WIN:
        return _win_active()
    if IS_LINUX:
        return _linux_active()
    return None, None


def list_windows():
    if IS_WIN:
        return _win_list()
    if IS_LINUX:
        return _linux_list()
    return []


def window_detection_available():
    if IS_WIN:
        return True
    if IS_LINUX:
        return _get_xlib() is not None
    return False


def _is_blocked(title, process, blocklist):
    title = (title or "").lower()
    process = (process or "").lower()
    for entry in blocklist:
        e = (entry or "").strip().lower()
        if e and (e in title or e in process):
            return True
    return False


def capture_with_redaction(app, blocklist, jpeg_quality=70):
    blocklist = blocklist or []
    active_title, active_proc = get_active_window_info()
    if blocklist and not window_detection_available():
        return None
    if _is_blocked(active_title, active_proc, blocklist):
        return None

    screen = app.primaryScreen()
    if screen is None:
        return None
    pixmap = screen.grabWindow(0)
    if pixmap is None or pixmap.isNull():
        return None

    if blocklist:
        hits = [w for w in list_windows() if _is_blocked(w.get("title"), w.get("process"), blocklist)]
        if hits:
            image = pixmap.toImage()
            painter = QPainter(image)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0))
            for w in hits:
                x0, y0, x1, y1 = w["rect"]
                if x1 > x0 and y1 > y0:
                    painter.drawRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))
            painter.end()
            pixmap = QPixmap.fromImage(image)

    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    pixmap.save(buf, "JPEG", jpeg_quality)
    data = bytes(buf.data())
    buf.close()
    if not data:
        return None
    return base64.b64encode(data).decode("ascii")
