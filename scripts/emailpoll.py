"""MIRA v3.3 sec.5 — confirmation-flow poller (WIRE EMAIL=<addr>).

WIRE <platform> EMAIL=<addr> sets the account email field and resumes the
confirmation flow: poll for the link, follow it, then continue to the
pinned-disclosure first post (the ceremony itself fires from onboard_check
once the platform's creds land and status flips ready).

Poll channels, in order:
  1. mail.tm / mail.gw inbox — exact-match address (scripts/mailtm.py)
  2. IMAP — env MAIL_IMAP_HOST + MAIL_IMAP_USER + MAIL_IMAP_PASS
     (e.g. Gmail with an app password; plus-addressed mail is found via
     the TO address, so the base inbox serves every platform identity)
  3. neither configured -> the human clicks the link in their own inbox
     (~1 minute) — recorded as an 'email' wall in state/walls.jsonl and
     surfaced as the cheapest next action in HANDOFF.md

Every link GET is logged; confirmation success sets
platforms.<p>.email_confirmed_at and removes the platform's WALL blocker.

CLI: python scripts/emailpoll.py --poll
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util
import walls

VERIFY_RE = re.compile(r"(verify|confirm|activate|validate|token|email-verification)", re.I)
LINK_RE = re.compile(r"https?://[^\s\"'<>)\]]+")

PLATFORM_DOMAINS = {
    "telegram": ("telegram.org", "t.me"),
    "mastodon": ("mastodon.social", "cleverlibre.org", "mstdn.social",
                 "joinmastodon.org"),
    "reddit": ("reddit.com", "reddithelp.com"),
    "x": ("x.com", "twitter.com"),
    "pinterest": ("pinterest.com",),
    "fanvue": ("fanvue.com",),
    "bluesky": ("bsky.app", "bluesky.social"),
}


def pick_link(links, domains):
    """pure: the ONE confirmation link worth following.
    preference: verify-word + platform domain > platform domain > verify-word."""
    links = [u.rstrip(".,;") for u in links or []]
    dom = [u for u in links if domains and any(d in u for d in domains)]
    ver = [u for u in links if VERIFY_RE.search(u)]
    both = [u for u in dom if u in ver]
    return (both or dom or ver or [None])[0]


def _mailtm_poll(addr, domains):
    """returns (status, detail) or None if the address is not a mailtm one."""
    import mailtm
    acc = next((a for a in mailtm._accounts() if a.get("address") == addr), None)
    if acc is None:
        return None
    for m in mailtm.messages(acc):
        mid = m.get("id") or m.get("@id", "").rpartition("/")[2]
        if not mid:
            continue
        full = mailtm.read_message(acc, mid)
        link = pick_link(mailtm.extract_links(full), domains)
        if link:
            code = util.http_get(link)
            util.log_event("email_confirm_link", channel="mailtm",
                           addr=addr, http=code, link=link[:200])
            if code < 400:
                return "confirmed", "followed %s (HTTP %s)" % (link[:80], code)
            return "failed", "link %s returned HTTP %s" % (link[:80], code)
    return "pending", "no confirmation link in the mail.tm inbox yet"


def _imap_poll(addr, domains):
    """returns (status, detail) or None if IMAP is not configured."""
    host = (os.environ.get("MAIL_IMAP_HOST") or "").strip()
    user = (os.environ.get("MAIL_IMAP_USER") or "").strip()
    pw = (os.environ.get("MAIL_IMAP_PASS") or "").strip()
    if not (host and user and pw):
        return None
    import imaplib
    import email as emaillib
    try:
        m = imaplib.IMAP4_SSL(host, timeout=30)
    except Exception as e:
        return "failed", "imap connect %r" % e
    try:
        m.login(user, pw)
        m.select("INBOX", readonly=True)
        typ, data = m.search(None, "TO", '"%s"' % addr)
        ids = (data[0] or b"").split()[-10:]
        for num in reversed(ids):          # newest first
            typ, msg_data = m.fetch(num, "(RFC822)")
            raw = next((d[1] for d in msg_data if isinstance(d, tuple)), None)
            if not raw:
                continue
            msg = emaillib.message_from_bytes(raw)
            links = []
            for part in msg.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    payload = part.get_payload(decode=True) or b""
                    charset = part.get_content_charset() or "utf-8"
                    links += LINK_RE.findall(payload.decode(charset, errors="replace"))
            link = pick_link(links, domains)
            if link:
                code = util.http_get(link)
                util.log_event("email_confirm_link", channel="imap",
                               addr=addr, http=code, link=link[:200])
                if code < 400:
                    return "confirmed", "followed %s (HTTP %s)" % (link[:80], code)
                return "failed", "link %s returned HTTP %s" % (link[:80], code)
        return "pending", "no confirmation link in the IMAP inbox yet"
    except Exception as e:
        return "failed", "imap %r" % e
    finally:
        try:
            m.logout()
        except Exception:
            pass


def poll(name, acc):
    """attempt the confirmation flow for one platform. Mutates acc only on
    success (email_confirmed_at). Returns (status, detail)."""
    addr = (acc.get("email") or "").strip()
    if not addr:
        return "no_email", "no account email set — WIRE %s EMAIL=<addr> first" % name
    domains = PLATFORM_DOMAINS.get(name, ())
    r = _mailtm_poll(addr, domains)
    if r is None:
        r = _imap_poll(addr, domains)
    if r is None:
        url, est = walls.resolve(name)
        walls.record(name, "email", attempts=0, url=url, est_min=est,
                     human_step="open %s, click the confirmation link from %s"
                                % (addr, " / ".join(domains) or "the platform"))
        return "no_channel", (
            "no poll channel for %s — click the confirmation link in that "
            "inbox (~1 min); or store MAIL_IMAP_HOST/USER/PASS secrets and "
            "the loop clicks it (walls ledger updated)" % addr)
    return r


def run_poll():
    """every tracked platform with an email set and not yet confirmed."""
    cfg = util.load_config("accounts.json")
    platforms = cfg.get("platforms", {})
    dirty = False
    out = []
    for name in walls._tracked():
        acc = platforms.get(name) or {}
        addr = (acc.get("email") or "").strip()
        if not addr or acc.get("email_confirmed_at"):
            continue
        status, detail = poll(name, acc)
        out.append("emailpoll %s: %s — %s" % (name, status, detail[:120]))
        util.log_event("emailpoll", platform=name, status=status, detail=detail[:200])
        if status == "confirmed":
            acc["email_confirmed_at"] = util.ts()
            dirty = True
            util.remove_blockers("WALL %s: email" % name)
    if dirty:
        util.save_json(util.CONFIG / "accounts.json", cfg)
    if out:
        print("\n".join(out))
    else:
        print("emailpoll: no platform awaiting confirmation")


@util.cli_guard
def main(argv):
    if argv and argv[0] == "--poll":
        run_poll()
        return
    print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
