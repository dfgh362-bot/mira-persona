"""MIRA v3.3 sec.2+3 — captcha budget policy + the walls ledger.

CAPTCHA BUDGET (hard rule, no judgment):
  attempt 1: programmatic
  attempt 2: fresh session, programmatic
  after 2 failures: STOP. Append BLOCKERS.md with the exact URL, the wall
  type (captcha|phone|email|queue) and the 2-minute human step. Never
  attempt a third chain.
  If the wall is NOT a captcha (phone/email/queue): skip the captcha
  entirely, go straight to BLOCKERS.

WALLS LEDGER (the human's dashboard):
  state/walls.jsonl — one line per platform per wall:
    {"platform": ..., "wall_type": ..., "attempts": ..., "url": ...,
     "human_step": ..., "est_min": ..., "ts": ...}
  HANDOFF.md surfaces exactly ONE line (backlog.rewrite_handoff):
    "N platforms blocked | cheapest human unblock: <platform> (<est> min) -> <url>"
  so the human always sees the single cheapest next action, never a wall
  of text.

CLI: python scripts/walls.py summary    # print the HANDOFF line
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

WALL_TYPES = ("captcha", "phone", "email", "queue")
MAX_CHAIN_ATTEMPTS = 2          # the third chain is FORBIDDEN (v3.3 §2)
WALLS = util.STATE / "walls.jsonl"
REPEAT_HOURS = 6.0               # same (platform, wall_type) re-logged at most 6-hourly

# v3.3 §4 — signup order cheapest-first; (url, est minutes for the human)
SIGNUP = {
    "telegram":  ("https://t.me/BotFather", 1),
    "mastodon":  ("https://mastodon.social/auth/sign_up", 2),
    "reddit":    ("https://www.reddit.com/register", 4),
    "x":         ("https://developer.x.com", 10),
    "pinterest": ("https://www.pinterest.com", 5),
    "fanvue":    ("https://fanvue.com", 8),
    "bluesky":   ("https://bsky.app/signup", 3),   # NEEDS PHONE, deferred
}
SIGNUP_ORDER = ("telegram", "mastodon", "reddit", "x", "pinterest", "fanvue", "bluesky")


def record(platform, wall_type, attempts, url=None, human_step=None, est_min=None):
    """log a wall: walls.jsonl line + BLOCKERS.md entry (deduped). Never raises.
    v3.2 sec.2: the caller stops after MAX_CHAIN_ATTEMPTS — this function is
    the terminal action of a failed chain, not a retry trigger."""
    platform, wall_type = (platform or "").lower(), (wall_type or "").lower()
    if wall_type not in WALL_TYPES:
        util.log_event("wall_bad_type", platform=platform, wall_type=wall_type)
        return None
    url = url or (SIGNUP.get(platform) or ("", 5))[0]
    est = est_min if est_min is not None else (SIGNUP.get(platform) or ("", 5))[1]
    line = {
        "platform": platform,
        "wall_type": wall_type,
        "attempts": int(attempts),
        "url": url,
        "human_step": human_step or "see docs/SIGNUP.md for the 2-minute step",
        "est_min": int(est),
        "ts": util.ts(),
    }
    recent = _recent(platform, wall_type)
    if not recent:                       # rate-limit the ledger itself
        with open(WALLS, "a", encoding="utf-8") as f:
            f.write(util.json_dumps_line(line))
    util.append_blocker(
        "WALL %s: %s at %s — human step: %s (cheapest-first: docs/SIGNUP.md)"
        % (platform, wall_type, url, line["human_step"]))
    util.log_event("wall", platform=platform, wall_type=wall_type,
                   attempts=line["attempts"], url=url)
    return line


def _recent(platform, wall_type):
    """last wall line for this (platform, wall_type) inside REPEAT_HOURS."""
    cut = datetime.now(timezone.utc) - timedelta(hours=REPEAT_HOURS)
    for w in reversed(load()):
        if w.get("platform") == platform and w.get("wall_type") == wall_type:
            try:
                t = datetime.strptime(w.get("ts") or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if t > cut:
                    return w
            except Exception:
                pass
    return None


def load():
    out = []
    if WALLS.exists():
        for ln in WALLS.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
    return out


def latest_wall(platform):
    for w in reversed(load()):
        if w.get("platform") == platform:
            return w
    return None


def resolve(platform):
    """(url, est_min) for a blocked platform — latest wall overrides the
    SIGNUP defaults, so HANDOFF always points at the real next step."""
    url, est = SIGNUP.get(platform, ("", 5))
    w = latest_wall(platform)
    if w:
        url = w.get("url") or url
        if w.get("est_min") is not None:
            est = int(w["est_min"])
    return url, int(est)


def _tracked():
    import onboard_check                      # lazy: avoid import cycles
    return list(onboard_check.ENV_NAMES)      # the 7-platform funnel


def blocked():
    """tracked platforms whose accounts.json status is not 'ready' —
    tiktok/instagram (tier 2, manual by ToS) are not 'blocked', they are
    parked, so they never appear here."""
    accs = util.load_config("accounts.json").get("platforms", {})
    return [p for p in _tracked() if (accs.get(p) or {}).get("status") != "ready"]


def summary_line():
    """the single HANDOFF line (v3.3 §3). exact format, no trailing text."""
    blk = blocked()
    if not blk:
        return "0 platforms blocked | cheapest human unblock: (none) — funnel open"
    rows = []
    for p in blk:
        url, est = resolve(p)
        pri = SIGNUP_ORDER.index(p) if p in SIGNUP_ORDER else len(SIGNUP_ORDER)
        rows.append((est, pri, p, url))
    est, _pri, plat, url = min(rows)          # cheapest; tie -> signup order
    return "%d platforms blocked | cheapest human unblock: %s (%d min) -> %s" % (
        len(blk), plat, est, url)


@util.cli_guard
def main(argv):
    if argv and argv[0] == "summary":
        print(summary_line())
        return
    print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
