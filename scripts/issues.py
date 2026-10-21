"""MIRA v4 immune system — GitHub Issues as the command channel.

- label "command" issues execute at TOP PRIORITY every cycle, then get a
  result comment and are closed. Labeling requires repo write access, so
  strangers cannot inject commands; RUN is additionally allowlisted.
- deadman: HEARTBEAT gap > 60 min -> open one "blocked:" issue.
- anti-thrash / self-termination notices also arrive here.

Commands: PAUSE / RESUME / STOP / REFILL / REPAIR / STATUS / HEALTH /
          PRIORITY <action [| cmd: <cmd>]> / RUN <cmd>

Auth (R-08, PAT optional): GITHUB_TOKEN in Actions, or the token parsed from
the origin remote URL on local runs.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

API = "https://api.github.com"
ALLOWED_RUN = re.compile(r"^(python scripts/[a-z0-9_]+\.py(\s|$)|git push$|bash scripts/)")


def _repo():
    return "%s/%s" % (util.gh_user(), util.DEFAULTS["repo"])


def _api(method, path, payload=None):
    tok = util.gh_token()
    if not tok:
        return None
    try:
        return util.http_json(method, API + path, payload=payload,
                              headers={"Authorization": "Bearer " + tok}, retries=2)
    except Exception as e:
        util.log_event("gh_api_error", path=path, error=repr(e)[:200])
        return None


def list_open(labels=None):
    q = "/repos/%s/issues?state=open" % _repo()
    if labels:
        q += "&labels=" + labels
    out = _api("GET", q)
    return out if isinstance(out, list) else []


def open_issue(title, body="", labels=(), dedupe=30):
    """open an issue unless an open issue already starts with the same key."""
    key = title[:dedupe]
    for it in list_open():
        if (it.get("title") or "").startswith(key):
            return None
    r = _api("POST", "/repos/%s/issues" % _repo(),
             {"title": title, "body": body, "labels": list(labels)})
    util.log_event("issue_opened", title=title[:100])
    return r


def _comment_close(num, body):
    _api("POST", "/repos/%s/issues/%s/comments" % (_repo(), num), {"body": str(body)[:6000]})
    _api("PATCH", "/repos/%s/issues/%s" % (_repo(), num), {"state": "closed"})


def _sh(cmd):
    try:
        p = subprocess.run(cmd, shell=True, cwd=util.ROOT, capture_output=True,
                            text=True, timeout=600)
        return "rc=%d\n%s" % (p.returncode, ((p.stdout or "") + (p.stderr or ""))[-1200:])
    except Exception as e:
        return repr(e)


def _exec(cmdline):
    c = (cmdline or "").strip()
    if not c:
        return "empty command"
    if re.search(r"[;&|`]|\$\(", c):
        return "refused: shell metacharacters not allowed"
    if not ALLOWED_RUN.match(c):
        return "refused (allowlist: python scripts/... | git push | bash scripts/...)"
    return _sh(c)


def _health_text():
    try:
        import health
        p, n = health.stats()
        return "status: %s\nproductive/noop (last %d): %d/%d\nHEALTH.md: committed in state/" % (
            health.status(), health.WINDOW, p, n)
    except Exception as e:
        return "health unavailable: %r" % e


def _run_backlog_cli(args):
    return _sh("python scripts/backlog.py " + " ".join(args))


def _dispatch(title, body_lines, num):
    cmd = (title.split(None, 1)[0] or "").upper()
    rest = title.split(None, 1)[1] if len(title.split(None, 1)) > 1 else ""
    if not rest and body_lines:
        rest = body_lines[0].strip()
    if cmd == "PAUSE":
        (util.STATE / "PAUSE").write_text("ts %s via issue #%s\n" % (util.ts(), num))
        return "paused. send a RESUME command issue to resume."
    if cmd == "RESUME":
        try:
            (util.STATE / "PAUSE").unlink()
        except Exception:
            pass
        return "resumed."
    if cmd == "STOP":
        (util.STATE / "STOP").write_text("ts %s via issue #%s\n" % (util.ts(), num))
        return "stopping — terminal. delete state/STOP to revive."
    if cmd == "REFILL":
        return _run_backlog_cli(["--refill"])
    if cmd == "REPAIR":
        return _exec("python scripts/selfheal.py --scan")
    if cmd == "STATUS":
        try:
            handoff = (util.STATE / "HANDOFF.md").read_text(encoding="utf-8")
        except Exception:
            handoff = "(no handoff)"
        return "```\n%s\n```" % handoff[:4000]
    if cmd == "HEALTH":
        return _health_text()
    if cmd == "PRIORITY":
        action, cmdtxt = rest, ""
        if "|" in rest:
            bits = [b.strip() for b in rest.split("|")]
            action = bits[0]
            for b in bits[1:]:
                if b.startswith("cmd:"):
                    cmdtxt = b[4:].strip()
        if not action:
            return "PRIORITY needs an action"
        return _run_backlog_cli(["--insert-top", '"%s"' % action, '"issue #%s"' % num, '"%s"' % cmdtxt])
    if cmd == "RUN":
        return _exec(rest)
    return "commands: PAUSE / RESUME / STOP / REFILL / REPAIR / STATUS / HEALTH / PRIORITY <action> / RUN <cmd>"


def poll_commands():
    """v4: execute open issues labeled 'command'. Returns count handled."""
    n = 0
    for it in list_open(labels="command"):
        title = (it.get("title") or "").strip()
        body_lines = [l for l in ((it.get("body") or "").splitlines()) if l.strip()]
        try:
            result = _dispatch(title, body_lines, it.get("number"))
        except Exception as e:
            result = "command crashed: %r" % e
        _comment_close(it.get("number"), result)
        util.log_event("issue_command", num=it.get("number"), title=title[:80])
        n += 1
    return n


def deadman_check():
    """v4: HEARTBEAT gap > 60 min -> one open 'blocked' issue."""
    if (util.STATE / "STOP").exists():
        return
    hb = util.load_json(util.STATE / "HEARTBEAT", {})
    try:
        from datetime import datetime, timezone
        t = datetime.strptime(hb.get("ts") or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        gap = (util.utcnow() - t).total_seconds()
    except Exception:
        return
    if gap > 3600:
        open_issue("blocked: heartbeat gap %d min" % int(gap / 60),
                   "the loop did not beat for %d min. last heartbeat: %s. "
                   "check Actions runs / loop.yml / run_forever.sh." % (int(gap / 60), hb.get("ts")),
                   labels=["blocked"], dedupe=22)
        util.log_event("deadman_fired", gap_min=int(gap / 60))


def thrash_notice(item_id, reason):
    """v4 anti-thrash: item failed 3x with the same reason -> issue + move on."""
    return bool(open_issue("anti-thrash: %s failed 3x (%s)" % (item_id, reason[:60]),
                           "same failure reason 3 times — item moved on. "
                           "see state/log.jsonl and state/thrash.json.",
                           labels=["thrash"], dedupe=44))


def selfterm_notice(cycles):
    open_issue("self-terminated: %d clean cycles with no work" % cycles,
               "queue drained, nothing refilled, no commands. state/STOP written.",
               labels=["self-terminated"], dedupe=40)


@util.cli_guard
def main(argv):
    if argv and argv[0] == "--deadman":
        deadman_check()
        print("deadman check done")
        return
    if argv and argv[0] == "--poll":
        print("handled %d command issue(s)" % poll_commands())
        return
    print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
