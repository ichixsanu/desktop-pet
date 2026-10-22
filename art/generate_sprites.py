"""generate_sprites.py - build the 16x16 pixel-art skins.

    python3 art/generate_sprites.py             # every companion
    python3 art/generate_sprites.py cat shiba   # just these
    python3 art/generate_sprites.py --sheet cat # also drop a contact sheet
                                                # in /tmp/opencode/pet for eyeballing
    python3 art/generate_sprites.py --check     # validate only, write nothing

Frames are written to skins/<skin>/<state>_<n>.png. The pet loader walks
<state>_0, <state>_1... and stops at the first gap, so indices must be
contiguous from zero. `--check` enforces that, plus palette sanity and "the
sprite actually touches the ground it claims to stand on".
"""

import os
import sys

ART_DIR = os.path.dirname(os.path.abspath(__file__))
SKINS_DIR = os.path.join(os.path.dirname(ART_DIR), "skins")
if ART_DIR not in sys.path:
    sys.path.insert(0, ART_DIR)

import pixelart  # noqa: E402
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
    frames = builder(skin) if skin in ("jarvis", "ultron") else builder()
    if not isinstance(frames, dict) or not frames:
        raise SpriteError("%s.frames() returned no frames" % MODULES[skin])
    return module, frames


def palette_for(skin, module):
    """One module can draw several skins with different palettes."""
    chooser = getattr(module, "palette", None)
    if callable(chooser):
        return chooser(skin)
    return module.PALETTE


def validate(skin, module, frames):
    """Return a list of problems: missing indices, unknown keys, floaters."""
    problems = []
    palette = palette_for(skin, module)
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
        if (sprite.w, sprite.h) != (16, 16):
            problems.append("%s: %dx%d, every frame must be 16x16"
                            % (name, sprite.w, sprite.h))
    for required in REQUIRED:
        if not any(n.startswith(required + "_") for n in frames):
            problems.append("missing animation %r" % required)
    return problems


# Every skin must ship these; the pet's frame table falls back for anything
# else, but these are what the behaviour code leans on.
REQUIRED = ("sit", "idle", "blink", "walk", "run", "sleep", "drag", "happy",
            "pet", "eat", "dizzy", "yawn", "dance", "alert", "jump", "fall")


def clear_stale(skin_dir, keep):
    """Remove PNGs a previous generator left behind.

    The loader prefers <state>_<n>.png but falls back to <state>.png, so an
    old single-frame file would otherwise shadow nothing and confuse anyone
    reading the folder -- or worse, a stale <state>_2.png extends a fresh
    two-frame cycle with an old drawing.
    """
    if not os.path.isdir(skin_dir):
        return
    for entry in os.listdir(skin_dir):
        if entry.endswith(".png") and entry[:-4] not in keep:
            os.remove(os.path.join(skin_dir, entry))


def write_sheet(skin, module, frames):
    os.makedirs(SHEET_DIR, exist_ok=True)
    ordered = sorted(frames.items())
    path = os.path.join(SHEET_DIR, "sheet_%s.png" % skin)
    pixelart.save_sheet(path, ordered, palette_for(skin, module),
                        scale=6, columns=10)
    print("  sheet: %s (%d frames)" % (path, len(ordered)))


def main(argv):
    sheet = "--sheet" in argv
    check_only = "--check" in argv
    wanted = [a for a in argv if not a.startswith("-")]
    wanted = wanted or list(MODULES)
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
        skin_dir = os.path.join(SKINS_DIR, skin)
        clear_stale(skin_dir, set(frames))
        pixelart.write_skin(skin_dir, frames, palette_for(skin, module))
        if sheet:
            write_sheet(skin, module, frames)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
