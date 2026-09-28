# Desktop Pet Companion

Pixel-art desktop buddy (cat / shiba / ghost) with optional Groq-powered AI dialogue
and screen-aware commentary.

## Setup

```
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```
MODEL=qwen/qwen3.6-27b
GROQ_API_KEY=your_key_here
GROQ_API_KEY2=optional_second_key
```

Add as many `GROQ_API_KEY`, `GROQ_API_KEY2`, `GROQ_API_KEY3`... as you have. The
companion rotates across all of them and skips any that fail. `qwen/qwen3.6-27b` and
`qwen/qwen3.8-27b` are the two Groq models that currently accept both text and images,
which is what makes the screenshot feature possible — swap `MODEL` for whichever you
prefer (3.8 supports `reasoning_effort` and has a higher output ceiling; 3.6 is cheaper
and takes more images per call, not that this app sends more than one at a time).

Run it:

```
python pet.py
```

If no key is set, or every key fails, the pet just uses its built-in canned lines —
nothing breaks.

## Configuring the companion

All behavior tuning lives in `companion_config.json` (plain JSON, edit and restart):

- `ai_enabled` — master on/off switch.
- `companions.<skin>.system_prompt` — personality per companion. Falls back to
  `default_system_prompt` if a skin doesn't have its own.
- `rate_limits` — minimum seconds between lines and a max-per-hour cap, separate for
  idle chatter (`idle`) vs screenshot commentary (`screenshot`). This is what stops it
  from spamming you regardless of how long you leave it running.
- `screenshots` — see below.
- `memory` — see below.

Secrets (`MODEL`, API keys) stay in `.env`. Everything else is in the JSON so you're
not hunting through code to change a personality or a rate limit.

## Screenshot commentary (off by default)

When `screenshots.enabled` is `true`, the companion occasionally grabs your screen and
asks the model for one short in-character reaction (e.g. something about Minecraft or
your code being on screen). It only fires:

- if there's been mouse/window activity in the last `require_recent_activity_minutes`
  (so it's not narrating an empty room),
- at most every `interval_minutes`,
- under `max_per_day` total,
- and still counts against the normal `rate_limits.screenshot` cap.

**This is off by default on purpose.** Turning it on means screenshots of your desktop
get sent to Groq's API. Read the privacy section below before enabling it.

### Privacy / blocklist

`screenshots.blocklist` is a list of process names or window-title substrings
(case-insensitive, partial match) — e.g. `"keepass"`, `"signal"`, `"bank"`,
`"incognito"`. Before every capture:

1. If the **foreground window** matches the blocklist, the capture is skipped
   entirely — nothing is grabbed, nothing is sent.
2. On **Windows**, every other visible window is also checked, and any that matches
   the blocklist gets blacked out in the captured image before it's sent, even if it's
   just sitting open in the background.
3. On **Linux**, the same background check is attempted via X11 (`python-xlib`). This
   works under X11 sessions. **It does not work under pure Wayland** — Wayland
   deliberately blocks apps from listing other windows, which is the same protection
   that makes this hard to build in the first place. If window detection isn't
   available at all (no X11), the app fails safe: if you've configured a blocklist, it
   skips screenshots rather than risk sending something unfiltered. You'll effectively
   get no screenshot feature on Wayland-only setups unless you drop the blocklist
   entirely (not recommended).

Be honest with yourself about that Wayland gap before relying on this for anything
truly sensitive — when in doubt, just leave `screenshots.enabled` at `false` and close
sensitive windows if you ever turn it on for a bit.

## Memory

If `memory.enabled` is `true`, the model can end a reply with a line like
`MEMORY: prefers dark roast coffee`. That line is stripped out of what the pet actually
says, stored in `companion_memory.json` (capped at `memory.max_facts`, oldest dropped
first), and quietly folded into future system prompts. Delete `companion_memory.json`
any time to wipe it. This adds no extra API calls — it just rides along in the normal
reply.

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

- Right-click the pet for the menu: switch companion, resize, force a line, exit.
- Left-click and release without dragging = pet it (in-character reply if AI is on and
  not rate-limited, canned line otherwise).
- Sprites are regenerated by `build_pet.py` in the parent project if you ever want to
  tweak the pixel art code itself — this folder is the built output.
