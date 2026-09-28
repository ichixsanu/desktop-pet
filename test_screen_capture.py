"""Tests for screen_capture.py.

The important property here is refusal: when a blocklist is configured, a
capture may only happen if we can actually see every window. Under Wayland we
cannot, so it must refuse rather than quietly sending an unfiltered desktop.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QColor, QImage  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

import screen_capture as sc  # noqa: E402
import window_tracker as wt  # noqa: E402

_app = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication([])


class TestBlocklist(unittest.TestCase):
    def test_matches_title_or_process_case_insensitively(self):
        self.assertTrue(sc.is_blocked("KEEPASSXC - vault", "keepassxc", ["keepass"]))
        self.assertTrue(sc.is_blocked("anything", "Signal", ["signal"]))
        self.assertFalse(sc.is_blocked("Editor", "code", ["keepass", "bank"]))
        self.assertFalse(sc.is_blocked("Editor", "code", []))
        self.assertFalse(sc.is_blocked(None, None, [None, "", "  "]))


class TestRedactionGuarantee(unittest.TestCase):
    def test_no_blocklist_always_safe(self):
        safe, reason = sc.redaction_guarantee([])
        self.assertTrue(safe)
        self.assertEqual(reason, "")

    def test_complete_detection_is_safe(self):
        with patch.object(wt, "window_detection_available", return_value=True):
            with patch.object(wt, "_detection_is_complete", return_value=True):
                self.assertTrue(sc.redaction_guarantee(["bank"])[0])

    def test_refuses_when_no_window_api_exists(self):
        with patch.object(wt, "window_detection_available", return_value=False):
            safe, reason = sc.redaction_guarantee(["bank"])
        self.assertFalse(safe)
        self.assertIn("Wayland", reason)

    def test_refuses_under_hybrid_wayland(self):
        # XWayland lets us see X clients while native Wayland windows stay
        # invisible. Believing we filtered them is the dangerous case.
        with patch.object(wt, "window_detection_available", return_value=True):
            with patch.object(wt, "_detection_is_complete", return_value=False):
                safe, reason = sc.redaction_guarantee(["keepass"])
        self.assertFalse(safe)
        self.assertIn("Wayland", reason)

    def test_missing_tracker_refuses(self):
        with patch.object(sc, "window_tracker", None):
            self.assertFalse(sc.redaction_guarantee(["bank"])[0])


class TestRedaction(unittest.TestCase):
    def setUp(self):
        self.tracker = wt.WindowTracker(cache_interval=30.0)
        patcher = patch.object(self.tracker, "_query_os_windows", return_value=(
            [wt.WindowInfo(id=1, title="Secret Bank", rect=(100, 50, 300, 200)),
             wt.WindowInfo(id=2, title="Editor", rect=(400, 50, 900, 400))], None))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tracker.set_screen_rect((0, 0, 1920, 1080))
        self.tracker.get_windows(force_refresh=True)

        self.image = QImage(1920, 1080, QImage.Format_RGB32)
        self.image.fill(QColor(120, 130, 140))

    def _pixel(self, x, y):
        return self.image.pixelColor(x, y).name()

    def test_blocked_window_is_blackened(self):
        with patch.object(wt, "get_tracker", return_value=self.tracker):
            sc.redact(self.image, ["bank"], (0, 0, 1920, 1080))
        self.assertEqual(self._pixel(150, 100), "#000000", "blocked area not redacted")
        self.assertEqual(self._pixel(500, 100), "#78828c", "unblocked area altered")

    def test_nothing_happens_without_a_match(self):
        with patch.object(wt, "get_tracker", return_value=self.tracker):
            sc.redact(self.image, ["keepass"], (0, 0, 1920, 1080))
        self.assertEqual(self._pixel(150, 100), "#78828c")

    def test_rects_are_translated_to_the_grabbed_screen(self):
        # Grabbing a secondary monitor whose origin is not (0,0): without the
        # offset, redactions land in the wrong place and a blocked window on
        # that screen ships unredacted.
        image = QImage(1280, 720, QImage.Format_RGB32)
        image.fill(QColor(10, 20, 30))
        with patch.object(wt, "get_tracker", return_value=self.tracker):
            sc.redact(image, ["bank"], (1920, 0, 3200, 720))
        # Window at 100..300 in desktop space is off-screen for this grab, so
        # nothing is drawn: it cannot leak, and nothing outside is touched.
        self.assertEqual(image.pixelColor(0, 0).name(), "#0a141e")
        self.assertEqual(image.pixelColor(1279, 719).name(), "#0a141e")

    def test_partial_intersection_is_still_redacted(self):
        image = QImage(400, 300, QImage.Format_RGB32)
        image.fill(QColor(10, 20, 30))
        with patch.object(wt, "get_tracker", return_value=self.tracker):
            sc.redact(image, ["bank"], (0, 0, 400, 300))
        self.assertEqual(image.pixelColor(150, 100).name(), "#000000")

    def test_no_blocklist_is_a_no_op(self):
        with patch.object(wt, "get_tracker", return_value=self.tracker):
            sc.redact(self.image, [], (0, 0, 1920, 1080))
        self.assertEqual(self._pixel(150, 100), "#78828c")

    def test_null_image_is_safe(self):
        self.assertIsNone(sc.redact(None, ["bank"]))


class TestEncoding(unittest.TestCase):
    def test_roundtrip(self):
        image = QImage(64, 48, QImage.Format_RGB32)
        image.fill(QColor(200, 30, 30))
        encoded = sc.encode_jpeg_base64(image, 70)
        self.assertIsInstance(encoded, str)
        self.assertGreater(len(encoded), 100)

    def test_null_image(self):
        self.assertIsNone(sc.encode_jpeg_base64(None, 70))
        self.assertIsNone(sc.encode_jpeg_base64(QImage(), 70))


class TestPrepareCapture(unittest.TestCase):
    def setUp(self):
        self.tracker = wt.WindowTracker(cache_interval=30.0)
        self.active = wt.WindowInfo(id=5, title="Bank of Testing", rect=(0, 0, 100, 100))
        patcher = patch.object(self.tracker, "_query_os_windows", return_value=([], None))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tracker.set_screen_rect((0, 0, 1920, 1080))
        self.tracker.get_windows(force_refresh=True)

    def _prepare(self, blocklist):
        with patch.object(wt, "get_tracker", return_value=self.tracker):
            with patch.object(self.tracker, "get_active_window", return_value=self.active):
                return sc.prepare_capture(_app, blocklist, (0, 0, 1920, 1080))

    def test_refuses_when_the_focused_window_is_blocked(self):
        with patch.object(wt, "window_detection_available", return_value=True):
            with patch.object(wt, "_detection_is_complete", return_value=True):
                image, reason = self._prepare(["bank"])
        self.assertIsNone(image)
        self.assertIn("blocklist", reason)

    def test_refuses_under_wayland_before_grabbing_anything(self):
        with patch.object(wt, "window_detection_available", return_value=True):
            with patch.object(wt, "_detection_is_complete", return_value=False):
                with patch.object(sc, "grab_screen_image") as grab:
                    image, reason = sc.prepare_capture(_app, ["bank"])
        self.assertIsNone(image)
        self.assertIn("Wayland", reason)
        grab.assert_not_called()

    def test_capture_with_redaction_returns_none_when_unsafe(self):
        with patch.object(wt, "window_detection_available", return_value=True):
            with patch.object(wt, "_detection_is_complete", return_value=False):
                self.assertIsNone(sc.capture_with_redaction(_app, ["bank"], 70))


if __name__ == "__main__":
    unittest.main(verbosity=2)
