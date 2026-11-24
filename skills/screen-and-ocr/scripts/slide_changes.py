#!/usr/bin/env python3
"""Find slide / page changes in a screen recording and save one clean frame per page.

Streams small grey thumbnails from ffmpeg (memory stays flat for multi-hour videos),
ignores masked regions (camera tiles, chat panels) and small changes (mouse pointer),
waits for the picture to settle after a transition, and marks long unsettled stretches
(scrolling, video playback) as "dynamic". Bullet-by-bullet builds are linked with a
shared "group" so you can OCR only the last, fullest frame of each slide.

usage:
  python slide_changes.py talk.mp4 --out slides/
  python slide_changes.py talk.mp4 --out slides/ --crop 0,0,1600,900 --mask 1600,0,320,180 --fps 2

Writes slides/segments.json and slides/slide_XXX.png (full resolution, cropped):
  [{"i": 0, "kind": "static", "start": 0.0, "end": 41.5, "rep_t": 41.0, "group": 0,
    "build": false, "file": "slide_000.png"}, {"kind": "dynamic", ...}]
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np


def video_size(src):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-print_format", "json",
                          "-show_streams", src], capture_output=True)
    s = json.loads(out.stdout.decode("utf-8", "replace"))["streams"][0]
    w, h = int(s["width"]), int(s["height"])
    rot = int(float((s.get("tags") or {}).get("rotate", 0)))
    for side in s.get("side_data_list") or []:
        rot = int(float(side.get("rotation", rot)))
    return (h, w) if rot % 180 else (w, h)


def parse_box(spec):
    return tuple(int(float(v)) for v in spec.split(","))


def stream_thumbs(src, fps, crop, aw, ah):
    vf = [f"fps={fps}"]
    if crop:
        x, y, w, h = crop
        vf.append(f"crop={w}:{h}:{x}:{y}")
    vf += [f"scale={aw}:{ah}:flags=area", "format=gray"]
    cmd = ["ffmpeg", "-v", "error", "-i", src, "-an", "-vf", ",".join(vf), "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = aw * ah
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(ah, aw).astype(np.int16)
    finally:
        proc.stdout.close()
        proc.wait()


def grab(src, t, crop, path):
    vf = []
    if crop:
        x, y, w, h = crop
        vf = ["-vf", f"crop={w}:{h}:{x}:{y}"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(t, 0):.3f}", "-i", src, "-frames:v", "1",
                    "-update", "1"] + vf + [path], check=True)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video"); ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=float, default=2.0, help="analysis rate (2 is plenty for slides)")
    ap.add_argument("--crop", help="x,y,w,h of the shared-screen area, in displayed pixels")
    ap.add_argument("--mask", action="append", default=[], help="x,y,w,h to ignore (repeatable)")
    ap.add_argument("--pix", type=int, default=14, help="grey-level change that counts as a changed pixel")
    ap.add_argument("--area", type=float, default=0.012, help="changed fraction that counts as a change")
    ap.add_argument("--settle", type=float, default=1.0, help="seconds of stillness that end a transition")
    ap.add_argument("--dynamic", type=float, default=4.0,
                    help="a transition longer than this becomes a 'dynamic' segment")
    ap.add_argument("--dyn-every", type=float, default=6.0, help="sample a dynamic segment every N seconds")
    ap.add_argument("--build-area", type=float, default=0.12,
                    help="max changed fraction for an additive build (new bullet) on the same slide")
    ap.add_argument("--no-frames", action="store_true", help="only write segments.json")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    W, H = video_size(args.video)
    crop = parse_box(args.crop) if args.crop else None
    cx, cy, cw, ch = crop if crop else (0, 0, W, H)
    aw = 192
    ah = max(16, int(round(aw * ch / cw)))
    keep = np.ones((ah, aw), bool)
    for spec in args.mask:
        x, y, w, h = parse_box(spec)
        x0 = int((x - cx) * aw / cw); x1 = int(np.ceil((x + w - cx) * aw / cw))
        y0 = int((y - cy) * ah / ch); y1 = int(np.ceil((y + h - cy) * ah / ch))
        keep[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = False
    n_keep = keep.sum()

    def frac(a, b):
        return float(((np.abs(a - b) > args.pix) & keep).sum()) / n_keep

    dt = 1.0 / args.fps
    settle_n = max(1, int(round(args.settle * args.fps)))
    segs, flashes, pending = [], [], []
    state, ref, last, seg_start, last_stable = "stable", None, None, 0.0, 0.0
    change_start, still, i = 0.0, 0, -1
    plat_start, plat_f = 0.0, None

    def close_static(end, rep):
        segs.append({"kind": "static", "start": round(seg_start, 2), "end": round(end, 2),
                     "rep_t": round(rep, 2), "ref": ref})

    def flush_plateau(t_end):
        # A short plateau inside a transition (>= 2 identical samples, but shorter than --settle) that
        # differs from the page before it: a card or popup that flashed by. Waiting for the picture
        # to "settle" would throw exactly these away, and they often carry the one fact nobody says.
        if plat_f is not None and still >= 1 and frac(plat_f, ref) > args.area:
            pending.append({"start": plat_start, "end": t_end, "f": plat_f})

    for i, f in enumerate(stream_thumbs(args.video, args.fps, crop, aw, ah)):
        t = i * dt
        if ref is None:
            ref, last, seg_start, last_stable = f, f, t, t
            continue
        if state == "stable":
            if frac(f, ref) <= args.area:
                last_stable = t
            else:
                state, change_start, still, plat_start, plat_f, pending = "changing", t, 0, t, f, []
        else:
            if frac(f, last) <= args.area:
                still += 1
            else:
                flush_plateau(t)
                still, plat_start, plat_f = 0, t, f
            if still >= settle_n:
                settle_t = plat_start
                if frac(f, ref) <= args.area:  # back to the same page (popup, pointer, flash card)
                    state, last_stable = "stable", t
                    flashes.extend(pending)
                else:
                    close_static(change_start, last_stable)
                    flashes.extend(p for p in pending if frac(p["f"], f) > args.area)
                    if settle_t - change_start >= args.dynamic:
                        segs.append({"kind": "dynamic", "start": round(change_start, 2), "end": round(settle_t, 2)})
                    seg_start, last_stable, ref, state = settle_t, t, f, "stable"
                pending = []
        last = f
    if ref is None:
        sys.exit("no frames decoded")
    end_t = (i + 1) * dt
    if state == "changing":
        flush_plateau(end_t)
        flashes.extend(pending)
    if state == "changing" and end_t - change_start >= args.dynamic:
        close_static(change_start, last_stable)
        segs.append({"kind": "dynamic", "start": round(change_start, 2), "end": round(end_t, 2)})
    else:
        close_static(end_t, last_stable)
    for p in flashes:
        rep = p["start"] + max(0.0, p["end"] - p["start"] - dt) / 2
        segs.append({"kind": "flash", "start": round(p["start"], 2), "end": round(p["end"], 2),
                     "rep_t": round(rep, 2), "ref": p["f"]})
    segs.sort(key=lambda s: (s["start"], s["kind"] != "static"))

    # link additive builds: small change whose changed pixels were empty background before
    group, prev_static = -1, None
    for s in segs:
        if s["kind"] == "flash":
            continue
        if s["kind"] != "static":
            prev_static = None
            continue
        s["build"] = False
        if prev_static is not None:
            a, b = prev_static["ref"], s["ref"]
            changed = (np.abs(a - b) > args.pix) & keep
            fr = changed.sum() / n_keep
            if fr <= args.build_area and changed.any():
                bg = np.bincount(a[keep].ravel().clip(0, 255)).argmax()
                if (np.abs(a[changed] - bg) < 12).mean() > 0.85:
                    s["build"] = True
        if not s["build"]:
            group += 1
        s["group"] = group
        prev_static = s

    for k, s in enumerate(segs):
        s["i"] = k
        s.pop("ref", None)
    # within each group only the last build is the complete slide
    last_of_group = {}
    for s in segs:
        if s["kind"] == "static":
            last_of_group[s["group"]] = s["i"]
    for s in segs:
        if s["kind"] == "static":
            s["complete"] = last_of_group[s["group"]] == s["i"]

    if not args.no_frames:
        for s in segs:
            if s["kind"] in ("static", "flash"):
                s["file"] = f"{'slide' if s['kind'] == 'static' else 'flash'}_{s['i']:03d}.png"
                grab(args.video, s["rep_t"], crop, os.path.join(args.out, s["file"]))
            else:
                s["samples"] = []
                t = s["start"] + args.dyn_every / 2
                while t < s["end"]:
                    name = f"dyn_{s['i']:03d}_{int(t * 10):06d}.png"
                    grab(args.video, t, crop, os.path.join(args.out, name))
                    s["samples"].append({"t": round(t, 2), "file": name})
                    t += args.dyn_every
    with open(os.path.join(args.out, "segments.json"), "w", encoding="utf-8") as fh:
        json.dump(segs, fh, ensure_ascii=False, indent=1)
    n_static = sum(1 for s in segs if s["kind"] == "static")
    n_flash = sum(1 for s in segs if s["kind"] == "flash")
    n_groups = len(last_of_group)
    print(f"{n_static} static segments in {n_groups} slide groups, {n_flash} flash(es), "
          f"{len(segs) - n_static - n_flash} dynamic stretches -> {args.out}/segments.json")
    for s in segs:
        extra = (" build" if s.get("build") else "") + ("" if s.get("complete", True) else " (partial)")
        print(f"  #{s['i']:3d} {s['kind']:7s} {s['start']:8.2f}-{s['end']:8.2f}{extra}")


if __name__ == "__main__":
    main()
