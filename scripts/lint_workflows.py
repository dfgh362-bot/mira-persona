"""MIRA v3.2 sec.2 — YAML lint: the silent-death guard.

A step name containing ":" once broke the workflow parse (D45): no dispatch,
no cron, no error. That class must never recur silently. This linter runs at
the TOP of every cycle, before anything else:

  - yaml.safe_load every .github/workflows/*.yml
  - assert each has a trigger and >= 1 job
  - on failure: open a "blocked" issue immediately, halt the cycle (exit 1)

It is wired into loop.yml / post.yml / generate.yml / inbox.yml as a hard
step and into backlog.one() as the first action (both paths converge here;
open_issue dedupes so the alarm fires once). keepalive.yml runs it too but
does NOT halt — the watchdog layer must survive dead layers and keep
watching (sec.3 chain: cron -> loop run -> deadman -> issue).

Self-bootstraps PyYAML if the runner image lacks it. `on:` parses as boolean
True under YAML 1.1 (PyYAML) — both key spellings are accepted.

CLI: python scripts/lint_workflows.py          (open blocked issue on failure)
     python scripts/lint_workflows.py --quiet   (no issue; local pre-commit)
Exit 0 clean / exit 1 blocked (cycle must halt).
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

WF_DIR = ".github/workflows"


def _yaml():
    try:
        import yaml
        return yaml
    except ImportError:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "pyyaml"],
                           capture_output=True, text=True, timeout=240)
        if r.returncode != 0:   # PEP 668 guard for system pythons
            subprocess.run([sys.executable, "-m", "pip", "install", "--quiet",
                             "--break-system-packages", "pyyaml"],
                            capture_output=True, timeout=240)
        import yaml
        return yaml


def _trigger_of(doc):
    """`on:` may parse as string key or boolean True (YAML 1.1)."""
    return doc.get("on") if isinstance(doc.get("on"), (dict, str, list)) else doc.get(True)


def lint_all(root=None):
    """pure check — returns a list of error strings ([] = clean).
    selftest exercises this with synthetic good/bad trees (v3.2)."""
    yaml = _yaml()
    base = Path(root) if root else util.ROOT
    files = sorted((base / WF_DIR).glob("*.yml")) + sorted((base / WF_DIR).glob("*.yaml"))
    if not files:
        return ["no workflow files found under %s" % WF_DIR]
    errors = []
    for f in files:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append("%s: yaml parse error: %s" % (f.name, str(e).replace("\n", " ")[:160]))
            continue
        if not isinstance(doc, dict):
            errors.append("%s: not a workflow mapping" % f.name)
            continue
        trig = _trigger_of(doc)
        if not trig or (isinstance(trig, dict) and not trig) or (isinstance(trig, str) and not trig.strip()):
            errors.append("%s: no trigger (missing or empty `on:`)" % f.name)
        jobs = doc.get("jobs")
        if not isinstance(jobs, dict) or not jobs:
            errors.append("%s: no jobs (needs >= 1)" % f.name)
        if isinstance(jobs, dict):
            for jname, job in jobs.items():
                if not isinstance(job, dict) or "runs-on" not in job:
                    errors.append("%s: job '%s' has no runs-on" % (f.name, jname))
    return errors


def run(open_issue=True):
    """lint the real tree; open the blocked issue + return exit code."""
    errors = lint_all()
    n = len(sorted((util.ROOT / WF_DIR).glob("*.yml")))
    if not errors:
        util.log_event("lint_ok", files=n)
        print("lint: %d workflow file(s) parse, all have trigger + jobs" % n)
        return 0
    util.log_event("lint_failed", files=n, errors=errors[:10])
    body = ("the YAML lint at the top of the cycle failed — this class is a "
            "silent death (no dispatch, no cron, no error; D45). the cycle is "
            "halted until fixed.\n\nerrors:\n%s\n\nfix the file(s), commit to "
            "main; the loop self-resumes on the next cron tick (*/5)." % "\n".join("- %s" % e for e in errors[:10]))
    if open_issue:
        try:
            import issues
            issues.open_issue("blocked: workflow YAML lint failed (%d error(s))" % len(errors),
                              body, labels=["blocked"], dedupe=40)
        except Exception as e:
            util.log_event("error", where="lint_open_issue", error=repr(e))
    print("LINT FAILED (%d error(s)):" % len(errors))
    for e in errors[:10]:
        print("  - %s" % e)
    return 1


@util.cli_guard
def main(argv):
    quiet = "--quiet" in argv
    raise SystemExit(run(open_issue=not quiet))


if __name__ == "__main__":
    main(sys.argv[1:])
