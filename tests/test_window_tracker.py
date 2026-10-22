"""Tests for window_tracker.py.

Covers the geometry helpers, the caching/snapshot machinery, the HiDPI
coordinate conversion, the Wayland trust rules, and the platform backends
(mocked, so they run anywhere). Run with:

    python3 -m unittest test_window_tracker
"""

import time
import unittest
from unittest.mock import MagicMock, patch

import window_tracker
from window_tracker import (
    ClimbableEdge,
    WalkableLedge,
    WindowInfo,
    WindowTracker,
    detection_is_complete,
    find_landing_y,
    find_nearby_climbable,
    get_climbable_edges,
    get_taskbar_rect,
    get_tracker,
    get_walkable_ledges,
    list_windows,
    safe_translate_coords,
)

SCREEN = (0, 0, 1920, 1080)


class TestDataStructures(unittest.TestCase):
    def test_window_info_rect_accessors(self):
        w = WindowInfo(id=123, title="Editor", rect=(100, 200, 700, 600),
                       process="code", pid=42)
        self.assertEqual((w.left, w.top, w.right, w.bottom), (100, 200, 700, 600))
        self.assertEqual(w.width, 600)
        self.assertEqual(w.height, 400)
        self.assertEqual(w.pid, 42)

    def test_window_info_ignores_degenerate_rects(self):
        w = WindowInfo(rect=(700, 600, 100, 200))
        self.assertEqual(w.width, 0)
        self.assertEqual(w.height, 0)

    def test_walkable_ledge_helpers(self):
        ledge = WalkableLedge(y=300, x_min=100, x_max=500)
        self.assertEqual(ledge.width, 400)
        self.assertTrue(ledge.holds_center(300))
        self.assertFalse(ledge.holds_center(90))
        # Overlap is what landing uses, so a partial overhang counts.
        self.assertTrue(ledge.holds_any(480, 560))
        self.assertFalse(ledge.holds_any(500, 560))

    def test_climbable_edge_helpers(self):
        edge = ClimbableEdge(x=200, y_bottom=800, y_top=200, is_left_edge=True,
                             distance=5.0)
        self.assertEqual(edge.height, 600)
        self.assertEqual(edge.distance, 5.0)


class TestSnapshotAndCache(unittest.TestCase):
    def setUp(self):
        self.tracker = WindowTracker(cache_interval=1.0)
        self.windows = [
            WindowInfo(id=1, title="Window A", rect=(100, 200, 500, 600)),
            WindowInfo(id=2, title="Window B", rect=(400, 400, 900, 750)),
        ]

    def _patched(self, windows=None, taskbar=None):
        return patch.object(self.tracker, "_query_os_windows",
                            return_value=(list(windows or self.windows), taskbar))

    def test_caching_interval(self):
        with self._patched() as query:
            self.assertEqual(len(self.tracker.get_windows()), 2)
            self.assertEqual(query.call_count, 1)
            self.tracker.get_windows()
            self.assertEqual(query.call_count, 1, "second call must hit the cache")
            self.tracker.get_windows(force_refresh=True)
            self.assertEqual(query.call_count, 2)
            self.tracker.invalidate_cache()
            self.tracker.get_windows()
            self.assertEqual(query.call_count, 3)

    def test_snapshot_holds_derived_geometry(self):
        with self._patched(taskbar=(0, 1040, 1920, 1080)):
            self.tracker.set_screen_rect(SCREEN)
            snapshot = self.tracker.get_snapshot()
        self.assertEqual(len(snapshot.windows), 2)
        self.assertEqual(snapshot.taskbar, (0, 1040, 1920, 1080))
        self.assertEqual(sorted(l.y for l in snapshot.ledges), [200, 400, 1040])
        self.assertEqual(len(snapshot.edges), 6)  # 2 windows + 2 screen edges

    def test_ledges_and_edges_only_include_the_current_screen(self):
        # A window on a second monitor must not become a ledge the pet can
        # never reach, nor a border it can try to climb.
        far = WindowInfo(id=9, title="Other monitor", rect=(3000, 100, 4000, 900))
        with self._patched(windows=[far], taskbar=None):
            self.tracker.set_screen_rect(SCREEN)
            self.assertEqual([l for l in self.tracker.get_walkable_ledges()
                              if not l.is_floor], [])
            self.assertEqual([e for e in self.tracker.get_climbable_edges()
                              if not e.is_screen_edge], [])

    def test_coordinate_scale_converts_native_pixels(self):
        native = [WindowInfo(id=1, title="Half scale", rect=(200, 400, 1200, 1000))]
        self.tracker.set_coordinate_scale(2.0)
        with self._patched(windows=native):
            scaled = self.tracker.get_windows(force_refresh=True)
        self.assertEqual(scaled[0].rect, (100, 200, 600, 500))

    def test_set_screen_rect_changes_derived_geometry(self):
        left_monitor = (-1920, 0, 0, 1080)
        with self._patched():
            self.tracker.set_screen_rect(SCREEN)
            self.assertEqual(self.tracker.get_walkable_ledges()[-1].y, 1080)
            self.tracker.set_screen_rect(left_monitor)
            ledges = self.tracker.get_walkable_ledges()
            self.assertEqual(ledges[-1].y, 1080)
            self.assertEqual(ledges[-1].x_min, -1920)
            # Window A at x 100..500 is not on the left monitor at all.
            self.assertEqual([l for l in ledges if not l.is_floor], [])

    def test_exclude_titles_and_pids(self):
        self.tracker = WindowTracker(exclude_titles=["my pet", "desktop"],
                                     exclude_pids=[7])
        windows = [
            WindowInfo(id=1, title="My Pet Window", rect=(0, 0, 100, 100)),
            WindowInfo(id=2, title="Desktop View", rect=(0, 0, 100, 100)),
            WindowInfo(id=3, title="Browser", rect=(100, 100, 600, 500), pid=7),
            WindowInfo(id=4, title="Editor", rect=(100, 100, 600, 500), pid=8),
        ]
        with self._patched(windows=windows):
            result = self.tracker.get_windows(force_refresh=True)
        self.assertEqual([w.title for w in result], ["Editor"])

    def test_background_poller_serves_reads_without_querying(self):
        with self._patched() as query:
            self.tracker.start_background(interval=5.0)
            try:
                # Wait for the snapshot to be *stored*, not merely for the
                # query to be called: those are not the same instant.
                deadline = time.monotonic() + 3.0
                while self.tracker.get_snapshot().at == 0.0 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertGreater(query.call_count, 0)
                self.assertEqual(len(self.tracker.get_windows()), 2)
                # Reads during a stale interval must not hit the OS again.
                count = query.call_count
                for _ in range(20):
                    self.tracker.get_windows()
                    self.tracker.get_walkable_ledges()
                    self.tracker.get_climbable_edges()
                self.assertEqual(query.call_count, count)
            finally:
                self.tracker.stop_background()
        self.assertFalse(self.tracker._background)


class TestPetHelpers(unittest.TestCase):
    def setUp(self):
        self.tracker = WindowTracker(cache_interval=10.0)
        self.windows = [
            WindowInfo(id=1, title="Window A", rect=(100, 200, 500, 600)),
            WindowInfo(id=2, title="Window B", rect=(400, 400, 900, 750)),
        ]
        patcher = patch.object(self.tracker, "_query_os_windows",
                               return_value=(self.windows, (0, 1000, 1920, 1080)))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tracker.set_screen_rect(SCREEN)
        self.tracker.get_windows(force_refresh=True)

    def test_get_walkable_ledges(self):
        ledges = self.tracker.get_walkable_ledges()
        win_a = next(l for l in ledges if l.y == 200)
        self.assertEqual((win_a.x_min, win_a.x_max), (100, 500))
        self.assertFalse(win_a.is_floor)
        floor = next(l for l in ledges if l.y == 1000)
        self.assertTrue(floor.is_taskbar)
        self.assertTrue(floor.is_floor)
        # Sorted top-down.
        self.assertEqual([l.y for l in ledges], sorted(l.y for l in ledges))

    def test_taskbar_that_does_not_span_the_screen_splits_the_floor(self):
        self.tracker._refresh(force=True)
        ledge = next(l for l in self.tracker.get_walkable_ledges() if l.y == 1000)
        self.assertTrue(ledge.is_taskbar)
        self.assertEqual((ledge.x_min, ledge.x_max), (0, 1920))

    def test_get_climbable_edges(self):
        edges = self.tracker.get_climbable_edges(include_screen_edges=True)
        left = next(e for e in edges if e.x == 100 and e.is_left_edge
                    and not e.is_screen_edge)
        self.assertEqual((left.y_top, left.y_bottom), (200, 600))
        right = next(e for e in edges if e.x == 500 and not e.is_left_edge
                    and not e.is_screen_edge)
        self.assertEqual((right.y_top, right.y_bottom), (200, 600))
        self.assertEqual(len([e for e in edges if e.is_screen_edge]), 2)
        # Screen edges can be excluded.
        self.assertEqual(
            [e for e in self.tracker.get_climbable_edges(include_screen_edges=False)
             if e.is_screen_edge], [])

    def test_find_landing_y_uses_the_highest_ledge_below(self):
        self.assertEqual(self.tracker.find_landing_y(200, 50, 40, 40, 960.0), 160.0)
        # Below window A but above window B: land on B.
        self.assertEqual(self.tracker.find_landing_y(450, 250, 40, 40, 960.0), 360.0)

    def test_find_landing_y_falls_to_floor(self):
        self.assertEqual(self.tracker.find_landing_y(50, 100, 40, 40, 960.0), 960.0)
        self.assertEqual(self.tracker.find_landing_y(200, 700, 40, 40, 960.0), 960.0)

    def test_find_landing_y_accepts_partial_overhang(self):
        # Pet spans 60..124: its centre (92) is left of the ledge, but it
        # overlaps. Landing uses overlap; find_ledge_at must agree, or PERCH is
        # entered holding no ledge -- which dereferenced None on the next tick
        # and took the process down.
        self.assertEqual(self.tracker.find_landing_y(60, 50, 64, 64, 960.0), 136.0)
        self.assertIsNotNone(self.tracker.find_ledge_at(200.0, 60, 64))
        self.assertIsNone(self.tracker.find_ledge_at(200.0, 940, 64))

    def test_find_ledge_at_agrees_with_find_landing_y(self):
        floor = 960.0
        for x, y in ((200, 50), (450, 250), (60, 50), (1500, 10)):
            landing = self.tracker.find_landing_y(x, y, 64, 64, floor)
            ledge = self.tracker.find_ledge_at(landing + 64, x, 64)
            if landing == floor:
                # Nothing but floor under the pet: no ledge, and the pet must
                # not be put into PERCH.
                self.assertIsNone(ledge)
                continue
            self.assertIsNotNone(ledge, "no ledge for landing at %s from %s" % (landing, x))
            self.assertAlmostEqual(ledge.y - 64, landing, msg="ledge/landing disagree")

    def test_find_nearby_climbable(self):
        edge = self.tracker.find_nearby_climbable(75, 300, 32, 32, reach_px=30)
        self.assertIsNotNone(edge)
        self.assertEqual(edge.x, 100)
        self.assertTrue(edge.is_left_edge)

        right = self.tracker.find_nearby_climbable(510, 300, 32, 32, reach_px=30)
        self.assertEqual(right.x, 500)
        self.assertFalse(right.is_left_edge)
        self.assertAlmostEqual(right.distance, 10.0)

        screen = self.tracker.find_nearby_climbable(10, 500, 32, 32, reach_px=30)
        self.assertTrue(screen.is_screen_edge)

        self.assertIsNone(
            self.tracker.find_nearby_climbable(250, 300, 32, 32, reach_px=20))

    def test_find_nearby_climbable_is_deterministic_on_ties(self):
        # Two windows whose left borders are equidistant: the same one must be
        # chosen every time, or the cat picks a different frame each launch.
        picks = set()
        for _ in range(20):
            edge = self.tracker.find_nearby_climbable(0, 300, 32, 32, reach_px=300)
            picks.add((edge.x, edge.is_left_edge))
        self.assertEqual(len(picks), 1)

    def test_edge_still_present_detects_closure(self):
        edge = self.tracker.find_nearby_climbable(75, 300, 32, 32, reach_px=30)
        self.assertTrue(self.tracker.edge_still_present(edge))
        gone = ClimbableEdge(x=edge.x, y_bottom=edge.y_bottom - 400,
                             y_top=edge.y_top - 400, is_left_edge=edge.is_left_edge)
        self.assertFalse(self.tracker.edge_still_present(gone))
        self.assertFalse(self.tracker.edge_still_present(None))


class TestPlatformTrust(unittest.TestCase):
    def test_wayland_is_never_trusted(self):
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0",
                                       "DISPLAY": ":0"}, clear=False):
            self.assertFalse(detection_is_complete())

    def test_x11_without_wayland_is_trusted(self):
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": "", "DISPLAY": ":0"},
                        clear=False):
            with patch.object(window_tracker, "_get_xlib", return_value=object()):
                self.assertTrue(detection_is_complete())

    def test_pure_wayland_reports_no_detection(self):
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0"}, clear=True):
            # The real X connection may already be memoised from an earlier
            # test, so ask the question the function actually asks.
            with patch.object(window_tracker, "_get_xlib", return_value=None):
                self.assertFalse(window_tracker.window_detection_available())
                self.assertFalse(detection_is_complete())

    def test_no_xlib_falls_back_to_screen_edges_only(self):
        tracker = WindowTracker()
        with patch.object(window_tracker, "_get_xlib", return_value=None):
            with patch.object(window_tracker, "IS_LINUX", True):
                with patch.object(window_tracker, "IS_WIN", False):
                    self.assertEqual(tracker.get_windows(force_refresh=True), [])
                    tracker.set_screen_rect(SCREEN)
                    ledges = tracker.get_walkable_ledges()
                    self.assertEqual(len(ledges), 1)
                    self.assertEqual(ledges[0].y, 1080)
                    edges = tracker.get_climbable_edges()
                    self.assertEqual(len(edges), 2)
                    self.assertEqual(tracker.find_landing_y(500, 100, 40, 40, 1040.0),
                                     1040.0)


class TestWindowsBackend(unittest.TestCase):
    def test_win32_enumeration_filters(self):
        """Visible, cloaked, minimized, layered and taskbar windows."""
        mock_user32 = MagicMock()
        mock_dwmapi = MagicMock()

        def mock_is_window_visible(hwnd):
            return hwnd != 103

        def mock_is_iconic(hwnd):
            return hwnd == 102

        def mock_get_window_text_length(hwnd):
            return {101: 7, 102: 13, 103: 4, 104: 11, 105: 11, 106: 9, 107: 0}.get(hwnd, 0)

        def mock_get_window_text(hwnd, buf, length):
            titles = {101: "Browser", 102: "Minimized App", 104: "Cloaked App",
                      105: "Transparent", 106: "Zero Size"}
            buf.value = titles.get(hwnd, "")
            return len(buf.value)

        def mock_get_class_name(hwnd, buf, length):
            buf.value = "Shell_TrayWnd" if hwnd == 107 else "GenericWindow"
            return len(buf.value)

        def mock_dwm_attr(hwnd, attr, byref_val, size):
            if attr == 14:  # DWMWA_CLOAKED
                byref_val._obj.value = 1 if hwnd == 104 else 0
                return 0
            if attr == 9:  # DWMWA_EXTENDED_FRAME_BOUNDS
                rect = byref_val._obj
                if hwnd == 101:
                    rect.left, rect.top, rect.right, rect.bottom = 100, 150, 900, 750
                elif hwnd == 106:
                    rect.left, rect.top, rect.right, rect.bottom = 100, 100, 100, 100
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
        mock_user32.FindWindowW.return_value = 107
        mock_dwmapi.DwmGetWindowAttribute.side_effect = mock_dwm_attr

        # 105 is a fully transparent layered window: it must be filtered.
        def mock_ex_style(hwnd, index):
            return window_tracker.WS_EX_LAYERED if hwnd == 105 else 0

        mock_user32.GetWindowLongW.side_effect = mock_ex_style
        mock_user32.GetWindowLongPtrW.side_effect = mock_ex_style

        def mock_layered_attrs(hwnd, key, alpha, flags):
            alpha._obj.value = 0
            flags._obj.value = window_tracker.LWA_ALPHA
            return 1  # success

        mock_user32.GetLayeredWindowAttributes.side_effect = mock_layered_attrs

        seen = []

        def mock_enum_windows(callback, lparam):
            for h in [101, 102, 103, 104, 105, 106, 107]:
                seen.append(h)
                if not callback(h, lparam):
                    break
            return 1

        mock_user32.EnumWindows.side_effect = mock_enum_windows

        with patch.object(window_tracker, "IS_WIN", True):
            with patch("ctypes.windll", create=True) as mock_windll:
                mock_windll.user32 = mock_user32
                mock_windll.dwmapi = mock_dwmapi
                windows, taskbar = window_tracker._win32_list_windows()

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].title, "Browser")
        self.assertEqual(windows[0].rect, (100, 150, 900, 750))
        self.assertIsNotNone(taskbar)
        self.assertEqual(taskbar, (0, 1040, 1920, 1080))
        self.assertIn(105, seen, "layered window was never offered to the callback")

    def test_win32_ex_style_coerces_to_int(self):
        # A non-integer style value must not make every bit test truthy and
        # silently drop every window.
        with patch("ctypes.windll", create=True) as mock_windll:
            mock_windll.user32.GetWindowLongPtrW.return_value = object()
            self.assertEqual(window_tracker._win32_ex_style(1), 0)


class TestLinuxBackend(unittest.TestCase):
    def _mock_display(self, client_ids, workarea=(0, 0, 1920, 1040)):
        mock_display = MagicMock()
        mock_screen = MagicMock()
        mock_screen.width_in_pixels = 1920
        mock_screen.height_in_pixels = 1080
        mock_root = MagicMock()
        mock_display.screen.return_value = mock_screen
        mock_screen.root = mock_root

        atoms = {name: index for index, name in enumerate(
            ["_NET_WORKAREA", "_NET_CLIENT_LIST_STACKING", "_NET_CLIENT_LIST",
             "_NET_WM_STATE", "_NET_WM_STATE_HIDDEN", "_NET_WM_WINDOW_TYPE",
             "_NET_WM_WINDOW_TYPE_DESKTOP", "_NET_WM_WINDOW_TYPE_DOCK",
             "_NET_WM_WINDOW_TYPE_SPLASH", "_NET_WM_WINDOW_TYPE_NOTIFICATION",
             "_NET_WM_WINDOW_TYPE_TOOLTIP", "_NET_FRAME_EXTENTS", "_NET_WM_PID",
             "_NET_WM_NAME", "_NET_ACTIVE_WINDOW"], start=1)}
        mock_display.intern_atom.side_effect = lambda name: atoms.get(name, 99)

        wa_prop = MagicMock()
        wa_prop.value = list(workarea)
        cl_prop = MagicMock()
        cl_prop.value = list(client_ids)

        def root_get_prop(atom, atom_type=0):
            if atom == atoms["_NET_WORKAREA"]:
                return wa_prop
            if atom in (atoms["_NET_CLIENT_LIST_STACKING"], atoms["_NET_CLIENT_LIST"]):
                return cl_prop
            return None

        mock_root.get_full_property.side_effect = root_get_prop

        def prop_for(atom_values, extra=None):
            def prop_fn(atom, atom_type=0):
                if extra and atom in extra:
                    return extra[atom]
                if atom in atom_values:
                    p = MagicMock()
                    p.value = atom_values[atom]
                    return p
                return None
            return prop_fn

        def create_resource_object(_kind, wid):
            w = MagicMock()
            if wid == 1001:  # normal window
                w.get_geometry.return_value = MagicMock(width=800, height=600)
                mock_root.translate_coords.return_value = MagicMock(x=100, y=100)
                w.get_full_property.side_effect = prop_for(
                    {}, extra={
                        atoms["_NET_FRAME_EXTENTS"]: _prop([5, 5, 25, 5]),
                        atoms["_NET_WM_NAME"]: _prop(b"Text Editor"),
                        atoms["_NET_WM_PID"]: _prop([4242]),
                    })
            elif wid == 1002:  # desktop
                w.get_full_property.side_effect = prop_for(
                    {atoms["_NET_WM_WINDOW_TYPE"]: [atoms["_NET_WM_WINDOW_TYPE_DESKTOP"]]})
            elif wid == 1003:  # minimized
                w.get_full_property.side_effect = prop_for(
                    {atoms["_NET_WM_STATE"]: [atoms["_NET_WM_STATE_HIDDEN"]]})
            elif wid == 1004:  # dock
                w.get_geometry.return_value = MagicMock(width=1920, height=40)
                mock_root.translate_coords.return_value = MagicMock(x=0, y=1040)
                w.get_full_property.side_effect = prop_for(
                    {atoms["_NET_WM_WINDOW_TYPE"]: [atoms["_NET_WM_WINDOW_TYPE_DOCK"]]},
                    extra={atoms["_NET_WM_NAME"]: _prop(b"Panel")})
            elif wid == 1005:  # closed mid-query
                w.get_geometry.side_effect = Exception("BadWindow")
            elif wid == 1006:  # modern window: only _NET_WM_NAME, no WM_NAME
                w.get_geometry.return_value = MagicMock(width=400, height=300)
                mock_root.translate_coords.return_value = MagicMock(x=50, y=60)
                w.get_wm_name.return_value = b""
                w.get_full_property.side_effect = prop_for(
                    {}, extra={atoms["_NET_WM_NAME"]: _prop(b"Modern App")})
            return w

        mock_display.create_resource_object.side_effect = create_resource_object
        return mock_display, mock_root

    def test_linux_window_filtering(self):
        display, _root = self._mock_display([1001, 1002, 1003, 1004, 1005, 1006])
        with patch.object(window_tracker, "_get_xlib", return_value=display):
            wins, taskbar = window_tracker._linux_list_windows()
        titles = sorted(w.title for w in wins)
        self.assertEqual(titles, ["Modern App", "Text Editor"])
        editor = next(w for w in wins if w.title == "Text Editor")
        self.assertEqual(editor.rect, (95, 75, 905, 705))
        self.assertEqual(editor.pid, 4242)
        self.assertEqual(editor.process, "")  # pid 4242 does not exist
        self.assertIsNotNone(taskbar)

    def test_net_wm_name_is_preferred_over_wm_name(self):
        # WM_NAME is empty for GTK4/Qt/Electron windows; reading only that made
        # window-aware dialogue and the foreground blocklist dead on Linux.
        display, root = self._mock_display([1006])
        with patch.object(window_tracker, "_get_xlib", return_value=display):
            active_prop = MagicMock()
            active_prop.value = [1006]
            atoms = {"_NET_ACTIVE_WINDOW": 15}
            original = root.get_full_property.side_effect

            def with_active(atom, atom_type=0):
                if atom == 15:
                    return active_prop
                return original(atom, atom_type)

            root.get_full_property.side_effect = with_active
            active = window_tracker._linux_active_window()
        self.assertIsNotNone(active)
        self.assertEqual(active.title, "Modern App")
        self.assertEqual(active.rect, (50, 60, 450, 360))


def _prop(value):
    p = MagicMock()
    p.value = value
    return p


class TestLiveEnvironment(unittest.TestCase):
    def test_live_window_listing(self):
        tracker = WindowTracker(cache_interval=0.5)
        wins = tracker.get_windows(force_refresh=True)
        self.assertIsInstance(wins, list)
        for w in wins:
            self.assertIsInstance(w, WindowInfo)
            self.assertTrue(w.title)
            self.assertEqual(len(w.rect), 4)
            left, top, right, bottom = w.rect
            self.assertGreaterEqual(right, left)
            self.assertGreaterEqual(bottom, top)

        tracker.set_screen_rect(window_tracker.virtual_screen_rect())
        self.assertIsInstance(tracker.get_walkable_ledges(), list)
        self.assertIsInstance(tracker.get_climbable_edges(), list)
        self.assertIsInstance(
            tracker.find_landing_y(100, 50, 32, 32, 600.0), (int, float))
        active = tracker.get_active_window()
        self.assertTrue(active is None or isinstance(active, WindowInfo))


class TestModuleLevelFunctions(unittest.TestCase):
    def test_singleton_is_shared(self):
        self.assertIs(get_tracker(), get_tracker())
        self.assertIsInstance(list_windows(), list)
        self.assertIsInstance(get_walkable_ledges(SCREEN), list)
        self.assertIsInstance(get_climbable_edges(SCREEN), list)
        self.assertIsInstance(find_landing_y(100, 100, 32, 32, 900.0), (int, float))
        self.assertTrue(find_nearby_climbable(10, 100, 32, 32, reach_px=30,
                                              screen_rect=SCREEN) is None
                        or isinstance(find_nearby_climbable(10, 100, 32, 32,
                                                            reach_px=30,
                                                            screen_rect=SCREEN),
                                      ClimbableEdge))
        self.assertTrue(get_taskbar_rect() is None
                        or isinstance(get_taskbar_rect(), tuple))


if __name__ == "__main__":
    unittest.main(verbosity=2)
