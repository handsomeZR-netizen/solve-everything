#!/usr/bin/env python3
"""Tempo, beats, a downbeat guess, onsets and loudness sections for a song or any rhythmic audio.

usage:
  python beats.py song.wav --out beats.json
  python beats.py song.wav --out beats.json --start 12.5 --dur 60

beats.json:
  {"tempo": 92.3, "beats": [...s], "downbeats": [...s], "onsets": [...s],
   "sections": [{"start", "end", "level": "quiet|mid|loud"}], "duration": 241.2}
The downbeat is a guess (the beat phase with the strongest onsets every 4 beats):
check it by ear or on a plot before cutting video to it.
"""
import argparse
import json
import sys

import numpy as np


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio"); ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=float, default=0.0); ap.add_argument("--dur", type=float, default=None)
    ap.add_argument("--meter", type=int, default=4, help="beats per bar for the downbeat guess")
    args = ap.parse_args()

    import librosa
    # librosa.load resamples to 22050 Hz and mixes to mono by default; both are fine for rhythm
    y, sr = librosa.load(args.audio, sr=22050, mono=True, offset=args.start, duration=args.dur)
    hop = 512
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=env, sr=sr, hop_length=hop)
    tempo = float(np.atleast_1d(tempo)[0])
    beats = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop)
    onsets = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=hop, units="time")

    downbeats = []
    if len(beat_frames) >= args.meter * 2:
        strength = [env[beat_frames[k::args.meter]].mean() for k in range(args.meter)]
        phase = int(np.argmax(strength))
        downbeats = beats[phase::args.meter].tolist()

    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    t = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop)
    win = max(1, int(2.0 * sr / hop))  # 2 s smoothing
    smooth = np.convolve(rms, np.ones(win) / win, mode="same")
    q1, q2 = np.percentile(smooth, [33, 66])
    level = np.where(smooth < q1, 0, np.where(smooth < q2, 1, 2))
    sections, names = [], ["quiet", "mid", "loud"]
    start = 0
    for i in range(1, len(level) + 1):
        if i == len(level) or level[i] != level[start]:
            if t[min(i, len(t) - 1)] - t[start] >= 4.0 or not sections:
                sections.append({"start": round(float(t[start]) + args.start, 2),
                                 "end": round(float(t[min(i, len(t) - 1)]) + args.start, 2),
                                 "level": names[int(level[start])]})
            elif sections:
                sections[-1]["end"] = round(float(t[min(i, len(t) - 1)]) + args.start, 2)
            start = i

    off = args.start
    res = {"tempo": round(tempo, 2), "beats": [round(b + off, 3) for b in beats.tolist()],
           "downbeats": [round(b + off, 3) for b in downbeats], "onsets": [round(o + off, 3) for o in onsets.tolist()],
           "sections": sections, "duration": round(len(y) / sr, 2)}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False)
    print(f"tempo {res['tempo']} BPM, {len(res['beats'])} beats, {len(res['onsets'])} onsets, "
          f"{len(sections)} loudness sections -> {args.out}")


if __name__ == "__main__":
    main()
