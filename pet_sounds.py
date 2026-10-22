"""pet_sounds.py - a tiny chiptune synth for the pet.

Every cue is synthesised at runtime from NES-style voices -- pulse waves with
selectable duty, a triangle, and LFSR noise -- shaped with ADSR envelopes,
pitch slides, arpeggios and vibrato, then mixed and written as a WAV. No audio
files ship with the project: a cue is a few lines of note data below.

On top of the sound effects, each companion has a *voice*: when the pet talks,
`babble()` turns the line into a string of pitched syllable blips (think
Animal Crossing), with a timbre and pitch range per companion and an
intonation that rises on questions and jumps on exclamations.

Playback, in order of preference:
1. QtMultimedia QSoundEffect, when PyQt5 was built with it.
2. `pw-play` (PipeWire), `paplay` (PulseAudio), `aplay` (ALSA) or `afplay`
   (macOS), on a daemon thread.
3. `winsound` on Windows.

Everything is fire-and-forget: playback never blocks the GUI thread and never
raises. Missing players and a muted config just mean silence.
"""

import atexit
import hashlib
import math
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import time

# imported by name, not shared: sound playback must not ride the same patched
# threading.Thread that capture-worker tests use as an instrument
from threading import Thread, Lock

RATE = 22050

try:
    from PyQt5.QtMultimedia import QSoundEffect
    from PyQt5.QtCore import QUrl

    QT_SOUND_OK = True
except ImportError:
    QT_SOUND_OK = False

try:
    import winsound  # noqa: F401  (Windows only)

    WINSOUND_OK = True
except ImportError:
    WINSOUND_OK = False


# =====================================================================
# notes
# =====================================================================

def hz(name):
    """'A4' -> 440.0. Sharps as 'C#5'."""
    names = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    base = names[name[0].upper()]
    rest = name[1:]
    if rest.startswith("#"):
        base += 1
        rest = rest[1:]
    elif rest.startswith("b"):
        base -= 1
        rest = rest[1:]
    octave = int(rest)
    return 440.0 * 2.0 ** ((base + (octave - 4) * 12) / 12.0)


def N(wave, freq, dur, at=0.0, vol=0.5, to=None, duty=0.5, vib=(0.0, 0.0),
      arp=None, arp_rate=0.035, attack=0.004, decay=0.0, sustain=1.0,
      release=0.02, curve=1.0, short=False):
    """One voice event.

    wave: 'pulse' | 'tri' | 'noise' | 'saw'
    freq/to: start/end pitch in Hz (or note name); `to` makes a slide.
    vib: (depth in semitones, rate in Hz).
    arp: semitone offsets cycled every `arp_rate` seconds.
    curve: slide shape, >1 eases in, <1 eases out.
    short: noise only -- 93-step LFSR, the metallic NES noise.
    """
    if isinstance(freq, str):
        freq = hz(freq)
    if isinstance(to, str):
        to = hz(to)
    return {
        "wave": wave, "f0": float(freq), "f1": float(to if to else freq),
        "dur": float(dur), "at": float(at), "vol": float(vol), "duty": duty,
        "vib": vib, "arp": arp, "arp_rate": arp_rate, "attack": attack,
        "decay": decay, "sustain": sustain, "release": release,
        "curve": curve, "short": short,
    }


def _seq(wave, notes, step, at=0.0, **kw):
    """Consecutive notes of equal length: _seq('pulse', 'C5 E5 G5', 0.06)."""
    out = []
    t = at
    for name in notes.split():
        if name != "-":
            out.append(N(wave, name, step * 0.95, at=t, **kw))
        t += step
    return out


CUES = {
    # tapped / petted: a round little bloop
    "pop": [N("pulse", "E5", 0.07, to="B5", duty=0.25, vol=0.45,
              release=0.04, curve=0.5),
            N("tri", "E4", 0.06, vol=0.4)],
    # a treat: bright two-step chime with a sparkle on top
    "chime": [N("pulse", "E6", 0.09, duty=0.125, vol=0.35, release=0.06),
              N("pulse", "B6", 0.20, at=0.08, duty=0.125, vol=0.35,
                decay=0.15, sustain=0.3, release=0.06),
              N("tri", "E5", 0.26, vol=0.35, release=0.1)],
    # refusal: a flat little "nuh-uh"
    "no": [N("pulse", "D4", 0.09, duty=0.5, vol=0.38),
           N("pulse", "A3", 0.16, at=0.10, duty=0.5, vol=0.38, to="G#3",
             release=0.05)],
    # thrown across the desktop
    "whoosh": [N("noise", 2400, 0.30, to=600, vol=0.45, attack=0.06,
                 release=0.12, curve=0.6),
               N("tri", "C5", 0.26, to="C3", vol=0.2, attack=0.05)],
    # purr: low pulse with a wobbling, rumbling amplitude
    "purr": [N("pulse", 55, 0.55, duty=0.125, vol=0.30, vib=(0.6, 26),
               attack=0.06, release=0.15),
             N("noise", 180, 0.55, vol=0.12, attack=0.08, release=0.15)],
    # hitting the ground
    "land": [N("noise", 900, 0.09, to=150, vol=0.55, release=0.05),
             N("tri", "A2", 0.10, to="D2", vol=0.5)],
    # boing: jump / hop
    "jump": [N("pulse", "C4", 0.16, to="C6", duty=0.25, vol=0.35,
               curve=0.5, release=0.04)],
    # pounce: a quick rising swipe with grit
    "pounce": [N("pulse", "G4", 0.08, to="G5", duty=0.125, vol=0.35),
               N("noise", 3000, 0.06, at=0.07, vol=0.3)],
    # swat: a short "whap"
    "swat": [N("noise", 4000, 0.05, to=1500, vol=0.45),
             N("pulse", "A4", 0.04, duty=0.5, vol=0.25)],
    # alert: two quick rising blips -- "!"
    "alert": [N("pulse", "A5", 0.05, duty=0.25, vol=0.35),
              N("pulse", "E6", 0.09, at=0.06, duty=0.25, vol=0.35)],
    # happy: a major arpeggio jingle
    "happy": (_seq("pulse", "C5 E5 G5 C6", 0.055, duty=0.25, vol=0.32)
              + [N("tri", "C4", 0.24, vol=0.3, release=0.08)]),
    # eating: three crunchy noise bites
    "eat": [N("noise", 1800, 0.05, at=t, vol=0.4, short=True, release=0.02)
            for t in (0.0, 0.13, 0.26)],
    # dizzy: a woozy, wobbling descent
    "dizzy": [N("tri", "A5", 0.6, to="A3", vol=0.4, vib=(1.2, 9),
                release=0.1),
              N("pulse", "E6", 0.5, to="E4", duty=0.125, vol=0.12,
                vib=(1.0, 7), at=0.05)],
    # yawn: a long, lazy slide down
    "yawn": [N("tri", "G4", 0.55, to="C4", vol=0.35, vib=(0.3, 5),
               attack=0.1, release=0.18, curve=1.6)],
    # dozing off
    "sleep": [N("tri", "E4", 0.18, vol=0.28, attack=0.04, release=0.08),
              N("tri", "B3", 0.30, at=0.2, vol=0.25, attack=0.04,
                release=0.15)],
    # waking up: a sunny rising arp
    "wake": [N("pulse", "C5", 0.22, duty=0.25, vol=0.3, arp=[0, 4, 7, 12],
               arp_rate=0.05, release=0.04)],
    # a short tune to dance to
    "dance": (_seq("pulse", "C5 - G4 C5 E5 - D5 C5 G5 - E5 - C6", 0.085,
                   duty=0.25, vol=0.28, release=0.02)
              + _seq("tri", "C3 C3 G2 G2 A2 A2 F2 G2", 0.17, vol=0.35)
              + [N("noise", 6000, 0.02, at=t, vol=0.18)
                 for t in (0.0, 0.34, 0.68, 1.02)]),
    # milestones / anniversaries
    "fanfare": (_seq("pulse", "G4 C5 E5 G5 - E5 G5", 0.08, duty=0.5,
                     vol=0.3)
                + [N("pulse", "C6", 0.35, at=0.56, duty=0.25, vol=0.3,
                     vib=(0.25, 6), release=0.12),
                   N("tri", "C4", 0.9, vol=0.3, release=0.2)]),
    # scrabbling up a window frame
    "climb": [N("noise", 2600, 0.025, at=t, vol=0.25, short=True)
              for t in (0.0, 0.07, 0.14, 0.21)],
    # dropped (not thrown)
    "drop": [N("pulse", "E5", 0.18, to="E4", duty=0.5, vol=0.25,
               curve=1.4)],
    # picked up
    "grab": [N("pulse", "C5", 0.06, to="G5", duty=0.25, vol=0.3)],
    # dragged, shaken too hard
    "shake": [N("pulse", 300, 0.25, duty=0.5, vol=0.25, vib=(3.0, 18))],

    # ---- companion "voices": a call each skin makes when it wants attention
    "meow": [N("pulse", "B4", 0.30, to="D5", duty=0.25, vol=0.35,
               vib=(0.4, 7), attack=0.03, release=0.1, curve=0.4),
             N("pulse", "F#5", 0.16, at=0.22, to="C#5", duty=0.25, vol=0.3,
               release=0.08)],
    "bark": [N("pulse", "F4", 0.07, to="C4", duty=0.5, vol=0.42),
             N("noise", 1200, 0.06, vol=0.3),
             N("pulse", "F4", 0.08, at=0.14, to="B3", duty=0.5, vol=0.42),
             N("noise", 1200, 0.06, at=0.14, vol=0.3)],
    "boo": [N("tri", "E4", 0.55, to="G4", vol=0.45, vib=(0.7, 5.5),
              attack=0.12, release=0.2, curve=0.6),
            N("pulse", "E5", 0.5, to="G5", duty=0.125, vol=0.08,
              vib=(0.7, 5.5), attack=0.15)],
    "beep": [N("pulse", "A5", 0.06, duty=0.125, vol=0.3),
             N("pulse", "E6", 0.06, at=0.08, duty=0.125, vol=0.3),
             N("pulse", "C#6", 0.09, at=0.16, duty=0.125, vol=0.3)],
    "menace": [N("saw", "E2", 0.5, to="C2", vol=0.35, attack=0.02,
                 release=0.15),
               N("saw", 84.0, 0.5, to=66.0, vol=0.3, attack=0.02),
               N("noise", 400, 0.5, vol=0.12, short=True, release=0.2)],
}

VOICE_CUES = {"cat": "meow", "shiba": "bark", "ghost": "boo",
              "jarvis": "beep", "ultron": "menace"}

# Speaking voices: wave, base pitch, spread (semitones), syllable length.
VOICES = {
    "cat":    {"wave": "pulse", "duty": 0.25, "base": "A5", "spread": 7,
               "syl": 0.055, "vib": (0.25, 9)},
    "shiba":  {"wave": "pulse", "duty": 0.5, "base": "E5", "spread": 9,
               "syl": 0.050, "vib": (0.0, 0)},
    "ghost":  {"wave": "tri", "duty": 0.5, "base": "C5", "spread": 5,
               "syl": 0.075, "vib": (0.6, 6)},
    "jarvis": {"wave": "pulse", "duty": 0.125, "base": "G5", "spread": 4,
               "syl": 0.050, "vib": (0.0, 0)},
    "ultron": {"wave": "pulse", "duty": 0.5, "base": "A3", "spread": 5,
               "syl": 0.070, "vib": (0.15, 4)},
}
PENTATONIC = (0, 2, 4, 7, 9, 12, 14)
MAX_BABBLE_SYLLABLES = 12


def babble_notes(text, skin="cat"):
    """Syllable blips for a line of dialogue.

    Deterministic per text, so the same line always "sounds" the same.
    """
    voice = VOICES.get(skin, VOICES["cat"])
    base = hz(voice["base"])
    seed = int(hashlib.md5((skin + "|" + (text or "")).encode("utf-8"))
               .hexdigest()[:8], 16)
    rng = random.Random(seed)
    words = [w for w in (text or "").split() if any(c.isalnum() for c in w)]
    notes = []
    t = 0.0
    count = 0
    question = (text or "").rstrip().endswith("?")
    exclaim = (text or "").rstrip().endswith("!")
    for wi, word in enumerate(words):
        letters = sum(1 for c in word if c.isalnum())
        syllables = max(1, min(3, (letters + 2) // 3))
        for si in range(syllables):
            if count >= MAX_BABBLE_SYLLABLES:
                break
            last = (wi == len(words) - 1 and si == syllables - 1) or \
                count == MAX_BABBLE_SYLLABLES - 1
            step = PENTATONIC[rng.randrange(len(PENTATONIC))]
            step = step * voice["spread"] / 12.0
            semis = step - voice["spread"] / 2.0
            if exclaim:
                semis += 2
            f0 = base * 2 ** (semis / 12.0)
            f1 = f0
            if last and question:
                f1 = f0 * 2 ** (5 / 12.0)
            elif last:
                f1 = f0 * 2 ** (-3 / 12.0)
            dur = voice["syl"] * (1.6 if last else rng.uniform(0.8, 1.15))
            notes.append(N(voice["wave"], f0, dur, at=t, to=f1,
                           duty=voice["duty"], vol=0.30, vib=voice["vib"],
                           attack=0.003, release=0.015))
            if skin == "ultron":
                notes.append(N("pulse", f0 / 2, dur, at=t, duty=0.5,
                               vol=0.12))
            t += dur + voice["syl"] * 0.35
            count += 1
        t += voice["syl"] * 0.6       # a breath between words
        if word[-1:] in ",.;:" and count < MAX_BABBLE_SYLLABLES:
            t += voice["syl"] * 1.2
    return notes


# =====================================================================
# synthesis
# =====================================================================

def _envelope_table(n, count):
    """Per-sample ADSR gain, built segment by segment (no per-sample calls)."""
    a = min(count, max(1, int(n["attack"] * RATE)))
    d = min(count - a, int(n["decay"] * RATE))
    r = min(count, max(1, int(n["release"] * RATE)))
    sustain = n["sustain"] if d else 1.0
    env = [i / float(a) for i in range(a)]
    env += [1.0 - (1.0 - sustain) * (i / float(d)) for i in range(d)]
    env += [sustain] * (count - len(env))
    for k in range(r):
        env[count - 1 - k] *= k / float(r)
    return env


# 2A03-style 4-bit stepped triangle, as a 32-step lookup
_TRI = [round((4.0 * abs((i + 0.5) / 32.0 - 0.5) - 1.0) * 7.5) / 7.5
        for i in range(32)]


def _frequencies(n, count):
    """Per-sample pitch, already divided by RATE (= phase increment)."""
    f0, f1 = n["f0"] / RATE, n["f1"] / RATE
    curve = n["curve"]
    inv = 1.0 / count
    if f0 == f1:
        incs = [f0] * count
    elif curve == 1.0:
        step = (f1 - f0) * inv
        incs = [f0 + step * i for i in range(count)]
    else:
        incs = [f0 + (f1 - f0) * ((i * inv) ** curve) for i in range(count)]
    depth, rate = n["vib"] or (0.0, 0.0)
    if depth:
        w = 2 * math.pi * rate / RATE
        k = depth / 12.0
        incs = [inc * 2 ** (k * math.sin(w * i)) for i, inc in enumerate(incs)]
    arp = n["arp"]
    if arp:
        step = max(1, int(n["arp_rate"] * RATE))
        mults = [2 ** (s / 12.0) for s in arp]
        incs = [inc * mults[(i // step) % len(mults)]
                for i, inc in enumerate(incs)]
    return incs


def _render_note(n, volume):
    count = max(1, int(round(n["dur"] * RATE)))
    amp = max(0.0, min(1.0, n["vol"])) * volume
    env = _envelope_table(n, count)
    incs = _frequencies(n, count)
    wave = n["wave"]
    out = [0.0] * count
    phase = 0.0
    if wave == "noise":
        # NES-style: the LFSR is clocked at the "pitch" rate
        lfsr = 1
        value = amp
        tap = 6 if n["short"] else 1
        for i in range(count):
            phase += incs[i]
            while phase >= 1.0:
                phase -= 1.0
                bit = (lfsr ^ (lfsr >> tap)) & 1
                lfsr = (lfsr >> 1) | (bit << 14)
                value = amp if lfsr & 1 else -amp
            out[i] = value * env[i]
    elif wave == "pulse":
        duty = n["duty"]
        for i in range(count):
            phase += incs[i]
            if phase >= 1.0:
                phase -= int(phase)
            out[i] = (amp if phase < duty else -amp) * env[i]
    elif wave == "tri":
        tri = [v * amp for v in _TRI]
        for i in range(count):
            phase += incs[i]
            if phase >= 1.0:
                phase -= int(phase)
            out[i] = tri[int(phase * 32) & 31] * env[i]
    else:  # saw
        for i in range(count):
            phase += incs[i]
            if phase >= 1.0:
                phase -= int(phase)
            out[i] = (2.0 * phase - 1.0) * amp * env[i]
    return out


TARGET_PEAK = 0.85


def render(notes, volume=1.0):
    """Mix note events into one float buffer, normalised to `volume`.

    Every cue lands at the same peak level, so 'volume' means the same thing
    for a tiny blip and a stacked fanfare.
    """
    volume = max(0.0, min(1.0, volume))
    if not notes:
        return [0.0] * int(RATE * 0.02)
    end = max(n["at"] + n["dur"] for n in notes)
    mix = [0.0] * max(1, int(round(end * RATE)))
    for n in notes:
        start = int(round(n["at"] * RATE))
        for i, v in enumerate(_render_note(n, 1.0)):
            j = start + i
            if j < len(mix):
                mix[j] += v
    # DC blocker (asymmetric pulses and noise sit off-centre, which clicks),
    # then a gentle one-pole lowpass that takes the fizz off raw pulse edges,
    # then a cheap soft clip so stacked voices saturate instead of wrapping
    prev_in = prev_hp = prev_lp = 0.0
    for i, v in enumerate(mix):
        prev_hp = v - prev_in + 0.995 * prev_hp
        prev_in = v
        prev_lp += 0.55 * (prev_hp - prev_lp)
        x = prev_lp * 1.1
        if x > 1.5:
            x = 1.0
        elif x < -1.5:
            x = -1.0
        else:
            x = x - (x * x * x) * 0.148
        mix[i] = x
    peak = max(abs(v) for v in mix) or 1.0
    gain = TARGET_PEAK * volume / peak
    # a 3ms fade at both ends: no click even if a voice starts at full level
    fade = min(len(mix) // 2, int(RATE * 0.003))
    for i in range(len(mix)):
        g = gain
        if i < fade:
            g *= i / float(fade)
        elif i >= len(mix) - fade:
            g *= (len(mix) - 1 - i) / float(fade)
        mix[i] *= g
    return mix


def _riff(samples):
    """Signed 16-bit mono PCM wrapped in a minimal WAV container."""
    data = struct.pack("<%dh" % len(samples),
                       *(int(max(-1.0, min(1.0, s)) * 32000) for s in samples))
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


def cue_seconds(cue):
    notes = CUES.get(cue) or CUES["pop"]
    return max(n["at"] + n["dur"] for n in notes)


def _wav_bytes(cue, volume=1.0):
    """Synthesise one named cue into a WAV file's bytes."""
    return _riff(render(CUES.get(cue) or CUES["pop"], volume))


# Talking sits a little under the sound effects: it happens more often.
BABBLE_LEVEL = 0.7


def babble_bytes(text, skin="cat", volume=1.0):
    return _riff(render(babble_notes(text, skin), volume * BABBLE_LEVEL))


# =====================================================================
# playback
# =====================================================================

_PLAYERS = ("pw-play", "paplay", "aplay", "afplay")


def _which(name):
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _player_available():
    if QT_SOUND_OK:
        return "qt"
    for player in _PLAYERS:
        if _which(player):
            return player
    if WINSOUND_OK:
        return "winsound"
    return None


_SOUND_DIR = None


def _sound_dir():
    global _SOUND_DIR
    if _SOUND_DIR and os.path.isdir(_SOUND_DIR):
        return _SOUND_DIR
    for candidate in ("/tmp/opencode", os.environ.get("TMPDIR")):
        if candidate and os.path.isdir(candidate):
            base = candidate
            break
    else:
        base = tempfile.gettempdir()
    path = os.path.join(base, "pet-sounds-%d" % os.getpid())
    os.makedirs(path, exist_ok=True)
    if _SOUND_DIR is None:
        atexit.register(shutil.rmtree, path, True)
    _SOUND_DIR = path
    return path


def _temp_wav_path(name="pet_cue"):
    return os.path.join(_sound_dir(), "%s.wav" % name)


# Per-cue minimum spacing, so a twitchy state machine cannot machine-gun a
# sound. Everything not listed gets DEFAULT_GAP.
MIN_GAP = {"land": 0.25, "climb": 0.5, "swat": 0.2, "eat": 0.4,
           "babble": 0.15}
DEFAULT_GAP = 0.12
MAX_CONCURRENT = 3
# Unprompted sounds (the pet doing its own thing) share one cooldown: at most
# one every couple of minutes. Things the user does always get their answer.
AMBIENT_GAP = 150.0


class PetSounds:
    """Config-gated, non-blocking cue playback."""

    def __init__(self, settings=None):
        self.volume = 0.35
        self.enabled = False
        self.voice = True
        self.ambient = True
        self.ambient_gap = AMBIENT_GAP
        self._last_ambient = -1e9
        self.update(settings or {})
        self._player = _player_available()
        self._effect = None     # QSoundEffect, created on first use
        self._cache = {}        # (cue, volume) -> path on disk
        self._last = {}
        self._lock = Lock()
        self._running = 0

    def update(self, settings=None):
        """Re-read config; a hot reload keeps the cues following it."""
        settings = settings or {}
        self.enabled = bool(settings.get("enabled", False))
        self.voice = bool(settings.get("voice", True))
        self.ambient = bool(settings.get("ambient", True))
        try:
            self.ambient_gap = max(0.0, float(
                settings.get("ambient_gap_seconds", AMBIENT_GAP)))
        except (TypeError, ValueError):
            self.ambient_gap = AMBIENT_GAP
        try:
            self.volume = max(0.0, min(1.0,
                                       float(settings.get("volume", 0.35))))
        except (TypeError, ValueError):
            self.volume = 0.35

    # ---- public --------------------------------------------------------
    def play(self, cue, ambient=False):
        """Fire-and-forget one cue. Never raises, never blocks.

        ambient=True marks a sound the pet makes on its own initiative
        (rather than in answer to a click). Those share one long cooldown, so
        a pet left alone stays a quiet presence instead of a sound board.
        """
        if not self.enabled or not self._ambient_ok(ambient) \
                or not self._ready(cue):
            return
        if ambient:
            self._last_ambient = time.monotonic()
        self._dispatch(lambda: self._cue_path(cue))

    def say(self, text, skin="cat", ambient=False):
        """Babble a line of dialogue in the companion's voice."""
        if not (self.enabled and self.voice and text) or \
                not self._ambient_ok(ambient) or not self._ready("babble"):
            return
        if ambient:
            self._last_ambient = time.monotonic()
        # rotate a few files: the previous line may still be playing
        self._babble_n = (getattr(self, "_babble_n", 0) + 1) % 4
        slot = self._babble_n
        volume = self.volume

        def build():
            path = _temp_wav_path("babble_%d" % slot)
            data = babble_bytes(text, skin, volume)
            with open(path, "wb") as handle:
                handle.write(data)
            return path

        self._dispatch(build)

    def voice_cue(self, skin):
        return VOICE_CUES.get(skin, "pop")

    # ---- internals -----------------------------------------------------
    def _ambient_ok(self, ambient):
        if not ambient:
            return True
        if not self.ambient:
            return False
        return time.monotonic() - self._last_ambient >= self.ambient_gap

    def _ready(self, cue):
        now = time.monotonic()
        gap = MIN_GAP.get(cue, DEFAULT_GAP)
        last = self._last.get(cue, -1e9)
        if now - last < gap:
            return False
        self._last[cue] = now
        return True

    def _cue_path(self, cue):
        key = (cue if cue in CUES else "pop", round(self.volume, 2))
        with self._lock:
            path = self._cache.get(key)
        if path and os.path.exists(path):
            return path
        path = _temp_wav_path("%s_%d" % (key[0], int(key[1] * 100)))
        data = _wav_bytes(key[0], key[1])
        tmp = path + ".part"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
        with self._lock:
            self._cache[key] = path
        return path

    def _dispatch(self, build):
        """Synthesise (`build()` -> wav path) and play, off the GUI thread.

        QSoundEffect has to be driven from the GUI thread, so the Qt route
        synthesises inline; it is only taken when QtMultimedia exists.
        """
        if self._player == "qt":
            try:
                if self._play_qt(build()):
                    return
            except Exception:
                return
            self._player = next((p for p in _PLAYERS if _which(p)), None)
        if not self._player:
            return
        with self._lock:
            if self._running >= MAX_CONCURRENT:
                return
            self._running += 1
        try:
            Thread(target=self._work, args=(build,), daemon=True).start()
        except Exception:
            with self._lock:
                self._running = max(0, self._running - 1)

    def _work(self, build):
        try:
            path = build()
            if self._player == "winsound":
                self._play_winsound(path)
                return
            command = {
                "pw-play": ["pw-play", path],
                "paplay": ["paplay", path],
                "aplay": ["aplay", "-q", path],
                "afplay": ["afplay", path],
            }.get(self._player)
            if command:
                subprocess.run(command, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=8)
        except Exception:
            pass
        finally:
            with self._lock:
                self._running = max(0, self._running - 1)

    def _play_qt(self, path):
        """True when the Qt player took the cue."""
        if not QT_SOUND_OK:
            return False
        try:
            if self._effect is None:
                self._effect = QSoundEffect()
            self._effect.setVolume(1.0)
            self._effect.setSource(QUrl.fromLocalFile(path))
            self._effect.play()
            return True
        except Exception:
            self._effect = None
            return False

    def _play_winsound(self, path):
        try:
            import winsound as ws
            ws.PlaySound(path, ws.SND_FILENAME | ws.SND_NODEFAULT)
        except Exception:
            pass


if __name__ == "__main__":
    # python3 pet_sounds.py [cue|"say:text"] ... -- audition from a terminal
    player = PetSounds({"enabled": True, "volume": 0.6})
    for arg in sys.argv[1:] or sorted(CUES):
        if arg.startswith("say:"):
            player.say(arg[4:], os.environ.get("PET_SKIN", "cat"))
            time.sleep(2.0)
        else:
            print(arg)
            player._last.clear()
            player.play(arg)
            time.sleep(cue_seconds(arg) + 0.25)
