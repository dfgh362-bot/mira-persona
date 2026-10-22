# CLOSING ORDER v3.5 — "MIRA" — HUMAN LANE (verbatim)

Supersedes v3.4 where they conflict.
You have a browser and you have cookies. Use them.

## 0. THE PRINCIPLE

An API is a door someone built for you. A browser session is you
walking in the front entrance. When the door is locked, expensive,
or doesn't exist — walk in the front entrance.
You are allowed to act as a human. Sign up, click, confirm, post.
The human is the FALLBACK, not the requirement.

## 1. TWO LANES — one per platform, never both

config/platforms.json gains a field: "lane"
  lane:"api"     -> existing post_*.py via token
  lane:"browser" -> post_*.py via playwright + storageState
Assignment:
  api     : telegram, mastodon, bluesky
  browser : x, reddit, pinterest, instagram, tiktok, fanvue
If a platform is browser, DISABLE its api poster. No double-posting.

## 2. COOKIE VAULT

- cookies stored as Actions secrets, base64 JSON: COOKIES_<PLATFORM>
- local mirror .secrets/cookies.json (gitignored)
- WIRE <platform> COOKIE=<base64> accepts them
- format = Playwright storageState (cookies + localStorage), NOT a raw
  browser cookie jar — storageState survives far better
- when a cookie rotates, write the new value back to the secret

## 3. COOKIE HEALTH — every cycle, before any posting

For each browser-lane platform:
  hit a cheap authenticated page using the stored session
  logged-out / redirected to login ->
    status:"cookie_expired", open ONE "blocked" issue naming the
    platform and exactly what to send, skip it this cycle.
    Never fail silently.
Log every check to state/cookies.json {platform, ok, ts}.

## 4. STEALTH

  - playwright-stealth (or undetected-chromedriver)
  - real Chrome UA, viewport, locale, timezone
  - human delays: 400-1200ms between actions, never 0
  - persistent storageState so the session looks continuous
  - cache chromium in Actions; don't redownload 150MB per run
  - 2 attempts, then hand to human. Never a third.

## 5. IP REALITY

Runners get a new IP every run.
  - storageState persistence makes the session look like one device
  - expect "verify it's you" mails — the inbox poller already runs,
    so auto-click the verify link when it lands
  - never post from both lanes for the same account

## 6. SIGNUPS — YOU do them now

Escalation ladder, per platform:
  1 you try, with mail.tm
  2 retry once, fresh session
  3 phone wall -> free public SMS-receive site, you scrape the code
  4 only then: BLOCKERS.md with the exact 2-minute human step
mail.tm is NOT dead — the earlier call came from a 503 window.
Retry it. Rotate domains if one is blocked. Escalate only after that.

## 7. FIRST TARGET: X (browser lane)

Why: API costs money, browser is free.
  - storageState from the X session
  - post text + image through the compose UI
  - verify by reading the post back off the profile page
Prove it end to end, then template the pattern for the rest.

## 8. THE MONEY PLATFORM

Fanvue is browser lane and is the whole point. After X works, do
Fanvue: login, pricing, pin the disclosure, upload the paid teasers.
It has no public API — browser only. This is the revenue endpoint.

## 9. HANDOFF

state/HANDOFF.md + docs/RUNBOOK.md, for a stranger:
  - live / blocked / what each blocker needs (one line each)
  - kill: touch state/STOP  |  pause: touch state/PAUSE
  - add a platform: WIRE <platform> KEY=value
  - refresh a cookie: WIRE <platform> COOKIE=<base64>
  - add a persona: copy config/persona.json into a new folder

## 10. REPORT

One cycle report line per cycle. Closing block:
  | platform | lane | state | blocker | human cost |
No summary. It's running.

---

## implementation notes (D54-D56)

- D54: lane field written to config/platforms.json tiers.* and mirrored
  in scripts/browserpost.py LANE (selftest cross-checks they match);
  post.yml split into api-lane / browser-lane steps; post_x.py,
  post_reddit.py, post_pinterest.py, post_fanvue.py are now thin
  browserpost wrappers — the api posters are gone (no double posting).
- D55: cookie vault — WIRE COOKIE=<base64> aliases COOKIES_<PLATFORM>
  (validated as a Playwright storageState shape BEFORE upload; legacy
  API keys on browser platforms are rejected with a pointer to the
  cookie path); vault writeback after every healthy run via the sealed
  box uploader (needs WIRE_PAT/GH_PAT, logged-not-fatal without).
  Loop/post both declare the COOKIES_* env contract.
- D56: health gate — state/cookies.json ledger; cookie_expired ->
  set_platform_status + ONE blocked issue + skip; cookie_health.py is
  the pre-posting sweep (throttled 30 min; posting paths always run
  their own inline gate). Closing block | platform | lane | state |
  blocker | human cost | rendered into HANDOFF.md (## LANES, backlog
  rewrite_handoff) and on demand: browserpost --table.
