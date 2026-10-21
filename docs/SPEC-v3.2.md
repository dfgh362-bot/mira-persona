# ============================================================
# BUILD ORDER v3.2 — "MIRA" — OPEN THE FUNNEL
# ============================================================
# v3.1 and v4 govern. v3.2 adds: a human wiring channel,
# YAML lint, and funnel-first escalation.

## 0. THE PROBLEM
The loop is healthy and producing. Nothing is published.
The bottleneck is now human wiring. Fix the funnel, not the metric.

## 1. WIRE COMMAND — new, highest priority
issues.py gains a handler for each of these, as issue title or first line:
  WIRE <platform> [KEY=value ...]
  PAUSE | RESUME | STOP | STATUS | REPAIR | REFILL | DRAIN
WIRE does:
  1 parse KEY=value pairs from the issue body
  2 upload each as an Actions secret (sealed box, PyNaCl — already used for MAIL_PASS)
  3 set accounts.json platforms.<p>.status = "ready"
  4 comment the result (never echo secret values), close the issue
onboard_check picks it up next cycle.
DRAIN = post every unposted item immediately, ignore the schedule.
Every command: comment on start, comment on result, close on success.

## 2. YAML LINT — a silent-death class
A step name containing ":" broke the workflow parse. No dispatch,
no cron, no error. That class must never recur silently.
Add scripts/lint_workflows.py, called at the TOP of every cycle,
before anything else:
  - yaml.safe_load every .github/workflows/*.yml
  - assert each has a trigger and >= 1 job
  - on failure: open a "blocked" issue immediately, halt the cycle
Add it to selftest.py too.

## 3. DEADMAN HARDENING
The deadman check lives inside the loop, so a dead loop cannot
report itself. The real watchdog is cron. Make it explicit:
  - keepalive.yml verifies every workflow's last run via the API
  - re-enable any workflow whose schedule was disabled
  - if any workflow has 0 runs in 24h: open a "blocked" issue
  - write the dependency chain into HEALTH.md:
      cron (external) -> loop run -> deadman -> issue

## 4. FUNNEL-FIRST ESCALATION (supersedes R-05's trigger)
If unposted items are older than 24h:
  escalate POSTING, not generating.
  - do not raise img_free_day while unposted queue > 20
  - insert "post now" items ahead of quota items
Only escalate generation when the unposted queue is empty.

## 5. ONBOARD NAME CONTRACT
onboard_check.py must accept BOTH canonical env names AND a
config/accounts.json creds block, so hand-added creds still fire it.
Print the exact expected env names into BLOCKERS.md per platform,
so the human cannot guess wrong. Canonical names, exact:
  telegram  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  bluesky   BSKY_HANDLE, BSKY_APP_PASSWORD
  mastodon  MASTODON_INSTANCE, MASTODON_TOKEN
  reddit    REDDIT_CLIENT_ID, REDDIT_SECRET, REDDIT_USERNAME,
            REDDIT_PASSWORD, REDDIT_SUBREDDIT
  x         X_BEARER_TOKEN
  pinterest PINTEREST_TOKEN, PINTEREST_BOARD_ID
  fanvue    FANVUE_EMAIL, FANVUE_PASSWORD

## 6. FIRST POST CEREMONY
The moment any platform goes ready:
  - post the pinned disclosure FIRST, verbatim
  - then post the oldest unposted item
  - comment the live URL on the wire issue

## 7. REPORT
Cycle report, one line. No summary.
