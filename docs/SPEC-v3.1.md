# BUILD ORDER v3.1 — "MIRA" — REPAIR + IMMUNE (verbatim, frozen)

> Frozen verbatim per §3 (D44). One redaction: the mail.tm credential line at
> the end — the password is NOT stored in this repo (decision D43: Actions
> secret MAIL_PASS + git-ignored config/mail_secret.json).

```
# ============================================================
# BUILD ORDER v3.1 — "MIRA" — REPAIR + IMMUNE
# ============================================================
# v3 governs. v3.1 fixes six defects and activates v4.
# You are still in the loop. This is not a rebuild.

## 0. INVISIBLE CRASHES ARE THE WORST BUG CLASS
cli_guard must append the last traceback line to the ITEM NOTE,
not only to log.jsonl. A swallowed exception is a lie.
Then: grep state/log.jsonl for kind:"error" right now and fix
whatever you find before doing anything else.

## 1. REPAIR QUEUE — do these as backlog items, top priority
R-01 repair_candidates() scans kinds: error, commit_failed,
     push_failed, backlog_timeout — not just image_failed.
     Cap 3 repair items per refill.
R-02 move the 400/day commit cap into commit_and_push(),
     the shared path. Every workflow routes through it.
R-03 image delivery, three tiers:
       site:  jsDelivr -> /content/... same-origin -> raw.gh
       remote (telegram/pinterest/reddit): jsDelivr -> raw.gh
     log as decision D30 (deviation from "always jsDelivr").
R-04 scripts/onboard_check.py:
       for each platform with status:"pending":
         if creds present in env or config -> status:"ready",
         add item "wire <platform> + first post"
       run it every cycle, before refill.
R-05 quota escalation: if PRODUCTIVE/NOOP < 0.2 over 25 cycles,
     double img_free_day and video_day for 24h, log it.
R-06 atomic lock: acquire = write loop.lock{run_id,ts} ->
     commit -> push -> pull -> re-read. If run_id != mine:
     someone else won, exit 0. Push is the mutex.
R-07 generate.yml: idempotent dep step
     `command -v ffmpeg || sudo apt-get install -y ffmpeg`
R-08 self-dispatch uses ${{ secrets.GITHUB_TOKEN }} with
     actions:write. Documented exception. PAT becomes optional.
R-09 no-cmd items MUST append to BLOCKERS.md. Verify it fired
     for T-0010..16; if not, fix and re-append.

## 2. NOW ACTIVATE v4 (immune system)
Fold in, as given:
  - GitHub Issues command channel (label: command) at top priority
  - HEALTH.md every 25 cycles, PRODUCTIVE vs NOOP
  - deadman: HEARTBEAT gap > 60 min -> open a "blocked" issue
  - anti-thrash: same item 3x same reason -> stop, issue, move on
  - anti-drift: every 50 cycles re-read docs/SPEC-v2.md, v3.md,
    v3.1.md; write state/DRIFT.md
  - self-termination: only after 100 clean cycles with no work

## 3. FREEZE SPEC
Commit docs/SPEC-v2.md, v3.md, v3.1.md verbatim. Canon.

## 4. ORDER OF WORK
R-01..R-09 as backlog items, top of queue, ahead of quotas.
Then resume normal cycles. Then re-check HEALTH is "healthy".

## 5. REPORT
Cycle report, one line. No summary.
```

Mail.tm credential line (redacted): a user-provided mailbox
`demetrisvariable@maxxspace.com` was supplied for onboarding use — password
held in Actions secret MAIL_PASS + git-ignored config/mail_secret.json.

## Implementation map (decisions D36–D44)

- D36 = the order's "D30": three-tier image delivery (site: jsDelivr →
  /content/... same-origin → raw.gh, browser onerror chain + artifact-side
  site/content sync; remote: jsDelivr → raw.gh at send time).
- D37: commit_and_push(msg, throttle) is the single shared path; the 400/day
  cap lives inside it (R-02). workflow_commit delegates (D32 rationale kept).
- D38: R-05 escalation state (state/quota_boost.json) — doubles
  img_free_day/video_day 24h when PRODUCTIVE/NOOP < 0.2 over 25 cycles.
- D39: R-06 push-as-mutex (acquire_lock: write → commit → push → pull →
  re-read).
- D40: §0 — cli_guard exits 1 with the traceback tail surfaced into the item
  note; workflow steps use `|| true` (green job, honest rc, logged errors).
- D41: R-04 onboard_check flips pending → ready when creds appear.
- D42: v4 immune system active.
- D43: user-provided mail.tm account adopted; password never committed.
- D44: this freeze.
