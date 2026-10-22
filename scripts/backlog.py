"""MIRA backlog engine — the infinite queue. Never empty. Never stalls.

Item format (state/BACKLOG.md):
  - [ ] T-0001 | <action> | <why> | cmd: <runnable command>
  - [~] T-0002 | <action> | attempted, <reason>
  - [x] T-0003 | <action> | ok: <result> (or commit sha)

CLI:
  --one            run one cycle: lock(R-06) -> refill -> top item -> guards -> HANDOFF -> commit
  --refill         ensure >= 5 unchecked items (section 4 sources), commit if changed
  --mark ID x|~ n  mark an item manually
  --check-lock     exit 1 if loop.lock is fresher than 4 minutes (cooldown guard)
  --expand-prompts move +5 scenes / +5 captions from spare pools into the library
  --insert-top <action> <why> <cmd>   priority insertion (v4 issues channel)

Guards per section 9 + v3.1: 4-min cooldown, max 400 commits/day INSIDE the
shared commit path (R-02), 1 commit per 2 min, log rotation at 5MB, repo
prune at 900MB. v4 immune system wired into one(): issues command channel
at top priority, HEALTH every 25 cycles (+R-05 escalation), anti-drift every
50, deadman + anti-thrash + self-termination.
"""
import json
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util
import issues
import health
import onboard_check
import lint_workflows

BACKLOG = util.STATE / "BACKLOG.md"
HANDOFF = util.STATE / "HANDOFF.md"
LOCK = util.STATE / "loop.lock"
HEARTBEAT = util.STATE / "HEARTBEAT"

THROTTLE_SECONDS = 120      # max 1 commit per 2 minutes
COOLDOWN_SECONDS = 240      # loop.lock fresher than 4 min -> idle
MAX_COMMITS_PER_DAY = 400
MAX_ITEM_RUNTIME = 900      # 15 min per item, fits the 20-min workflow window

HYGIENE = [
    ("rebuild site", "pipeline", "python scripts/build_site.py"),
    ("sweep mail.tm inboxes", "verification", "python scripts/mailtm.py verify --all"),
    ("archive old items", "hygiene", "python scripts/state.py archive --older-than 48h"),
    ("cycle audit: stats + guard checks", "self-improve", "python scripts/state.py stats"),
]


def sh(cmd, timeout=180):
    return subprocess.run(cmd, shell=True, cwd=util.ROOT,
                          capture_output=True, text=True, timeout=timeout)


def sh_list(args, timeout=300):
    return subprocess.run(args, cwd=util.ROOT, capture_output=True, text=True, timeout=timeout)


def redact(s):
    return re.sub(r"ghp_[A-Za-z0-9]+", "ghp_***", s or "")


# ---------------------------------------------------------------- queue file

def parse_items():
    items = []
    if not BACKLOG.exists():
        return items
    for raw in BACKLOG.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^- \[( |x|~)\] (T-\d+) \| (.*)$", raw)
        if not m:
            continue
        state, tid, rest = m.groups()
        parts = [p.strip() for p in rest.split("|")]
        item = {"marker": state, "id": tid, "action": parts[0],
                "note": parts[1] if len(parts) > 1 else "", "cmd": ""}
        for p in parts[1:]:
            if p.startswith("cmd:"):
                item["cmd"] = p[4:].strip()
        items.append(item)
    return items


def write_items(items):
    lines = ["# BACKLOG — infinite queue (never empty)", ""]
    for it in items:
        line = "- [%s] %s | %s | %s" % (it["marker"], it["id"], it["action"], it["note"])
        if it.get("cmd"):
            line += " | cmd: %s" % it["cmd"]
        lines.append(line)
    BACKLOG.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prune_done(items):
    keep = [i for i in items if i["marker"] != "x"]
    done = [i for i in items if i["marker"] == "x"]
    return keep + done[-25:]


def next_id(items):
    nums = [int(i["id"][2:]) for i in items if i["id"].startswith("T-")]
    return "T-%04d" % (max(nums) + 1 if nums else 1)


def mark(item_id, status, note):
    items = parse_items()
    for it in items:
        if it["id"] == item_id:
            it["marker"] = status if status in ("x", "~", " ") else "~"
            it["note"] = note
            break
    write_items(prune_done(items))


# ---------------------------------------------------------------- guards

def touch_lock():
    util.save_json(LOCK, {"ts": util.ts(), "run_id": uuid.uuid4().hex[:12]})


def acquire_lock():
    """v3.1 R-06: the push is the mutex. write loop.lock{run_id,ts} -> commit
    -> push -> pull -> re-read. If run_id != mine, someone else won: exit 0
    (caller idles). Lock commit skips the pace-sleep but not the daily cap."""
    run_id = uuid.uuid4().hex[:12]
    util.save_json(LOCK, {"ts": util.ts(), "run_id": run_id})
    if commit_and_push("loop: lock %s" % run_id, throttle=False) is None:
        return False   # budget exhausted or commit/push failed — mutex not ours
    sh("git pull --rebase origin main")
    won = util.load_json(LOCK, {}).get("run_id") == run_id
    if not won:
        util.log_event("lock_lost", run_id=run_id,
                       winner=util.load_json(LOCK, {}).get("run_id"))
    return won


def lock_is_fresh():
    try:
        lock = util.load_json(LOCK, {})
        t = datetime.strptime(lock.get("ts", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (util.utcnow() - t).total_seconds() < COOLDOWN_SECONDS
    except Exception:
        return False


def heartbeat_bump():
    hb = util.load_json(HEARTBEAT, {"ts": None, "cycle": 0})
    hb["cycle"] = int(hb.get("cycle", 0)) + 1
    hb["ts"] = util.ts()
    util.save_json(HEARTBEAT, hb)
    return hb["cycle"]


def last_commit_ts():
    try:
        return int(sh("git log -1 --format=%ct").stdout.strip())
    except Exception:
        return 0


def commits_today():
    try:
        return int(sh("git rev-list --count HEAD --since=midnight").stdout.strip())
    except Exception:
        return 0


def pace():
    delta = time.time() - last_commit_ts()
    if delta < THROTTLE_SECONDS:
        wait = THROTTLE_SECONDS - delta
        print("pace: sleeping %.0fs (max 1 commit / 2 min)" % wait)
        time.sleep(wait)


def rotate_logs():
    p = util.STATE / "log.jsonl"
    try:
        if p.exists() and p.stat().st_size > 5 * 1024 * 1024:
            p.replace(util.STATE / "log.1.jsonl")
    except Exception as e:
        util.log_event("guard_error", where="rotate_logs", error=repr(e))


def prune_repo():
    try:
        size = int(sh("du -sm .", timeout=120).stdout.split()[0])
        if size > 900:
            n = 0
            for f in util.CONTENT.rglob("*"):
                if f.is_file() and (time.time() - f.stat().st_mtime) > 60 * 86400:
                    f.unlink()
                    n += 1
            util.log_event("pruned", files=n)
    except Exception as e:
        util.log_event("guard_error", where="prune_repo", error=repr(e))


def _push_with_recovery():
    p = sh_list(["git", "push"])
    if p.returncode == 0:
        return True
    # multi-runner race: fold remote state under ours, retry once
    sh("git fetch origin main")
    r = sh("git rebase -X theirs origin/main")
    if r.returncode == 0:
        p2 = sh_list(["git", "push"])
        if p2.returncode == 0:
            return True
        util.log_event("push_failed", error=redact((p2.stderr or p2.stdout))[-300:])
        print("push failed after rebase (logged)")
        return False
    util.log_event("rebase_failed", error=redact((r.stderr or ""))[-300:])
    print("rebase failed (logged)")
    return False


def commit_and_push(msg, throttle=True):
    """v3.1 R-02: THE shared commit path — every workflow routes through here.
    The 400/day cap lives in this function and always applies. throttle=False
    is for workflow commits and the lock (cron self-limits, D32)."""
    try:
        sh("git add -A")
        if sh("git diff --cached --quiet").returncode == 0:
            return None  # nothing to commit
        if commits_today() >= MAX_COMMITS_PER_DAY:
            util.log_event("commit_skipped", reason="daily cap %d reached" % MAX_COMMITS_PER_DAY)
            return None
        if throttle:
            pace()
        c = sh_list(["git", "commit", "-m", msg])
        if c.returncode != 0:
            util.log_event("commit_failed", error=redact(c.stderr)[-300:])
            return None
        if not _push_with_recovery():
            return None  # v3.1: a sha only counts when the push landed
        return sh("git rev-parse --short HEAD").stdout.strip()
    except Exception as e:
        util.log_event("commit_error", error=repr(e))
        return None


def workflow_commit(msg):
    """workflow commits: same shared path, no pace-sleep (D32) — the cap
    still applies because it lives in commit_and_push (R-02)."""
    sha = commit_and_push(msg, throttle=False)
    if sha:
        print("workflow commit pushed: %s (%s)" % (msg, sha))
    return sha


# ---------------------------------------------------------------- refill sources

def today_counts():
    d = util.today()

    def jpgs(tier):
        p = util.CONTENT / tier / d
        return len(list(p.glob("*.jpg"))) if p.exists() else 0

    vids = 0
    vdir = util.CONTENT / "video"
    if vdir.exists():
        for m in vdir.glob("mira_clip_*.json"):
            try:
                if json.loads(m.read_text()).get("built", "").startswith(d):
                    vids += 1
            except Exception:
                pass
    return {"free": jpgs("free"), "paid": jpgs("paid"), "video": vids}


def voice_stale():
    vdir = util.CONTENT / "voice"
    files = list(vdir.glob("voice_*.mp3")) if vdir.exists() else []
    if not files:
        return True
    newest = max(f.stat().st_mtime for f in files)
    return (time.time() - newest) > 7 * 86400


def spare_prompts_available():
    return bool(util.load_json(util.PROMPTS / "spare_scenes.json", []))


def repair_candidates():
    """v3.1 R-01: scan kinds error, commit_failed, push_failed, backlog_timeout
    — not just image_failed. R-01 kinds claim slots first; legacy image/caption
    kinds fill what's left. Cap 3 repair items per refill."""
    out = []
    try:
        lines = (util.STATE / "log.jsonl").read_text(encoding="utf-8").splitlines()[-200:]
    except Exception:
        return out
    recs = []
    for line in reversed(lines):
        try:
            recs.append(json.loads(line))
        except Exception:
            continue
    for kinds in (("error", "commit_failed", "push_failed", "backlog_timeout"),
                  ("image_failed", "image_attempt_failed", "caption_gen_failed")):
        for rec in recs:
            if len(out) >= 3:
                break
            kind = rec.get("kind", "")
            if kind not in kinds or kind in [o[0] for o in out]:
                continue
            if kind == "error":
                out.append((kind, "self-heal recent errors (scan, map, re-run)",
                            "self-repair (R-01)", "python scripts/selfheal.py --scan"))
            elif kind == "commit_failed":
                out.append((kind, "retry commit via shared path",
                            "self-repair (R-01)",
                            "python scripts/backlog.py --commit repair: retry after commit_failed"))
            elif kind == "push_failed":
                out.append((kind, "retry git push", "self-repair (R-01)", "git push"))
            elif kind == "backlog_timeout":
                out.append((kind, "self-heal: requeue timed-out items",
                            "self-repair (R-01)", "python scripts/selfheal.py --scan"))
            elif kind == "caption_gen_failed":
                out.append((kind, "retry caption generation", "self-repair",
                            "python scripts/gen_caption.py"))
            else:  # image_failed / image_attempt_failed
                out.append((kind, "retry image generation (recent failure)", "self-repair",
                            "python scripts/gen_image.py --tier free --count 1"))
    return [(a, b, c) for _k, a, b, c in out]


def refill():
    items = parse_items()
    n_before = len(items)
    unchecked_actions = {i["action"] for i in items if i["marker"] == " "}
    all_actions = {i["action"] for i in items}

    def unchecked_count():
        return len([i for i in items if i["marker"] == " "])

    def add(action, why, cmd="", recurring=False):
        if unchecked_count() >= 12:
            return
        if recurring:
            if action in unchecked_actions:
                return
        elif action in all_actions:
            return
        items.append({"marker": " ", "id": next_id(items), "action": action,
                      "note": why, "cmd": cmd})
        unchecked_actions.add(action)
        all_actions.add(action)

    # source 1: daily quotas (aware of today's counts + R-05 escalation)
    c = today_counts()
    fmax = util.effective_quota("img_free_day")
    pmax = util.effective_quota("img_paid_day")
    vmax = util.effective_quota("video_day")
    if c["free"] < fmax:
        n = min(4, fmax - c["free"])
        add("generate %d free images" % n, "daily quota (%d/%d today)" % (c["free"], fmax),
            "python scripts/gen_image.py --tier free --count %d" % n, recurring=True)
    if c["paid"] < pmax:
        n = min(2, pmax - c["paid"])
        add("generate %d paid images" % n, "daily quota (%d/%d today)" % (c["paid"], pmax),
            "python scripts/gen_image.py --tier paid --count %d" % n, recurring=True)
    if c["video"] < vmax:
        add("build 1 video clip", "daily quota (%d/%d today)" % (c["video"], vmax),
            "python scripts/make_video.py --auto", recurring=True)
    if voice_stale():
        add("refresh voice notes", "weekly rotation", "python scripts/gen_voice.py", recurring=True)
    if any(i.get("status") == "queued" for i in util.load_queue().get("items", [])):
        add("caption queued items", "pipeline", "python scripts/gen_caption.py", recurring=True)

    # source 3: onboarding pending accounts (human needed -> [~] + BLOCKERS.md)
    accs = util.load_config("accounts.json").get("platforms", {})
    for name in ("fanvue", "bluesky", "telegram", "reddit", "mastodon", "x", "pinterest"):
        if accs.get(name, {}).get("status") == "pending":
            add("onboard %s: create account, bio + pinned, creds to Actions Secrets" % name,
                "onboarding (human)")

    # hygiene rotation (recurring, idempotent — no-ops commit nothing)
    for action, why, cmd in HYGIENE:
        add(action, why, cmd, recurring=True)

    # source 5: expand prompt library while spares last
    if spare_prompts_available():
        add("expand prompt library (+5 scenes, +5 captions)", "library growth",
            "python scripts/backlog.py --expand-prompts", recurring=True)

    # source 6: self-repair from recent failures
    for action, why, cmd in repair_candidates():
        add(action, why, cmd, recurring=True)

    # source 7: invent — never return zero
    if unchecked_count() < 5:
        add("cycle audit: stats + guard checks", "self-improve",
            "python scripts/state.py stats")
    if unchecked_count() < 1:
        items.append({"marker": " ", "id": next_id(items),
                     "action": "cycle audit: stats + guard checks",
                     "note": "invented (queue was empty)",
                     "cmd": "python scripts/state.py stats"})

    write_items(prune_done(items))
    return len(items) != n_before


def expand_prompts():
    scenes = util.load_json(util.PROMPTS / "scenes.json", [])
    sp = util.load_json(util.PROMPTS / "spare_scenes.json", [])
    take, rest = sp[:5], sp[5:]
    scenes += take
    util.save_json(util.PROMPTS / "scenes.json", scenes)
    util.save_json(util.PROMPTS / "spare_scenes.json", rest)
    caps = util.load_json(util.PROMPTS / "captions.json", [])
    spc = util.load_json(util.PROMPTS / "spare_captions.json", [])
    takec, restc = spc[:5], spc[5:]
    caps += takec
    util.save_json(util.PROMPTS / "captions.json", caps)
    util.save_json(util.PROMPTS / "spare_captions.json", restc)
    util.log_event("prompts_expanded", scenes_added=len(take), captions_added=len(takec))
    print("expanded: +%d scenes, +%d captions (%d / %d spares left)"
          % (len(take), len(takec), len(rest), len(restc)))


# ---------------------------------------------------------------- v4 helpers

def _thrash_capped(target, reason):
    """v4 anti-thrash: same item 3x same reason -> stop, issue, move on."""
    reason = str(reason).replace("|", "/")[:80]
    p = util.STATE / "thrash.json"
    d = util.load_json(p, {})
    e = d.get(target["id"]) or {}
    if e.get("reason") == reason:
        e["count"] = int(e.get("count", 0)) + 1
    else:
        e = {"reason": reason, "count": 1}
    d[target["id"]] = e
    if e["count"] >= 3:
        d.pop(target["id"], None)
        util.save_json(p, d)
        issues.thrash_notice(target["id"], reason)
        util.log_event("thrash_capped", id=target["id"], reason=reason[:60])
        return True
    util.save_json(p, d)
    return False


def drift_check(cycle):
    """v4 anti-drift: every 50 cycles re-read the frozen specs, verify
    invariants, write state/DRIFT.md."""
    docs = util.ROOT / "docs"
    specs = {n: (docs / n).read_text(encoding="utf-8")
             for n in ("SPEC-v2.md", "SPEC-v3.md", "SPEC-v3.1.md", "SPEC-v3.2.md")
             if (docs / n).exists()}
    src = (util.ROOT / "scripts" / "backlog.py").read_text(encoding="utf-8")
    site = (util.ROOT / "scripts" / "build_site.py").read_text(encoding="utf-8")
    checks = [
        ("specs frozen (v2/v3/v3.1/v3.2)", len(specs) == 4),
        ("queue never empty", len([i for i in parse_items() if i["marker"] == " "]) >= 1),
        ("commit caps in shared path", "MAX_COMMITS_PER_DAY" in src),
        ("lock push-mutex present", "acquire_lock" in src),
        ("disclosure rendered on site", "ai-generated" in site),
        ("site tier chain present", "data-fb" in site),
        ("quotas config intact", util.effective_quota("img_free_day") >= 8),
    ]
    lines = ["# DRIFT — spec conformance audit", "",
             "cycle: %d" % cycle,
             "specs re-read: %s" % (", ".join(specs) or "NONE"), ""]
    for name, ok in checks:
        lines.append("- [%s] %s" % ("ok" if ok else "DRIFT", name))
    lines.append("")
    lines.append("generated: %s" % util.ts())
    (util.STATE / "DRIFT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    util.log_event("drift_checked", cycle=cycle,
                   drifts=sum(1 for _, ok in checks if not ok))
    print("DRIFT.md written (%d drifts)" % sum(1 for _, ok in checks if not ok))


def selfterm_update(productive):
    """v4 self-termination: only after 100 clean cycles with no work."""
    p = util.STATE / "loop.json"
    d = util.load_json(p, {"clean_streak": 0})
    d["clean_streak"] = 0 if productive else int(d.get("clean_streak", 0)) + 1
    util.save_json(p, d)
    if d["clean_streak"] >= 100:
        (util.STATE / "STOP").write_text("ts %s self-terminated\n" % util.ts())
        issues.selfterm_notice(d["clean_streak"])
        util.log_event("self_terminated", cycles=d["clean_streak"])
    return d["clean_streak"]


# ---------------------------------------------------------------- execution

def run_cmd(target):
    cmd = target["cmd"]
    print("running: %s" % cmd)
    try:
        proc = subprocess.run(cmd, shell=True, cwd=util.ROOT,
                              capture_output=True, text=True, timeout=MAX_ITEM_RUNTIME)
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if out:
            print(out[-1500:])
        tail = out.splitlines()[-1] if out else ""
        # v3.1 sec.0: a swallowed exception is a lie — surface the traceback
        # tail in the ITEM NOTE (cli_guard prints 'mira-cli-guard: <tail>')
        guard_tail = ""
        for ln in reversed(err.splitlines()):
            if ln.startswith("mira-cli-guard:"):
                guard_tail = ln[len("mira-cli-guard:"):].strip()
                break
        if guard_tail:
            print("cli-guard: %s" % guard_tail)
        if not tail and guard_tail:
            tail = guard_tail
        tail = tail.replace("|", "/")
        util.log_event("backlog_exec", id=target["id"], rc=proc.returncode,
                       tail=(tail or guard_tail)[:200])
        if proc.returncode == 0 and "generated 0/" not in out:
            target["marker"] = "x"
            target["note"] = "ok: %s" % (tail[:60] or "rc=0")
            return (tail or "ok")[:80], "productive"
        reason = (guard_tail or tail or "blocked").replace("|", "/")[:80]
        if _thrash_capped(target, reason):
            target["marker"] = "~"
            target["note"] = "moved on (anti-thrash 3x): %s" % reason[:60]
            return reason[:80], "noop"
        target["marker"] = "~"
        target["note"] = "attempted: %s (rc=%d)" % (reason[:60], proc.returncode)
        return reason[:80], "noop"
    except subprocess.TimeoutExpired:
        reason = "timeout"
        _thrash_capped(target, reason)
        target["marker"] = "~"
        target["note"] = "attempted, timeout"
        util.log_event("backlog_timeout", id=target["id"])
        return reason, "noop"
    except Exception as e:
        target["marker"] = "~"
        target["note"] = "attempted: %r" % e
        return repr(e)[:80], "noop"


def rewrite_handoff(cycle, target, summary, sha):
    items = parse_items()
    nxt = next((i for i in items if i["marker"] == " "), None)
    if nxt is None:
        next_action = "python scripts/backlog.py --one"
    elif nxt.get("cmd"):
        next_action = nxt["cmd"]
    else:
        next_action = "python scripts/backlog.py --one  # %s (needs human)" % nxt["id"]
    blockers = "none"
    try:
        lines = [l for l in (util.STATE / "BLOCKERS.md").read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#") and "(none" not in l]
        if lines:
            # v3.3 sec.3: 5-line cap — the walls line is the headline, the
            # human never gets a wall of text (full detail: state/BLOCKERS.md)
            blockers = "\n".join(lines[:5])
    except Exception:
        pass
    # v3.3 sec.3: exactly one walls line — the single cheapest next action
    try:
        import walls
        wall_line = walls.summary_line()
    except Exception:
        wall_line = "(walls summary unavailable)"
    # v3.5 sec.10: closing block — | platform | lane | state | blocker | human cost |
    lanes_block = "(lane table unavailable)"
    try:
        import browserpost
        lanes_block = browserpost.lane_table()
    except Exception:
        pass
    text = ("## CURRENT\n%s %s — %s\n## NEXT ACTION\n%s\n## WALLS\n%s\n"
            "## BLOCKERS\n%s\n## LAST COMMIT\n%s\n## CYCLE\n%d\n"
            "## LANES (v3.5)\n%s\n"
            % (target["id"], target["action"], summary, next_action,
               wall_line, blockers, sha or "none", cycle, lanes_block))
    HANDOFF.write_text(text, encoding="utf-8")
    return next_action


def one():
    # v3 sentinels: STOP is terminal; PAUSE idles with heartbeat
    if (util.STATE / "STOP").exists():
        print("| - | STOP | halted (delete state/STOP to revive) | - | - |")
        return
    if (util.STATE / "PAUSE").exists():
        cycle = heartbeat_bump()
        if cycle % 6 == 0:   # commit a heartbeat every ~30 min while paused
            rewrite_handoff(cycle, {"id": "-", "action": "paused"}, "paused (state/PAUSE)", None)
            commit_and_push("cycle %d: paused heartbeat" % cycle)
        print("| %d | PAUSE | idle heartbeat | - | - |" % cycle)
        return
    # v3.2 sec.2: YAML lint at the TOP of every cycle, before anything else —
    # a silent-death class must never recur silently. (workflow-level lint
    # usually catches it first; this covers local --one invocations)
    if lint_workflows.run():
        commit_and_push("cycle: lint blocked — workflow YAML failed (v3.2 sec.2)")
        print("| - | lint | blocked: workflow YAML failed — cycle halted | - | - |")
        return
    # v4 deadman: heartbeat gap > 60 min -> blocked issue (once, deduped)
    issues.deadman_check()
    if lock_is_fresh():
        print("| - | lock | fresh — another runner is active, idling | - | - |")
        return
    if not acquire_lock():   # v3.1 R-06: push is the mutex
        print("| - | lock | not acquired — internal commit failed or another runner won | - | - |")
        return
    productive = False
    # v4: issues command channel executes at top priority (start comment,
    # result comment, close on success — v3.2 sec.1)
    try:
        n_cmds = issues.poll_commands()
        if n_cmds:
            productive = True
        # v3.1 R-04: onboard watch runs every cycle before refill
        flipped = onboard_check.run()
        if flipped:
            productive = True
        changed = refill()
        items = parse_items()
        target = next((i for i in items if i["marker"] == " "), None)
        if target is None:
            target = {"marker": " ", "id": next_id(items),
                      "action": "cycle audit: stats + guard checks",
                      "note": "invented (queue was empty)",
                      "cmd": "python scripts/state.py stats"}
            items.append(target)
        if target.get("cmd"):
            summary, cls = run_cmd(target)
        else:
            # v3.1 R-09: no-cmd items MUST append to BLOCKERS.md
            util.append_blocker("%s needs human: %s" % (target["id"], target["action"]))
            target["marker"] = "~"
            target["note"] = "attempted, needs human (BLOCKERS.md)"
            summary, cls = "needs human", "noop"
        if cls == "productive":
            productive = True
        write_items(prune_done(items))
        rotate_logs()
        prune_repo()
        cycle = heartbeat_bump()
        # v4 health + v3.1 R-05 escalation + 25-cycle formal report
        overall = "productive" if productive else "noop"
        health.record(cycle, overall, "%s %s" % (target["id"], summary[:40]))
        health.check(cycle)
        # v4 anti-drift every 50 cycles
        if cycle % 50 == 0:
            drift_check(cycle)
        # v4 self-termination streak (only after 100 clean cycles)
        selfterm_update(productive)
        sha = sh("git rev-parse --short HEAD").stdout.strip()
        next_action = rewrite_handoff(cycle, target, summary, sha)
        csha = commit_and_push("cycle %d: %s %s" % (cycle, target["id"], target["action"][:40]))
        print("| %d | %s %s | %s | %s | %s |" % (cycle, target["id"], target["action"][:30],
                                                summary[:40], csha or "none",
                                                next_action[:60]))
    except Exception as e:
        # the cycle itself must never crash the workflow — record and move on
        util.log_event("cycle_error", error=repr(e)[:300])
        print("| - | cycle | error %r | - | - |" % e)


@util.cli_guard
def main(argv):
    if "--check-lock" in argv:
        sys.exit(1 if lock_is_fresh() else 0)
    if "--refill" in argv:
        changed = refill()
        print("refill: %s" % ("changed" if changed else "no change"))
        if changed:
            commit_and_push("backlog: refill")
        return
    if "--commit" in argv and len(argv) > 1:
        workflow_commit(" ".join(argv[1:]))
        return
    if "--expand-prompts" in argv:
        expand_prompts()
        return
    if "--mark" in argv and len(argv) >= 3:
        mark(argv[1], argv[2], " ".join(argv[3:]) or "manual")
        commit_and_push("backlog: mark %s" % argv[1])
        return
    if "--insert-top" in argv and len(argv) > 1:
        i = argv.index("--insert-top")
        action = argv[i + 1]
        why = argv[i + 2] if len(argv) > i + 2 else "priority"
        cmd = argv[i + 3] if len(argv) > i + 3 else ""
        items = parse_items()
        items.insert(0, {"marker": " ", "id": next_id(items), "action": action,
                         "note": why, "cmd": cmd})
        write_items(prune_done(items))
        commit_and_push("backlog: insert-top %s" % action[:40])
        return
    one()


if __name__ == "__main__":
    main(sys.argv[1:])
