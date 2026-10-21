"""MIRA shared utilities. stdlib only.

v3.1 sec.0: cli_guard no longer swallows exceptions — it logs the traceback
tail, writes state/last_error.json, prints to stderr and exits 1. The parent
(backlog run_cmd) copies the tail into the ITEM NOTE. A swallowed exception
is a lie.
"""
import json
import os
import random
import re
import string
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
PROMPTS = ROOT / "prompts"
STATE = ROOT / "state"
CONTENT = ROOT / "content"

DEFAULTS = {
    "repo": "mira-persona",
    "branch": "main",
    "tz": "UTC",
    "img_free_day": 8,
    "img_paid_day": 4,
    "video_day": 2,
}

UA = "mira-bot/1.0 (github-actions)"


def utcnow():
    return datetime.now(timezone.utc)


def ts():
    return utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def today():
    return utcnow().strftime("%Y-%m-%d")


def _append_jsonl(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def log_event(kind, **kw):
    rec = {"ts": ts(), "kind": kind}
    rec.update(kw)
    _append_jsonl(STATE / "log.jsonl", rec)


def log_decision(decision, **kw):
    rec = {"ts": ts(), "decision": decision}
    rec.update(kw)
    _append_jsonl(STATE / "decisions.jsonl", rec)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_config(name):
    return load_json(CONFIG / name, {})


def load_queue():
    return load_json(CONTENT / "queue.json", {"items": []})


def save_queue(queue):
    save_json(CONTENT / "queue.json", queue)


def load_posted():
    return load_json(CONTENT / "posted.json", {"posts": []})


def save_posted(posted):
    save_json(CONTENT / "posted.json", posted)


def load_ledger():
    led = load_json(STATE / "ledger.json", {"counts": {"free": 0, "paid": 0, "video": 0, "voice": 0}, "updated": None})
    led.setdefault("counts", {}).setdefault("free", 0)
    led["counts"].setdefault("paid", 0)
    led["counts"].setdefault("video", 0)
    led["counts"].setdefault("voice", 0)
    return led


def save_ledger(led):
    led["updated"] = ts()
    save_json(STATE / "ledger.json", led)


# ---------------------------------------------------------------- http

def http_json(method, url, payload=None, headers=None, timeout=40, retries=3):
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        hdrs.setdefault("Content-Type", "application/json")
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode(errors="replace") or "{}"
                try:
                    return json.loads(body)
                except Exception:
                    return {"raw": body[:2000]}
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:500]
            last = "HTTP %s: %s" % (e.code, body)
            if e.code in (400, 401, 403, 404, 409, 422):
                raise RuntimeError(last)
        except Exception as e:
            last = repr(e)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("%s %s failed after %d tries: %s" % (method, url, retries, last))


def http_raw(method, url, body=None, headers=None, timeout=120, retries=2):
    hdrs = {"User-Agent": UA}
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = "HTTP %s: %s" % (e.code, e.read().decode(errors="replace")[:300])
            if e.code in (400, 401, 403, 404, 409, 422):
                raise RuntimeError(last)
        except Exception as e:
            last = repr(e)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("%s %s failed: %s" % (method, url, last))


def http_get(url, timeout=30):
    """follow redirects, return status code; used for verification links."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def http_download(url, dest, timeout=300, retries=3, min_size=2000):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                blob = r.read()
            if len(blob) < min_size:
                raise RuntimeError("suspiciously small download (%db)" % len(blob))
            with open(dest, "wb") as f:
                f.write(blob)
            return dest
        except Exception as e:
            last = repr(e)
            time.sleep(2 + 2 * attempt)
    raise RuntimeError("download %s failed: %s" % (url, last))


# ---------------------------------------------------------------- identity helpers

def gh_user():
    return (os.environ.get("GH_USER")
            or load_json(CONFIG / "gh.json", {}).get("user")
            or load_config("accounts.json").get("gh", {}).get("user")
            or "GH_USER_PLACEHOLDER")


def append_blocker(line):
    p = STATE / "BLOCKERS.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        txt = p.read_text(encoding="utf-8") if p.exists() else ""
    except Exception:
        txt = ""
    key = line[:48]
    for existing in txt.splitlines():          # v3.1 R-09: dedupe (no spam)
        if key in existing:
            return
    if "(none)" in txt:
        txt = txt.replace("(none)", "").rstrip() + "\n"
    with open(p, "a", encoding="utf-8") as f:
        f.write("- %s (ts %s)\n" % (line, ts()))
    log_event("blocker_added", line=line[:200])


def jsdelivr(rel_path):
    rel = str(rel_path).replace("\\", "/")
    while rel.startswith("/"):
        rel = rel[1:]
    return "https://cdn.jsdelivr.net/gh/%s/%s@main/%s" % (gh_user(), DEFAULTS["repo"], rel)


def raw_github(rel_path):
    """fallback origin when jsDelivr has an upstream outage (D35)"""
    rel = str(rel_path).replace("\\", "/")
    while rel.startswith("/"):
        rel = rel[1:]
    return "https://raw.githubusercontent.com/%s/%s/main/%s" % (gh_user(), DEFAULTS["repo"], rel)


def same_origin(rel_path):
    """v3.1 R-03 site middle tier: same-origin /content/... (Pages artifact
    carries site/content/ via build_site sync)."""
    rel = str(rel_path).replace("\\", "/")
    while rel.startswith("/"):
        rel = rel[1:]
    return "/" + rel


def site_media_tiers(rel_path):
    """v3.1 R-03: site delivery order jsDelivr -> /content/... -> raw.gh"""
    return [jsdelivr(rel_path), same_origin(rel_path), raw_github(rel_path)]


def remote_media_candidates(item):
    """v3.1 R-03: remote (telegram/pinterest/reddit) delivery order
    jsDelivr -> raw.gh, tried at send time."""
    item = item or {}
    primary = item.get("cdn") or jsdelivr(item.get("file", ""))
    out = [primary]
    raw = raw_github(item.get("file", ""))
    if raw not in out:
        out.append(raw)
    return out


def gh_token():
    """v3.1: token for API calls. env GH_TOKEN/GITHUB_TOKEN (Actions),
    else parsed from the origin remote URL (local runs). PAT optional per R-08."""
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if t:
        return t
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT,
                             capture_output=True, text=True, timeout=15).stdout.strip()
        m = re.search(r"://[^:/@]+:([^@]+)@", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def effective_quota(key, default=None):
    """v3.1 R-05: schedule.json quota x escalation multiplier while active
    (state/quota_boost.json {multiplier, until})."""
    sched = load_config("schedule.json").get("quotas", {})
    if default is None:
        default = DEFAULTS.get(key, 8)
    base = sched.get(key, default)
    boost = load_json(STATE / "quota_boost.json", {})
    try:
        until = datetime.strptime(boost.get("until") or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        mult = int(boost.get("multiplier", 1))
        if mult > 1 and until > utcnow():
            return int(base) * mult
    except Exception:
        pass
    return int(base)


def rand_localpart():
    words = ["mira", "solis", "lisbon", "film", "oat", "cortado", "grain", "camera",
             "light", "rooftop", "roll", "quiet", "golden", "window", "tea"]
    return random.choice(words) + str(random.randint(100, 9999))


def rand_password(n=14):
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))


# ---------------------------------------------------------------- queue / posting

def pick_due_item(queue, tier="free"):
    for it in queue.get("items", []):
        if it.get("status") == "captioned" and it.get("tier") == tier:
            return it
    return None


def find_item(queue, item_id):
    for it in queue.get("items", []):
        if it.get("id") == item_id:
            return it
    return None


def already_posted(posted, item_id, platform):
    return any(p.get("item") == item_id and p.get("platform") == platform
               for p in posted.get("posts", []))


def has_pinned(posted, platform):
    return any(p.get("platform") == platform and p.get("pinned")
               for p in posted.get("posts", []))


def record_post(item, platform, url=None, pinned=False, item_id=None):
    posted = load_posted()
    posted["posts"].append({
        "item": item_id or (item or {}).get("id"),
        "platform": platform,
        "url": url,
        "pinned": pinned,
        "ts": ts(),
    })
    save_posted(posted)
    log_event("post", item=item_id or (item or {}).get("id"), platform=platform, url=url)


def mark_posted(item):
    item["status"] = "posted"
    item["posted_at"] = ts()
    save_queue(load_queue())


def set_platform_status(platform, status):
    try:
        pf = load_config("platforms.json")
        entry = pf.get("tiers", {}).get(platform)
        if entry is not None:
            entry["status"] = status
            save_json(CONFIG / "platforms.json", pf)
    except Exception as e:
        log_event("error", where="set_platform_status", error=repr(e))


# ---------------------------------------------------------------- cli guard

def cli_guard(fn):
    def wrapper(argv):
        try:
            return fn(argv)
        except SystemExit:
            raise
        except Exception as e:
            # v3.1 sec.0: invisible crashes are the worst bug class.
            tb = traceback.format_exc().strip().splitlines()
            tail = tb[-1] if tb else repr(e)
            log_event("error", script=sys.argv[0], where=getattr(fn, "__name__", "cli"),
                      error=tail[:300])
            try:
                save_json(STATE / "last_error.json",
                          {"ts": ts(), "script": sys.argv[0],
                           "fn": getattr(fn, "__name__", "cli"), "tb_tail": tail[:300]})
            except Exception:
                pass
            print("mira-cli-guard: %s" % tail, file=sys.stderr)
            sys.exit(1)   # the parent sees the failure; it records the note
    return wrapper
