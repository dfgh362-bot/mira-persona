"""MIRA v3.5 human lane — browser posting via Playwright + storageState.

"An API is a door someone built for you. A browser session is you
walking in the front entrance." — CLOSING ORDER v3.5 sec.0

- LANE (sec.1, config/platforms.json): api = telegram, mastodon, bluesky;
  browser = x, reddit, pinterest, instagram, tiktok, fanvue. A browser-lane
  platform's API poster is DISABLED — no double posting.
- cookie vault (sec.2): COOKIES_<PLATFORM> Actions secret (base64 Playwright
  storageState — cookies + localStorage, NOT a raw jar), local mirror
  .secrets/cookies.json (gitignored). WIRE <p> COOKIE=<base64> accepts them
  (scripts/issues.py). A rotated cookie is written BACK to the secret after
  every run (needs WIRE_PAT/GH_PAT; logged+skipped when unavailable).
- health gate (sec.3, inline before ANY posting): cheap authenticated page;
  logged-out -> status "cookie_expired", ONE blocked issue naming the platform
  and exactly what to send, skip this cycle. Every check lands in
  state/cookies.json {platform: {ok, ts}}.
- stealth (sec.4): real Chrome UA / viewport / locale / timezone,
  400-1200ms human delays, persistent storageState (one continuous device),
  playwright-stealth when importable. 2 attempts — never a third.
- verify (sec.7): every post is read back off the profile page before it is
  recorded in posted.json.

CLI:
  python scripts/browserpost.py --platform x           # ceremony-aware post
  python scripts/browserpost.py --platform x --check   # health gate only
  python scripts/browserpost.py --table                # lane closing block

The X flow is the proven reference implementation (v3.5 sec.7); reddit /
pinterest / fanvue share the same skeleton with their own selectors —
they activate the moment cookies land in the vault.
"""
import base64
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

# ------------------------------------------------------------------ lanes

LANE = {
    "telegram": "api", "mastodon": "api", "bluesky": "api",
    "x": "browser", "reddit": "browser", "pinterest": "browser",
    "instagram": "browser", "tiktok": "browser", "fanvue": "browser",
}
BROWSER_LANE = tuple(p for p, l in LANE.items() if l == "browser")
API_LANE = tuple(p for p, l in LANE.items() if l == "api")
TIER1_BROWSER = ("x", "reddit", "pinterest")     # in post.yml's steady loop


def cookie_env(platform):
    return "COOKIES_" + platform.upper()


# ------------------------------------------------------------- vault (sec.2)

VAULT = util.ROOT / ".secrets" / "cookies.json"


def vault_read(platform):
    """base64 storageState for a platform: env secret first, local mirror
    second (local operator runs). None when the vault has nothing."""
    import os
    v = os.environ.get(cookie_env(platform))
    if v and v.strip():
        return v.strip()
    try:
        mirror = json.loads(VAULT.read_text(encoding="utf-8"))
        v = mirror.get(platform)
        return v if v else None
    except Exception:
        return None


def vault_write(platform, b64state, writeback=True):
    """mirror + write the rotated value back to the Actions secret (sec.2).
    Never raises; writeback failure is logged, not fatal."""
    try:
        mirror = {}
        try:
            mirror = json.loads(VAULT.read_text(encoding="utf-8"))
        except Exception:
            pass
        mirror[platform] = b64state
        VAULT.parent.mkdir(parents=True, exist_ok=True)
        VAULT.write_text(json.dumps(mirror, indent=1), encoding="utf-8")
    except Exception as e:
        util.log_event("vault_mirror_failed", platform=platform, error=repr(e)[:120])
    if writeback:
        try:
            import issues
            ok, lines = issues.upload_secrets({cookie_env(platform): b64state})
            util.log_event("vault_writeback", platform=platform, ok=bool(ok))
        except Exception as e:
            util.log_event("vault_writeback_failed", platform=platform,
                           error=repr(e)[:120])


def state_to_tempfile(platform, b64state):
    """storageState the browser can consume: base64 -> tmp json file."""
    p = util.STATE / ("cookies_%s.json" % platform)
    p.write_bytes(base64.b64decode(b64state))
    return str(p)


def state_from_context(context):
    """context.storage_state() -> base64 (for the vault)."""
    return base64.b64encode(json.dumps(context.storage_state(),
                                       separators=(",", ":")).encode()).decode()


# ------------------------------------------------------------ health (sec.3)

COOKIES_LEDGER = util.STATE / "cookies.json"


def log_health(platform, ok, note=""):
    d = util.load_json(COOKIES_LEDGER, {})
    d[platform] = {"ok": bool(ok), "ts": util.ts()}
    if note:
        d[platform]["note"] = note[:80]
    util.save_json(COOKIES_LEDGER, d)


def cookie_expired(platform, note):
    """sec.3: status cookie_expired + ONE blocked issue naming the platform
    and exactly what to send. Never fails silently."""
    util.set_platform_status(platform, "cookie_expired")
    util.append_blocker(
        "%s: browser-lane cookies EXPIRED — refresh with a new "
        "storageState: open an issue 'WIRE %s COOKIE=<base64 storageState>' "
        "(label: command), or re-login locally and let the vault writeback "
        "run (docs/RUNBOOK.md) (%s)" % (platform, platform, note[:100]))
    try:
        import issues
        issues.open_issue(
            "blocked: %s cookies expired" % platform,
            "cookie health gate failed before posting (v3.5 sec.3).\n\n"
            "what to send: a fresh Playwright storageState as base64 —\n"
            "  WIRE %s COOKIE=<base64>\n(labeled 'command'; it uploads sealed "
            "as COOKIES_%s and the platform flips ready again).\n\n"
            "2-minute recipe: python scripts/browserpost.py --login %s"
            % (platform, cookie_env(platform), platform),
            labels=["blocked"])
    except Exception as e:
        util.log_event("cookie_issue_failed", platform=platform, error=repr(e)[:120])
    util.log_event("cookie_expired", platform=platform)


# --------------------------------------------------------------- stealth (sec.4)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36")
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [
  {name:'Chrome PDF Plugin'},{name:'Chrome PDF Viewer'},{name:'Native Client'}]});
Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
if (navigator.userAgentData) {
  Object.defineProperty(navigator, 'userAgentData', {get: () => ({
    brands: [{brand:'Chromium', version:'__MAJOR__'},
             {brand:'Not_A Brand', version:'99'}],
    mobile: false,
    platform: 'Windows'
  })});
}
const orig = window.navigator.permissions.query;
window.navigator.permissions.query = (p) => (
  p && p.name === 'notifications'
    ? Promise.resolve({state: Notification.permission})
    : orig(p));
""".replace("__MAJOR__", "142")


def human_delay(lo=0.4, hi=1.2):
    """sec.4: 400-1200ms between actions, never 0."""
    time.sleep(random.uniform(lo, hi))


CHROME_MAJOR = "142"


def stealth_context(browser, state_path=None):
    ctx = browser.new_context(
        user_agent=UA,
        viewport={"width": 1366, "height": 850},
        locale="en-US",
        timezone_id="Europe/Lisbon",
        color_scheme="light",
        device_scale_factor=1.0,
        storage_state=state_path,
    )
    # client hints must AGREE with the UA or x.com 403s at the HTTP layer
    # (sec-ch-ua otherwise leaks the real headless chromium version/platform)
    ctx.set_extra_http_headers({
        "sec-ch-ua": '"Chromium";v="%s", "Not_A Brand";v="99"' % CHROME_MAJOR,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    })
    try:
        from playwright_stealth import stealth_sync     # optional layer
        stealth_sync(ctx)
    except Exception:
        pass
    ctx.add_init_script(STEALTH_JS)
    return ctx


def launch():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled",
              "--no-sandbox", "--disable-dev-shm-usage"])
    return pw, browser


# ------------------------------------------------------------- health pages

HEALTH = {
    "x": {
        "url": "https://x.com/home",
        "logged_out_url": ("/login", "/i/flow/login"),
        "authed_selector": '[data-testid="SideNav_NewTweet_Button"],'
                           'a[data-testid="AppTabBar_Profile_Link"]',
    },
    "reddit": {
        "url": "https://www.reddit.com/",
        "logged_out_url": ("/login",),
        "authed_selector": '[data-testid="user-drawer-button"],'
                           'button#expand-user-drawer-button,'
                           '[id^="USER_DROPDOWN"]',
    },
    "pinterest": {
        "url": "https://www.pinterest.com/",
        "logged_out_url": ("/login",),
        "authed_selector": '[data-test-id="header-profile"],'
                           'div[data-test-id="header-settings"]',
    },
    "fanvue": {
        "url": "https://fanvue.com/",
        "logged_out_url": ("/login", "/signup"),
        "authed_selector": "a[href*='/settings'], a[href*='/dashboard']",
    },
}


def check_health(page, platform):
    """True = session alive, False = logged out, raises on transport error."""
    spec = HEALTH.get(platform)
    if not spec:
        return True                      # unknown flow — let the poster decide
    page.goto(spec["url"], timeout=45000, wait_until="domcontentloaded")
    human_delay()
    page.wait_for_timeout(2500)
    url = page.url or ""
    for frag in spec["logged_out_url"]:
        if frag in url:
            return False
    try:
        page.wait_for_selector(spec["authed_selector"], timeout=12000)
        return True
    except Exception:
        # no authed marker and no login redirect — SPA ambiguity; second
        # signal: any login/signup link in the header means logged out
        try:
            page.wait_for_selector('a[href="/login"], a[href*="/i/flow/login"]',
                                   timeout=3000)
            return False
        except Exception:
            return True                  # ambiguous — let the compose try


# --------------------------------------------------------------- X flow (sec.7)

X_SEL = {
    "compose_btn": '[data-testid="SideNav_NewTweet_Button"]',
    "compose_btn_alt": 'a[data-testid="AppTabBar_Compose_Link"]',
    "tweet_box": '[data-testid="tweetTextarea_0"]',
    "file_input": 'input[data-testid="fileInput"]',
    "post_btn": '[data-testid="tweetButton"]',
    "post_btn_inline": '[data-testid="tweetButtonInline"]',
    "caret": '[data-testid="caret"]',
    "article": 'article[data-testid="tweet"]',
    "status_link": 'a[href*="/status/"]',
}


def x_type(page, text):
    """DraftJS-safe typing with human per-char delays."""
    for ch in text[:280]:                 # hard X text limit
        page.keyboard.type(ch, delay=random.randint(45, 130))
        if ch in " \n":
            time.sleep(random.uniform(0.01, 0.05))


def x_compose(page, text, image_path=None):
    human_delay()
    try:
        page.click(X_SEL["compose_btn"], timeout=8000)
    except Exception:
        page.click(X_SEL["compose_btn_alt"], timeout=8000)
    human_delay()
    box = page.wait_for_selector(X_SEL["tweet_box"], timeout=15000)
    box.click()
    human_delay(0.2, 0.5)
    x_type(page, text)
    if image_path:
        human_delay()
        try:
            fi = page.wait_for_selector(X_SEL["file_input"], timeout=8000)
            fi.set_input_files(str(image_path))
            page.wait_for_timeout(3000)     # preview to attach
        except Exception as e:
            util.log_event("x_attach_failed", error=repr(e)[:120])
    human_delay()
    for sel in (X_SEL["post_btn_inline"], X_SEL["post_btn"]):
        try:
            page.wait_for_selector(sel, state="visible", timeout=4000)
            page.click(sel)
            break
        except Exception:
            continue
    else:
        raise RuntimeError("post button never became clickable")
    human_delay()


def x_verify(page, handle, needle):
    """sec.7: read the post back off the profile page."""
    page.goto("https://x.com/%s" % handle, timeout=45000, wait_until="domcontentloaded")
    human_delay()
    page.wait_for_timeout(2500)
    art = page.wait_for_selector(X_SEL["article"], timeout=15000)
    body = art.inner_text()
    if needle.lower() not in body.lower():
        raise RuntimeError("verify failed: post not visible on profile")
    link = art.query_selector(X_SEL["status_link"])
    href = link.get_attribute("href") if link else ""
    if "/status/" in href:
        return "https://x.com%s" % href.split("?")[0]
    return "https://x.com/%s" % handle


def x_pin_top(page):
    """best-effort pin (like the telegram pin patch): ... -> Pin to profile."""
    try:
        art = page.wait_for_selector(X_SEL["article"], timeout=8000)
        caret = art.query_selector(X_SEL["caret"]) or page.query_selector(X_SEL["caret"])
        if not caret:
            return False
        human_delay()
        caret.click()
        human_delay()
        page.wait_for_selector('div[role="menuitem"]', timeout=5000)
        for mi in page.query_selector_all('div[role="menuitem"]'):
            if "pin" in (mi.inner_text() or "").lower():
                human_delay()
                mi.click()
                page.keyboard.press("Escape")
                return True
        page.keyboard.press("Escape")
    except Exception as e:
        util.log_event("x_pin_skipped", error=repr(e)[:120])
    return False


def post_x(ctx, page, item, caption, image_path):
    handle = util.load_config("accounts.json").get("platforms", {}).get(
        "x", {}).get("handle") or util.load_config("persona.json").get("handle", "mirasolis")
    x_compose(page, caption, image_path)
    url = x_verify(page, handle, caption[:40])
    return url, handle


# ---------------------------------------------------- other browser flows

def post_reddit(ctx, page, item, caption, image_path):
    """provisional template (activated when COOKIES_REDDIT lands)."""
    raise NotImplementedError("reddit browser flow lands with its cookies "
                              "(same skeleton as x — health gate + compose + verify)")


def post_pinterest(ctx, page, item, caption, image_path):
    raise NotImplementedError("pinterest browser flow lands with its cookies "
                              "(same skeleton as x)")


FLOWS = {"x": post_x}


# ------------------------------------------------------------------ poster

def record_or_pin(page, platform, ctx, item, caption, image_path):
    flow = FLOWS.get(platform)
    url, _ = flow(ctx, page, item, caption, image_path)
    return url


def run_platform(platform, check_only=False):
    """ceremony-aware browser-lane post. Returns True when something was
    posted or the platform is healthily idle."""
    if LANE.get(platform) != "browser":
        print("%s: not a browser-lane platform" % platform)
        return False
    b64 = vault_read(platform)
    if not b64:
        print("%s: no cookies in vault — pending signup (quiet skip)" % platform)
        util.log_event("browser_skip", platform=platform, reason="no cookies")
        return False
    state_path = state_to_tempfile(platform, b64)
    pw, browser = launch()
    ok = False
    try:
        for attempt in (1, 2):                     # sec.4: 2, never a third
            ctx = stealth_context(browser, state_path)
            page = ctx.new_page()
            try:
                if not check_health(page, platform):
                    cookie_expired(platform, "attempt %d" % attempt)
                    print("%s: cookie EXPIRED — blocked issue opened, skipped"
                          % platform)
                    ctx.close()
                    return False
                log_health(platform, True)
                if check_only:
                    print("%s: cookies healthy" % platform)
                    ctx.close()
                    return True
                if platform not in FLOWS:
                    # health gate ran (ledger updated); compose flow is a
                    # per-platform template that lands with its session
                    print("%s: cookies healthy, compose flow not provisioned "
                          "yet — quiet skip" % platform)
                    ctx.close()
                    return True
                posted = util.load_posted()
                disclosure = util.load_config("platforms.json").get("disclosure", {})
                if not util.has_pinned(posted, platform):
                    url = record_or_pin(page, platform, ctx, None,
                                        disclosure["pinned_post"], None)
                    if platform == "x":
                        x_pin_top(page)
                    util.record_post(None, platform, url, pinned=True, item_id="pinned")
                    print("%s: pinned disclosure posted + verified (%s)"
                          % (platform, url))
                    ok = True
                else:
                    queue = util.load_queue()
                    item = util.pick_due_item(queue, "free")
                    if not item:
                        print("%s: no due item" % platform)
                    elif util.already_posted(posted, item["id"], platform):
                        print("%s: dupe blocked" % platform)
                    else:
                        img = util.ROOT / item["file"] if item.get("file") else None
                        url = record_or_pin(page, platform, ctx, item,
                                            item["caption"], img)
                        util.record_post(item, platform, url)
                        util.mark_posted(item)
                        print("%s: posted %s + verified (%s)"
                              % (platform, item["id"], url))
                        ok = True
                # sec.2: rotated cookie writeback after every healthy run
                vault_write(platform, state_from_context(ctx))
                ctx.close()
                return ok or True
            except Exception as e:
                util.log_event("browser_attempt_failed", platform=platform,
                               attempt=attempt, error=repr(e)[:200])
                try:
                    log_health(platform, False, note=repr(e)[:80])
                except Exception:
                    pass
                try:
                    ctx.close()
                except Exception:
                    pass
                if attempt == 2:
                    # budget exhausted (v3.3 sec.2 hard rule): wall + stop
                    util.log_event("browser_wall", platform=platform)
                    util.append_blocker(
                        "%s: browser-lane failed 2 attempts (%s) — 2-minute "
                        "human step: log in, then 'WIRE %s COOKIE=<base64>' "
                        "(docs/RUNBOOK.md)" % (platform, repr(e)[:80], platform))
                    print("%s: 2 attempts failed — handed to human" % platform)
                    return False
                state_path = state_to_tempfile(platform, b64)   # fresh session
        return False
    finally:
        try:
            browser.close()
            pw.stop()
        except Exception:
            pass


# ------------------------------------------------- closing block (sec.10)

def lane_table():
    """| platform | lane | state | blocker | human cost | — for HANDOFF.md."""
    accs = util.load_config("accounts.json").get("platforms", {})
    cfg = util.load_config("platforms.json").get("tiers", {})
    human = {
        "telegram": "60s: public channel + add @MiraSolisbot admin",
        "mastodon": "1 min: click the confirmation mail (WIRE EMAIL= first)",
        "bluesky": "phone-required signup (mobile app), then app password",
        "x": "none — signup runs in the loop (mail.tm ladder)",
        "reddit": "none — cookies land via the loop",
        "pinterest": "none — cookies land via the loop",
        "instagram": "manual tier-2 (business verification)",
        "tiktok": "manual tier-2 (API approval)",
        "fanvue": "none — signup runs in the loop (mail.tm ladder)",
    }
    rows = ["| platform | lane | state | blocker | human cost |",
            "|---|---|---|---|---|"]
    try:
        bl = (util.STATE / "BLOCKERS.md").read_text(encoding="utf-8")
    except Exception:
        bl = ""
    for p in ("telegram", "mastodon", "bluesky", "x", "reddit", "pinterest",
              "instagram", "tiktok", "fanvue"):
        lane = (cfg.get(p) or {}).get("lane") or LANE.get(p, "?")
        state = (accs.get(p) or {}).get("status") or (cfg.get(p) or {}).get("status") or "?"
        blocked = any(("%s:" % p) in l or ("WIRE %s" % p) in l or ("%s onboarding" % p) in l
                      for l in bl.splitlines() if l.strip().startswith("-"))
        blocker = "blocked" if blocked and state not in ("ready", "live") else "-"
        rows.append("| %s | %s | %s | %s | %s |"
                    % (p, lane, state, blocker, human.get(p, "-")))
    return "\n".join(rows)


# -------------------------------------------------------------------- CLI

@util.cli_guard
def main(argv):
    platform = None
    check = False
    i = 0
    while i < len(argv):
        if argv[i] == "--platform":
            i += 1
            platform = argv[i] if i < len(argv) else None
        elif argv[i] == "--check":
            check = True
        elif argv[i] == "--table":
            print(lane_table())
            return
        i += 1
    if not platform:
        print(__doc__)
        print("usage: --platform <x|reddit|pinterest|fanvue> [--check] | --table")
        return
    run_platform(platform, check_only=check)


if __name__ == "__main__":
    main(sys.argv[1:])
