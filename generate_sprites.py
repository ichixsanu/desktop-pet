"""generate_sprites.py - build the pixel-art skins.

    python3 generate_sprites.py                 # every companion
    python3 generate_sprites.py cat shiba       # just these
    python3 generate_sprites.py --sheet cat     # also drop a contact sheet
                                                # in /tmp/opencode/pet for eyeballing
    python3 generate_sprites.py --check         # validate only, write nothing

Frames are written to skins/<skin>/<state>_<n>.png. The pet loader walks
<state>_0, <state>_1... and stops at the first gap, so indices must be
contiguous from zero. `--check` enforces that, plus palette sanity and "the
sprite actually touches the ground it claims to stand on".
"""

import os
import sys

import pixelart

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SKINS_DIR = os.path.join(BASE_DIR, "skins")
SHEET_DIR = "/tmp/opencode/pet"

MODULES = {
    "cat": "sprites_cat",
    "shiba": "sprites_shiba",
    "ghost": "sprites_ghost",
    "jarvis": "sprites_bots",
    "ultron": "sprites_bots",
}


def load_module(name):
    import importlib
    return importlib.import_module(name)


class SpriteError(Exception):
    """A skin could not be built at all."""


def frame_set(skin):
    """(module, frames) for a skin.

    A module that is still being written (no `frames()` yet) is a reportable
    problem, not a traceback: `--check` exists to say what is wrong.
    """
    module = load_module(MODULES[skin])
    builder = getattr(module, "frames", None)
    if not callable(builder):
        raise SpriteError("%s has no frames() function yet" % MODULES[skin])
    frames = builder("ultron") if skin == "ultron" else builder()
    if not isinstance(frames, dict) or not frames:
        raise SpriteError("%s.frames() returned no frames" % MODULES[skin])
    return module, frames


def validate(skin, module, frames):
    """Return a list of problems: missing indices, unknown keys, floaters."""
    problems = []
    palette = module.PALETTE
    families = {}
    for name in frames:
        base, _, index = name.rpartition("_")
        if not index.isdigit():
            problems.append("%s: frame name must end in _<n>" % name)
            continue
        families.setdefault(base, []).append(int(index))

    for base, indices in sorted(families.items()):
        want = list(range(len(indices)))
        if sorted(indices) != want:
            problems.append("%s: indices %s, expected %s"
                            % (base, sorted(indices), want))

    for name, sprite in sorted(frames.items()):
        for key in sprite.used_keys():
            if key not in palette:
                problems.append("%s: unknown palette key %r" % (name, key))
        box = sprite.box()
        if box is None:
            problems.append("%s: empty sprite" % name)
            continue
        x0, y0, x1, y1 = box
        if x0 < 0 or y0 < 0 or x1 >= sprite.w or y1 >= sprite.h:
            problems.append("%s: content outside the canvas" % name)
    return problems


def write_sheet(skin, module, frames):
    os.makedirs(SHEET_DIR, exist_ok=True)
    ordered = sorted(frames.items())
    path = os.path.join(SHEET_DIR, "sheet_%s.png" % skin)
    pixelart.save_sheet(path, ordered, module.PALETTE, scale=6, columns=6)
    print("  sheet: %s (%d frames)" % (path, len(ordered)))


def main(argv):
    sheet = "--sheet" in argv
    check_only = "--check" in argv
    wanted = [a for a in argv if not a.startswith("-")]
    wanted = wanted or [s for s in MODULES if s != "ultron" or True]
    # jarvis + ultron come from one module: run both when either is asked for.
    if "jarvis" in wanted or "ultron" in wanted:
        for skin in ("jarvis", "ultron"):
            if skin not in wanted:
                wanted.append(skin)

    failed = False
    for skin in wanted:
        if skin not in MODULES:
            print("unknown skin %r" % skin)
            failed = True
            continue
        try:
            module, frames = frame_set(skin)
        except SpriteError as problem:
            print("%s: ! %s" % (skin, problem))
            failed = True
            continue
        except ImportError as problem:
            print("%s: ! cannot import %s (%s)"
                  % (skin, MODULES[skin], problem))
            failed = True
            continue
        problems = validate(skin, module, frames)
        print("%s: %d frames" % (skin, len(frames)))
        for problem in problems:
            print("    ! %s" % problem)
        failed = failed or bool(problems)
        if problems or check_only:
            continue
        pixelart.write_skin(os.path.join(SKINS_DIR, skin), frames, module.PALETTE)
        if sheet:
            write_sheet(skin, module, frames)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
