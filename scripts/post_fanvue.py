"""Post paid teasers to Fanvue (tier 3 — Playwright inside Actions).

Creds: env FANVUE_EMAIL / FANVUE_PASSWORD or config/accounts.json.
Fanvue has no public posting API: this drives the web UI best-effort with
Playwright. Any failure -> status "manual" and the operator posts by hand.
Paid-tier items only; disclosure/AI-creator flag set in platform settings (R1).

CLI: python scripts/post_fanvue.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

PLAT = "fanvue"


@util.cli_guard
def main(argv):
    acc = util.load_config("accounts.json").get("platforms", {}).get(PLAT, {})
    email = os.environ.get("FANVUE_EMAIL") or acc.get("email")
    password = os.environ.get("FANVUE_PASSWORD") or acc.get("password")
    if not (email and password):
        util.set_platform_status(PLAT, "manual")
        util.log_event("post_skipped", platform=PLAT, reason="missing credentials")
        print("fanvue: missing credentials -> status manual (tier 3)")
        return

    queue = util.load_queue()
    posted = util.load_posted()
    item = None
    for it in queue.get("items", []):
        if it.get("tier") == "paid" and it.get("status") == "captioned":
            item = it
            break
    if not item:
        util.log_event("post_skipped", platform=PLAT, reason="no due paid item")
        print("fanvue: no due paid item")
        return
    if util.already_posted(posted, item["id"], PLAT):
        print("fanvue: dupe blocked")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        try:
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "playwright"],
                           capture_output=True, timeout=600)
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                           capture_output=True, timeout=900)
            from playwright.sync_api import sync_playwright
        except Exception as e:
            util.set_platform_status(PLAT, "manual")
            util.log_event("post_skipped", platform=PLAT, reason="playwright unavailable: %r" % e)
            print("fanvue: playwright unavailable -> status manual")
            return

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto("https://fanvue.com/login", timeout=60000)
            page.fill("input[type=email]", email)
            page.fill("input[type=password]", password)
            page.click("button[type=submit]")
            page.wait_for_load_state("networkidle", timeout=60000)
            # selectors drift; any miss below falls to manual
            page.goto("https://fanvue.com/post/compose", timeout=60000)
            page.set_input_files("input[type=file]", str(util.ROOT / item["file"]))
            page.fill("[contenteditable], textarea", item["caption"])
            page.click("button:has-text('Post')")
            browser.close()
        util.record_post(item, PLAT)
        util.mark_posted(item)
        print("fanvue: posted %s" % item["id"])
    except Exception as e:
        util.set_platform_status(PLAT, "manual")
        util.log_event("post_failed", platform=PLAT, error=repr(e))
        print("fanvue: failed -> status manual (%r)" % e)


if __name__ == "__main__":
    main(sys.argv[1:])
