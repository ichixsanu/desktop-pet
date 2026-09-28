"""Window tracking for the desktop pet.

One implementation, three consumers: the pet's physics (ledges, edges,
landing), the contextual dialogue (what window is focused), and screenshot
redaction. Everything is cached, and the OS query can be pushed onto a
background thread so the GUI never blocks on an X11/Win32 round trip.

Platform notes:
- Windows: ctypes (user32 + dwmapi). Skips minimized, cloaked, invisible,
  transparent and desktop windows. DWM extended frame bounds are used for
  the rect so the pet perches on the visible titlebar, not the shadow.
- Linux: python-xlib, when available. Prefers `_NET_WM_NAME` over the legacy
  `WM_NAME` (modern GTK4/Qt/Electron windows only set the former, and
  reading only `WM_NAME` is why window-aware dialogue was dead on Linux).
- Wayland: cannot be enumerated by design. `detection_is_complete()` returns
  False for any Wayland session so privacy-sensitive callers can fail
  closed instead of believing they filtered something they never saw.

Coordinate space: OS window APIs report native pixels, Qt reports logical
pixels. On a HiDPI display those differ by `devicePixelRatio`, so the pet
calls `set_coordinate_scale()` once at startup and every rect is converted
into Qt's space here. Everything above this module is Qt-logical.
"""

from __future__ import annotations

import os
import sys
import time
import threading
from dataclasses import dataclass
from typing import Any, List, NamedTuple, Optional, Sequence, Tuple, Union

IS_WIN = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")

try:
    import psutil
except Exception:
    psutil = None


def _get_process_name(pid: Optional[int]) -> str:
    """Safely get a process name from a PID."""
    if not psutil or not pid:
        return ""
    try:
        return psutil.Process(pid).name()
    except Exception:
        return ""


# =====================================================================
# Data structures
# =====================================================================

@dataclass
class WindowInfo:
    """A window the pet can see. Rect is (left, top, right, bottom)."""
    id: Union[int, str] = 0
    title: str = ""
    rect: Tuple[int, int, int, int] = (0, 0, 0, 0)
    process: str = ""
    pid: int = 0

    @property
    def left(self) -> int:
        return self.rect[0]

    @property
    def top(self) -> int:
        return self.rect[1]

    @property
    def right(self) -> int:
        return self.rect[2]

    @property
    def bottom(self) -> int:
        return self.rect[3]

    @property
    def width(self) -> int:
        return max(0, self.rect[2] - self.rect[0])

    @property
    def height(self) -> int:
        return max(0, self.rect[3] - self.rect[1])


class WalkableLedge(NamedTuple):
    """Horizontal surface segment the pet can stand on."""
    y: int
    x_min: int
    x_max: int
    is_taskbar: bool = False
    is_floor: bool = False

    @property
    def width(self) -> int:
        return max(0, self.x_max - self.x_min)

    def holds_center(self, center_x: float) -> bool:
        return self.x_min <= center_x <= self.x_max

    def holds_any(self, left: float, right: float) -> bool:
        """True when [left, right] overlaps the ledge horizontally."""
        return min(right, self.x_max) - max(left, self.x_min) > 0


class ClimbableEdge(NamedTuple):
    """Vertical segment the pet can climb.

    `is_left_edge` is True for a window's left border (its inside is to the
    right), False for its right border.
    """
    x: int
    y_bottom: int
    y_top: int
    is_left_edge: bool
    distance: float = 0.0
    is_screen_edge: bool = False

    @property
    def height(self) -> int:
        return max(0, self.y_bottom - self.y_top)


class WindowSnapshot(NamedTuple):
    """One coherent view of the desktop, computed once per poll."""
    windows: List[WindowInfo]
    taskbar: Optional[Tuple[int, int, int, int]]
    ledges: List[WalkableLedge]
    edges: List[ClimbableEdge]
    screen_rect: Optional[Tuple[int, int, int, int]]
    at: float
    detection_works: bool
    active: Optional[WindowInfo] = None
    detection_complete: bool = False


# =====================================================================
# Windows backend (ctypes)
# =====================================================================

import ctypes
from ctypes import wintypes

DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002

MIN_WINDOW_WIDTH = 60
MIN_WINDOW_HEIGHT = 50


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _win32_ex_style(hwnd) -> int:
    """GetWindowLongPtrW on 64-bit, GetWindowLongW on 32-bit.

    Coerced to int on purpose: a non-integer result would make every bit test
    below truthy and silently filter out every window.
    """
    try:
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            value = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        else:
            value = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        return int(value) & 0xFFFFFFFF
    except Exception:
        return 0


def _win32_list_windows(min_width: int = MIN_WINDOW_WIDTH,
                        min_height: int = MIN_WINDOW_HEIGHT
                        ) -> Tuple[List[WindowInfo], Optional[Tuple[int, int, int, int]]]:
    """List uncloaked, visible, non-minimized top-level windows."""
    if not IS_WIN:
        return [], None

    windows: List[WindowInfo] = []
    taskbar_rect: Optional[Tuple[int, int, int, int]] = None

    try:
        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi

        hwnd_taskbar = user32.FindWindowW("Shell_TrayWnd", None)
        if hwnd_taskbar and user32.IsWindowVisible(hwnd_taskbar):
            tb_rect = _RECT()
            user32.GetWindowRect(hwnd_taskbar, ctypes.byref(tb_rect))
            if tb_rect.right > tb_rect.left and tb_rect.bottom > tb_rect.top:
                taskbar_rect = (tb_rect.left, tb_rect.top, tb_rect.right, tb_rect.bottom)

        WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
        EnumWindowsProc = WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def enum_cb(hwnd, _lparam) -> bool:
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                if user32.IsIconic(hwnd):
                    return True

                length = user32.GetWindowTextLengthW(hwnd)
                if length == 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if not title or title == "Program Manager":
                    return True

                cls_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls_buf, 256)
                cls_name = cls_buf.value
                if cls_name in ("Progman", "WorkerW"):
                    return True

                if cls_name in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
                    rect = _RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    if rect.right > rect.left and rect.bottom > rect.top:
                        if taskbar_rect is None:
                            taskbar_rect = (rect.left, rect.top, rect.right, rect.bottom)
                    return True

                # Cloaked (Windows 8+ virtual desktop, UWP splash)
                cloaked = ctypes.c_int(0)
                try:
                    hr = dwmapi.DwmGetWindowAttribute(
                        hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
                    )
                    if hr == 0 and cloaked.value != 0:
                        return True
                except Exception:
                    pass

                # Click-through and fully transparent windows
                ex_style = _win32_ex_style(hwnd)
                if ex_style & WS_EX_TRANSPARENT:
                    return True
                if ex_style & WS_EX_LAYERED:
                    try:
                        cr_key = wintypes.COLORREF()
                        alpha = wintypes.BYTE()
                        flags = wintypes.DWORD()
                        if user32.GetLayeredWindowAttributes(
                            hwnd, ctypes.byref(cr_key), ctypes.byref(alpha), ctypes.byref(flags)
                        ):
                            if (flags.value & LWA_ALPHA) and alpha.value == 0:
                                return True
                    except Exception:
                        pass

                rect = _RECT()
                hr = -1
                try:
                    hr = dwmapi.DwmGetWindowAttribute(
                        hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)
                    )
                except Exception:
                    pass
                if hr != 0:
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))

                left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
                if right - left <= 0 or bottom - top <= 0:
                    return True
                if right - left < min_width or bottom - top < min_height:
                    return True

                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                windows.append(WindowInfo(
                    id=int(hwnd), title=title,
                    rect=(left, top, right, bottom),
                    process=_get_process_name(pid.value), pid=int(pid.value),
                ))
            except Exception:
                pass
            return True

        user32.EnumWindows(EnumWindowsProc(enum_cb), 0)
    except Exception:
        return [], taskbar_rect

    return windows, taskbar_rect


def _win32_active_window() -> Optional[WindowInfo]:
    """The focused window, or None."""
    if not IS_WIN:
        return None
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return None
        rect = _RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return WindowInfo(
            id=int(hwnd), title=title,
            rect=(rect.left, rect.top, rect.right, rect.bottom),
            process=_get_process_name(pid.value), pid=int(pid.value),
        )
    except Exception:
        return None


# =====================================================================
# Linux backend (Xlib, Wayland-safe)
# =====================================================================

_xlib_display = None
_xlib_init_attempted = False
_xlib_lock = threading.Lock()


def _get_xlib():
    """Lazily connect to the X server, or return None.

    Never called from the GUI thread once the background poller is running.
    """
    global _xlib_display, _xlib_init_attempted
    with _xlib_lock:
        if _xlib_init_attempted:
            return _xlib_display
        _xlib_init_attempted = True
        if not IS_LINUX:
            return None
        if not os.environ.get("DISPLAY") and os.environ.get("WAYLAND_DISPLAY"):
            return None
        try:
            from Xlib import display as xdisplay
            _xlib_display = xdisplay.Display()
        except Exception:
            _xlib_display = None
        return _xlib_display


def wayland_session() -> bool:
    """True in any Wayland session (native or XWayland hybrid)."""
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def _detection_is_complete() -> bool:
    """Whether we can see *every* window on the desktop.

    Wayland deliberately hides other clients' windows from ordinary
    applications. Under XWayland we can still see X clients, which is worse
    than useless for privacy: the caller believes it filtered the desktop
    when native Wayland windows were never listed at all. So any Wayland
    session reports incomplete and privacy-sensitive callers must refuse.
    """
    if IS_WIN:
        return True
    if wayland_session():
        return False
    if IS_LINUX:
        return _get_xlib() is not None
    return False

def window_detection_available() -> bool:
    """Whether any OS window query works (subset of the desktop is fine)."""
    if IS_WIN:
        return True
    if IS_LINUX:
        return _get_xlib() is not None
    return False


def safe_translate_coords(root_window, client_window, x: int = 0, y: int = 0
                          ) -> Optional[Tuple[int, int]]:
    """Translate client_window coordinates into root space, tolerating windows
    that closed mid-query (BadWindow / BadDrawable)."""
    if root_window is None or client_window is None:
        return None
    try:
        coords = root_window.translate_coords(client_window, x, y)
        if coords is not None:
            return (coords.x, coords.y)
    except Exception:
        return None
    return None


# X11 atoms used by the tracker, interned once per refresh. Interning per
# window was an extra server round trip each time; and the display attached to
# a resource object is a _BaseDisplay, which has no intern_atom at all, so the
# atoms have to come from the real Display.
_X11_ATOM_NAMES = (
    "_NET_ACTIVE_WINDOW",
    "_NET_CLIENT_LIST",
    "_NET_CLIENT_LIST_STACKING",
    "_NET_FRAME_EXTENTS",
    "_NET_WM_NAME",
    "_NET_WM_PID",
    "_NET_WM_STATE",
    "_NET_WM_STATE_HIDDEN",
    "_NET_WM_WINDOW_TYPE",
    "_NET_WM_WINDOW_TYPE_DESKTOP",
    "_NET_WM_WINDOW_TYPE_DOCK",
    "_NET_WM_WINDOW_TYPE_NOTIFICATION",
    "_NET_WM_WINDOW_TYPE_SPLASH",
    "_NET_WM_WINDOW_TYPE_TOOLTIP",
    "_NET_WORKAREA",
)


def _intern_atoms(display) -> dict:
    atoms = {}
    for name in _X11_ATOM_NAMES:
        try:
            atoms[name] = display.intern_atom(name)
        except Exception:
            atoms[name] = 0
    return atoms


def _x11_window_name(win, atoms: dict) -> str:
    """Title of an X window.

    `_NET_WM_NAME` is the modern property and the only one set by GTK4, Qt and
    Electron; `get_wm_name()` reads the legacy `WM_NAME` which is empty for
    exactly those apps. Reading only WM_NAME is why window-aware dialogue and
    the foreground blocklist never fired on Linux.
    """
    name = ""
    try:
        prop = win.get_full_property(atoms["_NET_WM_NAME"], 0)
        if prop and prop.value:
            val = prop.value
            name = val.decode("utf-8", "replace") if isinstance(val, bytes) else str(val)
    except Exception:
        name = ""
    if not name:
        try:
            name = win.get_wm_name() or ""
        except Exception:
            name = ""
    if isinstance(name, bytes):
        name = name.decode("utf-8", "replace")
    return name.strip()


def _x11_window_pid(win, atoms: dict) -> int:
    try:
        prop = win.get_full_property(atoms["_NET_WM_PID"], 0)
        if prop and prop.value:
            return int(prop.value[0])
    except Exception:
        pass
    return 0


def _linux_list_windows(min_width: int = MIN_WINDOW_WIDTH,
                        min_height: int = MIN_WINDOW_HEIGHT
                        ) -> Tuple[List[WindowInfo], Optional[Tuple[int, int, int, int]]]:
    """List visible, non-desktop Linux windows."""
    d = _get_xlib()
    if not d:
        return [], None
    try:
        from Xlib import Xatom, error
    except Exception:
        return [], None

    windows: List[WindowInfo] = []
    taskbar_rect: Optional[Tuple[int, int, int, int]] = None

    try:
        screen = d.screen()
        root = screen.root
        atoms = _intern_atoms(d)

        # Panels reserve space outside _NET_WORKAREA; the gap is the panel.
        try:
            workarea = root.get_full_property(atoms["_NET_WORKAREA"], Xatom.CARDINAL)
            if workarea and len(workarea.value) >= 4:
                wa_x, wa_y, wa_w, wa_h = workarea.value[:4]
                if wa_y + wa_h < screen.height_in_pixels:
                    taskbar_rect = (wa_x, wa_y + wa_h, wa_x + wa_w, screen.height_in_pixels)
        except Exception:
            pass

        client_prop = None
        for atom_name in ("_NET_CLIENT_LIST_STACKING", "_NET_CLIENT_LIST"):
            try:
                prop = root.get_full_property(atoms[atom_name], Xatom.WINDOW)
                if prop and prop.value:
                    client_prop = prop
                    break
            except Exception:
                continue
        if not client_prop:
            return [], taskbar_rect

        atom_wm_state = atoms["_NET_WM_STATE"]
        atom_state_hidden = atoms["_NET_WM_STATE_HIDDEN"]
        atom_window_type = atoms["_NET_WM_WINDOW_TYPE"]
        atom_type_desktop = atoms["_NET_WM_WINDOW_TYPE_DESKTOP"]
        atom_type_dock = atoms["_NET_WM_WINDOW_TYPE_DOCK"]
        atom_type_splash = atoms["_NET_WM_WINDOW_TYPE_SPLASH"]
        atom_type_notification = atoms["_NET_WM_WINDOW_TYPE_NOTIFICATION"]
        atom_type_tooltip = atoms["_NET_WM_WINDOW_TYPE_TOOLTIP"]
        atom_frame_extents = atoms["_NET_FRAME_EXTENTS"]

        for wid in client_prop.value:
            try:
                win = d.create_resource_object("window", wid)

                try:
                    state_prop = win.get_full_property(atom_wm_state, Xatom.ATOM)
                    if state_prop and atom_state_hidden in state_prop.value:
                        continue
                except (error.BadWindow, error.BadDrawable, error.XError):
                    continue
                except Exception:
                    pass

                is_dock = False
                try:
                    type_prop = win.get_full_property(atom_window_type, Xatom.ATOM)
                    if type_prop and type_prop.value:
                        tvals = set(type_prop.value)
                        if atom_type_desktop in tvals:
                            continue
                        if atom_type_splash in tvals or atom_type_notification in tvals \
                                or atom_type_tooltip in tvals:
                            continue
                        is_dock = atom_type_dock in tvals
                except (error.BadWindow, error.BadDrawable, error.XError):
                    continue
                except Exception:
                    pass

                name = _x11_window_name(win, atoms)
                if not name and not is_dock:
                    continue

                try:
                    geom = win.get_geometry()
                except (error.BadWindow, error.BadDrawable, error.XError):
                    continue

                coords = safe_translate_coords(root, win, 0, 0)
                if coords is None:
                    continue
                cx, cy = coords

                frame_ext = [0, 0, 0, 0]  # left, right, top, bottom
                try:
                    fprop = win.get_full_property(atom_frame_extents, Xatom.CARDINAL)
                    if fprop and fprop.value and len(fprop.value) >= 4:
                        frame_ext = list(fprop.value[:4])
                except Exception:
                    pass

                left = cx - frame_ext[0]
                top = cy - frame_ext[2]
                right = cx + geom.width + frame_ext[1]
                bottom = cy + geom.height + frame_ext[3]
                if right - left <= 0 or bottom - top <= 0:
                    continue

                if is_dock:
                    if cy > screen.height_in_pixels // 2:
                        taskbar_rect = (left, top, right, bottom)
                    continue

                if right - left < min_width or bottom - top < min_height:
                    continue

                pid = _x11_window_pid(win, atoms)
                windows.append(WindowInfo(
                    id=int(wid), title=name, rect=(left, top, right, bottom),
                    process=_get_process_name(pid), pid=pid,
                ))
            except (error.BadWindow, error.BadDrawable, error.XError):
                continue
            except Exception:
                continue
    except Exception:
        return [], taskbar_rect

    return windows, taskbar_rect


def _linux_active_window() -> Optional[WindowInfo]:
    """The focused window per `_NET_ACTIVE_WINDOW`, or None."""
    d = _get_xlib()
    if not d:
        return None
    try:
        from Xlib import Xatom
    except Exception:
        return None
    try:
        root = d.screen().root
        atoms = _intern_atoms(d)
        prop = root.get_full_property(atoms["_NET_ACTIVE_WINDOW"], 0)
        if not prop or not prop.value:
            return None
        win = d.create_resource_object("window", prop.value[0])
        title = _x11_window_name(win, atoms)
        if not title:
            return None
        geom = win.get_geometry()
        coords = safe_translate_coords(root, win, 0, 0) or (0, 0)
        pid = _x11_window_pid(win, atoms)
        return WindowInfo(
            id=int(prop.value[0]), title=title,
            rect=(coords[0], coords[1], coords[0] + geom.width, coords[1] + geom.height),
            process=_get_process_name(pid), pid=pid,
        )
    except Exception:
        return None


# =====================================================================
# Screen geometry
# =====================================================================

def _qt_virtual_geometry() -> Optional[Tuple[int, int, int, int]]:
    """Union of all monitors, in Qt logical pixels."""
    try:
        if "PyQt5.QtWidgets" in sys.modules:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                screens = app.screens()
                if not screens:
                    return None
                rects = [s.geometry() for s in screens]
                left = min(r.left() for r in rects)
                top = min(r.top() for r in rects)
                right = max(r.right() for r in rects)
                bottom = max(r.bottom() for r in rects)
                return (left, top, right, bottom)
    except Exception:
        pass
    return None


def _win32_virtual_geometry() -> Optional[Tuple[int, int, int, int]]:
    if not IS_WIN:
        return None
    try:
        SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
        SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
        user32 = ctypes.windll.user32
        w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        if w > 0 and h > 0:
            return (x, y, x + w, y + h)
    except Exception:
        pass
    return None


def _x11_virtual_geometry() -> Optional[Tuple[int, int, int, int]]:
    if not IS_LINUX:
        return None
    try:
        d = _get_xlib()
        if d:
            root_geom = d.screen().root.get_geometry()
            return (0, 0, root_geom.width, root_geom.height)
    except Exception:
        pass
    return None


def virtual_screen_rect() -> Optional[Tuple[int, int, int, int]]:
    """(left, top, right, bottom) covering every monitor.

    Note this is the *virtual desktop*, not the primary screen: on a second
    monitor the primary screen's origin is not (0, 0), and mixing the two
    coordinate spaces is how the pet ends up walking off its own floor.
    """
    return (_qt_virtual_geometry() or _win32_virtual_geometry()
            or _x11_virtual_geometry())


# Kept for callers that specifically want the primary display.
def _get_primary_screen_geometry() -> Optional[Tuple[int, int, int, int]]:
    try:
        if "PyQt5.QtWidgets" in sys.modules:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                scr = app.primaryScreen()
                if scr:
                    g = scr.geometry()
                    return (g.x(), g.y(), g.x() + g.width(), g.y() + g.height())
    except Exception:
        pass
    if IS_WIN:
        try:
            user32 = ctypes.windll.user32
            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
            if w > 0 and h > 0:
                return (0, 0, w, h)
        except Exception:
            pass
    return _x11_virtual_geometry()


def _normalize_screen_rect(rect: Any) -> Optional[Tuple[int, int, int, int]]:
    """Normalize QRect / x,y,w,h / (l,t,r,b) into (left, top, right, bottom)."""
    if rect is None:
        return virtual_screen_rect()

    if all(hasattr(rect, a) for a in ("left", "top", "right", "bottom")):
        try:
            return (int(rect.left()), int(rect.top()), int(rect.right()), int(rect.bottom()))
        except TypeError:
            return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))

    if all(hasattr(rect, a) for a in ("x", "y", "width", "height")):
        try:
            x, y, w, h = int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())
        except TypeError:
            x, y, w, h = int(rect.x), int(rect.y), int(rect.width), int(rect.height)
        return (x, y, x + w, y + h)

    if isinstance(rect, (tuple, list)) and len(rect) == 4:
        return (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))

    return None


# =====================================================================
# WindowTracker
# =====================================================================

class WindowTracker:
    """Cached window/ledge/edge data for the pet.

    Read path (get_windows, get_walkable_ledges, ...) is a dict-free in-memory
    read of the last snapshot, so it is safe and cheap to call at 20 Hz.
    Write path (`_refresh`) is the only thing that talks to the OS; it runs on
    a background thread once `start_background()` is called, or inline on the
    calling thread while there is no poller.
    """

    def __init__(
        self,
        cache_interval: float = 1.5,
        min_window_width: int = MIN_WINDOW_WIDTH,
        min_window_height: int = MIN_WINDOW_HEIGHT,
        exclude_titles: Optional[Sequence[str]] = None,
        exclude_pids: Optional[Sequence[int]] = None,
        coordinate_scale: float = 1.0,
        ignore_windows: Optional[Sequence[str]] = None,
    ):
        self.cache_interval = max(0.1, float(cache_interval))
        self.min_window_width = min_window_width
        self.min_window_height = min_window_height
        self.exclude_titles = [t.lower() for t in (exclude_titles or []) if t]
        self.exclude_pids = {int(p) for p in (exclude_pids or []) if p}
        self.coordinate_scale = max(0.01, float(coordinate_scale))
        # Windows the pet may look at but must not stand on: matched on title
        # or process, applied only when building ledges and edges. These stay in
        # `get_windows()` on purpose -- screenshot redaction has to see every
        # window, including the ones the pet is ignoring.
        self.ignore_windows = [w.lower() for w in (ignore_windows or []) if w]

        self._screen_rect: Optional[Tuple[int, int, int, int]] = None
        self._snapshot = WindowSnapshot([], None, [], [], None, 0.0, False, None, False)
        self._lock = threading.RLock()
        # Serialises the OS query itself. An Xlib Display is not thread-safe,
        # so the poller and any inline refresh must never overlap.
        self._query_lock = threading.Lock()
        self._poller: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._background = False

        # Legacy attributes, kept so existing tests and callers that poke the
        # cache directly keep working.
        self._last_poll_time: float = 0.0
        self._cached_windows: List[WindowInfo] = []
        self._cached_taskbar: Optional[Tuple[int, int, int, int]] = None

    # ---- configuration -------------------------------------------------

    def set_coordinate_scale(self, scale: float) -> None:
        """Convert OS-native rects into Qt logical pixels (HiDPI)."""
        scale = max(0.01, float(scale))
        if abs(scale - self.coordinate_scale) < 1e-6:
            return
        self.coordinate_scale = scale
        self.invalidate_cache()

    def set_screen_rect(self, rect: Any) -> None:
        """Tell the tracker which display the pet is on, so ledges and edges
        are built for that monitor instead of the whole virtual desktop."""
        normalized = _normalize_screen_rect(rect)
        with self._lock:
            if normalized == self._screen_rect:
                return
            self._screen_rect = normalized
        self.invalidate_cache()

    def add_excluded_pid(self, pid: int) -> None:
        """Stop the pet from seeing (and perching on) its own window."""
        if pid:
            with self._lock:
                self.exclude_pids.add(int(pid))
            self.invalidate_cache()

    def set_ignored_windows(self, patterns: Optional[Sequence[str]]) -> None:
        """Windows the pet must not perch on or climb.

        They remain in `get_windows()`: ignoring a window is about where the
        pet may stand, not about whether it exists -- a redacted screenshot has
        to account for the very windows the pet is ignoring.
        """
        cleaned = [str(p).lower() for p in (patterns or []) if p and str(p).strip()]
        with self._lock:
            if cleaned == self.ignore_windows:
                return
            self.ignore_windows = cleaned
        self.invalidate_cache()

    def ignores(self, window) -> bool:
        """Whether a window is on the ignore list."""
        if not self.ignore_windows or window is None:
            return False
        haystack = (window.title or "").lower()
        process = (window.process or "").lower()
        return any(p in haystack or p in process for p in self.ignore_windows)

    def invalidate_cache(self) -> None:
        """Force the next query to re-read the OS.

        While a background poller is running, readers never trigger their own
        query, so an invalidation has to refresh inline or callers would keep
        seeing the stale snapshot for up to a full poll interval -- which is
        exactly when the caller needs the new geometry (a monitor was just
        plugged in). The refresh is serialised against the poller, so this
        stays a one-off cost on a rare event.
        """
        with self._lock:
            self._last_poll_time = 0.0
            self._snapshot = self._snapshot._replace(at=0.0)
            background = self._background
        if background:
            self._wake.set()
            try:
                self._refresh(force=True)
            except Exception:
                pass

    # ---- background polling --------------------------------------------

    def start_background(self, interval: Optional[float] = None) -> None:
        """Poll the OS on a worker thread so the GUI never blocks.

        After this, read calls are guaranteed not to touch the OS: they return
        the most recent snapshot, however old.
        """
        if self._poller is not None and self._poller.is_alive():
            return
        period = self.cache_interval if interval is None else max(0.1, float(interval))
        self._stop.clear()
        self._background = True

        def loop():
            while not self._stop.is_set():
                try:
                    self._refresh(force=True)
                except Exception:
                    pass
                self._wake.wait(period)
                self._wake.clear()

        self._poller = threading.Thread(target=loop, name="window-poller", daemon=True)
        self._poller.start()

    def stop_background(self) -> None:
        self._stop.set()
        self._wake.set()
        poller, self._poller = self._poller, None
        self._background = False
        if poller is not None and poller.is_alive():
            poller.join(timeout=1.0)

    # ---- refresh -------------------------------------------------------

    def _scaled(self, rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        if abs(self.coordinate_scale - 1.0) < 1e-6:
            return rect
        s = self.coordinate_scale
        return (int(round(rect[0] / s)), int(round(rect[1] / s)),
                int(round(rect[2] / s)), int(round(rect[3] / s)))

    def _query_os_windows(self) -> Tuple[List[WindowInfo], Optional[Tuple[int, int, int, int]]]:
        try:
            if IS_WIN:
                return _win32_list_windows(self.min_window_width, self.min_window_height)
            if IS_LINUX:
                return _linux_list_windows(self.min_window_width, self.min_window_height)
        except Exception:
            pass
        return [], None

    def _refresh(self, force: bool = False) -> WindowSnapshot:
        """Read the OS once and rebuild the whole snapshot."""
        now = time.monotonic()
        with self._lock:
            fresh = (now - self._last_poll_time) < self.cache_interval

        if fresh and not force:
            with self._lock:
                return self._snapshot

        # One Xlib Display, one lock. The window listing and the active-window
        # lookup must not interleave with another thread's use of it either,
        # or the connection can wedge rather than merely return bad data.
        with self._query_lock:
            raw_windows, taskbar = self._query_os_windows()
            try:
                active = _win32_active_window() if IS_WIN else (
                    _linux_active_window() if IS_LINUX else None)
            except Exception:
                active = None

        windows = []
        for w in raw_windows:
            if self.exclude_pids and w.pid in self.exclude_pids:
                continue
            if self.exclude_titles and any(t in w.title.lower() for t in self.exclude_titles):
                continue
            windows.append(WindowInfo(
                id=w.id, title=w.title, rect=self._scaled(w.rect),
                process=w.process, pid=w.pid,
            ))

        with self._lock:
            self._last_poll_time = time.monotonic()
            self._cached_windows = windows
            self._cached_taskbar = self._scaled(taskbar) if taskbar else None
            screen_rect = self._screen_rect or virtual_screen_rect()
            self._snapshot = WindowSnapshot(
                windows=windows,
                taskbar=self._cached_taskbar,
                ledges=self._build_ledges(windows, self._cached_taskbar, screen_rect,
                                          ignore=self.ignores),
                edges=self._build_edges(windows, screen_rect, include_screen_edges=True,
                                        ignore=self.ignores),
                screen_rect=screen_rect,
                at=self._last_poll_time,
                detection_works=window_detection_available(),
                active=None if active is None else WindowInfo(
                    id=active.id, title=active.title, rect=self._scaled(active.rect),
                    process=active.process, pid=active.pid),
                detection_complete=_detection_is_complete(),
            )
            return self._snapshot

    def _ensure_snapshot(self, force_refresh: bool = False) -> WindowSnapshot:
        with self._lock:
            background = self._background
        if background and not force_refresh:
            # A poller owns the OS queries; do not race it or block the GUI.
            with self._lock:
                return self._snapshot
        return self._refresh(force=force_refresh)

    # ---- geometry builders ---------------------------------------------

    @staticmethod
    def _build_ledges(windows, taskbar, screen_rect, ignore=None) -> List[WalkableLedge]:
        ledges: List[WalkableLedge] = []

        for w in windows:
            if ignore is not None and ignore(w):
                continue
            top_y, left_x, right_x = w.top, w.left, w.right
            if screen_rect:
                s_left, s_top, s_right, s_bottom = screen_rect
                # Skip windows on another monitor entirely: a "ledge" the pet
                # can never reach produces a phantom walkable surface.
                if w.right <= s_left or w.left >= s_right or w.bottom <= s_top or w.top >= s_bottom:
                    continue
                top_y = max(s_top, top_y)
                left_x = max(s_left, left_x)
                right_x = min(s_right, right_x)
            if right_x - left_x >= 20:
                ledges.append(WalkableLedge(y=top_y, x_min=left_x, x_max=right_x))

        if screen_rect:
            s_left, s_top, s_right, s_bottom = screen_rect
            if taskbar:
                tb_left, tb_top, tb_right, tb_bottom = taskbar
                if tb_top < s_bottom and tb_bottom >= s_bottom - 20 and tb_right > tb_left:
                    t_left = max(s_left, tb_left)
                    t_right = min(s_right, tb_right)
                    if t_right > t_left:
                        ledges.append(WalkableLedge(y=tb_top, x_min=t_left, x_max=t_right,
                                                    is_taskbar=True, is_floor=True))
                    if t_left > s_left:
                        ledges.append(WalkableLedge(y=s_bottom, x_min=s_left, x_max=t_left, is_floor=True))
                    if t_right < s_right:
                        ledges.append(WalkableLedge(y=s_bottom, x_min=t_right, x_max=s_right, is_floor=True))
                else:
                    ledges.append(WalkableLedge(y=s_bottom, x_min=s_left, x_max=s_right, is_floor=True))
            else:
                ledges.append(WalkableLedge(y=s_bottom, x_min=s_left, x_max=s_right, is_floor=True))

        ledges.sort(key=lambda item: (item.y, item.x_min))
        return ledges

    @staticmethod
    def _build_edges(windows, screen_rect, include_screen_edges: bool = True,
                     ignore=None) -> List[ClimbableEdge]:
        edges: List[ClimbableEdge] = []

        for w in windows:
            if ignore is not None and ignore(w):
                continue
            left_x, right_x, top_y, bot_y = w.left, w.right, w.top, w.bottom
            if screen_rect:
                s_left, s_top, s_right, s_bottom = screen_rect
                # Same off-screen rule as ledges, so the pet never tries to
                # climb a window on the other monitor.
                if w.right <= s_left or w.left >= s_right or w.bottom <= s_top or w.top >= s_bottom:
                    continue
                top_y = max(s_top, top_y)
                bot_y = min(s_bottom, bot_y)
            if bot_y - top_y >= 20:
                edges.append(ClimbableEdge(x=left_x, y_bottom=bot_y, y_top=top_y, is_left_edge=True))
                edges.append(ClimbableEdge(x=right_x, y_bottom=bot_y, y_top=top_y, is_left_edge=False))

        if include_screen_edges and screen_rect:
            s_left, s_top, s_right, s_bottom = screen_rect
            if s_bottom > s_top:
                edges.append(ClimbableEdge(x=s_left, y_bottom=s_bottom, y_top=s_top,
                                           is_left_edge=True, is_screen_edge=True))
                edges.append(ClimbableEdge(x=s_right, y_bottom=s_bottom, y_top=s_top,
                                           is_left_edge=False, is_screen_edge=True))

        return edges

    # ---- public read API ------------------------------------------------

    def get_snapshot(self) -> WindowSnapshot:
        return self._ensure_snapshot()

    def get_windows(self, force_refresh: bool = False) -> List[WindowInfo]:
        return list(self._ensure_snapshot(force_refresh).windows)

    def get_taskbar_rect(self, force_refresh: bool = False
                         ) -> Optional[Tuple[int, int, int, int]]:
        return self._ensure_snapshot(force_refresh).taskbar

    def get_active_window(self) -> Optional[WindowInfo]:
        """The focused window.

        Served from the snapshot when a background poller is running, because
        Xlib Display objects are not thread-safe and the poller owns ours. It
        is at most one poll interval stale, which is fine for "what am I
        looking at" dialogue and for a blocklist check.
        """
        with self._lock:
            if self._background:
                return self._snapshot.active
        try:
            if IS_WIN:
                return _win32_active_window()
            if IS_LINUX:
                return _linux_active_window()
        except Exception:
            pass
        return None

    def get_walkable_ledges(self, screen_rect: Any = None,
                            force_refresh: bool = False) -> List[WalkableLedge]:
        """Horizontal surfaces: window titlebars plus the taskbar/floor."""
        snapshot = self._ensure_snapshot(force_refresh)
        if screen_rect is None:
            return list(snapshot.ledges)
        normalized = _normalize_screen_rect(screen_rect)
        if normalized == snapshot.screen_rect:
            return list(snapshot.ledges)
        return self._build_ledges(snapshot.windows, snapshot.taskbar, normalized,
                                  ignore=self.ignores)

    def get_climbable_edges(self, screen_rect: Any = None,
                            include_screen_edges: bool = True,
                            force_refresh: bool = False) -> List[ClimbableEdge]:
        """Vertical surfaces: window borders plus the screen edges."""
        snapshot = self._ensure_snapshot(force_refresh)
        if screen_rect is None:
            edges = snapshot.edges
        else:
            normalized = _normalize_screen_rect(screen_rect)
            if normalized == snapshot.screen_rect:
                edges = snapshot.edges
            else:
                return self._build_edges(snapshot.windows, normalized,
                                         include_screen_edges, ignore=self.ignores)
        if not include_screen_edges:
            return [e for e in edges if not e.is_screen_edge]
        return list(edges)

    def find_landing_y(self, x: float, y: float, sprite_w: int, sprite_h: int,
                      floor_y: float, screen_rect: Any = None,
                      step: float = 0.0) -> float:
        """Y of the highest surface under the pet, or floor_y.

        Overlap (not centre containment) decides whether a ledge counts, so the
        pet can land on the overhang of a narrow window.

        `step` is how far the pet travels this frame. Without it, a pet that
        has already moved past a thin titlebar in the same tick finds the ledge
        "above" it, discards it, and tunnels straight through to the floor.
        """
        pet_left, pet_right = x, x + sprite_w
        tolerance = 2.0 + max(0.0, float(step))

        candidates: List[float] = []
        for ledge in self.get_walkable_ledges(screen_rect=screen_rect):
            if ledge.is_floor:
                continue
            if not ledge.holds_any(pet_left, pet_right):
                continue
            target_y = float(ledge.y - sprite_h)
            if target_y >= y - tolerance and target_y < floor_y:
                candidates.append(target_y)

        return min(candidates) if candidates else float(floor_y)

    def find_ledge_at(self, y: float, x: float, sprite_w: int,
                      screen_rect: Any = None) -> Optional[WalkableLedge]:
        """The ledge directly under the pet, matched on overlap like
        `find_landing_y` so the two can never disagree."""
        bottom = y
        center = x + sprite_w / 2.0
        best: Optional[WalkableLedge] = None
        for ledge in self.get_walkable_ledges(screen_rect=screen_rect):
            if ledge.is_floor:
                continue
            if abs(ledge.y - bottom) > 8:
                continue
            if ledge.holds_center(center) or ledge.holds_any(x, x + sprite_w):
                if best is None or ledge.y < best.y:
                    best = ledge
        return best

    def find_nearby_climbable(self, pet_x: float, pet_y: float, sprite_w: int,
                              sprite_h: int, reach_px: float = 30.0,
                              screen_rect: Any = None) -> Optional[ClimbableEdge]:
        """The closest climbable edge within reach of the pet."""
        pet_left, pet_right = pet_x, pet_x + sprite_w
        pet_top, pet_bottom = pet_y, pet_y + sprite_h
        center_x = (pet_left + pet_right) / 2.0

        best: Optional[ClimbableEdge] = None
        best_key: Optional[Tuple[float, int, int]] = None

        for edge in self.get_climbable_edges(screen_rect=screen_rect):
            y_min = min(edge.y_top, edge.y_bottom)
            y_max = max(edge.y_top, edge.y_bottom)
            if pet_bottom < y_min - reach_px or pet_top > y_max + reach_px:
                continue

            if edge.x < pet_left:
                dist = pet_left - edge.x
            elif edge.x > pet_right:
                dist = edge.x - pet_right
            else:
                dist = 0.0
            if dist > reach_px:
                continue

            # Deterministic tie-break: distance, then nearest-to-centre, then
            # left edge first. Previously ties went to whichever window the OS
            # happened to enumerate first, so the pet picked a different
            # window frame to climb on every launch.
            key = (dist, abs(edge.x - center_x), 0 if edge.is_left_edge else 1)
            if best_key is None or key < best_key:
                best_key = key
                best = ClimbableEdge(
                    x=edge.x, y_bottom=edge.y_bottom, y_top=edge.y_top,
                    is_left_edge=edge.is_left_edge, distance=dist,
                    is_screen_edge=edge.is_screen_edge,
                )

        return best

    def edge_still_present(self, edge: ClimbableEdge,
                           tolerance: int = 12) -> bool:
        """Whether the thing being climbed is still on screen.

        A window can close mid-climb; without this the cat scrambles up thin
        air for the rest of the timeout.
        """
        if edge is None:
            return False
        for candidate in self.get_climbable_edges():
            if abs(candidate.x - edge.x) > tolerance:
                continue
            if abs(candidate.y_top - edge.y_top) > tolerance:
                continue
            if abs(candidate.y_bottom - edge.y_bottom) > tolerance:
                continue
            if candidate.is_left_edge == edge.is_left_edge:
                return True
        return False


# =====================================================================
# Module-level convenience API
# =====================================================================

_default_tracker: Optional[WindowTracker] = None
_default_lock = threading.Lock()


def get_tracker() -> WindowTracker:
    """The global tracker singleton."""
    global _default_tracker
    with _default_lock:
        if _default_tracker is None:
            _default_tracker = WindowTracker()
        return _default_tracker


def list_windows(force_refresh: bool = False) -> List[WindowInfo]:
    return get_tracker().get_windows(force_refresh=force_refresh)


def get_active_window() -> Optional[WindowInfo]:
    return get_tracker().get_active_window()


def get_taskbar_rect(force_refresh: bool = False) -> Optional[Tuple[int, int, int, int]]:
    return get_tracker().get_taskbar_rect(force_refresh=force_refresh)


def get_walkable_ledges(screen_rect: Any = None, force_refresh: bool = False) -> List[WalkableLedge]:
    return get_tracker().get_walkable_ledges(screen_rect=screen_rect, force_refresh=force_refresh)


def get_climbable_edges(screen_rect: Any = None, include_screen_edges: bool = True,
                        force_refresh: bool = False) -> List[ClimbableEdge]:
    return get_tracker().get_climbable_edges(
        screen_rect=screen_rect, include_screen_edges=include_screen_edges,
        force_refresh=force_refresh)


def find_landing_y(x: float, y: float, sprite_w: int, sprite_h: int,
                   floor_y: float, screen_rect: Any = None,
                   step: float = 0.0) -> float:
    return get_tracker().find_landing_y(x=x, y=y, sprite_w=sprite_w, sprite_h=sprite_h,
                                        floor_y=floor_y, screen_rect=screen_rect,
                                        step=step)


def find_ledge_at(y: float, x: float, sprite_w: int, screen_rect: Any = None
                  ) -> Optional[WalkableLedge]:
    return get_tracker().find_ledge_at(y=y, x=x, sprite_w=sprite_w, screen_rect=screen_rect)


def find_nearby_climbable(pet_x: float, pet_y: float, sprite_w: int, sprite_h: int,
                          reach_px: float = 30.0, screen_rect: Any = None
                          ) -> Optional[ClimbableEdge]:
    return get_tracker().find_nearby_climbable(
        pet_x=pet_x, pet_y=pet_y, sprite_w=sprite_w, sprite_h=sprite_h,
        reach_px=reach_px, screen_rect=screen_rect)


def detection_is_complete() -> bool:
    """Public: can we see every window? False under Wayland, by design."""
    return _detection_is_complete()
