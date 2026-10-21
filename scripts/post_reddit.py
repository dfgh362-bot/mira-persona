"""Post to Reddit (tier 1, script-type OAuth app).

Creds: env REDDIT_CLIENT_ID/SECRET/USERNAME/PASSWORD/SUBREDDIT or config/accounts.json.
First post is the pinned disclosure post (section 9). Dupe check via posted.json.
Image posts are link submissions; media URL follows v3.1 R-03
(jsDelivr -> raw.gh, retried at submit time).

CLI: python scripts/post_reddit.py
"""
import base64
import os
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

PLAT = "reddit"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"


def get_token(client_id, secret, username, password):
    basic = base64.b64encode(("%s:%s" % (client_id, secret)).encode()).decode()
    form = urllib.parse.urlencode({
        "grant_type": "password",
        "username": username,
        "password": password,
    }).encode()
    raw = util.http_raw("POST", TOKEN_URL, body=form, headers={
        "Authorization": "Basic " + basic,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": util.UA,
    })
    import json
    return json.loads(raw)["access_token"]


@util.cli_guard
def main(argv):
    acc = util.load_config("accounts.json").get("platforms", {}).get(PLAT, {})
    client_id = os.environ.get("REDDIT_CLIENT_ID") or acc.get("client_id")
    secret = os.environ.get("REDDIT_SECRET") or acc.get("secret")
    username = os.environ.get("REDDIT_USERNAME") or acc.get("username")
    password = os.environ.get("REDDIT_PASSWORD") or acc.get("password")
    subreddit = os.environ.get("REDDIT_SUBREDDIT") or acc.get("subreddit")
    if not all([client_id, secret, username, password, subreddit]):
        util.set_platform_status(PLAT, "manual")
        util.log_event("post_skipped", platform=PLAT, reason="missing credentials")
        print("reddit: missing credentials -> status manual")
        return

    queue = util.load_queue()
    posted = util.load_posted()
    disclosure = util.load_config("platforms.json").get("disclosure", {})

    try:
        token = get_token(client_id, secret, username, password)
        auth = {"Authorization": "Bearer " + token, "User-Agent": util.UA}

        def submit(form):
            form = urllib.parse.urlencode(form).encode()
            return util.http_raw("POST", API + "/api/submit", body=form, headers={
                **auth, "Content-Type": "application/x-www-form-urlencoded"})

        if not util.has_pinned(posted, PLAT):
            submit({"sr": subreddit, "kind": "self", "title": "about this account",
                    "text": disclosure["pinned_post"], "api_type": "json", "resubmit": "true"})
            util.record_post(None, PLAT, None, pinned=True, item_id="pinned")
            print("reddit: pinned disclosure posted (pin manually in mod view)")
            return

        item = util.pick_due_item(queue, "free")
        if not item:
            util.log_event("post_skipped", platform=PLAT, reason="no due item")
            print("reddit: no due item")
            return
        if util.already_posted(posted, item["id"], PLAT):
            print("reddit: dupe blocked")
            return

        submitted = False
        for url in util.remote_media_candidates(item):
            try:
                submit({"sr": subreddit, "kind": "link",
                        "url": url,
                        "title": item["caption"], "api_type": "json", "resubmit": "true"})
                submitted = True
                break
            except Exception as e:
                util.log_event("media_fallback", platform=PLAT,
                               failed_url=url[:120], error=repr(e)[:120])
        if not submitted:
            raise RuntimeError("all media URLs rejected")
        util.record_post(item, PLAT)
        util.mark_posted(item)
        print("reddit: posted %s to r/%s" % (item["id"], subreddit))
    except Exception as e:
        util.log_event("post_failed", platform=PLAT, error=repr(e))
        if "HTTP 40" in str(e) or "HTTP 43" in str(e):
            util.set_platform_status(PLAT, "manual")
        print("reddit: failed %r" % e)


if __name__ == "__main__":
    main(sys.argv[1:])
