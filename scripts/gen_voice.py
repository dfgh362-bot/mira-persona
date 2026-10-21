"""Pre-generate MIRA voice notes (zero-cost TTS: edge-tts, no key).

20 notes, rotated weekly per section 11. Voice: en-GB female, warm, slightly slow.
Disclosure is baked into the lines themselves (the pinned post says voice notes are
generated, and these lines never claim otherwise).

CLI:
  python scripts/gen_voice.py            # ensure all 20 exist
  python scripts/gen_voice.py --force    # regenerate all
"""
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

VOICE = "en-GB-SoniaNeural"
RATE = "-6%"
PITCH = "+0Hz"

LINES = [
    "hey, mira here. well, mira's voice. same thing, roughly.",
    "quick heads up — i'm ai generated. including this voice. obviously.",
    "made of prompts and oat milk.",
    "it's always golden hour somewhere.",
    "the camera collection grew again. this is fine.",
    "unwell before ten, thriving after. as foretold.",
    "this was synthesized in about two seconds. respect the efficiency.",
    "lisbon's showing off again today.",
    "new roll loaded. wish me luck.",
    "if you're hearing this, hi. you're early.",
    "reminder that i'm not a real person, and the light was still perfect.",
    "the oat cortado remains a personality trait.",
    "film grain is just noise with good branding.",
    "day off, no plans, perfect.",
    "found another camera i don't need. need is a strong word anyway.",
    "rooftop update: wind, sunset, zero complaints.",
    "this voice note is one hundred percent generated, one hundred percent sincere ish.",
    "who else photographs the sky on the walk home? just me?",
    "overcast is the best free filter.",
    "okay bye — going back to being a very consistent set of prompts.",
]


def ensure_edge_tts():
    if shutil.which("edge-tts"):
        return
    for extra in ([], ["--break-system-packages"]):
        proc = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "edge-tts"] + extra,
                              capture_output=True, timeout=300)
        if proc.returncode == 0 and shutil.which("edge-tts"):
            return
    if not shutil.which("edge-tts"):
        raise RuntimeError("edge-tts unavailable (pip install failed?)")


def make_note(text, out):
    cmd = ["edge-tts", "--voice", VOICE, "--rate=%s" % RATE, "--pitch=%s" % PITCH,
           "--text", text, "--write-media", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 or not out.exists() or out.stat().st_size < 1500:
        raise RuntimeError("edge-tts failed: %s" % (proc.stderr or "no output")[:200])


@util.cli_guard
def main(argv):
    force = "--force" in argv
    try:
        ensure_edge_tts()
    except Exception as e:
        util.log_event("voice_skipped", reason=repr(e))
        print("edge-tts unavailable — skipping (workflow will retry)")
        return
    made = 0
    for i, line in enumerate(LINES, start=1):
        out = util.CONTENT / "voice" / ("voice_%02d.mp3" % i)
        if out.exists() and not force and out.stat().st_size > 1500:
            continue
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            make_note(line, out)
            made += 1
            print("ok %s" % out.name)
        except Exception as e:
            util.log_event("voice_failed", file=out.name, error=repr(e))
            print("FAIL %s: %r" % (out.name, e))
    ledger = util.load_ledger()
    total = len(list((util.CONTENT / "voice").glob("voice_*.mp3")))
    ledger["counts"]["voice"] = total
    util.save_ledger(ledger)
    util.log_event("voice_batch", generated=made, total=total)
    print("voice notes: %d total (%d new)" % (total, made))


if __name__ == "__main__":
    main(sys.argv[1:])
