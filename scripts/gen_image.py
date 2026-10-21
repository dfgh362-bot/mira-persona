"""Generate MIRA images via Pollinations (flux, no key).

Each image: persona base prompt (verbatim prefix) + scene + variation modifier.
Saved to content/{tier}/{YYYY-MM-DD}/, enqueued in content/queue.json.

CLI:
  python scripts/gen_image.py --tier free --count 4
  python scripts/gen_image.py --tier paid --count 2 [--date 2026-10-21] [--scene 3]
"""
import random
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

MODIFIERS = [
    "candid expression",
    "soft smile",
    "looking away from camera",
    "looking at camera",
    "half body framing",
    "full body framing",
    "sitting relaxed",
    "standing relaxed",
    "laughing softly",
    "quiet expression",
]

FALLBACK_SCENE = "walking a Lisbon street at golden hour, denim jacket"


@util.cli_guard
def main(argv):
    tier = "free"
    count = 1
    date = util.today()
    scene_idx = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--tier":
            i += 1
            tier = argv[i] if i < len(argv) else "free"
        elif a == "--count":
            i += 1
            try:
                count = max(1, int(argv[i]))
            except Exception:
                count = 1
        elif a == "--date":
            i += 1
            date = argv[i]
        elif a == "--scene":
            i += 1
            scene_idx = int(argv[i])
        i += 1
    if tier not in ("free", "paid"):
        tier = "free"

    # daily quota guard (schedule.json x R-05 escalation): skip or trim if cap met
    cap = util.effective_quota("img_free_day" if tier == "free" else "img_paid_day",
                               8 if tier == "free" else 4)
    day_dir = util.CONTENT / tier / date
    have = len(list(day_dir.glob("*.jpg"))) if day_dir.exists() else 0
    if have >= cap:
        print("quota met (%d/%d %s images today), skipping" % (have, cap, tier))
        return
    count = min(count, cap - have)

    persona = util.load_config("persona.json")
    base = persona.get("base_prompt", "")
    scenes = util.load_json(util.PROMPTS / "scenes.json", []) or [FALLBACK_SCENE]
    if scene_idx is not None:
        scenes = [scenes[scene_idx % len(scenes)]]

    queue = util.load_queue()
    ledger = util.load_ledger()
    seq_start = ledger["counts"].get(tier, 0)

    made = 0
    consec_fails = 0
    for i in range(count):
        seq = seq_start + i
        scene = scenes[seq % len(scenes)]
        mod = MODIFIERS[(seq // len(scenes)) % len(MODIFIERS)]
        seed = random.randint(1, 999999)
        prompt = ("%s, %s, %s" % (base, scene, mod))[:1500]
        q = urllib.parse.quote(prompt, safe="")
        fname = "mira_%s_%s_%03d_%06d.jpg" % (tier, date.replace("-", ""), seq, seed)
        rel = "content/%s/%s/%s" % (tier, date, fname)
        used_model = None
        # zero-cost model ladder: flux first, turbo fallback.
        # pollinations anonymous tier intermittently 402s (per-IP quota);
        # actions runners get a fresh IP each run and 4 attempts x cooldowns fit the 20-min window.
        for model in ("flux", "turbo", "flux", "turbo"):
            url = ("https://image.pollinations.ai/prompt/%s"
                   "?width=1024&height=1536&model=%s&seed=%d&nologo=true" % (q, model, seed))
            try:
                dest = util.http_download(url, util.ROOT / rel, timeout=180,
                                          retries=1, min_size=2000)
                with open(dest, "rb") as f:
                    magic = f.read(2)
                if magic != b"\xff\xd8":
                    dest.unlink(missing_ok=True)
                    raise RuntimeError("response not a JPEG (magic=%r)" % magic)
                used_model = model
                break
            except Exception as e:
                util.log_event("image_attempt_failed", scene=scene, seed=seed,
                               model=model, error=repr(e))
                print("retry %s/%s %r" % (model, scene[:40], e))
                time.sleep(random.uniform(20, 30))
        try:
            if used_model is None:
                raise RuntimeError("all models failed")
            item = {
                "id": "%s-%s-s%06d" % (date, tier, seed),
                "tier": tier,
                "file": rel,
                "cdn": util.jsdelivr(rel),
                "scene": scene,
                "modifier": mod,
                "seed": seed,
                "model": used_model,
                "prompt": prompt,
                "caption": None,
                "status": "queued",
                "created": util.ts(),
                "posted_at": None,
            }
            queue["items"].append(item)
            ledger["counts"][tier] = seq + 1
            made += 1
            consec_fails = 0
            util.save_queue(queue)      # persist per item: partial progress survives kills
            util.save_ledger(ledger)
            util.log_event("image_generated", id=item["id"], file=rel, seed=seed, model=used_model)
            print("ok %s (%s, seed %d)" % (rel, used_model, seed))
        except Exception as e:
            util.log_event("image_failed", scene=scene, seed=seed, error=repr(e))
            print("FAIL %s: %r" % (scene, e))
            consec_fails += 1
            if consec_fails >= 2:
                print("early abort: %d consecutive failures — upstream blocked, next cycle retries" % consec_fails)
                break
        time.sleep(random.uniform(2, 4))

    util.save_queue(queue)
    util.save_ledger(ledger)
    print("generated %d/%d %s image(s)" % (made, count, tier))


if __name__ == "__main__":
    main(sys.argv[1:])
