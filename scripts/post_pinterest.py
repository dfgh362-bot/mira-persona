"""Post to Pinterest (tier 1, API v5).

Creds: env PINTEREST_TOKEN / PINTEREST_BOARD_ID or config/accounts.json.
Pin creation uses the jsDelivr CDN URL as image source (repo must be pushed).
First post is the pinned disclosure pin (section 9). Dupe check via posted.json.

CLI: python scripts/post_pinterest.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

PLAT = "pinterest"
API = "https://api.pinterest.com/v5"


@util.cli_guard
def main(argv):
    acc = util.load_config("accounts.json").get("platforms", {}).get(PLAT, {})
    token = os.environ.get("PINTEREST_TOKEN") or acc.get("token")
    board_id = os.environ.get("PINTEREST_BOARD_ID") or acc.get("board_id")
    if not (token and board_id):
        util.set_platform_status(PLAT, "manual")
        util.log_event("post_skipped", platform=PLAT, reason="missing credentials")
        print("pinterest: missing credentials -> status manual")
        return

    queue = util.load_queue()
    posted = util.load_posted()
    disclosure = util.load_config("platforms.json").get("disclosure", {})
    auth = {"Authorization": "Bearer " + token}

    def pin(title, desc, image_url):
        return util.http_json("POST", API + "/pins", {
            "board_id": board_id,
            "title": title[:100],
            "description": desc[:500],
            "media_source": {"source_type": "image_url", "url": image_url},
        }, headers=auth)

    try:
        if not util.has_pinned(posted, PLAT):
            resp = pin("about this account", disclosure["pinned_post"],
                       util.jsdelivr("content/free/2026-10-21/mira_free_20261021_001_582427.jpg"))
            util.record_post(None, PLAT, resp.get("id"), pinned=True, item_id="pinned")
            print("pinterest: pinned disclosure pin created")
            return

        item = util.pick_due_item(queue, "free")
        if not item:
            util.log_event("post_skipped", platform=PLAT, reason="no due item")
            print("pinterest: no due item")
            return
        if util.already_posted(posted, item["id"], PLAT):
            print("pinterest: dupe blocked")
            return

        resp = pin("mira solis", "%s (ai-generated)" % item["caption"],
                   item.get("cdn") or util.jsdelivr(item["file"]))
        util.record_post(item, PLAT, resp.get("id"))
        util.mark_posted(item)
        print("pinterest: posted %s -> pin %s" % (item["id"], resp.get("id")))
    except Exception as e:
        util.log_event("post_failed", platform=PLAT, error=repr(e))
        if "HTTP 40" in str(e):
            util.set_platform_status(PLAT, "manual")
        print("pinterest: failed %r" % e)


if __name__ == "__main__":
    main(sys.argv[1:])
