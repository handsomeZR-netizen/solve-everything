#!/usr/bin/env python3
"""Recover burned-in (hard) subtitles from a video: find when each line is on screen, then OCR it.

Two glyph detectors:
  median  (default) the subtitle band's background is the per-pixel median over time; text is
          bright (or dark) pixels that differ from it. Best for static or slow backgrounds.
  outline text is bright pixels next to a dark outline/shadow. Use it over moving video.
Intervals are split when the glyph mask changes (IoU below --iou), so a new line starts a new
interval even with no gap. The fullest frame of each interval is OCR'd.

usage:
  python burned_subs.py video.mp4 --crop 140,526,1000,60 --out subs/
  python burned_subs.py video.mp4 --crop 0,600,1280,120 --mode outline --fps 8 --out subs/

Writes subs/subs.json, subs/subs.srt, subs/sub_XXX.png and contact sheets subs/sheet_N.png.
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw


def frames(src, fps, crop):
    x, y, w, h = crop
    cmd = ["ffmpeg", "-v", "error", "-i", src, "-an", "-vf", f"fps={fps},crop={w}:{h}:{x}:{y}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = w * h * 3
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    finally:
        proc.stdout.close()
        proc.wait()


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video"); ap.add_argument("--crop", required=True, help="x,y,w,h of the subtitle band")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=float, default=10.0)
    ap.add_argument("--mode", choices=["median", "outline"], default="median")
    ap.add_argument("--dark-text", action="store_true", help="text darker than background (median mode)")
    ap.add_argument("--bright", type=int, default=200, help="min channel value for light text")
    ap.add_argument("--diff", type=int, default=50, help="min difference from background (median mode)")
    ap.add_argument("--min-pixels", type=int, default=0, help="glyph pixels that mean 'text present' (0 = auto)")
    ap.add_argument("--iou", type=float, default=0.5, help="mask IoU below this starts a new line")
    ap.add_argument("--min-dur", type=float, default=0.3)
    ap.add_argument("--upscale", type=int, default=0, help="OCR upscale factor, 0 = auto (1x, retry 2x if weak)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    crop = tuple(int(float(v)) for v in args.crop.split(","))
    W, H = crop[2], crop[3]
    min_px = args.min_pixels or max(40, int(W * H * 0.002))

    bg = None
    if args.mode == "median":  # pass 1: an evenly spread sample of <= 256 frames gives the background
        sample, stride = [], 1
        for k, f in enumerate(frames(args.video, 1.0, crop)):
            if k % stride == 0:
                sample.append(f)
                if len(sample) > 256:  # keep memory flat on long videos: halve the sample, double the stride
                    sample, stride = sample[::2], stride * 2
        if not sample:
            sys.exit("no frames decoded")
        bg = np.median(np.stack(sample).astype(np.int16), 0).astype(np.int16)
        del sample

    def glyphs(a):
        a = a.astype(np.int16)
        if args.mode == "median":
            diff = np.abs(a - bg).max(2)
            if args.dark_text:
                return (a.max(2) < 255 - args.bright) & (diff > args.diff)
            return (a.min(2) > args.bright) & (diff > args.diff)
        light = a.min(2) > args.bright
        dark = a.max(2) < 90
        near = np.zeros_like(dark)
        for dy in (-2, -1, 0, 1, 2):
            for dx in (-2, -1, 0, 1, 2):
                near |= np.roll(np.roll(dark, dy, 0), dx, 1)
        return light & near

    segs, cur = [], None  # cur = dict(start, end, ref, best_cnt, best_frame)
    n = 0
    for i, f in enumerate(frames(args.video, args.fps, crop)):
        n = i + 1
        m = glyphs(f)
        c = int(m.sum())
        if c < min_px:
            if cur:
                segs.append(cur)
                cur = None
            continue
        if cur is not None:
            inter = (m & cur["ref"]).sum()
            union = (m | cur["ref"]).sum()
            if inter / max(union, 1) < args.iou:
                segs.append(cur)
                cur = None
        if cur is None:
            cur = {"start": i, "end": i, "ref": m, "best_cnt": c, "best": f.copy()}
            continue
        cur["end"] = i
        if c >= cur["best_cnt"]:  # fullest frame = fully faded in; later wins ties
            cur["best_cnt"], cur["best"] = c, f.copy()
        if c > cur["ref"].sum():
            cur["ref"] = m
    if cur:
        segs.append(cur)
    segs = [s for s in segs if (s["end"] - s["start"] + 1) / args.fps >= args.min_dur]
    print(f"{len(segs)} text intervals in {n / args.fps:.1f}s", file=sys.stderr)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ocr import load_engine, ocr_image  # noqa: E402
    run = load_engine()
    res = []
    for k, s in enumerate(segs):
        name = f"sub_{k:03d}.png"
        Image.fromarray(s["best"]).save(os.path.join(args.out, name))
        r = ocr_image(run, os.path.join(args.out, name), 0.5, args.upscale)
        text = "".join(l["text"] for l in r["lines"])
        score = min((l["score"] for l in r["lines"]), default=0.0)
        res.append({"start": round(s["start"] / args.fps, 2), "end": round((s["end"] + 1) / args.fps, 2),
                    "text": text, "score": score, "file": name})
    merged = []  # the same line split by a flicker -> one interval
    for r in res:
        if merged and r["text"] and r["text"] == merged[-1]["text"] and r["start"] - merged[-1]["end"] < 0.35:
            merged[-1]["end"] = r["end"]
        else:
            merged.append(r)
    for k, r in enumerate(merged):
        r["i"] = k
    with open(os.path.join(args.out, "subs.json"), "w", encoding="utf-8") as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "subs.srt"), "w", encoding="utf-8") as fh:
        for k, r in enumerate([r for r in merged if r["text"]], 1):
            fh.write(f"{k}\n{srt_time(r['start'])} --> {srt_time(r['end'])}\n{r['text']}\n\n")

    rows = 20  # contact sheets: crop + time + OCR text, for eyeballing
    tw, th = min(W, 900), max(20, int(H * min(W, 900) / W))
    from PIL import ImageFont
    font = None
    for p in ("C:/Windows/Fonts/msyh.ttc", "/System/Library/Fonts/PingFang.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if os.path.exists(p):
            font = ImageFont.truetype(p, 16)
            break
    for p in range(0, len(merged), rows):
        chunk = merged[p:p + rows]
        sheet = Image.new("RGB", (tw + 140, len(chunk) * (th + 26)), (32, 32, 32))
        d = ImageDraw.Draw(sheet)
        for j, r in enumerate(chunk):
            y = j * (th + 26)
            sheet.paste(Image.open(os.path.join(args.out, r["file"])).resize((tw, th)), (140, y))
            d.text((6, y + 4), f"#{r['i']} {r['start']:.2f}", fill=(255, 220, 0), font=font)
            d.text((140, y + th + 3), r["text"] or "(no text)", fill=(140, 230, 140), font=font)
        sheet.save(os.path.join(args.out, f"sheet_{p // rows}.png"))
    for r in merged:
        print(f"{r['start']:8.2f} {r['end']:8.2f}  {r['text']}")


if __name__ == "__main__":
    main()
