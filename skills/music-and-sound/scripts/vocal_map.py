#!/usr/bin/env python3
"""Draw the singing voice as a timed picture, so lyric timing can be checked by eye.

Isolates the centre channel (lead vocals are usually mixed dead centre), removes
percussive energy with HPSS, detects vocal phrases, and renders rows of spectrogram
with a second ruler, phrase bars, optional beat ticks and optional lyric spans on top.
A vision model (or you) can then see whether a lyric line starts where the voice does.

usage:
  python vocal_map.py song.wav --png map.png                       # phrases -> map.json
  python vocal_map.py song.wav --png map.png --t0 20 --t1 80 --lyrics lyrics.json --beats beats.json

lyrics.json: [{"t": 21.3, "end": 24.0, "text": "..."}]   beats.json: output of beats.py
Mono files skip the centre-channel step (it needs a stereo mix).
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ANCHORS = np.array([[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66],
                    [245, 125, 21], [250, 193, 39], [252, 255, 164]], float)  # inferno-like


def colormap(v):
    x = np.clip(v, 0, 1) * (len(ANCHORS) - 1)
    i = np.minimum(x.astype(int), len(ANCHORS) - 2)
    f = (x - i)[..., None]
    return (ANCHORS[i] * (1 - f) + ANCHORS[i + 1] * f).astype(np.uint8)


def font(size):
    for p in (os.environ.get("SE_FONT", ""), "C:/Windows/Fonts/msyh.ttc", "/System/Library/Fonts/PingFang.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"):
        if p and os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio"); ap.add_argument("--png", required=True)
    ap.add_argument("--t0", type=float, default=0.0); ap.add_argument("--t1", type=float, default=None)
    ap.add_argument("--lyrics"); ap.add_argument("--beats")
    ap.add_argument("--row", type=float, default=20.0, help="seconds per row")
    ap.add_argument("--pps", type=int, default=72, help="pixels per second")
    ap.add_argument("--phrases-out", default=None, help="default: next to the png as .json")
    args = ap.parse_args()

    import librosa
    sr, n_fft, hop = 22050, 2048, 256
    dur = None if args.t1 is None else args.t1 - args.t0
    y, _ = librosa.load(args.audio, sr=sr, mono=False, offset=args.t0, duration=dur)
    if y.ndim == 2 and y.shape[0] == 2:
        L = librosa.stft(y[0], n_fft=n_fft, hop_length=hop)
        R = librosa.stft(y[1], n_fft=n_fft, hop_length=hop)
        mid, side = (L + R) / 2, (L - R) / 2
        mask = (np.abs(mid) ** 2 / (np.abs(mid) ** 2 + 2.5 * np.abs(side) ** 2 + 1e-9)) ** 2
        S = np.abs(mid * mask)
    else:
        print("mono input: skipping centre-channel isolation", file=sys.stderr)
        S = np.abs(librosa.stft(y if y.ndim == 1 else y.mean(0), n_fft=n_fft, hop_length=hop))
    Hm, _ = librosa.decompose.hpss(S, margin=(1.0, 3.0))
    hop_t = hop / sr
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    vox = Hm[(freqs > 150) & (freqs < 4000)].sum(0)
    w = int(0.18 / hop_t) | 1
    env = np.convolve(vox, np.hanning(w) / np.hanning(w).sum(), "same")
    env /= np.percentile(env, 98) + 1e-9
    phrases, on = [], None
    for i, v in enumerate(env):  # hysteresis: start above 0.16, end below 0.09
        if on is None and v > 0.16:
            on = i
        elif on is not None and v < 0.09:
            if (i - on) * hop_t > 0.25:
                phrases.append([on * hop_t + args.t0, i * hop_t + args.t0])
            on = None
    merged = []
    for a, b in phrases:
        if merged and a - merged[-1][1] < 0.16:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    out_json = args.phrases_out or os.path.splitext(args.png)[0] + ".json"
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump([[round(a, 2), round(b, 2)] for a, b in merged], fh)

    M = librosa.feature.melspectrogram(S=Hm ** 2, sr=sr, n_mels=110, fmin=100, fmax=2400)
    D = np.clip((librosa.power_to_db(M, ref=np.max) + 50) / 50, 0, 1)[::-1]
    rgb = colormap(D)
    lyrics = json.load(open(args.lyrics, encoding="utf-8")) if args.lyrics else []
    beats = json.load(open(args.beats, encoding="utf-8")).get("beats", []) if args.beats else []
    f = font(15)
    total = D.shape[1] * hop_t
    rows = []
    for r in range(int(np.ceil(total / args.row))):
        a = r * args.row
        i0, i1 = int(a / hop_t), min(int((a + args.row) / hop_t), D.shape[1])
        width = args.pps * int(args.row)
        strip = Image.fromarray(rgb[:, i0:i1]).resize((max(1, int((i1 - i0) * hop_t * args.pps)), 140))
        can = Image.new("RGB", (width, 220), (0, 0, 0))
        can.paste(strip, (0, 24))
        d = ImageDraw.Draw(can)
        ta = a + args.t0
        for s in range(int(args.row) + 1):
            x = s * args.pps
            d.line([x, 16, x, 24], fill=(255, 255, 255))
            d.text((x + 2, 1), str(int(ta + s)), fill=(255, 255, 255), font=f)
        for pa, pb in merged:
            if pb > ta and pa < ta + args.row:
                d.rectangle([(pa - ta) * args.pps, 168, (pb - ta) * args.pps, 176], fill=(80, 220, 120))
        for b in beats:
            if ta <= b < ta + args.row:
                x = (b - ta) * args.pps
                d.line([x, 164, x, 168], fill=(130, 130, 255))
        for ln in lyrics:
            if ln["end"] > ta and ln["t"] < ta + args.row:
                xa, xb = (ln["t"] - ta) * args.pps, (ln["end"] - ta) * args.pps
                d.line([xa, 24, xa, 182], fill=(90, 230, 255))
                d.rectangle([xa, 180, xb, 184], fill=(90, 230, 255))
                d.text((max(xa, 0) + 2, 188), ln["text"], fill=(255, 255, 255), font=f)
        rows.append(np.asarray(can))
    Image.fromarray(np.vstack(rows)).save(args.png)
    print(f"{len(merged)} vocal phrases -> {out_json}; picture -> {args.png}")


if __name__ == "__main__":
    main()
