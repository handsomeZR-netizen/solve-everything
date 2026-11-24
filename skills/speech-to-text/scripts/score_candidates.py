#!/usr/bin/env python3
"""Decide between candidate wordings of a short span by forced alignment.

The LLM is good at proposing what a garbled name or term *might* be; the acoustic
model is good at judging which proposal matches the sound. This script aligns each
candidate sentence to the same audio with Whisper and reports per-word probability,
so "浩然 / 浩岚 / 昊兰" is decided by the audio, not by guessing.

usage:
  python score_candidates.py audio.wav --start 36 --end 40.2 \
      --cand "哎，浩然，你最近在忙什么" --cand "哎，浩岚，你最近在忙什么"
  python score_candidates.py audio.wav --cases cases.json [--json out.json]
      cases.json = [{"start": 36, "end": 40.2, "candidates": ["...", "..."]}, ...]

Spans must be <= 30 s (one Whisper window). Uses faster-whisper internals
(find_alignment, pad_or_trim), so pin the faster-whisper version you tested with.
"""
import argparse
import json
import math
import os
import sys


def diff_window(cands):
    """Shared prefix/suffix length, so we can show only the part that differs."""
    pre = os.path.commonprefix(cands)
    suf = os.path.commonprefix([c[::-1] for c in cands])
    return len(pre), len(suf)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio")
    ap.add_argument("--start", type=float); ap.add_argument("--end", type=float)
    ap.add_argument("--cand", action="append", default=[], help="candidate sentence (repeat)")
    ap.add_argument("--cases", help="JSON list of {start, end, candidates}")
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--device", default="cpu"); ap.add_argument("--compute", default=None)
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--json", help="write full results here")
    args = ap.parse_args()

    if args.cases:
        with open(args.cases, encoding="utf-8") as fh:
            cases = json.load(fh)
    elif args.cand and args.start is not None and args.end is not None:
        cases = [{"start": args.start, "end": args.end, "candidates": args.cand}]
    else:
        ap.error("give --start/--end/--cand ... or --cases")

    import subprocess
    import numpy as np
    from faster_whisper import WhisperModel
    from faster_whisper.audio import pad_or_trim
    from faster_whisper.tokenizer import Tokenizer

    compute = args.compute or ("float16" if args.device == "cuda" else "int8")
    model = WhisperModel(args.model, device=args.device, compute_type=compute, local_files_only=args.local_only)
    tok = Tokenizer(model.hf_tokenizer, model.model.is_multilingual, task="transcribe", language=args.lang)
    sr = 16000
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", args.audio, "-vn", "-ac", "1", "-ar", str(sr),
                          "-f", "f32le", "-"], capture_output=True)
    if raw.returncode != 0:
        sys.exit(raw.stderr.decode("utf-8", "replace"))
    audio = np.frombuffer(raw.stdout, np.float32).copy()

    results = []
    for case in cases:
        a, b = float(case["start"]), float(case["end"])
        if b - a > 30:
            print(f"skip {a}-{b}: longer than 30 s", file=sys.stderr)
            continue
        feat = model.feature_extractor(audio[int(a * sr):int(b * sr)])
        enc = model.encode(pad_or_trim(feat))
        cands = case["candidates"]
        # one call per candidate: the encoder output has batch size 1 and align() needs matching batches
        aligned = [model.find_alignment(tok, [tok.encode(c)], enc, feat.shape[-1])[0] for c in cands]
        pre, suf = diff_window(cands)
        rows = []
        for cand, words in zip(cands, aligned):
            probs = [max(w["probability"], 1e-6) for w in words] or [1e-6]
            # words overlapping the differing region decide the case; whole-sentence mean dilutes them
            pos, focus = 0, []
            for w in words:
                lo, hi = pos, pos + len(w["word"])
                pos = hi
                if hi > pre and lo < len(cand) - suf:
                    focus.append(max(w["probability"], 1e-6))
            focus = focus or probs
            rows.append({
                "candidate": cand,
                "differs": cand[pre:len(cand) - suf] if len(cand) - suf > pre else cand,
                "focus_logprob": round(sum(math.log(p) for p in focus) / len(focus), 3),
                "mean_logprob": round(sum(math.log(p) for p in probs) / len(probs), 3),
                "min_prob": round(min(probs), 3),
                "words": [[round(a + w["start"], 2), round(a + w["end"], 2), w["word"], round(w["probability"], 3)]
                          for w in words],
            })
        rows.sort(key=lambda r: (r["focus_logprob"], r["mean_logprob"]), reverse=True)
        results.append({"start": a, "end": b, "ranking": rows})
        print(f"\n[{a:.2f}-{b:.2f}]")
        for i, r in enumerate(rows):
            mark = "->" if i == 0 else "  "
            print(f" {mark} {r['focus_logprob']:7.3f}  「{r['differs']}」  {r['candidate']}")
        if len(rows) > 1 and rows[0]["focus_logprob"] - rows[1]["focus_logprob"] < 0.1:
            print("    (margin < 0.1: too close to call, ask a human or get more context)")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
