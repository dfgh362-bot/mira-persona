"""v3.5 sec.3 — cookie health, every cycle BEFORE any posting.

For each browser-lane platform with cookies in the vault: hit a cheap
authenticated page with the stored session. logged-out / redirected to
login -> status "cookie_expired", ONE "blocked" issue naming the platform
and exactly what to send, skip this cycle. Never fail silently.
Every check lands in state/cookies.json {platform: {ok, ts}}.

Real checks are throttled to one per 30 min per platform (posting paths
always run their own inline gate inside browserpost.run_platform — this
CLI is the pre-posting sweep post.yml runs on its schedule).

CLI:
  python scripts/cookie_health.py [--force]     # all browser platforms
  python scripts/cookie_health.py --platform x [--force]
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

THROTTLE_S = 1800


def _age_s(platform):
    """seconds since the last ledger entry for this platform."""
    import browserpost
    d = util.load_json(browserpost.COOKIES_LEDGER, {}).get(platform) or {}
    try:
        t = datetime.strptime(d.get("ts", ""), "%Y-%m-%dT%H:%M:%SZ"
                              ).replace(tzinfo=timezone.utc)
        return (util.utcnow() - t).total_seconds()
    except Exception:
        return float("inf")


def _ledger_ok(platform):
    import browserpost
    d = util.load_json(browserpost.COOKIES_LEDGER, {}).get(platform) or {}
    return bool(d.get("ok"))


@util.cli_guard
def main(argv):
    import browserpost
    force = "--force" in argv
    targets = []
    if "--platform" in argv:
        i = argv.index("--platform")
        if i + 1 < len(argv):
            targets = [argv[i + 1]]
    else:
        targets = list(browserpost.TIER1_BROWSER) + ["fanvue"]
    for p in targets:
        if not browserpost.vault_read(p):
            continue                       # nothing stored — nothing to check
        if not force and _ledger_ok(p) and _age_s(p) < THROTTLE_S:
            print("%s: cookie ledger fresh+ok (throttled)" % p)
            continue
        browserpost.run_platform(p, check_only=True)
    print("cookie health sweep done (ledger: state/cookies.json)")


if __name__ == "__main__":
    main(sys.argv[1:])
