"""Build site/index.html from the queue: gallery of posted/captioned free items.

Image delivery (v3.1 R-03, decision D36 — deviation from "always jsDelivr"):
site tier: jsDelivr -> /content/... same-origin -> raw.githubusercontent,
chained in the browser via onerror (mfb). build_site also syncs
content/free/ into (git-ignored) site/content/ so the Pages artifact —
packaged in the generate job right after this build — serves the same-origin
tier. Fanvue CTA; disclosure is non-negotiable and rendered in header+footer.

CLI: python scripts/build_site.py
"""
import html
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

TPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mira Solis · ai-generated</title>
<meta name="description" content="Mira Solis — an ai-generated persona. Not a real person. Film-grain photo diary from Lisbon.">
<style>
body{{margin:0;background:#f4efe7;color:#2b241c;font:16px/1.6 Georgia,serif}}
header{{max-width:880px;margin:0 auto;padding:56px 20px 8px;text-align:center}}
h1{{font-weight:400;letter-spacing:.14em;font-size:28px;margin:0}}
.badge{{display:inline-block;margin-top:10px;padding:3px 12px;border:1px solid #2b241c;border-radius:999px;font:11px/1.6 system-ui;letter-spacing:.16em}}
main{{max-width:880px;margin:0 auto;padding:24px 20px 8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:18px}}
figure{{margin:0;background:#fffdf8;border:1px solid #e6ddcd;padding:10px}}
img{{width:100%;display:block;aspect-ratio:2/3;object-fit:cover;filter:saturate(.92) contrast(.98)}}
figcaption{{font:italic 13px/1.5 Georgia,serif;padding:10px 4px 2px;color:#5a4f3f}}
.cta{{display:block;width:fit-content;margin:36px auto 0;padding:12px 28px;background:#2b241c;color:#f4efe7;border-radius:999px;text-decoration:none;font:600 13px/1 system-ui;letter-spacing:.12em}}
footer{{max-width:880px;margin:0 auto;padding:32px 20px 56px;text-align:center;font:12px/1.7 system-ui;color:#7a6f5e}}
</style>
</head>
<body>
<header>
  <h1>MIRA SOLIS</h1>
  <span class="badge">LISBON · 35MM · ai-generated</span>
  <p>warm neutral tones, film grain, oat cortados.<br>this page is rebuilt by robots twice a day.</p>
</header>
<main>
  <div class="grid">
{cards}
  </div>
  <a class="cta" href="{fanvue}">FOLLOW THE FILM ROLL → FANVUE</a>
</main>
<footer>
  mira solis is an <b>ai-generated persona</b> — not a real person.<br>
  every image, caption and voice note on this page is generated.<br>
  built and hosted for zero cost.
</footer>
<script>
function mfb(el){{
  var n = (parseInt(el.dataset.n, 10) || 0) + 1; el.dataset.n = n;
  if (n === 1 && el.dataset.fb) {{ el.src = el.dataset.fb; return; }}
  if (n === 2 && el.dataset.raw) {{ var r = el.dataset.raw; el.dataset.raw = ""; el.src = r; return; }}
  el.onerror = null;
}}
</script>
</body>
</html>
"""

CARD = """    <figure>
      <img src="{cdn}" data-fb="{same}" data-raw="{raw}" onerror="mfb(this)" alt="{alt}" loading="lazy">
      <figcaption>{caption}</figcaption>
    </figure>"""


def sync_content():
    """v3.1 R-03: same-origin middle tier — mirror content/free into
    site/content/ (git-ignored; the Pages artifact is packaged from the
    build job's working tree, so untracked files ship)."""
    src = util.CONTENT / "free"
    dst = util.ROOT / "site" / "content"
    try:
        if dst.exists():
            shutil.rmtree(dst)
        if src.exists():
            shutil.copytree(src, dst / "free")
            return "synced content/free -> site/content/free"
        return "no content/free to sync"
    except Exception as e:
        util.log_event("error", where="sync_content", error=repr(e))
        return "sync failed: %r" % e


@util.cli_guard
def main(argv):
    queue = util.load_queue()
    platforms = util.load_config("platforms.json")
    fanvue = "https://fanvue.com/mirasolis"
    try:
        fanvue = util.load_config("accounts.json")["platforms"]["fanvue"].get("url") or fanvue
    except Exception:
        pass

    cards = []
    for it in queue.get("items", []):
        if it.get("tier") != "free" or it.get("status") not in ("captioned", "posted", "archived"):
            continue
        caption = html.escape(it.get("caption") or "")
        tiers = util.site_media_tiers(it["file"])
        cards.append(CARD.format(cdn=it.get("cdn") or tiers[0],
                                 same=tiers[1],
                                 raw=tiers[2],
                                 alt=html.escape("mira solis — ai-generated, " + (it.get("scene") or "")),
                                 caption=caption))
        if len(cards) >= 48:
            break

    if not cards:
        cards = ["""    <figure><img src="" alt="mira"
      onerror="this.parentNode.style.display='none'">
      <figcaption>waiting for the first roll…</figcaption></figure>"""]

    page = TPL.format(cards="\n".join(cards), fanvue=fanvue)
    out = util.ROOT / "site" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    note = sync_content()
    util.log_event("site_built", cards=len(cards), out=str(out), tier="R-03 3-tier")
    print("site/index.html rebuilt with %d card(s); %s" % (len(cards), note))


if __name__ == "__main__":
    main(sys.argv[1:])
