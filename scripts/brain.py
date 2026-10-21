"""Free brain: pollinations picks the next action. No key, no cost, no quota trust.

input : HANDOFF.md + top 5 unchecked backlog items + last 10 log lines
output: state/NEXT_ACTION (one line)

POST https://text.pollinations.ai/openai (openai-compatible, no key) with a
truncated-GET fallback; on any failure falls back to the top backlog item's cmd.
"""
import re
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util
import backlog

ASK = ("Using the state above, pick the single highest-value next action for this "
       "autonomous content pipeline. Answer with the exact shell command to run. "
       "one line only.")


def build_prompt():
    try:
        handoff = backlog.HANDOFF.read_text(encoding="utf-8").strip()
    except Exception:
        handoff = "(no handoff)"
    items = [i for i in backlog.parse_items() if i["marker"] == " "][:5]
    bl = "\n".join("- %s | %s" % (i["id"], i["action"]) for i in items) or "(queue empty)"
    try:
        logs = (util.STATE / "log.jsonl").read_text(encoding="utf-8").splitlines()[-10:]
    except Exception:
        logs = ["(no log)"]
    return "## HANDOFF\n%s\n\n## TOP BACKLOG\n%s\n\n## LOG\n%s\n\n%s" % (
        handoff, bl, "\n".join(logs), ASK)


def ask_post(prompt):
    resp = util.http_json("POST", "https://text.pollinations.ai/openai",
                          {"messages": [{"role": "user", "content": prompt}]},
                          timeout=60, retries=1)
    return ((resp.get("choices") or [{}])[0].get("message") or {}).get("content", "")


def ask_get(prompt):
    q = urllib.parse.quote(prompt[:800], safe="")
    return util.http_raw("GET", "https://text.pollinations.ai/" + q,
                         timeout=60, retries=1).decode(errors="replace")


def fallback():
    for i in backlog.parse_items():
        if i["marker"] == " " and i.get("cmd"):
            return i["cmd"]
    return "python scripts/backlog.py --one"


@util.cli_guard
def main(argv):
    prompt = build_prompt()
    line = ""
    for _attempt in range(2):
        for fn in (ask_post, ask_get):
            try:
                raw = fn(prompt)
            except Exception:
                continue
            raw = (raw or "").strip()
            if raw and "limit reached" not in raw.lower() and not raw.startswith("<"):
                line = raw
                break
        if line:
            break
        time.sleep(33)
    src = "pollinations"
    if not line:
        line = fallback()
        src = "fallback"
    line = re.sub(r"\s+", " ", line.strip().splitlines()[0])[:200]
    (util.STATE / "NEXT_ACTION").write_text(line + "\n", encoding="utf-8")
    util.log_event("brain", source=src, action=line[:120])
    print("[%s] %s" % (src, line))


if __name__ == "__main__":
    main(sys.argv[1:])
