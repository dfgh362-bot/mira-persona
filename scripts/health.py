"""MIRA v4 health + v3.2 sec.4 funnel-first escalation.

- every cycle is classified and recorded in state/health.json
- HEALTH.md written every 25 cycles (and on demand); it carries the
  dependency chain (sec.3): cron (external) -> loop run -> deadman -> issue
- v3.1 R-05 / v3.2 sec.4 — escalation policy, SUPERSEDED by funnel-first:
    1. if unposted (captioned) items are older than 24h:
       escalate POSTING, not generating — insert "post now: <platform>"
       items at the TOP of the backlog, ahead of quota items.
    2. never raise img_free_day while the unposted queue > 20 (any active
       generation boost is reset).
    3. the legacy generation boost (R-05 ratio < 0.2) may fire ONLY when
       the unposted queue is empty.

CLI: python scripts/health.py report|status
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

WINDOW = 25
HEALTH_MD = util.STATE / "HEALTH.md"
FUNNEL_STUCK_HOURS = 24     # sec.4: older than this -> escalate posting
FUNNEL_CAP = 20             # sec.4: never raise generation above this backlog
CHAIN = "cron (external) -> loop run -> deadman -> issue"


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


# ---------------------------------------------------------------- funnel (sec.4)

def funnel_state():
    """pure: (unposted_count, oldest_age_hours) over captioned queue items.
    The bottleneck is the funnel, not the metric — measure it directly."""
    items = util.load_queue().get("items", [])
    now = util.utcnow()
    oldest = 0.0
    n = 0
    for it in items:
        if it.get("status") != "captioned":
            continue
        n += 1
        try:
            t = datetime.strptime(it.get("created") or "", "%Y-%m-%dT%H:%M:%SZ"
                                  ).replace(tzinfo=timezone.utc)
            oldest = max(oldest, (now - t).total_seconds() / 3600.0)
        except Exception:
            pass
    return n, oldest


def should_escalate_posting():
    """funnel-first: unposted items older than 24h -> escalate POSTING."""
    n, oldest = funnel_state()
    if n and oldest > FUNNEL_STUCK_HOURS:
        return True, "funnel: %d unposted, oldest %.1fh > %dh" % (n, oldest, FUNNEL_STUCK_HOURS)
    return False, "funnel ok (%d unposted, oldest %.1fh)" % (n, oldest)


def escalate_posting():
    """insert 'post now: <platform>' items at the TOP of the backlog — ahead
    of quota items (sec.4). Never touches generation quotas."""
    import backlog          # lazy: backlog imports health at module scope
    import onboard_check
    items = backlog.parse_items()
    unchecked = {i["action"] for i in items if i["marker"] == " "}
    accs = util.load_config("accounts.json").get("platforms", {})
    inserted = []
    for name in sorted(onboard_check.POST_CMD):
        if (accs.get(name) or {}).get("status") != "ready":
            continue
        action = "post now: %s" % name
        if action in unchecked:
            continue
        items.insert(0, {"marker": " ", "id": backlog.next_id(items), "action": action,
                         "note": "funnel-first escalation (v3.2 sec.4)",
                         "cmd": onboard_check.POST_CMD[name]})
        inserted.append(name)
    if inserted:
        backlog.write_items(backlog.prune_done(items))
    n, oldest = funnel_state()
    # sec.4: do not raise img_free_day while unposted queue > 20 — reset any
    # active generation boost so the funnel drains first
    if n > FUNNEL_CAP:
        b = util.load_json(util.STATE / "quota_boost.json", {})
        if b.get("multiplier", 1) != 1:
            util.save_json(util.STATE / "quota_boost.json", {"multiplier": 1, "until": None})
            util.log_event("boost_reset", unposted=n, cap=FUNNEL_CAP)
    util.log_decision("D47: v3.2 sec.4 funnel-first escalation — posting escalated "
                      "(%d post-now item(s) inserted ahead of quota items: %s); generation "
                      "quotas untouched; unposted=%d oldest=%.1fh. R-05 generation "
                      "escalation only fires when the unposted queue is empty."
                      % (len(inserted), ", ".join(inserted) or "-", n, oldest))
    util.log_event("escalated_posting", items=len(inserted), platforms=",".join(inserted))


def should_escalate():
    """legacy R-05 ratio check — selftest exercises it. v3.2: callers only
    reach this when the unposted queue is EMPTY (sec.4)."""
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
    """legacy R-05 generation boost — guarded by sec.4: refused while the
    unposted queue exceeds the cap (never raise img_free_day then)."""
    n, _ = funnel_state()
    if n > FUNNEL_CAP:
        util.log_event("escalation_refused", reason="unposted %d > cap %d (sec.4)"
                       % (n, FUNNEL_CAP))
        return
    until = (util.utcnow() + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    util.save_json(util.STATE / "quota_boost.json", {"multiplier": 2, "until": until})
    util.log_decision("D38/D47: quota escalation — PRODUCTIVE/NOOP < 0.2 over 25 "
                      "cycles AND unposted queue empty (v3.2 sec.4); img_free_day and "
                      "video_day doubled for 24h (until %s)." % until)
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
    unposted, oldest = funnel_state()
    ka = util.load_json(util.STATE / "keepalive.json", {})
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
        "- funnel (v3.2): %d captioned unposted, oldest %.1fh (stuck>%dh, gen-cap %d)"
        % (unposted, oldest, FUNNEL_STUCK_HOURS, FUNNEL_CAP),
        "- quota boost (R-05): %s" % _boost_text(),
        "- commits today: %s / 400" % commits,
        "- dependency chain (v3.2 sec.3): %s" % CHAIN,
        "- keepalive last check: %s (state/keepalive.json)" % (ka.get("checked") or "never"),
        "- generated: %s" % util.ts(),
    ]
    HEALTH_MD.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    util.log_event("health_reported", status=status(), p=p, n=n, unposted=unposted)
    print("HEALTH.md: %s (P=%d N=%d, funnel %d unposted)" % (status(), p, n, unposted))


def check(cycle):
    """called at the end of every cycle: funnel-first escalation + the
    25-cycle formal report. Supersedes the bare R-05 trigger (v3.2 sec.4)."""
    b = util.load_json(util.STATE / "quota_boost.json", {})
    try:
        mult = int(b.get("multiplier", 1))
    except Exception:
        mult = 1
    if mult > 1 and not b.get("until"):
        util.save_json(util.STATE / "quota_boost.json", {"multiplier": 1, "until": None})
    n, oldest = funnel_state()
    if n and oldest > FUNNEL_STUCK_HOURS:
        # 1) funnel stuck -> escalate POSTING, not generating
        escalate_posting()
    elif n == 0:
        # 3) legacy generation escalation ONLY when the unposted queue is empty
        esc, why = should_escalate()
        if esc:
            escalate()
        else:
            util.log_event("health_check", escalation=why)
    else:
        # 2) draining: fresh unposted items exist, schedule is keeping up
        util.log_event("health_check", funnel="draining", unposted=n, oldest_h=round(oldest, 1))
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
