"""mail.tm / mail.gw disposable inbox client + CLI.

API (identical on both hosts):
  GET  /domains
  POST /accounts      {"address","password"}
  POST /token         {"address","password"} -> {"token","id"}
  GET  /messages      Bearer
  GET  /messages/{id} Bearer

Retry ladder on signup rejection: 1) new local-part  2) new domain  3) api.mail.gw

CLI:
  python scripts/mailtm.py domains
  python scripts/mailtm.py create            # creates + saves one account
  python scripts/mailtm.py import <address>   # v3.1: adopt a user-provided account
  python scripts/mailtm.py inbox <address>
  python scripts/mailtm.py read <address> <id>
  python scripts/mailtm.py verify --all      # sweep inboxes, GET verification links

Passwords resolve in order: account entry -> env MAIL_PASS (Actions secret)
-> git-ignored config/mail_secret.json. The user-provided mailbox (v3.1)
never carries its password inside the repo (decision D43).
"""
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

HOSTS = ["https://api.mail.tm", "https://api.mail.gw"]
VERIFY_RE = re.compile(r"(verify|confirm|activate|validate|token|email-verification)", re.I)


def _req(host, method, path, payload=None, token=None, retries=3):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    return util.http_json(method, host + path, payload=payload, headers=headers, retries=retries)


def _password(acc):
    """v3.1: password resolution — entry, env MAIL_PASS, mail_secret.json."""
    pw = acc.get("password")
    if pw:
        return pw
    pw = os.environ.get("MAIL_PASS")
    if pw:
        return pw
    sec = util.load_json(util.CONFIG / "mail_secret.json", {})
    return sec.get(acc.get("address") or "")


def _refresh_token(acc):
    tok = _req(acc.get("host", HOSTS[0]), "POST", "/token",
               {"address": acc["address"], "password": _password(acc)})
    acc["token"] = tok.get("token")
    return acc


def _accounts():
    return util.load_config("accounts.json").get("mailtm", [])


def _save_account(acc):
    cfg = util.load_config("accounts.json")
    entries = cfg.setdefault("mailtm", [])
    for i, old in enumerate(entries):
        if old.get("address") == acc.get("address"):
            entries[i] = acc
            break
    else:
        entries.append(acc)
    util.save_json(util.CONFIG / "accounts.json", cfg)


def _acc_for(address):
    for a in _accounts():
        if a.get("address") == address:
            return a
    raise RuntimeError("no stored mailtm account for %s" % address)


def domains(host=HOSTS[0]):
    data = _req(host, "GET", "/domains?page=1")
    members = data.get("hydra:member") if isinstance(data, dict) else data
    if members is None:
        members = data if isinstance(data, list) else []
    return [d["domain"] for d in members if isinstance(d, dict) and d.get("isActive", True)]


def create_account(localpart=None, attempts=6):
    """retry ladder: new local-part -> new domain -> fallback host."""
    password = util.rand_password()
    errors = []
    for i in range(attempts):
        host = HOSTS[i % len(HOSTS)]
        try:
            doms = domains(host)
            if not doms:
                raise RuntimeError("no active domains on %s" % host)
            lp = localpart if (localpart and i == 0) else util.rand_localpart()
            dom = doms[i % len(doms)]
            addr = "%s@%s" % (lp, dom)
            _req(host, "POST", "/accounts", {"address": addr, "password": password})
            tok = _req(host, "POST", "/token", {"address": addr, "password": password})
            acc = {
                "address": addr,
                "password": password,
                "token": tok.get("token"),
                "id": tok.get("id"),
                "host": host,
                "created": util.ts(),
            }
            util.log_event("mailtm_created", address=addr, host=host)
            return acc
        except Exception as e:
            errors.append("%s: %r" % (host, e))
            time.sleep(1 + i)
    raise RuntimeError("mailtm retry ladder exhausted: " + " | ".join(errors))


def messages(acc):
    try:
        data = _req(acc["host"], "GET", "/messages?page=1", token=acc.get("token"))
    except RuntimeError as e:
        if "401" in str(e):
            acc = _refresh_token(acc)
            _save_account(acc)
            data = _req(acc["host"], "GET", "/messages?page=1", token=acc.get("token"))
        else:
            raise
    members = data.get("hydra:member") if isinstance(data, dict) else data
    return members or []


def read_message(acc, mid):
    try:
        return _req(acc["host"], "GET", "/messages/%s" % mid, token=acc.get("token"))
    except RuntimeError as e:
        if "401" in str(e):
            acc = _refresh_token(acc)
            _save_account(acc)
            return _req(acc["host"], "GET", "/messages/%s" % mid, token=acc.get("token"))
        raise


def extract_links(msg):
    html = msg.get("html") or ""
    if isinstance(html, list):
        html = " ".join(html)
    text = msg.get("text") or ""
    found = re.findall(r"https?://[^\s\"'<>)\]]+", html + " " + text)
    out = []
    for u in found:
        u = u.rstrip(".,;")
        if u not in out:
            out.append(u)
    return out


def verify_all():
    """sweep every stored inbox; GET any verification-looking link once."""
    accs = _accounts()
    if not accs:
        util.log_event("inbox", note="no mailtm accounts stored")
        print("no mailtm accounts stored")
        return
    for acc in accs:
        try:
            msgs = messages(acc)
            util.log_event("inbox_swept", address=acc["address"], count=len(msgs))
            print("%s: %d message(s)" % (acc["address"], len(msgs)))
            for m in msgs:
                mid = m.get("id") or m.get("@id", "").rpartition("/")[2]
                if not mid:
                    continue
                full = read_message(acc, mid)
                for link in extract_links(full):
                    if VERIFY_RE.search(link):
                        status = util.http_get(link)
                        util.log_event("verify_link", address=acc["address"],
                                       link=link[:200], http=status)
                        print("  verify %s -> %s" % (status, link[:100]))
        except Exception as e:
            util.log_event("inbox_error", address=acc.get("address"), error=repr(e))
            print("%s: error %r" % (acc.get("address"), e))


@util.cli_guard
def main(argv):
    if not argv or argv[0] == "domains":
        for host in HOSTS:
            try:
                print(host, "->", ", ".join(domains(host)[:10]))
            except Exception as e:
                print(host, "-> error:", repr(e))
        return
    cmd = argv[0]
    if cmd == "create":
        acc = create_account()
        _save_account(acc)
        print("created %s (password %s) on %s" % (acc["address"], acc["password"], acc["host"]))
        return
    if cmd == "import" and len(argv) > 1:
        address = argv[1]
        host = argv[2] if len(argv) > 2 else None
        pw = _password({"address": address})
        if not pw:
            raise SystemExit("no password for %s: set MAIL_PASS env or "
                             "config/mail_secret.json[address]" % address)
        tried = []
        for h in ([host] if host else HOSTS):
            try:
                tok = _req(h, "POST", "/token", {"address": address, "password": pw})
                acc = {"address": address, "password": None,
                       "secret": "env MAIL_PASS / mail_secret.json (D43)",
                       "token": tok.get("token"), "id": tok.get("id"), "host": h,
                       "created": util.ts(), "source": "user-provided (v3.1)"}
                _save_account(acc)
                util.log_event("mailtm_imported", address=address, host=h)
                print("imported %s on %s (password NOT stored in repo)" % (address, h))
                return
            except Exception as e:
                tried.append("%s: %r" % (h, e))
        raise SystemExit("import failed: " + " | ".join(tried))
    if cmd == "inbox" and len(argv) > 1:
        acc = _acc_for(argv[1])
        msgs = messages(acc)
        for m in msgs:
            print("%s  %s  %s" % (m.get("createdAt", "")[:19], m.get("from", {}).get("address", "?"),
                                  m.get("subject", "")))
        print("-- %d message(s)" % len(msgs))
        return
    if cmd == "read" and len(argv) > 2:
        acc = _acc_for(argv[1])
        msg = read_message(acc, argv[2])
        print(msg.get("subject", ""))
        for u in extract_links(msg):
            print("  ", u)
        return
    if cmd == "verify" and "--all" in argv:
        verify_all()
        return
    print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
