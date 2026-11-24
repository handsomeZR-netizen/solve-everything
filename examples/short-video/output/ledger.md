# Input ledger

6 file(s): 0.8 min of media, 2 PDF pages, 2 slides, 1 images, 63 text characters. 7 high-severity risk(s).

| file | type | units | risks | route |
|---|---|---|---|---|
| `clip.mp4` | video | seconds=50.35, frames=503 | uniform_16<br>uniform_32 | media-ingest → speech-to-text → screen-and-ocr → timeline-fusion → visual-verify |
| `data.xlsx` | office | sheets=2 | **hidden_sheets**<br>many_sheets | docs-and-images |
| `deck.pptx` | office | slides=2 | **speaker_notes**<br>**hidden_slides** | docs-and-images |
| `long_screenshot.png` | image | pixels=[1200, 5000], frames=1 | **downscaled**<br>**extreme_aspect** | docs-and-images (tile_image) → screen-and-ocr (text) |
| `notes.docx` | office | chars=11 | embedded_media<br>**comments** | docs-and-images |
| `report.pdf` | pdf | pages=2, chars=52 | **scanned_pages** | docs-and-images → screen-and-ocr (scanned pages) |

## What a quick pass would drop

- `data.xlsx` **hidden_sheets**: 1 hidden sheet(s)
- `deck.pptx` **speaker_notes**: 1 slide(s) carry speaker notes: often the real argument
- `deck.pptx` **hidden_slides**: 1 hidden slide(s)
- `long_screenshot.png` **downscaled**: 1200x5000 will be shrunk to 0.31x at a 1568px vision limit: 24 px text becomes 8 px; tile it (docs-and-images/tile_image.py)
- `long_screenshot.png` **extreme_aspect**: aspect ratio 4.2:1 (long screenshot / banner)
- `notes.docx` **comments**: 1 comment(s) outside the body text
- `report.pdf` **scanned_pages**: 1 page(s) have no text layer [2]: a text-only read sees them as blank; OCR or view them
