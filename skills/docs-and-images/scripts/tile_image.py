#!/usr/bin/env python3
"""Make big images readable for a vision model: fit them, or cut them into overlapping tiles.

Vision models downscale large images (Claude: long edge above ~1568 px), so small print in a
long screenshot, poster, dashboard or scanned page turns to mush. Tiling keeps the pixels.

usage:
  python tile_image.py long_screenshot.png --out tiles/              # tiles <= 1500 px, 12% overlap
  python tile_image.py poster.jpg --out tiles/ --max 1200 --overlap 0.2
  python tile_image.py photo.jpg --fit --out small.jpg               # just downscale to <= 1568 px

Tiles are named tile_r{row}_c{col}.png; tiles/index.json records each tile's box in the
original image so findings can be mapped back.
"""
import argparse
import json
import math
import os
import sys

from PIL import Image


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image"); ap.add_argument("--out", required=True)
    ap.add_argument("--max", type=int, default=1500, help="max tile edge in pixels")
    ap.add_argument("--overlap", type=float, default=0.12, help="fraction of a tile shared with its neighbour")
    ap.add_argument("--fit", action="store_true", help="downscale the whole image to <= 1568 px instead")
    args = ap.parse_args()

    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(args.image)
    im = im.convert("RGB") if im.mode not in ("RGB", "L") else im
    w, h = im.size
    if args.fit:
        k = min(1.0, 1568 / max(w, h))
        im.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS).save(args.out)
        print(f"{w}x{h} -> {int(w * k)}x{int(h * k)}: {args.out}")
        return
    os.makedirs(args.out, exist_ok=True)
    step = int(args.max * (1 - args.overlap))
    cols = 1 if w <= args.max else math.ceil((w - args.max) / step) + 1
    rows = 1 if h <= args.max else math.ceil((h - args.max) / step) + 1
    index = []
    for r in range(rows):
        for c in range(cols):
            x0 = min(c * step, max(0, w - args.max)); y0 = min(r * step, max(0, h - args.max))
            box = (x0, y0, min(w, x0 + args.max), min(h, y0 + args.max))
            name = f"tile_r{r}_c{c}.png"
            im.crop(box).save(os.path.join(args.out, name))
            index.append({"file": name, "row": r, "col": c, "box": list(box)})
    with open(os.path.join(args.out, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"source": args.image, "size": [w, h], "tiles": index}, fh, ensure_ascii=False, indent=1)
    print(f"{w}x{h} -> {rows}x{cols} tiles in {args.out} (read them in row order)")


if __name__ == "__main__":
    main()
