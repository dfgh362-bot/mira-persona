# ============================================================
# BUILD ORDER v3.3 — "MIRA" — EMAIL REALITY + CAPTCHA BUDGET
# ============================================================
# v3.2 governs. v3.3 corrects one false premise and adds one hard rule.

## 1. KILL THE TEMP-EMAIL PREMISE
v2 §4 says "every account uses a mail.tm address". Now false.
New rule: real email, plus-addressed:
  <base>+<persona>@gmail.com             -> persona general
  <base>+<persona>-<platform>@gmail.com  -> per platform
Store base in config/email.json (gitignored) AND secret MAIL_BASE.
mail.tm demoted to throwaway/secondary only.
Do NOT rewrite docs/SPEC-v2.md. Append an ERRATA block to it instead.
Log as decision D46.

## 2. CAPTCHA BUDGET — hard rule, no judgment
  attempt 1: programmatic
  attempt 2: fresh session, programmatic
  after 2 failures: STOP. Append BLOCKERS.md with the exact URL,
    the wall type (captcha|phone|email|queue), and the 2-minute
    human step. Never attempt a third chain.
  if the wall is NOT a captcha (phone/email/queue): skip the captcha
    entirely, go straight to BLOCKERS.
Log every wall to state/walls.jsonl {platform, wall_type, attempts, ts}.

## 3. WALLS LEDGER — the human's dashboard
state/walls.jsonl, one line per platform per wall.
HANDOFF.md must surface exactly one line:
  "N platforms blocked | cheapest human unblock: <platform> (<est> min) -> <url>"
So the human always sees the single cheapest next action, never a wall of text.

## 4. docs/SIGNUP.md — the human's two minutes
Per platform: exact URL, exact fields, exact 2-minute human step,
exact WIRE issue to open afterwards. Ordered cheapest-first:
  telegram (60s, no email/phone/captcha) -> mastodon -> reddit ->
  x -> pinterest -> fanvue
bluesky marked: NEEDS PHONE, deferred.
Every entry ends with a copy-paste WIRE block.

## 5. WIRE gains EMAIL=
WIRE <platform> EMAIL=<addr> sets the account email field and resumes
the confirmation flow: poll for the link, follow it, then continue
to the pinned-disclosure first post.

## 6. REPORT
Cycle report, one line. No summary.
