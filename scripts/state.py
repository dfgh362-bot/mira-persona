"""MIRA state machine: queued -> captioned -> posted -> archived.

CLI:
  python scripts/state.py stats
  python scripts/state.py list [--status queued|captioned|posted|archived]
  python scripts/state.py show <id>
  python scripts/state.py advance <id> [--to queued|captioned|posted|archived]
  python scripts/state.py archive --older-than 48h
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

TRANSITIONS = {"queued": "captioned", "captioned": "posted", "posted": "archived"}


def _parse_age(s):
    m = {"h": 1, "d": 24}
    num = "".join(ch for ch in s if ch.isdigit())
    unit = "".join(ch for ch in s if ch.isalpha())
    return float(num) * m.get(unit, 24)


@util.cli_guard
def main(argv):
    if not argv or argv[0] == "stats":
        queue = util.load_queue()
        counts = {}
        for it in queue["items"]:
            counts[it["status"]] = counts.get(it["status"], 0) + 1
        ledger = util.load_ledger()
        print("items: %d  %s" % (len(queue["items"]), counts))
        print("ledger:", ledger["counts"], "updated:", ledger["updated"])
        return

    cmd = argv[0]
    queue = util.load_queue()

    if cmd == "list":
        want = None
        if "--status" in argv:
            want = argv[argv.index("--status") + 1]
        for it in queue["items"]:
            if want and it["status"] != want:
                continue
            print("%s  %-9s %-5s %s" % (it["id"], it["status"], it["tier"], (it.get("caption") or "")[:50]))
        return

    if cmd == "show" and len(argv) > 1:
        it = util.find_item(queue, argv[1])
        print(json.dumps(it, indent=2, ensure_ascii=False) if it else "not found")
        return

    if cmd == "advance" and len(argv) > 1:
        it = util.find_item(queue, argv[1])
        if not it:
            print("not found")
            return
        target = None
        if "--to" in argv:
            target = argv[argv.index("--to") + 1]
        else:
            target = TRANSITIONS.get(it["status"])
        if target not in ("queued", "captioned", "posted", "archived"):
            print("bad target state")
            return
        old = it["status"]
        it["status"] = target
        if target == "posted":
            it["posted_at"] = util.ts()
        util.save_queue(queue)
        util.log_event("state_advanced", id=it["id"], frm=old, to=target)
        print("%s: %s -> %s" % (it["id"], old, target))
        return

    if cmd == "archive" and "--older-than" in argv:
        hours = _parse_age(argv[argv.index("--older-than") + 1])
        cutoff = util.utcnow() - timedelta(hours=hours)
        moved = 0
        for it in queue["items"]:
            if it["status"] != "posted":
                continue
            try:
                when = datetime.strptime(it.get("posted_at") or it.get("created", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if when < cutoff:
                it["status"] = "archived"
                moved += 1
        util.save_queue(queue)
        util.log_event("archived", moved=moved, older_than_hours=hours)
        print("archived %d item(s)" % moved)
        return

    print(__doc__)


import json  # noqa: E402  (used by show)

if __name__ == "__main__":
    main(sys.argv[1:])
