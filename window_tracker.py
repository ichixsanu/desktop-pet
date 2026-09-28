"""Window Tracker Module for Desktop Pets.

Provides a robust, lightweight, cross-platform window tracking system:
- Windows: Uses ctypes (user32, dwmapi) to find visible, unminimized,
  uncloaked windows with valid titles and bounding rects. Identifies
  taskbars (Shell_TrayWnd) and filters zero-size, transparent, or cloaked windows.
- Linux: Uses python-xlib (when available). Filters desktop windows, panels,
  and minimized windows (_NET_WM_STATE_HIDDEN). Handles dynamic window closing
  gracefully with BadWindow catching and safe coordinate translation.
- Fallback: Gracefully handles Wayland, headless, or unsupported systems by
  returning safe defaults without throwing exceptions or crashing.
- Caching: Efficiently caches window queries for a configurable interval (1.5 - 2.0s)
  so heavy OS operations never run on every animation frame.
- Pet Helpers:
    * get_walkable_ledges(screen_rect)
    * get_climbable_edges(screen_rect)
    * find_landing_y(x, y, sprite_w, sprite_h, floor_y)
    * find_nearby_climbable(pet_x, pet_y, sprite_w, sprite_h, reach_px)
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Any, List, NamedTuple, Optional, Sequence, Tuple, Union

IS_WIN = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")

# Optional psutil for process inspection
try:
    import psutil
except Exception:
    psutil = None


def _get_process_name(pid: Optional[int]) -> str:
    """Safely get process name from PID."""
    if not psutil or not pid:
        return ""
    try:
        return psutil.Process(pid).name()
    except Exception:
        return ""


# =====================================================================
# Data Structures
# =====================================================================

@dataclass
class WindowInfo:
    """Represents detected window information."""
    id: Union[int, str]
    title: str
    rect: Tuple[int, int, int, int]  # (left, top, right, bottom)
    process: str = ""
    is_taskbar: bool = False
    is_minimized: bool = False
    is_visible: bool = True

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

    def __getitem__(self, item: str) -> Any:
        """Allow dict-like indexing for backward compatibility."""
        if item == "id":
            return self.id
        elif item == "title":
            return self.title
        elif item == "rect":
            return self.rect
        elif item == "process":
            return self.process
        elif item == "is_taskbar":
            return self.is_taskbar
        elif item == "is_minimized":
            return self.is_minimized
        elif item == "is_visible":
            return self.is_visible
        raise KeyError(item)


class WalkableLedge(NamedTuple):
    """Horizontal surface segment (y, x_min, x_max)."""
    y: int
    x_min: int
    x_max: int
    is_taskbar: bool = False
    is_floor: bool = False

    @property
    def width(self) -> int:
        return max(0, self.x_max - self.x_min)


class ClimbableEdge(NamedTuple):
    """Vertical climbable segment (x, y_bottom, y_top, is_left_edge)."""
    x: int
    y_bottom: int
    y_top: int
    is_left_edge: bool
    distance: float = 0.0
    is_screen_edge: bool = False

    @property
    def height(self) -> int:
        return max(0, self.y_bottom - self.y_top)


# =====================================================================
# Windows Backend (ctypes)
# =====================================================================

import ctypes
from ctypes import wintypes

# Win32 Constants (safe to declare on any platform)
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
LWA_ALPHA = 0x00000002

class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _win32_list_windows(min_width: int = 50, min_height: int = 50) -> Tuple[List[WindowInfo], Optional[Tuple[int, int, int, int]]]:
    """List uncloaked, visible, non-minimized Windows windows using ctypes."""
    if not IS_WIN:
        return [], None

    windows: List[WindowInfo] = []
    taskbar_rect: Optional[Tuple[int, int, int, int]] = None

    try:
        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi

        # Check main taskbar
        hwnd_taskbar = user32.FindWindowW("Shell_TrayWnd", None)
        if hwnd_taskbar and user32.IsWindowVisible(hwnd_taskbar):
            tb_rect = _RECT()
            user32.GetWindowRect(hwnd_taskbar, ctypes.byref(tb_rect))
            if tb_rect.right > tb_rect.left and tb_rect.bottom > tb_rect.top:
                taskbar_rect = (tb_rect.left, tb_rect.top, tb_rect.right, tb_rect.bottom)

        WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
        EnumWindowsProc = WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def enum_cb(hwnd: int, _lparam: int) -> bool:
            nonlocal taskbar_rect
            try:
                # 1. Must be a valid visible window
                if not user32.IsWindowVisible(hwnd):
                    return True

                # 2. Must not be minimized (iconic)
                if user32.IsIconic(hwnd):
                    return True

                # 3. Check window title
                length = user32.GetWindowTextLengthW(hwnd)
                if length == 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if not title or title == "Program Manager":
                    return True

                # 4. Check class name for taskbars and shell desktop
                cls_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls_buf, 256)
                cls_name = cls_buf.value
                if cls_name in ("Progman", "WorkerW"):
                    return True

                # 5. Check cloaked status (Windows 8+)
                cloaked = ctypes.c_int(0)
                try:
                    hr = dwmapi.DwmGetWindowAttribute(
                        hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
                    )
                    if hr == 0 and cloaked.value != 0:
                        return True
                except Exception:
                    pass

                # 6. Check extended styles (layered transparent windows)
                try:
                    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    if ex_style & WS_EX_TRANSPARENT:
                        return True
                    if ex_style & WS_EX_LAYERED:
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

                # 7. Get window bounding rect (prefer DWM extended frame bounds)
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
                width = right - left
                height = bottom - top

                # 8. Filter zero or tiny size
                if width <= 0 or height <= 0:
                    return True

                # If it's a taskbar window
                is_taskbar = cls_name in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd")
                if is_taskbar:
                    if taskbar_rect is None:
                        taskbar_rect = (left, top, right, bottom)
                    return True

                if width < min_width or height < min_height:
                    return True

                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                proc = _get_process_name(pid.value)

                windows.append(
                    WindowInfo(
                        id=hwnd,
                        title=title,
                        rect=(left, top, right, bottom),
                        process=proc,
                        is_taskbar=False,
                        is_minimized=False,
                        is_visible=True,
                    )
                )
            except Exception:
                pass
            return True

        user32.EnumWindows(EnumWindowsProc(enum_cb), 0)
    except Exception:
        return [], taskbar_rect

    return windows, taskbar_rect


# =====================================================================
# Linux Backend (Xlib + Wayland safe fallback)
# =====================================================================

_xlib_display = None
_xlib_init_attempted = False


def _get_xlib():
    """Lazily initialize and return Xlib display, or None if unavailable/Wayland."""
    global _xlib_display, _xlib_init_attempted
    if _xlib_init_attempted:
        return _xlib_display

    _xlib_init_attempted = True
    if not IS_LINUX:
        _xlib_display = None
        return None

    # Check for headless or pure Wayland without DISPLAY
    display_env = os.environ.get("DISPLAY")
    if not display_env and os.environ.get("WAYLAND_DISPLAY"):
        _xlib_display = None
        return None

    try:
        from Xlib import display
        _xlib_display = display.Display()
    except Exception:
        _xlib_display = None

    return _xlib_display


def safe_translate_coords(root_window, client_window, x: int = 0, y: int = 0) -> Optional[Tuple[int, int]]:
    """Safely translate client_window (x, y) coordinates to root window space.

    Handles Xlib.error.BadWindow, BadDrawable, and general exceptions gracefully
    when windows close dynamically.
    """
    if root_window is None or client_window is None:
        return None
    try:
        # In python-xlib: root.translate_coords(client, x, y) translates (x, y) in client to root
        coords = root_window.translate_coords(client_window, x, y)
        if coords is not None:
            return (coords.x, coords.y)
    except Exception:
        return None
    return None


def _linux_list_windows(min_width: int = 50, min_height: int = 50) -> Tuple[List[WindowInfo], Optional[Tuple[int, int, int, int]]]:
    """List visible, non-desktop Linux windows using Xlib with Wayland safe fallback."""
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

        # Query workarea to check for panels/dock reservation
        try:
            workarea_prop = root.get_full_property(d.intern_atom("_NET_WORKAREA"), Xatom.CARDINAL)
            if workarea_prop and len(workarea_prop.value) >= 4:
                wa_x, wa_y, wa_w, wa_h = workarea_prop.value[:4]
                screen_h = screen.height_in_pixels
                screen_w = screen.width_in_pixels
                if wa_y + wa_h < screen_h:
                    # Bottom panel exists
                    taskbar_rect = (wa_x, wa_y + wa_h, wa_x + wa_w, screen_h)
        except Exception:
            pass

        # Try _NET_CLIENT_LIST_STACKING (Z-order) or _NET_CLIENT_LIST
        client_prop = None
        for atom_name in ("_NET_CLIENT_LIST_STACKING", "_NET_CLIENT_LIST"):
            try:
                atom = d.intern_atom(atom_name)
                prop = root.get_full_property(atom, Xatom.WINDOW)
                if prop and prop.value:
                    client_prop = prop
                    break
            except Exception:
                continue

        if not client_prop:
            return [], taskbar_rect

        atom_wm_state = d.intern_atom("_NET_WM_STATE")
        atom_state_hidden = d.intern_atom("_NET_WM_STATE_HIDDEN")
        atom_window_type = d.intern_atom("_NET_WM_WINDOW_TYPE")
        atom_type_desktop = d.intern_atom("_NET_WM_WINDOW_TYPE_DESKTOP")
        atom_type_dock = d.intern_atom("_NET_WM_WINDOW_TYPE_DOCK")
        atom_type_splash = d.intern_atom("_NET_WM_WINDOW_TYPE_SPLASH")
        atom_type_notification = d.intern_atom("_NET_WM_WINDOW_TYPE_NOTIFICATION")
        atom_type_tooltip = d.intern_atom("_NET_WM_WINDOW_TYPE_TOOLTIP")
        atom_frame_extents = d.intern_atom("_NET_FRAME_EXTENTS")
        atom_wm_pid = d.intern_atom("_NET_WM_PID")
        atom_net_wm_name = d.intern_atom("_NET_WM_NAME")

        for wid in client_prop.value:
            try:
                w = d.create_resource_object("window", wid)

                # Check window state for _NET_WM_STATE_HIDDEN (minimized)
                try:
                    state_prop = w.get_full_property(atom_wm_state, Xatom.ATOM)
                    if state_prop and atom_state_hidden in state_prop.value:
                        continue
                except (error.BadWindow, error.BadDrawable, error.XError):
                    continue
                except Exception:
                    pass

                # Check window type
                is_dock = False
                try:
                    type_prop = w.get_full_property(atom_window_type, Xatom.ATOM)
                    if type_prop and type_prop.value:
                        tvals = set(type_prop.value)
                        if atom_type_desktop in tvals:
                            continue  # Skip desktop background
                        if atom_type_splash in tvals or atom_type_notification in tvals or atom_type_tooltip in tvals:
                            continue
                        if atom_type_dock in tvals:
                            is_dock = True
                except (error.BadWindow, error.BadDrawable, error.XError):
                    continue
                except Exception:
                    pass

                # Check title
                name = ""
                try:
                    name_prop = w.get_full_property(atom_net_wm_name, 0)
                    if name_prop and name_prop.value:
                        val = name_prop.value
                        name = val.decode("utf-8", errors="replace") if isinstance(val, bytes) else str(val)
                    if not name:
                        name = w.get_wm_name() or ""
                except Exception:
                    name = ""

                name = name.strip()
                if not name and not is_dock:
                    continue

                # Geometry and safe coordinates translation
                try:
                    geom = w.get_geometry()
                except (error.BadWindow, error.BadDrawable, error.XError):
                    continue

                coords = safe_translate_coords(root, w, 0, 0)
                if coords is None:
                    continue
                cx, cy = coords

                # Check frame extents (titlebar and window border margins)
                frame_ext = [0, 0, 0, 0]  # left, right, top, bottom
                try:
                    fprop = w.get_full_property(atom_frame_extents, Xatom.CARDINAL)
                    if fprop and fprop.value and len(fprop.value) >= 4:
                        frame_ext = list(fprop.value[:4])
                except Exception:
                    pass

                left = cx - frame_ext[0]
                top = cy - frame_ext[2]
                right = cx + geom.width + frame_ext[1]
                bottom = cy + geom.height + frame_ext[3]
                width = right - left
                height = bottom - top

                if width <= 0 or height <= 0:
                    continue

                if is_dock:
                    # Panel or dock
                    if cy > screen.height_in_pixels // 2:
                        taskbar_rect = (left, top, right, bottom)
                    continue

                if width < min_width or height < min_height:
                    continue

                # Process name
                proc = ""
                try:
                    pid_prop = w.get_full_property(atom_wm_pid, 0)
                    if pid_prop and pid_prop.value:
                        proc = _get_process_name(pid_prop.value[0])
                except Exception:
                    pass

                windows.append(
                    WindowInfo(
                        id=wid,
                        title=name,
                        rect=(left, top, right, bottom),
                        process=proc,
                        is_taskbar=False,
                        is_minimized=False,
                        is_visible=True,
                    )
                )
            except (error.BadWindow, error.BadDrawable, error.XError):
                continue
            except Exception:
                continue

    except Exception:
        return [], taskbar_rect

    return windows, taskbar_rect


# =====================================================================
# Screen Geometry Helper
# =====================================================================

def _get_primary_screen_geometry() -> Optional[Tuple[int, int, int, int]]:
    """Get primary screen geometry as (0, 0, width, height) if possible."""
    # 1. Try PyQt5 if loaded
    try:
        if "PyQt5.QtWidgets" in sys.modules:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                scr = app.primaryScreen()
                if scr:
                    geo = scr.geometry()
                    return (geo.x(), geo.y(), geo.x() + geo.width(), geo.y() + geo.height())
    except Exception:
        pass

    # 2. Try Windows
    if IS_WIN:
        try:
            import ctypes
            w = ctypes.windll.user32.GetSystemMetrics(0)
            h = ctypes.windll.user32.GetSystemMetrics(1)
            if w > 0 and h > 0:
                return (0, 0, w, h)
        except Exception:
            pass

    # 3. Try Linux Xlib
    if IS_LINUX:
        try:
            d = _get_xlib()
            if d:
                scr = d.screen()
                return (0, 0, scr.width_in_pixels, scr.height_in_pixels)
        except Exception:
            pass

    return None


def _normalize_screen_rect(rect: Any) -> Optional[Tuple[int, int, int, int]]:
    """Normalize various screen rect representations to (left, top, right, bottom)."""
    if rect is None:
        return _get_primary_screen_geometry()

    # Handle QRect or objects with left/top/right/bottom or x/y/width/height
    if hasattr(rect, "left") and hasattr(rect, "right") and hasattr(rect, "top") and hasattr(rect, "bottom"):
        try:
            return (int(rect.left()), int(rect.top()), int(rect.right()), int(rect.bottom()))
        except TypeError:
            return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom()))

    if hasattr(rect, "x") and hasattr(rect, "y") and hasattr(rect, "width") and hasattr(rect, "height"):
        try:
            x, y, w, h = int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())
        except TypeError:
            x, y, w, h = int(rect.x), int(rect.y), int(rect.width), int(rect.height)
        return (x, y, x + w, y + h)

    if isinstance(rect, (tuple, list)) and len(rect) == 4:
        return (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))

    return None


# =====================================================================
# WindowTracker Class
# =====================================================================

class WindowTracker:
    """Lightweight, cached, cross-platform window tracker for desktop pets.

    Provides cached window listing, walkable ledges (including window titlebars
    and screen floor/taskbar), climbable edges, landing calculation, and edge reach.
    """

    def __init__(
        self,
        cache_interval: float = 1.5,
        min_window_width: int = 60,
        min_window_height: int = 50,
        exclude_titles: Optional[Sequence[str]] = None,
    ):
        """Initialize the tracker.

        Args:
            cache_interval: Seconds to cache window listings (e.g. 1.5 - 2.0s)
            min_window_width: Filter out windows smaller than this width
            min_window_height: Filter out windows smaller than this height
            exclude_titles: Optional list of window title substrings to exclude
        """
        self.cache_interval = max(0.1, float(cache_interval))
        self.min_window_width = min_window_width
        self.min_window_height = min_window_height
        self.exclude_titles = [t.lower() for t in (exclude_titles or [])]

        self._last_poll_time: float = 0.0
        self._cached_windows: List[WindowInfo] = []
        self._cached_taskbar: Optional[Tuple[int, int, int, int]] = None

    def invalidate_cache(self) -> None:
        """Force the next query to refresh window list from the OS."""
        self._last_poll_time = 0.0

    def _query_os_windows(self) -> Tuple[List[WindowInfo], Optional[Tuple[int, int, int, int]]]:
        """Query windows from OS with safe fallback."""
        try:
            if IS_WIN:
                return _win32_list_windows(self.min_window_width, self.min_window_height)
            elif IS_LINUX:
                return _linux_list_windows(self.min_window_width, self.min_window_height)
        except Exception:
            pass
        return [], None

    def get_windows(self, force_refresh: bool = False) -> List[WindowInfo]:
        """Return list of active, visible, unminimized, uncloaked windows.

        Uses cached results if called within cache_interval. Never raises exceptions.
        """
        now = time.monotonic()
        if force_refresh or (now - self._last_poll_time >= self.cache_interval):
            raw_windows, taskbar = self._query_os_windows()
            # Filter excluded titles
            filtered = []
            for w in raw_windows:
                title_lower = w.title.lower()
                if any(ex in title_lower for ex in self.exclude_titles):
                    continue
                filtered.append(w)

            self._cached_windows = filtered
            self._cached_taskbar = taskbar
            self._last_poll_time = now

        return list(self._cached_windows)

    def get_taskbar_rect(self, force_refresh: bool = False) -> Optional[Tuple[int, int, int, int]]:
        """Return the bounding rect (left, top, right, bottom) of the taskbar/dock, if found."""
        self.get_windows(force_refresh=force_refresh)
        return self._cached_taskbar

    # -----------------------------------------------------------------
    # Pet Helper 1: Walkable Ledges
    # -----------------------------------------------------------------
    def get_walkable_ledges(
        self,
        screen_rect: Any = None,
        force_refresh: bool = False,
    ) -> List[WalkableLedge]:
        """Return horizontal segments (y, x_min, x_max) that the pet can sit or walk on.

        Includes window titlebars and the screen floor / taskbar.
        """
        s_rect = _normalize_screen_rect(screen_rect)
        windows = self.get_windows(force_refresh=force_refresh)
        taskbar = self._cached_taskbar

        ledges: List[WalkableLedge] = []

        # 1. Window titlebars (top edge)
        for w in windows:
            top_y = w.top
            left_x = w.left
            right_x = w.right

            if s_rect:
                s_left, s_top, s_right, s_bottom = s_rect
                # Skip windows entirely off-screen
                if top_y < s_top or top_y >= s_bottom:
                    continue
                left_x = max(s_left, left_x)
                right_x = min(s_right, right_x)

            if right_x - left_x >= 20:  # Minimum walkable segment width
                ledges.append(WalkableLedge(y=top_y, x_min=left_x, x_max=right_x, is_taskbar=False, is_floor=False))

        # 2. Floor / Taskbar ledge
        if s_rect:
            s_left, s_top, s_right, s_bottom = s_rect
            if taskbar:
                tb_left, tb_top, tb_right, tb_bottom = taskbar
                # Taskbar along bottom of screen
                if tb_top < s_bottom and tb_bottom >= s_bottom - 20:
                    # Ledge on top of taskbar
                    t_left = max(s_left, tb_left)
                    t_right = min(s_right, tb_right)
                    if t_right > t_left:
                        ledges.append(WalkableLedge(y=tb_top, x_min=t_left, x_max=t_right, is_taskbar=True, is_floor=True))
                    # Outside taskbar coverage if taskbar doesn't span whole screen width
                    if t_left > s_left:
                        ledges.append(WalkableLedge(y=s_bottom, x_min=s_left, x_max=t_left, is_taskbar=False, is_floor=True))
                    if t_right < s_right:
                        ledges.append(WalkableLedge(y=s_bottom, x_min=t_right, x_max=s_right, is_taskbar=False, is_floor=True))
                else:
                    ledges.append(WalkableLedge(y=s_bottom, x_min=s_left, x_max=s_right, is_taskbar=False, is_floor=True))
            else:
                ledges.append(WalkableLedge(y=s_bottom, x_min=s_left, x_max=s_right, is_taskbar=False, is_floor=True))

        # Sort ledges by elevation (top of screen / smallest y first)
        ledges.sort(key=lambda item: (item.y, item.x_min))
        return ledges

    # -----------------------------------------------------------------
    # Pet Helper 2: Climbable Edges
    # -----------------------------------------------------------------
    def get_climbable_edges(
        self,
        screen_rect: Any = None,
        include_screen_edges: bool = True,
        force_refresh: bool = False,
    ) -> List[ClimbableEdge]:
        """Return vertical segments (x, y_bottom, y_top, is_left_edge) of windows.

        is_left_edge is True for the window's left border (inside is to the right),
        and False for the window's right border (inside is to the left).
        """
        s_rect = _normalize_screen_rect(screen_rect)
        windows = self.get_windows(force_refresh=force_refresh)

        edges: List[ClimbableEdge] = []

        for w in windows:
            left_x = w.left
            right_x = w.right
            top_y = w.top
            bot_y = w.bottom

            if s_rect:
                s_left, s_top, s_right, s_bottom = s_rect
                top_y = max(s_top, top_y)
                bot_y = min(s_bottom, bot_y)

            if bot_y - top_y >= 20:
                # Left edge
                edges.append(ClimbableEdge(x=left_x, y_bottom=bot_y, y_top=top_y, is_left_edge=True, is_screen_edge=False))
                # Right edge
                edges.append(ClimbableEdge(x=right_x, y_bottom=bot_y, y_top=top_y, is_left_edge=False, is_screen_edge=False))

        if include_screen_edges and s_rect:
            s_left, s_top, s_right, s_bottom = s_rect
            if s_bottom > s_top:
                # Left screen edge
                edges.append(ClimbableEdge(x=s_left, y_bottom=s_bottom, y_top=s_top, is_left_edge=True, is_screen_edge=True))
                # Right screen edge
                edges.append(ClimbableEdge(x=s_right, y_bottom=s_bottom, y_top=s_top, is_left_edge=False, is_screen_edge=True))

        return edges

    # -----------------------------------------------------------------
    # Pet Helper 3: Landing Ledge Detection
    # -----------------------------------------------------------------
    def find_landing_y(
        self,
        x: float,
        y: float,
        sprite_w: int,
        sprite_h: int,
        floor_y: float,
        screen_rect: Any = None,
    ) -> float:
        """Find the highest ledge below the pet at x, so if the pet falls,

        it lands on top of a window or on the floor.

        Args:
            x: Pet's current x coordinate (top-left)
            y: Pet's current y coordinate (top-left)
            sprite_w: Pet's sprite width
            sprite_h: Pet's sprite height
            floor_y: The pet's resting y position on the floor
            screen_rect: Optional screen rectangle

        Returns:
            The pet's landing y coordinate (top-left) on the highest ledge below it,
            or floor_y if no window ledge is below the pet.
        """
        pet_left = x
        pet_right = x + sprite_w
        tolerance = 2.0  # Allow pet already resting on the ledge to register it

        ledges = self.get_walkable_ledges(screen_rect=screen_rect)
        candidate_pet_ys: List[float] = []

        for ledge in ledges:
            # Floor ledges (screen bottom / taskbar) are handled by floor_y
            if ledge.is_floor:
                continue

            # Check horizontal overlap
            overlap = min(pet_right, ledge.x_max) - max(pet_left, ledge.x_min)
            # Must have positive overlap
            if overlap <= 0:
                continue

            # Target pet top-left y coordinate if it lands on this ledge
            target_pet_y = float(ledge.y - sprite_h)

            # Ledge must be below the pet (or at pet feet within tolerance)
            # and above the floor
            if target_pet_y >= y - tolerance and target_pet_y < floor_y:
                candidate_pet_ys.append(target_pet_y)

        if candidate_pet_ys:
            # Highest physical ledge = smallest y coordinate
            return min(candidate_pet_ys)

        return float(floor_y)

    # -----------------------------------------------------------------
    # Pet Helper 4: Nearby Climbable Edge Detection
    # -----------------------------------------------------------------
    def find_nearby_climbable(
        self,
        pet_x: float,
        pet_y: float,
        sprite_w: int,
        sprite_h: int,
        reach_px: float = 30.0,
        screen_rect: Any = None,
    ) -> Optional[ClimbableEdge]:
        """Find if there is a window edge or screen edge nearby that the cat can grab and climb.

        Args:
            pet_x: Pet's current x position (top-left)
            pet_y: Pet's current y position (top-left)
            sprite_w: Pet sprite width
            sprite_h: Pet sprite height
            reach_px: Grabbing reach radius in pixels
            screen_rect: Optional screen bounding rectangle

        Returns:
            ClimbableEdge if a nearby edge is found within reach_px, else None.
        """
        pet_left = pet_x
        pet_right = pet_x + sprite_w
        pet_top = pet_y
        pet_bottom = pet_y + sprite_h

        edges = self.get_climbable_edges(screen_rect=screen_rect, include_screen_edges=True)

        best_edge: Optional[ClimbableEdge] = None
        min_dist = float("inf")

        for edge in edges:
            y_min = min(edge.y_top, edge.y_bottom)
            y_max = max(edge.y_top, edge.y_bottom)

            # 1. Vertical range check (pet must overlap vertically with reach margin)
            if pet_bottom < y_min - reach_px or pet_top > y_max + reach_px:
                continue

            # 2. Horizontal distance check
            if edge.x < pet_left:
                dist_x = pet_left - edge.x
            elif edge.x > pet_right:
                dist_x = edge.x - pet_right
            else:
                dist_x = 0.0

            if dist_x <= reach_px:
                if dist_x < min_dist:
                    min_dist = dist_x
                    best_edge = ClimbableEdge(
                        x=edge.x,
                        y_bottom=edge.y_bottom,
                        y_top=edge.y_top,
                        is_left_edge=edge.is_left_edge,
                        distance=dist_x,
                        is_screen_edge=edge.is_screen_edge,
                    )

        return best_edge


# =====================================================================
# Module-level Convenience Functions (Singleton Pattern)
# =====================================================================

_default_tracker: Optional[WindowTracker] = None


def get_tracker() -> WindowTracker:
    """Return the global default WindowTracker singleton."""
    global _default_tracker
    if _default_tracker is None:
        _default_tracker = WindowTracker()
    return _default_tracker


def list_windows(force_refresh: bool = False) -> List[WindowInfo]:
    """Return list of active, unminimized, visible windows."""
    return get_tracker().get_windows(force_refresh=force_refresh)


def get_taskbar_rect(force_refresh: bool = False) -> Optional[Tuple[int, int, int, int]]:
    """Return taskbar/dock bounding rect if detected."""
    return get_tracker().get_taskbar_rect(force_refresh=force_refresh)


def get_walkable_ledges(screen_rect: Any = None, force_refresh: bool = False) -> List[WalkableLedge]:
    """Return walkable horizontal segments (y, x_min, x_max)."""
    return get_tracker().get_walkable_ledges(screen_rect=screen_rect, force_refresh=force_refresh)


def get_climbable_edges(
    screen_rect: Any = None, include_screen_edges: bool = True, force_refresh: bool = False
) -> List[ClimbableEdge]:
    """Return vertical climbable segments (x, y_bottom, y_top, is_left_edge)."""
    return get_tracker().get_climbable_edges(
        screen_rect=screen_rect, include_screen_edges=include_screen_edges, force_refresh=force_refresh
    )


def find_landing_y(
    x: float, y: float, sprite_w: int, sprite_h: int, floor_y: float, screen_rect: Any = None
) -> float:
    """Find the highest ledge below the pet at x, or floor_y."""
    return get_tracker().find_landing_y(
        x=x, y=y, sprite_w=sprite_w, sprite_h=sprite_h, floor_y=floor_y, screen_rect=screen_rect
    )


def find_nearby_climbable(
    pet_x: float, pet_y: float, sprite_w: int, sprite_h: int, reach_px: float = 30.0, screen_rect: Any = None
) -> Optional[ClimbableEdge]:
    """Find if a window or screen edge is nearby within reach_px."""
    return get_tracker().find_nearby_climbable(
        pet_x=pet_x, pet_y=pet_y, sprite_w=sprite_w, sprite_h=sprite_h, reach_px=reach_px, screen_rect=screen_rect
    )
