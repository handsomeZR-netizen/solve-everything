#!/usr/bin/env python3
"""Give every ASR word a speaker, then regroup words into speaker turns.

Inputs
  --asr   JSONL from transcribe.py (segments with "words": [[start, end, word, prob], ...])
  --diar  diarization result: RTTM, or JSON/JSONL rows {"start", "end", "speaker"}
  --names optional JSON {"SPK_0": "主持人", ...} (only names a human confirmed)

Output JSONL turns:
  {"start", "end", "speaker", "text", "conf", "n_words", "overlap": bool}
and a short report: talk time per speaker, words with no speaker, very short turns.

Rule: a word goes to the speaker whose segment overlaps it the most; with no overlap it
goes to the nearest segment within --snap seconds, otherwise "UNK". A new turn starts
when the speaker changes or the gap exceeds --gap seconds.
"""
import argparse
import bisect
import json
import sys
from collections import defaultdict


def read_diar(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if path.lower().endswith(".rttm") or text.lstrip().startswith("SPEAKER"):
        for line in text.splitlines():
            p = line.split()
            if len(p) >= 8 and p[0] == "SPEAKER":
                s, d = float(p[3]), float(p[4])
                rows.append({"start": s, "end": s + d, "speaker": p[7]})
    else:
        try:
            data = json.loads(text)
            data = data if isinstance(data, list) else data.get("segments", [])
        except json.JSONDecodeError:
            data = [json.loads(l) for l in text.splitlines() if l.strip()]
        for r in data:
            rows.append({"start": float(r["start"]), "end": float(r["end"]), "speaker": str(r["speaker"])})
    rows.sort(key=lambda r: r["start"])
    return rows


def read_words(path):
    words = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            seg = json.loads(line)
            ws = seg.get("words") or []
            if not ws:  # segment without word timestamps: treat it as one word
                ws = [[seg["start"], seg["end"], seg["text"], 1.0]]
            for k, w in enumerate(ws):
                words.append({"start": float(w[0]), "end": float(w[1]), "word": w[2],
                              "prob": float(w[3]) if len(w) > 3 else 1.0, "first": k == 0,
                              "next_start": float(ws[k + 1][0]) if k + 1 < len(ws) else None})
    words.sort(key=lambda w: w["start"])
    return words


def expected_len(word):
    cjk = sum(1 for c in word if "㐀" <= c <= "鿿")
    other = sum(1 for c in word if c.isalnum()) - cjk
    return max(0.2, 0.3 * cjk + 0.08 * other)


def tighten(words):
    """Whisper often stretches the first word after a pause back into the silence
    (a 1-char word lasting 1.3 s, sometimes ending well before the next word). Left alone,
    that word lands on the previous speaker. For an over-long first word of a segment we trust
    the next word's start instead (its timing is reliable) and place the word right before it;
    other over-long words keep only their plausible tail."""
    fixed = 0
    for w in words:
        exp = expected_len(w["word"])
        if w["end"] - w["start"] <= 2.5 * exp:
            continue
        if w["first"] and w["next_start"] is not None and w["next_start"] - w["end"] < 1.5:
            w["end"] = max(w["end"], w["next_start"])
            w["start"] = w["end"] - exp
        else:
            w["start"] = w["end"] - exp
        fixed += 1
    return fixed


def assign(words, diar, snap):
    starts = [d["start"] for d in diar]
    for w in words:
        best, best_ov, speakers_here = None, 0.0, set()
        i = bisect.bisect_right(starts, w["end"])
        for d in diar[max(0, i - 50):i]:  # segments starting before the word ends
            ov = min(w["end"], d["end"]) - max(w["start"], d["start"])
            if ov > 0:
                speakers_here.add(d["speaker"])
                if ov > best_ov:
                    best, best_ov = d["speaker"], ov
        if best is None and diar:
            mid = (w["start"] + w["end"]) / 2
            near = min(diar, key=lambda d: 0 if d["start"] <= mid <= d["end"] else min(abs(mid - d["start"]), abs(mid - d["end"])))
            dist = min(abs(mid - near["start"]), abs(mid - near["end"]))
            best = near["speaker"] if dist <= snap else "UNK"
        w["speaker"] = best or "UNK"
        w["overlap"] = len(speakers_here) > 1
    return words


def join_text(parts):
    out = ""
    for p in parts:
        if out and out[-1].isascii() and out[-1].isalnum() and p[:1].isascii() and p[:1].isalnum():
            out += " "
        out += p
    return out.strip()


def group(words, gap):
    turns, cur = [], None
    for w in words:
        if cur and (w["speaker"] != cur["speaker"] or w["start"] - cur["end"] > gap):
            turns.append(cur)
            cur = None
        if cur is None:
            cur = {"start": w["start"], "end": w["end"], "speaker": w["speaker"], "parts": [], "words": [],
                   "overlap": False}
        cur["end"] = max(cur["end"], w["end"])
        cur["parts"].append(w["word"].strip() if not w["word"].startswith(" ") else w["word"])
        cur["words"].append([w["start"], w["end"], w["word"], w["prob"]])
        cur["overlap"] |= w["overlap"]
    if cur:
        turns.append(cur)
    out = []
    for t in turns:
        probs = [w[3] for w in t["words"]]
        out.append({"start": round(t["start"], 2), "end": round(t["end"], 2), "speaker": t["speaker"],
                    "text": join_text(t["parts"]), "conf": round(sum(probs) / len(probs), 3),
                    "n_words": len(probs), "overlap": t["overlap"], "words": t["words"]})
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asr", required=True); ap.add_argument("--diar", required=True)
    ap.add_argument("--names", help='JSON {"SPK_0": "主持人"}')
    ap.add_argument("--snap", type=float, default=0.5, help="max distance to borrow a speaker for unmatched words")
    ap.add_argument("--gap", type=float, default=1.2, help="silence that splits a turn of the same speaker")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    diar = read_diar(args.diar)
    words = read_words(args.asr)
    stretched = tighten(words)
    words = assign(words, diar, args.snap)
    turns = group(words, args.gap)
    names = {}
    if args.names:
        with open(args.names, encoding="utf-8") as fh:
            names = json.load(fh)
    for t in turns:
        t["speaker"] = names.get(t["speaker"], t["speaker"])
    with open(args.out, "w", encoding="utf-8") as fh:
        for t in turns:
            fh.write(json.dumps(t, ensure_ascii=False) + "\n")

    talk = defaultdict(float)
    for t in turns:
        talk[t["speaker"]] += t["end"] - t["start"]
    unk = sum(1 for w in words if w["speaker"] == "UNK")
    short = sum(1 for t in turns if t["end"] - t["start"] < 1.0)
    ovl = sum(1 for t in turns if t["overlap"])
    print(f"{len(turns)} turns from {len(words)} words; talk time:")
    for spk, sec in sorted(talk.items(), key=lambda kv: -kv[1]):
        print(f"  {spk:>10}  {sec:7.1f}s")
    print(f"unassigned words: {unk}   turns < 1 s: {short}   turns touching overlapped speech: {ovl}   "
          f"over-long words tightened: {stretched}")
    if short or ovl:
        print("check short and overlapped turns by ear: that is where diarization is usually wrong")


if __name__ == "__main__":
    main()
