#!/usr/bin/env python3
"""PDF -> per-page text with structure, tables as CSV, and page images where text is missing.

For every page it decides: real text layer, or scanned / image-only page (little text,
large image coverage). Text pages become Markdown with headings guessed from font size.
Scanned pages are rendered to PNG so you can OCR them (screen-and-ocr/scripts/ocr.py)
or look at them directly.

usage:
  python pdf_extract.py report.pdf --out report/                 # text + scanned pages rendered
  python pdf_extract.py report.pdf --out report/ --render all    # also render every page (charts!)
  python pdf_extract.py report.pdf --out report/ --tables        # tables -> CSV

Writes report/document.md, report/pages.jsonl, report/page_XXX.png, report/table_pXXX_N.csv
"""
import argparse
import csv
import json
import os
import statistics
import sys


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf"); ap.add_argument("--out", required=True)
    ap.add_argument("--render", choices=["scanned", "all", "none"], default="scanned")
    ap.add_argument("--dpi", type=int, default=150, help="150 reads well; 200-300 for small print OCR")
    ap.add_argument("--tables", action="store_true", help="extract tables to CSV (PyMuPDF find_tables)")
    ap.add_argument("--pages", help="page range, 1-based, e.g. 1-5,8")
    args = ap.parse_args()

    try:
        import fitz  # PyMuPDF
    except ImportError:
        sys.exit("pip install pymupdf")
    os.makedirs(args.out, exist_ok=True)
    doc = fitz.open(args.pdf)
    wanted = range(doc.page_count)
    if args.pages:
        sel = set()
        for part in args.pages.split(","):
            a, _, b = part.partition("-")
            sel.update(range(int(a) - 1, int(b or a)))
        wanted = [p for p in range(doc.page_count) if p in sel]

    # body font size = the size most characters are set in
    sizes = []
    for p in wanted:
        for b in doc[p].get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    sizes += [round(s["size"], 1)] * len(s["text"].strip())
    body = statistics.mode(sizes) if sizes else 10.0

    md, rows, scanned = [f"# {os.path.basename(args.pdf)}\n"], [], []
    for p in wanted:
        page = doc[p]
        area = page.rect.width * page.rect.height
        img_cover = 0.0
        for info in page.get_image_info():
            x0, y0, x1, y1 = info["bbox"]
            img_cover += max(0, x1 - x0) * max(0, y1 - y0)
        img_cover = min(1.0, img_cover / area)
        text = page.get_text("text", sort=True)
        n_chars = len("".join(text.split()))
        is_scan = n_chars < 30 and img_cover > 0.4
        kind = "scanned" if is_scan else ("empty" if n_chars < 5 else "text")

        md.append(f"\n## p.{p + 1}\n")
        tables, table_boxes = [], []
        if args.tables and kind == "text" and hasattr(page, "find_tables"):
            try:
                for k, tab in enumerate(page.find_tables().tables):
                    data = [[(c or "").replace("\n", " ") for c in r] for r in (tab.extract() or [])]
                    if len(data) < 2:
                        continue
                    name = f"table_p{p + 1:03d}_{k}.csv"
                    with open(os.path.join(args.out, name), "w", newline="", encoding="utf-8-sig") as fh:
                        csv.writer(fh).writerows(data)
                    tables.append(name)
                    mdt = ["| " + " | ".join(data[0]) + " |", "|" + "---|" * len(data[0])]
                    mdt += ["| " + " | ".join(r) + " |" for r in data[1:]]
                    table_boxes.append({"bbox": fitz.Rect(tab.bbox), "md": mdt + [f"*({name})*", ""], "done": False})
            except Exception as e:  # table detection is heuristic; never let it kill the run
                print(f"p.{p + 1}: table extraction failed: {e}", file=sys.stderr)
        if kind == "text":
            for b in page.get_text("dict", sort=True)["blocks"]:
                cx, cy = (b["bbox"][0] + b["bbox"][2]) / 2, (b["bbox"][1] + b["bbox"][3]) / 2
                inside = next((t for t in table_boxes if t["bbox"].contains(fitz.Point(cx, cy))), None)
                if inside:  # the table is rendered once, as a Markdown table, where it starts
                    if not inside["done"]:
                        md += inside["md"]
                        inside["done"] = True
                    continue
                lines = []
                big = 0.0
                for l in b.get("lines", []):
                    t = "".join(s["text"] for s in l["spans"]).strip()
                    if t:
                        lines.append(t)
                        big = max(big, max(s["size"] for s in l["spans"]))
                para = " ".join(lines) if all(x[-1:].isascii() for x in lines) else "".join(lines)
                if not para:
                    continue
                if big >= body * 1.25 and len(para) < 80:
                    md.append(("### " if big >= body * 1.6 else "#### ") + para)
                else:
                    md.append(para)
                md.append("")
        else:
            md.append(f"*(page has no usable text layer: {kind}, image cover {img_cover:.0%}; "
                      f"see page_{p + 1:03d}.png)*")

        for t in table_boxes:  # tables with no text block inside still get printed
            if not t["done"]:
                md += t["md"]

        image = None
        if args.render == "all" or (args.render == "scanned" and kind != "text"):
            image = f"page_{p + 1:03d}.png"
            page.get_pixmap(dpi=args.dpi).save(os.path.join(args.out, image))
        if kind != "text":
            scanned.append(p + 1)
        rows.append({"page": p + 1, "kind": kind, "chars": n_chars, "image_cover": round(img_cover, 2),
                     "text": text, "tables": tables, "image": image})

    with open(os.path.join(args.out, "document.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md).strip() + "\n")
    with open(os.path.join(args.out, "pages.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} pages, body font {body}pt, {len(scanned)} without text layer"
          + (f" (pages {scanned[:20]}{'...' if len(scanned) > 20 else ''}: OCR or view the PNGs)" if scanned else ""))
    print(f"-> {args.out}/document.md")


if __name__ == "__main__":
    main()
