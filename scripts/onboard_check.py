"""MIRA v3.1 R-04 + v3.2 sec.5/6 — onboarding watch + first post ceremony.

Runs every cycle, BEFORE refill:

- for each tier-1 platform with status "pending": if ALL canonical env names
  (v3.2 sec.5 contract) are present — from the environment (Actions
  secrets, incl. those a WIRE issue uploaded) OR the config/accounts.json
  creds block — flip status to "ready" and insert a top backlog item
  "wire <platform> + first post".
- v3.2: platforms set "ready" by a WIRE issue (no pending transition) get
  the same top item next cycle — onboard_check picks them up.
- the item's cmd runs the platform's post script TWICE: pinned disclosure
  FIRST (verbatim), then the oldest unposted item (sec.6 ceremony). Once
  both are live, their URLs are commented on the wire issue (if any).
- still-pending platforms are surfaced in BLOCKERS.md with the EXACT
  expected env names, so the human cannot guess wrong.

Name contract (canonical env names, exact — v3.2 sec.5; v3.5 sec.1/2
lane-aware: browser platforms take the COOKIES_<PLATFORM> vault secret):
  telegram  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  bluesky   BSKY_HANDLE, BSKY_APP_PASSWORD
  mastodon  MASTODON_INSTANCE, MASTODON_TOKEN
  reddit    COOKIES_REDDIT                  (browser lane)
  x         COOKIES_X                        (browser lane)
  pinterest COOKIES_PINTEREST                (browser lane)
  fanvue    COOKIES_FANVUE                   (browser lane, tier 3)
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

# v3.2 sec.5 — canonical env names, exact (v3.5: lane-aware)
ENV_NAMES = {
    "telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
    "bluesky": ("BSKY_HANDLE", "BSKY_APP_PASSWORD"),
    "mastodon": ("MASTODON_INSTANCE", "MASTODON_TOKEN"),
    "reddit": ("COOKIES_REDDIT",),
    "x": ("COOKIES_X",),
    "pinterest": ("COOKIES_PINTEREST",),
    "fanvue": ("COOKIES_FANVUE",),
}

ENV_TO_ACC = {
    "BSKY_HANDLE": "handle", "BSKY_APP_PASSWORD": "app_password",
    "TELEGRAM_BOT_TOKEN": "bot_token", "TELEGRAM_CHAT_ID": "chat_id",
    "MASTODON_INSTANCE": "instance", "MASTODON_TOKEN": "token",
    "X_BEARER_TOKEN": "bearer_token",
    "PINTEREST_TOKEN": "token", "PINTEREST_BOARD_ID": "board_id",
    "FANVUE_EMAIL": "email", "FANVUE_PASSWORD": "password",
    # v3.5 sec.2: cookie vault marker (set by WIRE COOKIE=)
    "COOKIES_X": "cookies", "COOKIES_REDDIT": "cookies",
    "COOKIES_PINTEREST": "cookies", "COOKIES_FANVUE": "cookies",
    "COOKIES_INSTAGRAM": "cookies", "COOKIES_TIKTOK": "cookies",
}


def eval_platform(name, acc, env):
    """v3.2 sec.5: EVERY canonical name must resolve — from env (Actions
    secrets / WIRE upload) OR the config/accounts.json creds block.
    Pure check — selftest exercises this (r04, v32)."""
    need = ENV_NAMES.get(name, ())
    acc = acc or {}
    for key in need:
        if not (env.get(key) or acc.get(ENV_TO_ACC.get(key, key.lower()))):
            return False
    return bool(need)


def _wire_item_action(name):
    return "wire %s + first post" % name


def _introduced(name):
    """platform already went through the ceremony (pinned disclosure live)."""
    return util.has_pinned(util.load_posted(), name)


def _queue_wire(name):
    """insert the ceremony item at the TOP — ahead of quota items (sec.6):
    cmd runs the post script twice: pinned disclosure FIRST, then the
    oldest unposted item. Requeues after a failed attempt (marker ~),
    capped at 5 total attempts; post.yml remains the steady drip."""
    import backlog  # lazy: backlog imports onboard_check at module scope of one()
    items = backlog.parse_items()
    action = _wire_item_action(name)
    if any(i["marker"] == " " and i["action"] == action for i in items):
        return                                  # already queued
    if len([i for i in items if i["action"] == action and i["marker"] == "~"]) >= 5:
        return                                  # 5 failed attempts — stop requeueing
    cmd = POST_CMD.get(name, "")
    items.insert(0, {"marker": " ", "id": backlog.next_id(items), "action": action,
                     "note": "creds detected / WIRE (v3.2 sec.6 ceremony)",
                     "cmd": ("%s && %s" % (cmd, cmd)) if cmd else ""})
    backlog.write_items(backlog.prune_done(items))


def _comment_wire_urls(name, acc):
    """sec.6: once the ceremony is live, comment the URLs on the wire issue
    (closed issues still accept comments). One-shot per platform.
    Returns True when acc was mutated (caller persists)."""
    num = acc.get("wire_issue")
    if not num or acc.get("wire_commented"):
        return False
    posts = [p for p in util.load_posted().get("posts", [])
             if p.get("platform") == name and p.get("url")]
    pinned = next((p for p in posts if p.get("pinned")), None)
    first = next((p for p in posts if not p.get("pinned")), None)
    if not (pinned and first):
        return False   # ceremony incomplete — retry next cycle
    import issues
    body = ("first posts are live (v3.2 sec.6):\n"
            "- pinned disclosure: %s\n- first post: %s\nfunnel continues on "
            "the post.yml schedule + funnel-first escalation." % (pinned["url"], first["url"]))
    issues.comment(num, body)
    acc["wire_commented"] = True
    util.log_event("wire_urls_commented", platform=name, issue=num)
    return True


def _blocker_line(name):
    return ("WIRE %s: onboarding needs human — secrets expected: %s "
            "(or body lines KEY=value in a 'WIRE %s' issue, label: command); "
            "2-minute steps in docs/SIGNUP.md"
            % (name, ", ".join(ENV_NAMES.get(name, ())), name))


def run():
    cfg = util.load_config("accounts.json")
    platforms = cfg.get("platforms", {})
    flipped = []
    changed = False
    # tier-1: pending -> ready on creds; queue the ceremony
    for name in PENDING_PLATFORMS:
        acc = platforms.get(name) or {}
        if acc.get("status") == "pending" and eval_platform(name, acc, os.environ):
            acc["status"] = "ready"
            flipped.append(name)
            changed = True
            util.set_platform_status(name, "ready")
            util.remove_blockers("%s onboarding needs human" % name)
        if acc.get("status") == "ready" and not _introduced(name):
            _queue_wire(name)          # covers flip AND WIRE-set ready (sec.1)
        if acc.get("status") == "ready":
            changed = _comment_wire_urls(name, acc) or changed
    # fanvue (tier 3): creds -> ready, no ceremony item (post.yml tier-3 step)
    fv = platforms.get("fanvue") or {}
    if fv.get("status") in ("pending", "manual") and eval_platform("fanvue", fv, os.environ):
        fv["status"] = "ready"
        flipped.append("fanvue")
        changed = True
        util.set_platform_status("fanvue", "ready")
        util.remove_blockers("WIRE fanvue")
        util.log_event("onboard_ready", platform="fanvue", tier=3)
    if changed:
        util.save_json(util.CONFIG / "accounts.json", cfg)
    if flipped:
        for name in flipped:
            if name != "fanvue":
                util.log_event("onboard_ready", platform=name)
    # R-09 aid + v3.2 sec.5: surface still-pending onboarding with the EXACT
    # expected env names in BLOCKERS.md (deduped by prefix)
    for name in PENDING_PLATFORMS:
        acc = platforms.get(name) or {}
        if acc.get("status") == "pending":
            util.append_blocker(_blocker_line(name))
    if (platforms.get("fanvue") or {}).get("status") != "ready":
        util.append_blocker(_blocker_line("fanvue"))
    # v3.3 sec.1: MAIL_BASE is the single gating secret for email identities
    # — self-heals out of BLOCKERS the moment it resolves
    import emailaddr
    if emailaddr.base():
        util.remove_blockers("MAIL_BASE not set")
    else:
        util.append_blocker(
            "MAIL_BASE not set: store the base gmail address as Actions secret "
            "MAIL_BASE (Settings > Secrets and variables > Actions > New "
            "repository secret) or run 'python scripts/emailaddr.py base <addr>' "
            "locally — plus-addressed identities <base>+mirasolis-<platform>@"
            "gmail.com are derived from it (v3.3 sec.1)")
    return flipped


@util.cli_guard
def main(argv):
    flipped = run()
    print("onboard_check: %s" % (", ".join(flipped) if flipped else "no platforms became ready"))


if __name__ == "__main__":
    main(sys.argv[1:])
