"""MIRA v3.1 R-04 — onboarding watch. Runs every cycle, BEFORE refill.

For each platform with status "pending": if creds are present in env or
config, flip status to "ready" (accounts.json + platforms.json) and insert a
top backlog item "wire <platform> + first post".
Still-pending platforms are surfaced in BLOCKERS.md (deduped) so the human
always sees the onboarding queue without waiting for queue order (R-09 aid).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

PENDING_PLATFORMS = ("bluesky", "telegram", "reddit", "mastodon", "x", "pinterest")

POST_CMD = {
    "bluesky": "python scripts/post_bluesky.py",
    "telegram": "python scripts/post_telegram.py",
    "reddit": "python scripts/post_reddit.py",
    "mastodon": "python scripts/post_mastodon.py",
    "x": "python scripts/post_x.py",
    "pinterest": "python scripts/post_pinterest.py",
}


def _first(*vals):
    for v in vals:
        if v:
            return v
    return None


def eval_platform(name, acc, env):
    """pure readiness check — selftest exercises this (R-04)."""
    e = lambda k: env.get(k)
    if name == "bluesky":
        return bool(_first(e("BSKY_HANDLE"), acc.get("handle"))
                    and _first(e("BSKY_APP_PASSWORD"), acc.get("app_password")))
    if name == "telegram":
        return bool(_first(e("TELEGRAM_BOT_TOKEN"), acc.get("bot_token"))
                    and _first(e("TELEGRAM_CHAT_ID"), acc.get("chat_id")))
    if name == "mastodon":
        return bool(_first(e("MASTODON_TOKEN"), acc.get("token")))
    if name == "reddit":
        return bool(_first(e("REDDIT_CLIENT_ID"), acc.get("client_id"))
                    and _first(e("REDDIT_SECRET"), acc.get("secret")))
    if name == "x":
        return bool(_first(e("X_BEARER_TOKEN"), acc.get("bearer_token")))
    if name == "pinterest":
        return bool(_first(e("PINTEREST_TOKEN"), acc.get("token"))
                    and _first(e("PINTEREST_BOARD_ID"), acc.get("board_id")))
    return False


def _queue_wire(name):
    import backlog  # lazy: backlog imports onboard_check at module scope of one()
    items = backlog.parse_items()
    action = "wire %s + first post" % name
    if any(i["action"] == action for i in items):
        return
    items.insert(0, {"marker": " ", "id": backlog.next_id(items), "action": action,
                     "note": "creds detected (R-04)", "cmd": POST_CMD.get(name, "")})
    backlog.write_items(backlog.prune_done(items))


def run():
    cfg = util.load_config("accounts.json")
    platforms = cfg.get("platforms", {})
    flipped = []
    for name in PENDING_PLATFORMS:
        acc = platforms.get(name) or {}
        if acc.get("status") == "pending" and eval_platform(name, acc, os.environ):
            acc["status"] = "ready"
            flipped.append(name)
            util.set_platform_status(name, "ready")
    if flipped:
        util.save_json(util.CONFIG / "accounts.json", cfg)
        for name in flipped:
            _queue_wire(name)
            util.log_event("onboard_ready", platform=name)
    # R-09 aid: surface still-pending onboarding in BLOCKERS.md (deduped)
    for name in PENDING_PLATFORMS:
        acc = platforms.get(name) or {}
        if acc.get("status") == "pending":
            util.append_blocker("%s onboarding needs human: create account, "
                                "bio + pinned, creds to Actions Secrets" % name)
    return flipped


@util.cli_guard
def main(argv):
    flipped = run()
    print("onboard_check: %s" % (", ".join(flipped) if flipped else "no platforms became ready"))


if __name__ == "__main__":
    main(sys.argv[1:])
