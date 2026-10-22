"""v3.5 sec.5/7 — X signup IP probe (runs on an Actions runner via RUN cmd).

Answers ONE question: does the jf begin_verification gate pass from a
runner IP with the repo stealth context? Prints the begin_login response
body (read-only diagnostic; no state is written).

CLI: python scripts/x_ip_probe.py [email]   (email optional — a fixed
address is best so the emailnator session dependency is removed)
"""
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util
import browserpost

FIXED_EMAIL = "wipetmp+6jlen@gmail.com"      # generated locally, reusable


def log(*a):
    print("[x-ip-probe]", *a, flush=True)


def delay(lo=0.4, hi=1.2):
    time.sleep(random.uniform(lo, hi))


@util.cli_guard
def main(argv):
    email = (argv[0] if argv else FIXED_EMAIL).strip()
    log("email:", email)
    pw, browser = browserpost.launch()
    try:
        ctx = browserpost.stealth_context(browser)
        jf = []

        def on_response(r):
            if "jf.x.com" in r.url and "actions" in r.url:
                try:
                    body = r.text()
                except Exception:
                    body = "(undecodable)"
                jf.append((r.status, r.url.split("jf.x.com")[-1][:50], body[:400]))
        ctx.on("response", on_response)

        x = ctx.new_page()
        x.goto("https://x.com/", wait_until="domcontentloaded", timeout=45000)
        delay(1.5, 2.5)
        box = x.wait_for_selector("#jf-input-username_or_email", timeout=25000)
        box.click()
        delay(0.2, 0.6)
        box.type(email, delay=random.randint(50, 120))
        delay()
        btn = x.locator("button", has_text=re.compile(r"^Continue$")).first
        log("continue visible:", btn.is_visible())
        btn.click()
        for i in range(15):
            delay(0.9, 1.2)
            body = x.evaluate("document.body.innerText.slice(0,300)")
            if "not right" in body or "different method" in body:
                log("REJECTED after %ds" % i)
                break
            if x.query_selector("input[name='name'], select, "
                                "input[autocomplete='new-password']"):
                log("ADVANCED to signup form at %ds" % i)
                break
        log("url:", x.url)
        log("body head:", x.evaluate("document.body.innerText.slice(0,250)"))
        log("jf action calls: %d" % len(jf))
        for s, u, b in jf:
            log("  %s %s" % (s, u))
            printable = "".join(ch if 32 <= ord(ch) < 127 else "." for ch in b)
            log("    body:", printable[:200])
        # also probe a plain GET for the record
        log("landing html bytes:", len(x.content()))
    finally:
        try:
            browser.close()
            pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main(sys.argv[1:])
