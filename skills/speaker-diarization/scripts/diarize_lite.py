#!/usr/bin/env python3
"""Zero-download speaker clustering baseline: one label per sentence-sized unit of the ASR output.

ASR segments are cut into units at sentence-ending punctuation and at word gaps (--split-gap);
each unit gets a voice fingerprint (MFCC mean/std + pitch statistics) and the units are clustered. It needs only librosa + scipy, runs on CPU in seconds, and
works when voices are clearly different (e.g. 2-5 people, little cross-talk).
It cannot split a segment that contains two speakers and it is far weaker than
pyannote / 3D-Speaker embeddings: use it to bootstrap, then switch backends
(see references/backends.md) when DER matters.

usage:
  python diarize_lite.py audio.wav --asr asr.jsonl --speakers 3 --out diar.rttm
  python diarize_lite.py audio.wav --asr asr.jsonl --out diar.rttm            # guess the count
"""
import argparse
import json
import sys

import numpy as np


def features(y, sr):
    """Long-term spectral envelope of the voiced part: 30 MFCC (from 64 log-mel bands) mean + std.
    On the synthetic demo a grid over MFCC sizes, pitch, deltas, Ward / k-means stayed at 77-87 %
    cluster purity: that is the ceiling of hand-made features, hence the advice to use embeddings."""
    import librosa
    if len(y) < sr * 0.3:
        y = np.pad(y, (0, int(sr * 0.3) - len(y)))
    S = np.abs(librosa.stft(y, n_fft=512, hop_length=160)) ** 2
    M = np.log(librosa.feature.melspectrogram(S=S, sr=sr, n_mels=64, fmin=50, fmax=7600) + 1e-8)
    energy = S.sum(0)
    voiced = energy > np.percentile(energy, 30)
    C = librosa.feature.mfcc(S=M, n_mfcc=30)[1:]
    C = C[:, voiced] if voiced.sum() > 5 else C
    return np.concatenate([C.mean(1), C.std(1)])


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio"); ap.add_argument("--asr", required=True, help="transcribe.py JSONL")
    ap.add_argument("--speakers", type=int, default=0, help="number of speakers if known (much better)")
    ap.add_argument("--max-speakers", type=int, default=8)
    ap.add_argument("--min-seg", type=float, default=1.0, help="units shorter than this inherit a neighbour")
    ap.add_argument("--split-gap", type=float, default=0.35, help="word gap (s) that splits a segment into units")
    ap.add_argument("--out", required=True, help="RTTM output")
    args = ap.parse_args()

    from scipy.cluster.hierarchy import fcluster, linkage
    import subprocess
    sr = 16000
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", args.audio, "-vn", "-ac", "1", "-ar", str(sr),
                          "-f", "f32le", "-"], capture_output=True)
    if raw.returncode != 0:
        sys.exit(raw.stderr.decode("utf-8", "replace"))
    y = np.frombuffer(raw.stdout, np.float32).copy()
    # Units = ASR segments split at sentence ends and word gaps. Whisper/VAD happily glue two
    # speakers into one segment when the pause is short; clustering whole segments would then
    # give the second speaker's sentence to the first.
    segs = []
    with open(args.asr, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            words = r.get("words") or []
            if not words:
                segs.append((float(r["start"]), float(r["end"])))
                continue
            a, b = words[0][0], words[0][1]
            for prev, w in zip(words, words[1:]):
                if w[0] - prev[1] >= args.split_gap or prev[2].strip()[-1:] in "。？！?!；;":
                    segs.append((a, b))
                    a = w[0]
                b = w[1]
            segs.append((a, b))
    if not segs:
        sys.exit("no segments in --asr")

    long_ids = [i for i, (a, b) in enumerate(segs) if b - a >= args.min_seg]
    if len(long_ids) < 2:
        labels_long = np.ones(len(long_ids), int)
    else:
        X = np.stack([features(y[int(segs[i][0] * sr):int(segs[i][1] * sr)], sr) for i in long_ids])
        X = (X - X.mean(0)) / (X.std(0) + 1e-6)
        Z = linkage(X, method="ward")
        if args.speakers:
            labels_long = fcluster(Z, t=args.speakers, criterion="maxclust")
        else:
            # cut at the largest jump in merge distance among the last merges
            d = Z[:, 2]
            k_max = min(args.max_speakers, len(d))
            gaps = [(d[-k + 1] - d[-k], k) for k in range(2, k_max + 1)]
            k = max(gaps)[1] if gaps else 1
            labels_long = fcluster(Z, t=k, criterion="maxclust")
            print(f"guessed {k} speakers (pass --speakers to fix)", file=sys.stderr)

    labels = [None] * len(segs)
    for i, lab in zip(long_ids, labels_long):
        labels[i] = int(lab)
    for i in range(len(segs)):  # short segments: borrow the nearest labelled neighbour
        if labels[i] is None:
            cands = [j for j in range(len(segs)) if labels[j] is not None]
            labels[i] = labels[min(cands, key=lambda j: abs(segs[j][0] - segs[i][0]))] if cands else 1
    # renumber by first appearance: SPK_0 is whoever talks first
    order = {}
    for lab in labels:
        order.setdefault(lab, len(order))
    with open(args.out, "w", encoding="utf-8") as fh:
        for (a, b), lab in zip(segs, labels):
            fh.write(f"SPEAKER audio 1 {a:.2f} {b - a:.2f} <NA> <NA> SPK_{order[lab]} <NA> <NA>\n")
    print(f"wrote {args.out}: {len(segs)} segments, {len(order)} speakers")


if __name__ == "__main__":
    main()
