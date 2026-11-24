#!/usr/bin/env python3
"""Draw a fused timeline as pictures: who spoke when, which slide was up, how sure the ASR was.

A model that cannot hear can still *see* misalignment: a speaker bar that runs over a
slide change, a red confidence stripe on a name, a turn that starts before the voice does.
Rows wrap every --row seconds and pages stay under ~1500 px so nothing gets downscaled.

usage:
  python timeline_plot.py --timeline timeline.jsonl --out plots/tl          # -> plots/tl_00.png ...
  python timeline_plot.py --timeline timeline.jsonl --audio audio.wav --row 60 --t0 0 --t1 600 --out plots/tl

Lanes per row: time ruler | loudness (with --audio) | one lane per speaker | word confidence
(red < 0.5 < amber < 0.8 < green) | slides (index + first OCR words) | sound events.
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PALETTE = [(78, 121, 167), (242, 142, 43), (89, 161, 79), (225, 87, 89), (118, 183, 178),
           (237, 201, 72), (176, 122, 161), (255, 157, 167), (156, 117, 95), (186, 176, 172)]


def font(size):
    for p in (os.environ.get("SE_FONT", ""), "C:/Windows/Fonts/msyh.ttc", "/System/Library/Fonts/PingFang.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"):
        if p and os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def fit(d, text, f, width):
    if width < 14:
        return ""
    if d.textlength(text, font=f) <= width:
        return text
    while text and d.textlength(text + "…", font=f) > width:
        text = text[:-1]
    return text + "…" if text else ""


def conf_color(p):
    return (214, 39, 40) if p < 0.5 else ((240, 170, 30) if p < 0.8 else (60, 170, 90))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--timeline", required=True); ap.add_argument("--out", required=True, help="output prefix")
    ap.add_argument("--audio"); ap.add_argument("--row", type=float, default=60.0)
    ap.add_argument("--width", type=int, default=1500); ap.add_argument("--max-height", type=int, default=1500)
    ap.add_argument("--t0", type=float, default=0.0); ap.add_argument("--t1", type=float, default=None)
    args = ap.parse_args()

    with open(args.timeline, encoding="utf-8") as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    t1 = args.t1 or max(r["t1"] for r in rows)
    asr = [r for r in rows if r["src"] == "asr"]
    speakers = []
    for r in asr:
        s = r.get("spk") or "?"
        if s not in speakers:
            speakers.append(s)
    color = {s: PALETTE[i % len(PALETTE)] for i, s in enumerate(speakers)}
    slides = [r for r in rows if r["src"] == "slide"]
    events = [r for r in rows if r["src"] == "event"]

    energy, e_hop = None, 0.05
    if args.audio:
        import subprocess
        raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", args.audio, "-vn", "-ac", "1", "-ar", "16000",
                              "-f", "f32le", "-"], capture_output=True)
        if raw.returncode != 0:
            sys.exit(raw.stderr.decode("utf-8", "replace"))
        y = np.frombuffer(raw.stdout, np.float32).copy()
        n = int(e_hop * 16000)
        frames = y[: len(y) // n * n].reshape(-1, n)
        energy = 20 * np.log10(np.sqrt((frames ** 2).mean(1)) + 1e-5)
        energy = np.clip((energy + 60) / 60, 0, 1)

    pad_l = 92
    pps = (args.width - pad_l - 8) / args.row
    lane = 22
    lanes = ["ruler"] + (["energy"] if energy is not None else []) + [f"spk:{s}" for s in speakers] + \
            (["conf"] if asr else []) + (["slides"] if slides else []) + (["events"] if events else [])
    heights = {"ruler": 18, "energy": 26, "conf": 10, "slides": lane, "events": 14}
    row_h = sum(heights.get(l, lane) + 3 for l in lanes) + 10
    f, fs = font(13), font(11)
    n_rows = int(np.ceil((t1 - args.t0) / args.row))
    per_page = max(1, args.max_height // row_h)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    written = []
    for p0 in range(0, n_rows, per_page):
        rr = range(p0, min(n_rows, p0 + per_page))
        img = Image.new("RGB", (args.width, row_h * len(rr)), (250, 250, 248))
        d = ImageDraw.Draw(img)
        for k, r_i in enumerate(rr):
            a = args.t0 + r_i * args.row
            b = a + args.row
            X = lambda t: pad_l + (min(max(t, a), b) - a) * pps
            y = k * row_h + 4
            for name in lanes:
                h = heights.get(name, lane)
                label = name.split(":", 1)[1] if name.startswith("spk:") else {"ruler": "", "energy": "level",
                                                                                  "conf": "conf", "slides": "screen",
                                                                                  "events": "events"}[name]
                d.text((4, y + h / 2 - 7), fit(d, label, f, pad_l - 8), fill=(60, 60, 60), font=f)
                if name == "ruler":
                    step = 5 if args.row <= 90 else 30
                    for s in range(0, int(args.row) + 1, step):
                        x = pad_l + s * pps
                        d.line([x, y + 12, x, y + h], fill=(120, 120, 120))
                        t = int(a + s)
                        d.text((x + 2, y), f"{t // 60:02d}:{t % 60:02d}", fill=(90, 90, 90), font=fs)
                elif name == "energy":
                    i0, i1 = int(a / e_hop), min(len(energy), int(b / e_hop))
                    for i in range(i0, i1):
                        x = pad_l + (i * e_hop - a) * pps
                        v = energy[i]
                        d.line([x, y + h - v * h, x, y + h], fill=(150, 150, 160))
                elif name.startswith("spk:"):
                    spk = name[4:]
                    d.rectangle([pad_l, y, args.width - 8, y + h], fill=(240, 240, 236))
                    for r in asr:
                        if (r.get("spk") or "?") == spk and r["t1"] > a and r["t0"] < b:
                            x0, x1 = X(r["t0"]), X(r["t1"])
                            d.rectangle([x0, y + 1, max(x0 + 1, x1), y + h - 1], fill=color[spk])
                            d.text((x0 + 3, y + 3), fit(d, r.get("text", ""), fs, x1 - x0 - 6), fill=(255, 255, 255), font=fs)
                elif name == "conf":
                    for r in asr:
                        if r["t1"] <= a or r["t0"] >= b:
                            continue
                        ws = r.get("words") or [[r["t0"], r["t1"], "", r.get("conf") or 1.0]]
                        for w in ws:
                            if w[1] > a and w[0] < b:
                                d.rectangle([X(w[0]), y, max(X(w[0]) + 1, X(w[1])), y + h], fill=conf_color(w[3]))
                elif name == "slides":
                    for j, s in enumerate(slides):
                        if s["t1"] > a and s["t0"] < b:
                            dyn = "dynamic" in s.get("flags", [])
                            fill = (200, 200, 200) if dyn else ((205, 225, 245) if j % 2 == 0 else (225, 210, 240))
                            x0, x1 = X(s["t0"]), X(s["t1"])
                            d.rectangle([x0, y + 1, max(x0 + 1, x1), y + h - 1], fill=fill, outline=(150, 150, 170))
                            first = (s.get("text") or "").split("\n")[0]
                            lab = ("~ " if dyn else f"#{j} ") + first
                            d.text((x0 + 3, y + 3), fit(d, lab, fs, x1 - x0 - 6), fill=(40, 40, 60), font=fs)
                elif name == "events":
                    for e in events:
                        if e["t1"] > a and e["t0"] < b:
                            x0 = X(e["t0"])
                            d.rectangle([x0, y + 2, max(x0 + 3, X(e["t1"])), y + h - 2], fill=(170, 90, 200))
                            d.text((x0 + 4, y), fit(d, e.get("text", ""), fs, 120), fill=(90, 40, 120), font=fs)
                y += h + 3
            d.line([0, k * row_h + row_h - 2, args.width, k * row_h + row_h - 2], fill=(210, 210, 210))
        path = f"{args.out}_{p0 // per_page:02d}.png"
        img.save(path)
        written.append(path)
    print(f"{len(written)} page(s): " + ", ".join(written))


if __name__ == "__main__":
    main()
