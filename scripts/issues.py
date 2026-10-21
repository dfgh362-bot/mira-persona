"""MIRA v4+v3.2 immune system — GitHub Issues as the command channel.

- label "command" issues execute at TOP PRIORITY every cycle: start comment,
  result comment, close on success (v3.2 sec.1). Labeling requires repo write
  access, so strangers cannot inject commands; RUN is additionally allowlisted.
- the command may live in the issue title OR the first line of the body.
- WIRE <platform> [KEY=value ...] (v3.2 sec.1): parse KEY=value pairs from
  the issue, upload each as an Actions secret (sealed box, PyNaCl), set
  accounts.json platforms.<p>.status = "ready", comment the result (never
  echoing secret values), close the issue. onboard_check picks it up next
  cycle and queues the first post ceremony (sec.6).
- DRAIN: post every unposted item immediately, ignoring the schedule.
- failed commands stay open and retry next cycle, capped at 3 attempts.
- deadman: HEARTBEAT gap > 60 min -> open one "blocked:" issue.
- anti-thrash / self-termination notices also arrive here.

Commands: WIRE / PAUSE / RESUME / STOP / STATUS / REPAIR / REFILL / DRAIN /
          HEALTH / PRIORITY <action [| cmd: <cmd>]> / RUN <cmd>

Secret uploads need a token with secrets access. GITHUB_TOKEN does NOT have
it (the `secrets` permission is not available to GITHUB_TOKEN), so the
capable token is probed in order: env WIRE_PAT -> env GH_PAT (Actions secret
GH_PAT, one-time human setup) -> GITHUB_TOKEN -> PAT parsed from the origin
remote URL (local runs — how MAIL_PASS was uploaded, D43).
Values are redacted from the issue body/title immediately after parsing
(this repo is public; close the exposure window).

Auth (R-08, PAT optional elsewhere): GITHUB_TOKEN in Actions, or the token
parsed from the origin remote URL on local runs.
"""
import base64
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

API = "https://api.github.com"
ALLOWED_RUN = re.compile(r"^(python scripts/[a-z0-9_]+\.py(\s|$)|git push$|bash scripts/)")
COMMANDS = {"WIRE", "PAUSE", "RESUME", "STOP", "STATUS", "REPAIR", "REFILL", "DRAIN",
            "HEALTH", "PRIORITY", "RUN"}
ATTEMPTS = util.STATE / "command_attempts.json"

# v3.2 sec.5 — the onboarding name contract, canonical env names, exact:
PLATFORM_ENVS = {
    "telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
    "bluesky": ("BSKY_HANDLE", "BSKY_APP_PASSWORD"),
    "mastodon": ("MASTODON_INSTANCE", "MASTODON_TOKEN"),
    "reddit": ("REDDIT_CLIENT_ID", "REDDIT_SECRET", "REDDIT_USERNAME",
               "REDDIT_PASSWORD", "REDDIT_SUBREDDIT"),
    "x": ("X_BEARER_TOKEN",),
    "pinterest": ("PINTEREST_TOKEN", "PINTEREST_BOARD_ID"),
    "fanvue": ("FANVUE_EMAIL", "FANVUE_PASSWORD"),
}
PAIR_LINE_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]{2,})=(.*)$")     # body: KEY=value rest-of-line
PAIR_TOKEN_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})=([^\s]+)")  # title: space-separated


def _repo():
    return "%s/%s" % (util.gh_user(), util.DEFAULTS["repo"])


def _api(method, path, payload=None, token=None, retries=2):
    """returns parsed json or None; logs (never values) on failure."""
    tok = token or util.gh_token()
    if not tok:
        return None
    try:
        return util.http_json(method, API + path, payload=payload,
                              headers={"Authorization": "Bearer " + tok}, retries=retries)
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
    for it in list_open():
        if (it.get("title") or "").startswith(title[:dedupe]):
            return None
    r = _api("POST", "/repos/%s/issues" % _repo(),
             {"title": title, "body": body, "labels": list(labels)})
    util.log_event("issue_opened", title=title[:100])
    return r


def comment(num, body):
    """v3.2 sec.1: comment on start AND on result."""
    if not num:
        return
    _api("POST", "/repos/%s/issues/%s/comments" % (_repo(), num), {"body": str(body)[:6000]})


def _close(num):
    _api("PATCH", "/repos/%s/issues/%s" % (_repo(), num), {"state": "closed"})


def _sh(cmd, timeout=600):
    try:
        p = subprocess.run(cmd, shell=True, cwd=util.ROOT, capture_output=True,
                            text=True, timeout=timeout)
        return "rc=%d\n%s" % (p.returncode, ((p.stdout or "") + (p.stderr or ""))[-1200:])
    except Exception as e:
        return "rc=-1\n%r" % e


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


def _status_text():
    """v3.2: STATUS shows the funnel + platform wiring table."""
    import health
    try:
        unposted, oldest = health.funnel_state()
    except Exception:
        unposted, oldest = -1, -1.0
    accs = util.load_config("accounts.json").get("platforms", {})
    plats = " ".join("%s=%s" % (n, (accs.get(n) or {}).get("status") or "?")
                     for n in sorted(PLATFORM_ENVS))
    try:
        handoff = (util.STATE / "HANDOFF.md").read_text(encoding="utf-8")
    except Exception:
        handoff = "(no handoff)"
    return ("platforms: %s\nfunnel: %d captioned unposted, oldest %.1fh "
            "(stuck threshold %dh, generation cap %d)\nqueue: %d items\n```\n%s\n```"
            % (plats, unposted, oldest, health.FUNNEL_STUCK_HOURS, health.FUNNEL_CAP,
               len(util.load_queue().get("items", [])), handoff[:3000]))


def _run_backlog_cli(args):
    return _sh("python scripts/backlog.py " + " ".join(args))


# ---------------------------------------------------------------- WIRE (v3.2)

def _wire_help(msg):
    lines = [msg, "", "usage: open an issue titled 'WIRE <platform>' (label: command) "
             "with one KEY=value pair per line in the body.", "",
             "canonical env names, exact (v3.2 sec.5):"]
    for plat in ("telegram", "bluesky", "mastodon", "reddit", "x", "pinterest", "fanvue"):
        lines.append("  %-10s %s" % (plat, ", ".join(PLATFORM_ENVS[plat])))
    lines += ["", "example body:", "  TELEGRAM_BOT_TOKEN=123456:ABC...",
              "  TELEGRAM_CHAT_ID=-1001234567890"]
    return "\n".join(lines)


def parse_wire_pairs(cmdline_rest, body_lines):
    """pure: KEY=value pairs from the title rest (space-separated tokens)
    plus body lines (value = rest of line, spaces allowed). selftest v32."""
    pairs = {}
    for m in PAIR_TOKEN_RE.finditer(cmdline_rest or ""):
        pairs[m.group(1)] = m.group(2)
    for line in body_lines or []:
        m = PAIR_LINE_RE.match(line)
        if m:
            pairs[m.group(1)] = m.group(2).strip()
    return pairs


def _nacl():
    try:
        from nacl.public import PublicKey, SealedBox
        return PublicKey, SealedBox
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "pynacl"],
                       capture_output=True, timeout=240)
        from nacl.public import PublicKey, SealedBox
        return PublicKey, SealedBox


def _secrets_capable_token():
    """probe candidates against the repo public-key endpoint (secrets read)."""
    cands = []
    for env in ("WIRE_PAT", "GH_PAT"):
        v = os.environ.get(env)
        if v and v not in cands:
            cands.append(v)
    gt = util.gh_token()
    if gt and gt not in cands:
        cands.append(gt)
    for tok in cands:
        path = "/repos/%s/actions/secrets/public-key" % _repo()
        try:
            req = util.http_json("GET", API + path,
                                 headers={"Authorization": "Bearer " + tok}, retries=1)
            if req and req.get("key_id"):
                return tok
        except Exception:
            continue
    return None


def upload_secrets(pairs):
    """sealed-box upload. returns (ok, detail_lines). NEVER logs values."""
    tok = _secrets_capable_token()
    if not tok:
        return False, [
            "no token with secrets access was found (GITHUB_TOKEN cannot write "
            "secrets — GitHub limitation).", "one-time fix, either:",
            "  1. store a PAT (repo scope) as Actions secret GH_PAT, or",
            "  2. run 'python scripts/issues.py --poll' locally (PAT in origin url).",
        ]
    try:
        PublicKey, SealedBox = _nacl()
        pk = util.http_json("GET", API + "/repos/%s/actions/secrets/public-key" % _repo(),
                            headers={"Authorization": "Bearer " + tok}, retries=2)
        box = SealedBox(PublicKey(base64.b64decode(pk["key"])))
        lines = []
        for name, value in sorted(pairs.items()):
            enc = base64.b64encode(box.encrypt((value or "").encode())).decode()
            util.http_json("PUT", API + "/repos/%s/actions/secrets/%s" % (_repo(), name),
                           payload={"encrypted_value": enc, "key_id": pk["key_id"]},
                           headers={"Authorization": "Bearer " + tok}, retries=2)
            lines.append("%s=*** (uploaded)" % name)
        return True, lines
    except Exception as e:
        return False, ["upload failed: %r" % e]


def _redact_issue(num, title, body, pairs):
    """public repo: scrub secret values from the issue the moment they are
    parsed, regardless of upload outcome. longest values first."""
    vals = sorted({v for v in pairs.values() if v and len(v) >= 3}, key=len, reverse=True)
    if not vals or not num:
        return False
    new_body, new_title = body or "", title or ""
    for v in vals:
        new_body = new_body.replace(v, "***")
        new_title = new_title.replace(v, "***")
    if new_body == (body or "") and new_title == (title or ""):
        return False
    r = _api("PATCH", "/repos/%s/issues/%s" % (_repo(), num),
             {"body": new_body, "title": new_title})
    util.log_event("wire_redacted", num=num, ok=bool(r))
    return bool(r)


def _wire(cmdline_rest, body_lines, num, title, body):
    parts = (cmdline_rest or "").split()
    if not parts:
        return _wire_help("WIRE needs a platform."), True
    plat = parts[0].lower()
    if plat not in PLATFORM_ENVS:
        return _wire_help("unknown platform '%s'." % plat), True
    canonical = PLATFORM_ENVS[plat]
    pairs = parse_wire_pairs(cmdline_rest, body_lines)
    bad = sorted(k for k in pairs if k not in canonical)
    if bad:
        return _wire_help("non-canonical key(s) for %s: %s — expected exactly: %s"
                          % (plat, ", ".join(bad), ", ".join(canonical))), True
    if not pairs:
        return _wire_help("WIRE %s: no KEY=value pairs found in title or body." % plat), True
    empty = [k for k, v in pairs.items() if not v.strip()]
    if empty:
        return _wire_help("empty value(s): %s — re-issue with values filled in."
                          % ", ".join(sorted(empty))), True
    # close the exposure window FIRST, whatever happens next
    redacted = _redact_issue(num, title, body, pairs)
    ok, lines = upload_secrets(pairs)
    if not ok:
        return "\n".join(["WIRE %s: upload FAILED." % plat] + lines +
                         ["issue stays open — retried next cycle (attempt capped at 3)."]), False
    cfg = util.load_config("accounts.json")
    acc = cfg.setdefault("platforms", {}).setdefault(plat, {})
    acc["status"] = "ready"
    acc["wired"] = sorted(pairs.keys())
    acc["wired_at"] = util.ts()
    if num:
        acc["wire_issue"] = num
    util.save_json(util.CONFIG / "accounts.json", cfg)
    util.set_platform_status(plat, "ready")
    util.remove_blockers("WIRE %s" % plat)
    util.remove_blockers("%s onboarding needs human" % plat)
    util.log_decision(
        "D46: WIRE %s via issue #%s — %d secret(s) uploaded sealed-box, status -> ready; "
        "onboard_check queues the first post ceremony next cycle (pinned disclosure "
        "first, then oldest unposted item, live URLs commented on the wire issue)."
        % (plat, num, len(pairs)))
    out = ["WIRE %s ok:" % plat,
           "secrets uploaded: %s (values never echoed)" % ", ".join(sorted(pairs.keys()))]
    if redacted:
        out.append("issue body/title redacted (public repo — values scrubbed).")
    out.append("next cycle: pinned disclosure posts FIRST, then the oldest unposted "
               "item; live URLs will be commented on this issue.")
    return "\n".join(out), True


# ---------------------------------------------------------------- DRAIN (v3.2)

def _drain():
    """post every unposted item immediately, ignoring the schedule."""
    import onboard_check
    accs = util.load_config("accounts.json").get("platforms", {})
    t0 = time.time()
    before = len(util.load_posted().get("posts", []))
    out = ["DRAIN: posting every unposted item now (schedule ignored, v3.2 sec.1)"]
    ready = [n for n in sorted(onboard_check.POST_CMD)
             if (accs.get(n) or {}).get("status") == "ready"]
    if not ready:
        out.append("no ready tier-1 platform — WIRE one first "
                   "(secrets upload + status flip happens there).")
        return "\n".join(out), True
    for name in ready:
        if time.time() - t0 > 480:
            out.append("- %s: skipped (drain budget 480s exhausted)" % name)
            continue
        runs = 0
        while runs < 12 and time.time() - t0 < 480:
            r = _sh(onboard_check.POST_CMD[name], timeout=150)
            runs += 1
            if "no due item" in r or "dupe blocked" in r:
                break
            if not r.startswith("rc=0"):
                out.append("- %s: stopped after failure: %s" % (name, r.splitlines()[0][:100]))
                break
            if "failed" in r or "missing credentials" in r:
                out.append("- %s: platform reported failure/manual — stopping" % name)
                break
        out.append("- %s: %d post run(s)" % (name, runs))
    after = len(util.load_posted().get("posts", []))
    out.append("posted.json: %d -> %d post(s)" % (before, after))
    return "\n".join(out), True


# ---------------------------------------------------------------- dispatch

def _dispatch(cmdline, body_lines, num, title, body):
    """returns (result_text, ok). ok=False keeps the issue open for retry."""
    cmdline = (cmdline or "").strip()
    parts = cmdline.split(None, 1)
    cmd = (parts[0] or "").upper() if parts else ""
    rest = parts[1] if len(parts) > 1 else ""
    if not rest and body_lines:
        rest = body_lines[0].strip()
    if cmd == "PAUSE":
        (util.STATE / "PAUSE").write_text("ts %s via issue #%s\n" % (util.ts(), num))
        return "paused. send a RESUME command issue to resume.", True
    if cmd == "RESUME":
        try:
            (util.STATE / "PAUSE").unlink()
        except Exception:
            pass
        return "resumed.", True
    if cmd == "STOP":
        (util.STATE / "STOP").write_text("ts %s via issue #%s\n" % (util.ts(), num))
        return "stopping — terminal. delete state/STOP to revive.", True
    if cmd == "REFILL":
        return _run_backlog_cli(["--refill"]), True
    if cmd == "REPAIR":
        return _exec("python scripts/selfheal.py --scan"), True
    if cmd == "STATUS":
        return _status_text(), True
    if cmd == "HEALTH":
        return _health_text(), True
    if cmd == "DRAIN":
        return _drain()
    if cmd == "WIRE":
        return _wire(rest, body_lines, num, title, body)
    if cmd == "PRIORITY":
        action, cmdtxt = rest, ""
        if "|" in rest:
            bits = [b.strip() for b in rest.split("|")]
            action = bits[0]
            for b in bits[1:]:
                if b.startswith("cmd:"):
                    cmdtxt = b[4:].strip()
        if not action:
            return "PRIORITY needs an action", True
        return _run_backlog_cli(["--insert-top", '"%s"' % action, '"issue #%s"' % num,
                                 '"%s"' % cmdtxt]), True
    if cmd == "RUN":
        return _exec(rest), True
    return ("commands: WIRE <platform> [KEY=value ...] / PAUSE / RESUME / STOP / "
            "STATUS / REPAIR / REFILL / DRAIN / HEALTH / PRIORITY <action> / RUN <cmd>"), True


def _resolve_command(title, body_lines):
    """v3.2 sec.1: the command is the issue title OR the first body line."""
    for cand in [title] + (body_lines or [])[:1]:
        c = (cand or "").strip()
        if not c:
            continue
        if c.split(None, 1)[0].upper() in COMMANDS:
            return c
    return title or ""


def _bump_attempts(num):
    d = util.load_json(ATTEMPTS, {})
    n = int(d.get(str(num), 0)) + 1
    d[str(num)] = n
    if len(d) > 60:   # prune oldest entries
        for k in list(d)[: len(d) - 60]:
            d.pop(k, None)
    util.save_json(ATTEMPTS, d)
    return n


def _clear_attempts(num):
    d = util.load_json(ATTEMPTS, {})
    if d.pop(str(num), None) is not None:
        util.save_json(ATTEMPTS, d)


def poll_commands():
    """execute open issues labeled 'command'. Returns count handled."""
    n = 0
    for it in list_open(labels="command"):
        num = it.get("number")
        title = (it.get("title") or "").strip()
        body = it.get("body") or ""
        body_lines = [l for l in body.splitlines() if l.strip()]
        cmdline = _resolve_command(title, body_lines)
        comment(num, "> started: %s" % cmdline)          # sec.1: comment on start
        try:
            result, ok = _dispatch(cmdline, body_lines, num, title, body)
        except Exception as e:
            result, ok = "command crashed: %r" % e, False
        comment(num, result)                              # sec.1: comment on result
        if ok:
            _close(num)                                  # sec.1: close on success
            _clear_attempts(num)
        else:
            a = _bump_attempts(num)
            if a >= 3:
                comment(num, "3 attempts failed — closing (anti-thrash). see state/log.jsonl")
                _close(num)
                _clear_attempts(num)
            else:
                comment(num, "issue stays open — retried next cycle (attempt %d/3)" % a)
        util.log_event("issue_command", num=num, ok=bool(ok), title=title[:80])
        n += 1
    return n


def deadman_check():
    """v4: HEARTBEAT gap > 60 min -> one open 'blocked' issue.
    v3.2 sec.3: this is the in-loop deadman; the external watchdog is
    keepalive.py (workflow runs verified via API by cron)."""
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
                   "check Actions runs / loop.yml / keepalive.py (the cron "
                   "watchdog also verifies workflow runs via the API)."
                   % (int(gap / 60), hb.get("ts")),
                   labels=["blocked"])
        util.log_event("deadman_fired", gap_min=int(gap / 60))


def thrash_notice(item_id, reason):
    """v4 anti-thrash: item failed 3x with the same reason -> issue + move on."""
    return bool(open_issue("anti-thrash: %s failed 3x (%s)" % (item_id, reason[:60]),
                           "same failure reason 3 times — item moved on. "
                           "see state/log.jsonl and state/thrash.json.",
                           labels=["thrash"]))


def selfterm_notice(cycles):
    open_issue("self-terminated: %d clean cycles with no work" % cycles,
               "queue drained, nothing refilled, no commands. state/STOP written.",
               labels=["self-terminated"])


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
