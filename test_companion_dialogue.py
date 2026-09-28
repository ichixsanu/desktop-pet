"""Tests for companion_dialogue.py.

Focuses on the window classifier (substring matching used to be wildly
over-eager) and on the guarantee that every companion can answer every event.
"""

import unittest
from datetime import datetime

import companion_dialogue as cd


class TestCategorizeWindow(unittest.TestCase):
    def assert_category(self, expected, title, process=""):
        self.assertEqual(cd.categorize_window(title, process), expected,
                         "%r / %r" % (title, process))

    def test_process_names_win_over_title_words(self):
        # A browser tab showing a source file is still a browser.
        self.assert_category("browser", "main.py - Some Editor", "firefox")
        self.assert_category("coding", "cat.png - Image Viewer", "code")

    def test_dotted_domains_are_not_code(self):
        # ".c" used to match every .com/.config/.cache, so almost any window
        # with a URL or a dotted filename was reported as coding.
        self.assert_category("browser", "example.com", "chrome")
        self.assert_category("browser", "news.example.co.uk - Firefox", "firefox")
        self.assert_category("general", "config.json and notes", "")
        self.assert_category("general", "my.config file", "")

    def test_file_extensions_still_match(self):
        self.assert_category("coding", "pet.py", "")
        self.assert_category("coding", "pet.py - ~/Documents", "")
        self.assert_category("coding", "index.html: rendered", "")
        self.assert_category("general", "x.python", "")

    def test_process_matching_is_segment_aware(self):
        self.assert_category("coding", "untitled", "code")
        self.assert_category("coding", "untitled", "code-insiders")
        self.assert_category("coding", "main.py", "code.exe")
        # "code" must not match these.
        self.assert_category("general", "chroma lab", "chroma")
        self.assert_category("general", "layout", "keyboard-layout-x11")
        self.assert_category("terminal", "sh", "sh")
        self.assert_category("general", "shell", "bashful")

    def test_terminal_takes_priority(self):
        self.assert_category("terminal", "vim main.py", "gnome-terminal-server")
        self.assert_category("terminal", "tony@server: ~/dev", "")
        self.assert_category("terminal", "user@host: /var/log", "")
        self.assert_category("terminal", "anything", "alacritty")

    def test_known_apps(self):
        self.assert_category("chat", "Discord", "discord")
        self.assert_category("media_gaming", "YouTube", "firefox")
        self.assert_category("media_gaming", "Steam", "steam.exe")
        self.assert_category("chat", "Slack", "slack.exe")

    def test_empty_input(self):
        self.assert_category("general", "", "")
        self.assert_category("general", None, None)

    def test_titles_do_not_carry_user_specific_hosts(self):
        # The old table hardcoded one developer's hostname.
        self.assertNotIn("tony@", str(cd.WINDOW_CATEGORIES["terminal"]["titles"]))


class TestTimeOfDay(unittest.TestCase):
    def test_buckets(self):
        cases = {
            0: "late_night", 1: "late_night", 4: "late_night",
            5: "early_morning", 8: "early_morning",
            10: "daytime", 13: "afternoon_slump", 16: "afternoon_slump",
            17: "daytime", 23: "daytime",
        }
        for hour, expected in cases.items():
            self.assertEqual(cd.get_time_of_day_key(datetime(2024, 1, 1, hour)),
                             expected, "hour %d" % hour)


class TestQuoteSelection(unittest.TestCase):
    SKINS = sorted(cd.COMPANION_DIALOGUE)

    def test_every_skin_answers_every_event(self):
        # A missing key silently degraded to "general" and an empty list would
        # raise IndexError inside random.choice, mid-game-loop.
        events = ["window", "time", "idle", "greeting"] + list(cd.EVENT_TYPES)
        for skin in self.SKINS:
            for event in events:
                line = cd.get_contextual_quote(skin, event_type=event,
                                               window_title="main.py",
                                               window_proc="code")
                self.assertIsInstance(line, str)
                self.assertTrue(line.strip(), "%s/%s produced nothing" % (skin, event))

    def test_every_skin_has_the_same_keys(self):
        reference = set(cd.COMPANION_DIALOGUE["cat"])
        for skin in self.SKINS:
            self.assertEqual(set(cd.COMPANION_DIALOGUE[skin]), reference,
                             "%s has a different set of lines" % skin)

    def test_no_empty_line_lists(self):
        for skin, lines in cd.COMPANION_DIALOGUE.items():
            for key, entries in lines.items():
                self.assertTrue(entries, "%s/%s is empty" % (skin, key))
                for entry in entries:
                    self.assertTrue(entry.strip(), "%s/%s has a blank line" % (skin, key))

    def test_unknown_skin_falls_back_to_the_cat(self):
        line = cd.get_contextual_quote("nosuchskin", "pet_first")
        self.assertIn(line, cd.COMPANION_DIALOGUE["cat"]["pet_first"])

    def test_unknown_event_falls_back(self):
        self.assertTrue(cd.get_contextual_quote("cat", event_type="not_an_event"))

    def test_window_event_uses_the_category(self):
        coding = {cd.get_contextual_quote("cat", "window", "pet.py", "")}
        self.assertTrue(coding.issubset(set(cd.COMPANION_DIALOGUE["cat"]["coding"])))

    def test_idle_blends_window_and_general(self):
        picks = {cd.get_contextual_quote("cat", "idle", "pet.py", "") for _ in range(60)}
        allowed = set(cd.COMPANION_DIALOGUE["cat"]["coding"]) \
            | set(cd.COMPANION_DIALOGUE["cat"]["general"])
        self.assertTrue(picks.issubset(allowed))

    def test_system_state_events_exist_for_every_skin(self):
        for skin in self.SKINS:
            self.assertTrue(cd.COMPANION_DIALOGUE[skin]["low_memory"])
            self.assertTrue(cd.COMPANION_DIALOGUE[skin]["low_battery"])


class TestInteractionTracker(unittest.TestCase):
    def test_pet_spam_detection(self):
        tracker = cd.InteractionTracker(pet_spam_threshold=3, spam_window_seconds=10)
        self.assertEqual(tracker.record_pet(), "pet_first")
        self.assertEqual(tracker.record_pet(), "pet_first")
        self.assertEqual(tracker.record_pet(), "pet_spam")
        self.assertEqual(tracker.record_pet(), "pet_spam")

    def test_pet_counter_expires(self):
        tracker = cd.InteractionTracker(pet_spam_threshold=2, spam_window_seconds=0.05)
        self.assertEqual(tracker.record_pet(), "pet_first")
        import time
        time.sleep(0.08)
        self.assertEqual(tracker.record_pet(), "pet_first")

    def test_drop_above_the_floor(self):
        tracker = cd.InteractionTracker()
        tracker.record_drag_start(700.0)
        self.assertEqual(tracker.record_drag_release(300.0, 1080.0), "drop")

    def test_released_after_being_lifted_high(self):
        tracker = cd.InteractionTracker()
        tracker.record_drag_start(1000.0)
        # Lifted 400px, released near the floor.
        self.assertEqual(tracker.record_drag_release(600.0, 1080.0), "drop")

    def test_sliding_downwards_is_not_a_fall(self):
        # The old sign convention made dragging the pet *down* read as a fall,
        # so almost any release above the bottom of the screen counted.
        tracker = cd.InteractionTracker()
        tracker.record_drag_start(100.0)
        self.assertIsNone(tracker.record_drag_release(1000.0, 1080.0))

    def test_short_release_is_not_a_drop(self):
        tracker = cd.InteractionTracker()
        tracker.record_drag_start(1050.0)
        self.assertIsNone(tracker.record_drag_release(1040.0, 1080.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
