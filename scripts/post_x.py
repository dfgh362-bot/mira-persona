"""Post to X via the BROWSER LANE (v3.5 sec.1/7) — Playwright + storageState.

The old API poster (X_BEARER_TOKEN) is DISABLED by v3.5: browser lane and
API lane never run for the same platform (no double posting). Cookies come
from the COOKIES_X vault secret; posting goes through the compose UI and
every post is verified by reading it back off the profile page (sec.7).

CLI: python scripts/post_x.py        (thin wrapper -> scripts/browserpost.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util


@util.cli_guard
def main(argv):
    import browserpost
    ok = browserpost.run_platform("x")
    if not ok:
        print("x: browser-lane run did not post (see log)")


if __name__ == "__main__":
    main(sys.argv[1:])
