"""MIRA v4 health — PRODUCTIVE vs NOOP ledger.

- every cycle is classified and recorded in state/health.json
- HEALTH.md written every 25 cycles (and on demand)
- v3.1 R-05: if PRODUCTIVE/NOOP < 0.2 over the last 25 cycles, double
  img_free_day and video_day for 24h (state/quota_boost.json, logged).

CLI: python scripts/health.py report|status
"""
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

WINDOW = 25
HEALTH_MD = util.STATE / "HEALTH.md"


def _data():
    return util.load_json(util.STATE / "health.json", {"cycles": []})


def record(cycle, cls, why=""):
    d = _data()
    cyc = d.setdefault("cycles", [])
    cyc.append({"c": int(cycle), "cls": cls, "why": str(why).replace("|", "/")[:80]})
    d["cycles"] = cyc[-200:]
    util.save_json(util.STATE / "health.json", d)


def stats():
    cyc = _data().get("cycles", [])[-WINDOW:]
    p = sum(1 for e in cyc if e.get("cls") == "productive")
    n = sum(1 for e in cyc if e.get("cls") == "noop")
    return p, n


def ratio():
    p, n = stats()
    return (p / n) if n else None


def status():
    r = ratio()
    if r is None or r >= 0.2:
        return "healthy"
    return "degraded"


def should_escalate():
    """pure check so selftest can exercise it (R-05)."""
    cyc = _data().get("cycles", [])[-WINDOW:]
    if len(cyc) < WINDOW:
        return False, "window not full (%d/%d)" % (len(cyc), WINDOW)
    p = sum(1 for e in cyc if e.get("cls") == "productive")
    n = sum(1 for e in cyc if e.get("cls") == "noop")
    if n == 0:
        return False, "no noop cycles"
    if (p / n) >= 0.2:
        return False, "ratio ok (%.2f, %dP/%dN)" % (p / n, p, n)
    return True, "ratio %.2f (%dP/%dN) < 0.2" % (p / n, p, n)


def escalate():
    until = (util.utcnow() + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    util.save_json(util.STATE / "quota_boost.json", {"multiplier": 2, "until": until})
    util.log_decision("D38: v3.1 R-05 quota escalation — PRODUCTIVE/NOOP < 0.2 over 25 "
                      "cycles; img_free_day and video_day doubled for 24h (until %s)." % until)
    util.log_event("quota_escalated", multiplier=2, until=until)


def _boost_text():
    b = util.load_json(util.STATE / "quota_boost.json", {})
    try:
        mult = int(b.get("multiplier", 1))
    except Exception:
        mult = 1
    if mult > 1:
        return "x%d until %s (img_free_day=%d, video_day=%d)" % (
            mult, b.get("until"), util.effective_quota("img_free_day"),
            util.effective_quota("video_day"))
    return "none (img_free_day=%d, video_day=%d)" % (
        util.effective_quota("img_free_day"), util.effective_quota("video_day"))


def report():
    p, n = stats()
    r = ratio()
    try:
        import subprocess
        commits = subprocess.run(["git", "rev-list", "--count", "HEAD", "--since=midnight"],
                                 cwd=util.ROOT, capture_output=True, text=True,
                                 timeout=30).stdout.strip()
    except Exception:
        commits = "?"
    lines = [
        "# HEALTH",
        "",
        "status: **%s**" % status(),
        "",
        "- classified window: last %d cycles" % WINDOW,
        "- productive: %d" % p,
        "- noop: %d" % n,
        "- ratio: %s" % ("n/a (no noop)" if r is None else "%.2f" % r),
        "- quota boost (R-05): %s" % _boost_text(),
        "- commits today: %s / 400" % commits,
        "- generated: %s" % util.ts(),
    ]
    HEALTH_MD.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    util.log_event("health_reported", status=status(), p=p, n=n)
    print("HEALTH.md: %s (P=%d N=%d)" % (status(), p, n))


def check(cycle):
    """called at the end of every cycle: escalation + 25-cycle formal report."""
    b = util.load_json(util.STATE / "quota_boost.json", {})
    try:
        mult = int(b.get("multiplier", 1))
    except Exception:
        mult = 1
    if mult > 1 and not b.get("until"):
        util.save_json(util.STATE / "quota_boost.json", {"multiplier": 1, "until": None})
    esc, why = should_escalate()
    if esc:
        escalate()
    else:
        util.log_event("health_check", escalation=why)
    if int(cycle) % WINDOW == 0:
        report()


@util.cli_guard
def main(argv):
    if argv and argv[0] == "status":
        print(status())
        return
    report()


if __name__ == "__main__":
    main(sys.argv[1:])
