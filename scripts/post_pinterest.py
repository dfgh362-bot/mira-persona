"""Post to Pinterest via the BROWSER LANE (v3.5 sec.1) — Playwright + storageState.

The old API poster (PINTEREST_TOKEN / PINTEREST_BOARD_ID) is DISABLED by
v3.5: no double posting. Cookies come from the COOKIES_PINTEREST vault
secret; the flow activates the moment they land.

CLI: python scripts/post_pinterest.py (thin wrapper -> scripts/browserpost.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util


@util.cli_guard
def main(argv):
    import browserpost
    ok = browserpost.run_platform("pinterest")
    if not ok:
        print("pinterest: browser-lane run did not post (see log)")


if __name__ == "__main__":
    main(sys.argv[1:])
