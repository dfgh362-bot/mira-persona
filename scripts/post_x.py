"""Post to X (tier 1, API v2 free tier).

Creds: env X_BEARER_TOKEN or config/accounts.json.
Free tier posts are text + jsDelivr image link (media upload needs OAuth 1.0a,
logged as limitation). First post is the pinned disclosure post (section 9).

CLI: python scripts/post_x.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

PLAT = "x"


@util.cli_guard
def main(argv):
    acc = util.load_config("accounts.json").get("platforms", {}).get(PLAT, {})
    token = os.environ.get("X_BEARER_TOKEN") or acc.get("bearer_token")
    if not token:
        util.set_platform_status(PLAT, "manual")
        util.log_event("post_skipped", platform=PLAT, reason="missing credentials")
        print("x: missing credentials -> status manual")
        return

    queue = util.load_queue()
    posted = util.load_posted()
    disclosure = util.load_config("platforms.json").get("disclosure", {})
    auth = {"Authorization": "Bearer " + token}

    def tweet(text):
        return util.http_json("POST", "https://api.x.com/2/tweets", {"text": text}, headers=auth)

    try:
        if not util.has_pinned(posted, PLAT):
            resp = tweet(disclosure["pinned_post"])
            tid = resp.get("data", {}).get("id")
            util.record_post(None, PLAT, "https://x.com/i/web/status/%s" % tid,
                             pinned=True, item_id="pinned")
            print("x: pinned disclosure posted (pin manually in app)")
            return

        item = util.pick_due_item(queue, "free")
        if not item:
            util.log_event("post_skipped", platform=PLAT, reason="no due item")
            print("x: no due item")
            return
        if util.already_posted(posted, item["id"], PLAT):
            print("x: dupe blocked")
            return

        text = "%s %s" % (item["caption"], item.get("cdn") or util.jsdelivr(item["file"]))
        resp = tweet(text[:280])
        tid = resp.get("data", {}).get("id")
        util.record_post(item, PLAT, "https://x.com/i/web/status/%s" % tid)
        util.mark_posted(item)
        print("x: posted %s -> %s" % (item["id"], tid))
    except Exception as e:
        util.log_event("post_failed", platform=PLAT, error=repr(e))
        if "HTTP 40" in str(e):
            util.set_platform_status(PLAT, "manual")
        print("x: failed %r" % e)


if __name__ == "__main__":
    main(sys.argv[1:])
