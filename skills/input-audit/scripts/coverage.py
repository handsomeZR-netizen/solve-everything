#!/usr/bin/env python3
"""Coverage audit: prove how much of each input was actually processed, and list what was not.

Each subcommand measures one modality against what really exists in the file, appends the
result to a shared coverage.json, and prints the gaps with timestamps / page numbers:

  audio    sound and speech that has no transcript (missed or dropped), and transcript where
           there is no sound (hallucination candidates)
           python coverage.py audio --media clip.mp4 --asr asr.jsonl --cov coverage.json
  video    which on-screen states (slides, cards, subtitle lines) a sampling strategy would see:
           uniform N frames, fixed fps, and the change-detection result; optional ground truth
           python coverage.py video --segments slides/segments.json [--subs subs/subs.json] \
               [--duration 62] [--uniform 8 16 32] [--fps 0.5 1] [--truth truth_screen.json] --cov coverage.json
  pdf      pages with a usable text layer, scanned pages that were OCR'd or viewed, pages never read
           python coverage.py pdf --pages report/pages.jsonl [--ocr ocr.json] --cov coverage.json
  image    effective resolution a vision model gets, directly vs through tiles
           python coverage.py image --image long.png [--tiles tiles/index.json] --cov coverage.json
  office   speaker notes, hidden slides/sheets, comments, tracked changes found vs the inventory
           python coverage.py office --ledger ledger.json --found extracted/deck.pptx.found.json --cov coverage.json
  summary  one table for everything, with verdicts
           python coverage.py summary --cov coverage.json --md coverage.md [--min 0.98]

Exit code of `summary` is 1 when any measured coverage is below --min.
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np


# ---------------------------------------------------------------- helpers
def load_cov(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {"items": []}


def save_cov(path, cov, item):
    cov["items"] = [i for i in cov["items"] if not (i["input"] == item["input"] and i["kind"] == item["kind"])]
    cov["items"].append(item)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cov, fh, ensure_ascii=False, indent=1)


def union(iv):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def total(iv):
    return sum(b - a for a, b in iv)


def intersect(A, B):
    out, i, j = [], 0, 0
    while i < len(A) and j < len(B):
        a, b = max(A[i][0], B[j][0]), min(A[i][1], B[j][1])
        if a < b:
            out.append([a, b])
        if A[i][1] < B[j][1]:
            i += 1
        else:
            j += 1
    return out


def subtract(A, B):
    out = []
    for a, b in A:
        cur = a
        for c, d in B:
            if d <= cur or c >= b:
                continue
            if c > cur:
                out.append([cur, c])
            cur = max(cur, d)
        if cur < b:
            out.append([cur, b])
    return out


def ts(t):
    t = max(0, int(round(t)))
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def decode(path, track=0, sr=16000):
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-map", f"0:a:{track}", "-ac", "1", "-ar", str(sr),
           "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True)
    if out.returncode != 0:
        sys.exit("ffmpeg could not decode audio:\n" + out.stderr.decode("utf-8", "replace"))
    return np.frombuffer(out.stdout, np.float32).copy()


def energy_activity(y, sr, hop=0.02, min_gap=0.3, min_len=0.25):
    n = int(hop * sr)
    fr = y[: len(y) // n * n].reshape(-1, n)
    db = 20 * np.log10(np.sqrt((fr ** 2).mean(1)) + 1e-9)
    floor = float(np.percentile(db, 10))
    thr = max(floor + 12.0, -50.0)
    act = db > thr
    iv, start = [], None
    for i, a in enumerate(act):
        if a and start is None:
            start = i
        elif not a and start is not None:
            iv.append([start * hop, i * hop])
            start = None
    if start is not None:
        iv.append([start * hop, len(act) * hop])
    merged = []
    for a, b in iv:
        if merged and a - merged[-1][1] < min_gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [x for x in merged if x[1] - x[0] >= min_len], thr


def silero_speech(y, sr):
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except ImportError:
        return None
    ts_ = get_speech_timestamps(y, VadOptions(min_silence_duration_ms=300, speech_pad_ms=100))
    return union([[t["start"] / sr, t["end"] / sr] for t in ts_])


def verdict(c, lo):
    return "OK" if c >= lo else ("CHECK" if c >= lo - 0.08 else "FAIL")


# ---------------------------------------------------------------- audio
def cmd_audio(a):
    sr = 16000
    y = decode(a.media, a.track, sr)
    dur = len(y) / sr
    segs = []
    with open(a.asr, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                segs.append(r)
    # pad each transcript span: VAD keeps ~0.3 s around speech, sentence-level spans do not
    covered = union([[float(r["start"]) - a.pad, float(r["end"]) + a.pad] for r in segs])
    sound, thr = energy_activity(y, sr)
    speech = silero_speech(y, sr)
    res = {"input": a.name or a.media, "kind": "audio", "duration": round(dur, 2), "energy_threshold_db": round(thr, 1)}
    meas = {}
    for label, act in (("speech", speech), ("sound", sound)):
        if act is None:
            continue
        hit = total(intersect(act, covered))
        tot = total(act)
        gaps = [g for g in subtract(act, covered) if g[1] - g[0] >= a.min_gap]
        meas[label] = {"active_s": round(tot, 2), "covered_s": round(hit, 2),
                       "coverage": round(hit / tot, 4) if tot else 1.0,
                       "gaps": [[round(x, 2), round(y_, 2)] for x, y_ in gaps]}
    orphans = []
    for r in segs:
        span = [[float(r["start"]), float(r["end"])]]
        ov = total(intersect(span, sound))
        if ov < 0.2 * max(1e-6, float(r["end"]) - float(r["start"])):
            orphans.append({"start": r["start"], "end": r["end"], "text": r.get("text", "")[:60]})
    res.update(measures=meas, orphan_text=orphans,
               flagged=[{"start": r["start"], "flags": r["flags"], "text": r.get("text", "")[:40]}
                        for r in segs if r.get("flags")])
    main_cov = meas.get("speech", meas.get("sound"))["coverage"]
    res["coverage"] = main_cov
    save_cov(a.cov, load_cov(a.cov), res)
    print(f"[audio] {res['input']}  {dur:.1f}s")
    for label, m in meas.items():
        print(f"  {label:6s} active {m['active_s']:7.1f}s  transcribed {m['covered_s']:7.1f}s  coverage {m['coverage']:.1%}  "
              f"gaps >= {a.min_gap}s: {len(m['gaps'])}")
        for g in m["gaps"][:12]:
            print(f"     no text at {ts(g[0])}–{ts(g[1])} ({g[1] - g[0]:.1f}s)")
    if "speech" in meas:
        print("  (speech = Silero VAD, the detector transcribe.py also uses; sound = raw energy, independent of it:"
              " music and noise count as sound)")
    if orphans:
        print(f"  {len(orphans)} transcript segment(s) over near-silence (hallucination candidates):")
        for o in orphans[:8]:
            print(f"     {ts(o['start'])} {o['text']}")
    if res["flagged"]:
        print(f"  {len(res['flagged'])} flagged segment(s) still in the transcript")


# ---------------------------------------------------------------- video
def cmd_video(a):
    segs = json.load(open(a.segments, encoding="utf-8"))
    states = [s for s in segs if s.get("kind") in ("static", "flash")]
    dyn = [s for s in segs if s.get("kind") == "dynamic"]
    dur = a.duration or max(s["end"] for s in segs)
    subs = json.load(open(a.subs, encoding="utf-8")) if a.subs else []
    truth = json.load(open(a.truth, encoding="utf-8")) if a.truth else None
    events = {"screen states": [(s["start"], s["end"]) for s in states]}
    if subs:
        events["subtitle lines"] = [(s["start"], s["end"]) for s in subs if s.get("text")]
    if truth:
        events = {"truth on-screen items": [(t["start"], t["end"]) for t in truth]}

    strategies = {f"uniform {n} frames": [(k + 0.5) * dur / n for k in range(n)] for n in a.uniform}
    for f in a.fps:
        strategies[f"{f:g} fps"] = list(np.arange(0.0, dur, 1.0 / f) + 0.5 / f)

    res = {"input": a.name or a.segments, "kind": "video", "duration": round(dur, 2), "strategies": {}}
    n_flash = sum(1 for s in states if s["kind"] == "flash")
    print(f"[video] {res['input']}  {dur:.1f}s, {len(states)} screen states ({n_flash} flashes), "
          f"{len(dyn)} dynamic stretches"
          + (f", {len(subs)} subtitle lines" if subs else ""))
    for ev_name, ev in events.items():
        short = min((b - a_ for a_, b in ev), default=0)
        print(f"  {ev_name}: {len(ev)} (shortest {short:.1f}s)")
        for name, times in strategies.items():
            t = np.array(times)
            seen = sum(1 for s, e in ev if ((t >= s) & (t < e)).any())
            res["strategies"][f"{ev_name} | {name}"] = {"seen": seen, "of": len(ev), "frames": len(times)}
            print(f"     {name:18s} {len(times):5d} frames -> sees {seen}/{len(ev)} ({seen / max(1, len(ev)):.0%})")
    if truth:
        det = [(s["start"], s["end"]) for s in states]
        found = 0
        for t in truth:
            span = t["end"] - t["start"]
            if any(min(t["end"], e) - max(t["start"], s) >= 0.5 * span for s, e in det):
                found += 1
        res["detection_recall"] = round(found / max(1, len(truth)), 4)
        print(f"     change detection   {len(states):5d} frames -> finds {found}/{len(truth)} "
              f"({res['detection_recall']:.0%})")
    ocr_missing = [s["i"] for s in states if s.get("complete", True) and "ocr" in s and not s["ocr"].strip()]
    if any("ocr" in s for s in states):
        res["states_without_text"] = ocr_missing
        print(f"  screen states with empty OCR: {ocr_missing or 'none'}")
    res["coverage"] = res.get("detection_recall", 1.0 if states else 0.0)
    save_cov(a.cov, load_cov(a.cov), res)


# ---------------------------------------------------------------- pdf
def cmd_pdf(a):
    pages = [json.loads(l) for l in open(a.pages, encoding="utf-8") if l.strip()]
    ocr_done = set()
    if a.ocr:
        for r in json.load(open(a.ocr, encoding="utf-8")):
            if r.get("text", "").strip():
                ocr_done.add(os.path.basename(r["image"]))
    text_pages = [p["page"] for p in pages if p["kind"] == "text"]
    other = [p for p in pages if p["kind"] != "text"]
    read = [p["page"] for p in other if p.get("image") and p["image"] in ocr_done]
    missing = [p["page"] for p in other if p["page"] not in read]
    cov = (len(text_pages) + len(read)) / max(1, len(pages))
    res = {"input": a.name or a.pages, "kind": "pdf", "pages": len(pages), "text_layer": len(text_pages),
           "ocr_read": read, "never_read": missing, "coverage": round(cov, 4)}
    save_cov(a.cov, load_cov(a.cov), res)
    print(f"[pdf] {res['input']}  {len(pages)} pages: text layer {len(text_pages)}, OCR'd {len(read)}, "
          f"never read {missing or 'none'}  -> coverage {cov:.0%}")


# ---------------------------------------------------------------- image
def cmd_image(a):
    from PIL import Image
    w, h = Image.open(a.image).size
    direct = min(1.0, a.vision_max / max(w, h))
    tiled = None
    if a.tiles:
        idx = json.load(open(a.tiles, encoding="utf-8"))
        tiled = min(min(1.0, a.vision_max / max(t["box"][2] - t["box"][0], t["box"][3] - t["box"][1]))
                    for t in idx["tiles"])
    best = tiled if tiled is not None else direct
    res = {"input": a.name or a.image, "kind": "image", "pixels": [w, h], "direct_scale": round(direct, 3),
           "tiled_scale": tiled, "coverage": round(best, 4)}
    save_cov(a.cov, load_cov(a.cov), res)
    print(f"[image] {res['input']}  {w}x{h}: viewed directly at {direct:.2f}x (24 px text -> {24 * direct:.0f} px)"
          + (f"; through tiles at {tiled:.2f}x" if tiled is not None else "; no tiles given"))


# ---------------------------------------------------------------- office
OFFICE_KEYS = [("units", "slides"), ("parts", "speaker_notes"), ("parts", "hidden_slides"), ("parts", "comments"),
               ("parts", "tracked_changes"), ("units", "sheets"), ("parts", "hidden_sheets")]


def cmd_office(a):
    ledger = json.load(open(a.ledger, encoding="utf-8"))["inputs"]
    found = json.load(open(a.found, encoding="utf-8"))
    base = os.path.basename(found["file"])
    entry = next((e for e in ledger if os.path.basename(e["file"]) == base), None)
    if entry is None:
        sys.exit(f"{base} is not in the ledger")
    exp_tot = got_tot = 0
    rows = []
    for where, key in OFFICE_KEYS:
        exp = entry.get(where, {}).get(key)
        if not exp:
            continue
        got = found["found"].get(key, 0)
        exp_tot += exp
        got_tot += min(got, exp)
        rows.append((key, got, exp))
    media = entry.get("parts", {}).get("embedded_media", 0)
    cov = got_tot / exp_tot if exp_tot else 1.0
    res = {"input": a.name or base, "kind": "office", "checked": rows, "embedded_media_to_view": media,
           "coverage": round(cov, 4)}
    save_cov(a.cov, load_cov(a.cov), res)
    print(f"[office] {res['input']}: " + ", ".join(f"{k} {g}/{e}" for k, g, e in rows)
          + f"  -> coverage {cov:.0%}" + (f"; {media} embedded image(s) still need viewing" if media else ""))


# ---------------------------------------------------------------- summary
def cmd_summary(a):
    cov = load_cov(a.cov)
    rows, bad = [], 0
    for it in cov["items"]:
        c = it.get("coverage", 0.0)
        v = verdict(c, a.min)
        bad += v != "OK"
        if it["kind"] == "audio":
            m = it["measures"].get("speech") or it["measures"].get("sound")
            detail = f"{m['covered_s']:.0f}/{m['active_s']:.0f}s speech transcribed; {len(m['gaps'])} gap(s); " \
                     f"{len(it['orphan_text'])} text-without-sound"
        elif it["kind"] == "video":
            worst = min(it["strategies"].items(), key=lambda kv: kv[1]["seen"] / max(1, kv[1]["of"]), default=None)
            detail = f"detection {it.get('detection_recall', '—')}; worst naive: {worst[0]} {worst[1]['seen']}/{worst[1]['of']}" if worst else ""
        elif it["kind"] == "pdf":
            detail = f"{it['pages']} pages; never read: {it['never_read'] or 'none'}"
        elif it["kind"] == "office":
            detail = ", ".join(f"{k} {g}/{e}" for k, g, e in it["checked"]) + \
                     (f"; {it['embedded_media_to_view']} image(s) to view" if it["embedded_media_to_view"] else "")
        else:
            detail = f"{it['pixels'][0]}x{it['pixels'][1]}; direct {it['direct_scale']}x, tiled {it['tiled_scale']}"
        rows.append(f"| `{os.path.basename(str(it['input']))}` | {it['kind']} | {c:.1%} | {v} | {detail} |")
    md = "\n".join(["# Coverage", "", f"threshold {a.min:.0%}", "",
                    "| input | kind | coverage | verdict | detail |", "|---|---|---|---|---|"] + rows) + "\n"
    if a.md:
        open(a.md, "w", encoding="utf-8").write(md)
    print(md)
    sys.exit(1 if bad else 0)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("audio"); p.add_argument("--media", required=True); p.add_argument("--asr", required=True)
    p.add_argument("--track", type=int, default=0); p.add_argument("--min-gap", type=float, default=0.5)
    p.add_argument("--pad", type=float, default=0.3, help="seconds added around each transcript span")
    p.add_argument("--name"); p.add_argument("--cov", default="coverage.json"); p.set_defaults(fn=cmd_audio)
    p = sub.add_parser("video"); p.add_argument("--segments", required=True); p.add_argument("--subs")
    p.add_argument("--duration", type=float); p.add_argument("--truth")
    p.add_argument("--uniform", type=int, nargs="*", default=[8, 16, 32]); p.add_argument("--fps", type=float, nargs="*", default=[0.5, 1])
    p.add_argument("--name"); p.add_argument("--cov", default="coverage.json"); p.set_defaults(fn=cmd_video)
    p = sub.add_parser("pdf"); p.add_argument("--pages", required=True); p.add_argument("--ocr")
    p.add_argument("--name"); p.add_argument("--cov", default="coverage.json"); p.set_defaults(fn=cmd_pdf)
    p = sub.add_parser("image"); p.add_argument("--image", required=True); p.add_argument("--tiles")
    p.add_argument("--vision-max", type=int, default=1568)
    p.add_argument("--name"); p.add_argument("--cov", default="coverage.json"); p.set_defaults(fn=cmd_image)
    p = sub.add_parser("office"); p.add_argument("--ledger", required=True); p.add_argument("--found", required=True)
    p.add_argument("--name"); p.add_argument("--cov", default="coverage.json"); p.set_defaults(fn=cmd_office)
    p = sub.add_parser("summary"); p.add_argument("--cov", default="coverage.json"); p.add_argument("--md")
    p.add_argument("--min", type=float, default=0.98); p.set_defaults(fn=cmd_summary)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
