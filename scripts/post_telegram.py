"""Post to a Telegram channel via Bot API (tier 1).

Creds: env TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID or config/accounts.json.
First post is the pinned disclosure post (section 9). Dupe check via posted.json.
Image delivery (v3.1 R-03): jsDelivr -> raw.github, tried at send time.

CLI: python scripts/post_telegram.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

PLAT = "telegram"


@util.cli_guard
def main(argv):
    acc = util.load_config("accounts.json").get("platforms", {}).get(PLAT, {})
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or acc.get("bot_token")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or acc.get("chat_id")
    if not (token and chat_id):
        util.set_platform_status(PLAT, "manual")
        util.log_event("post_skipped", platform=PLAT, reason="missing credentials")
        print("telegram: missing credentials -> status manual")
        return

    queue = util.load_queue()
    posted = util.load_posted()
    disclosure = util.load_config("platforms.json").get("disclosure", {})
    base = "https://api.telegram.org/bot%s/" % token

    def api(method, payload):
        return util.http_json("POST", base + method, payload)

    try:
        if not util.has_pinned(posted, PLAT):
            resp = api("sendMessage", {"chat_id": chat_id, "text": disclosure["pinned_post"]})
            url = "https://t.me/%s" % resp.get("result", {}).get("chat", {}).get("username", "")
            util.record_post(None, PLAT, url, pinned=True, item_id="pinned")
            print("telegram: pinned disclosure posted")
            return

        item = util.pick_due_item(queue, "free")
        if not item:
            util.log_event("post_skipped", platform=PLAT, reason="no due item")
            print("telegram: no due item")
            return
        if util.already_posted(posted, item["id"], PLAT):
            print("telegram: dupe blocked")
            return

        resp = None
        last_err = None
        for url in util.remote_media_candidates(item):
            try:
                resp = api("sendPhoto", {
                    "chat_id": chat_id,
                    "photo": url,
                    "caption": item["caption"],
                })
                break
            except Exception as e:
                last_err = e
                util.log_event("media_fallback", platform=PLAT,
                               failed_url=url[:120], error=repr(e)[:120])
        if resp is None:
            raise last_err
        msg = resp.get("result", {}).get("message_id")
        util.record_post(item, PLAT, "tg://mid_%s" % msg)
        util.mark_posted(item)
        print("telegram: posted %s (msg %s)" % (item["id"], msg))
    except Exception as e:
        util.log_event("post_failed", platform=PLAT, error=repr(e))
        if "HTTP 40" in str(e):
            util.set_platform_status(PLAT, "manual")
        print("telegram: failed %r" % e)


if __name__ == "__main__":
    main(sys.argv[1:])
