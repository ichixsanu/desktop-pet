"""Tests for pet.py.

Focuses on the things that used to take the whole process down or produce
nonsense: text wrapping, the speech bubble layout, and the FSM invariants
around landing, perching and climbing. The pet is driven directly instead of
through the timer so the tests are deterministic.
"""

import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, mock_open, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPoint, Qt  # noqa: E402
from PyQt5.QtGui import QFont, QFontMetrics  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

import ai_companion  # noqa: E402
import companion_dialogue as cd  # noqa: E402
import json  # noqa: E402

import pet as P  # noqa: E402
import screen_capture as sc  # noqa: E402
import window_tracker as wt  # noqa: E402

_app = None
SCREEN = (0, 0, 1280, 720)


_mute = None


def setUpModule():
    global _app, _mute
    _app = QApplication.instance() or QApplication([])
    # the pet makes noise now: a test run must not play through the speakers
    _mute = patch.object(P.pet_sounds.PetSounds, "_dispatch",
                         lambda self, build: None)
    _mute.start()


def tearDownModule():
    if _mute is not None:
        _mute.stop()


def make_font():
    return QFont("DejaVu Sans Mono", P.SPEECH_FONT_SIZE)


def _find_action(menu, text):
    """Find an action by label, looking inside submenus too.

    The menu gained a Screenshots & Privacy submenu, so the old flat scan for
    "Look At This" stopped finding it. Walking the tree keeps the tests honest
    about the real layout.
    """
    for action in menu.actions():
        if action.text() == text:
            return action
        submenu = action.menu()
        if submenu is not None:
            found = _find_action(submenu, text)
            if found is not None:
                return found
    return None


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

    def land(self, x, y):
        """Drop the pet from (x, y) and return the state it settles into."""
        self.pet.x_pos, self.pet.y_pos = float(x), float(y)
        self.pet.vy = 0.0
        self.pet._enter_fall()
        for _ in range(2000):
            self.pet._tick_fall()
            if self.pet.state != "FALL":
                return self.pet.state
        return "FALL"

    def setUp(self):
        # Never touch the real pet_state.json: a leftover file would silently
        # decide which skin and position every test runs with.
        import copy

        import ai_companion

        config = copy.deepcopy(ai_companion.CONFIG)
        config.setdefault("state", {})["enabled"] = False
        config.setdefault("focus", {})["enabled"] = False
        patcher = patch.object(ai_companion, "CONFIG", config)
        patcher.start()
        self.addCleanup(patcher.stop)

        # Idle chatter must never reach the network from a test. Tests that are
        # about the model path patch these explicitly.
        for name, value in (("maybe_context_line", False), ("maybe_idle_line", None)):
            ctx = patch.object(ai_companion, name, return_value=value)
            ctx.start()
            self.addCleanup(ctx.stop)

        # Pin the environment signals the pet reads from the OS: a machine that
        # happens to be idle (or showing a fullscreen window) while the tests
        # run must not change what the FSM does.
        idle = patch.object(P.DesktopPet, "_user_idle_seconds", return_value=0.0)
        idle.start()
        self.addCleanup(idle.stop)

        self.pet = P.DesktopPet(skin="cat", scale=2)
        self.pet.timer.stop()
        self.apply_screen()
        self.tracker_patcher = patch.object(self.pet.tracker, "_query_os_windows",
                                            return_value=(list(self.WINDOWS), None))
        self.tracker_patcher.start()
        self.addCleanup(self.tracker_patcher.stop)
        fullscreen = patch.object(self.pet.tracker, "fullscreen_active",
                                  return_value=False)
        fullscreen.start()
        self.addCleanup(fullscreen.stop)
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
        # Identity, not position: a pet seated at the very top of the screen has
        # its feet below the titlebar it is standing on, so "is the pet over the
        # ledge" is the wrong question to ask.
        ledge = next(l for l in self.ledges() if l.y == 200)
        self.pet.current_ledge = ledge
        self.assertTrue(self.pet._validate_current_ledge())
        with patch.object(self.pet.tracker, "_query_os_windows",
                          return_value=([], None)):
            self.pet.tracker.invalidate_cache()
            self.assertFalse(self.pet._validate_current_ledge())

    def test_validate_reseats_the_pet(self):
        ledge = next(l for l in self.ledges() if l.y == 200)
        self.pet.current_ledge = ledge
        self.pet.y_pos = 5.0
        self.assertTrue(self.pet._validate_current_ledge())
        self.assertAlmostEqual(self.pet.y_pos, ledge.y - self.pet.sprite_h, delta=1.0)

    def test_validate_rejects_when_the_tracker_is_gone(self):
        self.pet.current_ledge = next(l for l in self.ledges() if l.y == 200)
        self.pet.tracker = None
        self.assertFalse(self.pet._validate_current_ledge())


class TestFallingAndPerching(PetHarness):
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


class TestSpeechBubbleLayout(PetHarness):
    """The bubble must never be drawn over the sprite.

    This was the bug where the pet vanished every time it spoke, at every
    scale: the widget is sprite_h + bubble_h tall with the bubble above the
    sprite, but the sprite was drawn at the top of the widget, which is exactly
    where the bubble goes.
    """

    def test_sprite_sits_below_the_bubble(self):
        self.pet.speak("a line of dialogue")
        self.pet._sync_widget_geometry()
        self.assertFalse(self.pet.speech_below)
        self.assertEqual(self.pet._sprite_offset(), self.pet.speech_bubble_h)
        self.assertEqual(self.pet.height(),
                         self.pet.sprite_h + self.pet.speech_bubble_h)
        # The sprite's top must be the bottom of the bubble, not inside it.
        self.assertGreaterEqual(self.pet._sprite_offset(), self.pet.speech_bubble_h)

    def test_sprite_at_the_top_when_there_is_no_bubble(self):
        self.pet.speak("hello")
        self.pet._clear_speech()
        self.assertEqual(self.pet._sprite_offset(), 0)

    def test_bubble_flips_below_at_the_top_of_the_screen(self):
        self.pet.y_pos = self.pet.screen_top + 1
        self.pet.speak("a line of dialogue that needs a bubble above it")
        self.pet._sync_widget_geometry()
        self.assertTrue(self.pet.speech_below)
        self.assertEqual(self.pet._sprite_offset(), 0)

    def test_sprite_stays_inside_the_widget_either_way(self):
        for y_pos, label in ((400.0, "bubble above"), (self.pet.screen_top + 1,
                                                        "bubble below")):
            with self.subTest(label):
                self.pet.y_pos = y_pos
                self.pet.speak("some dialogue for the bubble")
                self.pet._sync_widget_geometry()
                offset = self.pet._sprite_offset()
                self.assertGreaterEqual(offset, 0)
                self.assertLessEqual(offset + self.pet.sprite_h, self.pet.height())

    def test_sprite_is_actually_painted(self):
        # The sprite pixels have to be present in the rendered widget, not just
        # accounted for on paper.
        self.pet.speak("a line of dialogue")
        self.pet._sync_widget_geometry()
        image = self.pet.grab().toImage()
        bottom = self.pet._sprite_offset() + self.pet.sprite_h
        # Somewhere in the sprite band there must be a non-background pixel.
        varied = False
        for y in range(self.pet._sprite_offset(), min(bottom, image.height())):
            for x in range(0, min(self.pet.sprite_w, image.width())):
                if image.pixelColor(x, y).alpha() > 0:
                    varied = True
                    break
            if varied:
                break
        self.assertTrue(varied, "nothing was painted where the sprite should be")


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

        # A skipped *background* request stays silent...
        self.pet.ai_request_kind = "idle"
        with patch.object(self.pet, "speak") as speak:
            self.pet._on_ai_line(None, ai_companion.STATUS_SKIPPED)
            speak.assert_not_called()

        # ...but a skipped request the user made themselves gets the canned
        # line, because a menu item that does nothing reads as broken.
        self.pet.ai_request_kind = "user"
        with patch.object(self.pet, "speak") as speak:
            self.pet._on_ai_line(None, ai_companion.STATUS_SKIPPED)
            speak.assert_called_once()

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
        # Running the worker body must redact, filter, encode, then ask.
        with patch("pet.screen_capture.redact") as redact:
            with patch("pet.screen_capture.scan_capture",
                       return_value=(True, "")) as scan:
                with patch("pet.screen_capture.encode_jpeg_base64",
                           return_value="b64") as encode:
                    with patch("pet.ai_companion.request_screenshot_comment") as ask:
                        with patch("pet.ai_companion.record_capture_attempt") as record:
                            captured["target"]()
        redact.assert_called_once()
        scan.assert_called_once()
        encode.assert_called_once()
        ask.assert_called_once()
        record.assert_called_once_with(True)
        self.assertFalse(self.pet._screenshot_inflight)

    def test_sensitive_capture_is_discarded_not_sent(self):
        """The OCR filter runs after redaction and before anything is sent."""
        captured, thread_cls = self._worker_kwargs()
        with patch("pet.ai_companion.screenshot_settings", return_value=self.settings):
            with patch("pet.ai_companion.screenshot_slot_ok", return_value=True):
                with patch("pet.screen_capture.prepare_capture",
                           return_value=(MagicMock(), "")):
                    with patch("pet.threading.Thread", thread_cls):
                        self.pet.maybe_screenshot()
        with patch("pet.screen_capture.redact"):
            with patch("pet.screen_capture.scan_capture",
                       return_value=(False, "sensitive text on screen (card number)")):
                with patch("pet.screen_capture.encode_jpeg_base64") as encode:
                    with patch("pet.ai_companion.request_screenshot_comment") as ask:
                        with patch("pet.ai_companion.record_capture_attempt") as record:
                            with patch("pet.ai_companion.note_capture_decision") as note:
                                captured["target"]()
        encode.assert_not_called()
        ask.assert_not_called()
        record.assert_called_once_with(False)
        self.assertFalse(self.pet._screenshot_inflight)
        self.assertTrue(any(call.args[0] == "discarded" for call in note.call_args_list))

    def test_manual_capture_respects_the_daily_cap(self):
        # reserve_forced_screenshot()'s result used to be thrown away, so a
        # user-initiated capture ignored the daily cap completely.
        with patch("pet.ai_companion.screenshot_settings", return_value=self.settings):
            with patch("pet.ai_companion.ai_enabled", return_value=True):
                with patch("pet.ai_companion.reserve_forced_screenshot",
                           return_value=False) as reserve:
                    with patch("pet.screen_capture.prepare_capture") as prepare:
                        with patch("pet.threading.Thread") as thread:
                            with patch("pet.ai_companion.note_capture_decision") as note:
                                self.pet.maybe_screenshot(force=True)
        reserve.assert_called_once()
        prepare.assert_not_called()
        thread.assert_not_called()
        self.assertTrue(any(call.args[0] == "refused" for call in note.call_args_list))

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
    def land_helper(self):
        self.pet.x_pos, self.pet.y_pos = 200.0, 50.0
        self.pet.vy = 0.0
        self.pet._enter_fall()
        for _ in range(2000):
            self.pet._tick_fall()
            if self.pet.state != "FALL":
                return self.pet.state
        return "FALL"

    def test_drag_clears_the_ledge(self):
        self.assertEqual(self.land_helper(), "PERCH")
        self.pet.mousePressEvent(MagicMock(button=lambda: Qt.LeftButton,
                                           globalPos=lambda: QPoint(300, 300)))
        self.assertIsNone(self.pet.current_ledge)
        self.assertEqual(self.pet.state, "DRAG")

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


class TestMoodsAndEnergy(PetHarness):
    def test_content_by_default(self):
        self.pet.energy = 50.0
        self.pet.petted_until_tick = None
        self.assertEqual(self.pet.mood(), "content")

    def test_sleepy_when_tired(self):
        self.pet.energy = P.MOOD_SLEEPY_MAX - 1
        self.assertEqual(self.pet.mood(), "sleepy")

    def test_sleepy_while_asleep_even_when_full(self):
        self.pet.energy = 100.0
        self.pet._enter_state("SLEEP")
        self.assertEqual(self.pet.mood(), "sleepy")

    def test_happy_only_after_being_petted(self):
        self.pet.energy = 100.0
        self.pet.petted_until_tick = None
        self.assertEqual(self.pet.mood(), "content")
        self.pet.petted_until_tick = self.pet.tick_count
        self.assertEqual(self.pet.mood(), "happy")

    def test_happy_expires(self):
        self.pet.energy = 100.0
        self.pet.petted_until_tick = self.pet.tick_count - 601
        self.assertEqual(self.pet.mood(), "content")

    def test_energy_drains_with_exertion(self):
        self.pet.energy = 100.0
        self.pet._enter_state("CHASE")
        for _ in range(50):
            self.pet._drain_energy()
        self.assertLess(self.pet.energy, 100.0)

    def test_energy_recovers_while_sitting(self):
        self.pet.energy = 50.0
        self.pet._enter_state("SIT")
        self.pet._drain_energy()
        self.assertGreater(self.pet.energy, 50.0)

    def test_energy_recovers_while_sleeping(self):
        self.pet.energy = 10.0
        self.pet._enter_state("SLEEP")
        for _ in range(20):
            self.pet._drain_energy()
        self.assertGreater(self.pet.energy, 10.0)

    def test_energy_never_leaves_range(self):
        self.pet.energy = 99.0
        self.pet._enter_state("SLEEP")
        for _ in range(500):
            self.pet._drain_energy()
        self.assertLessEqual(self.pet.energy, 100.0)
        self.pet.energy = 1.0
        self.pet._enter_state("CHASE")
        for _ in range(500):
            self.pet._drain_energy()
        self.assertGreaterEqual(self.pet.energy, 0.0)

    def test_tired_pet_prefers_sleep(self):
        self.pet.energy = 5.0
        self.pet.state_timer = 100
        self.pet._tick_idle(0, 100)
        self.assertEqual(self.pet.state, "SLEEP")

    def test_tired_pet_does_not_chase(self):
        # Clearly below MOOD_SLEEPY_MAX, so the pet is sleepy and must not
        # start anything energetic.
        for _ in range(50):
            self.pet.energy = 20.0
            self.pet._enter_state("SIT")
            self.pet.state_timer = 200
            self.pet._pick_idle_transition(40, 100)
            self.assertNotIn(self.pet.state, ("CHASE", "STALK", "JUMP", "POUNCE"),
                             "exhausted pet started %s" % self.pet.state)

    def test_mood_drives_the_line_choice(self):
        self.pet.energy = 10.0
        self.assertEqual(self.pet._mood_event(), "sleepy")
        self.pet.energy = 100.0
        self.pet.petted_until_tick = self.pet.tick_count
        with patch("pet.random.random", return_value=0.0):
            self.assertEqual(self.pet._mood_event(), "happy")
        with patch("pet.random.random", return_value=0.9):
            self.assertIsNone(self.pet._mood_event())


class TestNewMovementStates(PetHarness):
    def test_jump_rises_then_lands(self):
        self.pet.x_pos = 300.0
        self.pet.y_pos = self.pet.floor_y
        self.pet.current_ledge = None
        self.pet._start_jump()
        self.assertEqual(self.pet.state, "JUMP")
        start = self.pet.y_pos
        highest = start
        for _ in range(400):
            self.pet._tick_jump()
            highest = min(highest, self.pet.y_pos)
            if self.pet.state != "JUMP":
                break
        self.assertLess(highest, start, "a jump should leave the ground")
        self.assertEqual(self.pet.state, "SIT")
        self.assertAlmostEqual(self.pet.y_pos, self.pet.floor_y)

    def test_jump_does_not_announce_a_drop(self):
        self.pet.y_pos = self.pet.floor_y
        self.pet._start_jump()
        with patch.object(self.pet, "_speak_contextual") as speak:
            for _ in range(400):
                self.pet._tick_jump()
                if self.pet.state != "JUMP":
                    break
        speak.assert_not_called()

    def test_chase_closes_on_the_cursor(self):
        # A cursor that stays put: the pet must actually reach it rather than
        # sprint past, because cursor_dist is recomputed every tick in the real
        # loop and flips it into a pounce.
        target = 300.0

        def distance():
            return abs(target - (self.pet.x_pos + self.pet.sprite_w / 2))

        self.pet.x_pos = 200.0
        self.pet.y_pos = self.pet.floor_y
        self.pet._enter_state("CHASE")
        before = distance()
        for _ in range(200):
            dx = target - (self.pet.x_pos + self.pet.sprite_w / 2)
            self.pet._tick_chase(dx, abs(dx))
            if self.pet.state != "CHASE":
                break
        self.assertLess(distance(), before)
        self.assertIn(self.pet.state, ("POUNCE", "JUMP", "SIT"))

    def test_chase_becomes_a_pounce_up_close(self):
        self.pet.x_pos = 300.0
        self.pet.y_pos = self.pet.floor_y
        self.pet._enter_state("CHASE")
        self.pet._tick_chase(1, 20)
        self.assertEqual(self.pet.state, "POUNCE")

    def test_chase_gives_up_on_a_fleeing_cursor(self):
        self.pet.x_pos = 300.0
        self.pet.y_pos = self.pet.floor_y
        self.pet._enter_state("CHASE")
        self.pet._tick_chase(100, 900)
        self.assertEqual(self.pet.state, "SIT")

    def test_chase_stops_at_the_screen_edge(self):
        self.pet.x_pos = 40.0
        self.pet.y_pos = self.pet.floor_y
        self.pet._enter_state("CHASE")
        for _ in range(60):
            if self.pet.state != "CHASE":
                break
            self.pet._tick_chase(-50, 50)
        self.assertEqual(self.pet.state, "SIT")
        self.assertGreaterEqual(self.pet.x_pos, self.pet.screen_left)

    def test_chase_cannot_run_off_a_ledge(self):
        self.assertEqual(PetHarness.land(self, 200, 50), "PERCH")
        ledge = self.pet.current_ledge
        self.pet._enter_state("CHASE")
        for _ in range(200):
            self.pet._tick_chase(200, 200)
            if self.pet.state != "CHASE":
                break
        self.assertLessEqual(self.pet.x_pos + self.pet.sprite_w, ledge.x_max)

    def test_new_states_have_frames(self):
        for state in ("JUMP", "POUNCE", "CHASE", "LEAP"):
            self.pet.state = state
            self.assertTrue(self.pet.get_frames(), "no frames for %s" % state)
            self.assertIsNotNone(self.pet.get_current_frame())

    def test_jump_can_be_switched_off(self):
        self.pet.allow_jump = False
        self.pet.energy = 100.0
        self.pet.state_timer = 200
        with patch("pet.random.random", return_value=0.30):
            self.pet._pick_idle_transition(40, 100)
        self.assertNotEqual(self.pet.state, "JUMP")


class TestFocusBehaviour(PetHarness):
    def setUp(self):
        super().setUp()
        import tempfile

        import focus_timer

        self.focus_timer = focus_timer
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.focus_path = os.path.join(self.tmp.name, "focus.json")
        # poll_seconds=0 means "read on every call".
        self.pet.focus = focus_timer.FocusWatcher([self.focus_path], poll_seconds=0)

    def write_focus(self, mode="focus", label="docs"):
        self.focus_timer.write_state(self.focus_path, mode, label=label)

    def establish_focus(self):
        """Put the pet in a focus block it already knows about."""
        self.write_focus("focus")
        self.pet._poll_focus_session()

    def test_no_file_means_no_reaction(self):
        with patch.object(self.pet, "_speak_contextual") as speak:
            self.pet._poll_focus_session()
        speak.assert_not_called()
        self.assertFalse(self.pet.in_focus())

    def test_session_start_speaks(self):
        with patch.object(self.pet, "_speak_contextual") as speak:
            self.write_focus("focus")
            self.pet._poll_focus_session()
        speak.assert_called_once_with("focus_start")
        self.assertTrue(self.pet.in_focus())

    def test_session_end_speaks_and_rests(self):
        self.establish_focus()
        self.pet.energy = 50.0
        with patch.object(self.pet, "_speak_contextual") as speak:
            self.write_focus("break")
            self.pet._poll_focus_session()
        speak.assert_called_once_with("focus_end")
        self.assertGreater(self.pet.energy, 50.0)
        self.assertFalse(self.pet.in_focus())

    def test_break_without_focus_is_celebrated(self):
        with patch.object(self.pet, "_speak_contextual") as speak:
            self.write_focus("break")
            self.pet._poll_focus_session()
        speak.assert_called_once_with("happy")

    def test_repeated_polls_do_not_repeat_the_line(self):
        self.establish_focus()
        with patch.object(self.pet, "_speak_contextual") as speak:
            self.pet._poll_focus_session()
            self.pet._poll_focus_session()
        speak.assert_not_called()

    def test_file_disappearing_ends_the_session(self):
        self.establish_focus()
        with patch.object(self.pet, "_speak_contextual") as speak:
            os.unlink(self.focus_path)
            self.pet._poll_focus_session()
        speak.assert_called_once_with("focus_end")

    def test_transition_interrupts_existing_speech(self):
        # The pet is mid-sentence when the timer ends; the user still needs to
        # know, so the session-end line replaces it.
        self.establish_focus()
        self.pet.speak("something long and ongoing")
        self.assertGreater(self.pet.speech_timer, 0)
        with patch.object(self.pet, "_speak_contextual") as speak:
            self.write_focus("break")
            self.pet._poll_focus_session()
        speak.assert_called_once_with("focus_end")

    def test_transition_waits_while_being_dragged(self):
        self.establish_focus()
        self.pet._enter_state("DRAG")
        with patch.object(self.pet, "_speak_contextual") as speak:
            self.write_focus("break")
            self.pet._poll_focus_session()
        speak.assert_not_called()

    def test_pet_stops_chatter_during_focus(self):
        self.establish_focus()
        self.pet.speech_timer = 0
        self.pet.last_window_title = "Editor"
        with patch.object(self.pet, "speak") as speak:
            self.pet._check_window_context()
        speak.assert_not_called()

    def test_pet_does_not_chase_during_focus(self):
        self.establish_focus()
        for _ in range(40):
            self.pet.energy = 100.0
            self.pet._enter_state("SIT")
            self.pet.state_timer = 200
            self.pet._pick_idle_transition(40, 100)
            self.assertNotIn(self.pet.state, ("CHASE", "STALK", "POUNCE"))

    def test_chatter_resumes_after_the_session(self):
        self.establish_focus()
        self.write_focus("break")
        self.pet._poll_focus_session()
        self.assertFalse(self.pet.in_focus())
        self.pet.speech_timer = 0
        self.pet.last_window_title = "Editor"
        with patch.object(self.pet, "speak") as speak:
            self.pet._check_window_context()
        speak.assert_called_once()


class TestIgnoreList(PetHarness):
    def test_ignored_windows_are_not_ledges(self):
        self.pet.tracker.set_ignored_windows(["window a"])
        self.refresh()
        ledges = self.pet.tracker.get_walkable_ledges()
        self.assertEqual([l for l in ledges if l.y == 200], [])
        self.assertTrue([l for l in ledges if l.y == 400])

    def test_ignored_windows_still_visible_for_redaction(self):
        # The pet ignoring a window must not hide it from screenshot redaction.
        self.pet.tracker.set_ignored_windows(["window a"])
        self.refresh()
        titles = [w.title for w in self.pet.tracker.get_windows()]
        self.assertIn("Window A", titles)

    def test_ignored_windows_have_no_climb_edges(self):
        self.pet.tracker.set_ignored_windows(["window a"])
        self.refresh()
        edges = [e for e in self.pet.tracker.get_climbable_edges()
                 if not e.is_screen_edge]
        self.assertEqual([e for e in edges if e.x in (100, 500)], [])

    def test_ignores_by_process_name(self):
        ignore = self.pet.tracker.ignores
        self.pet.tracker.set_ignored_windows(["code"])
        window = wt.WindowInfo(title="anything", rect=(0, 0, 10, 10), process="Code")
        self.assertTrue(ignore(window))
        self.pet.tracker.set_ignored_windows([])
        self.assertFalse(ignore(window))


class TestPersonalityEditor(PetHarness):
    def test_set_and_clear_prompt(self):
        import tempfile

        import ai_companion

        saved_path = ai_companion.CONFIG_PATH
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        tmp.close()
        self.addCleanup(lambda: os.path.exists(tmp.name) and os.unlink(tmp.name))
        ai_companion.CONFIG_PATH = tmp.name
        self.addCleanup(lambda: setattr(ai_companion, "CONFIG_PATH", saved_path))

        self.assertTrue(ai_companion.set_system_prompt("cat", "be a lizard."))
        self.assertEqual(ai_companion.get_system_prompt("cat"), "be a lizard.")
        with open(tmp.name) as handle:
            stored = json.load(handle)
        self.assertEqual(stored["companions"]["cat"]["system_prompt"], "be a lizard.")
        # Applied immediately, without a restart.
        self.assertIn("be a lizard", ai_companion._system_prompt("cat"))

        # Clearing falls back to the default prompt.
        self.assertTrue(ai_companion.set_system_prompt("cat", "   "))
        self.assertEqual(ai_companion.get_system_prompt("cat"), "")
        self.assertNotIn("be a lizard", ai_companion._system_prompt("cat"))

    def test_saving_personality_does_not_clobber_other_config(self):
        import tempfile

        import ai_companion

        saved_path = ai_companion.CONFIG_PATH
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        tmp.close()
        self.addCleanup(lambda: os.path.exists(tmp.name) and os.unlink(tmp.name))
        ai_companion.CONFIG_PATH = tmp.name
        self.addCleanup(lambda: setattr(ai_companion, "CONFIG_PATH", saved_path))
        self.addCleanup(ai_companion.set_system_prompt, "cat", "")

        ai_companion.set_system_prompt("cat", "be a lizard.")
        with open(tmp.name) as handle:
            stored = json.load(handle)
        self.assertIn("screenshots", stored)
        self.assertIn("rate_limits", stored)
        self.assertIn("memory", stored)


class TestLeaping(PetHarness):
    """The pet has to be able to leave the taskbar, or nothing else matters."""

    def place_on_floor(self, x):
        self.pet.x_pos = float(x)
        self.pet.y_pos = self.pet.floor_y
        self.pet.vy = self.pet.vx = 0.0
        self.pet.current_ledge = None
        self.pet._enter_sit()

    def use_windows(self, rects):
        windows = [wt.WindowInfo(id=i + 1, title="W%d" % i, rect=r)
                   for i, r in enumerate(rects)]
        patcher = patch.object(self.pet.tracker, "_query_os_windows",
                               return_value=(windows, None))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.refresh()

    def run_until_settled(self, limit=8000):
        cursor = MagicMock(x=lambda: 400, y=lambda: 400)
        for _ in range(limit):
            self.pet._update_fsm(cursor)
            if self.pet.state in ("PERCH", "SIT", "IDLE") and self.pet.state_timer > 3:
                return self.pet.state
        return self.pet.state

    def titlebars(self):
        return self.pet._titlebar_ledges()

    def test_solves_a_leap_to_a_window_straight_above(self):
        self.use_windows([(0, 0, 1280, 700)])
        self.place_on_floor(640)
        solution = self.pet._leap_solution(self.titlebars()[0])
        self.assertIsNotNone(solution, "a maximised window must be reachable")
        vy0, vx, flight = solution
        self.assertLess(vy0, 0, "must launch upwards")
        self.assertAlmostEqual(vx, 0.0, places=6, msg="directly overhead: no drift")
        self.assertGreater(flight, 10)
        self.assertLessEqual(flight, P.LEAP_MAX_TICKS)

    def test_declines_leaps_it_cannot_make(self):
        self.use_windows([(0, 0, 1280, 700)])
        self.place_on_floor(640)
        ledge = self.titlebars()[0]
        # Same height as the pet: that is a walk, not a leap.
        level = wt.WalkableLedge(y=int(self.pet.floor_y) + self.pet.sprite_h,
                                 x_min=0, x_max=1280)
        self.assertIsNone(self.pet._leap_solution(level))
        # Too far sideways.
        self.assertIsNone(self.pet._leap_solution(ledge, x=-400))
        # Absurdly high.
        self.assertIsNone(self.pet._leap_solution(ledge, y=ledge.y - 5000))
        # A floor ledge is never a leap target.
        self.assertIsNone(self.pet._leap_solution(wt.WalkableLedge(
            y=self.pet.floor_y + 32, x_min=0, x_max=1280, is_floor=True)))

    def test_arc_lands_exactly_on_the_target(self):
        # The analytic arc is the whole point: an integrated one overshoots the
        # apex and lands short, which reads as the pet missing the window.
        self.use_windows([(300, 250, 700, 700)])
        self.place_on_floor(200)
        ledge = self.titlebars()[0]
        _vy0, _vx, flight = self.pet._leap_solution(ledge)
        self.assertTrue(self.pet._start_leap(ledge))
        target_top = float(ledge.y) - self.pet.sprite_h
        apex = self.pet.y_pos
        for _ in range(int(flight) + 8):
            if self.pet.state != "LEAP":
                break
            self.pet._tick_leap()
            apex = min(apex, self.pet.y_pos)
        # It must clear the target, then come down onto it.
        self.assertLess(apex, target_top, "arc never rose above the titlebar")
        self.assertEqual(self.pet.state, "PERCH")
        self.assertIs(self.pet.current_ledge, ledge)
        self.assertAlmostEqual(self.pet.y_pos, target_top, delta=1.0)
        self.assertTrue(ledge.holds_any(self.pet.x_pos,
                                        self.pet.x_pos + self.pet.sprite_w))

    def test_leap_lands_on_a_window_in_every_common_layout(self):
        layouts = [
            ([(0, 0, 1280, 700)], 100.0),      # maximised, far left
            ([(0, 0, 1280, 700)], 1150.0),     # maximised, far right
            ([(700, 380, 1100, 700)], 250.0),   # up and to the right
            ([(150, 300, 400, 700)], 550.0),   # to the left
            ([(0, 0, 600, 700), (650, 0, 1250, 700)], 640.0),  # side by side
        ]
        for rects, start_x in layouts:
            with self.subTest(rects=rects, start_x=start_x):
                self.setUp()
                self.use_windows(rects)
                self.place_on_floor(start_x)
                self.assertTrue(self.pet._start_exploring())
                self.assertEqual(self.run_until_settled(), "PERCH")
                self.assertFalse(self.pet.current_ledge.is_floor)

    def test_walks_under_a_far_window_then_leaps(self):
        self.use_windows([(60, 90, 300, 400)])
        self.place_on_floor(1000)
        self.assertTrue(self.pet._start_exploring())
        self.assertEqual(self.pet.state, "WALK", "should walk first")
        self.assertIsNotNone(self.pet.goal_ledge)
        self.assertEqual(self.run_until_settled(), "PERCH")

    def test_gives_up_when_nothing_is_reachable(self):
        # Nothing a pet could ever jump to: a titlebar at the very top of a
        # very tall screen, with the rise limit squeezed.
        self.use_windows([(0, 0, 1280, 700)])
        self.place_on_floor(640)
        with patch.object(P, "LEAP_MAX_RISE", 10.0):
            self.assertIsNone(self.pet._pick_goal_ledge()[0])
            self.assertFalse(self.pet._start_exploring())

    def test_does_not_target_the_window_it_is_already_on(self):
        self.use_windows([(300, 250, 700, 700)])
        self.place_on_floor(400)
        self.assertTrue(self.pet._start_exploring())
        self.run_until_settled()
        self.assertEqual(self.pet.state, "PERCH")
        # Standing on it, there is nothing else to aim at.
        self.assertIsNone(self.pet._pick_goal_ledge()[0])

    def test_goal_anchor_is_the_nearest_point_not_the_middle(self):
        ledge = wt.WalkableLedge(y=100, x_min=0, x_max=1280)
        anchor = self.pet._goal_anchor(ledge, 32, here=100)
        self.assertEqual(anchor, 100.0, "should not walk to the middle of a window")

    def test_recent_ledges_bias_against_repeats(self):
        self.pet._remember_ledge(wt.WalkableLedge(y=100, x_min=0, x_max=100))
        self.pet._remember_ledge(wt.WalkableLedge(y=200, x_min=0, x_max=100))
        self.assertEqual(self.pet.recent_ledges, [100, 200])
        # Re-visiting moves it to the most-recent slot rather than duplicating.
        self.pet._remember_ledge(wt.WalkableLedge(y=100, x_min=0, x_max=100))
        self.assertEqual(self.pet.recent_ledges, [200, 100])

    def test_closed_window_mid_leap_does_not_crash(self):
        self.use_windows([(0, 0, 1280, 700)])
        self.place_on_floor(640)
        self.assertTrue(self.pet._start_leap(self.titlebars()[0]))
        # The window closes while the pet is in the air. Landing on the stale
        # ledge would leave it perching on a titlebar that no longer exists.
        patcher = patch.object(self.pet.tracker, "_query_os_windows",
                               return_value=([], None))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pet.tracker.invalidate_cache()

        for _ in range(400):
            self.pet._update_fsm(MagicMock(x=lambda: 400, y=lambda: 400))
            if self.pet.state in ("SIT", "IDLE", "PERCH"):
                break
        self.assertIn(self.pet.state, ("SIT", "IDLE"))
        self.assertAlmostEqual(self.pet.y_pos, self.pet.floor_y, delta=1.0)

    def test_leap_always_resolves(self):
        self.use_windows([(0, 0, 1280, 700)])
        self.place_on_floor(640)
        self.assertTrue(self.pet._start_exploring())
        for _ in range(3000):
            self.pet._update_fsm(MagicMock(x=lambda: 400, y=lambda: 400))
            if self.pet.state != "LEAP":
                break
        self.assertNotEqual(self.pet.state, "LEAP", "leap never resolved")
        self.assertIn(self.pet.state, ("PERCH", "SIT", "IDLE"))
        if self.pet.state == "PERCH":
            self.assertFalse(self.pet.current_ledge.is_floor)

    def test_leap_announces_arrival_not_a_drop(self):
        self.use_windows([(0, 0, 1280, 700)])
        self.place_on_floor(640)
        with patch.object(self.pet, "_speak_contextual") as speak:
            self.assertTrue(self.pet._start_exploring())
            for _ in range(3000):
                self.pet._update_fsm(MagicMock(x=lambda: 400, y=lambda: 400))
                if self.pet.state in ("PERCH", "SIT", "IDLE") and self.pet.state_timer > 3:
                    break
        said = [call.args[0] for call in speak.call_args_list]
        self.assertIn("climb", said)
        self.assertIn("perch", said)
        self.assertNotIn("drop", said, "a leap is not a drop")

    def test_top_of_screen_ledge_keeps_the_pet_visible(self):
        top = wt.WalkableLedge(y=0, x_min=0, x_max=1280)
        self.pet.current_ledge = top
        self.pet.y_pos = self.pet._stand_y(top)
        self.assertGreaterEqual(self.pet.y_pos, self.pet.screen_top)
        with patch.object(self.pet.tracker, "_query_os_windows",
                          return_value=([wt.WindowInfo(id=1, title="Max",
                                                       rect=(0, 0, 1280, 700))], None)):
            self.pet.tracker.invalidate_cache()
            self.assertTrue(self.pet._validate_current_ledge())


class TestManualCapture(PetHarness):
    def _capture(self, thread_cls):
        with patch("pet.screen_capture.prepare_capture") as prepare:
            prepare.return_value = (MagicMock(), "")
            with patch("pet.ai_companion.screenshot_slot_ok") as slot:
                with patch("pet.ai_companion.reserve_forced_screenshot") as reserve:
                    with patch("pet.ai_companion.ai_enabled", return_value=True):
                        with patch("pet.threading.Thread", thread_cls):
                            self.pet.maybe_screenshot(force=True)
        return prepare, slot, reserve

    def test_pet_is_hidden_during_the_grab(self):
        # Otherwise the model reads the pet's own speech bubble and comments on
        # the pet commenting on the screen.
        self.pet.show()
        self.assertTrue(self.pet.isVisible())
        seen = {}

        def grab(*_args, **_kwargs):
            seen["visible"] = self.pet.isVisible()
            return MagicMock(), ""

        with patch("pet.screen_capture.prepare_capture", side_effect=grab):
            with patch("pet.ai_companion.ai_enabled", return_value=True):
                with patch("pet.ai_companion.reserve_forced_screenshot"):
                    with patch("pet.threading.Thread"):
                        self.pet.maybe_screenshot(force=True)
        self.assertFalse(seen.get("visible"), "pet was on screen while grabbing")
        self.assertTrue(self.pet.isVisible(), "pet was not restored")

    def test_pet_is_restored_even_if_the_grab_fails(self):
        self.pet.show()
        with patch("pet.screen_capture.prepare_capture",
                   side_effect=RuntimeError("grab failed")):
            with patch("pet.ai_companion.ai_enabled", return_value=True):
                with patch("pet.ai_companion.reserve_forced_screenshot"):
                    with self.assertRaises(RuntimeError):
                        self.pet.maybe_screenshot(force=True)
        self.assertTrue(self.pet.isVisible())

    def test_the_pet_comes_back_on_top_after_a_capture(self):
        # The bug this whole flag-dance exists for: show() after hide() hands
        # the window manager a new mapping and the pet came back *behind* the
        # window it had been covering.
        from PyQt5.QtCore import Qt as QtFlags

        self.pet.show()
        with patch("pet.screen_capture.prepare_capture") as prepare:
            prepare.return_value = (MagicMock(), "")
            with patch("pet.ai_companion.ai_enabled", return_value=True):
                with patch("pet.ai_companion.reserve_forced_screenshot"):
                    with patch("pet.threading.Thread"):
                        self.pet.maybe_screenshot(force=True)
        prepare.assert_called_once()
        self.assertTrue(bool(self.pet.windowFlags() & QtFlags.WindowStaysOnTopHint),
                        "the pet is no longer always-on-top after a capture")
        self.assertTrue(self.pet.isVisible())

    def test_the_flags_survive_click_through_too(self):
        from PyQt5.QtCore import Qt as QtFlags

        self.pet.click_through = True
        self.pet._restack_on_top()
        flags = self.pet.windowFlags()
        self.assertTrue(bool(flags & QtFlags.WindowStaysOnTopHint))
        self.assertTrue(bool(flags & QtFlags.WindowTransparentForInput))

    def test_a_capture_while_hidden_stays_hidden(self):
        # Hidden for a fullscreen window: the capture must not drag the pet
        # back onto the film.
        self.pet.hide()
        self.pet._hidden_for_fullscreen = True
        self.pet._capture_was_visible = False
        self.pet._show_after_capture()
        self.assertFalse(self.pet.isVisible())

    def test_menu_defers_the_capture_until_it_closes(self):
        # Capturing from inside the menu action would put the pet's own menu in
        # the screenshot.
        from PyQt5.QtGui import QContextMenuEvent
        from PyQt5.QtWidgets import QMenu

        pet = self.pet
        pet.show()

        def exec_and_trigger(menu, _pos=None):
            action = _find_action(menu, "Look At This")
            if action is not None:
                action.trigger()
            return None

        timers = []

        def record_single_shot(ms, slot):
            timers.append((ms, slot))

        with patch.object(QMenu, "exec_", exec_and_trigger):
            with patch.object(P.QTimer, "singleShot", staticmethod(record_single_shot)):
                with patch.object(pet, "maybe_screenshot") as capture:
                    pet.contextMenuEvent(
                        QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10)))

                    capture.assert_not_called()   # not while the menu is up
                    self.assertEqual(len(timers), 1, "no deferred capture scheduled")
                    delay_ms, slot = timers[0]
                    self.assertGreaterEqual(delay_ms, P.MENU_CLOSE_DELAY_MS)

                    slot()                      # the menu has closed by now
                    capture.assert_called_once_with(force=True)

    def test_menu_does_not_capture_when_another_action_was_used(self):
        from PyQt5.QtGui import QContextMenuEvent
        from PyQt5.QtWidgets import QMenu

        def exec_and_trigger(menu, _pos=None):
            for action in menu.actions():
                if action.text() == "Speak":
                    action.trigger()
            return None

        timers = []
        # Speak asks the model for a line; stub it, because a unit test must
        # never make a real API call.
        with patch.object(self.pet, "request_dialogue") as request:
            with patch.object(QMenu, "exec_", exec_and_trigger):
                with patch.object(P.QTimer, "singleShot",
                                  staticmethod(lambda ms, slot: timers.append(ms))):
                    with patch.object(self.pet, "maybe_screenshot") as capture:
                        self.pet.contextMenuEvent(
                            QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10)))
        request.assert_called_once()
        capture.assert_not_called()
        self.assertEqual(timers, [])

    def test_manual_capture_works_with_screenshots_disabled(self):
        # The automatic feature is off by default, but "Look At This" is a
        # direct request and must still work.
        import ai_companion

        self.assertFalse(ai_companion.screenshot_settings()["enabled"])
        captured = {}

        class FakeThread:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def start(self):
                pass

        prepare, slot, reserve = self._capture(FakeThread)
        prepare.assert_called_once()
        slot.assert_not_called()
        reserve.assert_called_once()
        self.assertIn("target", captured)

    def test_manual_capture_without_ai_never_sends_anything(self):
        # Look At This still works with the model off -- a local OCR pass
        # picks a canned line -- but nothing may be encoded, threaded or sent.
        grabbed = {}

        def grab(*_args, **_kwargs):
            grabbed["called"] = True
            return MagicMock(), ""

        with patch("pet.screen_capture.prepare_capture", side_effect=grab):
            with patch("pet.screen_capture.encode_jpeg_base64") as encode:
                with patch("pet.screen_capture.capture_topics",
                           return_value="code") as topics:
                    with patch("pet.threading.Thread") as thread:
                        with patch("pet.ai_companion.ai_enabled",
                                   return_value=False):
                            with patch.object(self.pet, "_speak_contextual") as speak:
                                self.pet.maybe_screenshot(force=True)
        self.assertTrue(grabbed.get("called"), "an AI-off look should still look")
        encode.assert_not_called()
        thread.assert_not_called()
        topics.assert_called_once()
        speak.assert_called_once_with("local_look_code")

    def test_local_look_is_still_refused_by_the_blocklist(self):
        with patch("pet.screen_capture.prepare_capture") as prepare:
            prepare.return_value = (None, "focused window matches the blocklist")
            with patch("pet.screen_capture.capture_topics") as topics:
                with patch("pet.ai_companion.ai_enabled", return_value=False):
                    with patch.object(self.pet, "_speak_contextual") as speak:
                        self.pet.maybe_screenshot(force=True)
        topics.assert_not_called()
        speak.assert_called_once_with("screenshot_blocked")

    def test_manual_capture_still_respects_the_blocklist(self):
        with patch("pet.screen_capture.prepare_capture") as prepare:
            prepare.return_value = (None, "focused window matches the blocklist")
            with patch("pet.ai_companion.ai_enabled", return_value=True):
                with patch("pet.ai_companion.reserve_forced_screenshot"):
                    with patch("pet.ai_companion.record_capture_attempt") as record:
                        with patch.object(self.pet, "_speak_contextual") as speak:
                            self.pet.maybe_screenshot(force=True)
        speak.assert_called_once_with("screenshot_blocked")
        self.assertTrue(record.called)
        self.assertFalse(record.call_args[0][0], "a refused capture must not count")


class TestLongRunInvariants(PetHarness):
    def test_random_input_keeps_every_invariant(self):
        """A long randomised run: no crash, no floating, no illegal perch."""
        import random

        random.seed(20260928)
        cursor = QPoint(600, 400)
        self.pet.load_skin("cat")
        self.apply_screen()
        self.refresh()
        self.pet.energy = 100.0
        self.pet.allow_jump = True
        self.pet.allow_chase = True

        states = {}
        for tick in range(6000):
            if tick % 5 == 0:
                cursor = QPoint(random.randint(-20, 1300), random.randint(-20, 740))
            if tick % 401 == 0:
                self.pet.mousePressEvent(
                    MagicMock(button=lambda: Qt.LeftButton,
                              globalPos=lambda: QPoint(300, 300)))
                self.pet.mouseMoveEvent(
                    MagicMock(buttons=lambda: Qt.LeftButton,
                              globalPos=lambda: cursor))
                self.pet.mouseReleaseEvent(
                    MagicMock(button=lambda: Qt.LeftButton,
                              globalPos=lambda: cursor))
            if tick % 601 == 0:
                self.pet.energy = random.choice([5.0, 55.0, 100.0])

            with patch("pet.QCursor", MagicMock(pos=MagicMock(return_value=cursor))):
                self.pet.game_loop()

            states[self.pet.state] = states.get(self.pet.state, 0) + 1
            self.assertIn(self.pet.state, set(P.FRAME_SPEED) | {"IDLE"},
                          "unknown state %s" % self.pet.state)
            if self.pet.state == "PERCH":
                self.assertIsNotNone(self.pet.current_ledge)
                self.assertFalse(self.pet.current_ledge.is_floor)
                self.assertAlmostEqual(
                    self.pet.y_pos, self.pet.current_ledge.y - self.pet.sprite_h,
                    delta=2.0, msg="perched but not on the ledge")
            if self.pet.state in ("SIT", "IDLE", "WALK", "STALK", "RUN", "CHASE",
                                  "SWAT", "BLINK", "GROOM", "SLEEP", "SWAT"):
                if not self.pet._is_on_ledge() and not self.pet.flies:
                    self.assertAlmostEqual(
                        self.pet.y_pos, self.pet.floor_y, delta=12.0,
                        msg="%s floating at %.1f" % (self.pet.state, self.pet.y_pos))
            self.assertGreaterEqual(self.pet.x_pos, self.pet.screen_left - 1)
            self.assertLessEqual(self.pet.x_pos,
                                 self.pet.screen_left + self.pet.screen_w)
            self.assertGreaterEqual(self.pet.energy, 0.0)
            self.assertLessEqual(self.pet.energy, 100.0)
        # A run this long should have exercised more than sitting still.
        self.assertGreaterEqual(len(states), 4, "only saw %s" % sorted(states))


class TestStaleLedgeOutsidePerch(PetHarness):
    """A window that closes under the pet must not leave it in mid-air.

    The validation used to run from PERCH only, so a pet that had settled into
    SIT/WALK/SLEEP on a titlebar kept standing at the height of a window that
    no longer existed.
    """

    def perch_on_window_a(self):
        self.assertEqual(self.land(200, 50), "PERCH")   # Window A, titlebar y=200
        ledge = self.pet.current_ledge
        self.assertIsNotNone(ledge)
        return ledge

    def vanish_the_windows(self):
        with patch.object(self.pet.tracker, "_query_os_windows",
                          return_value=([], None)):
            self.refresh()

    def test_sitting_pet_falls_when_its_window_closes(self):
        ledge = self.perch_on_window_a()
        self.pet._enter_state("SIT")
        self.vanish_the_windows()
        self.pet._update_fsm(QPoint(5, 5))
        self.assertEqual(self.pet.state, "FALL")
        self.assertIsNone(self.pet.current_ledge)
        self.assertLess(self.pet.y_pos, ledge.y)

    def test_walking_pet_falls_when_its_window_closes(self):
        self.perch_on_window_a()
        self.pet._enter_state("WALK")
        self.vanish_the_windows()
        self.pet._update_fsm(QPoint(5, 5))
        self.assertEqual(self.pet.state, "FALL")

    def test_sleeping_pet_falls_when_its_window_closes(self):
        self.perch_on_window_a()
        self.pet._enter_state("SLEEP")
        self.vanish_the_windows()
        self.pet._update_fsm(QPoint(5, 5))
        self.assertEqual(self.pet.state, "FALL")

    def test_a_window_that_moves_out_from_under_the_pet_drops_it(self):
        # Ledge identity is (y, x range): a titlebar that moves is a different
        # ledge, so the pet loses its footing and falls -- onto the new spot
        # when it is below, exactly like a real perch being yanked sideways.
        self.perch_on_window_a()
        moved = [wt.WindowInfo(id=1, title="Window A", rect=(100, 300, 500, 600)),
                 wt.WindowInfo(id=2, title="Window B", rect=(400, 400, 900, 750))]
        with patch.object(self.pet.tracker, "_query_os_windows",
                          return_value=(moved, None)):
            self.refresh()
            self.pet._enter_state("SIT")
            self.pet._update_fsm(QPoint(5, 5))
            self.assertEqual(self.pet.state, "FALL")
            for _ in range(200):
                self.pet._update_fsm(QPoint(5, 5))
                if self.pet.state != "FALL":
                    break
        ledge = self.pet.current_ledge
        self.assertIsNotNone(ledge)
        self.assertEqual(ledge.y, 300)
        self.assertAlmostEqual(self.pet.y_pos, ledge.y - self.pet.sprite_h, delta=1.5)

    def test_a_still_window_keeps_the_pet_seated(self):
        ledge = self.perch_on_window_a()
        self.pet._enter_state("SIT")
        self.pet._update_fsm(QPoint(5, 5))
        self.assertIsNotNone(self.pet.current_ledge)
        self.assertAlmostEqual(self.pet.y_pos, ledge.y - self.pet.sprite_h, delta=1.0)

    def test_a_pet_on_the_floor_is_left_alone(self):
        self.pet._enter_state("SIT")
        ledge = self.pet.current_ledge
        self.assertIsNone(ledge)
        self.pet._update_fsm(QPoint(5, 5))
        self.assertIn(self.pet.state, ("SIT", "IDLE"))
        self.assertAlmostEqual(self.pet.y_pos, self.pet.floor_y, delta=1.0)


class TestQuietHours(PetHarness):
    def set_quiet(self, enabled=True, start="23:00", end="07:00"):
        behaviour = self.pet._behaviour()
        behaviour["quiet_hours"] = {"enabled": enabled, "start": start, "end": end}

    def test_parsing(self):
        self.assertEqual(P._parse_clock("23:30"), 1410)
        self.assertEqual(P._parse_clock("00:05"), 5)
        self.assertIsNone(P._parse_clock("not a time"))
        self.assertIsNone(P._parse_clock(None))

    def test_wraps_midnight(self):
        self.set_quiet(start="23:00", end="07:00")
        with patch("pet.time.localtime",
                   return_value=time.struct_time((2026, 1, 1, 2, 0, 0, 3, 1, 0))):
            self.assertTrue(self.pet._quiet_now())
        with patch("pet.time.localtime",
                   return_value=time.struct_time((2026, 1, 1, 12, 0, 0, 3, 1, 0))):
            self.assertFalse(self.pet._quiet_now())

    def test_plain_window(self):
        self.set_quiet(start="09:00", end="17:00")
        with patch("pet.time.localtime",
                   return_value=time.struct_time((2026, 1, 1, 10, 0, 0, 3, 1, 0))):
            self.assertTrue(self.pet._quiet_now())
        with patch("pet.time.localtime",
                   return_value=time.struct_time((2026, 1, 1, 20, 0, 0, 3, 1, 0))):
            self.assertFalse(self.pet._quiet_now())

    def test_disabled_or_broken_config_is_never_quiet(self):
        self.set_quiet(enabled=False)
        self.assertFalse(self.pet._quiet_now())
        self.set_quiet(start="garbage")
        self.assertFalse(self.pet._quiet_now())

    def test_quiet_hours_silence_the_context_chatter(self):
        self.set_quiet()
        self.pet.speech_timer = 0
        with patch.object(self.pet, "speak") as speak:
            with patch("pet.time.localtime",
                       return_value=time.struct_time((2026, 1, 1, 23, 30, 0, 3, 1, 0))):
                self.pet._check_window_context()
        speak.assert_not_called()

    def test_a_quiet_hour_nap_still_lets_the_user_speak(self):
        import ai_companion

        self.set_quiet()
        with patch.object(ai_companion, "ai_enabled", return_value=False):
            with patch.object(self.pet, "speak") as speak:
                self.pet.request_dialogue(user_initiated=True)
        self.assertTrue(speak.called, "an explicit request must always answer")

    def test_a_throttled_user_request_falls_back_to_a_canned_line(self):
        # maybe_idle_line reports SKIPPED synchronously when the pool is full;
        # the menu item must still say something.
        import ai_companion

        def fake_idle_line(skin, on_done, kind="idle"):
            on_done(None, ai_companion.STATUS_SKIPPED)

        with patch.object(ai_companion, "maybe_idle_line", side_effect=fake_idle_line):
            with patch.object(ai_companion, "ai_enabled", return_value=True):
                with patch.object(self.pet, "speak") as speak:
                    self.pet.request_dialogue(user_initiated=True)
        self.assertTrue(speak.called)


class TestIdleNap(PetHarness):
    def test_naps_after_the_configured_idle_time(self):
        self.pet._enter_state("SIT")
        with patch.object(self.pet, "_user_idle_seconds", return_value=400.0):
            self.pet._update_fsm(QPoint(5, 5))
        self.assertEqual(self.pet.state, "SLEEP")

    def test_stays_awake_before_it(self):
        self.pet._enter_state("SIT")
        with patch.object(self.pet, "_user_idle_seconds", return_value=5.0):
            self.pet._update_fsm(QPoint(5, 5))
        self.assertNotEqual(self.pet.state, "SLEEP")

    def test_disabled_with_zero(self):
        self.pet._behaviour()["sleep_when_idle_seconds"] = 0
        self.pet._enter_state("SIT")
        with patch.object(self.pet, "_user_idle_seconds", return_value=99999.0):
            self.pet._update_fsm(QPoint(5, 5))
        self.assertNotEqual(self.pet.state, "SLEEP")

    def test_never_naps_in_the_middle_of_the_air(self):
        self.pet.y_pos = 0.0
        self.pet._enter_fall()
        with patch.object(self.pet, "_user_idle_seconds", return_value=99999.0):
            self.pet._update_fsm(QPoint(5, 5))
        self.assertEqual(self.pet.state, "FALL")

    def test_an_idle_pet_stays_asleep_past_its_timer(self):
        self.pet._enter_state("SLEEP")
        self.pet.state_timer = P.STATE_MAX_DURATION.get("SLEEP", 300) + 50
        with patch.object(self.pet, "_user_idle_seconds", return_value=9999.0):
            self.pet._update_fsm(QPoint(500, 500))
        self.assertEqual(self.pet.state, "SLEEP", "woke up while nobody was there")

    def test_waking_when_the_user_comes_back(self):
        self.pet._enter_state("SLEEP")
        self.pet.state_timer = P.STATE_MAX_DURATION.get("SLEEP", 300) + 50
        with patch.object(self.pet, "_user_idle_seconds", return_value=1.0):
            self.pet._update_fsm(QPoint(500, 500))
        self.assertNotEqual(self.pet.state, "SLEEP")


class TestLateReplyHandling(PetHarness):
    def test_a_late_reply_does_not_overwrite_newer_speech(self):
        import ai_companion

        self.pet.awaiting_ai = True
        self.pet.ai_deadline = self.pet.tick_count - 1
        self.pet.ai_request_kind = "idle"
        self.pet.speech_timer = 0
        with patch.object(self.pet, "speak") as speak:
            self.pet.game_loop()          # deadline missed: canned line
        self.assertTrue(speak.called)
        # The user (or another event) says something else; the model reply
        # arrives afterwards and must not replace it mid-sentence.
        self.pet.speak("something newer")
        with patch.object(self.pet, "speak") as speak:
            self.pet._on_ai_line("the late model line", ai_companion.STATUS_OK)
        speak.assert_not_called()

    def test_a_late_reply_is_still_used_when_the_bubble_is_empty(self):
        import ai_companion

        self.pet.awaiting_ai = True
        self.pet.ai_deadline = self.pet.tick_count - 1
        self.pet.speech_timer = 0
        with patch.object(self.pet, "speak") as first:
            self.pet.game_loop()
        self.pet.speech_timer = 0
        self.pet.speech_text = None
        with patch.object(self.pet, "speak") as speak:
            self.pet._on_ai_line("the late model line", ai_companion.STATUS_OK)
        speak.assert_called_once_with("the late model line")


class TestMenuToggles(PetHarness):
    def setUp(self):
        super().setUp()
        import pet_state
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_path = os.path.join(self.tmp.name, "state.json")

    def make_state_store(self):
        import pet_state

        return pet_state.PetState(path=self.state_path)

    def hidden_state(self):
        store = self.make_state_store()
        store.load()
        return store.data

    def test_movement_toggles_persist(self):
        store = self.make_state_store()
        self.pet.state_store = store
        self.pet._set_movement_flag("allow_jump", False)
        self.pet._set_movement_flag("allow_chase", False)
        self.assertFalse(self.pet.allow_jump)
        self.assertFalse(self.pet.allow_chase)
        saved = self.hidden_state()
        self.assertFalse(saved["allow_jump"])
        self.assertFalse(saved["allow_chase"])

    def test_climb_toggle_persists(self):
        self.pet.state_store = self.make_state_store()
        self.pet._set_climb(False)
        self.assertFalse(self.pet.climb_enabled)
        self.assertFalse(self.hidden_state()["climb_enabled"])

    def test_click_through_persists_and_sets_the_flag(self):
        self.pet.state_store = self.make_state_store()
        self.pet._set_click_through(True)
        self.assertTrue(self.pet.click_through)
        self.assertTrue(bool(self.pet.windowFlags() & Qt.WindowTransparentForInput))
        self.assertTrue(self.hidden_state()["click_through"])
        self.pet._set_click_through(False)
        self.assertFalse(bool(self.pet.windowFlags() & Qt.WindowTransparentForInput))

    def test_treat_feeds_and_counts(self):
        self.pet.state_store = self.make_state_store()
        self.pet.energy = 40.0
        with patch.object(self.pet, "_speak_contextual") as speak:
            self.pet._menu_treat()
        self.assertEqual(self.pet.energy, 65.0)
        self.assertTrue(speak.called)
        self.assertEqual(self.hidden_state()["treats_given"], 1)
        # Spamming the menu must not be a free energy tap.
        with patch.object(self.pet, "_speak_contextual"):
            self.pet._menu_treat()
        self.assertEqual(self.pet.energy, 65.0)

    def test_stats_line_mentions_the_counters(self):
        self.pet.state_store = self.make_state_store()
        text = self.pet._stats_text()
        self.assertIn("alive", text)
        self.assertIn("treats", text)


class TestPrivacyMenu(PetHarness):
    def test_menu_exposes_the_privacy_controls(self):
        menu = self.pet._build_menu()
        for label in ("Screenshots && Privacy", "Look At This",
                      "Never Capture This App", "Edit Blocklist...",
                      "OCR Content Filter", "What Happened To My Screens..."):
            self.assertIsNotNone(_find_action(menu, label),
                                 "menu is missing %r" % label)

    def test_the_tray_menu_is_rebuilt_from_live_state(self):
        from PyQt5.QtWidgets import QMenu

        menu = QMenu()
        self.pet.tray_menu = menu
        self.pet._repopulate_tray_menu()
        self.assertIsNotNone(_find_action(menu, "Speak"))
        # A rebuild must replace the old contents, not pile up duplicates.
        second = self.pet._build_menu(menu)
        self.assertIs(second, menu)
        labels = [a.text() for a in menu.actions() if a.text()]
        self.assertEqual(len(labels), len(set(labels)))

    def test_screenshot_toggle_writes_the_config(self):
        import ai_companion

        with patch.object(ai_companion, "save_config", return_value=True) as save:
            self.pet._set_screenshots_enabled(True)
            self.assertTrue(ai_companion.CONFIG["screenshots"]["enabled"])
            self.pet._set_screenshots_enabled(False)
            self.assertFalse(ai_companion.CONFIG["screenshots"]["enabled"])
        self.assertEqual(save.call_count, 2)

    def test_ocr_toggle_writes_the_config(self):
        import ai_companion

        with patch.object(ai_companion, "save_config", return_value=True):
            self.pet._set_ocr_enabled(False)
            self.assertFalse(ai_companion.ocr_settings()["enabled"])
            self.pet._set_ocr_enabled(True)
            self.assertTrue(ai_companion.ocr_settings()["enabled"])

    def test_block_current_app_adds_a_process_rule(self):
        import ai_companion

        window = wt.WindowInfo(id=9, title="Vault", rect=(0, 0, 100, 100),
                               process="keepassxc", pid=123)
        with patch.object(self.pet, "_focused_window", return_value=window):
            with patch.object(ai_companion, "save_config", return_value=True):
                with patch.object(self.pet, "speak") as speak:
                    self.pet._menu_block_current_app()
        self.assertIn("proc:keepassxc", ai_companion.blocklist())
        self.assertTrue(speak.called)

    def test_block_current_app_falls_back_to_a_title_rule(self):
        import ai_companion

        window = wt.WindowInfo(id=9, title="Vault", rect=(0, 0, 100, 100),
                               process="", pid=0)
        with patch.object(self.pet, "_focused_window", return_value=window):
            with patch.object(ai_companion, "save_config", return_value=True):
                with patch.object(self.pet, "speak"):
                    self.pet._menu_block_current_app()
        self.assertIn("title:Vault", ai_companion.blocklist())

    def test_blocking_with_nothing_focused_says_so(self):
        with patch.object(self.pet, "_focused_window", return_value=None):
            with patch.object(self.pet, "speak") as speak:
                self.pet._menu_block_current_app()
        self.assertTrue(speak.called)


class TestFullscreenHide(PetHarness):
    def enable_hide(self, enabled=True):
        self.pet._behaviour()["hide_on_fullscreen"] = enabled

    def test_hides_for_a_fullscreen_window(self):
        self.enable_hide()
        with patch.object(self.pet.tracker, "fullscreen_active", return_value=True):
            self.pet.show()
            self.pet._check_fullscreen()
        self.assertTrue(self.pet._hidden_for_fullscreen)
        self.assertFalse(self.pet.isVisible())

    def test_comes_back_when_it_ends(self):
        self.enable_hide()
        with patch.object(self.pet.tracker, "fullscreen_active", return_value=True):
            self.pet.show()
            self.pet._check_fullscreen()
        with patch.object(self.pet.tracker, "fullscreen_active", return_value=False):
            self.pet._check_fullscreen()
        self.assertFalse(self.pet._hidden_for_fullscreen)
        self.assertTrue(self.pet.isVisible())

    def test_can_be_switched_off(self):
        self.enable_hide(False)
        with patch.object(self.pet.tracker, "fullscreen_active", return_value=True):
            self.pet.show()
            self.pet._check_fullscreen()
        self.assertFalse(self.pet._hidden_for_fullscreen)
        self.assertTrue(self.pet.isVisible())

    def test_no_capture_while_hidden(self):
        with patch("pet.screen_capture.prepare_capture") as prepare:
            self.pet._hidden_for_fullscreen = True
            self.pet.maybe_screenshot(force=True)
        prepare.assert_not_called()


class TestScreenGeometry(PetHarness):
    def test_virtual_desktop_covers_every_screen(self):
        from PyQt5.QtCore import QRect

        class FakeScreen:
            def __init__(self, rect):
                self._rect = QRect(*rect)

            def geometry(self):
                return self._rect

        screens = [FakeScreen((-1920, 0, 1920, 1080)),
                   FakeScreen((0, 0, 1280, 720))]
        with patch.object(QApplication, "screens", return_value=screens):
            rect = self.pet._virtual_desktop_rect()
        self.assertEqual(rect, (-1920, 0, 1280, 1080))

    def test_dragging_onto_a_monitor_left_of_primary_is_allowed(self):
        from PyQt5.QtCore import QRect

        class FakeScreen:
            def __init__(self, rect):
                self._rect = QRect(*rect)

            def geometry(self):
                return self._rect

        screens = [FakeScreen((-1920, 0, 1920, 1080)),
                   FakeScreen((0, 0, 1280, 720))]
        event = MagicMock(buttons=lambda: Qt.LeftButton,
                          globalPos=lambda: QPoint(-1000, 400))
        with patch.object(QApplication, "screens", return_value=screens):
            self.pet.drag_offset = QPoint(0, 0)
            self.pet.mouseMoveEvent(event)
        self.assertLess(self.pet.x_pos, 0)
        self.assertGreaterEqual(self.pet.x_pos, -1920)

    def test_no_screens_falls_back_to_the_current_one(self):
        with patch.object(QApplication, "screens", return_value=[]):
            self.assertEqual(self.pet._virtual_desktop_rect(), self.pet.screen_rect)


class TestFlingPhysics(PetHarness):
    def drag_with_speed(self, points, per_step=0.02):
        """Send a press + cursor path, then release. `points`: [(x, y), ...]."""
        import time as time_mod

        press = MagicMock(button=lambda: Qt.LeftButton,
                          globalPos=lambda: QPoint(points[0][0], points[0][1]))
        self.pet.mousePressEvent(press)
        stamp = time_mod.time()
        for x, y in points[1:]:
            stamp += per_step
            with patch.object(time_mod, "time", return_value=stamp):
                move = MagicMock(buttons=lambda: Qt.LeftButton,
                                 globalPos=lambda: QPoint(x, y))
                self.pet.mouseMoveEvent(move)
        release = MagicMock(button=lambda: Qt.LeftButton,
                            globalPos=lambda: QPoint(points[-1][0],
                                                     points[-1][1]))
        self.pet.mouseReleaseEvent(release)

    def test_a_fast_release_throws_the_pet(self):
        self.pet.show()
        self.drag_with_speed([(500, 550), (560, 540), (620, 520), (700, 500)])
        self.assertNotEqual(self.pet.state, "DRAG")
        self.assertEqual(self.pet.land_event, "fling")
        self.assertGreater(self.pet.vx, 0.0, "moving right should throw right")

    def test_a_slow_release_is_a_plain_drop(self):
        self.pet.show()
        self.drag_with_speed([(500, 500), (502, 501), (503, 502)],
                             per_step=0.4)
        self.assertEqual(self.pet.vx, 0.0)
        self.assertNotEqual(self.pet.land_event, "fling")

    def test_a_fling_speaks_about_it_on_landing(self):
        self.pet.show()
        self.drag_with_speed([(400, 400), (700, 380), (1000, 360)])
        for _ in range(400):
            self.pet._update_fsm(QPoint(5, 5))
            if self.pet.state != "FALL":
                break
        self.assertNotEqual(self.pet.state, "FALL")
        self.assertTrue(self.pet.speech_text, "a fling should get a comment")
        # It should have actually travelled.
        self.assertGreater(self.pet.x_pos, 450.0)

    def test_the_arc_stays_inside_the_desktop(self):
        self.pet.show()
        self.drag_with_speed([(200, 300), (1300, 300), (5000, 300)])
        for _ in range(600):
            self.pet._update_fsm(QPoint(5, 5))
            if self.pet.state not in ("FALL", "JUMP", "POUNCE"):
                break
        left, top, right, bottom = self.pet._virtual_desktop_rect()
        self.assertGreaterEqual(self.pet.x_pos, left)
        self.assertLessEqual(self.pet.x_pos + self.pet.sprite_w, right)

    def test_releasing_on_another_monitor_reseats_the_screen(self):
        self.pet.show()
        with patch.object(self.pet, "_refresh_screen_geometry") as refresh:
            self.drag_with_speed([(100, 100), (120, 110)])
        # A drag release must re-read which screen the pet is on before the
        # arc decides where the floor is.
        self.assertTrue(refresh.called)

    def test_history_is_bounded(self):
        self.pet.show()
        for index in range(40):
            move = MagicMock(buttons=lambda: Qt.LeftButton,
                             globalPos=lambda: QPoint(100 + index, 200))
            self.pet.mouseMoveEvent(move)
        self.assertLessEqual(len(self.pet._drag_history), 8)


class TestSnooze(PetHarness):
    def test_shushing_mutes_idle_chatter(self):
        self.pet.snooze_for(900)
        self.assertTrue(self.pet._quiet_now())

    def test_speak_still_answers(self):
        self.pet.snooze_for(900)
        with patch.object(ai_companion, "ai_enabled", return_value=False):
            with patch.object(self.pet, "speak") as speak:
                self.pet.request_dialogue(user_initiated=True)
        self.assertTrue(speak.called, "an explicit request is never muted")

    def test_petting_ends_the_snooze(self):
        self.pet.snooze_for(900)
        self.pet.mouseReleaseEvent(MagicMock(
            button=lambda: Qt.LeftButton, globalPos=lambda: QPoint(10, 10)))
        self.assertEqual(self.pet._snoozed_until, 0)
        self.assertFalse(self.pet._quiet_now())

    def test_unshush_from_the_menu(self):
        self.pet.snooze_for(900)
        self.pet._menu_shush(0)
        self.assertFalse(self.pet._quiet_now())

    def test_an_expired_snooze_clears_itself(self):
        self.pet.snooze_for(-1)     # already over
        self.assertFalse(self.pet._quiet_now())
        self.assertEqual(self.pet._snoozed_until, 0,
                         "an expired snooze should not linger")

    def test_status_line_mentions_it(self):
        self.pet.snooze_for(90)
        self.assertIn("shushed for 2 more min", self.pet._status_text())
        self.pet.snooze_for(0)
        self.assertNotIn("shushed", self.pet._status_text())

    def test_quiet_hours_live_alongside_the_snooze(self):
        cfg = self.pet._behaviour()
        cfg["quiet_hours"] = {"enabled": True, "start": "00:00", "end": "23:59"}
        self.assertTrue(self.pet._quiet_now())
        self.pet.snooze_for(0)
        self.assertTrue(self.pet._quiet_now(), "quiet hours are still on")
        cfg["quiet_hours"] = {"enabled": False}
        self.pet.snooze_for(0)
        self.assertFalse(self.pet._quiet_now())

    def test_the_menu_offers_shush_items(self):
        menu = self.pet._build_menu()
        self.assertIsNotNone(_find_action(menu, "Shush..."))
        self.assertIsNotNone(_find_action(menu, "15 minutes"))
        self.assertIsNotNone(_find_action(menu, "Unshush Now"))


class TestMilestone(PetHarness):
    def store_with_lifetime(self, seconds):
        import pet_state
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = pet_state.PetState(path=os.path.join(tmp.name, "s.json"),
                                   save_interval=0)
        store.load()
        store.lifetime_base = float(seconds)
        store.data["milestone_days"] = 0
        self.pet.state_store = store
        return store

    def test_marks_the_day_and_speaks_once(self):
        store = self.store_with_lifetime(86400.0 + 60.0)   # just over a day
        with patch.object(self.pet, "speak") as speak:
            self.pet._check_milestone()
        self.assertTrue(speak.called)
        self.assertEqual(store.data["milestone_days"], 1)
        self.assertIn("1", speak.call_args[0][0])
        with patch.object(self.pet, "speak") as speak:
            self.pet._check_milestone()
        self.assertFalse(speak.called, "the same day must not be re-celebrated")

    def test_day_two_speaks_again(self):
        store = self.store_with_lifetime(2 * 86400.0)
        store.data["milestone_days"] = 1
        with patch.object(self.pet, "speak") as speak:
            self.pet._check_milestone()
        self.assertEqual(store.data["milestone_days"], 2)
        self.assertTrue(speak.called)


class TestLocalLookTopics(unittest.TestCase):
    def test_topics(self):
        self.assertEqual(sc.detect_topics(""), "blank")
        self.assertEqual(sc.detect_topics("   \n \n "), "blank")
        self.assertEqual(sc.detect_topics(
            "def main():\n    import os\nprint(error)"), "code")
        self.assertEqual(sc.detect_topics(
            "2001 2002 2003 2004 2005 2006 2007"), "numbers")
        self.assertEqual(sc.detect_topics("word " * 50), "text")
        self.assertEqual(sc.detect_topics("just a little note"), "blank")

    def test_capture_topics_needs_no_engine(self):
        with patch.object(sc, "ocr_guard", None):
            self.assertEqual(sc.capture_topics(MagicMock()), "blank")

    def test_capture_topics_reduces_to_a_name(self):
        with patch.object(sc, "ocr_guard", MagicMock()) as guard:
            guard.recognize.return_value = "$ git status\nnothing to commit"
            self.assertEqual(sc.capture_topics(MagicMock()), "code")


class TestMenuForget(PetHarness):
    def test_forget_resets_the_toggles_and_position(self):
        import pet_state
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pet.state_store = pet_state.PetState(
            path=os.path.join(tmp.name, "s.json"))
        self.pet.click_through = True
        self.pet._set_click_through(True)
        self.pet.x_pos = 900.0
        with patch.object(self.pet, "_speak_contextual") as speak:
            self.pet._menu_forget()
        self.assertFalse(self.pet.click_through)
        self.assertFalse(bool(self.pet.windowFlags() & Qt.WindowTransparentForInput))
        self.assertLess(self.pet.x_pos, self.pet.screen_w)
        self.assertTrue(speak.called)


class FakeMessageBox:
    """QMessageBox stand-in that records what the handler showed."""

    Ok = 0x00200000          # real StandardButton values, so `|` composes
    Yes = 0x00004000
    No = 0x00010000
    DestructiveRole = "destructive"
    instances = []

    def __init__(self, parent=None):
        self.title = None
        self.text = None
        self.detail = None
        self.buttons = []
        self.clicked = None
        self.return_code = None
        FakeMessageBox.instances.append(self)

    def setWindowTitle(self, value):
        self.title = value

    def setText(self, value):
        self.text = value

    def setDetailedText(self, value):
        self.detail = value

    def setStandardButtons(self, *values):
        self.buttons = list(values)

    def setDefaultButton(self, value):
        pass

    def addButton(self, label, role):
        self.buttons.append(label)
        return label

    def clickedButton(self):
        return self.clicked

    def exec_(self):
        return self.return_code


class TestMenuMemory(PetHarness):
    """'What Do You Remember?' reads the memory file back, and can erase it."""

    def point_memory(self, file_bytes):
        """Point ai_companion at a throwaway memory file holding `file_bytes`."""
        import ai_companion

        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        handle.close()
        with open(handle.name, "w", encoding="utf-8") as fh:
            fh.write(file_bytes)
        saved = ai_companion.MEMORY_PATH
        ai_companion.MEMORY_PATH = handle.name
        self.addCleanup(lambda: os.path.exists(handle.name)
                        and os.unlink(handle.name))
        self.addCleanup(lambda: setattr(ai_companion, "MEMORY_PATH", saved))
        return handle.name

    def run_menu(self, speak=True):
        FakeMessageBox.instances = []
        with patch("PyQt5.QtWidgets.QMessageBox", FakeMessageBox):
            if speak:
                with patch.object(self.pet, "speak") as speak_mock:
                    self.pet._menu_memory()
                    return FakeMessageBox.instances, speak_mock
            self.pet._menu_memory()
            return FakeMessageBox.instances, None

    def test_lists_the_facts_read_only(self):
        self.point_memory('["you like mango", "you fear moths"]')
        boxes, _ = self.run_menu(speak=False)
        shown = boxes[0]
        self.assertIn("2", shown.text)
        self.assertIn("you like mango", shown.detail)
        self.assertIn("you fear moths", shown.detail)
        self.assertIn("Forget Everything", shown.buttons)
        # a plain read opens exactly one dialog and nothing more
        self.assertEqual(len(boxes), 1)

    def test_empty_memory_says_so_without_a_forget_button(self):
        self.point_memory("[]")
        boxes, _ = self.run_menu(speak=False)
        shown = boxes[0]
        self.assertIn("Nothing yet", shown.detail)
        self.assertNotIn("Forget Everything", shown.buttons)
        self.assertEqual(len(boxes), 1)

    def test_forget_everything_erases_the_file(self):
        import ai_companion

        path = self.point_memory('["you like mango"]')

        def scripted_exec(box):
            # first dialog: the erase button is pressed; the second agrees
            if box is FakeMessageBox.instances[0]:
                box.clicked = "Forget Everything"
                return None
            return FakeMessageBox.Yes

        FakeMessageBox.instances = []
        with patch("PyQt5.QtWidgets.QMessageBox", FakeMessageBox):
            with patch.object(FakeMessageBox, "exec_", scripted_exec):
                with patch.object(self.pet, "speak") as speak_mock:
                    self.pet._menu_memory()
        self.assertEqual(len(FakeMessageBox.instances), 2)
        final = [call.args[0] for call in speak_mock.call_args_list]
        self.assertIn("forgotten. clean slate.", final)
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), [])

    def test_declining_the_erase_keeps_everything(self):
        path = self.point_memory('["you like mango"]')

        def scripted_exec(box):
            if box is FakeMessageBox.instances[0]:
                box.clicked = None                    # a plain Ok read
                return None
            return FakeMessageBox.No

        FakeMessageBox.instances = []
        with patch("PyQt5.QtWidgets.QMessageBox", FakeMessageBox):
            with patch.object(FakeMessageBox, "exec_", scripted_exec):
                with patch.object(self.pet, "speak") as speak_mock:
                    self.pet._menu_memory()
        final = [call.args[0] for call in speak_mock.call_args_list]
        self.assertEqual(final, [])
        with open(path, encoding="utf-8") as handle:
            self.assertIn("mango", handle.read())

    def test_facts_helper_caps_and_orders(self):
        import ai_companion

        with patch.object(ai_companion, "_load_memory",
                          return_value=["a", "b", "c"]):
            self.assertEqual(ai_companion.memory_facts(limit=2), ["b", "c"])
            self.assertEqual(ai_companion.memory_facts(), ["a", "b", "c"])


def _fake_cf():
    """CoreFoundation stand-in: plain-function attrs so restype/argtypes stick."""
    cf = lambda: None
    cf.CFStringCreateWithCString = lambda alloc, data, encoding: (
        data.decode("utf-8"))
    cf.CFArrayGetCount = lambda ref: len(ref)
    cf.CFArrayGetValueAtIndex = lambda ref, index: ref[index]

    def dict_value(dict_ref, key):
        try:
            return dict_ref.get(key)
        except Exception:
            return None

    cf.CFDictionaryGetValue = dict_value

    def number(raw, code, out):
        out._obj.value = raw[1] if isinstance(raw, tuple) else raw
        return True

    cf.CFNumberGetValue = number

    def string(raw, buf, size, encoding):
        text = raw[1] if isinstance(raw, tuple) else str(raw)
        buf.value = text.encode("utf-8")
        return True

    cf.CFStringGetCString = string
    return cf


def _bounds(x, y, w, h):
    return {"X": ("n", float(x)), "Y": ("n", float(y)),
            "Width": ("n", float(w)), "Height": ("n", float(h))}


class TestMacosTracking(unittest.TestCase):
    """The macOS backends must parse CoreGraphics output and fail closed."""

    def test_not_mac_returns_none(self):
        with patch.object(wt, "IS_MAC", False):
            self.assertIsNone(wt._macos_active_window())
            self.assertIsNone(wt._macos_idle_seconds())

    def test_missing_frameworks_returns_none(self):
        with patch.object(wt, "_macos_core_foundation",
                          return_value=(None, None)):
            self.assertIsNone(wt._macos_active_window())
            self.assertIsNone(wt._macos_idle_seconds())

    def test_active_window_parses_frontmost_layer0(self):
        array = [
            {"kCGWindowLayer": ("n", 20),                      # an overlay first
             "kCGWindowBounds": _bounds(0, 0, 200, 30)},
            {"kCGWindowLayer": ("n", 0),                       # too tiny: tooltip
             "kCGWindowBounds": _bounds(10, 10, 300, 10)},
            {"kCGWindowLayer": ("n", 0),                       # the real window
             "kCGWindowBounds": _bounds(0, 25, 1440, 900),
             "kCGWindowOwnerPID": ("n", 42),
             "kCGWindowName": ("s", "Spring Game"),
             "kCGWindowOwnerName": ("s", "spring")},
            {"kCGWindowLayer": ("n", 0),                       # behind: ignored
             "kCGWindowBounds": _bounds(5, 5, 800, 600)},
        ]
        # plain-function attributes: the module tacks restype/argtypes onto
        # the handles, which bound methods would refuse
        fake = lambda: None
        fake.options = None

        def copy_window_info(option, window_id):
            fake.options = (option, window_id)
            return array

        fake.CGWindowListCopyWindowInfo = copy_window_info
        with patch.object(wt, "IS_MAC", True):
            with patch.object(wt, "_macos_core_foundation",
                              return_value=(fake, _fake_cf())):
                window = wt._macos_active_window()
        self.assertIsNotNone(window)
        self.assertEqual(window.title, "Spring Game")
        self.assertEqual(window.rect, (0, 25, 1440, 925))
        self.assertEqual(window.pid, 42)
        # on-screen only, desktop elements excluded: no zip files of the
        # desktop, no wandering icons
        self.assertEqual(fake.options[0], 1 | 16)

    def test_no_usable_window_returns_none(self):
        array = [{"kCGWindowLayer": ("n", 20),
                  "kCGWindowBounds": _bounds(0, 0, 800, 600)}]
        with patch.object(wt, "IS_MAC", True):
            with patch.object(wt, "_macos_core_foundation",
                              return_value=(object(), _fake_cf())):
                self.assertIsNone(wt._macos_active_window())

    def test_idle_reads_combined_session(self):
        seen = {}

        def fake_query(state, event):
            seen["state"] = state
            seen["event"] = event
            return 12.5

        fake = lambda: None
        fake.CGEventSourceSecondsSinceLastEventType = fake_query
        with patch.object(wt, "IS_MAC", True):
            with patch.object(wt, "_macos_core_foundation",
                              return_value=(fake, object())):
                idle = wt._macos_idle_seconds()
        self.assertEqual(idle, 12.5)
        # combined session state (-1), any input type (~0); ctypes may hand
        # the fake wrapped objects, so unwrap before comparing
        self.assertEqual(getattr(seen["state"], "value", seen["state"]), -1)
        self.assertEqual(getattr(seen["event"], "value", seen["event"]),
                         2 ** 64 - 1)

    def test_idle_negative_answer_is_no_answer(self):
        fake = lambda: None
        fake.CGEventSourceSecondsSinceLastEventType = lambda state, event: -1.0
        with patch.object(wt, "IS_MAC", True):
            with patch.object(wt, "_macos_core_foundation",
                              return_value=(fake, object())):
                self.assertIsNone(wt._macos_idle_seconds())

    def test_idle_dispatch_uses_mac_branch(self):
        with patch.object(wt, "IS_WIN", False):
            with patch.object(wt, "IS_LINUX", False):
                with patch.object(wt, "IS_MAC", True):
                    with patch.object(wt, "_macos_idle_seconds",
                                      return_value=7.5):
                        self.assertEqual(wt.idle_seconds(), 7.5)

    def test_detection_functions_trust_mac(self):
        with patch.object(wt, "IS_MAC", True):
            with patch.object(wt, "wayland_session", lambda: False):
                self.assertTrue(wt.window_detection_available())
                self.assertTrue(wt._detection_is_complete())




# =====================================================================
# Reactions, juice and pixel-perfect rendering
# =====================================================================

def _click():
    return MagicMock(button=lambda: Qt.LeftButton,
                     globalPos=lambda: QPoint(10, 10))


class TestReactions(PetHarness):
    def test_a_pat_is_answered_with_the_petted_pose_and_hearts(self):
        self.pet._enter_sit()
        self.pet.mousePressEvent(_click())
        self.pet.mouseReleaseEvent(_click())
        self.assertEqual(self.pet.state, "PETTED")
        self.assertGreater(self.pet.heart_timer, 0)

    def test_repeated_pats_make_it_hop(self):
        self.pet._enter_sit()
        with patch.object(self.pet.interaction, "record_pet",
                          return_value="pet_spam"):
            with patch.object(P.random, "random", return_value=0.9):
                self.pet.mousePressEvent(_click())
                self.pet.mouseReleaseEvent(_click())
        self.assertEqual(self.pet.state, "HAPPY")

    def test_an_over_petted_cat_walks_off(self):
        self.pet.load_skin("cat")
        self.pet._enter_sit()
        with patch.object(self.pet.interaction, "record_pet",
                          return_value="pet_spam"):
            with patch.object(P.random, "random", return_value=0.0):
                self.pet.mousePressEvent(_click())
                self.pet.mouseReleaseEvent(_click())
        self.assertEqual(self.pet.state, "WALK")

    def test_poking_a_sleeping_pet_makes_it_sulk(self):
        self.pet._enter_state("SLEEP")
        self.pet.state_timer = 200
        self.pet.mousePressEvent(_click())
        self.pet.mouseReleaseEvent(_click())
        self.assertEqual(self.pet.state, "SULK")

    def test_one_shots_settle_back_down(self):
        self.pet._enter_sit()
        self.pet._start_one_shot("ALERT")
        for _ in range(P.ONE_SHOT_TICKS["ALERT"] + 2):
            self.pet._update_fsm(QPoint(5, 5))
        self.assertIn(self.pet.state, ("SIT", "IDLE"))

    def test_a_treat_is_eaten_then_celebrated(self):
        self.pet._enter_sit()
        self.pet._menu_treat()
        self.assertEqual(self.pet.state, "EAT")
        for _ in range(P.ONE_SHOT_TICKS["EAT"] + 1):
            self.pet._update_fsm(QPoint(5, 5))
        self.assertEqual(self.pet.state, "HAPPY")

    def test_no_reaction_mid_air(self):
        self.pet._enter_fall()
        self.assertFalse(self.pet._start_one_shot("DANCE"))
        self.assertEqual(self.pet.state, "FALL")

    def test_shaking_while_dragging_makes_it_dizzy(self):
        self.pet.show()
        self.pet.mousePressEvent(MagicMock(button=lambda: Qt.LeftButton,
                                           globalPos=lambda: QPoint(500, 500)))
        for i in range(14):
            x = 500 + (60 if i % 2 else -60)
            self.pet.mouseMoveEvent(MagicMock(buttons=lambda: Qt.LeftButton,
                                              globalPos=lambda x=x: QPoint(x, 500)))
        self.assertTrue(self.pet._shaken)
        self.pet._fling_velocity = lambda: (None, None)
        self.pet.mouseReleaseEvent(MagicMock(button=lambda: Qt.LeftButton,
                                             globalPos=lambda: QPoint(500, 500)))
        for _ in range(400):
            if self.pet.state != "FALL":
                break
            self.pet._tick_fall()
        self.assertEqual(self.pet.state, "DIZZY")

    def test_a_trick_turns_the_pet_around(self):
        self.pet._enter_sit()
        self.pet.facing = 1
        self.pet.mouseDoubleClickEvent(_click())
        self.assertEqual(self.pet.state, "HAPPY")
        self.assertEqual(self.pet.facing, -1)
        # the double-click's trailing release is not also a pat
        self.pet.mouseReleaseEvent(_click())
        self.assertEqual(self.pet.state, "HAPPY")

    def test_laser_pointer_turns_calm_into_chase_and_ends(self):
        self.pet._enter_sit()
        self.pet._menu_laser()
        self.pet._update_fsm(QPoint(int(self.pet.x_pos) + 300, int(self.pet.y_pos)))
        self.assertEqual(self.pet.state, "CHASE")
        self.pet.tick_count = self.pet._laser_until
        self.pet._ambient_flourish(QPoint(0, 0), 0)
        self.assertEqual(self.pet._laser_until, 0)

    def test_cursor_flick_nearby_catches_its_eye(self):
        self.pet._enter_sit()
        near = QPoint(int(self.pet.x_pos + self.pet.sprite_w),
                      int(self.pet.y_pos))
        self.pet._ambient_flourish(near, P.ALERT_SPEED_PX + 5)
        self.assertEqual(self.pet.state, "ALERT")
        # and not again straight away
        self.pet._enter_sit()
        self.pet._ambient_flourish(near, P.ALERT_SPEED_PX + 5)
        self.assertEqual(self.pet.state, "SIT")

    def test_ghost_spooks_when_the_cursor_creeps_up(self):
        self.pet.load_skin("ghost")
        self.pet._enter_sit()
        here = QPoint(int(self.pet.x_pos + self.pet.sprite_w / 2),
                      int(self.pet.y_pos + self.pet.sprite_h / 2))
        self.pet._ambient_flourish(here, 0)
        self.assertEqual(self.pet.state, "SPOOK")


class TestPersonality(PetHarness):
    """Each companion behaves like itself, and never like an NPC loop."""

    def pick_many(self, skin, n=300, energy=90.0):
        self.pet.load_skin(skin)
        self.apply_screen()
        seen = {}
        last = None
        for _ in range(n):
            self.pet.energy = energy
            self.pet.current_ledge = None
            self.pet.x_pos = 600.0
            self.pet.y_pos = self.pet.floor_y
            self.pet._enter_sit()
            self.pet._pick_idle_transition(200, 250)
            action = self.pet.chooser.recent[-1] if self.pet.chooser.recent else None
            if action is not None and action == last:
                self.fail("%s repeated %s back to back" % (skin, action))
            last = action
            seen[self.pet.state] = seen.get(self.pet.state, 0) + 1
        return seen

    def test_companions_have_different_repertoires(self):
        cat = self.pick_many("cat")
        shiba = self.pick_many("shiba")
        ghost = self.pick_many("ghost")
        self.assertIn("GROOM", cat)
        self.assertNotIn("FOLLOW", cat)
        self.assertIn("FOLLOW", shiba)
        self.assertIn("SNIFF", shiba)
        self.assertNotIn("CLIMB", shiba)
        self.assertIn("FLY", ghost)
        self.assertNotIn("WALK", ghost)

    def test_shiba_never_leaves_the_floor_on_its_own(self):
        seen = self.pick_many("shiba")
        for state in ("CLIMB", "LEAP"):
            self.assertNotIn(state, seen)

    def test_exploring_has_a_cooldown(self):
        self.pet.load_skin("cat")
        self.pet._last_explore_tick = self.pet.tick_count
        self.assertFalse(self.pet._explore_ready())
        self.pet.tick_count += int(self.pet.profile["explore_cooldown"]
                                   * P.TICKS_PER_SECOND) + 1
        self.assertTrue(self.pet._explore_ready())

    def test_a_perched_pet_settles_in_instead_of_bouncing_off(self):
        self.assertEqual(self.land(200, 50), "PERCH")
        stayed = 0
        for _ in range(60):
            self.land(200, 50)
            self.pet._enter_state("PERCH")
            self.pet.state_timer = P.STATE_MIN_DURATION["PERCH"]
            self.pet._tick_perch(0, 500)
            if self.pet._is_on_ledge():
                stayed += 1
        self.assertGreater(stayed, 40, "it should mostly stay up there")

    def test_flyers_hover_where_they_are_dropped(self):
        self.pet.load_skin("jarvis")
        self.apply_screen()
        self.assertTrue(self.pet.flies)
        self.pet.mousePressEvent(_click())
        self.pet.dragging = True
        self.pet.y_pos = 150.0
        self.pet.mouseReleaseEvent(_click())
        self.assertNotEqual(self.pet.state, "FALL")

    def test_drift_flies_somewhere_and_settles(self):
        self.pet.load_skin("ghost")
        self.apply_screen()
        self.pet._start_fly(self.pet.x_pos + 200, self.pet.floor_y - 200)
        for _ in range(P.FLY_MAX_TICKS + 5):
            self.pet._update_fsm(QPoint(0, 0))
            if self.pet.state != "FLY":
                break
        self.assertIn(self.pet.state, ("IDLE", "SIT"))

    def test_phasing_hides_then_reappears(self):
        self.pet.load_skin("ghost")
        self.apply_screen()
        self.pet._enter_state("PHASE")
        seen_hidden = False
        for _ in range(P.PHASE_TICKS + 2):
            self.pet._update_fsm(QPoint(0, 0))
            seen_hidden = seen_hidden or self.pet.phased_out()
        self.assertTrue(seen_hidden)
        self.assertFalse(self.pet.phased_out())

    def test_zoomies_end_in_a_groom_for_the_cat(self):
        self.pet.load_skin("cat")
        self.apply_screen()
        self.pet._enter_sit()
        self.assertTrue(self.pet._run_action("zoomies", 0, 500))
        for _ in range(500):
            self.pet._update_fsm(QPoint(0, 0))
            if self.pet.state != "ZOOMIES":
                break
        self.assertEqual(self.pet._next_action, "groom")


class TestNoJitter(PetHarness):
    """Running in place while flipping left/right every tick, under a
    cursor it cannot reach, was a real bug."""

    def overhead(self, height):
        return QPoint(int(self.pet.x_pos + self.pet.sprite_w / 2 + 3),
                      int(self.pet.y_pos - height))

    def count_flips(self, state, cursor, ticks=120):
        self.pet._enter_state(state)
        flips, last = 0, self.pet.facing
        for _ in range(ticks):
            # the user's hand is never perfectly still
            wobble = QPoint(cursor.x() + (1 if _ % 2 else -1) * 4, cursor.y())
            self.pet._update_fsm(wobble)
            if self.pet.facing != last:
                flips += 1
                last = self.pet.facing
            if self.pet.state != state:
                break
        return flips

    def test_chase_does_not_flip_flop_under_an_unreachable_cursor(self):
        self.pet._enter_sit()
        flips = self.count_flips("CHASE", self.overhead(400))
        self.assertLessEqual(flips, 1)
        self.assertNotEqual(self.pet.state, "CHASE",
                            "it should give up and watch, not run on the spot")

    def test_chase_pounces_at_a_cursor_just_overhead(self):
        self.pet._enter_sit()
        self.count_flips("CHASE", self.overhead(60), ticks=5)
        self.assertIn(self.pet.state, ("POUNCE", "FALL", "SIT"))

    def test_laser_waits_under_the_dot_instead_of_running(self):
        self.pet._enter_sit()
        self.pet._menu_laser()
        cursor = self.overhead(400)
        flips, last = 0, self.pet.facing
        for i in range(120):
            self.pet._update_fsm(QPoint(cursor.x() + (4 if i % 2 else -4),
                                        cursor.y()))
            if self.pet.facing != last:
                flips += 1
                last = self.pet.facing
        self.assertLessEqual(flips, 1)
        self.assertNotEqual(self.pet.state, "CHASE")

    def test_stalk_does_not_flip_flop(self):
        self.pet._enter_sit()
        self.assertLessEqual(self.count_flips("STALK", self.overhead(400)), 1)

    def test_haunt_keeps_its_side(self):
        self.pet.load_skin("ghost")
        self.apply_screen()
        self.pet._enter_sit()
        self.assertLessEqual(self.count_flips("HAUNT", self.overhead(300)), 1)


class TestJuice(PetHarness):
    def test_speech_types_itself_in(self):
        self.pet.speak("hello there friend")
        self.assertEqual(self.pet.speech_reveal, 0)
        self.pet.game_loop()
        self.assertGreater(self.pet.speech_reveal, 0)
        for _ in range(40):
            self.pet.game_loop()
        self.assertGreaterEqual(self.pet.speech_reveal,
                                len("hello there friend"))

    def test_answers_to_the_user_are_voiced(self):
        with patch.object(self.pet.sounds, "say") as say:
            self.pet._mark_user_moment()
            self.pet.speak("hi")
        self.assertTrue(say.called)
        self.assertFalse(say.call_args[1].get("ambient", False))

    def test_volunteered_lines_are_voiced_rarely_if_at_all(self):
        self.pet._user_moment = -10 ** 6
        with patch.object(self.pet.sounds, "say") as say:
            with patch.object(P.random, "random", return_value=0.99):
                self.pet.speak("hi")
        self.assertFalse(say.called)
        with patch.object(self.pet.sounds, "say") as say:
            with patch.object(P.random, "random", return_value=0.0):
                self.pet.speak("hi again")
        self.assertTrue(say.call_args[1].get("ambient"))

    def test_hearts_become_particles(self):
        if self.pet.fx is None:
            self.skipTest("no fx overlay")
        self.pet.fx.clear()
        self.pet.heart_timer = 20
        self.pet._heart_seen = 0
        self.pet.game_loop()
        kinds = {p.kind for p in self.pet.fx.particles}
        self.assertTrue(kinds & {"heart", "heart_s"})

    def test_fx_overlay_hides_with_the_pet(self):
        if self.pet.fx is None:
            self.skipTest("no fx overlay")
        self.pet.show()
        self.pet.fx.burst("hearts")
        self.pet._tick_fx()
        self.pet.hide()
        self.assertFalse(self.pet.fx.isVisible())

    def test_sleep_starts_with_a_yawn(self):
        self.pet._enter_state("SLEEP")
        key, _frames, _index = self.pet._frame_choice()
        self.assertEqual(key, "yawn")
        self.pet.state_timer = P.YAWN_TICKS + 1
        key, _frames, _index = self.pet._frame_choice()
        self.assertEqual(key, "SLEEP")

    def test_airborne_frames_follow_velocity(self):
        self.pet._enter_state("JUMP")
        self.pet.vy = -5.0
        self.assertEqual(self.pet._frame_choice()[0], "jump")
        self.pet.vy = 5.0
        self.assertEqual(self.pet._frame_choice()[0], "fall")


class TestPixelPerfect(PetHarness):
    def test_frames_are_whole_multiples_of_the_art(self):
        for scale in (1, 2, 3, 5, 8):
            self.pet.scale_factor = scale
            self.pet.load_skin("cat")
            self.assertEqual((self.pet.sprite_w, self.pet.sprite_h),
                             (16 * scale, 16 * scale))

    def test_scaling_is_nearest_neighbour(self):
        self.pet.scale_factor = 4
        self.pet.load_skin("cat")
        image = self.pet.sprites["sit"][0].toImage()
        ratio = int(self.pet.sprites["sit"][0].devicePixelRatio())
        block = 4 * ratio
        for y in range(0, image.height(), block):
            for x in range(0, image.width(), block):
                corner = image.pixel(x, y)
                self.assertEqual(image.pixel(x + block - 1, y + block - 1),
                                 corner)

    def test_mirroring_keeps_the_pixel_ratio(self):
        pix = self.pet.sprites["sit"][0]
        pix.setDevicePixelRatio(2.0)
        self.assertEqual(self.pet._mirrored(pix).devicePixelRatio(), 2.0)

    def test_every_skin_ships_the_reaction_frames(self):
        for skin in P.discover_skins():
            self.pet.load_skin(skin)
            for family in ("happy", "pet", "eat", "dizzy", "dance", "yawn",
                           "alert", "jump", "fall"):
                self.assertIn(family, self.pet.sprites,
                              "%s has no %s frames" % (skin, family))


if __name__ == "__main__":
    unittest.main(verbosity=2)
