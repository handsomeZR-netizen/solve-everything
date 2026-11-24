#!/usr/bin/env python3
"""Merge every modality into one timeline: a JSONL for code and a Markdown file for the LLM.

inputs (give at least one):
  --asr     turns.jsonl (merge_speakers.py) or asr.jsonl (transcribe.py)
  --slides  segments.json (slide_changes.py; run ocr.py --segments first to fill "ocr")
  --subs    subs.json (burned_subs.py)
  --events  sv.jsonl (sensevoice_onnx.py): laughter, applause, non-neutral emotion
  --notes   JSONL {"start", "end", "text"}: chat log, agenda, manual notes, anything timed
  --shift-asr / --shift-video   seconds added to that source (fix A/V offsets found by probe.py)

outputs:
  --out timeline.jsonl   rows {"t0", "t1", "src", "spk", "text", "conf", "flags", "ref"}
  --md  timeline.md      one section per slide (or every --section seconds); each utterance as
                         "- [mm:ss] 主持人：..." with low-confidence words marked {词?}

usage:
  python fuse.py --asr turns.jsonl --slides slides/segments.json --events sv.jsonl \
                 --out timeline.jsonl --md timeline.md --title "第3讲 卷积"
"""
import argparse
import difflib
import json
import os
import sys
import unicodedata
from collections import defaultdict

LABELS = {
    "zh": {"slide": "第{n}页", "screen": "屏幕文字", "dyn": "屏幕在变化（滚动或播放），抽样帧：", "sub": "字幕",
           "flash": "屏幕闪现", "xline": "字幕/语音不一致（字幕在前，语音在后）",
           "xcheck": "字幕与语音不一致：{n} 处（逐条标在字幕下方；至少有一边是错的，以原片为准）",
           "note": "备注", "legend": "图例：{词?} = 识别置信度低的词；[!x] = 被标记的片段；（笑声）等 = 声音事件",
           "sources": "来源", "speakers": "说话人", "dur": "时长", "unknown": "未知"},
    "en": {"slide": "Slide {n}", "screen": "On screen", "dyn": "Screen changing (scroll / playback), samples:",
           "flash": "on screen briefly", "xline": "subtitle / speech differ (subtitle first)",
           "xcheck": "subtitle vs speech disagreements: {n} (marked under each subtitle; at least one side is wrong)",
           "sub": "subtitle", "note": "note", "legend": "Legend: {word?} = low-confidence word; [!x] = flagged; "
           "(laughter) etc. = sound events", "sources": "Sources", "speakers": "Speakers", "dur": "Duration",
           "unknown": "unknown"},
}
EVENT_ZH = {"Laughter": "笑声", "Applause": "掌声", "Cry": "哭声", "Cough": "咳嗽", "BGM": "背景音乐",
            "Sneeze": "喷嚏", "Breath": "呼吸声"}


def ts(t):
    t = max(0, int(t))
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def marked_text(row, low):
    """Rebuild text from words, wrapping runs of low-probability words as {...?}."""
    words = row.get("words")
    if not words:
        return row.get("text", "").strip()
    out, run = [], []
    for w in words:
        word, p = w[2], (w[3] if len(w) > 3 else 1.0)
        if p < low and word.strip():
            run.append(word)
            continue
        if run:
            out.append("{" + "".join(run).strip() + "?}")
            run = []
        out.append(word)
    if run:
        out.append("{" + "".join(run).strip() + "?}")
    text = "".join(out).strip()
    return " ".join(text.split()) if any(c.isascii() and c.isalpha() for c in text) else text.replace(" ", "")


def plain(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(c for c in s if unicodedata.category(c)[0] in "LN")


def cross_check(subs, asr_rows):
    """Subtitle text vs what was heard in the same span. Where they differ, at least one is wrong:
    OCR drops or swaps characters, ASR mishears homophones. Neither source is trusted blindly."""
    words = [w for r in asr_rows for w in (r.get("words") or [])]
    n = 0
    for s in subs:
        # take a generous window (ASR word times can be off by a second or more), then keep only the
        # stretch that actually matches the subtitle, so neighbouring sentences do not count as errors
        heard = "".join(w[2] for w in words if s["t0"] - 3.0 <= (w[0] + w[1]) / 2 <= s["t1"] + 3.0)
        a, wide = plain(s["text"]), plain(heard)
        if not a or not wide:
            continue
        blocks = [m for m in difflib.SequenceMatcher(None, a, wide, autojunk=False).get_matching_blocks() if m.size]
        if not blocks:
            continue
        b0 = max(0, blocks[0].b - blocks[0].a)
        b1 = min(len(wide), blocks[-1].b + blocks[-1].size + (len(a) - blocks[-1].a - blocks[-1].size))
        b = wide[b0:b1]
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        if sm.ratio() < 0.5:  # not the same sentence: do not guess
            continue
        d = [(a[i1:i2], b[j1:j2]) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
        if d:
            s["xcheck"] = d
            n += len(d)
    return n


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asr"); ap.add_argument("--slides"); ap.add_argument("--subs")
    ap.add_argument("--events"); ap.add_argument("--notes")
    ap.add_argument("--shift-asr", type=float, default=0.0); ap.add_argument("--shift-video", type=float, default=0.0)
    ap.add_argument("--low", type=float, default=0.45, help="word probability below which a word is marked")
    ap.add_argument("--section", type=float, default=300.0, help="section length when there are no slides")
    ap.add_argument("--lang", choices=["zh", "en"], default="zh")
    ap.add_argument("--title", default="Timeline")
    ap.add_argument("--out", required=True); ap.add_argument("--md", required=True)
    args = ap.parse_args()
    L = LABELS[args.lang]

    rows = []
    if args.asr:
        for r in read_jsonl(args.asr):
            sa = args.shift_asr
            words = [[w[0] + sa, w[1] + sa] + list(w[2:]) for w in r.get("words") or []]
            conf = r.get("conf")
            if conf is None and words:
                conf = round(sum(w[3] for w in words) / len(words), 3)
            rows.append({"t0": round(r["start"] + sa, 2), "t1": round(r["end"] + sa, 2), "src": "asr",
                         "spk": r.get("speaker"), "text": r.get("text", "").strip(), "conf": conf,
                         "flags": r.get("flags", []), "words": words})
    slides = []
    if args.slides:
        with open(args.slides, encoding="utf-8") as fh:
            slides = json.load(fh)
        for s in slides:
            sv = args.shift_video
            if s["kind"] == "flash":  # on screen for about a second: often the one fact nobody says aloud
                rows.append({"t0": round(s["start"] + sv, 2), "t1": round(s["end"] + sv, 2), "src": "flash",
                             "spk": None, "text": s.get("ocr", ""), "conf": None, "flags": [], "ref": s.get("file")})
                continue
            rows.append({"t0": round(s["start"] + sv, 2), "t1": round(s["end"] + sv, 2), "src": "slide",
                         "spk": None, "text": s.get("ocr", ""), "conf": None, "flags": [s["kind"]],
                         "ref": s.get("file"), "group": s.get("group"),
                         "samples": [x["file"] for x in s.get("samples", [])]})
    if args.subs:
        with open(args.subs, encoding="utf-8") as fh:
            for s in json.load(fh):
                if s.get("text"):
                    rows.append({"t0": s["start"] + args.shift_video, "t1": s["end"] + args.shift_video,
                                 "src": "sub", "spk": None, "text": s["text"], "conf": s.get("score"), "flags": []})
    events = []
    if args.events:
        for e in read_jsonl(args.events):
            tags = []
            if e.get("event") and e["event"] not in ("Speech", "Event_UNK"):
                tags.append(EVENT_ZH.get(e["event"], e["event"]) if args.lang == "zh" else e["event"].lower())
            if e.get("emotion") and e["emotion"] not in ("NEUTRAL", "EMO_UNKNOWN"):
                tags.append(e["emotion"].lower())
            if tags:
                events.append({"t0": e["start"] + args.shift_asr, "t1": e["end"] + args.shift_asr, "tags": tags})
                rows.append({"t0": e["start"] + args.shift_asr, "t1": e["end"] + args.shift_asr, "src": "event",
                             "spk": None, "text": ",".join(tags), "conf": None, "flags": []})
    if args.notes:
        for n in read_jsonl(args.notes):
            rows.append({"t0": n["start"], "t1": n.get("end", n["start"]), "src": "note", "spk": None,
                         "text": n["text"], "conf": None, "flags": []})
    if not rows:
        sys.exit("nothing to fuse: give --asr / --slides / --subs / --notes")
    rows.sort(key=lambda r: (r["t0"], r["src"] != "slide"))
    n_x = cross_check([r for r in rows if r["src"] == "sub"], [r for r in rows if r["src"] == "asr"])

    with open(args.out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps({k: v for k, v in r.items() if v not in (None, [], "")}, ensure_ascii=False) + "\n")

    # ---------- Markdown for reading ----------
    speech = [r for r in rows if r["src"] in ("asr", "sub", "note", "flash")]
    end_t = max(r["t1"] for r in rows)
    talk = defaultdict(float)
    for r in rows:
        if r["src"] == "asr":
            talk[r["spk"] or L["unknown"]] += r["t1"] - r["t0"]

    sections = []  # (t0, t1, heading, lines_before)
    statics = [s for s in rows if s["src"] == "slide"]
    if statics:
        groups = []
        for s in statics:
            if "dynamic" in s["flags"]:
                groups.append({"t0": s["t0"], "t1": s["t1"], "dyn": True, "samples": s.get("samples", [])})
            elif groups and not groups[-1].get("dyn") and groups[-1]["group"] == s.get("group"):
                groups[-1]["t1"] = s["t1"]
                groups[-1]["text"] = s["text"] or groups[-1]["text"]
                groups[-1]["ref"] = s.get("ref") or groups[-1]["ref"]
            else:
                groups.append({"t0": s["t0"], "t1": s["t1"], "group": s.get("group"), "text": s["text"],
                               "ref": s.get("ref"), "dyn": False})
        n = 0
        for g in groups:
            if g["dyn"]:
                pre = [f"> {L['dyn']} " + ", ".join(g["samples"][:6])] if g["samples"] else [f"> {L['dyn']}"]
                sections.append((g["t0"], g["t1"], f"[{ts(g['t0'])}–{ts(g['t1'])}] …", pre))
                continue
            n += 1
            lines = [x.strip() for x in (g["text"] or "").splitlines() if x.strip()]
            head = L["slide"].format(n=n) + (f" · {lines[0][:40]}" if lines else "")
            pre = []
            if lines:
                body = " / ".join(lines)
                pre.append(f"> {L['screen']}：{body[:400]}{'…' if len(body) > 400 else ''}")
            if g.get("ref"):
                pre.append(f"> ({g['ref']})")
            sections.append((g["t0"], g["t1"], f"[{ts(g['t0'])}–{ts(g['t1'])}] {head}", pre))
        if sections and sections[0][0] > 0.5:
            sections.insert(0, (0.0, sections[0][0], f"[{ts(0)}–{ts(sections[0][0])}]", []))
    else:
        t = 0.0
        while t < end_t:
            sections.append((t, min(t + args.section, end_t), f"[{ts(t)}–{ts(min(t + args.section, end_t))}]", []))
            t += args.section
    # sections are contiguous: anything between two slides (a flash, a pause) belongs to the earlier one
    sections = [(a, sections[k + 1][0] if k + 1 < len(sections) else max(b, end_t), h, p)
                for k, (a, b, h, p) in enumerate(sections)]

    out = [f"# {args.title}", "",
           f"- {L['dur']}: {ts(end_t)}",
           f"- {L['sources']}: " + ", ".join(f"{k} {sum(1 for r in rows if r['src'] == k)}"
                                             for k in ("asr", "slide", "flash", "sub", "event", "note")
                                             if any(r["src"] == k for r in rows))]
    if any(r.get("spk") for r in rows if r["src"] == "asr"):
        out.append(f"- {L['speakers']}: " + ", ".join(f"{k} {v / 60:.1f} min"
                                                    for k, v in sorted(talk.items(), key=lambda kv: -kv[1])))
    if any(r["src"] == "sub" for r in rows):
        out.append(f"- {L['xcheck'].format(n=n_x)}")
    out += [f"- {L['legend']}", ""]
    used = set()
    for k, (a, b, head, pre) in enumerate(sections):
        last = k == len(sections) - 1
        members = [r for r in speech if id(r) not in used and (a <= (r["t0"] + r["t1"]) / 2 < b or
                                                               (last and (r["t0"] + r["t1"]) / 2 >= a))]
        out.append(f"## {head}")
        out += pre
        if pre:
            out.append("")
        for r in members:
            used.add(id(r))
            if r["src"] == "asr":
                text = marked_text(r, args.low)
                spk = r["spk"] or ""
                tags = []
                for e in events:
                    ov = min(e["t1"], r["t1"]) - max(e["t0"], r["t0"])
                    if ov > 0.3 * min(e["t1"] - e["t0"], r["t1"] - r["t0"]):
                        tags += e["tags"]
                tail = ("（" + "，".join(dict.fromkeys(tags)) + "）") if tags else ""
                flags = "".join(f" [!{f}]" for f in r.get("flags", []))
                out.append(f"- [{ts(r['t0'])}] {spk + '：' if spk else ''}{text}{tail}{flags}")
            elif r["src"] == "sub":
                out.append(f"- [{ts(r['t0'])}] 〔{L['sub']}〕{r['text']}")
                if r.get("xcheck"):
                    pairs = "；".join(f"「{x or '∅'}」/「{y or '∅'}」" for x, y in r["xcheck"])
                    out.append(f"  - ⚠ {L['xline']}：{pairs}")
            elif r["src"] == "flash":
                body = " / ".join(x.strip() for x in (r["text"] or "").splitlines() if x.strip()) or "?"
                out.append(f"- [{ts(r['t0'])}] **〔{L['flash']} {r['t1'] - r['t0']:.1f}s〕{body}**"
                           + (f" ({r['ref']})" if r.get("ref") else ""))
            else:
                out.append(f"- [{ts(r['t0'])}] 〔{L['note']}〕{r['text']}")
        out.append("")
    with open(args.md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out).rstrip() + "\n")
    print(f"{len(rows)} rows -> {args.out}; {len(sections)} sections -> {args.md}")


if __name__ == "__main__":
    main()
