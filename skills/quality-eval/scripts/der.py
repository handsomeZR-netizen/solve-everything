#!/usr/bin/env python3
"""Diarization error rate (DER) between two RTTM files, frame-based, with optimal speaker mapping.

DER = (missed speech + false alarm + speaker confusion) / total reference speech.
Hypothesis labels are mapped to reference labels with the Hungarian algorithm (scipy).
A collar (default 0.25 s) around every reference boundary is not scored, as is standard.

usage:
  python der.py --ref truth.rttm --hyp diar.rttm [--collar 0.25] [--step 0.01]
"""
import argparse
import sys

import numpy as np


def read_rttm(path):
    segs = []
    for line in open(path, encoding="utf-8"):
        p = line.split()
        if len(p) >= 8 and p[0] == "SPEAKER":
            s, d = float(p[3]), float(p[4])
            segs.append((s, s + d, p[7]))
    return segs


def to_matrix(segs, speakers, n, step):
    M = np.zeros((n, len(speakers)), bool)
    idx = {s: i for i, s in enumerate(speakers)}
    for a, b, s in segs:
        M[int(round(a / step)):int(round(b / step)), idx[s]] = True
    return M


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", required=True); ap.add_argument("--hyp", required=True)
    ap.add_argument("--collar", type=float, default=0.25); ap.add_argument("--step", type=float, default=0.01)
    args = ap.parse_args()
    from scipy.optimize import linear_sum_assignment

    ref, hyp = read_rttm(args.ref), read_rttm(args.hyp)
    end = max([b for _, b, _ in ref + hyp] + [0])
    n = int(np.ceil(end / args.step)) + 1
    rs = sorted({s for *_, s in ref}); hs = sorted({s for *_, s in hyp})
    R, H = to_matrix(ref, rs, n, args.step), to_matrix(hyp, hs, n, args.step)
    scored = np.ones(n, bool)
    c = int(round(args.collar / args.step))
    for a, b, _ in ref:
        for t in (a, b):
            k = int(round(t / args.step))
            scored[max(0, k - c):k + c] = False
    R, H = R[scored], H[scored]
    overlap = R.T.astype(np.int64) @ H.astype(np.int64)  # ref x hyp co-activity in frames
    ri, hi = linear_sum_assignment(-overlap)
    mapping = {hs[j]: rs[i] for i, j in zip(ri, hi)}
    n_ref, n_hyp = R.sum(1), H.sum(1)
    correct = np.zeros(len(R), np.int64)
    for i, j in zip(ri, hi):
        correct += (R[:, i] & H[:, j])
    miss = np.maximum(0, n_ref - n_hyp).sum()
    fa = np.maximum(0, n_hyp - n_ref).sum()
    conf = (np.minimum(n_ref, n_hyp) - correct).sum()
    total = n_ref.sum()
    der = (miss + fa + conf) / max(1, total)
    s = args.step
    print(f"DER {der:.2%}  (miss {miss * s:.1f}s, false alarm {fa * s:.1f}s, confusion {conf * s:.1f}s, "
          f"scored speech {total * s:.1f}s, collar {args.collar}s)")
    print("mapping hyp -> ref: " + ", ".join(f"{k}->{v}" for k, v in mapping.items()))
    unmapped = [h for h in hs if h not in mapping]
    if unmapped:
        print("hyp speakers with no ref partner (counted as confusion): " + ", ".join(unmapped))


if __name__ == "__main__":
    main()
