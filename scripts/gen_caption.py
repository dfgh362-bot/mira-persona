"""Generate captions for queued MIRA items via Pollinations text endpoint.

Style contract: lowercase, 1-2 lines, rare emoji, deadpan warm voice.
Fallback: static pool in prompts/captions.json.
Caption rule (config/platforms.json): never claim to be human, never deny being ai.

CLI:
  python scripts/gen_caption.py            # caption every 'queued' item
  python scripts/gen_caption.py --count 2
"""
import random
import re
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

STYLE = ("Write one short social media caption for this photo scene: '%s'. "
         "Style rules: all lowercase, one or two short lines, deadpan warm tone, "
         "no hashtags, no quotes, no @ mentions, emoji only rarely, max 14 words. "
         "Never claim to be human. Reply with the caption only.")

EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def sanitize(text):
    text = text.strip().strip('"').strip("'")
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.lower()
    # rare emoji: drop all, then re-allow at most one
    emoji = EMOJI_RE.findall(text)
    text = EMOJI_RE.sub("", text).strip()
    if emoji and random.random() < 0.15:
        text = text.rstrip(".,!?") + " " + emoji[0]
    if not (3 <= len(text) <= 140):
        raise RuntimeError("caption length out of range: %r" % text)
    if "i am human" in text or "i'm human" in text or "real girl" in text:
        raise RuntimeError("caption violated disclosure rule: %r" % text)
    return text


def gen_caption_text(scene):
    q = urllib.parse.quote(STYLE % scene, safe="")
    url = "https://text.pollinations.ai/%s" % q
    # free tier: 1 reply / 30s / IP -> single attempt, then wait out the window
    for attempt in range(3):
        raw = util.http_raw("GET", url, timeout=60, retries=1).decode(errors="replace")
        raw = raw.strip()
        if not raw or raw.startswith("<") or "limit reached" in raw.lower():
            time.sleep(33)
            continue
        return sanitize(raw)
    raise RuntimeError("text endpoint unavailable: %r" % raw[:80])


def pool_fallback(used):
    pool = util.load_json(util.PROMPTS / "captions.json", [])
    fresh = [c for c in pool if c not in used]
    return random.choice(fresh or pool or ["golden hour does most of the work"])


@util.cli_guard
def main(argv):
    limit = 999
    if "--count" in argv:
        try:
            limit = int(argv[argv.index("--count") + 1])
        except Exception:
            limit = 999

    queue = util.load_queue()
    used = [it.get("caption") for it in queue.get("items", []) if it.get("caption")]

    done = 0
    for it in queue.get("items", []):
        if done >= limit:
            break
        if it.get("status") != "queued" or it.get("caption"):
            continue
        try:
            caption = gen_caption_text(it.get("scene", ""))
            source = "generated"
        except Exception as e:
            util.log_event("caption_gen_failed", id=it.get("id"), error=repr(e))
            caption = pool_fallback(used)
            source = "pool"
        it["caption"] = caption
        it["status"] = "captioned"
        used.append(caption)
        done += 1
        util.save_queue(queue)      # persist per item
        util.log_event("captioned", id=it.get("id"), source=source, caption=caption)
        print("[%s] %s -> %s" % (source, it.get("id"), caption))
        time.sleep(31)   # pollinations text free tier: 1 reply / 30s / IP

    util.save_queue(queue)
    print("captioned %d item(s)" % done)


if __name__ == "__main__":
    main(sys.argv[1:])
