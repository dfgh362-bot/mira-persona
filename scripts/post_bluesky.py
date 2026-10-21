"""Post to Bluesky via AT Protocol XRPC (tier 1).

Creds: env BSKY_HANDLE / BSKY_APP_PASSWORD or config/accounts.json -> platforms.bluesky.
First post on a fresh account is always the pinned disclosure post (section 9).
Duplicate protection: content/posted.json checked before every post.

CLI: python scripts/post_bluesky.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

PLAT = "bluesky"
XRPC = "https://bsky.social/xrpc"


def session(handle, password):
    return util.http_json("POST", XRPC + "/com.atproto.server.createSession",
                          {"identifier": handle, "password": password})


def upload(jwt, image_path):
    with open(image_path, "rb") as f:
        blob = f.read()
    raw = util.http_raw("POST", XRPC + "/com.atproto.repo.uploadBlob", body=blob,
                         headers={"Authorization": "Bearer " + jwt,
                                  "Content-Type": "image/jpeg"})
    return json.loads(raw)["blob"]


def create_record(jwt, did, record):
    return util.http_json("POST", XRPC + "/com.atproto.repo.createRecord",
                          {"repo": did, "collection": "app.bsky.feed.post", "record": record},
                          headers={"Authorization": "Bearer " + jwt})


def post_text(jwt, did, text):
    record = {"$type": "app.bsky.feed.post", "createdAt": util.ts(), "text": text}
    return create_record(jwt, did, record)


def post_image(jwt, did, text, image_path, alt):
    blob = upload(jwt, image_path)
    record = {
        "$type": "app.bsky.feed.post",
        "createdAt": util.ts(),
        "text": text,
        "embed": {"$type": "app.bsky.embed.images",
                  "images": [{"image": blob, "altText": alt[:500]}]},
    }
    return create_record(jwt, did, record)


@util.cli_guard
def main(argv):
    acc = util.load_config("accounts.json").get("platforms", {}).get(PLAT, {})
    handle = os.environ.get("BSKY_HANDLE") or acc.get("handle")
    password = os.environ.get("BSKY_APP_PASSWORD") or acc.get("app_password")
    if not (handle and password):
        util.set_platform_status(PLAT, "manual")
        util.log_event("post_skipped", platform=PLAT, reason="missing credentials")
        print("bluesky: missing credentials -> status manual")
        return

    queue = util.load_queue()
    posted = util.load_posted()
    disclosure = util.load_config("platforms.json").get("disclosure", {})

    try:
        sess = session(handle, password)
        jwt, did = sess["accessJwt"], sess["did"]

        if not util.has_pinned(posted, PLAT):
            resp = post_text(jwt, did, disclosure["pinned_post"])
            rkey = resp["uri"].rpartition("/")[2]
            url = "https://bsky.app/profile/%s/post/%s" % (did, rkey)
            util.record_post(None, PLAT, url, pinned=True, item_id="pinned")
            print("bluesky: pinned disclosure posted -> %s" % url)
            return

        item = util.pick_due_item(queue, "free")
        if not item:
            util.log_event("post_skipped", platform=PLAT, reason="no due item")
            print("bluesky: no due item")
            return
        if util.already_posted(posted, item["id"], PLAT):
            print("bluesky: dupe blocked")
            return

        resp = post_image(jwt, did, item["caption"], util.ROOT / item["file"],
                          "ai-generated image of the mira solis persona")
        rkey = resp["uri"].rpartition("/")[2]
        url = "https://bsky.app/profile/%s/post/%s" % (did, rkey)
        util.record_post(item, PLAT, url)
        util.mark_posted(item)
        print("bluesky: posted %s -> %s" % (item["id"], url))
    except Exception as e:
        util.log_event("post_failed", platform=PLAT, error=repr(e))
        if "HTTP 40" in str(e):
            util.set_platform_status(PLAT, "manual")
        print("bluesky: failed %r" % e)


if __name__ == "__main__":
    main(sys.argv[1:])
