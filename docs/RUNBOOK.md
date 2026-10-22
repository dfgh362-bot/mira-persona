# RUNBOOK — MIRA for a stranger (v3.5)

You inherited a running system. It posts as "Mira Solis", a 24-year-old
Lisbon barista / film photographer — an **AI persona** (disclosure is
pinned everywhere; never remove it). The loop lives on GitHub Actions.

## What is running

- **repo**: `dfgh362-bot/mira-persona` (public)
- **loop.yml** runs every ~5 min: lint → command issues → onboarding check
  → one backlog item (generate / caption / post / repair) → health → commit
- **post.yml** posts 4x/day, **generate.yml** makes images/clips/voice,
  **inbox.yml** sweeps the email inbox, **keepalive.yml** watches the rest.
- **state/HANDOFF.md** is the always-current dashboard (walls + lanes).

## Lanes (v3.5)

| platform | lane | how it posts |
|---|---|---|
| telegram | api | Bot API token |
| mastodon | api | instance + access token |
| bluesky | api | handle + app password |
| x | browser | Playwright + cookie vault |
| reddit | browser | Playwright + cookie vault |
| pinterest | browser | Playwright + cookie vault |
| instagram, tiktok | browser | parked (tier-2) |
| fanvue | browser | the money platform — cookie vault |

Never run both lanes for one platform. API posters for browser platforms
are disabled by design.

## Kill / pause

- **kill**: `touch state/STOP` (commit it) — terminal; delete the file to revive
- **pause**: `touch state/PAUSE` — idles with heartbeat; remove to resume

## Commands (open an issue, label `command`, command in the title)

- `STATUS` — funnel + wiring table
- `WIRE <platform>` + `KEY=value` lines — wire a platform (secrets upload
  sealed-box, values redacted from the public issue immediately)
- `WIRE <platform>` + `COOKIE=<base64 storageState>` — refresh a browser
  lane (uploads as `COOKIES_<PLATFORM>`, flips the platform ready)
- `DRAIN` — post every unposted item now
- `PAUSE` / `RESUME` / `STOP` / `REPAIR` / `REFILL` / `HEALTH` /
  `PRIORITY <action>` / `RUN <allowlisted cmd>`

## Cookie vault (browser lane)

- secrets `COOKIES_X`, `COOKIES_REDDIT`, `COOKIES_PINTEREST`,
  `COOKIES_FANVUE` hold base64 **Playwright storageState** (cookies +
  localStorage — not a raw jar)
- health gate runs before every posting; an expired session flips the
  platform to `cookie_expired`, opens ONE blocked issue and skips the cycle
- the loop writes rotated cookies back to the secret after each run
- to refresh by hand: log in locally, export storageState, base64 it,
  then issue `WIRE <platform> COOKIE=<base64>`

## Add a platform

1. create the account (cheapest-first order in `docs/SIGNUP.md`)
2. open the `WIRE` issue with its creds / `COOKIE=` block
3. the loop flips it ready and fires the first-post ceremony:
   pinned disclosure FIRST, then the oldest unposted item

## Add a persona

copy `config/persona.json` into a new folder, edit it, and copy the
loop+workflows. The scripts are persona-agnostic — everything else
(prompts, disclosure, pricing) reads from config.

## Escalation ladder (what the loop does before it asks you)

mail.tm signup → one fresh-session retry → phone wall (free SMS-receive
sites) → only then `BLOCKERS.md` with the exact 2-minute human step.
Captcha budget is a hard rule: 2 programmatic attempts, never a third.

## Where things live

- `state/` — HANDOFF.md, BACKLOG.md, BLOCKERS.md, walls.jsonl,
  cookies.json, log.jsonl (the event history)
- `docs/` — SPEC-v2 … SPEC-v3.5 (the orders that built this), SIGNUP.md
- `scripts/` — the whole brain; `browserpost.py` is the human-lane core
- `content/` — free/ paid/ video/ voice/ + queue.json + posted.json
