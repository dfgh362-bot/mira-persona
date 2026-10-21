# SPEC-v3 — MIRA loop order (canon, frozen)

> Provenance: reconstructed from the ratified v3 build order as issued (see
> D44). v3 governs the loop protocol; v3.1 repairs it and activates v4.

## 1. Remote bring-up (first cycles)

- First step: PAT scope check (needs `repo`, `workflow`). Missing `workflow`
  → note in state/BLOCKERS.md, do not block.
- API tasks: create public repo mira-persona → push main → enable Pages
  (build_type: workflow) → set topics → verify workflows listed → write
  config/gh.json with the derived GH_USER (no token inside).

## 2. Loop protocol — there is no "done", only cycles

Every cycle: read state/HANDOFF.md → execute the top unchecked item of
state/BACKLOG.md → commit → mark `[x]` + sha → if unchecked items < 5,
`backlog.py --refill` → rewrite HANDOFF.md → continue.

HANDOFF format (fixed sections):
`## CURRENT` / `## NEXT ACTION` / `## BLOCKERS` / `## LAST COMMIT` / `## CYCLE`

## 3. New files

- state/: HANDOFF.md, BACKLOG.md, loop.lock, STOP, PAUSE, BLOCKERS.md,
  HEARTBEAT.
- scripts/backlog.py — `--one` / `--refill`; refill sources (never empty):
  content quotas → posting → pending accounts → analytics tuning →
  scenes+5/captions+5 → self-repair of log.jsonl failures → self-improvement.
- scripts/brain.py — free Pollinations picks the next action, writes
  state/NEXT_ACTION (fallback: top backlog cmd).
- .github/workflows/loop.yml — `*/5` cron + self-dispatch dual heartbeat,
  4-minute loop.lock cooldown, contents:write + actions:write.
- run_forever.sh — local watchdog.

## 4. Guardrails

- Max 1 commit / 2 minutes; 400 commits/day; log.jsonl > 5 MB → rotate;
  repo > 900 MB → prune; 5000 req/hr budget.
- state/STOP = terminate. state/PAUSE = idle spin (heartbeat continues).
- Cycle report one line: `| cycle | task | result | commit | next |`.
  No final summary — the loop never finishes.

## 5. Bring-up decisions (D20–D35)

Self-dispatch via GITHUB_TOKEN + actions:write (D20); loop throttle 1 commit/
2 min inside backlog.py (D21); early-abort after 2 total upstream failures
(D22); run_forever drives the deterministic agent (D23); item lines carry
`cmd:` (D24); brain POST + GET fallback (D25); initial order video/captions
ahead of images (D26); `[~]` on upstream block (D27); 3x retries inside
scripts (D28); one commit per cycle (D29); workflow commits via
backlog.py --commit with rebase recovery (D31); workflow commits skip the
pace-sleep (D32); site brace-bug root cause + seed ids (D33); ffmpeg
apt-install + quota guards (D34); jsDelivr primary with raw.github browser
fallback (D35).
