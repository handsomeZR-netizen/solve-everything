#!/usr/bin/env python3
"""Extract EVERYTHING from .pptx / .docx / .xlsx, including what a normal read skips.

  pptx  every slide in deck order (hidden ones marked), speaker notes, chart/table text, image count
  docx  body, headers/footers, footnotes, comments (with author), tracked insertions/deletions, images
  xlsx  every sheet including hidden / very hidden ones, cell values (first --rows rows), formulas count

Standard library only (zip + XML), so it runs anywhere. Output: Markdown for reading plus a JSON
count of what was found (feed it to input-audit/coverage.py office).

usage:
  python office_extract.py deck.pptx --out deck.md
  python office_extract.py notes.docx data.xlsx --out-dir extracted/
"""
import argparse
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def xml(z, name):
    return ET.fromstring(z.read(name)) if name in z.namelist() else None


def rels(z, part):
    folder, base = os.path.split(part)
    rp = f"{folder}/_rels/{base}.rels"
    out = {}
    root = xml(z, rp)
    if root is None:
        return out
    for r in root.findall("rel:Relationship", NS):
        target = r.get("Target")
        if not target.startswith("/"):
            target = os.path.normpath(os.path.join(folder, target)).replace("\\", "/")
        else:
            target = target.lstrip("/")
        out[r.get("Id")] = (r.get("Type", "").rsplit("/", 1)[-1], target)
    return out


def para_text(root, p_tag, t_tag):
    lines = []
    for p in root.iter(p_tag):
        t = "".join(x.text or "" for x in p.iter(t_tag)).strip()
        if t:
            lines.append(t)
    return lines


def do_pptx(z):
    md, found = [], {"slides": 0, "hidden_slides": 0, "speaker_notes": 0, "charts": 0, "images": 0}
    pres = xml(z, "ppt/presentation.xml")
    prel = rels(z, "ppt/presentation.xml")
    ids = [s.get(f"{{{NS['r']}}}id") for s in pres.find("p:sldIdLst", NS)] if pres is not None else []
    slides = [prel[i][1] for i in ids if i in prel]
    for n, sp in enumerate(slides, 1):
        root = xml(z, sp)
        hidden = root.get("show") == "0"
        srel = rels(z, sp)
        found["slides"] += 1
        found["hidden_slides"] += hidden
        md.append(f"## Slide {n}{' (HIDDEN)' if hidden else ''}")
        md += [f"- {t}" for t in para_text(root, f"{{{NS['a']}}}p", f"{{{NS['a']}}}t")]
        for kind, target in srel.values():
            if kind == "notesSlide":
                notes = [t for t in para_text(xml(z, target), f"{{{NS['a']}}}p", f"{{{NS['a']}}}t")
                         if not re.fullmatch(r"\d+", t)]  # drop the slide-number placeholder
                if notes:
                    found["speaker_notes"] += 1
                    md.append("> **Speaker notes:** " + " ".join(notes))
            elif kind == "chart":
                found["charts"] += 1
                vals = [v.text for v in xml(z, target).iter(f"{{{NS['a'].replace('main', 'chart')}}}v")][:40]
                md.append(f"> chart values: {', '.join(v for v in vals if v)}")
            elif kind == "image":
                found["images"] += 1
        md.append("")
    return md, found


def do_docx(z):
    md, found = [], {"comments": 0, "tracked_changes": 0, "images": 0, "headers_footers": 0, "footnotes": 0}
    W = f"{{{NS['w']}}}"
    body = xml(z, "word/document.xml")
    md.append("## Body")
    md += para_text(body, W + "p", W + "t")
    ins = ["".join(t.text or "" for t in e.iter(W + "t")) for e in body.iter(W + "ins")]
    dels = ["".join(t.text or "" for t in e.iter(W + "delText")) for e in body.iter(W + "del")]
    found["tracked_changes"] = len([x for x in ins + dels if x.strip()])
    if found["tracked_changes"]:
        md += ["", "## Tracked changes"] + [f"- inserted: {x}" for x in ins if x.strip()] + \
              [f"- deleted: {x}" for x in dels if x.strip()]
    for name in sorted(n for n in z.namelist() if re.match(r"word/(header|footer)\d*\.xml$", n)):
        lines = para_text(xml(z, name), W + "p", W + "t")
        if lines:
            found["headers_footers"] += 1
            md += ["", f"## {os.path.basename(name)}"] + lines
    fn = xml(z, "word/footnotes.xml")
    if fn is not None:
        notes = [t for t in para_text(fn, W + "p", W + "t")]
        if notes:
            found["footnotes"] = len(notes)
            md += ["", "## Footnotes"] + notes
    cm = xml(z, "word/comments.xml")
    if cm is not None:
        items = cm.findall("w:comment", NS)
        found["comments"] = len(items)
        if items:
            md += ["", "## Comments"]
            for c in items:
                md.append(f"- **{c.get(W + 'author', '?')}**: " + " ".join(para_text(c, W + "p", W + "t")))
    found["images"] = len([n for n in z.namelist() if n.startswith("word/media/")])
    if found["images"]:
        md += ["", f"*({found['images']} embedded image(s) in word/media/: view them, text extraction cannot)*"]
    return md, found


def do_xlsx(z, max_rows):
    S = f"{{{NS['s']}}}"
    md, found = [], {"sheets": 0, "hidden_sheets": 0, "formulas": 0}
    shared = []
    ss = xml(z, "xl/sharedStrings.xml")
    if ss is not None:
        shared = ["".join(t.text or "" for t in si.iter(S + "t")) for si in ss.findall("s:si", NS)]
    wb = xml(z, "xl/workbook.xml")
    wrel = rels(z, "xl/workbook.xml")
    for sh in wb.find("s:sheets", NS):
        name, state = sh.get("name"), sh.get("state", "visible")
        target = wrel.get(sh.get(f"{{{NS['r']}}}id"), (None, None))[1]
        found["sheets"] += 1
        found["hidden_sheets"] += state != "visible"
        md.append(f"## Sheet: {name}{' (' + state.upper() + ')' if state != 'visible' else ''}")
        root = xml(z, target) if target else None
        if root is None:
            continue
        rows = []
        for row in root.iter(S + "row"):
            cells = []
            for c in row.findall("s:c", NS):
                v = c.find("s:v", NS)
                f = c.find("s:f", NS)
                found["formulas"] += f is not None
                val = v.text if v is not None else ""
                if c.get("t") == "s" and val:
                    val = shared[int(val)]
                elif c.get("t") == "inlineStr":
                    val = "".join(t.text or "" for t in c.iter(S + "t"))
                cells.append(val or "")
            rows.append(cells)
            if len(rows) >= max_rows:
                break
        if rows:
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            md.append("| " + " | ".join(rows[0]) + " |")
            md.append("|" + "---|" * width)
            md += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        md.append("")
    return md, found


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+"); ap.add_argument("--out", help="single output .md (one input)")
    ap.add_argument("--out-dir", help="one .md + .json per input"); ap.add_argument("--rows", type=int, default=200)
    args = ap.parse_args()
    for f in args.files:
        ext = os.path.splitext(f)[1].lower()
        with zipfile.ZipFile(f) as z:
            if ext == ".pptx":
                md, found = do_pptx(z)
            elif ext == ".docx":
                md, found = do_docx(z)
            elif ext == ".xlsx":
                md, found = do_xlsx(z, args.rows)
            else:
                print(f"skip {f}: not pptx/docx/xlsx")
                continue
        text = f"# {os.path.basename(f)}\n\n" + "\n".join(md).strip() + "\n"
        out = args.out if (args.out and len(args.files) == 1) else None
        if args.out_dir:
            os.makedirs(args.out_dir, exist_ok=True)
            out = os.path.join(args.out_dir, os.path.basename(f) + ".md")
        if out:
            open(out, "w", encoding="utf-8").write(text)
            json.dump({"file": f, "found": found}, open(os.path.splitext(out)[0] + ".found.json", "w", encoding="utf-8"),
                      ensure_ascii=False)
        print(text if not out else f"{f} -> {out}")
        print("found: " + ", ".join(f"{k}={v}" for k, v in found.items()))


if __name__ == "__main__":
    main()
