---
name: docs-and-images
description: >-
  Get everything out of documents and still images, including the parts a normal read skips: PDF text
  with headings and tables (Markdown + CSV), scanned / image-only pages detected and rendered for OCR,
  PowerPoint speaker notes and hidden slides, Word comments, tracked changes, headers, footnotes and
  embedded images, Excel hidden and very-hidden sheets, and tiling of long screenshots, posters and
  dashboards so small print survives a vision model's downscaling. Use whenever the input is a PDF, scan,
  .pptx, .docx, .xlsx, long screenshot, poster, infographic or any image with text that must be read,
  summarised, compared or quoted accurately. PDF、扫描件、PPT 备注、隐藏页、批注、隐藏表、长截图、小字，都用这个。
---

# docs-and-images：文档和图片，连藏着的一起读

文档类输入出错，通常不是因为模型理解不了，而是**它拿到的东西就是残缺的**：表格被拍平成一串文字，扫描页根本没有文字层，长截图被缩到看不清，演讲备注、批注、隐藏工作表压根没被读出来。

## Office：office_extract.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/office_extract.py deck.pptx notes.docx data.xlsx --out-dir office/
```

只用标准库（zip + XML），任何环境都能跑。每个文件输出一份 `.md`（给模型读）和一份 `.found.json`（交给 `input-audit/scripts/coverage.py office` 对账）：

| 格式 | 除了正文，还会提取 |
|---|---|
| `.pptx` | 按放映顺序排列的所有页（隐藏页会标出）、**演讲备注**、图表数值、图片数量 |
| `.docx` | 页眉页脚、脚注、**批注（带作者）**、**修订（插入/删除）**、嵌入图片数量 |
| `.xlsx` | **所有工作表，包括 hidden / veryHidden 的**、单元格值（默认前 200 行）、公式数量 |

实测（`examples/short-video`）：演讲备注里的"其实已经决定选 B"、隐藏页上的"供应商可能延期两周"、批注"这一条要改，先别发"、隐藏表里和汇总表对不上的 130，全部提取了出来。这些内容按常规方式读取全都看不到：只读幻灯片正文、只读 Word 正文、默认只读第一张工作表。

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

## Office 的版式和图片

`office_extract.py` 取出的是文字和结构。版式、图表的样子、嵌入图片的内容，要先用 LibreOffice 转成 PDF（`soffice --headless --convert-to pdf`），再走上面的 PDF 流程（`--render all`）去看图。环境里如果有专门处理 docx / pptx / xlsx 的 skill，修改文件时用它们。
