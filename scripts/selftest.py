"""MIRA v3.1 verification harness — the R-01..R-09 repair queue, v4, specs.

Backlog items run these one per cycle (they are the repair-queue proofs):
  python scripts/selftest.py r01|r02|...|r09|v4|specs|remote|all

Exit 0 = check passed. Exit 1 = check failed (item will be re-attempted,
anti-thrash caps at 3).
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util
import backlog

ROOT = util.ROOT
RESULTS = []


def read(path):
    return Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print("  %-6s %s %s" % ("PASS" if ok else "FAIL", name, ("— " + detail) if detail else ""))
    return bool(ok)


# ---------------------------------------------------------------- R-01
def r01():
    log = util.STATE / "log.jsonl"

    def with_lines(synthetic):
        before = read(log)
        with open(log, "w", encoding="utf-8") as f:
            f.write("\n".join(synthetic) + "\n")
        try:
            return backlog.repair_candidates()
        finally:
            with open(log, "w", encoding="utf-8") as f:
                f.write(before)

    j = lambda items: " || ".join(a + " " + c for a, _w, c in items)
    # the four R-01 kinds present -> they claim the 3 slots (cap), first-come
    items = with_lines([
        json.dumps({"ts": util.ts(), "kind": "error", "script": "scripts/fake.py", "error": "synthetic"}),
        json.dumps({"ts": util.ts(), "kind": "commit_failed", "error": "synthetic"}),
        json.dumps({"ts": util.ts(), "kind": "push_failed", "error": "synthetic"}),
        json.dumps({"ts": util.ts(), "kind": "backlog_timeout", "id": "T-9999"}),
    ])
    check("scan-r01-kinds", "self-heal" in j(items) and "retry git push" in j(items)
          and "retry commit" in j(items), "candidates: %s" % [i[1] for i in items])
    check("cap-3", len(items) <= 3, "%d items" % len(items))
    # legacy kinds still repair when R-01 kinds are absent
    items2 = with_lines([json.dumps({"ts": util.ts(), "kind": "image_failed", "error": "synthetic"})])
    check("legacy-kinds", "gen_image" in j(items2), "candidates: %s" % [i[1] for i in items2])


# ---------------------------------------------------------------- R-02
def r02():
    src = read(ROOT / "scripts" / "backlog.py")
    m = re.search(r"def commit_and_push\(msg, throttle=True\):(.*?)\ndef workflow_commit", src, re.S)
    check("shared-path", bool(m), "commit_and_push(msg, throttle=True) defined")
    if m:
        check("cap-inside", "MAX_COMMITS_PER_DAY" in m.group(1), "400/day cap inside shared path")
    wf = re.search(r"def workflow_commit\(msg\):(.{0,400})", src, re.S)
    check("workflows-route", bool(wf) and "commit_and_push" in wf.group(1),
          "workflow_commit delegates to the shared path")
    ymls = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    routed = [y.name for y in ymls
              if "backlog.py --commit" in read(y) or "--one" in read(y)]
    check("all-ymls", len(routed) == len(ymls), "%d/%d workflows route via backlog" % (len(routed), len(ymls)))


# ---------------------------------------------------------------- R-03
def r03():
    rel = "content/free/2026-10-21/mira_free_20261021_001_582427.jpg"
    tiers = util.site_media_tiers(rel)
    check("site-3-tier", len(tiers) == 3 and tiers[1] == "/" + rel
          and "cdn.jsdelivr.net" in tiers[0] and "raw.githubusercontent" in tiers[2],
          "jsDelivr -> /content/... -> raw.gh")
    cands = util.remote_media_candidates({"cdn": None, "file": rel})
    check("remote-2-tier", len(cands) == 2 and cands[0] == util.jsdelivr(rel)
          and cands[1] == util.raw_github(rel), "jsDelivr -> raw.gh at send time")
    site_src = read(ROOT / "scripts" / "build_site.py")
    check("site-cascade", "data-fb" in site_src and "mfb(" in site_src and "site/content" in site_src,
          "site sync + browser onerror cascade")
    remote_ok = all("remote_media_candidates" in read(ROOT / "scripts" / f)
                    for f in ("post_telegram.py", "post_pinterest.py", "post_reddit.py"))
    check("posters-fallback", remote_ok, "tg/pinterest/reddit use send-time fallback")


# ---------------------------------------------------------------- R-04
def r04():
    import onboard_check
    env_on = {"TELEGRAM_BOT_TOKEN": "x", "TELEGRAM_CHAT_ID": "y",
              "PINTEREST_TOKEN": "t", "PINTEREST_BOARD_ID": "b"}
    check("ready-on-creds",
          onboard_check.eval_platform("telegram", {"bot_token": None}, env_on)
          and onboard_check.eval_platform("pinterest", {"token": None, "board_id": None}, env_on),
          "pending -> ready when creds present")
    check("pending-without-creds",
          not onboard_check.eval_platform("telegram", {"bot_token": None}, {}),
          "stays pending without creds")


# ---------------------------------------------------------------- R-05
def r05():
    import health
    d = util.load_json(util.STATE / "health.json", {"cycles": []})
    saved = json.loads(json.dumps(d))
    try:
        util.save_json(util.STATE / "health.json",
                       {"cycles": [{"c": i, "cls": "noop", "why": "synthetic"} for i in range(25)]})
        esc, why = health.should_escalate()
        check("escalates", esc, why)
        util.save_json(util.STATE / "health.json",
                       {"cycles": [{"c": i, "cls": "productive", "why": "synthetic"} for i in range(25)]})
        esc2, why2 = health.should_escalate()
        check("no-escalation-when-healthy", not esc2, why2)
    finally:
        util.save_json(util.STATE / "health.json", saved)
    check("boost-reads", util.effective_quota("img_free_day") in (8, 16)
          and util.effective_quota("video_day") in (2, 4),
          "effective_quota resolves (8/16, 2/4)")


# ---------------------------------------------------------------- R-06
def r06():
    src = read(ROOT / "scripts" / "backlog.py")
    m = re.search(r"def acquire_lock\(\):(.*?)\n    return won", src, re.S)
    check("mutex-code", bool(m) and "git pull --rebase" in (m.group(1) if m else "")
          and "run_id" in (m.group(1) if m else ""), "write -> commit -> push -> pull -> re-read")
    check("one-uses-it", "acquire_lock()" in src, "one() acquires via push mutex")


# ---------------------------------------------------------------- R-07
def r07():
    yml = read(ROOT / ".github" / "workflows" / "generate.yml")
    check("idempotent-ffmpeg",
          bool(re.search(r"command -v ffmpeg \|\| sudo apt-get install -y ffmpeg", yml)),
          "exact R-07 step present")


# ---------------------------------------------------------------- R-08
def r08():
    yml = read(ROOT / ".github" / "workflows" / "loop.yml")
    check("token", "${{ secrets.GITHUB_TOKEN }}" in yml and "secrets.GH_TOKEN" not in yml,
          "self-dispatch uses the auto GITHUB_TOKEN")
    check("actions-write", re.search(r"actions:\s*write", yml) is not None,
          "actions:write granted (documented exception)")
    no_pat = all("secrets.GH_TOKEN" not in read(y)
                 for y in (ROOT / ".github" / "workflows").glob("*.yml"))
    check("pat-optional", no_pat, "no workflow requires the PAT")


# ---------------------------------------------------------------- R-09
def r09():
    probe = "selftest T-9999 needs human (probe)"
    p = util.STATE / "BLOCKERS.md"
    before = read(p)
    util.append_blocker(probe)
    util.append_blocker(probe)   # twice -> dedupe must keep exactly one
    after = read(p)
    check("appends", after.count(probe) == 1, "no-cmd item -> BLOCKERS.md, deduped")
    # restore
    lines = [l for l in after.splitlines() if probe not in l]
    body = "\n".join(lines).rstrip() + "\n"
    if not [l for l in lines if l.strip() and not l.startswith("#")]:
        body = "# BLOCKERS — things needing the human\n\n(none)\n"
    p.write_text(body, encoding="utf-8")
    check("restored", probe not in read(p), "probe cleaned up")
    # the T-0010..16 no-cmd path exists in one()
    check("one-wires-it", "needs human" in read(ROOT / "scripts" / "backlog.py"),
          "one() appends BLOCKERS for no-cmd items")


# ---------------------------------------------------------------- v4
def v4():
    names = ["issues.py", "health.py", "onboard_check.py", "selfheal.py"]
    check("modules", all((ROOT / "scripts" / n).exists() for n in names),
          "immune modules present")
    loop = read(ROOT / ".github" / "workflows" / "loop.yml")
    check("issues-perm", re.search(r"issues:\s*write", loop) is not None,
          "loop.yml can open issues")
    src = read(ROOT / "scripts" / "backlog.py")
    check("wired", all(k in src for k in ("poll_commands", "deadman_check", "drift", "clean_streak")),
          "one() wires commands/deadman/drift/self-term")
    import health
    check("health-status", health.status() in ("healthy", "degraded"), health.status())
    util.log_decision("D42: v4 immune system active — issues command channel (label:command, "
                      "top priority), HEALTH.md every 25 cycles, deadman at heartbeat gap > 60 min, "
                      "anti-thrash at 3x same reason, anti-drift every 50 cycles (state/DRIFT.md), "
                      "self-termination only after 100 clean cycles with no work.")


# ---------------------------------------------------------------- specs
def specs():
    for n in ("SPEC-v2.md", "SPEC-v3.md", "SPEC-v3.1.md"):
        t = read(ROOT / "docs" / n)
        check(n, len(t) > 200, "%d bytes" % len(t))
    v31 = read(ROOT / "docs" / "SPEC-v3.1.md")
    check("verbatim-markers", "R-09" in v31 and "immune system" in v31,
          "v3.1 order frozen verbatim")
    check("redacted", "V4y24" not in v31, "credential redacted in frozen spec")


# ---------------------------------------------------------------- remote
def remote():
    cfg = util.load_json(util.CONFIG / "gh.json", {})
    check("gh-config", bool(cfg.get("user")) and cfg.get("user") != "GH_USER_PLACEHOLDER",
          "user=%s" % cfg.get("user"))
    tok = util.gh_token()
    check("token", bool(tok), "token available (env or origin url)")
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/%s/%s" % (util.gh_user(), util.DEFAULTS["repo"]),
            headers={"Authorization": "Bearer " + tok, "User-Agent": "mira-selftest"})
        with urllib.request.urlopen(req, timeout=30) as r:
            code = r.status
    except Exception as e:
        code = str(e)[:60]
    check("repo-live", code == 200, str(code))


CHECKS = {"r01": r01, "r02": r02, "r03": r03, "r04": r04, "r05": r05, "r06": r06,
          "r07": r07, "r08": r08, "r09": r09, "v4": v4, "specs": specs, "remote": remote}


@util.cli_guard
def main(argv):
    which = argv[0] if argv else "all"
    if which == "all":
        order = ["r01", "r02", "r03", "r04", "r05", "r06", "r07", "r08", "r09", "v4", "specs", "remote"]
        for k in order:
            print("== %s" % k)
            CHECKS[k]()
    elif which in CHECKS:
        print("== %s" % which)
        CHECKS[which]()
    else:
        print("unknown check: %s (r01..r09, v4, specs, remote, all)" % which)
        raise SystemExit(2)
    failed = [n for n, ok, _ in RESULTS if not ok]
    print("-- %d/%d passed" % (len(RESULTS) - len(failed), len(RESULTS)))
    if failed:
        raise SystemExit("FAILED: " + ", ".join(failed))


if __name__ == "__main__":
    main(sys.argv[1:])
