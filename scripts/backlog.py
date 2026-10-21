"""MIRA backlog engine — the infinite queue. Never empty. Never stalls.

Item format (state/BACKLOG.md):
  - [ ] T-0001 | <action> | <why> | cmd: <runnable command>
  - [~] T-0002 | <action> | attempted, <reason>
  - [x] T-0003 | <action> | ok: <result> (or commit sha)

CLI:
  --one            run one cycle: lock -> refill -> top item -> guards -> HANDOFF -> commit
  --refill         ensure >= 5 unchecked items (section 4 sources), commit if changed
  --mark ID x|~ n  mark an item manually
  --check-lock     exit 1 if loop.lock is fresher than 4 minutes (cooldown guard)
  --expand-prompts move +5 scenes / +5 captions from spare pools into the library

Guards implemented per section 9: 4-min cooldown, max 400 commits/day,
1 commit per 2 minutes, log rotation at 5MB, repo prune at 900MB.
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


def throttle():
    delta = time.time() - last_commit_ts()
    if delta < THROTTLE_SECONDS:
        wait = THROTTLE_SECONDS - delta
        print("throttle: sleeping %.0fs (max 1 commit / 2 min)" % wait)
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


def commit_and_push(msg):
    try:
        sh("git add -A")
        if sh("git diff --cached --quiet").returncode == 0:
            return None  # nothing to commit
        if commits_today() >= MAX_COMMITS_PER_DAY:
            util.log_event("commit_skipped", reason="daily cap %d reached" % MAX_COMMITS_PER_DAY)
            return None
        throttle()
        c = sh_list(["git", "commit", "-m", msg])
        if c.returncode != 0:
            util.log_event("commit_failed", error=redact(c.stderr)[-300:])
            return None
        p = sh_list(["git", "push"])
        if p.returncode != 0:
            # multi-runner race (sandbox/Actions overlap): fold remote under ours, retry once
            sh("git fetch origin main")
            r = sh("git rebase -X theirs origin/main")
            if r.returncode == 0:
                p2 = sh_list(["git", "push"])
                if p2.returncode != 0:
                    util.log_event("push_failed", error=redact((p2.stderr or p2.stdout))[-300:])
                    print("push failed after rebase (logged)")
            else:
                util.log_event("rebase_failed", error=redact((r.stderr or ""))[-300:])
                print("rebase failed (logged)")
        return sh("git rev-parse --short HEAD").stdout.strip()
    except Exception as e:
        util.log_event("commit_error", error=repr(e))
        return None


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
    out = []
    try:
        lines = (util.STATE / "log.jsonl").read_text(encoding="utf-8").splitlines()[-150:]
    except Exception:
        return out
    seen = set()
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        kind = rec.get("kind", "")
        if kind in seen:
            continue
        if kind in ("image_failed", "image_attempt_failed"):
            out.append(("retry image generation (recent failure)", "self-repair",
                        "python scripts/gen_image.py --tier free --count 1"))
            seen.add(kind)
        elif kind == "caption_gen_failed":
            out.append(("retry caption generation", "self-repair", "python scripts/gen_caption.py"))
            seen.add(kind)
        elif kind == "push_failed":
            out.append(("retry git push", "self-repair", "git push"))
            seen.add(kind)
        if len(out) >= 2:
            break
    return out


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

    # source 1: daily quotas (aware of today's counts)
    c = today_counts()
    sched = util.load_config("schedule.json").get("quotas", {})
    fmax = sched.get("img_free_day", 8)
    pmax = sched.get("img_paid_day", 4)
    vmax = sched.get("video_day", 2)
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


# ---------------------------------------------------------------- execution

def run_cmd(target):
    cmd = target["cmd"]
    print("running: %s" % cmd)
    try:
        proc = subprocess.run(cmd, shell=True, cwd=util.ROOT,
                              capture_output=True, text=True, timeout=MAX_ITEM_RUNTIME)
        out = (proc.stdout or "").strip()
        if out:
            print(out[-1500:])
        tail = out.splitlines()[-1] if out else ""
        util.log_event("backlog_exec", id=target["id"], rc=proc.returncode, tail=tail[:200])
        if proc.returncode == 0 and "generated 0/" not in out:
            target["marker"] = "x"
            target["note"] = "ok: %s" % (tail[:60] or "rc=0")
            return (tail or "ok")[:80]
        target["marker"] = "~"
        target["note"] = "attempted: %s (rc=%d)" % (tail[:60] or "blocked", proc.returncode)
        return (tail or "blocked")[:80]
    except subprocess.TimeoutExpired:
        target["marker"] = "~"
        target["note"] = "attempted, timeout"
        util.log_event("backlog_timeout", id=target["id"])
        return "timeout"
    except Exception as e:
        target["marker"] = "~"
        target["note"] = "attempted: %r" % e
        return repr(e)[:80]


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
            blockers = "\n".join(lines[:10])
    except Exception:
        pass
    text = ("## CURRENT\n%s %s — %s\n## NEXT ACTION\n%s\n## BLOCKERS\n%s\n"
            "## LAST COMMIT\n%s\n## CYCLE\n%d\n"
            % (target["id"], target["action"], summary, next_action,
               blockers, sha or "none", cycle))
    HANDOFF.write_text(text, encoding="utf-8")


def one():
    touch_lock()
    refill()
    items = parse_items()
    target = next((i for i in items if i["marker"] == " "), None)
    if target is None:
        target = {"marker": " ", "id": next_id(items),
                  "action": "cycle audit: stats + guard checks",
                  "note": "invented (queue was empty)",
                  "cmd": "python scripts/state.py stats"}
        items.append(target)
    print("== cycle item: %s | %s" % (target["id"], target["action"]))
    if target["cmd"]:
        summary = run_cmd(target)
    else:
        util.append_blocker("%s needs human: %s" % (target["id"], target["action"]))
        target["marker"] = "~"
        target["note"] = "attempted, needs human (BLOCKERS.md)"
        summary = "needs human"
    write_items(prune_done(items))
    rotate_logs()
    prune_repo()
    cycle = heartbeat_bump()
    sha = sh("git rev-parse --short HEAD").stdout.strip()
    rewrite_handoff(cycle, target, summary, sha)
    csha = commit_and_push("cycle %d: %s %s" % (cycle, target["id"], target["action"][:40]))
    print("== cycle %d done: %s [%s] commit %s" % (cycle, target["id"], target["marker"], csha or "none"))


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
    if "--expand-prompts" in argv:
        expand_prompts()
        return
    if "--mark" in argv and len(argv) >= 3:
        mark(argv[1], argv[2], " ".join(argv[3:]) or "manual")
        commit_and_push("backlog: mark %s" % argv[1])
        return
    one()


if __name__ == "__main__":
    main(sys.argv[1:])
