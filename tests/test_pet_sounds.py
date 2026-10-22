"""Tests for pet_sounds.py.

Three things are sacred here:

1. Playback must never be able to break the pet. Every failure path -- missing
   player, unreadable temp dir, disabled config -- ends in silence or a
   no-op, never an exception out of `play()` or `say()`.
2. Nothing blocks. Synthesis and the player both run off the GUI thread.
3. The pet is not a sound board. Sounds it makes on its own share one long
   cooldown; only things the user does are answered every time.

The bytes themselves are checked structurally (RIFF/WAVE header, mono signed
16-bit, plausible length) rather than by ear.
"""

import os
import struct
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pet_sounds  # noqa: E402


def frame_count(data):
    """PCM payload length in samples, read from the data chunk header."""
    data_size = struct.unpack("<I", data[40:44])[0]
    return data_size // 2


def samples(data):
    return struct.unpack("<%dh" % frame_count(data), data[44:])


class TestCueBytes(unittest.TestCase):
    def test_every_cue_is_a_valid_mono_wav(self):
        for cue in pet_sounds.CUES:
            data = pet_sounds._wav_bytes(cue, 0.4)
            self.assertEqual(data[:4], b"RIFF", cue)
            self.assertEqual(data[8:12], b"WAVE", cue)
            fmt, channels, rate = struct.unpack("<HHI", data[20:28])
            self.assertEqual(fmt, 1, cue)          # PCM
            self.assertEqual(channels, 1, cue)     # mono
            self.assertEqual(rate, pet_sounds.RATE, cue)
            want = int(round(pet_sounds.cue_seconds(cue) * pet_sounds.RATE))
            self.assertAlmostEqual(frame_count(data), want, delta=4, msg=cue)

    def test_cues_are_short(self):
        # a desktop pet chirps; it does not play songs at you
        for cue in pet_sounds.CUES:
            self.assertLessEqual(pet_sounds.cue_seconds(cue), 1.5, cue)

    def test_volume_bakes_into_amplitude(self):
        loud = max(abs(p) for p in samples(pet_sounds._wav_bytes("pop", 1.0)))
        quiet = max(abs(p) for p in samples(pet_sounds._wav_bytes("pop", 0.1)))
        self.assertGreater(loud, quiet * 2)
        self.assertLessEqual(loud, 32000)

    def test_cues_are_normalised_to_one_level(self):
        peaks = [max(abs(p) for p in samples(pet_sounds._wav_bytes(c, 0.5)))
                 for c in ("pop", "land", "dance", "purr")]
        self.assertLess(max(peaks) - min(peaks), 800)

    def test_no_dc_offset(self):
        # asymmetric pulses sit off-centre; that clicks on start and stop
        for cue in ("pop", "land", "meow", "beep"):
            pcm = samples(pet_sounds._wav_bytes(cue, 0.5))
            self.assertLess(abs(sum(pcm) / len(pcm)), 400, cue)

    def test_starts_and_ends_silent(self):
        for cue in pet_sounds.CUES:
            pcm = samples(pet_sounds._wav_bytes(cue, 1.0))
            self.assertLess(abs(pcm[0]), 50, cue)
            self.assertLess(abs(pcm[-1]), 50, cue)

    def test_unknown_cue_falls_back_to_pop(self):
        self.assertEqual(pet_sounds._wav_bytes("nope", 0.3),
                         pet_sounds._wav_bytes("pop", 0.3))

    def test_every_companion_has_a_voice_and_a_call(self):
        for skin in ("cat", "shiba", "ghost", "jarvis", "ultron"):
            self.assertIn(skin, pet_sounds.VOICES)
            self.assertIn(pet_sounds.VOICE_CUES[skin], pet_sounds.CUES)


class TestBabble(unittest.TestCase):
    def test_deterministic_per_line(self):
        a = pet_sounds.babble_notes("hello there", "cat")
        b = pet_sounds.babble_notes("hello there", "cat")
        self.assertEqual(a, b)

    def test_companions_sound_different(self):
        cat = pet_sounds.babble_notes("hello there", "cat")
        bot = pet_sounds.babble_notes("hello there", "ultron")
        self.assertNotEqual(cat[0]["f0"], bot[0]["f0"])

    def test_long_lines_are_capped(self):
        notes = pet_sounds.babble_notes("word " * 80, "shiba")
        self.assertLessEqual(len(notes), pet_sounds.MAX_BABBLE_SYLLABLES)
        end = max(n["at"] + n["dur"] for n in notes)
        self.assertLess(end, 2.0)

    def test_questions_rise(self):
        notes = pet_sounds.babble_notes("are you there?", "cat")
        self.assertGreater(notes[-1]["f1"], notes[-1]["f0"])

    def test_empty_line_is_silent_not_broken(self):
        self.assertEqual(pet_sounds.babble_notes("", "cat"), [])
        data = pet_sounds.babble_bytes("...", "ghost", 0.3)
        self.assertEqual(data[:4], b"RIFF")


class TestConfigGates(unittest.TestCase):
    def test_disabled_by_default_without_config(self):
        sounds = pet_sounds.PetSounds()
        self.assertFalse(sounds.enabled)

    def test_enabled_reads_config(self):
        sounds = pet_sounds.PetSounds({"enabled": True, "volume": 0.9})
        self.assertTrue(sounds.enabled)
        self.assertAlmostEqual(sounds.volume, 0.9)
        sounds.update({"enabled": False, "volume": 12})
        self.assertFalse(sounds.enabled)
        self.assertEqual(sounds.volume, 1.0)   # clamped, not crashed

    def test_bad_values_are_not_type_errors(self):
        sounds = pet_sounds.PetSounds({"enabled": True, "volume": "loud",
                                       "ambient_gap_seconds": "soon"})
        self.assertEqual(sounds.volume, 0.35)
        self.assertEqual(sounds.ambient_gap, pet_sounds.AMBIENT_GAP)


class TestRarity(unittest.TestCase):
    def setUp(self):
        self.sounds = pet_sounds.PetSounds({"enabled": True})
        self.dispatched = []
        patcher = patch.object(pet_sounds.PetSounds, "_dispatch",
                               lambda s, build: self.dispatched.append(build))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ambient_sounds_share_one_long_cooldown(self):
        self.sounds.play("yawn", ambient=True)
        self.sounds.play("alert", ambient=True)
        self.sounds.play("climb", ambient=True)
        self.assertEqual(len(self.dispatched), 1)

    def test_user_sounds_always_answer(self):
        self.sounds.play("yawn", ambient=True)
        self.sounds.play("purr")
        self.sounds.play("chime")
        self.assertEqual(len(self.dispatched), 3)

    def test_ambient_can_be_switched_off(self):
        self.sounds.update({"enabled": True, "ambient": False})
        self.sounds.play("yawn", ambient=True)
        self.sounds.play("purr")
        self.assertEqual(len(self.dispatched), 1)

    def test_the_same_cue_cannot_machine_gun(self):
        for _ in range(10):
            self.sounds.play("land")
        self.assertEqual(len(self.dispatched), 1)

    def test_voice_toggle_mutes_babble_only(self):
        self.sounds.update({"enabled": True, "voice": False})
        self.sounds.say("hello", "cat")
        self.sounds.play("pop")
        self.assertEqual(len(self.dispatched), 1)


class TestPlay(unittest.TestCase):
    def test_muted_play_is_a_no_op(self):
        sounds = pet_sounds.PetSounds({"enabled": False})
        with patch.object(pet_sounds.PetSounds, "_dispatch",
                          side_effect=AssertionError("must not dispatch")):
            sounds.play("chime")
            sounds.say("hello", "cat")

    def test_synthesis_happens_off_the_gui_thread(self):
        sounds = pet_sounds.PetSounds({"enabled": True})
        sounds._player = "paplay"
        started = []

        class FakeThread:
            def __init__(self, target, args, daemon):
                started.append((target, args))

            def start(self):
                pass

        with patch.object(pet_sounds, "Thread", FakeThread):
            with patch.object(pet_sounds, "_wav_bytes",
                              side_effect=AssertionError("synth on GUI thread")):
                sounds.play("whoosh")
        self.assertEqual(len(started), 1)

    def test_worker_runs_the_chosen_player(self):
        sounds = pet_sounds.PetSounds({"enabled": True})
        sounds._player = "paplay"
        with patch.object(pet_sounds.subprocess, "run") as run:
            sounds._running = 1
            sounds._work(lambda: "/tmp/opencode/x.wav")
        command = run.call_args[0][0]
        self.assertEqual(command[0], "paplay")
        self.assertEqual(sounds._running, 0)

    def test_qt_player_takes_priority_when_available(self):
        sounds = pet_sounds.PetSounds({"enabled": True})
        sounds._player = "qt"
        with patch.object(pet_sounds.PetSounds, "_play_qt",
                          return_value=True) as qt:
            with patch.object(pet_sounds, "Thread",
                              side_effect=AssertionError("no thread for qt")):
                sounds._dispatch(lambda: "/tmp/opencode/x.wav")
        self.assertTrue(qt.called)

    def test_player_probe_survives_no_players(self):
        with patch("pet_sounds._PLAYERS", ("definitely-not-here",)):
            with patch("pet_sounds.WINSOUND_OK", False):
                sounds = pet_sounds.PetSounds({"enabled": True})
            self.assertEqual(sounds._player,
                             "qt" if pet_sounds.QT_SOUND_OK else None)

    def test_worker_never_raises(self):
        sounds = pet_sounds.PetSounds({"enabled": True})
        sounds._player = "paplay"

        def broken():
            raise OSError("disk is a lie")

        sounds._running = 1
        sounds._work(broken)          # the pet must not die from its own beep
        self.assertEqual(sounds._running, 0)

    def test_concurrency_is_capped(self):
        sounds = pet_sounds.PetSounds({"enabled": True})
        sounds._player = "paplay"
        sounds._running = pet_sounds.MAX_CONCURRENT
        with patch.object(pet_sounds, "Thread",
                          side_effect=AssertionError("over the cap")):
            sounds._dispatch(lambda: "/tmp/opencode/x.wav")


if __name__ == "__main__":
    unittest.main()
