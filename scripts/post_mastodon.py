"""Post to Mastodon (tier 1).

Creds: env MASTODON_INSTANCE / MASTODON_TOKEN or config/accounts.json.
First post is the pinned disclosure post (section 9). Dupe check via posted.json.

CLI: python scripts/post_mastodon.py
"""
import io
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

PLAT = "mastodon"


def multipart(fields, file_field, file_bytes, filename):
    boundary = "----mira" + uuid.uuid4().hex
    body = io.BytesIO()
    for k, v in fields.items():
        body.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                    % (boundary, k, v)).encode())
    body.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                "Content-Type: image/jpeg\r\n\r\n" % (boundary, file_field, filename)).encode())
    body.write(file_bytes)
    body.write(("\r\n--%s--\r\n" % boundary).encode())
    return body.getvalue(), "multipart/form-data; boundary=" + boundary


@util.cli_guard
def main(argv):
    acc = util.load_config("accounts.json").get("platforms", {}).get(PLAT, {})
    instance = (os.environ.get("MASTODON_INSTANCE") or acc.get("instance")
                or "https://mastodon.social").rstrip("/")
    token = os.environ.get("MASTODON_TOKEN") or acc.get("token")
    if not token:
        util.set_platform_status(PLAT, "manual")
        util.log_event("post_skipped", platform=PLAT, reason="missing credentials")
        print("mastodon: missing credentials -> status manual")
        return

    queue = util.load_queue()
    posted = util.load_posted()
    disclosure = util.load_config("platforms.json").get("disclosure", {})
    auth = {"Authorization": "Bearer " + token}

    try:
        if not util.has_pinned(posted, PLAT):
            resp = util.http_json("POST", instance + "/api/v1/statuses",
                                  {"status": disclosure["pinned_post"], "visibility": "public"},
                                  headers=auth)
            util.record_post(None, PLAT, resp.get("url"), pinned=True, item_id="pinned")
            print("mastodon: pinned disclosure posted -> %s" % resp.get("url"))
            return

        item = util.pick_due_item(queue, "free")
        if not item:
            util.log_event("post_skipped", platform=PLAT, reason="no due item")
            print("mastodon: no due item")
            return
        if util.already_posted(posted, item["id"], PLAT):
            print("mastodon: dupe blocked")
            return

        with open(util.ROOT / item["file"], "rb") as f:
            blob = f.read()
        body, ctype = multipart({"description": "ai-generated image of the mira solis persona"},
                                 "file", blob, "mira.jpg")
        raw = util.http_raw("POST", instance + "/api/v1/media", body=body,
                            headers={**auth, "Content-Type": ctype})
        import json as _json
        media_id = _json.loads(raw)["id"]
        resp = util.http_json("POST", instance + "/api/v1/statuses",
                              {"status": item["caption"], "media_ids": [media_id],
                               "visibility": "public"},
                              headers=auth)
        util.record_post(item, PLAT, resp.get("url"))
        util.mark_posted(item)
        print("mastodon: posted %s -> %s" % (item["id"], resp.get("url")))
    except Exception as e:
        util.log_event("post_failed", platform=PLAT, error=repr(e))
        if "HTTP 40" in str(e):
            util.set_platform_status(PLAT, "manual")
        print("mastodon: failed %r" % e)


if __name__ == "__main__":
    main(sys.argv[1:])
