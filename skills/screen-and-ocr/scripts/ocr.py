#!/usr/bin/env python3
"""OCR images with RapidOCR (PaddleOCR models on ONNX, CPU) and return text in reading order.

What it adds on top of the raw engine:
  * upscales small images before OCR (small glyphs are the #1 cause of misreads)
  * drops low-score boxes, groups boxes into lines, sorts lines top-to-bottom, left-to-right
  * detects a two-column layout (a vertical gutter) and reads the left column first
  * works with both the old `rapidocr_onnxruntime` package and the newer `rapidocr`

usage:
  python ocr.py slide.png another.jpg --out ocr.json
  python ocr.py slides/ --out ocr.json                      # every png/jpg in the folder
  python ocr.py --segments slides/segments.json             # fills "ocr" into each static segment
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image


def load_engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
        eng = RapidOCR()

        def run(img):
            res, _ = eng(img)
            return [(np.asarray(b, float), t, float(s)) for b, t, s in (res or [])]
        return run
    except ImportError:
        pass
    try:
        from rapidocr import RapidOCR
    except ImportError:
        sys.exit("install an OCR engine: pip install rapidocr-onnxruntime   (or: pip install rapidocr onnxruntime)")
    eng = RapidOCR()

    def run(img):
        out = eng(img)
        if out is None or getattr(out, "boxes", None) is None:
            return []
        return [(np.asarray(b, float), t, float(s)) for b, t, s in zip(out.boxes, out.txts, out.scores)]
    return run


def to_lines(items, width):
    """items: [(x0, y0, x1, y1, text, score)] -> list of lines in reading order."""
    if not items:
        return []

    def group_lines(boxes):
        boxes = sorted(boxes, key=lambda b: (b[1] + b[3]) / 2)
        lines = []
        for b in boxes:
            cy, h = (b[1] + b[3]) / 2, b[3] - b[1]
            if lines:
                L = lines[-1]
                lcy = sum((x[1] + x[3]) / 2 for x in L) / len(L)
                lh = max(x[3] - x[1] for x in L)
                if abs(cy - lcy) < 0.5 * max(h, lh):
                    L.append(b)
                    continue
            lines.append([b])
        return [sorted(L, key=lambda b: b[0]) for L in lines]

    # two-column detection on boxes narrower than 60% of the page
    narrow = [b for b in items if (b[2] - b[0]) < 0.6 * width]
    wide = [b for b in items if (b[2] - b[0]) >= 0.6 * width]
    cover = np.zeros(int(width) + 1, bool)
    for b in narrow:
        cover[int(max(0, b[0])):int(min(width, b[2])) + 1] = True
    lo, hi = int(0.25 * width), int(0.75 * width)
    gutter, run, best = None, 0, 0
    for x in range(lo, hi):
        run = run + 1 if not cover[x] else 0
        if run > best:
            best, gutter = run, x - run // 2
    columns = None
    if gutter is not None and best >= 0.03 * width:
        left = [b for b in narrow if (b[0] + b[2]) / 2 < gutter]
        right = [b for b in narrow if (b[0] + b[2]) / 2 >= gutter]
        if len(left) >= 2 and len(right) >= 2:
            columns = (left, right)
    if not columns:
        return group_lines(items)
    top = min(b[1] for b in narrow)
    head = [b for b in wide if (b[1] + b[3]) / 2 < top]
    tail = [b for b in wide if (b[1] + b[3]) / 2 >= top]
    return group_lines(head) + group_lines(columns[0]) + group_lines(columns[1]) + group_lines(tail)


def join(parts):
    out = ""
    for p in parts:
        if out and out[-1].isascii() and out[-1].isalnum() and p[:1].isascii() and p[:1].isalnum():
            out += " "
        out += p
    return out


def _detect(run, im, k, min_score):
    w, h = im.size
    big = im.resize((w * k, h * k), Image.LANCZOS) if k > 1 else im
    arr = np.asarray(big)[:, :, ::-1].copy()  # BGR, the OpenCV convention the engine expects
    items, low = [], 0
    for box, text, score in run(arr):
        if score < min_score or not text.strip():
            low += 1
            continue
        xs, ys = box[:, 0] / k, box[:, 1] / k
        items.append((xs.min(), ys.min(), xs.max(), ys.max(), text.strip(), score))
    return items, low


def ocr_image(run, path, min_score, upscale):
    """upscale > 0 forces a factor. upscale == 0 (auto) reads at 1x and retries at 2x only when the
    1x result is weak: upscaling helps tiny glyphs but can break detection of text that is
    already large (a 30 px subtitle doubled to 60 px was missed entirely in testing)."""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    if upscale > 0:
        k = upscale
        items, low = _detect(run, im, k, min_score)
    else:
        k = 1
        items, low = _detect(run, im, 1, min_score)
        weak = not items or min(i[5] for i in items) < 0.8
        if weak and min(w, h) < 720:
            items2, low2 = _detect(run, im, 2, min_score)
            mass = lambda its: sum(i[5] * len(i[4]) for i in its)
            if mass(items2) > mass(items):
                items, low, k = items2, low2, 2
    lines = []
    for L in to_lines(items, w):
        lines.append({"text": join([b[4] for b in L]), "score": round(min(b[5] for b in L), 3),
                      "box": [round(min(b[0] for b in L)), round(min(b[1] for b in L)),
                              round(max(b[2] for b in L)), round(max(b[3] for b in L))]})
    return {"image": path, "size": [w, h], "upscale": k, "lines": lines,
            "text": "\n".join(l["text"] for l in lines), "dropped_low_score": low}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", help="images or folders")
    ap.add_argument("--segments", help="segments.json from slide_changes.py (updated in place)")
    ap.add_argument("--all-builds", action="store_true", help="with --segments: also OCR partial build frames")
    ap.add_argument("--out", help="JSON output (default: print)")
    ap.add_argument("--min-score", type=float, default=0.5)
    ap.add_argument("--upscale", type=int, default=0, help="0 = auto (2x when the short side < 720 px)")
    args = ap.parse_args()

    run = load_engine()
    if args.segments:
        base = os.path.dirname(os.path.abspath(args.segments))
        with open(args.segments, encoding="utf-8") as fh:
            segs = json.load(fh)
        for s in segs:
            if s.get("kind") == "static" and s.get("file") and (s.get("complete", True) or args.all_builds):
                r = ocr_image(run, os.path.join(base, s["file"]), args.min_score, args.upscale)
                s["ocr"] = r["text"]
                s["ocr_lines"] = r["lines"]
                first = r["text"].splitlines()[0] if r["text"] else ""
                print(f"#{s['i']:3d} {s['start']:8.2f}  {first}")
        with open(args.segments, "w", encoding="utf-8") as fh:
            json.dump(segs, fh, ensure_ascii=False, indent=1)
        return

    paths = []
    for p in args.inputs:
        if os.path.isdir(p):
            paths += [os.path.join(p, f) for f in sorted(os.listdir(p))
                      if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp"))]
        else:
            paths.append(p)
    if not paths:
        ap.error("no images given")
    results = [ocr_image(run, p, args.min_score, args.upscale) for p in paths]
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)
    for r in results:
        print(f"== {r['image']} ({len(r['lines'])} lines, {r['dropped_low_score']} dropped)")
        print(r["text"])


if __name__ == "__main__":
    main()
