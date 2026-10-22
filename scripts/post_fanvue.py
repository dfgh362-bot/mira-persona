"""Post paid teasers to Fanvue via the BROWSER LANE (v3.5 sec.1/8).

Fanvue has no public API — browser only, this is the revenue endpoint.
Cookies come from the COOKIES_FANVUE vault secret (storageState): login
happens once (v3.5 sec.8 live session or WIRE fanvue COOKIE=<base64>),
then the session persists and rotates back into the vault. The old
FANVUE_EMAIL/PASSWORD login bootstrap is retired (no double paths).

The compose flow (login -> pricing -> pinned disclosure -> paid teasers)
is provisioned in scripts/browserpost.py FLOWS when the account lands.

CLI: python scripts/post_fanvue.py  (thin wrapper -> scripts/browserpost.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util


@util.cli_guard
def main(argv):
    import browserpost
    ok = browserpost.run_platform("fanvue")
    if not ok:
        print("fanvue: browser-lane run did not post (see log)")


if __name__ == "__main__":
    main(sys.argv[1:])
