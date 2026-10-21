"""Make MIRA video clips: ken-burns (zoompan) + crossfade (xfade) over stills, ffmpeg.

720x1280 portrait, alternating zoom in/out, 4s per still, 0.6s crossfades.
Zero cost, no audio. Output: content/video/mira_clip_<date>_<n>.mp4

CLI:
  python scripts/make_video.py --auto            # up to 5 recent free stills
  python scripts/make_video.py --from a.jpg b.jpg c.jpg
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import util

W, H, FPS = 720, 1280, 30
DUR, FADE = 4.0, 0.6


def clip_index(n):
    existing = sorted((util.CONTENT / "video").glob("mira_clip_*.mp4")) if (util.CONTENT / "video").exists() else []
    return len(existing) + 1


def today_clips():
    d = util.today().replace("-", "")
    vdir = util.CONTENT / "video"
    return len(list(vdir.glob("mira_clip_%s_*.json" % d))) if vdir.exists() else 0


def pick_stills():
    queue = util.load_queue()
    cand = [it for it in queue.get("items", [])
            if it.get("tier") == "free" and it.get("status") in ("captioned", "posted", "archived")]
    cand.sort(key=lambda it: it.get("created") or "", reverse=True)
    used = []
    seen_clip = set()
    # prefer stills not already used in an existing clip
    for clip in (util.CONTENT / "video").glob("*.json") if (util.CONTENT / "video").exists() else []:
        try:
            import json
            seen_clip.update(json.loads(clip.read_text()).get("files", []))
        except Exception:
            pass
    for it in cand:
        rel = it["file"]
        if rel in seen_clip:
            continue
        if (util.ROOT / rel).exists():
            used.append(it)
        if len(used) >= 5:
            break
    if len(used) < 3:
        for it in cand:  # allow reuse if not enough fresh ones
            if it not in used and (util.ROOT / it["file"]).exists():
                used.append(it)
            if len(used) >= 3:
                break
    return used[:5]


def build(paths, out):
    n = len(paths)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for p in paths:
        cmd += ["-i", str(p)]   # single frame per input; zoompan d=N expands it to N frames
    parts = []
    for i in range(n):
        if i % 2 == 0:
            z = "min(1.0+0.0015*on,1.25)"
        else:
            z = "if(eq(on,0),1.25,max(1.001,zoom-0.0015))"
        parts.append(
            "[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,"
            "crop=%d:%d,zoompan=z='%s':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            "d=%d:s=%dx%d:fps=%d[v%d];" % (i, W, H, W, H, z, int(DUR * FPS), W, H, FPS, i))
    prev = "[v0]"
    for k in range(1, n):
        offset = k * (DUR - FADE)   # joining clip k+1: cumulative playhead = k*(DUR-FADE)
        lbl = "[x%d]" % k
        parts.append("%s[v%d]xfade=transition=fade:duration=%.2f:offset=%.2f%s;"
                     % (prev, k, FADE, offset, lbl))
        prev = lbl
    # last label is used as final output; strip trailing ';' of last part
    filt = "".join(parts).rstrip(";")
    cmd += ["-filter_complex", filt, "-map", prev,
            "-c:v", "libx264", "-r", str(FPS), "-pix_fmt", "yuv420p",
            "-crf", "26", "-preset", "veryfast", "-an",
            "-movflags", "+faststart", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed: %s" % proc.stderr[-500:])
    return out


@util.cli_guard
def main(argv):
    if shutil.which("ffmpeg") is None:
        util.log_event("video_skipped", reason="ffmpeg not installed")
        print("ffmpeg not installed — skipping")
        return
    if "--from" in argv:
        idx = argv.index("--from")
        paths = [Path(x) for x in argv[idx + 1:]]
    else:
        sched = util.load_config("schedule.json").get("quotas", {})
        if today_clips() >= sched.get("video_day", 2):
            print("video quota met (%d today), skipping" % today_clips())
            return
        items = pick_stills()
        if len(items) < 3:
            util.log_event("video_skipped", reason="not enough stills (need >=3)")
            print("not enough stills yet — skipping (need >= 3)")
            return
        paths = [util.ROOT / it["file"] for it in items]
    out = util.CONTENT / "video" / ("mira_clip_%s_%02d.mp4" % (util.today().replace("-", ""), clip_index(0)))
    build(paths, out)
    manifest = util.CONTENT / "video" / (out.stem + ".json")
    util.save_json(manifest, {"files": [str(p.relative_to(util.ROOT)) for p in paths],
                              "built": util.ts()})
    ledger = util.load_ledger()
    ledger["counts"]["video"] += 1
    util.save_ledger(ledger)
    util.log_event("video_built", file=str(out.relative_to(util.ROOT)), stills=len(paths))
    print("built %s from %d stills" % (out.relative_to(util.ROOT), len(paths)))


if __name__ == "__main__":
    main(sys.argv[1:])
