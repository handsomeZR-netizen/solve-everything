---
name: docs-and-images
description: >-
  Get clean, structured input out of documents and still images: PDF text with headings and tables
  (as Markdown and CSV), automatic detection of scanned / image-only pages that need OCR or viewing,
  page rendering for charts, and tiling of long screenshots, posters and dashboards so small print
  survives a vision model's downscaling. Use whenever the input is a PDF, scanned file, slide export,
  long chat screenshot, poster, infographic, whiteboard photo or any image with text that must be read,
  summarised, compared or quoted accurately. PDF 提取、扫描件、表格、长截图、海报、图片看不清小字，都用这个。
---

# docs-and-images：文档和图片的干净输入

文档类输入出错，通常不是因为模型理解不了，而是**它拿到的东西就是乱的**：表格被拍平成一串文字、扫描页根本没有文字层、长截图被缩小到看不清。

## PDF：pdf_extract.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/pdf_extract.py report.pdf --out report/ --tables          # 常规
python ${CLAUDE_SKILL_DIR}/scripts/pdf_extract.py report.pdf --out report/ --render all     # 图表多：每页都渲染
python ${CLAUDE_SKILL_DIR}/scripts/pdf_extract.py report.pdf --out report/ --pages 1-5,12
```

- 每页判断是**有文字层**还是**扫描/纯图片**（文字少于 30 字且图片覆盖超过 40%）。扫描页渲染成 PNG，再交给 `screen-and-ocr/scripts/ocr.py` 或者直接看图。
- 正文字号取"多数字符使用的字号"。比正文大 1.25 倍以上的短行当作标题（`###` / `####`），这样 `document.md` 带有可导航的结构。
- `--tables`：用 PyMuPDF 的 `find_tables` 找表格，存成 CSV，并在原位置插入 Markdown 表格，同时把表格区域内的散乱文字块跳过，避免"项目金额(万元)负责人"这样拍平的行重复出现。
- `pages.jsonl` 记录每页类型、字数、图片覆盖率和渲染文件名，方便程序判断哪些页要额外处理。

坑：

- 多栏论文用 `sort=True` 时大体按阅读顺序输出，但跨栏的图注、页眉页脚仍可能插进正文。重要段落对照渲染图核对。
- 表格检测是启发式的：没有框线的表格可能检测不到，合并单元格会被拆开。数字要求精确时，看渲染图核对。
- 加密 PDF 先解密（需要密码时请用户自己操作），否则读出来是空的。
- 图表里的数字不在文字层里，`--render all` 之后看图，或者对相应区域 OCR。

## 图片：tile_image.py 和直接看

视觉模型会缩小大图（Claude 的长边超过约 1568 px 就会被缩小）。一张 1200×5000 的聊天长截图被缩小后，字就糊成一片了。

```bash
python ${CLAUDE_SKILL_DIR}/scripts/tile_image.py long.png --out tiles/                   # 切成 ≤1500 px、12% 重叠的块
python ${CLAUDE_SKILL_DIR}/scripts/tile_image.py poster.jpg --out tiles/ --max 1200 --overlap 0.2
python ${CLAUDE_SKILL_DIR}/scripts/tile_image.py photo.jpg --fit --out small.jpg         # 只是缩小到 ≤1568 px
```

按行顺序逐块读，`index.json` 记录了每块在原图中的位置，发现的问题可以映射回原图坐标。重叠区的内容会读到两次，汇总时去重。

什么时候 OCR、什么时候直接看：

| 内容 | 做法 |
|---|---|
| 大段文字、需要逐字引用 | OCR（`screen-and-ocr/scripts/ocr.py`），再抽查原图 |
| 图表、流程图、UI、手写、版式关系 | 直接看图（必要时先切块） |
| 表格 | 先 OCR 或 PDF 表格提取，再看图确认行列 |
| 照片里的场景、人物动作 | 直接看图 |

## Office 文件

`.docx` / `.pptx` / `.xlsx` 如果环境里有对应的专门 skill，就用它们。没有的话：python-docx / python-pptx / openpyxl 读结构；需要看版式时，先用 LibreOffice 转成 PDF（`soffice --headless --convert-to pdf`），再走上面的 PDF 流程。
