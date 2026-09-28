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
- **Climb Windows** — toggle window-frame climbing.
- **Speak** — ask for a line now.
- **Reset Position** — back to the middle of the floor.
- A status line showing whether AI is on, and **Retry AI** if it is configured
  but failing.
- **Exit**.

Left-click and release without dragging = pet it (in-character reply if AI is
available, canned line otherwise).

## Tests

```
python3 -m unittest discover -p 'test_*.py'
```

174 tests, no third-party test runner needed. They cover the window-tracker's
geometry, caching, HiDPI conversion and Wayland trust rules; the model's result
contract, rate limiting, key rotation and `MEMORY:` parsing; redaction and the
refusal rules; and the pet's FSM invariants (never `PERCH` without a ledge,
never walk off a titlebar, climbs finish, drag clamping, bubble layout).

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
