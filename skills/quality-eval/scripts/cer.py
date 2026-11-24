#!/usr/bin/env python3
"""Character error rate for Chinese (and mixed) ASR, with the normalisation that makes it fair.

CER = (substitutions + deletions + insertions) / reference characters, after:
  * NFKC (full-width -> half-width), lower-case, punctuation and whitespace removed
  * optional traditional -> simplified (--t2s, needs opencc)
  * optional Chinese numerals -> digits (--num): 十二月五号 == 12月5号, P九十九 == P99
Without --num, "十二月" vs "12月" counts as 3 errors: ITN mismatches can dominate CER.

Also reports keyword recall (--keywords: names, terms, numbers) because a 5% CER that gets every
name wrong is worse for any summary than a 10% CER that gets them right.

usage:
  python cer.py --ref ref.txt --hyp hyp.txt [--num] [--t2s] [--keywords kw.txt] [--show 15]
  python cer.py --ref-jsonl truth.jsonl --hyp-jsonl asr.jsonl --num      # concatenates "text" fields
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter

import numpy as np

CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CN_UNIT = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}


def cn_to_int(s):
    if all(c in CN_DIGIT for c in s):  # 一二三 read digit by digit (phone numbers, years)
        return "".join(str(CN_DIGIT[c]) for c in s)
    total, section, num = 0, 0, 0
    for c in s:
        if c in CN_DIGIT:
            num = CN_DIGIT[c]
        else:
            u = CN_UNIT[c]
            if u >= 10000:
                section = (section + num) * u
                total += section
                section = 0
            else:
                section += (num or 1) * u
            num = 0
    return str(total + section + num)


def normalise(s, t2s=None, num=False):
    s = unicodedata.normalize("NFKC", s).lower()
    if t2s:
        s = t2s(s)
    if num:
        s = re.sub(r"[零〇一二两三四五六七八九十百千万亿]+", lambda m: cn_to_int(m.group(0))
                   if not (len(m.group(0)) == 1 and m.group(0) in "万亿千百") else m.group(0), s)
    return "".join(c for c in s if unicodedata.category(c)[0] in "LN")


def align(r, h):
    """Levenshtein with backtrace; rows computed with a vectorised cumulative-min trick."""
    n, m = len(r), len(h)
    big = n * m > 3e7
    D = None if big else np.zeros((n + 1, m + 1), np.int32)
    prev = np.arange(m + 1, dtype=np.int32)
    if D is not None:
        D[0] = prev
    hv = np.array([ord(c) for c in h], np.int64) if m else np.zeros(0, np.int64)
    ar = np.arange(m + 1, dtype=np.int32)
    for i in range(1, n + 1):
        cost = (hv != ord(r[i - 1])).astype(np.int32)
        tmp = np.empty(m + 1, np.int32)
        tmp[0] = i
        tmp[1:] = np.minimum(prev[1:] + 1, prev[:-1] + cost)
        cur = np.minimum.accumulate(tmp - ar) + ar  # resolves the left-neighbour (insertion) dependency
        if D is not None:
            D[i] = cur
        prev = cur
    dist = int(prev[m])
    if D is None:
        return dist, None
    ops, i, j = [], n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and D[i, j] == D[i - 1, j - 1] + (r[i - 1] != h[j - 1]):
            ops.append(("=" if r[i - 1] == h[j - 1] else "S", r[i - 1], h[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and D[i, j] == D[i - 1, j] + 1:
            ops.append(("D", r[i - 1], ""))
            i -= 1
        else:
            ops.append(("I", "", h[j - 1]))
            j -= 1
    return dist, ops[::-1]


def read_text(path, jsonl):
    if not jsonl:
        return open(path, encoding="utf-8").read()
    with open(path, encoding="utf-8") as fh:
        return "".join(json.loads(l).get("text", "") for l in fh if l.strip())


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref"); ap.add_argument("--hyp")
    ap.add_argument("--ref-jsonl"); ap.add_argument("--hyp-jsonl")
    ap.add_argument("--t2s", action="store_true"); ap.add_argument("--num", action="store_true")
    ap.add_argument("--keywords", help="file, one keyword per line")
    ap.add_argument("--show", type=int, default=12, help="how many error snippets to print")
    ap.add_argument("--json", help="write metrics here")
    args = ap.parse_args()

    conv = None
    if args.t2s:
        import opencc
        try:
            conv = opencc.OpenCC("t2s").convert
        except Exception:
            conv = opencc.OpenCC("t2s.json").convert
    ref_raw = read_text(args.ref_jsonl or args.ref, bool(args.ref_jsonl))
    hyp_raw = read_text(args.hyp_jsonl or args.hyp, bool(args.hyp_jsonl))
    r, h = normalise(ref_raw, conv, args.num), normalise(hyp_raw, conv, args.num)
    dist, ops = align(r, h)
    res = {"ref_chars": len(r), "hyp_chars": len(h), "errors": dist, "cer": round(dist / max(1, len(r)), 4)}
    if ops:
        c = Counter(o[0] for o in ops)
        res.update(sub=c["S"], dele=c["D"], ins=c["I"])
    print(f"CER {res['cer']:.2%}  ({dist} errors / {len(r)} ref chars"
          + (f"; S={res['sub']} D={res['dele']} I={res['ins']})" if ops else ")"))

    if ops and args.show:
        snippets, k = [], 0
        while k < len(ops):
            if ops[k][0] == "=":
                k += 1
                continue
            j = k
            while j < len(ops) and ops[j][0] != "=":
                j += 1
            ctx_l = "".join(o[1] for o in ops[max(0, k - 4):k])
            ctx_r = "".join(o[1] for o in ops[j:j + 4])
            rr = "".join(o[1] for o in ops[k:j]); hh = "".join(o[2] for o in ops[k:j])
            snippets.append(f"  …{ctx_l}[{rr or '∅'} → {hh or '∅'}]{ctx_r}…")
            k = j
        res["error_spans"] = len(snippets)
        print(f"{len(snippets)} error spans; first {min(args.show, len(snippets))}:")
        print("\n".join(snippets[:args.show]))

    if args.keywords:
        kws = [l.strip() for l in open(args.keywords, encoding="utf-8") if l.strip()]
        hit = tot = 0
        rows = []
        for kw in kws:
            k = normalise(kw, conv, args.num)
            nr, nh = r.count(k), h.count(k)
            hit += min(nr, nh); tot += nr
            rows.append((kw, nr, nh))
        res["keyword_recall"] = round(hit / max(1, tot), 4)
        print(f"keyword recall {res['keyword_recall']:.2%} ({hit}/{tot})")
        for kw, nr, nh in rows:
            if nh < nr:
                print(f"  missed {kw}: ref {nr}, hyp {nh}")
    if args.json:
        json.dump(res, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
