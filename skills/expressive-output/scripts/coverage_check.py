#!/usr/bin/env python3
"""Check a finished write-up against its source before anyone else reads it.

Three checks, use any combination:
  --facts facts.json   every extracted item must survive: each item's "must" strings must appear
                       in the output (exit code 1 if any is missing). Build facts.json in the
                       "extract first, write second" step.
  --source FILE        hard-token audit: numbers, dates, money, percentages and times found in the
                       source are listed if they never appear in the output (informational: not every
                       number belongs in a summary, but every dropped one should be a choice).
  --lint               filler phrases that carry no information (深入讨论, 达成共识, 值得注意的是 ...).

usage:
  python coverage_check.py --output minutes.md --facts facts.json --lint
  python coverage_check.py --output minutes.md --source timeline.md

facts.json: [{"id": "D1", "kind": "decision", "text": "上线改到12月15日", "must": ["12月15"]}, ...]
"""
import argparse
import json
import re
import sys
import unicodedata

FILLER_ZH = ["深入讨论", "深入探讨", "充分讨论", "广泛讨论", "热烈讨论", "达成共识", "达成一致意见", "各抒己见",
             "值得注意的是", "需要指出的是", "总的来说", "总而言之", "综上所述", "不难看出", "至关重要", "具有重要意义",
             "进行了讨论", "进行了交流", "进行了沟通", "就相关问题", "相关事宜", "一系列", "赋能", "助力",
             "抓手", "闭环", "打通", "全方位", "多维度", "高度重视", "积极推进", "有序推进", "稳步推进"]
FILLER_EN = ["it is worth noting", "in conclusion", "overall,", "delve", "robust discussion", "fruitful discussion",
             "aligned on", "synergy", "leverage", "in today's", "it's important to note", "a testament to"]

HARD = re.compile(
    r"(?:\d{4}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}[日号]?)?)"          # 2026-11-24, 2026年11月
    r"|(?:\d{1,2}月\d{1,2}[日号]?)"                                # 12月15日
    r"|(?:(?:下|本|这|上)?(?:周|星期|礼拜)[一二三四五六日天])"       # 下周一
    r"|(?:\d{1,2}[:：]\d{2})"                                       # 14:30
    r"|(?:[A-Za-z]{1,4}\d{1,4})"                                    # P99, Q3, v2
    r"|(?:\d+(?:\.\d+)?\s*(?:%|％|万元|万|亿|千|元|块|ms|毫秒|秒|分钟|小时|天|周|个月|月|年|台|人|个|次|GB|MB|TB|k|K|w|倍))"
    r"|(?:\d+(?:\.\d+)?)")


def norm(s):
    """Canonical form so equivalent spellings match: 12月1号 == 12月1日, 4万8 == 4.8万,
    300毫秒 == 300ms, 星期一 == 周一, full-width == half-width."""
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"(\d{1,2}月\d{1,2})号", r"\1日", s)
    s = re.sub(r"(\d+)万(\d)(?![\d.万])", r"\1.\2万", s)
    s = s.replace("毫秒", "ms").replace("星期", "周").replace("礼拜", "周").replace("万元", "万")
    s = s.replace("这周", "本周")
    return s


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", required=True, help="the write-up to check (md / txt)")
    ap.add_argument("--facts"); ap.add_argument("--source"); ap.add_argument("--lint", action="store_true")
    args = ap.parse_args()

    text = open(args.output, encoding="utf-8").read()
    out_n = norm(text)
    failed = False

    if args.facts:
        facts = json.load(open(args.facts, encoding="utf-8"))
        missing = []
        for f in facts:
            must = f.get("must") or [f.get("text", "")]
            lost = [m for m in must if norm(m) not in out_n]
            if lost:
                missing.append((f, lost))
        kept = len(facts) - len(missing)
        print(f"facts kept: {kept}/{len(facts)}")
        for f, lost in missing:
            print(f"  MISSING {f.get('id', '?')} [{f.get('kind', '')}] {f.get('text', '')}  -> not found: {lost}")
        failed |= bool(missing)

    if args.source:
        src = open(args.source, encoding="utf-8").read()
        if "\n## " in src:  # fuse.py timeline: skip the header block (duration, talk time, legend)
            src = src[src.index("\n## "):]
        src = re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?(?:[–-]\d{1,2}:\d{2}(?::\d{2})?)?\]", " ", src)  # timestamps
        src = re.sub(r"[\w./\\-]+\.(?:png|jpe?g|webp|json|jsonl|csv|wav|mp4|srt)", " ", src)    # file names
        tokens = []
        for m in HARD.finditer(src):
            t = m.group(0).strip()
            if len(norm(t)) >= 2 or not t.isdigit():
                tokens.append(t)
        seen, uniq = set(), []
        for t in tokens:  # dedupe on the canonical form, keep the first spelling
            if norm(t) not in seen:
                seen.add(norm(t))
                uniq.append(t)
        absent = [t for t in uniq if norm(t) not in out_n]
        print(f"hard tokens in source: {len(uniq)}, absent from output: {len(absent)}")
        if absent:
            print("  " + "  ".join(absent[:80]) + ("  ..." if len(absent) > 80 else ""))
            print("  (each absent number or date should be a deliberate omission)")

    if args.lint:
        hits = [(p, text.count(p)) for p in FILLER_ZH if p in text]
        low = text.lower()
        hits += [(p, low.count(p)) for p in FILLER_EN if p in low]
        if hits:
            print("filler phrases: " + ", ".join(f"{p}×{n}" for p, n in hits))
            print("  replace each with the concrete thing that happened (who decided what, by when)")
        else:
            print("filler phrases: none")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
