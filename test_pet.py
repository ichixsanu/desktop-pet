"""Tests for pet.py.

Focuses on the things that used to take the whole process down or produce
nonsense: text wrapping, the speech bubble layout, and the FSM invariants
around landing, perching and climbing. The pet is driven directly instead of
through the timer so the tests are deterministic.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPoint, Qt  # noqa: E402
from PyQt5.QtGui import QFont, QFontMetrics  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

import companion_dialogue as cd  # noqa: E402
import pet as P  # noqa: E402
import window_tracker as wt  # noqa: E402

_app = None
SCREEN = (0, 0, 1280, 720)


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication([])


def make_font():
    return QFont("DejaVu Sans Mono", P.SPEECH_FONT_SIZE)


class TestTextWrapping(unittest.TestCase):
    def setUp(self):
        self.metrics = QFontMetrics(make_font())

    def test_short_text_is_one_line(self):
        self.assertEqual(P._wrap_text("hi", self.metrics, 500), ["hi"])

    def test_wraps_on_word_boundaries(self):
        lines = P._wrap_text("alpha bravo charlie delta echo", self.metrics, 60)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertNotIn("  ", line)
            self.assertLessEqual(self.metrics.horizontalAdvance(line), 60 + 1)

    def test_repeated_words_are_not_lost(self):
        # The old implementation rebuilt the final line with
        # `words.index(word)`, which finds the *first* occurrence, so a word
        # repeated before the cut point was emitted twice.
        text = ("the cat sat on the mat and the cat looked at the dog and the "
                "cat meowed loudly at the moon")
        source = text.split()
        lines = P._wrap_text(text, self.metrics, 70)
        self.assertLessEqual(len(lines), P.SPEECH_MAX_LINES)
        self.assertTrue(lines[-1].endswith("..."), "expected elision here")
        spoken = " ".join(lines).replace("...", " ").split()
        source_words = set(source)
        for word in set(spoken) & source_words:
            self.assertLessEqual(spoken.count(word), source.count(word),
                                 "%r duplicated by wrapping" % word)

    def test_overflow_is_elided_not_truncated_mid_word_silently(self):
        text = " ".join(["word%d" % i for i in range(60)])
        lines = P._wrap_text(text, self.metrics, 60)
        self.assertEqual(len(lines), P.SPEECH_MAX_LINES)
        self.assertTrue(lines[-1].endswith("..."))

    def test_respects_max_lines(self):
        lines = P._wrap_text(" ".join(["x"] * 200), self.metrics, 40, max_lines=2)
        self.assertEqual(len(lines), 2)

    def test_empty_text(self):
        self.assertEqual(P._wrap_text("", self.metrics, 100), [""])
        self.assertEqual(P._wrap_text(None, self.metrics, 100), [""])

    def test_elide_helper(self):
        self.assertEqual(P._elide("short", self.metrics, 500), "short")
        elided = P._elide("a very long line indeed", self.metrics, 30)
        self.assertTrue(elided.endswith("..."), repr(elided))
        self.assertLessEqual(self.metrics.horizontalAdvance(elided), 30)


class TestBubbleGeometry(unittest.TestCase):
    def test_size_grows_with_content(self):
        _lines, narrow_w, _h1 = P._compute_bubble_geometry("hi", make_font())
        lines, wide_w, tall_h = P._compute_bubble_geometry(
            "a considerably longer sentence that has to wrap somewhere", make_font())
        self.assertGreater(wide_w, narrow_w)
        self.assertGreater(tall_h, _h1)
        self.assertGreaterEqual(len(lines), 2)

    def test_within_limits(self):
        for text in ("", "hi", "x" * 500, "word " * 100):
            _lines, width, height = P._compute_bubble_geometry(text, make_font())
            self.assertGreaterEqual(width, P.SPEECH_MIN_WIDTH)
            self.assertLessEqual(width, P.SPEECH_MAX_WIDTH)
            self.assertGreater(height, 0)


class TestGuardedDecorator(unittest.TestCase):
    def test_exceptions_are_swallowed_and_logged(self):
        @P.guarded
        def boom(self):
            raise RuntimeError("kaboom")

        sentinel = object()
        with patch.object(P, "log_exception") as log:
            self.assertIsNone(boom(sentinel))
        log.assert_called_once()
        self.assertIn("boom", log.call_args[0][0])


class TestSystemStatus(unittest.TestCase):
    def setUp(self):
        P._status_cache["at"] = 0.0

    def test_cached_between_calls(self):
        with patch.object(P, "_mem_percent", return_value=42) as mem:
            with patch.object(P, "_battery_percent", return_value=77):
                P.system_status()
                P.system_status()
                P.system_status()
        self.assertEqual(mem.call_count, 1)

    def test_expires_after_the_ttl(self):
        P._status_cache["at"] = 0.0
        with patch.object(P, "_mem_percent", return_value=42) as mem:
            P.system_status()
        self.assertEqual(mem.call_count, 1)

    def test_quote_uses_the_companion_voice(self):
        for skin in sorted(cd.COMPANION_DIALOGUE):
            with patch.object(P, "system_status", return_value=(10, 100)):
                line = P.get_system_status_quote(skin)
            allowed = set(cd.COMPANION_DIALOGUE[skin]["general"]) | set(
                cd.COMPANION_DIALOGUE[skin]["coding"])
            self.assertIn(line, allowed)

    def test_low_memory_selects_the_system_line(self):
        with patch.object(P, "system_status", return_value=(95, 100)):
            line = P.get_system_status_quote("cat")
        self.assertIn(line, cd.COMPANION_DIALOGUE["cat"]["low_memory"])

    def test_low_battery_wins_over_memory(self):
        with patch.object(P, "system_status", return_value=(95, 5)):
            line = P.get_system_status_quote("cat")
        self.assertIn(line, cd.COMPANION_DIALOGUE["cat"]["low_battery"])


class TestSkinDiscovery(unittest.TestCase):
    def test_finds_the_bundled_skins(self):
        skins = P.discover_skins()
        self.assertIn("cat", skins)
        self.assertNotIn("_heart", skins)
        self.assertEqual(skins, sorted(skins))


class PetHarness(unittest.TestCase):
    """A pet on a fixed screen with a fake window layout underneath it."""

    WINDOWS = [
        wt.WindowInfo(id=1, title="Window A", rect=(100, 200, 500, 600)),
        wt.WindowInfo(id=2, title="Window B", rect=(400, 400, 900, 750)),
    ]

    def setUp(self):
        self.pet = P.DesktopPet(skin="cat", scale=2)
        self.pet.timer.stop()
        self.apply_screen()
        self.tracker_patcher = patch.object(self.pet.tracker, "_query_os_windows",
                                            return_value=(list(self.WINDOWS), None))
        self.tracker_patcher.start()
        self.addCleanup(self.tracker_patcher.stop)
        self.addCleanup(self.pet.shutdown)
        self.refresh()

    def apply_screen(self):
        pet = self.pet
        pet.screen_left, pet.screen_top = 0, 0
        pet.screen_w, pet.screen_h = SCREEN[2], SCREEN[3]
        pet.screen_rect = SCREEN
        pet.floor_y = float(SCREEN[3] - pet.sprite_h)
        pet.x_pos, pet.y_pos = 300.0, pet.floor_y
        if pet.tracker is not None:
            pet.tracker.set_screen_rect(SCREEN)

    def refresh(self):
        if self.pet.tracker is not None:
            self.pet.tracker.get_windows(force_refresh=True)

    def ledges(self):
        return self.pet.tracker.get_walkable_ledges()


class TestLedgeHandling(PetHarness):
    def perched_y(self, ledge_y):
        return float(ledge_y - self.pet.sprite_h)

    def test_ledge_lookup_uses_overlap(self):
        # Pet left of the ledge's left edge but overlapping it.
        ledge = next(l for l in self.ledges() if l.y == 200)
        self.pet.x_pos = ledge.x_min - 4
        self.pet.y_pos = self.perched_y(200)
        found = self.pet._ledge_under_pet()
        self.assertIsNotNone(found)
        self.assertEqual(found.y, 200)

    def test_no_ledge_returns_none(self):
        self.pet.x_pos, self.pet.y_pos = 1500.0, self.pet.floor_y
        self.assertIsNone(self.pet._ledge_under_pet())

    def test_clamp_to_ledge_keeps_the_pet_on_it(self):
        ledge = next(l for l in self.ledges() if l.y == 200)
        self.pet.current_ledge = ledge
        self.pet.x_pos = ledge.x_max + 500
        self.assertTrue(self.pet._clamp_to_ledge())
        self.assertEqual(self.pet.x_pos, ledge.x_max - self.pet.sprite_w)

    def test_clamp_on_the_left_edge(self):
        ledge = next(l for l in self.ledges() if l.y == 200)
        self.pet.current_ledge = ledge
        self.pet.x_pos = ledge.x_min - 100
        self.assertTrue(self.pet._clamp_to_ledge())
        self.assertEqual(self.pet.x_pos, ledge.x_min)

    def test_clamp_is_a_noop_off_a_ledge(self):
        self.pet.current_ledge = None
        before = self.pet.x_pos
        self.assertFalse(self.pet._clamp_to_ledge())
        self.assertEqual(self.pet.x_pos, before)

    def test_validate_rejects_a_vanished_ledge(self):
        self.pet.current_ledge = next(l for l in self.ledges() if l.y == 200)
        self.pet.x_pos, self.pet.y_pos = 1000.0, self.pet.floor_y
        self.assertFalse(self.pet._validate_current_ledge())

    def test_validate_rejects_when_the_tracker_is_gone(self):
        self.pet.current_ledge = next(l for l in self.ledges() if l.y == 200)
        self.pet.tracker = None
        self.assertFalse(self.pet._validate_current_ledge())


class TestFallingAndPerching(PetHarness):
    def land(self, x, y):
        self.pet.x_pos, self.pet.y_pos = float(x), float(y)
        self.pet.vy = 0.0
        self.pet._enter_fall()
        for _ in range(2000):
            self.pet._tick_fall()
            if self.pet.state != "FALL":
                return self.pet.state
        return "FALL"

    def test_lands_on_a_titlebar_and_perches(self):
        self.assertEqual(self.land(200, 50), "PERCH")
        self.assertIsNotNone(self.pet.current_ledge)
        self.assertFalse(self.pet.current_ledge.is_floor)
        self.assertAlmostEqual(self.pet.y_pos, self.pet.current_ledge.y - self.pet.sprite_h)

    def test_lands_on_the_floor_without_a_ledge(self):
        self.assertEqual(self.land(1500, 100), "SIT")
        self.assertIsNone(self.pet.current_ledge)

    def test_never_enters_perch_without_a_ledge(self):
        # The abort: PERCH used to be entered whenever a landing surface was
        # found, even if no ledge could be identified, and the next tick
        # dereferenced None inside a Qt slot, which calls abort().
        for x in range(0, 1280, 40):
            for y in (10, 60, 120, 300, 500):
                state = self.land(x, y)
                if state == "PERCH":
                    self.assertIsNotNone(self.pet.current_ledge)
                    self.assertFalse(self.pet.current_ledge.is_floor)
                else:
                    self.assertIn(state, ("SIT", "IDLE"))

    def test_partial_overhang_lands_and_perches_consistently(self):
        # A titlebar narrower than the sprite, only partly under the pet.
        narrow = [wt.WindowInfo(id=9, title="Narrow", rect=(280, 300, 320, 500))]
        with patch.object(self.pet.tracker, "_query_os_windows",
                          return_value=(narrow, None)):
            self.refresh()
            self.assertEqual(self.land(300, 200), "PERCH")
            self.assertIsNotNone(self.pet.current_ledge)

    def test_stalk_cannot_walk_off_a_ledge(self):
        self.assertEqual(self.land(200, 50), "PERCH")
        ledge = self.pet.current_ledge
        self.pet._enter_state("STALK")
        self.pet.facing = 1
        for _ in range(500):
            self.pet._tick_stalk(300, 300)
        self.assertGreaterEqual(self.pet.x_pos, ledge.x_min)
        self.assertLessEqual(self.pet.x_pos + self.pet.sprite_w, ledge.x_max)

    def test_run_cannot_walk_off_a_ledge(self):
        self.assertEqual(self.land(200, 50), "PERCH")
        ledge = self.pet.current_ledge
        self.pet._enter_state("RUN")
        self.pet.facing = 1
        for _ in range(500):
            self.pet._tick_run(300, 300)
        self.assertLessEqual(self.pet.x_pos + self.pet.sprite_w, ledge.x_max)

    def test_perch_releases_at_max_duration(self):
        self.assertEqual(self.land(200, 50), "PERCH")
        self.pet._enter_state("PERCH")
        self.pet.state_timer = P.STATE_MAX_DURATION["PERCH"]
        self.pet._tick_perch(0, 500)
        self.assertNotEqual(self.pet.state, "PERCH")
        self.assertIsNone(self.pet.current_ledge)


class TestClimbing(PetHarness):
    def test_climbs_a_full_screen_and_perches_on_top(self):
        tall = [wt.WindowInfo(id=1, title="Tall", rect=(0, 0, 700, 720))]
        with patch.object(self.pet.tracker, "_query_os_windows",
                          return_value=(tall, None)):
            self.refresh()
            self.pet.x_pos, self.pet.y_pos = 10.0, self.pet.floor_y
            self.assertTrue(self.pet._try_start_climb())
            self.assertEqual(self.pet.state, "CLIMB")
            budget = self.pet.climb_budget_ticks
            # A full screen at 50px/s is ~700 ticks: the old fixed 200-tick cap
            # could never finish, so the pet always fell off mid-climb.
            self.assertGreater(budget, 200)
            for _ in range(budget + P.CLIMB_GRACE_TICKS + 10):
                self.pet._tick_climb()
                if self.pet.state != "CLIMB":
                    break
            self.assertEqual(self.pet.state, "PERCH")
            self.assertIsNotNone(self.pet.current_ledge)

    def test_budget_does_not_shrink_as_the_pet_climbs(self):
        tall = [wt.WindowInfo(id=1, title="Tall", rect=(0, 0, 700, 720))]
        with patch.object(self.pet.tracker, "_query_os_windows",
                          return_value=(tall, None)):
            self.refresh()
            self.pet.x_pos, self.pet.y_pos = 10.0, self.pet.floor_y
            self.pet._try_start_climb()
            budget = self.pet.climb_budget_ticks
            for _ in range(20):
                self.pet._tick_climb()
            self.assertEqual(self.pet.climb_budget_ticks, budget)

    def test_abandons_a_ledge_that_vanished(self):
        tall = [wt.WindowInfo(id=1, title="Tall", rect=(0, 0, 700, 720))]
        with patch.object(self.pet.tracker, "_query_os_windows",
                          return_value=(tall, None)):
            self.refresh()
            self.pet.x_pos, self.pet.y_pos = 10.0, self.pet.floor_y
            self.pet._try_start_climb()
            with patch.object(self.pet.tracker, "edge_still_present",
                              return_value=False):
                self.pet._tick_climb()
        self.assertEqual(self.pet.state, "FALL")
        self.assertIsNone(self.pet.climb_target_edge)

    def test_will_not_start_a_climb_it_cannot_use(self):
        tiny = [wt.WindowInfo(id=1, title="Tiny", rect=(280, 600, 320, 640))]
        with patch.object(self.pet.tracker, "_query_os_windows",
                          return_value=(tiny, None)):
            self.refresh()
            self.pet.x_pos, self.pet.y_pos = 290.0, self.pet.floor_y
            self.assertFalse(self.pet._try_start_climb())
        self.assertNotEqual(self.pet.state, "CLIMB")

    def test_hugging_an_edge_stays_on_screen(self):
        far = [wt.WindowInfo(id=1, title="Far", rect=(1250, 0, 1280, 720))]
        with patch.object(self.pet.tracker, "_query_os_windows",
                          return_value=(far, None)):
            self.refresh()
            self.pet.x_pos, self.pet.y_pos = 1270.0, self.pet.floor_y
            self.pet._try_start_climb()
        self.assertLessEqual(self.pet.x_pos,
                             self.pet.screen_left + self.pet.screen_w - self.pet.sprite_w)


class TestSpeechAndActivity(PetHarness):
    def test_speak_sets_and_clears_the_bubble(self):
        self.pet.speak("hello there, this is a line of dialogue")
        self.assertTrue(self.pet.speech_text)
        self.assertTrue(self.pet.speech_lines)
        self.pet.speech_timer = 1
        self.pet.game_loop()
        self.assertEqual(self.pet.speech_text, "")

    def test_speak_collapses_whitespace_and_caps_length(self):
        self.pet.speak("  a\n\n  b   " + "c" * 500)
        self.assertNotIn("\n", self.pet.speech_text)
        self.assertLessEqual(len(self.pet.speech_text), P.SPEECH_MAX_CHARS)

    def test_empty_speech_is_ignored(self):
        self.pet.speak("")
        self.assertEqual(self.pet.speech_text, "")

    def test_focus_change_counts_as_activity(self):
        self.pet.last_window_title = None
        self.pet.last_activity_tick = 0
        self.pet.tick_count = 1000
        active = wt.WindowInfo(id=1, title="Editor", rect=(0, 0, 10, 10),
                               process="code")
        with patch.object(self.pet.tracker, "get_active_window", return_value=active):
            self.pet._poll_focus()
        self.assertEqual(self.pet.last_window_title, "Editor")
        self.assertEqual(self.pet.last_activity_tick, 1000)

    def test_unchanged_focus_does_not_count_as_activity(self):
        # Marking the pet active on every poll made the recent-activity gate
        # always true, so screenshots fired on an unattended machine.
        active = wt.WindowInfo(id=1, title="Editor", rect=(0, 0, 10, 10))
        self.pet.last_window_title = "Editor"
        self.pet.last_activity_tick = 500
        self.pet.tick_count = 2000
        with patch.object(self.pet.tracker, "get_active_window", return_value=active):
            self.pet._poll_focus()
        self.assertEqual(self.pet.last_activity_tick, 500)

    def test_ai_line_status_handling(self):
        import ai_companion

        self.pet.ai_request_kind = "user"
        with patch.object(self.pet, "speak") as speak:
            self.pet._on_ai_line("a model line", ai_companion.STATUS_OK)
            speak.assert_called_once_with("a model line")

        with patch.object(self.pet, "speak") as speak:
            self.pet._on_ai_line(None, ai_companion.STATUS_SKIPPED)
            speak.assert_not_called()

        with patch.object(self.pet, "speak") as speak:
            self.pet._on_ai_line(None, ai_companion.STATUS_UNAVAILABLE)
            speak.assert_called_once()

    def test_background_failure_is_silent(self):
        # A failed background request must not make the pet speak.
        import ai_companion

        self.pet.ai_request_kind = "idle"
        with patch.object(self.pet, "speak") as speak:
            self.pet._on_ai_line(None, ai_companion.STATUS_UNAVAILABLE)
            speak.assert_not_called()

    def test_ai_deadline_falls_back_once(self):
        self.pet.awaiting_ai = True
        self.pet.ai_request_kind = "user"
        self.pet.ai_deadline = 0
        self.pet.tick_count = 10
        self.pet.speech_timer = 0
        with patch("pet.system_status", return_value=(10, 100)):
            with patch.object(self.pet, "speak") as speak:
                self.pet.game_loop()
                speak.assert_called_once()
                # A later tick must not restart the fallback loop.
                self.pet.game_loop()
                self.assertEqual(speak.call_count, 1)
                self.assertFalse(self.pet.awaiting_ai)


class TestScreenshotWiring(PetHarness):
    def setUp(self):
        super().setUp()
        self.settings = dict(__import__("ai_companion").screenshot_settings())
        self.settings["enabled"] = True
        self.pet.last_activity_tick = self.pet.tick_count

    def _worker_kwargs(self):
        """Capture the kwargs the screenshot worker thread was started with."""
        captured = {}

        class FakeThread:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def start(self):
                pass

        return captured, FakeThread

    def test_nothing_happens_when_disabled(self):
        self.settings["enabled"] = False
        with patch("pet.ai_companion.screenshot_settings", return_value=self.settings):
            with patch("pet.ai_companion.screenshot_slot_ok", return_value=True):
                with patch("pet.screen_capture.prepare_capture") as prepare:
                    with patch("pet.threading.Thread") as thread:
                        self.pet.maybe_screenshot()
        prepare.assert_not_called()
        thread.assert_not_called()

    def test_idle_pet_does_not_capture(self):
        with patch("pet.ai_companion.screenshot_settings", return_value=self.settings):
            with patch("pet.ai_companion.screenshot_slot_ok", return_value=True):
                with patch("pet.screen_capture.prepare_capture") as prepare:
                    self.pet.last_activity_tick = 0
                    self.pet.tick_count = 10 ** 6
                    self.pet.maybe_screenshot()
        prepare.assert_not_called()

    def test_refused_capture_releases_the_slot(self):
        captured, thread_cls = self._worker_kwargs()
        with patch("pet.ai_companion.screenshot_settings", return_value=self.settings):
            with patch("pet.ai_companion.screenshot_slot_ok", return_value=True):
                with patch("pet.ai_companion.record_capture_attempt") as record:
                    with patch("pet.screen_capture.prepare_capture",
                               return_value=(None, "focused window matches")):
                        with patch("pet.threading.Thread", thread_cls):
                            self.pet.maybe_screenshot()
        record.assert_called_once_with(False)
        self.assertEqual(captured, {})

    def test_capture_is_encoded_off_the_gui_thread(self):
        captured, thread_cls = self._worker_kwargs()
        image = MagicMock()
        with patch("pet.ai_companion.screenshot_settings", return_value=self.settings):
            with patch("pet.ai_companion.screenshot_slot_ok", return_value=True):
                with patch("pet.ai_companion.record_capture_attempt"):
                    with patch("pet.screen_capture.prepare_capture",
                               return_value=(image, "")):
                        with patch("pet.threading.Thread", thread_cls):
                            self.pet.maybe_screenshot()
        self.assertIn("target", captured, "capture did not go to a worker")
        self.assertTrue(captured["daemon"])
        # Running the worker body must redact, encode, then ask the model.
        with patch("pet.screen_capture.redact") as redact:
            with patch("pet.screen_capture.encode_jpeg_base64",
                       return_value="b64") as encode:
                with patch("pet.ai_companion.request_screenshot_comment") as ask:
                    with patch("pet.ai_companion.record_capture_attempt") as record:
                        captured["target"]()
        redact.assert_called_once()
        encode.assert_called_once()
        ask.assert_called_once()
        record.assert_called_once_with(True)
        self.assertFalse(self.pet._screenshot_inflight)

    def test_encode_failure_is_reported_and_clears_the_flag(self):
        captured, thread_cls = self._worker_kwargs()
        with patch("pet.ai_companion.screenshot_settings", return_value=self.settings):
            with patch("pet.ai_companion.screenshot_slot_ok", return_value=True):
                with patch("pet.screen_capture.prepare_capture",
                           return_value=(MagicMock(), "")):
                    with patch("pet.threading.Thread", thread_cls):
                        self.pet.maybe_screenshot()
        self.assertTrue(self.pet._screenshot_inflight)
        with patch("pet.screen_capture.redact"):
            with patch("pet.screen_capture.encode_jpeg_base64", return_value=None):
                with patch("pet.ai_companion.request_screenshot_comment") as ask:
                    with patch("pet.ai_companion.record_capture_attempt") as record:
                        captured["target"]()
        ask.assert_not_called()
        record.assert_called_once_with(False)
        self.assertFalse(self.pet._screenshot_inflight)

    def test_worker_crash_still_clears_the_flag(self):
        captured, thread_cls = self._worker_kwargs()
        with patch("pet.ai_companion.screenshot_settings", return_value=self.settings):
            with patch("pet.ai_companion.screenshot_slot_ok", return_value=True):
                with patch("pet.screen_capture.prepare_capture",
                           return_value=(MagicMock(), "")):
                    with patch("pet.threading.Thread", thread_cls):
                        self.pet.maybe_screenshot()
        with patch("pet.screen_capture.redact", side_effect=RuntimeError("boom")):
            with patch("pet.log_exception") as log:
                captured["target"]()
        log.assert_called()
        self.assertFalse(self.pet._screenshot_inflight)


class TestDragAndGeometry(PetHarness):
    def test_drag_clears_the_ledge(self):
        self.assertEqual(self.land_helper(), "PERCH")
        self.pet.mousePressEvent(MagicMock(button=lambda: Qt.LeftButton,
                                           globalPos=lambda: QPoint(300, 300)))
        self.assertIsNone(self.pet.current_ledge)
        self.assertEqual(self.pet.state, "DRAG")

    def land_helper(self):
        self.pet.x_pos, self.pet.y_pos = 200.0, 50.0
        self.pet.vy = 0.0
        self.pet._enter_fall()
        for _ in range(2000):
            self.pet._tick_fall()
            if self.pet.state != "FALL":
                return self.pet.state
        return "FALL"

    def test_stays_within_the_desktop(self):
        move = MagicMock(buttons=lambda: Qt.LeftButton,
                         globalPos=lambda: QPoint(-500, -9000))
        with patch("pet.QCursor"):
            self.pet.mousePressEvent(MagicMock(button=lambda: Qt.LeftButton,
                                               globalPos=lambda: QPoint(300, 300)))
            self.pet.mouseMoveEvent(move)
        self.assertGreaterEqual(self.pet.y_pos, 0)

    def test_bubble_flips_below_when_there_is_no_room_above(self):
        self.pet.y_pos = self.pet.screen_top + 1
        self.pet.speak("a line of dialogue that needs a bubble above it")
        self.assertTrue(self.pet.speech_below)

    def test_bubble_prefers_above_when_there_is_room(self):
        self.pet.y_pos = 400.0
        self.pet.speak("a line of dialogue")
        self.assertFalse(self.pet.speech_below)

    def test_ghost_hovers_from_where_it_was_released(self):
        self.pet.load_skin("ghost")
        self.apply_screen()
        self.assertTrue(self.pet.is_ghost)
        self.pet.ghost_hover_y = self.pet.floor_y - 6.0
        self.pet.mousePressEvent(MagicMock(button=lambda: Qt.LeftButton,
                                           globalPos=lambda: QPoint(300, 300)))
        self.pet.dragging = True          # a real drag moves before releasing
        self.pet.y_pos = 100.0
        self.pet.mouseReleaseEvent(MagicMock(button=lambda: Qt.LeftButton,
                                             globalPos=lambda: QPoint(300, 100)))
        # Hover resumes from the drop point, rather than the old code assigning
        # y_pos and immediately overwriting it with the floor value.
        self.assertEqual(self.pet.ghost_hover_y, 100.0)
        self.assertNotEqual(self.pet.state, "FALL")

    def test_scale_and_skin_switches_keep_the_pet_on_screen(self):
        self.pet.x_pos = 5.0
        self.pet._set_scale(3)
        self.assertGreaterEqual(self.pet.x_pos, self.pet.screen_left)
        self.pet._switch_skin("ghost")
        self.assertEqual(self.pet.current_skin, "ghost")
        self.assertLessEqual(self.pet.x_pos + self.pet.sprite_w,
                             self.pet.screen_left + self.pet.screen_w)

    def test_every_state_resolves_to_a_frame(self):
        for state in P.FRAME_SPEED:
            self.pet.state = state
            self.pet.tick_count += 1
            self.assertTrue(self.pet.get_frames(), "no frames for %s" % state)
            self.assertIsNotNone(self.pet.get_current_frame(), state)

    def test_mirrored_frames_are_cached(self):
        self.pet.state = "SIT"
        self.pet.facing = -1
        first = self.pet.get_current_frame()
        self.assertIsNotNone(first)
        self.assertTrue(self.pet._flipped_cache)
        self.assertIs(first, self.pet.get_current_frame())


if __name__ == "__main__":
    unittest.main(verbosity=2)
