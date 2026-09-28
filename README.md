# Desktop Pet Companion

Pixel-art desktop buddy (cat / shiba / ghost / jarvis / ultron) with optional
Groq-powered AI dialogue and screen-aware commentary. It walks the taskbar,
perches on window titlebars, climbs window frames, and reacts to what you are
doing.

## Setup

```
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```
MODEL=qwen/qwen3.8-27b
GROQ_API_KEY=your_key_here
GROQ_API_KEY2=optional_second_key
```

Add as many `GROQ_API_KEY`, `GROQ_API_KEY2`, `GROQ_API_KEY3`... as you have.
Requests rotate across all of them; a key that fails authentication is dropped
for the session and one that gets rate-limited is sidelined for five minutes.

**Check that your key can actually reach the model.** `MODEL` defaults to
`qwen/qwen3.8-27b`. If your key cannot see it, every request fails with a 404
and the pet quietly falls back to canned lines. When that happens the app says
so once on stderr:

```
[ai_companion] model_not_found: qwen/qwen3.8-27b is not available for this key
(set MODEL in .env to a model your key can use)
```

The right-click menu shows whether AI is on and why not, and offers **Retry AI**
after you fix it.

Run it:

```
python3 pet.py
```

If no key is set, or every key fails, the pet just uses its built-in canned
lines — nothing breaks.

## Configuring the companion

All behavior tuning lives in `companion_config.json` (plain JSON, edit and
restart):

- `ai_enabled` — master on/off switch.
- `companions.<skin>.system_prompt` — personality per companion. Falls back to
  `default_system_prompt` if a skin doesn't have its own. Nested keys merge, so
  you can override one value without restating its neighbours.
- `rate_limits` — minimum seconds between lines and a max-per-hour cap, separate
  for idle chatter (`idle`) vs screenshot commentary (`screenshot`). A slot is
  only charged when a line actually comes back.
- `screenshots` — see below.
- `memory` — see below.

Secrets (`MODEL`, API keys) stay in `.env`. Everything else is in the JSON so
you're not hunting through code to change a personality or a rate limit.

Companion voice lives in exactly one place, `companion_dialogue.py`: window
reactions, time-of-day lines, petting, drops, climbs, perching, low memory, low
battery. Add a line there and every code path can use it.

## Screenshots (off by default)

When `screenshots.enabled` is `true`, the companion occasionally grabs your
screen and asks the model for one short in-character reaction. It only fires:

- if the focused window (or the cursor) actually changed in the last
  `require_recent_activity_minutes` — an idle pet with a static screen is not
  worth narrating, and quota is not spent on it,
- at most every `interval_minutes`,
- under `max_per_day` total,
- and still counts against the normal `rate_limits.screenshot` cap.

The whole policy is checked *before* any pixels are grabbed, so a refused or
rate-limited request costs nothing. The grab happens on the GUI thread (Qt
requires it); redaction, JPEG encoding and the API call happen on a worker
thread, so the pet keeps animating.

**This is off by default on purpose.** Turning it on means screenshots of your
desktop get sent to Groq's API. Read the privacy section below before enabling
it.

### Privacy / blocklist

`screenshots.blocklist` is a list of process names or window-title substrings
(case-insensitive, partial match) — e.g. `"keepass"`, `"signal"`, `"bank"`,
`"incognito"`. Before every capture:

1. If the **foreground window** matches the blocklist, the capture is skipped
   entirely — nothing is grabbed, nothing is sent.
2. Every other visible window that matches is blacked out in the captured image
   before it's sent, even if it's just sitting open in the background.
3. The blocklist is only honoured when the app can see **every** window on the
   desktop. If it can't, the capture is refused outright rather than filtered
   optimistically. That covers:
   - **Wayland**, including hybrid Wayland + XWayland sessions. XWayland lets
     the app see X clients while native Wayland windows stay invisible to it, so
     a "filtered" capture would in fact contain windows that were never listed.
     This is the case the blocklist exists for, so it fails closed.
   - Headless or unsupported sessions with no window API at all.

If you drop the blocklist entirely, captures work everywhere and nothing is
redacted — not recommended.

Redaction rectangles are translated into the grabbed screen's coordinate space,
so a second monitor does not shift them off target.

## Memory

If `memory.enabled` is `true`, the model can end a reply with a line like
`MEMORY: prefers dark roast coffee`. That is stripped out of what the pet says,
stored in `companion_memory.json` (capped at `memory.max_facts`, oldest dropped
first, duplicates ignored), and folded into future system prompts. The marker is
stripped wherever it appears, including mid-sentence, so a chatty model can't
make the pet say "memory:" out loud. Delete `companion_memory.json` any time to
wipe it. This adds no extra API calls — it rides along in the normal reply.

## Coming back to the same pet

The pet remembers where it was. `pet_state.json` holds its companion, scale,
position, energy and whether window-climbing is on, and it is written every 30
seconds, on every meaningful action, and when the process is stopped (including
`SIGTERM`, which is how systemd and pm2 stop it — a default handler would throw
the session away).

Time away costs energy: about `state.energy_decay_per_hour` per hour, capped at
eight hours, with a fifteen-minute grace period so restarting the app five times
in a row doesn't exhaust anyone. A position is only restored if it is still on a
connected display, so unplugging a monitor between sessions can't strand the
pet off-screen. **Forget Me** in the menu deletes the file.

## Moods and energy

Energy drains when the pet is busy (walking, climbing, chasing, pouncing) and
comes back when it rests or sleeps, so a pet that has been bouncing around
eventually curls up, and a rested one is up for it. Three moods follow from
that, and they change both behaviour and vocabulary:

| mood | when | behaviour | voice |
|------|------|-----------|-------|
| `sleepy` | energy below 30, or asleep | naps more, never chases or leaps | `sleepy` lines |
| `happy` | energy above 70 and petted recently | extra lively | `happy` lines |
| `content` | otherwise | the usual | its normal pools |

Waking up startled and being petted both restore energy, so the fastest way to
cheer it up is a click.

## Focus and pomodoro sessions

The pet reads a small JSON file if one exists, and gets out of the way while
you're working:

```json
{"mode": "focus", "remaining_minutes": 24, "label": "writing docs"}
```

`mode` is `"focus"` or `"break"`; every field is optional. Point it at your
timer's state file in `companion_config.json`:

```json
"focus": {
  "enabled": true,
  "state_files": ["~/.focus.json", "~/.config/focus/state.json"],
  "poll_seconds": 5
}
```

Anything that can write that file works — a shell one-liner on a cron tick, a
Taskwarrior hook, a Keyboard Maestro macro:

```
# start a 25 minute block
python3 -c "import focus_timer; focus_timer.write_state('$HOME/.focus.json','focus',25,'deep work')"
# and when it ends
python3 -c "import focus_timer; focus_timer.write_state('$HOME/.focus.json','break')"
```

During a focus block the pet stops interrupting, stops chasing the cursor, and
says one line at the start and one at the end. If the file disappears — because
your timer stopped — the session is treated as over rather than ignored.

## New movement

- **Chase** — sprints after the cursor and pounces when it gets close, giving
  up if you outrun it.
- **Pounce / Jump** — real arcs under gravity, so a hop off a titlebar reads as
  a decision rather than a glitch. Both can be switched off in the menu.

## Windows the pet should ignore

`behaviour.ignore_windows` is a list of title or process fragments. Matching
windows are never stood on or climbed, but they are still *visible* to the app —
screenshot redaction has to account for exactly the windows the pet is ignoring.
**Ignore Windows...** in the menu edits the list and saves it.

## Changing a personality without editing JSON

**Edit Personality...** opens a box with the current companion's instructions —
the same text as `companions.<skin>.system_prompt` — and applies it the moment
you save. Clearing the box removes the override and falls back to
`default_system_prompt`.

## Displays

The pet lives in the monitor it's currently on and follows it across a
multi-monitor setup, including monitors whose origin is not (0, 0). Plugging in
or unplugging a monitor re-reads the geometry and pulls the pet back on-screen
if it was left outside. HiDPI is handled by working in Qt logical pixels
throughout and converting OS window rectangles once, at the window-tracker
boundary.

## Right-click menu

- **Switch Companion** — cat, shiba, ghost, jarvis, ultron.
- **Scale** — 1x to 4x.
- **Climb Windows**, **Allow Jumping**, **Allow Chasing** — behaviour toggles.
- **Speak** — ask for a line now.
- **Look At This** — capture the screen once and comment on it. Works even when
  the automatic screenshot feature is off, and still refuses whenever the
  blocklist or the Wayland guarantee says so. Privacy is not a quota.
- **Edit Personality...** — rewrite this companion's instructions in a dialog.
- **Ignore Windows...** — windows the pet must not stand on.
- **Reset Position** — back to the middle of the floor.
- **Forget Me** — delete the saved session.
- A status line showing whether AI is on, and **Retry AI** if it is configured
  but failing.
- **Exit**.

Left-click and release without dragging = pet it (in-character reply if AI is
available, canned line otherwise).

## Tests

```
python3 -m unittest discover -p 'test_*.py'
```

239 tests, no third-party test runner needed. They cover the window-tracker's
geometry, caching, HiDPI conversion, Wayland trust rules and ignore list; the
model's result contract, rate limiting, key rotation and `MEMORY:` parsing;
redaction and the refusal rules; persistence and the focus file; and the pet's
FSM invariants — never `PERCH` without a ledge, never walk off a titlebar,
climbs finish, drag clamping, bubble layout, mood and energy behaviour, and a
6000-tick randomised run that asserts every invariant on every single tick.

## Troubleshooting

`pet.log` in this directory collects anything that went wrong in a slot. PyQt5
turns an unhandled exception inside a Qt slot into `abort()`, so every slot is
guarded; this file is where a guarded failure would show up. Set `PET_DEBUG=1`
to also print those tracebacks to stderr.

## Running it in the background

**pm2** (any OS with Node/pm2 installed):

```
pm2 start pet.py --name desktop-pet --interpreter python3
pm2 save
```

**Linux (systemd user service)**, `~/.config/systemd/user/desktop-pet.service`:

```
[Unit]
Description=Desktop Pet

[Service]
ExecStart=/usr/bin/python3 %h/desktop_pet/pet.py
Restart=on-failure

[Install]
WantedBy=default.target
```

then `systemctl --user enable --now desktop-pet`.

**Windows**: Task Scheduler → trigger "At log on" → action running
`pythonw.exe pet.py` (use `pythonw` instead of `python` so no console window opens).

## Notes

- Sprites are regenerated by `build_pet.py` in the parent project if you ever
  want to tweak the pixel art code itself — this folder is the built output.
  Drop a new skin in as `skins/<name>/` with any subset of `sit_0.png`,
  `walk_0.png`, `sleep_0.png` and it appears in the menu on next launch; missing
  states fall back gracefully.
