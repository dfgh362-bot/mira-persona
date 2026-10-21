"""One-time remote bring-up for MIRA. Idempotent — safe to re-run.
Reads GH_TOKEN from env only (never written to any tracked file).

Steps: derive user -> gh.json + jsDelivr cdn fixes -> create repo -> push main
-> enable Pages (workflow build) -> set topics -> dispatch all 5 workflows -> verify.
Hard failures append to state/BLOCKERS.md and exit 1; the backlog marks T-0001 [~].
"""
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

REPO = "mira-persona"
WORKFLOWS = ["generate.yml", "post.yml", "inbox.yml", "keepalive.yml", "loop.yml"]
API = "https://api.github.com"


def gh(method, path, payload=None):
    token = os.environ.get("GH_TOKEN", "")
    return util.http_json(method, API + path, payload=payload,
                          headers={"Authorization": "Bearer " + token}, retries=2)


def gh_code(err):
    m = re.search(r"HTTP (\d{3})", str(err))
    return m.group(1) if m else "???"


def sh(cmd):
    return subprocess.run(cmd, shell=True, cwd=util.ROOT, capture_output=True,
                          text=True, timeout=600)


def sh_list(args):
    return subprocess.run(args, cwd=util.ROOT, capture_output=True, text=True, timeout=600)


def blocker(line):
    util.append_blocker(line)
    print("BLOCKER: %s" % line)


def main():
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        blocker("GH_TOKEN env missing — set it and re-run scripts/bringup_remote.py")
        return 1

    # 0. who is this token
    try:
        me = gh("GET", "/user")
    except Exception as e:
        blocker("token invalid for GET /user (HTTP %s) — regenerate PAT with repo+workflow" % gh_code(e))
        return 1
    login = me.get("login") or "unknown"
    print("user: %s" % login)

    # 0b. scope check (fine-grained PATs send no header — only trust an explicit negative)
    scopes = ""
    try:
        req = urllib.request.Request(API + "/user", method="HEAD",
                                     headers={"Authorization": "Bearer " + token,
                                              "User-Agent": util.UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            scopes = r.headers.get("x-oauth-scopes") or ""
    except Exception as e:
        print("scope header check failed: %r" % e)
    print("scopes: %s" % (scopes or "(none reported — fine-grained PAT?)"))
    if scopes and "workflow" not in scopes:
        blocker("PAT lacks 'workflow' scope — .github/workflows/ cannot be pushed. "
                "Regenerate the token with repo+workflow and re-run bringup.")
        print("HUMAN: token lacks 'workflow' scope — regenerate with repo+workflow, then re-run bringup.")

    # 1. local fixes: gh.json + queue cdn urls + site
    util.save_json(util.CONFIG / "gh.json", {"user": login})
    accs = util.load_config("accounts.json")
    accs.setdefault("gh", {})["user"] = login
    util.save_json(util.CONFIG / "accounts.json", accs)
    q = util.load_queue()
    for it in q.get("items", []):
        if it.get("file"):
            it["cdn"] = util.jsdelivr(it["file"])
    util.save_queue(q)
    sh("python scripts/build_site.py")
    sh("git add -A")
    if sh("git diff --cached --quiet").returncode != 0:
        sh_list(["git", "commit", "-m", "bringup: gh.json + jsDelivr cdn urls fixed"])
    print("local: gh.json + cdn urls fixed")

    # 2. create repo (idempotent)
    try:
        gh("POST", "/user/repos",
           {"name": REPO, "private": False,
            "description": "MIRA — an ai-generated persona run entirely by GitHub Actions. "
                           "Zero cost. Not a real person (full disclosure in README)."})
        print("repo: created https://github.com/%s/%s" % (login, REPO))
    except Exception as e:
        if gh_code(e) in ("422", "409"):
            print("repo: already exists")
        else:
            blocker("repo creation failed (HTTP %s) — check token 'repo' scope" % gh_code(e))
            return 1

    # 3. remote + push (idempotent)
    url = "https://%s:%s@github.com/%s/%s.git" % (login, token, login, REPO)
    sh("git remote remove origin")
    sh_list(["git", "remote", "add", "origin", url])
    if sh("git fetch origin main").returncode == 0:
        sh("git rebase origin/main")
    p = sh("git push -u origin main")
    if p.returncode != 0:
        blocker("git push failed: %s"
                 % re.sub(r"ghp_[A-Za-z0-9]+", "ghp_***", (p.stderr or ""))[-200:])
        # per contract: continue with the rest of the API tasks anyway
    else:
        n = sh("git rev-list --count HEAD").stdout.strip() or "?"
        print("push: main up (%s commits)" % n)

    # 4. enable Pages (workflow build)
    try:
        gh("POST", "/repos/%s/%s/pages" % (login, REPO), {"build_type": "workflow"})
        print("pages: enabled (workflow build)")
    except Exception as e:
        if gh_code(e) == "409":
            print("pages: already enabled")
        else:
            print("pages: enable returned %s (generate.yml pages job will retry)" % gh_code(e))

    # 5. topics
    try:
        gh("PUT", "/repos/%s/%s/topics" % (login, REPO),
           {"names": ["ai-generated", "virtual-persona", "github-actions", "automation",
                      "zero-cost", "content-pipeline", "pollinations"]})
        print("topics: set")
    except Exception as e:
        print("topics: failed (%s)" % gh_code(e))

    # 6. dispatch all workflows once (v2 seq 11 + loop start)
    for wf in WORKFLOWS:
        try:
            gh("POST", "/repos/%s/%s/actions/workflows/%s/dispatches" % (login, REPO, wf),
               {"ref": "main"})
            print("dispatch %s: ok" % wf)
        except Exception as e:
            print("dispatch %s: failed (%s)" % (wf, gh_code(e)))

    # 7. verify
    try:
        wl = gh("GET", "/repos/%s/%s/actions/workflows" % (login, REPO))
        found = [(w.get("name"), w.get("state")) for w in wl.get("workflows", [])]
        print("workflows on remote (%d): %s" % (len(found), found))
        if len(found) < len(WORKFLOWS):
            print("note: expected %d workflows, found %d" % (len(WORKFLOWS), len(found)))
    except Exception as e:
        print("verify failed: %s" % gh_code(e))

    util.log_event("bringup_done", user=login)
    print("bringup complete: https://github.com/%s/%s" % (login, REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
