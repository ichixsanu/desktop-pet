"""Tests for pet_state.py and focus_timer.py."""

import json
import os
import tempfile
import time
import unittest

import focus_timer
import pet_state


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "pet_state.json")

    def read(self, path=None):
        with open(path or self.path) as handle:
            return json.load(handle)


class TestPersistence(TempDirCase):
    def test_defaults_when_missing(self):
        store = pet_state.PetState(self.path)
        data = store.load()
        self.assertEqual(data["skin"], None)
        self.assertEqual(data["energy"], 100.0)
        self.assertEqual(store.hours_away(), 0.0)

    def test_roundtrip(self):
        store = pet_state.PetState(self.path, save_interval=0)
        store.touch(skin="ghost", scale=3, energy=42.0, x=10.0, y=20.0,
                    climb_enabled=False)
        self.assertTrue(store.save(force=True))

        reloaded = pet_state.PetState(self.path).load()
        self.assertEqual(reloaded["skin"], "ghost")
        self.assertEqual(reloaded["scale"], 3)
        self.assertEqual(reloaded["energy"], 42.0)
        self.assertEqual(reloaded["climb_enabled"], False)
        self.assertGreater(reloaded["last_seen"], 0)

    def test_corrupt_file_degrades_to_defaults(self):
        with open(self.path, "w") as handle:
            handle.write("{not json at all")
        data = pet_state.PetState(self.path).load()
        self.assertEqual(data["energy"], 100.0)
        self.assertIsNone(data["skin"])

    def test_garbage_fields_are_coerced(self):
        with open(self.path, "w") as handle:
            json.dump({"skin": 7, "scale": "big", "energy": "lots",
                       "x": None, "seconds_alive": [], "pet_count": -4,
                       "climb_enabled": "no"}, handle)
        data = pet_state.PetState(self.path).load()
        self.assertIsNone(data["skin"])
        self.assertEqual(data["scale"], 2)
        self.assertEqual(data["energy"], 100.0)
        self.assertEqual(data["seconds_alive"], 0.0)
        self.assertEqual(data["pet_count"], 0)
        self.assertIs(data["climb_enabled"], False)

    def test_out_of_range_values_are_clamped(self):
        with open(self.path, "w") as handle:
            json.dump({"energy": 5000, "scale": 99, "pet_count": 10 ** 9}, handle)
        data = pet_state.PetState(self.path).load()
        self.assertEqual(data["energy"], 100.0)
        self.assertEqual(data["scale"], 8)
        self.assertEqual(data["pet_count"], 10 ** 9)

    def test_non_dict_payload(self):
        with open(self.path, "w") as handle:
            json.dump([1, 2, 3], handle)
        self.assertEqual(pet_state.PetState(self.path).load()["energy"], 100.0)

    def test_energy_decays_while_away(self):
        store = pet_state.PetState(self.path)
        store.touch(energy=100.0)
        store.save(force=True, now=1000.0)

        reloaded = pet_state.PetState(self.path)
        reloaded.load()
        # One hour gone: a quarter-hour of grace, then decay.
        expected = 100.0 - (1.0 - pet_state.GRACE_PERIOD_HOURS) \
            * pet_state.ENERGY_DECAY_PER_HOUR
        self.assertAlmostEqual(reloaded.rested_energy(now=4600.0), expected,
                               places=5)
        # A long absence is capped, so the pet is not ruined forever: 48 hours
        # away costs the same as the 8-hour cap.
        capped = reloaded.rested_energy(now=1000.0 + 3600 * 48)
        self.assertEqual(capped, reloaded.rested_energy(now=1000.0 + 3600 * 9))
        self.assertGreater(capped, 0.0)

    def test_quick_restart_is_free(self):
        store = pet_state.PetState(self.path)
        store.touch(energy=10.0)
        store.save(force=True, now=1000.0)
        reloaded = pet_state.PetState(self.path)
        reloaded.load()
        self.assertEqual(reloaded.rested_energy(now=1010.0), 10.0)

    def test_saves_are_rate_limited(self):
        store = pet_state.PetState(self.path, save_interval=30)
        self.assertTrue(store.save(force=True, now=100.0))
        self.assertFalse(store.save(force=False, now=110.0))
        self.assertTrue(store.save(force=False, now=131.0))
        self.assertTrue(store.save(force=False, now=131.0) is False)

    def test_no_temp_file_left_behind(self):
        store = pet_state.PetState(self.path)
        store.touch(energy=1.0)
        store.save(force=True)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_forget_removes_the_file(self):
        store = pet_state.PetState(self.path)
        store.touch(energy=1.0)
        store.save(force=True)
        self.assertTrue(os.path.exists(self.path))
        store.forget()
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(store.data["energy"], 100.0)

    def test_survives_an_unwritable_directory(self):
        store = pet_state.PetState("/proc/definitely/not/writable.json")
        store.touch(energy=1.0)
        store.save(force=True)  # must not raise


class TestFocusStateFile(TempDirCase):
    def test_reads_a_focus_file(self):
        path = os.path.join(self.tmp.name, "focus.json")
        focus_timer.write_state(path, "focus", remaining_minutes=24,
                                label="writing docs")
        state = pet_state.find_focus_state([path])
        self.assertEqual(state["mode"], "focus")
        self.assertEqual(state["remaining_minutes"], 24)
        self.assertEqual(state["label"], "writing docs")

    def test_ignores_missing_and_malformed_files(self):
        good = os.path.join(self.tmp.name, "good.json")
        focus_timer.write_state(good, "break")
        bad = os.path.join(self.tmp.name, "bad.json")
        with open(bad, "w") as handle:
            handle.write("{{{")
        self.assertEqual(pet_state.find_focus_state([bad, good])["mode"], "break")
        self.assertIsNone(pet_state.find_focus_state([bad]))
        self.assertIsNone(pet_state.find_focus_state([]))
        self.assertIsNone(pet_state.find_focus_state(None))

    def test_ignores_an_unknown_mode(self):
        path = os.path.join(self.tmp.name, "weird.json")
        focus_timer.write_state(path, "coffee")
        self.assertIsNone(pet_state.find_focus_state([path]))

    def test_label_is_truncated(self):
        path = os.path.join(self.tmp.name, "long.json")
        focus_timer.write_state(path, "focus", label="x" * 500)
        self.assertLessEqual(len(pet_state.find_focus_state([path])["label"]), 60)


class TestFocusWatcher(TempDirCase):
    def setUp(self):
        super().setUp()
        self.path = os.path.join(self.tmp.name, "focus.json")
        self.watcher = focus_timer.FocusWatcher([self.path], poll_seconds=5)

    def test_reports_focus_and_break(self):
        focus_timer.write_state(self.path, "focus")
        self.assertEqual(self.watcher.poll(force=True), focus_timer.MODE_FOCUS)
        self.assertTrue(self.watcher.is_focus())
        focus_timer.write_state(self.path, "break")
        self.assertEqual(self.watcher.poll(force=True), focus_timer.MODE_BREAK)
        self.assertFalse(self.watcher.is_focus())

    def test_transitions(self):
        self.assertIsNone(self.watcher.transition(focus_timer.MODE_NONE))
        focus_timer.write_state(self.path, "focus")
        self.watcher.poll(force=True)
        self.assertEqual(self.watcher.transition(focus_timer.MODE_NONE), "started")
        self.assertIsNone(self.watcher.transition(focus_timer.MODE_FOCUS))
        focus_timer.write_state(self.path, "break")
        self.watcher.poll(force=True)
        self.assertEqual(self.watcher.transition(focus_timer.MODE_FOCUS), "ended")
        self.assertIsNone(self.watcher.transition(focus_timer.MODE_BREAK))

    def test_file_going_away_ends_the_session(self):
        focus_timer.write_state(self.path, "focus")
        self.watcher.poll(force=True)
        os.unlink(self.path)
        self.assertEqual(self.watcher.poll(force=True), focus_timer.MODE_NONE)
        self.assertEqual(self.watcher.transition(focus_timer.MODE_FOCUS), "ended")

    def test_polling_is_throttled(self):
        writes = []
        real = focus_timer.find_focus_state

        def counting(paths):
            writes.append(paths)
            return real(paths)

        focus_timer.find_focus_state = counting
        self.addCleanup(lambda: setattr(focus_timer, "find_focus_state", real))

        self.watcher.poll(now=0.0, force=True)
        self.watcher.poll(now=1.0)
        self.watcher.poll(now=2.0)
        self.assertEqual(len(writes), 1)
        self.watcher.poll(now=100.0)
        self.assertEqual(len(writes), 2)

    def test_unconfigured_watcher(self):
        # An explicit empty list means "off"; None would mean "use defaults".
        watcher = focus_timer.FocusWatcher([], poll_seconds=5)
        self.assertFalse(watcher.configured())
        self.assertIsNone(watcher.poll(force=True))
        self.assertEqual(watcher.describe(), "off")

    def test_defaults_are_used_when_paths_are_omitted(self):
        watcher = focus_timer.FocusWatcher()
        self.assertTrue(watcher.configured())
        self.assertTrue(watcher.paths)

    def test_describe(self):
        focus_timer.write_state(self.path, "focus", label="docs")
        self.watcher.poll(force=True)
        self.assertEqual(self.watcher.describe(), "focus: docs")


if __name__ == "__main__":
    unittest.main(verbosity=2)
