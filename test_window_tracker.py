"""Unit and integration tests for window_tracker.py.

Tests cross-platform window tracking, Windows/Linux backends, fallback modes,
caching, and geometry helper methods for desktop pets.
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

import window_tracker
from window_tracker import (
    ClimbableEdge,
    WalkableLedge,
    WindowInfo,
    WindowTracker,
    find_landing_y,
    find_nearby_climbable,
    get_climbable_edges,
    get_taskbar_rect,
    get_tracker,
    get_walkable_ledges,
    list_windows,
    safe_translate_coords,
)


class TestDataStructures(unittest.TestCase):
    """Test WindowInfo, WalkableLedge, and ClimbableEdge structures."""

    def test_window_info(self):
        w = WindowInfo(
            id=123,
            title="Editor",
            rect=(100, 200, 700, 600),
            process="code",
            is_taskbar=False,
            is_minimized=False,
            is_visible=True,
        )
        self.assertEqual(w.left, 100)
        self.assertEqual(w.top, 200)
        self.assertEqual(w.right, 700)
        self.assertEqual(w.bottom, 600)
        self.assertEqual(w.width, 600)
        self.assertEqual(w.height, 400)
        # Dict indexing
        self.assertEqual(w["rect"], (100, 200, 700, 600))
        self.assertEqual(w["title"], "Editor")
        self.assertEqual(w["process"], "code")
        self.assertEqual(w["id"], 123)

    def test_walkable_ledge_unpacking(self):
        ledge = WalkableLedge(y=300, x_min=100, x_max=500, is_taskbar=False, is_floor=False)
        y, x_min, x_max = ledge[:3]
        self.assertEqual(y, 300)
        self.assertEqual(x_min, 100)
        self.assertEqual(x_max, 500)
        self.assertEqual(ledge.width, 400)

    def test_climbable_edge_unpacking(self):
        edge = ClimbableEdge(x=200, y_bottom=800, y_top=200, is_left_edge=True, distance=5.0)
        x, y_bot, y_top, is_left = edge[:4]
        self.assertEqual(x, 200)
        self.assertEqual(y_bot, 800)
        self.assertEqual(y_top, 200)
        self.assertTrue(is_left)
        self.assertEqual(edge.height, 600)
        self.assertEqual(edge.distance, 5.0)


class TestCaching(unittest.TestCase):
    """Test caching and resource preservation."""

    def test_caching_interval(self):
        tracker = WindowTracker(cache_interval=1.0)
        mock_windows = [
            WindowInfo(id=1, title="Test Window", rect=(100, 100, 500, 400))
        ]

        with patch.object(tracker, "_query_os_windows", return_value=(mock_windows, None)) as mock_query:
            # First call queries OS
            wins1 = tracker.get_windows()
            self.assertEqual(len(wins1), 1)
            self.assertEqual(mock_query.call_count, 1)

            # Second immediate call uses cache
            wins2 = tracker.get_windows()
            self.assertEqual(len(wins2), 1)
            self.assertEqual(mock_query.call_count, 1)

            # force_refresh bypasses cache
            wins3 = tracker.get_windows(force_refresh=True)
            self.assertEqual(len(wins3), 1)
            self.assertEqual(mock_query.call_count, 2)

            # After invalidation
            tracker.invalidate_cache()
            tracker.get_windows()
            self.assertEqual(mock_query.call_count, 3)

    def test_exclude_titles(self):
        tracker = WindowTracker(exclude_titles=["my pet", "desktop"])
        mock_windows = [
            WindowInfo(id=1, title="My Pet Window", rect=(0, 0, 100, 100)),
            WindowInfo(id=2, title="Desktop View", rect=(0, 0, 100, 100)),
            WindowInfo(id=3, title="Browser", rect=(100, 100, 600, 500)),
        ]
        with patch.object(tracker, "_query_os_windows", return_value=(mock_windows, None)):
            res = tracker.get_windows(force_refresh=True)
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0].title, "Browser")


class TestPetHelpers(unittest.TestCase):
    """Test helper methods for walking, climbing, and landing."""

    def setUp(self):
        self.tracker = WindowTracker(cache_interval=10.0)
        # Setup simulated windows:
        # Window A: Left=100, Top=200, Right=500, Bottom=600
        # Window B: Left=400, Top=400, Right=900, Bottom=750
        self.mock_windows = [
            WindowInfo(id=1, title="Window A", rect=(100, 200, 500, 600)),
            WindowInfo(id=2, title="Window B", rect=(400, 400, 900, 750)),
        ]
        self.tracker._cached_windows = list(self.mock_windows)
        self.tracker._cached_taskbar = (0, 1000, 1920, 1080)
        self.tracker._last_poll_time = time.monotonic()

    def test_get_walkable_ledges(self):
        screen_rect = (0, 0, 1920, 1080)
        ledges = self.tracker.get_walkable_ledges(screen_rect=screen_rect)

        # Expected:
        # Ledge 1: Window A top at y=200, x=[100, 500]
        # Ledge 2: Window B top at y=400, x=[400, 900]
        # Ledge 3: Taskbar floor at y=1000, x=[0, 1920]
        self.assertGreaterEqual(len(ledges), 3)

        # Verify Window A titlebar ledge
        win_a_ledge = next(l for l in ledges if l.y == 200)
        self.assertEqual(win_a_ledge.x_min, 100)
        self.assertEqual(win_a_ledge.x_max, 500)
        self.assertFalse(win_a_ledge.is_floor)

        # Verify Window B titlebar ledge
        win_b_ledge = next(l for l in ledges if l.y == 400)
        self.assertEqual(win_b_ledge.x_min, 400)
        self.assertEqual(win_b_ledge.x_max, 900)

        # Verify Taskbar floor ledge
        taskbar_ledge = next(l for l in ledges if l.y == 1000)
        self.assertTrue(taskbar_ledge.is_taskbar)
        self.assertTrue(taskbar_ledge.is_floor)

    def test_get_climbable_edges(self):
        screen_rect = (0, 0, 1920, 1080)
        edges = self.tracker.get_climbable_edges(screen_rect=screen_rect, include_screen_edges=True)

        # Window A has left edge (100, 600, 200, True) and right edge (500, 600, 200, False)
        edge_a_left = next((e for e in edges if e.x == 100 and e.is_left_edge and not e.is_screen_edge), None)
        self.assertIsNotNone(edge_a_left)
        self.assertEqual(edge_a_left.y_bottom, 600)
        self.assertEqual(edge_a_left.y_top, 200)

        edge_a_right = next((e for e in edges if e.x == 500 and not e.is_left_edge and not e.is_screen_edge), None)
        self.assertIsNotNone(edge_a_right)
        self.assertEqual(edge_a_right.y_bottom, 600)
        self.assertEqual(edge_a_right.y_top, 200)

        # Screen edges
        screen_left = next((e for e in edges if e.x == 0 and e.is_left_edge and e.is_screen_edge), None)
        self.assertIsNotNone(screen_left)
        self.assertEqual(screen_left.y_bottom, 1080)
        self.assertEqual(screen_left.y_top, 0)

        screen_right = next((e for e in edges if e.x == 1920 and not e.is_left_edge and e.is_screen_edge), None)
        self.assertIsNotNone(screen_right)

    def test_find_landing_y_above_window_a(self):
        sprite_w, sprite_h = 40, 40
        floor_y = 960.0  # pet floor y (1000 - 40)

        # Pet at x=200, y=50 (above Window A top=200)
        landing_y = self.tracker.find_landing_y(
            x=200, y=50, sprite_w=sprite_w, sprite_h=sprite_h, floor_y=floor_y
        )
        # Should land on Window A titlebar: 200 - 40 = 160.0
        self.assertEqual(landing_y, 160.0)

    def test_find_landing_y_stacked_windows(self):
        sprite_w, sprite_h = 40, 40
        floor_y = 960.0

        # Pet at x=450 (overlaps both Window A [100,500] and Window B [400,900])
        # Pet is at y=50: highest ledge below pet is Window A (top=200)
        landing_y1 = self.tracker.find_landing_y(
            x=450, y=50, sprite_w=sprite_w, sprite_h=sprite_h, floor_y=floor_y
        )
        self.assertEqual(landing_y1, 160.0)

        # Now pet is at y=250 (below Window A top=200, but above Window B top=400)
        landing_y2 = self.tracker.find_landing_y(
            x=450, y=250, sprite_w=sprite_w, sprite_h=sprite_h, floor_y=floor_y
        )
        # Should land on Window B titlebar: 400 - 40 = 360.0
        self.assertEqual(landing_y2, 360.0)

    def test_find_landing_y_falls_to_floor(self):
        sprite_w, sprite_h = 40, 40
        floor_y = 960.0

        # Pet at x=50 (not overlapping any window)
        landing_y = self.tracker.find_landing_y(
            x=50, y=100, sprite_w=sprite_w, sprite_h=sprite_h, floor_y=floor_y
        )
        self.assertEqual(landing_y, floor_y)

        # Pet at x=200 but y=700 (below Window A bottom)
        landing_y_below = self.tracker.find_landing_y(
            x=200, y=700, sprite_w=sprite_w, sprite_h=sprite_h, floor_y=floor_y
        )
        self.assertEqual(landing_y_below, floor_y)

    def test_find_nearby_climbable(self):
        sprite_w, sprite_h = 32, 32
        screen_rect = (0, 0, 1920, 1080)

        # 1. Pet near Window A left edge (x=100)
        # Pet at x=75 (pet_right = 107), y=300
        edge = self.tracker.find_nearby_climbable(
            pet_x=75, pet_y=300, sprite_w=sprite_w, sprite_h=sprite_h, reach_px=30, screen_rect=screen_rect
        )
        self.assertIsNotNone(edge)
        self.assertEqual(edge.x, 100)
        self.assertTrue(edge.is_left_edge)
        self.assertFalse(edge.is_screen_edge)

        # 2. Pet near Window A right edge (x=500)
        # Pet at x=510 (pet_left = 510, distance to 500 is 10), y=300
        edge_r = self.tracker.find_nearby_climbable(
            pet_x=510, pet_y=300, sprite_w=sprite_w, sprite_h=sprite_h, reach_px=30, screen_rect=screen_rect
        )
        self.assertIsNotNone(edge_r)
        self.assertEqual(edge_r.x, 500)
        self.assertFalse(edge_r.is_left_edge)
        self.assertAlmostEqual(edge_r.distance, 10.0)

        # 3. Pet near left screen edge (x=0)
        edge_screen = self.tracker.find_nearby_climbable(
            pet_x=10, pet_y=500, sprite_w=sprite_w, sprite_h=sprite_h, reach_px=30, screen_rect=screen_rect
        )
        self.assertIsNotNone(edge_screen)
        self.assertEqual(edge_screen.x, 0)
        self.assertTrue(edge_screen.is_screen_edge)

        # 4. Pet far away in empty space
        edge_none = self.tracker.find_nearby_climbable(
            pet_x=250, pet_y=300, sprite_w=sprite_w, sprite_h=sprite_h, reach_px=20, screen_rect=screen_rect
        )
        self.assertIsNone(edge_none)


class TestLinuxBackendAndFallback(unittest.TestCase):
    """Test Linux Xlib behavior, error handling, and safe fallbacks."""

    def test_safe_translate_coords_handles_bad_window(self):
        mock_root = MagicMock()
        mock_client = MagicMock()

        # Normal success
        mock_res = MagicMock()
        mock_res.x = 42
        mock_res.y = 84
        mock_root.translate_coords.return_value = mock_res
        self.assertEqual(safe_translate_coords(mock_root, mock_client), (42, 84))

        # Exception / BadWindow
        mock_root.translate_coords.side_effect = Exception("BadWindow: resource 0x123 dead")
        self.assertIsNone(safe_translate_coords(mock_root, mock_client))

        # None arguments
        self.assertIsNone(safe_translate_coords(None, mock_client))
        self.assertIsNone(safe_translate_coords(mock_root, None))

    def test_fallback_when_xlib_unavailable(self):
        """Verify tracker never crashes if Xlib or DISPLAY is missing (Wayland / headless)."""
        tracker = WindowTracker()
        with patch("window_tracker._get_xlib", return_value=None):
            with patch("window_tracker.IS_WIN", False):
                with patch("window_tracker.IS_LINUX", True):
                    wins = tracker.get_windows(force_refresh=True)
                    self.assertEqual(wins, [])

                    # Pet helpers still work using screen fallback
                    screen_rect = (0, 0, 1920, 1080)
                    ledges = tracker.get_walkable_ledges(screen_rect=screen_rect)
                    self.assertEqual(len(ledges), 1)
                    self.assertEqual(ledges[0].y, 1080)

                    climb_edges = tracker.get_climbable_edges(screen_rect=screen_rect)
                    self.assertEqual(len(climb_edges), 2)  # 2 screen edges

                    landing = tracker.find_landing_y(500, 100, 40, 40, 1040.0, screen_rect=screen_rect)
                    self.assertEqual(landing, 1040.0)


class TestWindowsBackend(unittest.TestCase):
    """Test Windows ctypes window listing and filtering logic with mocks."""

    def test_win32_enumeration_filters(self):
        """Simulate Windows EnumWindows callback with visible, cloaked, minimized, and taskbar windows."""
        # Setup mock user32 and dwmapi
        mock_user32 = MagicMock()
        mock_dwmapi = MagicMock()

        # Windows handles:
        # 101: Normal visible window ("Browser")
        # 102: Minimized window ("Minimized App")
        # 103: Invisible window
        # 104: Cloaked window ("Cloaked App")
        # 105: Transparent layered window
        # 106: Zero-size window
        # 107: Taskbar ("Shell_TrayWnd")

        def mock_is_window_visible(hwnd):
            return hwnd != 103

        def mock_is_iconic(hwnd):
            return hwnd == 102

        def mock_get_window_text_length(hwnd):
            titles = {101: 7, 102: 13, 103: 4, 104: 11, 105: 11, 106: 9, 107: 0}
            return titles.get(hwnd, 0)

        def mock_get_window_text(hwnd, buf, length):
            titles = {101: "Browser", 102: "Minimized App", 104: "Cloaked App", 105: "Transparent", 106: "Zero Size"}
            buf.value = titles.get(hwnd, "")
            return len(buf.value)

        def mock_get_class_name(hwnd, buf, length):
            if hwnd == 107:
                buf.value = "Shell_TrayWnd"
            else:
                buf.value = "GenericWindow"
            return len(buf.value)

        def mock_dwm_attr(hwnd, attr, byref_val, size):
            if attr == 14:  # DWMWA_CLOAKED
                if hwnd == 104:
                    byref_val._obj.value = 1  # cloaked
                else:
                    byref_val._obj.value = 0
                return 0
            elif attr == 9:  # DWMWA_EXTENDED_FRAME_BOUNDS
                rect = byref_val._obj
                if hwnd == 101:
                    rect.left, rect.top, rect.right, rect.bottom = 100, 150, 900, 750
                elif hwnd == 106:
                    rect.left, rect.top, rect.right, rect.bottom = 100, 100, 100, 100  # 0 size
                elif hwnd == 107:
                    rect.left, rect.top, rect.right, rect.bottom = 0, 1040, 1920, 1080
                else:
                    rect.left, rect.top, rect.right, rect.bottom = 200, 200, 600, 500
                return 0
            return -1

        def mock_get_window_rect(hwnd, byref_rect):
            rect = byref_rect._obj
            rect.left, rect.top, rect.right, rect.bottom = 0, 1040, 1920, 1080
            return 1

        mock_user32.IsWindowVisible.side_effect = mock_is_window_visible
        mock_user32.IsIconic.side_effect = mock_is_iconic
        mock_user32.GetWindowTextLengthW.side_effect = mock_get_window_text_length
        mock_user32.GetWindowTextW.side_effect = mock_get_window_text
        mock_user32.GetClassNameW.side_effect = mock_get_class_name
        mock_user32.GetWindowRect.side_effect = mock_get_window_rect
        mock_user32.GetWindowLongW.return_value = 0
        mock_user32.FindWindowW.return_value = 107
        mock_dwmapi.DwmGetWindowAttribute.side_effect = mock_dwm_attr

        def mock_enum_windows(callback, lparam):
            for h in [101, 102, 103, 104, 106, 107]:
                if not callback(h, lparam):
                    break
            return 1

        mock_user32.EnumWindows.side_effect = mock_enum_windows

        with patch("window_tracker.IS_WIN", True):
            with patch("ctypes.windll", create=True) as mock_windll:
                mock_windll.user32 = mock_user32
                mock_windll.dwmapi = mock_dwmapi
                windows, taskbar = window_tracker._win32_list_windows()

                # Only window 101 ("Browser") should survive all filters
                self.assertEqual(len(windows), 1)
                self.assertEqual(windows[0].title, "Browser")
                self.assertEqual(windows[0].rect, (100, 150, 900, 750))

                # Taskbar 107 should be identified
                self.assertIsNotNone(taskbar)
                self.assertEqual(taskbar, (0, 1040, 1920, 1080))


class TestLinuxBackendDetails(unittest.TestCase):
    """Test Linux Xlib details, BadWindow resilience, and atom filtering."""

    def test_linux_window_filtering(self):
        mock_display = MagicMock()
        mock_screen = MagicMock()
        mock_screen.width_in_pixels = 1920
        mock_screen.height_in_pixels = 1080
        mock_root = MagicMock()
        mock_display.screen.return_value = mock_screen
        mock_screen.root = mock_root

        # Mock atoms
        def intern_atom(name):
            atoms = {
                "_NET_WORKAREA": 1,
                "_NET_CLIENT_LIST_STACKING": 2,
                "_NET_CLIENT_LIST": 3,
                "_NET_WM_STATE": 4,
                "_NET_WM_STATE_HIDDEN": 5,
                "_NET_WM_WINDOW_TYPE": 6,
                "_NET_WM_WINDOW_TYPE_DESKTOP": 7,
                "_NET_WM_WINDOW_TYPE_DOCK": 8,
                "_NET_WM_WINDOW_TYPE_SPLASH": 9,
                "_NET_WM_WINDOW_TYPE_NOTIFICATION": 10,
                "_NET_WM_WINDOW_TYPE_TOOLTIP": 11,
                "_NET_FRAME_EXTENTS": 12,
                "_NET_WM_PID": 13,
                "_NET_WM_NAME": 14,
            }
            return atoms.get(name, 99)

        mock_display.intern_atom.side_effect = intern_atom

        # Workarea property
        wa_prop = MagicMock()
        wa_prop.value = [0, 0, 1920, 1040]
        mock_root.get_full_property.return_value = wa_prop

        # Windows in client list:
        # W1: Normal window ("Text Editor")
        # W2: Desktop window ("Desktop") -> filtered
        # W3: Minimized window -> filtered
        # W4: Dock window ("Dock") -> detected as dock/taskbar
        # W5: Window that closed dynamically (raises BadWindow) -> gracefully ignored
        cl_prop = MagicMock()
        cl_prop.value = [1001, 1002, 1003, 1004, 1005]

        def root_get_prop(atom, atom_type=0):
            if atom == 2:  # _NET_CLIENT_LIST_STACKING
                return cl_prop
            if atom == 1:  # _NET_WORKAREA
                return wa_prop
            return None

        mock_root.get_full_property.side_effect = root_get_prop

        def create_resource_object(res_type, wid):
            w = MagicMock()
            w.display = mock_display

            if wid == 1001:
                # Normal window
                w.get_wm_name.return_value = "Text Editor"
                geom = MagicMock(width=800, height=600)
                w.get_geometry.return_value = geom
                coords = MagicMock(x=100, y=100)
                mock_root.translate_coords.return_value = coords

                def prop_fn(atom, atom_type=0):
                    if atom == 4:  # WM_STATE
                        return None  # not hidden
                    if atom == 6:  # WINDOW_TYPE
                        p = MagicMock(value=[999])
                        return p
                    if atom == 12:  # FRAME_EXTENTS
                        p = MagicMock(value=[5, 5, 25, 5])
                        return p
                    return None

                w.get_full_property.side_effect = prop_fn

            elif wid == 1002:
                # Desktop window
                w.get_wm_name.return_value = "Desktop"

                def prop_fn(atom, atom_type=0):
                    if atom == 6:  # WINDOW_TYPE
                        p = MagicMock(value=[7])  # DESKTOP
                        return p
                    return None

                w.get_full_property.side_effect = prop_fn

            elif wid == 1003:
                # Minimized window
                w.get_wm_name.return_value = "Minimized Window"

                def prop_fn(atom, atom_type=0):
                    if atom == 4:  # WM_STATE
                        p = MagicMock(value=[5])  # HIDDEN
                        return p
                    return None

                w.get_full_property.side_effect = prop_fn

            elif wid == 1004:
                # Dock window
                w.get_wm_name.return_value = "Panel"
                geom = MagicMock(width=1920, height=40)
                w.get_geometry.return_value = geom
                coords = MagicMock(x=0, y=1040)
                mock_root.translate_coords.return_value = coords

                def prop_fn(atom, atom_type=0):
                    if atom == 6:
                        p = MagicMock(value=[8])  # DOCK
                        return p
                    return None

                w.get_full_property.side_effect = prop_fn

            elif wid == 1005:
                # Dynamically closed window
                w.get_geometry.side_effect = Exception("BadWindow")
                w.get_wm_name.side_effect = Exception("BadWindow")

            return w

        mock_display.create_resource_object.side_effect = create_resource_object

        with patch("window_tracker._get_xlib", return_value=mock_display):
            wins, taskbar = window_tracker._linux_list_windows()

            # Only W1 should be in wins
            self.assertEqual(len(wins), 1)
            self.assertEqual(wins[0].title, "Text Editor")
            # Rect: left = 100 - 5 = 95, top = 100 - 25 = 75, right = 100 + 800 + 5 = 905, bottom = 100 + 600 + 5 = 705
            self.assertEqual(wins[0].rect, (95, 75, 905, 705))

            # Dock W4 or workarea should be identified as taskbar
            self.assertIsNotNone(taskbar)


class TestLiveEnvironment(unittest.TestCase):
    """Test on the active system environment without mocks."""

    def test_live_window_listing(self):
        tracker = WindowTracker(cache_interval=0.5)
        wins = tracker.get_windows(force_refresh=True)
        # Should return a list without error
        self.assertIsInstance(wins, list)
        for w in wins:
            self.assertIsInstance(w, WindowInfo)
            self.assertTrue(len(w.title) > 0)
            self.assertEqual(len(w.rect), 4)
            left, top, right, bottom = w.rect
            self.assertGreater(right, left)
            self.assertGreater(bottom, top)

        # Helpers should execute smoothly on live system
        ledges = tracker.get_walkable_ledges()
        self.assertIsInstance(ledges, list)

        edges = tracker.get_climbable_edges()
        self.assertIsInstance(edges, list)

        landing = tracker.find_landing_y(100, 50, 32, 32, 600.0)
        self.assertIsInstance(landing, (int, float))


class TestModuleLevelFunctions(unittest.TestCase):
    """Test module-level convenience functions."""

    def test_singleton_methods(self):
        t = get_tracker()
        self.assertIsInstance(t, WindowTracker)

        wins = list_windows()
        self.assertIsInstance(wins, list)

        ledges = get_walkable_ledges((0, 0, 1920, 1080))
        self.assertIsInstance(ledges, list)

        edges = get_climbable_edges((0, 0, 1920, 1080))
        self.assertIsInstance(edges, list)

        landing = find_landing_y(100, 100, 32, 32, 900.0)
        self.assertIsInstance(landing, (int, float))

        climb = find_nearby_climbable(10, 100, 32, 32, reach_px=30, screen_rect=(0, 0, 1920, 1080))
        self.assertTrue(climb is None or isinstance(climb, ClimbableEdge))


if __name__ == "__main__":
    unittest.main(verbosity=2)


