"""Telegram re-point: DM preview -> public channel (one command).

When the funnel starts in the owner's DM (private chat), this switches
TELEGRAM_CHAT_ID to the public channel and resets the telegram pinned
record so the first-post ceremony re-fires there (pinned disclosure +
oldest item), exactly as v3.2 sec.6 requires.

CLI: python scripts/tg_repoint.py <new_chat_id>     # e.g. -1001234567890
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util


def main():
    if len(sys.argv) < 2:
        print("usage: tg_repoint.py <new_chat_id>")
        return
    new_id = sys.argv[1].strip()
    if not new_id.startswith("-100"):
        print("WARNING: a public channel id starts with -100 (got %r) — "
              "continuing anyway" % new_id)
    # 1. update the secret (sealed box upload via the WIRE path)
    import issues
    ok, lines = issues.upload_secrets({"TELEGRAM_CHAT_ID": new_id})
    print("secret TELEGRAM_CHAT_ID:", "ok" if ok else "FAILED")
    for l in lines:
        print(" ", l)
    if not ok:
        return
    # 2. reset the telegram records so the ceremony re-fires on the channel
    posted = util.load_posted()
    before = len(posted.get("posts", []))
    posted["posts"] = [p for p in posted.get("posts", [])
                       if p.get("platform") != "telegram"]
    util.save_posted(posted)
    print("telegram post records reset: %d -> %d"
          % (before, len(posted["posts"])))
    # 3. keep the platform ready so onboard_check re-queues the ceremony
    util.set_platform_status("telegram", "ready")
    cfg = util.load_config("accounts.json")
    acc = cfg.setdefault("platforms", {}).setdefault("telegram", {})
    acc["status"] = "ready"
    acc["chat_id"] = new_id
    acc["repointed_at"] = util.ts()
    util.save_json(util.CONFIG / "accounts.json", cfg)
    util.log_event("tg_repointed", chat_id=new_id)
    print("next cycle: pinned disclosure + first post go to the new channel")


if __name__ == "__main__":
    main()
