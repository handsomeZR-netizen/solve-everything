#!/usr/bin/env python3
"""Input inventory: list everything inside the inputs, and what a quick pass would silently drop.

Before an agent reads, watches or listens to anything, it should know how much there is:
seconds of audio, frames of video, pages, slides, embedded images, hidden sheets, pixels.
Models rarely say "I skipped page 37"; this ledger makes the size of the job explicit so
coverage can be checked afterwards (coverage.py).

usage:
  python inventory.py inputs/ report.pdf clip.mp4 --out ledger.json --md ledger.md
  python inventory.py inputs/ --vision-max 1568 --uniform-frames 32 --context-chars 200000

Detects per type (no network, stdlib + optional ffprobe / PyMuPDF / Pillow):
  video/audio  duration, tracks, fps (VFR), rotation, embedded subtitles, start_time;
               what uniform N-frame sampling would mean (one frame every X s)
  pdf          pages, pages without a text layer (scanned), encrypted, total characters
  image        size; downscale factor at the vision limit; extreme aspect ratio; animated frames
  docx/pptx/xlsx  embedded images, charts, speaker notes, hidden slides / sheets, comments
  text/subtitle   characters vs the context budget, encoding, cue count
  archive      entries inside (unpack first: untrusted)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import zipfile

VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".m4v", ".ts", ".wmv"}
AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".amr"}
IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic"}
TEXT = {".txt", ".md", ".json", ".jsonl", ".csv", ".tsv", ".log", ".html", ".htm", ".xml", ".yaml", ".yml",
        ".py", ".js", ".ts", ".java", ".c", ".cpp", ".go", ".rs", ".tex"}
SUBS = {".srt", ".vtt", ".ass", ".ssa", ".lrc"}
OFFICE = {".docx", ".pptx", ".xlsx"}
ARCHIVE = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz"}


def risk(code, detail, severity="warn"):
    return {"code": code, "severity": severity, "detail": detail}


def probe_media(path, uniform):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                             capture_output=True)
        info = json.loads(out.stdout.decode("utf-8", "replace"))
    except FileNotFoundError:
        return {"units": {}, "parts": {}, "risks": [risk("no_ffprobe", "ffprobe not on PATH: cannot size this file", "high")]}
    fmt = info.get("format", {})
    dur = float(fmt.get("duration") or 0)
    streams = info.get("streams", [])
    vids = [s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")]
    auds = [s for s in streams if s.get("codec_type") == "audio"]
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]
    units = {"seconds": round(dur, 2)}
    parts = {"audio_tracks": len(auds), "subtitle_tracks": len(subs), "video_streams": len(vids)}
    risks = []
    if vids:
        v = vids[0]

        def ratio(t):
            try:
                a, b = (float(x) for x in str(t).split("/"))
                return a / b if b else 0.0
            except ValueError:
                return 0.0
        fps = ratio(v.get("avg_frame_rate"))
        rfps = ratio(v.get("r_frame_rate"))
        units["frames"] = int(dur * fps) if fps else None
        parts.update(width=v.get("width"), height=v.get("height"), fps=round(fps, 3))
        if fps and rfps and abs(fps - rfps) / rfps > 0.01:
            risks.append(risk("vfr", f"variable frame rate (avg {fps:.2f} vs nominal {rfps:.2f}): time from frame index drifts"))
        rot = int(float((v.get("tags") or {}).get("rotate", 0) or 0))
        for side in v.get("side_data_list") or []:
            rot = int(float(side.get("rotation", rot)))
        if rot % 360:
            risks.append(risk("rotation", f"rotated {rot % 360}°: crop boxes refer to the rotated picture", "info"))
        for n in uniform:
            if dur > 0:
                risks.append(risk(f"uniform_{n}",
                                  f"sampling {n} frames uniformly = one frame every {dur / n:.1f} s; anything on screen "
                                  f"for less than that can be missed entirely", "high" if dur / n > 5 else "warn"))
    if len(auds) > 1:
        risks.append(risk("multi_audio", f"{len(auds)} audio tracks: a default pass hears only the first one", "high"))
    if not auds:
        risks.append(risk("no_audio", "no audio stream", "info"))
    if subs:
        risks.append(risk("embedded_subs", f"{len(subs)} embedded subtitle track(s): free exact text, extract it", "info"))
    st = float(fmt.get("start_time") or 0)
    if abs(st) > 0.001:
        risks.append(risk("start_time", f"container start_time {st:.3f} s: tools may disagree on time zero"))
    if dur > 3600:
        risks.append(risk("long_media", f"{dur / 3600:.1f} h: process in chunks with offsets; one-shot summaries lose the middle", "high"))
    return {"units": units, "parts": parts, "risks": risks}


def inspect_pdf(path, context_chars):
    try:
        import fitz
    except ImportError:
        return {"units": {}, "parts": {}, "risks": [risk("no_pymupdf", "pip install pymupdf to size PDFs", "high")]}
    risks = []
    try:
        doc = fitz.open(path)
    except Exception as e:
        return {"units": {}, "parts": {}, "risks": [risk("unreadable", str(e), "high")]}
    if doc.needs_pass:
        return {"units": {"pages": doc.page_count}, "parts": {},
                "risks": [risk("encrypted", "password protected: nothing can be read until the user unlocks it", "high")]}
    scanned, chars, images = [], 0, 0
    for i, page in enumerate(doc):
        t = page.get_text("text")
        n = len("".join(t.split()))
        chars += n
        info = page.get_image_info()
        images += len(info)
        area = page.rect.width * page.rect.height
        cover = sum(max(0, b["bbox"][2] - b["bbox"][0]) * max(0, b["bbox"][3] - b["bbox"][1]) for b in info) / max(area, 1)
        if n < 30 and cover > 0.4:
            scanned.append(i + 1)
    if scanned:
        risks.append(risk("scanned_pages", f"{len(scanned)} page(s) have no text layer {scanned[:15]}: a text-only "
                                           f"read sees them as blank; OCR or view them", "high"))
    if images - len(scanned) > 0:
        risks.append(risk("figures", f"{images - len(scanned)} embedded image(s)/figure(s): numbers inside charts are "
                                     f"not in the text layer"))
    if chars > context_chars:
        risks.append(risk("over_context", f"{chars} characters > budget {context_chars}: read in chunks and track which "
                                          f"chunks were read", "high"))
    return {"units": {"pages": doc.page_count, "chars": chars},
            "parts": {"scanned_pages": scanned, "embedded_images": images}, "risks": risks}


def inspect_image(path, vision_max):
    try:
        from PIL import Image
    except ImportError:
        return {"units": {}, "parts": {}, "risks": [risk("no_pillow", "pip install pillow to size images")]}
    try:
        im = Image.open(path)
    except Exception as e:
        return {"units": {}, "parts": {}, "risks": [risk("unreadable", str(e), "high")]}
    w, h = im.size
    frames = getattr(im, "n_frames", 1)
    risks = []
    k = min(1.0, vision_max / max(w, h))
    if k < 1.0:
        sev = "high" if k < 0.6 else "warn"
        risks.append(risk("downscaled", f"{w}x{h} will be shrunk to {k:.2f}x at a {vision_max}px vision limit: "
                                        f"24 px text becomes {24 * k:.0f} px; tile it (docs-and-images/tile_image.py)", sev))
    if max(w, h) / max(1, min(w, h)) > 3:
        risks.append(risk("extreme_aspect", f"aspect ratio {max(w, h) / min(w, h):.1f}:1 (long screenshot / banner)", "high"))
    if frames > 1:
        risks.append(risk("animated", f"{frames} frames: a single view sees only one of them", "high"))
    return {"units": {"pixels": [w, h], "frames": frames}, "parts": {"vision_scale": round(k, 3)}, "risks": risks}


def inspect_office(path, ext):
    risks, parts, units = [], {}, {}
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return {"units": {}, "parts": {}, "risks": [risk("unreadable", "not a valid Office file", "high")]}
    names = z.namelist()
    media = [n for n in names if "/media/" in n]
    charts = [n for n in names if re.search(r"/charts/chart\d+\.xml$", n)]
    parts.update(embedded_media=len(media), charts=len(charts))
    if media:
        risks.append(risk("embedded_media", f"{len(media)} embedded image/media file(s): text extraction drops them"))
    if charts:
        risks.append(risk("charts", f"{len(charts)} chart(s): their numbers live in chart XML, not in the text"))
    if ext == ".pptx":
        slides = [n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)]
        notes = [n for n in names if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", n)]
        hidden = sum(1 for n in slides if 'show="0"' in z.read(n).decode("utf-8", "ignore")[:600])
        units["slides"] = len(slides)
        parts.update(speaker_notes=len(notes), hidden_slides=hidden)
        if notes:
            risks.append(risk("speaker_notes", f"{len(notes)} slide(s) carry speaker notes: often the real argument", "high"))
        if hidden:
            risks.append(risk("hidden_slides", f"{hidden} hidden slide(s)", "high"))
    elif ext == ".docx":
        doc = z.read("word/document.xml").decode("utf-8", "ignore")
        units["chars"] = len(re.sub(r"<[^>]+>", "", doc))
        comments = z.read("word/comments.xml").decode("utf-8", "ignore").count("<w:comment ") if "word/comments.xml" in names else 0
        tracked = doc.count("<w:ins ") + doc.count("<w:del ")
        parts.update(comments=comments, tracked_changes=tracked)
        if comments:
            risks.append(risk("comments", f"{comments} comment(s) outside the body text", "high"))
        if tracked:
            risks.append(risk("tracked_changes", f"{tracked} tracked insertion/deletion(s): which version is 'the' text?", "high"))
    elif ext == ".xlsx":
        wb = z.read("xl/workbook.xml").decode("utf-8", "ignore")
        sheets = re.findall(r"<sheet [^>]*>", wb)
        hidden = [s for s in sheets if 'state="hidden"' in s or 'state="veryHidden"' in s]
        units["sheets"] = len(sheets)
        parts["hidden_sheets"] = len(hidden)
        if hidden:
            risks.append(risk("hidden_sheets", f"{len(hidden)} hidden sheet(s)", "high"))
        if len(sheets) > 1:
            risks.append(risk("many_sheets", f"{len(sheets)} sheets: a quick read often sees only the first"))
    return {"units": units, "parts": parts, "risks": risks}


def inspect_text(path, ext, context_chars):
    raw = open(path, "rb").read()
    enc = "utf-8"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        enc = "gb18030"
        text = raw.decode("gb18030", "replace")
    risks = []
    if enc != "utf-8":
        risks.append(risk("encoding", "not UTF-8 (decoded as GB18030): tools that assume UTF-8 will garble it"))
    units = {"chars": len(text), "lines": text.count("\n") + 1}
    parts = {"encoding": enc}
    if ext in SUBS:
        cues = len(re.findall(r"\d+:\d{2}:\d{2}[,.]\d{3}\s*-->", text)) or len(re.findall(r"^\[\d+:\d{2}", text, re.M))
        parts["cues"] = cues
    if len(text) > context_chars:
        risks.append(risk("over_context", f"{len(text)} characters > budget {context_chars}: chunk it and record which "
                                          f"chunks were read", "high"))
    return {"units": units, "parts": parts, "risks": risks}


def inspect_archive(path):
    try:
        with zipfile.ZipFile(path) as z:
            n = len(z.namelist())
        return {"units": {"entries": n}, "parts": {},
                "risks": [risk("archive", f"{n} entries inside: unpack into an empty folder and inventory again", "high")]}
    except zipfile.BadZipFile:
        return {"units": {}, "parts": {}, "risks": [risk("archive", "archive: unpack first, then inventory again", "high")]}


ROUTES = {
    "video": ["media-ingest", "speech-to-text", "screen-and-ocr", "timeline-fusion", "visual-verify"],
    "audio": ["media-ingest", "speech-to-text", "speaker-diarization?", "music-and-sound?"],
    "pdf": ["docs-and-images", "screen-and-ocr (scanned pages)"],
    "image": ["docs-and-images (tile_image)", "screen-and-ocr (text)"],
    "office": ["docs-and-images"],
    "text": ["read in chunks"], "subtitle": ["timeline-fusion (as notes)"], "archive": ["unpack first"],
}


def kind_of(ext):
    if ext in VIDEO: return "video"
    if ext in AUDIO: return "audio"
    if ext == ".pdf": return "pdf"
    if ext in IMAGE: return "image"
    if ext in OFFICE: return "office"
    if ext in SUBS: return "subtitle"
    if ext in TEXT: return "text"
    if ext in ARCHIVE: return "archive"
    return "other"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", default="ledger.json"); ap.add_argument("--md", default=None)
    ap.add_argument("--vision-max", type=int, default=1568, help="long edge a vision model keeps without shrinking")
    ap.add_argument("--uniform-frames", type=int, nargs="*", default=[16, 32],
                    help="frame budgets to evaluate for naive uniform video sampling")
    ap.add_argument("--context-chars", type=int, default=200000, help="text budget for one read")
    args = ap.parse_args()

    files = []
    for p in args.inputs:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                files += [os.path.join(root, n) for n in sorted(names) if not n.startswith(".")]
        else:
            files.append(p)

    ledger = []
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        kind = kind_of(ext)
        if kind in ("video", "audio"):
            r = probe_media(f, args.uniform_frames if kind == "video" else [])
            if kind == "video" and not r["parts"].get("video_streams"):
                kind = "audio"
        elif kind == "pdf":
            r = inspect_pdf(f, args.context_chars)
        elif kind == "image":
            r = inspect_image(f, args.vision_max)
        elif kind == "office":
            r = inspect_office(f, ext)
        elif kind in ("text", "subtitle"):
            r = inspect_text(f, ext, args.context_chars)
        elif kind == "archive":
            r = inspect_archive(f)
        else:
            r = {"units": {}, "parts": {}, "risks": [risk("unknown_type", "unknown type: decide how to read it", "warn")]}
        ledger.append({"file": f.replace("\\", "/"), "type": kind, "size_mb": round(os.path.getsize(f) / 1e6, 2),
                       **r, "route": ROUTES.get(kind, ["?"]), "status": "pending"})

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"inputs": ledger}, fh, ensure_ascii=False, indent=1)

    tot = {"seconds": 0.0, "pages": 0, "slides": 0, "images": 0, "chars": 0}
    for e in ledger:
        u = e["units"]
        tot["seconds"] += u.get("seconds", 0) or 0
        tot["pages"] += u.get("pages", 0) or 0
        tot["slides"] += u.get("slides", 0) or 0
        tot["chars"] += u.get("chars", 0) or 0
        tot["images"] += 1 if e["type"] == "image" else 0
    high = [(e["file"], r) for e in ledger for r in e["risks"] if r["severity"] == "high"]
    lines = ["# Input ledger", "",
             f"{len(ledger)} file(s): {tot['seconds'] / 60:.1f} min of media, {tot['pages']} PDF pages, "
             f"{tot['slides']} slides, {tot['images']} images, {tot['chars']} text characters. "
             f"{len(high)} high-severity risk(s).", "",
             "| file | type | units | risks | route |", "|---|---|---|---|---|"]
    for e in ledger:
        units = ", ".join(f"{k}={v}" for k, v in e["units"].items() if v not in (None, 0))
        rk = "<br>".join(f"{'**' if r['severity'] == 'high' else ''}{r['code']}{'**' if r['severity'] == 'high' else ''}"
                         for r in e["risks"]) or "—"
        lines.append(f"| `{os.path.basename(e['file'])}` | {e['type']} | {units} | {rk} | {' → '.join(e['route'])} |")
    lines += ["", "## What a quick pass would drop", ""]
    for f, r in high:
        lines.append(f"- `{os.path.basename(f)}` **{r['code']}**: {r['detail']}")
    if not high:
        lines.append("- nothing high-severity found")
    md = "\n".join(lines) + "\n"
    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(md)
    print(md)


if __name__ == "__main__":
    main()
