"""MIRA v3.1 R-01 executor — map recent log failures to concrete repairs.

--scan reads the last 200 log.jsonl records:
  backlog_timeout -> requeue the item (unless anti-thrash capped)
  push_failed     -> git push
  commit_failed   -> shared commit path (backlog.py --commit)
  error           -> mailtm sweep / re-run the failing script once /
                     legacy 'margin' signature -> site rebuild /
                     unmapped -> BLOCKERS.md (needs human triage)
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util


def sh(cmd, timeout=420):
    return subprocess.run(cmd, shell=True, cwd=util.ROOT,
                           capture_output=True, text=True, timeout=timeout)


def scan():
    try:
        lines = (util.STATE / "log.jsonl").read_text(encoding="utf-8").splitlines()[-200:]
    except Exception:
        lines = []
    thrash = util.load_json(util.STATE / "thrash.json", {})
    did, seen = [], set()
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        kind = rec.get("kind", "")
        if kind == "backlog_timeout":
            tid = rec.get("id")
            if tid and tid not in seen and int(thrash.get(tid, {}).get("count", 0)) < 3:
                seen.add(tid)
                r = sh("python scripts/backlog.py --mark %s ' ' requeued-by-selfheal" % tid)
                did.append("requeue %s rc=%d" % (tid, r.returncode))
        elif kind == "push_failed":
            if "push" not in seen:
                seen.add("push")
                r = sh("git push")
                did.append("git push rc=%d" % r.returncode)
        elif kind == "commit_failed":
            if "commit" not in seen:
                seen.add("commit")
                r = sh("python scripts/backlog.py --commit repair: retry after commit_failed")
                did.append("commit-retry rc=%d" % r.returncode)
        elif kind == "error":
            script = rec.get("script") or ""
            err = str(rec.get("error") or "")
            blob = script + " " + err
            if "mailtm" in blob:
                if "mailtm" not in seen:
                    seen.add("mailtm")
                    r = sh("python scripts/mailtm.py verify --all")
                    did.append("mailtm sweep rc=%d" % r.returncode)
            elif "margin" in err:
                if "margin" not in seen:
                    seen.add("margin")
                    r = sh("python scripts/build_site.py")
                    did.append("site rebuild rc=%d" % r.returncode)
            elif script.endswith(".py") and "selfheal" not in script and "selftest" not in script:
                if script not in seen:
                    seen.add(script)
                    r = sh("python %s" % script)
                    did.append("rerun %s rc=%d" % (script, r.returncode))
            elif err and "unmapped" not in seen:
                seen.add("unmapped")
                util.append_blocker("unmapped error needs triage: %s" % err.replace("|", "/")[:80])
                did.append("blocker noted")
    util.log_event("selfheal_run", repairs=did[:20])
    for d in did:
        print(" -", d)
    if not did:
        print("nothing to heal")


@util.cli_guard
def main(argv):
    if "--scan" in argv:
        scan()
        return
    print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
