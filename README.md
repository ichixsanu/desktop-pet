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

or run `./install.sh`, which does the pip step, checks for `tesseract`, and
installs a menu entry for the pet (`--autostart` also starts it at login;
`--uninstall` removes the entries again).

Optional but recommended: install `tesseract` with your system package manager
(`apt install tesseract-ocr`, `pacman -S tesseract`, `brew install tesseract`).
It powers the OCR content filter described under **Screenshots** below. Without
it, captures are refused rather than sent unfiltered.

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

All behavior tuning lives in `companion_config.json` (plain JSON). **Edits are
picked up while the pet is running** — at most five seconds after you save, so
turning screenshots off actually turns them off in the process you already have
open:

- `ai_enabled` — master on/off switch.
- `companions.<skin>.system_prompt` — personality per companion. Falls back to
  `default_system_prompt` if a skin doesn't have its own. Nested keys merge, so
  you can override one value without restating its neighbours.
- `rate_limits` — minimum seconds between lines and a max-per-hour cap, tracked
  separately for idle chatter (`idle`), screenshot commentary (`screenshot`) and
  things you asked for yourself (`user`, i.e. **Speak**, petting, **Give a
  Treat**). A slot is only charged when a line actually comes back. The `user`
  pool is deliberately its own: background chatter must never be able to make
  the Talk-to-me button do nothing.
- `screenshots` — see below.
- `memory` — see below.
- `state` — saved session, including `energy_decay_per_hour`.
- `behaviour` — `ignore_windows`, `allow_jump`, `allow_chase`,
  `ai_context_lines`, `hide_on_fullscreen`, `sleep_when_idle_seconds`,
  `quiet_hours` (see **Keeping out of the way** below), and
  `always_on_top`: `"strong"` (default) makes the pet an unmanaged X11
  window that stays above everything, fullscreen video included; `"normal"`
  is a regular always-on-top window that fullscreen apps can cover.

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
rate-limited request costs nothing. Turning `screenshots.enabled` off is a hard
gate, not a preference: an automatic capture cannot happen while it is off, no
matter what else the timer or the window tracker are doing. Manual captures
(**Look At This** / **Look At My Screen**) are the one exception, because you
asked for them.

The grab happens on the GUI thread (Qt requires it); redaction, the OCR pass,
JPEG encoding and the API call happen on a worker thread, so the pet keeps
animating.

**This is off by default on purpose.** Turning it on means screenshots of your
desktop get sent to Groq's API. Read the privacy section below before enabling
it.

### Privacy / blocklist

`screenshots.blocklist` is a list of matchers, case-insensitive. A plain entry
like `"keepass"` is a substring match against the window title *or* the process
name. Prefixes make a rule specific:

| entry | matches |
|-------|---------|
| `keepass` | process name or title contains "keepass" (the old behaviour) |
| `proc:keepassxc` | the process name is `keepassxc` (or `keepassxc.exe`) |
| `proc:code*` | process name starts with `code` |
| `pid:4242` | that exact process id |
| `title:Inbox` | the window title only |
| `re:^\(\d+\)` | a regular expression against the title (or `regex:`) |

`proc:` is the precise one — a browser tab titled "keepassxc" is not the vault.
Before every capture:

1. If the **focused window** matches the blocklist, the capture is skipped
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

### Wayland: Look At This through the portal

Wayland sessions refuse out-of-process screen grabs by design, so the manual
**Look At This** capture has a special path there: it asks the desktop portal
(`org.freedesktop.portal.Screenshot`) to do the grabbing. The portal shows your
compositor's own picker dialog, you choose the screen (or decline), and whatever
comes back goes through the same OCR filter as every other capture. Because you
sat in the picker dialog, *you* are the privacy gate — the blocklist cannot be
honoured on Wayland, and nothing is pretended otherwise.

- Off by default: set `"screenshots": { "wayland_portal": true }` in
  `companion_config.json` to allow it.
- Manual only. Automatic captures never take the portal path, and they never
  try to grab on Wayland any other way.
- The portal can only hand over a whole screen, so no redaction happens on that
  path; the OCR filter still runs and can still discard the result.
- Requires QtDBus (ships with PyQt5). If the portal service is not running or
  the request times out (20s), the pet tells you and nothing was captured.

### Sounds

A tiny chiptune synth lives in `pet_sounds.py`: NES-style pulse waves, a
stepped triangle and LFSR noise, with envelopes, pitch slides, arpeggios and
vibrato. There are no audio files; every cue is a few lines of note data,
rendered off the GUI thread and cached for the session. Audition them from a
terminal:

```
python3 pet_sounds.py meow bark boo beep menace dance "say:hello there?"
```

Each companion has its own **call** (cat meow, shiba bark, ghost "boo", jarvis
beeps, ultron rumble) and its own **talking voice**: when it speaks, the line
is babbled as pitched syllable blips (Animal Crossing style) that rise on a
question and jump on an exclamation.

It is meant to be heard rarely:

- Things *you* do always get an answer: a pat, a treat, a throw, a trick.
- Things the pet does **on its own** (yawning, noticing the cursor, climbing,
  dancing) share a single cooldown, at most one every `ambient_gap_seconds`
  (150s by default).
- It only talks out loud when answering you. A line it volunteers is voiced
  about a third of the time at most, and only when the ambient cooldown allows.
  Never during quiet hours, a snooze or a focus block.

```json
"audio": { "enabled": true, "volume": 0.3, "voice": true,
           "ambient": true, "ambient_gap_seconds": 150 }
```

All of it is also in the right-click **Sound** menu. Playback goes through
QSoundEffect, `pw-play`, `paplay`, `aplay`, `afplay` or `winsound`, whichever
exists, and fails to silence, never to an error.

**Never Capture This App** in the menu adds a `proc:` rule for whatever is
focused right now (falling back to `title:` when the process name is not
available), which is usually easier than typing it. **Edit Blocklist...** shows
the whole list, one entry per line.

### OCR content filter

Redaction only knows about windows you told it about. The OCR filter is the
second line of defence: the redacted image is run through a local OCR pass, and
if the text on screen looks like credentials, the image is discarded before
anything is sent. Nothing about that text leaves the machine — the decision is
made locally and only a verdict travels.

```json
"ocr": {
  "enabled": true,
  "engine": "auto",
  "fail_closed": true,
  "max_width": 1600,
  "timeout_seconds": 6,
  "languages": "eng",
  "psm": 3,
  "extra_keywords": [],
  "allowed_keywords": []
}
```

What it looks for:

- **Strong keywords** — `seed phrase`, `private key`, `api key`, `card number`,
  `recovery code`, …
- **Fields with values** — `password: hunter2`, `token = "…"`. A line that only
  *names* a secret is not flagged: `password = os.environ["PASSWORD"]`,
  `${DB_PASSWORD}`, `api_key: <your key here>` and `secret: null` are how code
  and config templates look, and blocking those would cost you every editor
  screenshot you wanted.
- **Secret shapes** — OpenAI/Groq/GitHub/Anthropic/Slack/AWS keys, JWTs, bearer
  tokens, PEM private-key blocks.
- **Checksummed numbers** — card numbers (Luhn) and IBANs (mod-97), so a build
  id that merely looks like a 16-digit number is not a card number.
- `extra_keywords` adds your own; `allowed_keywords` exempts a line (say
  `"docs/security.md"` in a tutorial) from the keyword rules. It never exempts a
  real key or card number.

`fail_closed: true` means "if the scan could not run, refuse the capture" — a
screen full of text that we failed to read is not known to be clean. Turn it off
if you would rather capture anyway, and unset `enabled` to skip the filter.

The filter needs the `tesseract` binary (`sudo pacman -S tesseract` /
`apt install tesseract-ocr`); it is not a Python package. Without it, and with
`fail_closed: true`, captures are refused and `pet.log` says why. The
**OCR Content Filter** menu item toggles it and shows the current engine and
rule count.

### What happened to my screenshots?

**What Happened To My Screens...** opens the capture decision log: the last
`screenshots.capture_log_size` (default 20) decisions, newest first, each with
whether the image was `sent`, `discarded`, `refused` or `failed` — and the
reason, e.g. `sensitive text on screen (card number, password field)` or
`focused window matches the blocklist`. The reasons name rules, never the text
that matched.

### Look At This with no model

The manual look needs pixels to send while automatic captures need nothing to
do when AI is off — those are different cases, and they are handled
differently:

- **Manual (Look At This)** with the model off still runs the whole capture
  pipeline up to generation: policy gates, grab, local OCR. The reply is a
  canned line keyed by what the screen holds (code, a wall of text, numbers,
  or nothing). At no point in this flow is anything transmitted — this is the
  "describe" version, not an "upload" with a canned ending.
- **Automatic** captures simply do not happen when AI is off; there is no one
  to comment to.

### Always on top

The pet sets `WindowStaysOnTopHint` at startup, and re-applies its window flags
and raises itself after anything that might have re-stacked it — in particular
the hide/show dance used to keep the pet out of its own manual capture. You
should never have to hunt for it behind another window.

## Memory

If `memory.enabled` is `true`, the model can end a reply with a line like
`MEMORY: prefers dark roast coffee`. That is stripped out of what the pet says,
stored in `companion_memory.json` (capped at `memory.max_facts`, oldest dropped
first, duplicates ignored), and folded into future system prompts. The marker is
stripped wherever it appears, including mid-sentence, so a chatty model can't
make the pet say "memory:" out loud. This adds no extra API calls — it rides
along in the normal reply.

**What Do You Remember?** in the menu shows everything currently kept, read
only. The dialog's **Forget Everything** button (with a confirm step) is the
only thing that erases the memory file — the other resets (*Forget Me*, state)
deliberately leave it untouched.

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
- **Throw** — drag fast and let go: the release velocity carries, the pet
  travels through the air, lands (titled titlebar or floor, whichever is under
  it) and complains about it. A slow release is still a placement, not a
  throw. Cross-monitor drags re-seat the pet on the screen it was released on
  before the arc decides where the floor is.

## Personalities

Each companion has its own repertoire (`pet_personality.py`), so they behave
like what they are rather than five skins on one NPC:

- **Cat**: aloof. Stares at you, grooms, loafs, stalks the cursor and
  pounces, naps anywhere (up on a window by preference), climbs, gets the
  zoomies and then sits down and grooms as if nothing happened. Pet it too
  much and it walks off.
- **Shiba**: your shadow. Trots over to wherever your cursor is and sits
  looking up, sniffs along the floor, begs, barks, zoomies, spins in a circle
  before lying down. Dogs do not climb: it stays on the floor, and hops down
  if you put it on a window.
- **Ghost**: no floor. Drifts anywhere on screen, haunts the cursor from a
  polite distance, phases out in a puff and reappears somewhere else, and
  spooks you if the cursor creeps up on it.
- **Jarvis**: a butler drone. Cruises and patrols at hover height, floats over
  beside your cursor to "assist", scans, docks to recharge when low.
- **Ultron**: heavy and theatrical. Marches (every step kicks up dust), glares
  at the cursor, stalks it, scales windows and surveys from the top, power
  surges, stomps.

Picks are weighted per companion and remembered: the same action never
happens twice in a row, and anything done recently is strongly discounted.
Climbing up to a window has a cooldown (2.5 minutes for the cat), and once up
there the pet settles in for a while instead of bouncing straight back down.

## Reactions

The pet reacts to things with its body as well as its mouth. Every companion
has frames for all of these:

- **Pat it** (click): it leans into your hand, with hearts. Pat it a few times
  in a row and it hops for joy. Poke it while it is deep asleep and it sulks.
- **Double-click**: a trick. It hops, turns around mid-air and sparkles.
- **Give a Treat**: it eats (a bowl for the cat and shiba, a cookie for the
  ghost, a battery filling up on the robots' screens), then celebrates.
- **Shake it** while dragging (wiggle left and right): it lands dizzy, with
  stars circling its head. A very hard throw can do the same.
- **Flick the cursor** past it: ears up, a "!" over its head. It does not
  fall for this every time.
- **Play > Laser Pointer**: for 30 seconds it sprints after your cursor and
  pounces on it.
- **Play > Dance!**: a short dance with music notes. A happy, rested pet
  sometimes dances on its own.
- **Yawns** as it nods off and as it wakes up, **Zzz** while asleep, dust when
  it lands or runs, sweat drops when it is running on empty.

Particles are drawn on the same pixel grid as the sprite, in a separate
click-through overlay window, so a heart at 4x is made of the same 4px blocks
as the cat. Speech types itself into a pixel-art bubble.

## Daily life

- **Anniversaries** — once per completed day of total lifetime, the pet marks
  it with one line. The counter is the accumulated lifetime across sessions,
  and the milestone is saved the moment it triggers so a restart can't repeat
  it.
- **Wake-ups** — wake a napping pet and it sometimes has a word to say about
  being interrupted.
- Energy drains with activity and recovers while resting, and `state.energy_decay_per_hour`
  applies while the app is closed.

## Windows the pet should ignore

`behaviour.ignore_windows` is a list of title or process fragments. Matching
windows are never stood on or climbed, but they are still *visible* to the app —
screenshot redaction has to account for exactly the windows the pet is ignoring.
**Ignore Windows...** in the menu edits the list and saves it.

## Keeping out of the way

Three `behaviour` settings decide when the pet stays quiet, all optional:

- `hide_on_fullscreen` (default `true`) — hides while a fullscreen window is
  focused (a film, a game, a slideshow) and comes back when it isn't. It still
  checks once a second, so it is off your screen but not asleep. Detection is
  geometric on every platform (window rect vs screen), with an X11 hint where
  the window manager can answer directly.
- `sleep_when_idle_seconds` (default `300`) — after this long with no keyboard
  or mouse input, the pet naps and stops wandering an empty screen. It wakes on
  your next input. `0` disables it. Idle time comes from the OS where possible:
  XScreenSaver on Linux, `GetLastInputInfo` on Windows, `CGEventSource` on
  macOS; without one the pet falls back to its own cursor-activity signal.
- `quiet_hours` — `{"enabled": true, "start": "23:00", "end": "07:00"}`
  (windows that cross midnight work) suppresses idle chatter and window
  comments. Lines you asked for still happen: quiet hours mean "don't
  interrupt", not "don't speak".

`ai_context_lines` (default `true`) controls whether idle window comments may
use the model. Off means the pet still reacts to your windows, just from the
built-in canned lines — no tokens, no network.

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
- **Scale** — 1x to 8x, always a whole multiple of the 16x16 art, so every
  art pixel is an identical square (on a HiDPI screen the sprites are built
  at the physical resolution, not upscaled twice).
- **Climb Windows**, **Allow Jumping**, **Allow Chasing**, **Click Through** —
  behaviour toggles. Click-through makes the pet ignore the mouse entirely
  (handy on a busy screen); the tray icon still offers the full menu, which is
  the way back out. All four remember your choice.
- **Focus Timer** — enable/disable reading the focus file without editing JSON.
- **Speak** — ask for a line now.
- **Give a Treat** — a small energy top-up, on a cooldown.
- **Play** — **Dance!**, **Do a Trick**, **Laser Pointer**.
- **Sound** — sounds on/off, the talking voice, rare sounds on its own, and
  Quiet / Normal / Loud.
- **Shush...** — 15 minutes / 1 hour / 2 hours of silence for films and calls
  (session-only: quiet hours are the permanent version). Unshush any time, or
  just pet the pet — being touched ends the snooze early. Requested lines
  (Speak, petting, Look At This) are never muted by a snooze.
- **Screenshots && Privacy** — the whole capture policy in one submenu:
  - **Look At My Screen** — turn automatic captures on/off.
  - **Look At This** — capture the screen once and comment on it. Works even
    when the automatic feature is off, still refuses whenever the blocklist,
    the Wayland guarantee or the OCR filter says so. Privacy is not a quota.
  - **Never Capture This App** — blocklist whatever is focused right now.
  - **Edit Blocklist...** — the raw rule list.
  - **OCR Content Filter** — toggle the filter (the item below it shows the
    engine, rule count and fail mode).
  - a status line, and **What Happened To My Screens...**.
- **Edit Personality...** — rewrite this companion's instructions in a dialog.
- **Ignore Windows...** — windows the pet must not stand on.
- **Reset Position** — back to the middle of the floor.
- **Forget Me** — delete the saved session.
- **What Do You Remember?** — read back the pet's long-term memory (see
  **Memory**), with an explicit erase behind a confirm dialog.
- A status line showing whether AI is on, and **Retry AI** if it is configured
  but failing. Below it, a small stats line (time alive, sessions, pets,
  treats).
- **Exit**.

The same menu is on the tray icon, rebuilt each time it opens so the
checkmarks and status text are never stale.

Left-click and release without dragging = pet it (in-character reply if AI is
available, canned line otherwise). If the model is rate-limited, slow or
unreachable, the canned line happens instead — the pet never just stands there
because a request is in flight.

## Tests

```
python3 -m unittest discover tests
```

Run it from the repository root. About 480 tests, no third-party test runner
needed. They cover the window-tracker's
geometry, caching, HiDPI conversion, Wayland trust rules and ignore list, and
the macOS CoreGraphics backends; the model's result contract, rate limiting,
key rotation, `MEMORY:` parsing and config hot-reload; redaction, the blocklist
prefixes and the refusal rules; the OCR filter including its own
false-positive rules and its fail-closed behaviour; the Wayland portal flow
against a faked D-Bus (interactive flag, single-answer latch, timeout, URI
cleanup); the synthesizer (valid WAVs, normalised levels, no DC offset or clicks), the
babble voices and the ambient-sound cooldown; the sprite pipeline (every skin
validates and the PNGs on disk match the generator); persistence, the
focus file and the lifetime counter; and the pet's FSM invariants — never
`PERCH` without a ledge, never walk off a titlebar, never stand on a window
that closed, climbs finish, drag clamping, bubble layout, mood and energy
behaviour, quiet hours, the idle nap, fullscreen hiding, the memory-recall
menu, and a 6000-tick randomised run that asserts every invariant on every
single tick.

## Troubleshooting

`pet.log` in this directory collects anything that went wrong in a slot. PyQt5
turns an unhandled exception inside a Qt slot into `abort()`, so every slot is
guarded; this file is where a guarded failure would show up. Set `PET_DEBUG=1`
to also print those tracebacks to stderr.

## Running it in the background

`./install.sh --autostart` writes a desktop entry into your autostart folder
(Linux/BSD; the plain `./install.sh` run only installs the menu entry and
dependencies). Otherwise:

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

- Sprites are 16×16 pixel art. The source of truth is the code in `art/`:
  `sprites_quad.py` is a four-legged rig shared by the cat and the shiba
  (species differ in head, ears, tail and markings), `sprites_ghost.py` and
  `sprites_bots.py` draw the rest, on top of the tiny engine in `pixelart.py`.
  `python3 art/generate_sprites.py` rebuilds `skins/<name>/*.png`
  (`--check` validates only, `--sheet` writes a contact sheet to look at).
  The PNGs are committed so the pet runs without a build step, and a test
  fails if they drift from the generator.
- A hand-made skin still works: drop PNGs into `skins/<name>/` named
  `<animation>_<n>.png` (any subset of `sit`, `walk`, `run`, `sleep`, `happy`,
  ...) and it appears in the menu; missing animations fall back gracefully.
- State that is private stays private: `pet_state.json`,
  `companion_memory.json` and the capture log are written with `0600`
  permissions, and `.env` should be too (`chmod 600 .env`).
- `pet.log` rotates to `pet.log.1` when it grows past `pet.LOG_MAX_BYTES`, so a
  long-lived pet cannot fill a disk.
