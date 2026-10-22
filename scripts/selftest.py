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


# ---------------------------------------------------------------- v3.2
def v32():
    import tempfile
    import shutil
    from datetime import timedelta
    import lint_workflows
    import issues
    import onboard_check
    import health

    # sec.2 — the lint itself is clean on the real tree
    errs = lint_workflows.lint_all()
    check("lint-clean", errs == [], "; ".join(errs[:2]))

    # sec.2 — the lint catches the silent-death class (synthetic tree)
    tmp = Path(tempfile.mkdtemp())
    try:
        wf = tmp / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "bad.yml").write_text("name: bad\n  step: [unclosed\n", encoding="utf-8")
        (wf / "notrig.yml").write_text("name: nt\njobs:\n  a:\n    runs-on: ubuntu-latest\n", encoding="utf-8")
        (wf / "nojobs.yml").write_text("name: nj\non:\n  workflow_dispatch:\n", encoding="utf-8")
        errs = lint_workflows.lint_all(root=tmp)
        joined = " || ".join(errs)
        check("lint-detects", ("bad.yml" in joined and "notrig.yml" in joined
                               and "nojobs.yml" in joined), "; ".join(errs[:3]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # sec.2 — lint wired into every workflow as a top step + backlog.one()
    ymls = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    with_lint = [y.name for y in ymls if "lint_workflows.py" in read(y)]
    check("lint-in-every-workflow", len(with_lint) == len(ymls), "%s" % with_lint)
    check("lint-in-one", "lint_workflows.run()" in read(ROOT / "scripts" / "backlog.py"),
          "backlog.one() lints before anything else")

    # sec.1 — WIRE pair parsing (title tokens + body lines, spaces in values)
    pairs = issues.parse_wire_pairs("telegram TELEGRAM_BOT_TOKEN=abc123",
                                    ["TELEGRAM_CHAT_ID=-1001234567890",
                                     "REDDIT_SECRET=my pass word", "junk line"])
    check("wire-parse", pairs.get("TELEGRAM_BOT_TOKEN") == "abc123"
          and pairs.get("TELEGRAM_CHAT_ID") == "-1001234567890"
          and pairs.get("REDDIT_SECRET") == "my pass word", str(sorted(pairs)))

    # sec.1/5 — WIRE validation is deterministic + prints canonical names
    res, ok = issues._wire("nosuch", [], None, "WIRE nosuch", "")
    check("wire-unknown-platform", ok and "canonical env names" in res, res[:80])
    res2, ok2 = issues._wire("telegram X_INVALID=1", [], None, "WIRE telegram", "")
    check("wire-unknown-key", ok2 and "TELEGRAM_BOT_TOKEN" in res2
          and "TELEGRAM_CHAT_ID" in res2, res2[:120])

    # sec.1 — command resolution: title OR first body line
    check("cmd-title", issues._resolve_command("DRAIN", []) == "DRAIN")
    check("cmd-body", issues._resolve_command("please wire this", ["WIRE telegram A=1", "x"])
          == "WIRE telegram A=1",
          issues._resolve_command("please wire this", ["WIRE telegram A=1", "x"]))

    # sec.5 — the name contract is complete: post.yml env == ENV_NAMES union
    # (GITHUB_TOKEN is the runner token for the lint/issues channel, not a
    # platform secret — excluded)
    posty = read(ROOT / ".github" / "workflows" / "post.yml")
    in_yml = set(re.findall(r"secrets\.([A-Z0-9_]+)", posty)) - {"GITHUB_TOKEN"}
    expected = set()
    for names in onboard_check.ENV_NAMES.values():
        expected |= set(names)
    check("name-contract-vs-post-yml", in_yml == expected,
          "yml-only: %s contract-only: %s" % (sorted(in_yml - expected), sorted(expected - in_yml)))

    # sec.5 — full-contract readiness (all names, env OR accounts.json block)
    full_env = {k: "x" for k in onboard_check.ENV_NAMES["reddit"]}
    part_env = dict(full_env)
    part_env.pop("REDDIT_PASSWORD")
    check("reddit-full", onboard_check.eval_platform("reddit", {}, full_env)
          and not onboard_check.eval_platform("reddit", {}, part_env),
          "all 5 names required")
    check("fanvue-contract", onboard_check.eval_platform("fanvue", {}, {"FANVUE_EMAIL": "e", "FANVUE_PASSWORD": "p"})
          and not onboard_check.eval_platform("fanvue", {}, {}), "FANVUE_EMAIL + FANVUE_PASSWORD")
    check("acc-block-fires-it", onboard_check.eval_platform(
        "telegram", {"bot_token": "t", "chat_id": "c"}, {})
        and onboard_check.eval_platform("telegram", {}, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}),
        "hand-added accounts.json creds still fire the flip")

    # sec.4 — funnel-first escalation (state save/restore)
    sq = json.dumps(util.load_queue())
    sh = json.dumps(util.load_json(util.STATE / "health.json", {}))
    sb = read(util.STATE / "BACKLOG.md")
    sboost = json.dumps(util.load_json(util.STATE / "quota_boost.json", {}))
    sacc = json.dumps(util.load_config("accounts.json"))
    try:
        old = (util.utcnow() - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fresh = util.ts()
        util.save_queue({"items": [{"id": "x1", "tier": "free", "status": "captioned",
                                    "created": old, "caption": "c"}]})
        esc, why = health.should_escalate_posting()
        check("funnel-stuck-detected", esc, why)
        util.save_queue({"items": [{"id": "f1", "tier": "free", "status": "captioned",
                                    "created": fresh}]})
        esc2, why2 = health.should_escalate_posting()
        check("funnel-fresh-no-escalation", not esc2, why2)
        # > 20 unposted -> generation boost refused (never raise img_free_day)
        util.save_queue({"items": [{"id": "u%d" % i, "tier": "free", "status": "captioned",
                                    "created": old} for i in range(25)]})
        health.escalate()
        b = util.load_json(util.STATE / "quota_boost.json", {})
        check("gen-boost-refused-over-cap", int(b.get("multiplier", 1)) == 1,
              "no raise while unposted > 20")
        # ready platform -> post-now item inserted at the TOP, ahead of quotas
        acc = util.load_config("accounts.json")
        acc.setdefault("platforms", {}).setdefault("telegram", {})["status"] = "ready"
        util.save_json(util.CONFIG / "accounts.json", acc)
        util.save_queue({"items": [{"id": "x1", "tier": "free", "status": "captioned",
                                    "created": old, "caption": "c"}]})
        health.escalate_posting()
        items = backlog.parse_items()
        check("post-now-ahead", items and items[0]["action"] == "post now: telegram"
              and items[0]["cmd"] == "python scripts/post_telegram.py",
              "top item: %s" % (items[0]["action"] if items else "-"))
        # legacy generation escalation only when the unposted queue is empty
        util.save_queue({"items": [{"id": "p1", "tier": "free", "status": "posted",
                                    "created": old, "posted_at": old}]})
        util.save_json(util.STATE / "health.json",
                       {"cycles": [{"c": i, "cls": "noop", "why": "synthetic"} for i in range(25)]})
        esc3, why3 = health.should_escalate()
        check("legacy-only-when-empty", esc3, why3)
    finally:
        util.save_json(util.CONTENT / "queue.json", json.loads(sq))
        util.save_json(util.STATE / "health.json", json.loads(sh))
        (util.STATE / "BACKLOG.md").write_text(sb, encoding="utf-8")
        util.save_json(util.STATE / "quota_boost.json", json.loads(sboost))
        util.save_json(util.CONFIG / "accounts.json", json.loads(sacc))

    # sec.3 — dependency chain lands in HEALTH.md
    health.report()
    hm = read(util.STATE / "HEALTH.md")
    check("chain-in-health", "cron (external) -> loop run -> deadman -> issue" in hm
          and "funnel" in hm, "HEALTH.md carries chain + funnel")
    ky = read(ROOT / ".github" / "workflows" / "keepalive.yml")
    check("keepalive-watchdog", "keepalive.py" in ky
          and re.search(r"actions:\s*write", ky) is not None
          and re.search(r"issues:\s*write", ky) is not None,
          "cron watchdog hardened (runs keepalive.py, actions+issues:write)")
    util.log_decision("D48: v3.2 — lint_workflows (silent-death guard) at the top of "
                      "every cycle in all 5 workflows + backlog.one(); D49: keepalive "
                      "hardened — workflow runs verified via API every 6h, disabled "
                      "schedules re-enabled, 24h stall opens a blocked issue; chain "
                      "written into HEALTH.md.")


# ---------------------------------------------------------------- specs
def specs():
    for n in ("SPEC-v2.md", "SPEC-v3.md", "SPEC-v3.1.md", "SPEC-v3.2.md", "SPEC-v3.3.md"):
        t = read(ROOT / "docs" / n)
        check(n, len(t) > 200, "%d bytes" % len(t))
    v31 = read(ROOT / "docs" / "SPEC-v3.1.md")
    check("verbatim-markers", "R-09" in v31 and "immune system" in v31,
          "v3.1 order frozen verbatim")
    check("redacted", "V4y24" not in v31, "credential redacted in frozen spec")
    v32 = read(ROOT / "docs" / "SPEC-v3.2.md")
    check("v32-frozen", "OPEN THE FUNNEL" in v32 and "WIRE" in v32
          and "FIRST POST CEREMONY" in v32, "v3.2 order frozen verbatim")
    v33 = read(ROOT / "docs" / "SPEC-v3.3.md")
    check("v33-spec-markers", "CAPTCHA BUDGET" in v33 and "WALLS LEDGER" in v33,
          "v3.3 order frozen verbatim")


# ---------------------------------------------------------------- v3.3
def v33():
    import tempfile
    import shutil
    import emailaddr
    import walls
    import emailpoll
    import issues
    from datetime import timedelta

    # sec.1 — plus-address derivation (pure)
    os.environ["MAIL_BASE"] = "human@gmail.com"
    try:
        check("addr-general", emailaddr.general() == "human+mirasolis@gmail.com",
              emailaddr.general() or "None")
        check("addr-platform", emailaddr.platform("mastodon")
              == "human+mirasolis-mastodon@gmail.com",
              emailaddr.platform("mastodon") or "None")
    finally:
        del os.environ["MAIL_BASE"]
    check("addr-nobase", emailaddr.general() is None
          and emailaddr.platform("x") is None, "no base -> None, no crash")
    check("addr-gitignored", "config/email.json" in read(ROOT / ".gitignore"),
          "config/email.json gitignored")

    # sec.2+3 — walls ledger: record + summary line + ready-exclusion
    snap = {}
    for p in (util.CONFIG / "accounts.json", util.STATE / "BLOCKERS.md",
              util.STATE / "HANDOFF.md", walls.WALLS):
        snap[p] = p.read_text(encoding="utf-8") if p.exists() else None
    tmpdir = tempfile.mkdtemp()
    try:
        line = walls.record("reddit", "captcha", attempts=2,
                            url="https://x.example/signup", est_min=4,
                            human_step="solve it, human")
        check("wall-record", line is not None and line["attempts"] == 2,
              "record returned the line")
        w = walls.load()
        check("wall-ledger", any(x.get("platform") == "reddit"
                                and x.get("wall_type") == "captcha"
                                and x.get("attempts") == 2 for x in w),
              "%d ledger line(s)" % len(w))
        check("wall-blockers", "WALL reddit: captcha" in read(util.STATE / "BLOCKERS.md"),
              "BLOCKERS.md gained the wall line")
        s = walls.summary_line()
        check("wall-summary-fmt",
              re.match(r"^\d+ platforms blocked \| cheapest human unblock: "
                       r"[a-z]+ \(\d+ min\) -> https?://\S+$", s) is not None, s)
        check("wall-cheapest", s.startswith("7 platforms blocked")
              and "telegram (1 min) -> https://t.me/BotFather" in s, s)
        # ready platforms leave the blocked set
        cfg = util.load_config("accounts.json")
        cfg["platforms"]["telegram"]["status"] = "ready"
        util.save_json(util.CONFIG / "accounts.json", cfg)
        s2 = walls.summary_line()
        check("wall-ready-excluded", s2.startswith("6 platforms blocked")
              and "telegram" not in s2.split("|", 1)[1], s2)

        # sec.5 — WIRE EMAIL=: parse, validation, account field, flow status
        pairs = issues.parse_wire_pairs("mastodon",
                                        ["EMAIL=human+mirasolis-mastodon@gmail.com"])
        check("wire-email-parse", pairs.get("EMAIL")
              == "human+mirasolis-mastodon@gmail.com", str(sorted(pairs)))
        res, ok = issues._wire("mastodon", ["EMAIL=notanemail"], None,
                               "WIRE mastodon", "")
        check("wire-email-invalid", ok and "not a valid address" in res, res[:80])
        res2, ok2 = issues._wire("mastodon",
                                 ["EMAIL=human+mirasolis-mastodon@gmail.com"],
                                 None, "WIRE mastodon", "")
        check("wire-email-ok", ok2 and "account email field set" in res2
              and "confirmation:" in res2, res2.splitlines()[0][:80])
        acc = util.load_config("accounts.json")["platforms"]["mastodon"]
        check("wire-email-stored", acc.get("email")
              == "human+mirasolis-mastodon@gmail.com", "accounts.json email set")
        check("wire-email-status", "no_channel" in res2 or "pending" in res2
              or "confirmed" in res2 or "failed" in res2,
              "flow status reported")

        # sec.3 — HANDOFF surfaces exactly one walls line
        import backlog
        backlog.rewrite_handoff(99, {"id": "T-9999", "action": "v33 selftest"},
                                "synthetic", "dead")
        h = read(util.STATE / "HANDOFF.md")
        wl = [l for l in h.splitlines()
              if "platforms blocked" in l and "cheapest human unblock" in l]
        check("handoff-one-line", len(wl) == 1 and "## WALLS" in h,
              "%d line(s): %s" % (len(wl), wl[0][:80] if wl else "none"))

        # sec.5 — link picker preference order (pure)
        links = ["https://site.example/unrelated",
                 "https://mastodon.social/verify?token=abc",
                 "https://mastodon.social/profile"]
        check("pick-link", emailpoll.pick_link(links, ("mastodon.social",))
              == "https://mastodon.social/verify?token=abc",
              emailpoll.pick_link(links, ("mastodon.social",)))
        check("pick-link-none", emailpoll.pick_link([], ()) is None, "empty -> None")
    finally:
        for p, txt in snap.items():
            if txt is None:
                if p.exists():
                    p.unlink()
            else:
                p.write_text(txt, encoding="utf-8")
        shutil.rmtree(tmpdir, ignore_errors=True)

    # sec.4 — SIGNUP.md: cheapest-first order, WIRE blocks, bluesky deferred
    su = read(ROOT / "docs" / "SIGNUP.md")
    pos = [su.find("## %d." % i) for i in range(1, 7)]
    check("signup-order", all(p >= 0 for p in pos) and pos == sorted(pos)
          and "telegram" in su[pos[0]:pos[1]], "1..6 cheapest-first")
    for blk in ("WIRE telegram", "WIRE mastodon", "WIRE reddit", "WIRE x",
                "WIRE pinterest", "WIRE fanvue", "WIRE bluesky"):
        check("signup-block-%s" % blk.split()[1], blk in su, "copy-paste block")
    check("signup-bluesky-deferred", "NEEDS PHONE" in su
          and su.find("bluesky — NEEDS PHONE") > pos[-1], "deferred marker last")
    check("signup-mail-base", "MAIL_BASE" in su and "Step 0" in su,
          "step 0 stores the base")

    # specs — v3.3 frozen verbatim, v2 ERRATA appended (not rewritten)
    v33t = read(ROOT / "docs" / "SPEC-v3.3.md")
    check("v33-frozen", "CAPTCHA BUDGET" in v33t and "EMAIL REALITY" in v33t
          and "WIRE gains EMAIL=" in v33t, "order frozen verbatim")
    v2 = read(ROOT / "docs" / "SPEC-v2.md")
    check("v2-errata", "ERRATA v3.3" in v2 and "MAIL_BASE" in v2,
          "errata block appended")

    # inbox.yml carries the emailpoll step (no colon in the step name — D45)
    iy = read(ROOT / ".github" / "workflows" / "inbox.yml")
    check("inbox-emailpoll", "emailpoll.py --poll" in iy
          and "MAIL_BASE" in iy, "poller wired into the inbox cycle")


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
          "r07": r07, "r08": r08, "r09": r09, "v4": v4, "v32": v32, "v33": v33,
          "specs": specs, "remote": remote}


@util.cli_guard
def main(argv):
    which = argv[0] if argv else "all"
    if which == "all":
        order = ["r01", "r02", "r03", "r04", "r05", "r06", "r07", "r08", "r09",
                 "v4", "v32", "v33", "specs", "remote"]
        for k in order:
            print("== %s" % k)
            CHECKS[k]()
    elif which in CHECKS:
        print("== %s" % which)
        CHECKS[which]()
    else:
        print("unknown check: %s (r01..r09, v4, v32, specs, remote, all)" % which)
        raise SystemExit(2)
    failed = [n for n, ok, _ in RESULTS if not ok]
    print("-- %d/%d passed" % (len(RESULTS) - len(failed), len(RESULTS)))
    if failed:
        raise SystemExit("FAILED: " + ", ".join(failed))


if __name__ == "__main__":
    main(sys.argv[1:])
