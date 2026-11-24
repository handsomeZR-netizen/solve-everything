#!/usr/bin/env python3
"""Tile many images into a few captioned pages, so one look checks dozens of frames.

usage:
  python contact_sheet.py frames/*.jpg --out sheets/s                 # captions = file names
  python contact_sheet.py --dir frames/ --index frames/index.json --out sheets/s   # captions = times
  python contact_sheet.py --segments slides/segments.json --out sheets/slides       # slide frames + OCR
  python contact_sheet.py --subs subs/subs.json --out sheets/subs --cols 1 --thumb 900

Pages are capped at --max-height so a vision model does not downscale them into mush.
"""
import argparse
import glob
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont


def font(size):
    for p in (os.environ.get("SE_FONT", ""), "C:/Windows/Fonts/msyh.ttc", "/System/Library/Fonts/PingFang.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"):
        if p and os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def ts(t):
    t = int(t)
    return f"{t // 60:02d}:{t % 60:02d}"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="*")
    ap.add_argument("--dir"); ap.add_argument("--index", help="index.json from extract.py frames")
    ap.add_argument("--segments"); ap.add_argument("--subs")
    ap.add_argument("--out", required=True, help="output prefix")
    ap.add_argument("--cols", type=int, default=4); ap.add_argument("--thumb", type=int, default=360)
    ap.add_argument("--max-height", type=int, default=1500)
    ap.add_argument("--caption-lines", type=int, default=2)
    args = ap.parse_args()

    items = []  # (path, caption)
    if args.segments:
        base = os.path.dirname(os.path.abspath(args.segments))
        for s in json.load(open(args.segments, encoding="utf-8")):
            if s.get("file"):
                first = " / ".join((s.get("ocr") or "").split("\n")[:2])
                items.append((os.path.join(base, s["file"]), f"#{s['i']} {ts(s['start'])}-{ts(s['end'])} {first}"))
            for x in s.get("samples", []):
                items.append((os.path.join(base, x["file"]), f"#{s['i']}~ {ts(x['t'])}"))
    elif args.subs:
        base = os.path.dirname(os.path.abspath(args.subs))
        for s in json.load(open(args.subs, encoding="utf-8")):
            items.append((os.path.join(base, s["file"]), f"{s['start']:.2f}-{s['end']:.2f} {s['text']}"))
    else:
        paths = []
        for p in args.images:
            paths += sorted(glob.glob(p)) or [p]
        if args.dir:
            paths += [os.path.join(args.dir, f) for f in sorted(os.listdir(args.dir))
                      if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
        times = {}
        if args.index:
            times = {x["file"]: x["t"] for x in json.load(open(args.index, encoding="utf-8"))}
        for p in paths:
            name = os.path.basename(p)
            items.append((p, f"{ts(times[name])}  {name}" if name in times else name))
    if not items:
        sys.exit("no images")

    f = font(14)
    first = Image.open(items[0][0])
    th = int(args.thumb * first.height / first.width)
    cap_h = 6 + 18 * args.caption_lines
    cell_w, cell_h = args.thumb + 8, th + cap_h + 8
    rows_per_page = max(1, args.max_height // cell_h)
    per_page = rows_per_page * args.cols
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    written = []
    for p0 in range(0, len(items), per_page):
        chunk = items[p0:p0 + per_page]
        rows = (len(chunk) + args.cols - 1) // args.cols
        sheet = Image.new("RGB", (cell_w * args.cols, cell_h * rows), (28, 28, 30))
        d = ImageDraw.Draw(sheet)
        for j, (path, cap) in enumerate(chunk):
            x, y = (j % args.cols) * cell_w + 4, (j // args.cols) * cell_h + 4
            im = Image.open(path).convert("RGB")
            im.thumbnail((args.thumb, th))
            sheet.paste(im, (x, y))
            lines, cur = [], ""
            for ch in cap:
                if d.textlength(cur + ch, font=f) > args.thumb:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            lines.append(cur)
            for li, text in enumerate(lines[:args.caption_lines]):
                d.text((x, y + th + 3 + li * 18), text, fill=(235, 220, 120) if li == 0 else (200, 200, 200), font=f)
        path = f"{args.out}_{p0 // per_page:02d}.png"
        sheet.save(path)
        written.append(path)
    print(f"{len(items)} images -> {len(written)} page(s): " + ", ".join(written))


if __name__ == "__main__":
    main()
