"""pet_personality.py - who each companion is, as behaviour.

Every companion used to share one decision table, so a cat, a dog, a ghost
and two robots all did the same things in the same proportions: an NPC with
five skins. Here each one gets its own repertoire and its own habits:

    cat     aloof. Stares, grooms, stalks and pounces, naps anywhere (high
            places preferred), gets the zoomies and then grooms as if nothing
            happened, climbs. Walks off when petted too much.
    shiba   your shadow. Follows the cursor around, sniffs the floor, begs,
            barks, zoomies, spins in a circle before lying down. Dogs do not
            climb walls: it stays on the floor.
    ghost   no floor at all. Drifts anywhere on screen, haunts the cursor,
            phases out and reappears somewhere else, spooks you.
    jarvis  a butler drone. Patrols at hover height, floats over to the
            cursor to "assist", scans the window you are working in, docks to
            recharge instead of sleeping.
    ultron  a heavy, theatrical walker. Marches (every step thuds), glares at
            the cursor, stalks it, scales windows and surveys from the top,
            power surges, stomps.

Choosing is weighted-random with a memory: the same action never happens
twice in a row, and anything done in the last few picks is strongly
discounted, so a pet left alone keeps doing *different* things.

This module is pure data and a chooser; pet.py implements the actions.
"""

import random

# Actions that take energy. A tired pet, or one in a focus block, skips them.
ENERGETIC = {"chase", "zoomies", "stalk", "hop", "climb", "explore", "dance",
             "haunt", "stomp", "beg", "follow", "surge", "assist"}

# Actions that need a permission toggle from the menu.
NEEDS = {"chase": "allow_chase", "hop": "allow_jump", "stomp": "allow_jump",
         "climb": "climb_enabled", "explore": "climb_enabled"}

PROFILES = {
    "cat": {
        "floor": {"stare": 8, "groom": 9, "wander": 8, "stalk": 6,
                  "climb": 5, "nap": 5, "blink": 3, "hop": 2, "chase": 2,
                  "explore": 3, "zoomies": 1.5, "loaf": 6, "dance": 0.3},
        # up high a cat settles in: it grooms, stares, naps, and stays a while
        "ledge": {"stare": 8, "groom": 7, "nap": 7, "loaf": 7, "wander": 3,
                  "blink": 2, "go_down": 2.5, "explore": 1.5},
        "walk_speed": 1.1,
        "explore_cooldown": 150,
        "aloof": True,
        "after": {"zoomies": "groom"},    # "i meant to do that"
    },
    "shiba": {
        "floor": {"follow": 10, "sniff": 8, "zoomies": 5, "chase": 6,
                  "hop": 4, "beg": 4, "bark": 3, "dance": 3, "wander": 5,
                  "nap": 3, "stare": 3, "blink": 2},
        # placed on a window by hand: it wants down
        "ledge": {"go_down": 12, "bark": 3, "stare": 2},
        "walk_speed": 1.6,
        "explore_cooldown": None,
        "nap_spin": True,
    },
    "ghost": {
        "air": {"drift": 12, "haunt": 6, "phase": 4, "stare": 5, "wave": 3,
                "blink": 3, "nap": 3, "dance": 1.5},
        "walk_speed": 1.4,
        "explore_cooldown": None,
    },
    "jarvis": {
        "air": {"patrol": 9, "drift": 7, "assist": 6, "scan": 7, "blink": 3,
                "charge": 2, "beep": 2, "nap": 2, "dance": 1},
        "walk_speed": 2.2,
        "explore_cooldown": None,
    },
    "ultron": {
        "floor": {"march": 9, "stalk": 7, "glare": 6, "climb": 6,
                  "explore": 4, "scan": 4, "surge": 3, "stomp": 3,
                  "stare": 3, "blink": 2, "nap": 2, "charge": 2,
                  "dance": 0.4},
        # atop a window: surveying the domain
        "ledge": {"glare": 8, "stare": 6, "scan": 5, "march": 3,
                  "go_down": 3, "explore": 2, "surge": 2},
        "walk_speed": 0.8,
        "explore_cooldown": 100,
        "heavy": True,
    },
}

FLYERS = ("ghost", "jarvis")
RECENT = 4


def profile(skin):
    return PROFILES.get(skin) or PROFILES["cat"]


def flies(skin):
    return skin in FLYERS


class Chooser:
    """Weighted pick with anti-repetition, per companion."""

    def __init__(self, rng=None):
        self.recent = []
        self.rng = rng or random

    def forget(self):
        self.recent = []

    def remember(self, action):
        self.recent.append(action)
        del self.recent[:-RECENT]

    def weights(self, skin, context, *, tired=False, focusing=False,
                allowed=None, can_explore=True, energy=100.0):
        table = dict(profile(skin).get(context) or {})
        out = {}
        for action, weight in table.items():
            if weight <= 0:
                continue
            if action in ENERGETIC and (tired or focusing):
                continue
            if allowed is not None and not allowed(action):
                continue
            if action == "explore" and not can_explore:
                continue
            if action == "charge" and energy > 70:
                continue
            if self.recent and action == self.recent[-1]:
                continue                       # strictly: never twice in a row
            if action in self.recent:
                weight *= 0.25
            if action == "nap" and tired:
                weight *= 4
            out[action] = weight
        return out

    def pick(self, skin, context, **kw):
        table = self.weights(skin, context, **kw)
        if not table:
            return None
        total = sum(table.values())
        roll = self.rng.random() * total
        for action, weight in table.items():
            roll -= weight
            if roll <= 0:
                return action
        return next(reversed(table))
