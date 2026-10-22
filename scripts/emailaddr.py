"""MIRA v3.3 sec.1 — real-email addressing (plus-addressed Gmail).

BUILD ORDER v3.3 kills the temp-email premise of SPEC-v2 §4: no disposable
domain receives platform confirmation mail reliably (state/BLOCKERS.md
FUNNEL EMAIL WALL, 2026-10-21). New rule:

  persona general   <base>+<persona>@gmail.com
  per platform      <base>+<persona>-<platform>@gmail.com

The base address is stored ONCE and never committed:
  - Actions secret MAIL_BASE (the runner channel), or
  - gitignored config/email.json {"base": "..."} (local runs).
mail.tm is demoted to throwaway/secondary only (decision D51).

CLI:
  python scripts/emailaddr.py base <addr>   # store base in config/email.json
  python scripts/emailaddr.py show          # print derived identities
  python scripts/emailaddr.py check         # exit 0 if a base is configured
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
GMAIL_DOMAINS = ("gmail.com", "googlemail.com")


def base():
    """env MAIL_BASE (Actions secret) first, then gitignored config/email.json."""
    b = (os.environ.get("MAIL_BASE") or "").strip()
    if b:
        return b
    cfg = util.load_json(util.CONFIG / "email.json", {})
    return (cfg.get("base") or "").strip() or None


def persona():
    """persona token for plus-addresses — persona.json handle, [a-z0-9]."""
    h = util.load_config("persona.json").get("handle") or "mira"
    return re.sub(r"[^a-z0-9]", "", str(h).lower()) or "mira"


def _derive(tag):
    b = base()
    if not b:
        return None
    local, _, dom = b.partition("@")
    return "%s+%s@%s" % (local, tag, dom)


def general():
    """<base>+<persona>@<domain> — the persona-general address."""
    return _derive(persona())


def platform(name):
    """<base>+<persona>-<platform>@<domain> — the per-platform address."""
    return _derive("%s-%s" % (persona(), (name or "").strip().lower()))


def gmail_warning():
    """None if the base is a Gmail address, else a one-line warning."""
    b = base()
    if not b:
        return None
    dom = b.partition("@")[2].lower()
    return None if dom in GMAIL_DOMAINS else (
        "note: base domain is %s, not gmail.com — plus-addressing still "
        "derives, but v3.3 §1 names gmail" % dom)


def store_base(addr):
    addr = (addr or "").strip()
    if not EMAIL_RE.match(addr):
        raise SystemExit("not a valid email address: %r" % addr)
    util.save_json(util.CONFIG / "email.json", {"base": addr, "stored": util.ts()})
    util.log_decision("D51: email base stored in gitignored config/email.json "
                      "(v3.3 §1 — plus-addressed identities, mail.tm demoted "
                      "to throwaway/secondary; runner channel is the MAIL_BASE "
                      "secret)", addr=addr[:3] + "***")
    return addr


@util.cli_guard
def main(argv):
    if argv and argv[0] == "base" and len(argv) > 1:
        addr = store_base(" ".join(argv[1:]))
        print("stored base %s in config/email.json (gitignored; never committed)"
              % addr)
        w = gmail_warning()
        if w:
            print(w)
        print("derived: general=%s" % general())
        return
    if argv and argv[0] == "check":
        b = base()
        if not b:
            print("no base configured (MAIL_BASE secret or config/email.json)")
            raise SystemExit(1)
        print("base configured (domain %s)" % b.partition("@")[2])
        return
    if argv and argv[0] == "show":
        b = base()
        if not b:
            print("no base configured — set Actions secret MAIL_BASE, or run: "
                  "python scripts/emailaddr.py base <addr>")
            return
        print("base: %s (source: %s)" % (b, "MAIL_BASE env" if (os.environ.get("MAIL_BASE") or "").strip()
                                         else "config/email.json"))
        w = gmail_warning()
        if w:
            print(w)
        print("general : %s" % general())
        for p in ("telegram", "mastodon", "reddit", "x", "pinterest", "fanvue", "bluesky"):
            print("%-9s: %s" % (p, platform(p)))
        return
    print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
