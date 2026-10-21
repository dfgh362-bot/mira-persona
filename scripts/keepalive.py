"""MIRA v3.2 sec.3 — deadman hardening. The real watchdog is cron.

The deadman check lives inside the loop, so a dead loop cannot report
itself. keepalive.yml (external cron, every 6h) runs THIS instead:

  - verify every workflow's last run via the API
  - re-enable any workflow whose schedule was disabled
  - if any workflow has 0 runs in 24h: open a "blocked" issue
  - write state/keepalive.json; HEALTH.md carries the chain:
        cron (external) -> loop run -> deadman -> issue

Also keeps the 48h archive sweep (was keepalive.yml's only job, v3).

CLI: python scripts/keepalive.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util
import issues

STALL_HOURS = 24


def _age_hours(iso):
    try:
        t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (util.utcnow() - t).total_seconds() / 3600.0
    except Exception:
        return None


def _api_raw(method, path):
    """direct call that RAISES (unlike issues._api) — keepalive must know."""
    tok = util.gh_token()
    if not tok:
        return None
    return util.http_json(method, "https://api.github.com" + path, payload=None,
                          headers={"Authorization": "Bearer " + tok}, retries=2)


def run():
    repo = "%s/%s" % (util.gh_user(), util.DEFAULTS["repo"])
    try:
        wfs = _api_raw("GET", "/repos/%s/actions/workflows?per_page=100" % repo) or {}
    except Exception as e:
        util.log_event("keepalive_error", where="list_workflows", error=repr(e)[:200])
        print("keepalive: could not list workflows (%r)" % e)
        return
    report = {}
    for wf in wfs.get("workflows", []):
        name = wf.get("name") or wf.get("path", "?").rpartition("/")[2]
        wid = wf.get("id")
        state = wf.get("state")
        if state != "active" and wid:
            # sec.3: re-enable any workflow whose schedule was disabled
            try:
                _api_raw("PUT", "/repos/%s/actions/workflows/%s/enable" % (repo, wid))
                util.log_event("workflow_reenabled", workflow=name, was=state)
                state = "active (re-enabled)"
            except Exception as e:
                util.log_event("reenable_failed", workflow=name, error=repr(e)[:150])
        last_run = None
        age = None
        if wid:
            try:
                runs = _api_raw("GET", "/repos/%s/actions/workflows/%s/runs?per_page=1"
                               % (repo, wid)) or {}
                lr = (runs.get("workflow_runs") or [{}])[0]
                last_run = lr.get("created_at")
                age = _age_hours(last_run)
            except Exception as e:
                util.log_event("keepalive_error", where="runs:%s" % name, error=repr(e)[:150])
        report[name] = {"state": state, "last_run": last_run,
                        "age_h": round(age, 1) if age is not None else None}
    stalled = sorted(n for n, r in report.items()
                    if r["age_h"] is None or r["age_h"] > STALL_HOURS)
    util.save_json(util.STATE / "keepalive.json", {"checked": util.ts(), "stalled": stalled,
                                                   "workflows": report})
    if stalled:
        issues.open_issue(
            "blocked: workflow(s) with 0 runs in %dh: %s" % (STALL_HOURS, ", ".join(stalled)),
            "the cron watchdog (keepalive.yml -> keepalive.py) found stalled workflow(s): "
            "%s.\nlast runs: %s\ncheck the Actions tab, the workflow files, and state/"
            "keepalive.json. dependency chain: cron (external) -> loop run -> deadman "
            "-> issue." % (", ".join(stalled),
                           "; ".join("%s last ran %s (%sh ago)" % (n, report[n]["last_run"],
                                                                    report[n]["age_h"])
                                     for n in stalled)),
            labels=["blocked"])
        util.log_event("keepalive_stalled", workflows=",".join(stalled))
    else:
        util.log_event("keepalive_ok", workflows=len(report))
    # refresh HEALTH.md so the chain + keepalive state land in-repo
    try:
        import health
        health.report()
    except Exception as e:
        util.log_event("keepalive_error", where="health_report", error=repr(e)[:150])
    print("keepalive: %d workflow(s) checked, %d stalled (%s)"
          % (len(report), len(stalled), ", ".join(stalled) or "none"))


@util.cli_guard
def main(argv):
    run()


if __name__ == "__main__":
    main(sys.argv[1:])
