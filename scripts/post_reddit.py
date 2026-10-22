"""Post to Reddit via the BROWSER LANE (v3.5 sec.1) — Playwright + storageState.

The old script-app API poster (REDDIT_* secrets) is DISABLED by v3.5: no
double posting. Cookies come from the COOKIES_REDDIT vault secret; the flow
activates the moment they land (same skeleton as X: health gate + compose +
verify). Until then this is a quiet skip.

CLI: python scripts/post_reddit.py  (thin wrapper -> scripts/browserpost.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util


@util.cli_guard
def main(argv):
    import browserpost
    ok = browserpost.run_platform("reddit")
    if not ok:
        print("reddit: browser-lane run did not post (see log)")


if __name__ == "__main__":
    main(sys.argv[1:])
