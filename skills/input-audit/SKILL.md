---
name: input-audit
description: >-
  Answer the question most pipelines skip: did the model actually process ALL of the input? Inventory
  every input before reading it (seconds, frames, tracks, pages, scanned pages, slides, speaker notes,
  hidden slides and sheets, comments, tracked changes, embedded images, pixels vs the vision limit,
  characters vs the context budget), then measure coverage after processing (speech without transcript,
  transcript without sound, on-screen states a sampling strategy would miss, PDF pages never read,
  effective image resolution, Office parts extracted) and refuse to conclude below threshold. Use for any
  agent task that consumes files, recordings, folders, screenshots or another agent's output, before
  summarising, answering questions, comparing documents or handing work to another agent. 输入审计、
  有没有看全、漏没漏、覆盖率、处理完了吗、交接给下一个 agent、多 agent 协作，都先用这个。
---

# input-audit：LLM 真的处理完你的输入了吗？

模型几乎从不说"我没看第 37 页"。它会根据看到的那部分，给出一个流畅、自信、看起来很完整的回答。
被漏掉的往往不是噪声，而是最关键的那一条：只闪现一秒的口令、扫描页上的结论、演讲备注里的真实决定、隐藏工作表里对不上的数字。

这个 skill 只做一件事：**把"处理完了"从一种感觉变成一个数字**。

## 输入是怎么被悄悄丢掉的

| 输入 | 常见的丢法 | 本仓库怎么查、怎么补 |
|---|---|---|
| 视频 | 只抽固定数量的帧或固定帧率；一闪而过的卡片、价格、口令、某一页 PPT 根本没被采到 | `inventory.py` 估算抽帧间隔；`coverage.py video` 计算各种抽帧方式能看到几个画面状态；`screen-and-ocr/slide_changes.py` 按画面变化截图，闪现也单独截 |
| 音频 | 只听第一条音轨；VAD 把轻声、唱歌当静音；幻觉过滤误删真话；音乐段没有文字 | `coverage.py audio`：有声音却没文字的片段、没声音却有文字的片段（疑似幻觉） |
| 图片 | 长边超过视觉上限（Claude 约 1568 px）被缩小；长截图的小字糊掉；动图只看到一帧 | `inventory.py` 算缩放倍数；`docs-and-images/tile_image.py` 切块；`coverage.py image` |
| PDF | 扫描页没有文字层；图表里的数字不在文字层；多栏错序；超长被截断 | `inventory.py` 找扫描页；`docs-and-images/pdf_extract.py` + OCR；`coverage.py pdf` |
| Office | 演讲备注、隐藏页、批注、修订、隐藏工作表、页眉页脚、脚注、嵌入图片 | `inventory.py` 逐项计数；`docs-and-images/office_extract.py` 全量解包；`coverage.py office` |
| 文本 | 超出上下文被截断；长文"中间丢失"；编码不对变乱码 | `inventory.py` 对照上下文预算、检测编码；分块阅读并记录读过哪些块 |
| 压缩包 | 根本没解压 | `inventory.py` 提示先解压，解压后重新盘点 |
| 工具输出 | 命令输出超长被截断；分页结果只取了第一页 | 输出落盘再分段读；分页逐页取，并记录总页数 |
| 上游 agent | 拿摘要当原文，下游无从得知上游漏了什么 | 交接时必须附带盘点账和覆盖账（见下） |

## 三本账

1. **盘点账**（处理前）：输入一共有多少，以及快速读取会丢掉什么。

   ```bash
   python ${CLAUDE_SKILL_DIR}/scripts/inventory.py inputs/ --out ledger.json --md ledger.md \
       [--vision-max 1568] [--uniform-frames 16 32] [--context-chars 200000]
   ```

   给每个文件列出：总量（秒、帧、页、张、工作表、字符）、风险（高危的会加粗）、建议的处理路线。

2. **处理账**（处理中）：每一步都落成带时间戳或页码的中间文件，比如 `asr.jsonl`、`segments.json`、`pages.jsonl`、`office/*.md`、`tiles/index.json`。

3. **对账**（处理后）：拿中间文件对照真实输入，算出覆盖率，列出缺口。

   ```bash
   python ${CLAUDE_SKILL_DIR}/scripts/coverage.py audio  --media clip.mp4 --asr asr.jsonl --cov coverage.json
   python ${CLAUDE_SKILL_DIR}/scripts/coverage.py video  --segments slides/segments.json [--subs subs/subs.json] --cov coverage.json
   python ${CLAUDE_SKILL_DIR}/scripts/coverage.py pdf    --pages report/pages.jsonl --ocr ocr.json --cov coverage.json
   python ${CLAUDE_SKILL_DIR}/scripts/coverage.py image  --image long.png --tiles tiles/index.json --cov coverage.json
   python ${CLAUDE_SKILL_DIR}/scripts/coverage.py office --ledger ledger.json --found office/deck.pptx.found.json --cov coverage.json
   python ${CLAUDE_SKILL_DIR}/scripts/coverage.py summary --cov coverage.json --md coverage.md --min 0.98   # 低于阈值时退出码为 1
   ```

**覆盖率低于阈值，就不下结论。** 先处理缺口；处理不了的，在回答里明确写出来。

## 每个回答都带一句覆盖声明

> 已处理：视频 50 秒（语音 33/33 秒，画面 7/7 个状态）、PDF 2/2 页（第 2 页为扫描件，已 OCR）、长截图按 4 块读取、PPT 2/2 页及 1 条演讲备注、Excel 2/2 个工作表（含 1 个隐藏表）。
> 未处理：notes.docx 里的 1 张嵌入图片。
> 存疑：口播和字幕有 7 处不一致，已对照原片改正。

这句话的成本很低，却能让读者（人或者下一个 agent）知道这个回答**能信到什么程度**。

## 多 agent 协作协议

- **交出结果时**：附上 `ledger.md`、`coverage.md` 和存疑清单。模板见 `expressive-output/references/templates.md` 里的"Agent 交接单"。
- **接收结果时**：先看对方的覆盖声明。没有覆盖声明的摘要，一律按"未验证"对待；关键结论要回到原文的时间戳或页码核对。
- **分工切块时**：每块都记下自己负责的范围（第几秒到第几秒、第几页到第几页）。汇总前，检查所有块的并集是否覆盖了全部输入。
- **不要用"摘要的摘要"代替原文**：汇总时遇到矛盾，回到原文看，而不是在两份摘要之间挑一个。

## 实测（`examples/short-video`：一个文件夹，6 个文件，全部合成）

| 快速读取的方式 | 漏掉了什么 | 完整处理后 |
|---|---|---|
| 视频均匀抽 8 帧 / 16 帧 | 2 条只闪现 1 秒的信息，分别看到 0/2、1/2 | 画面变化检测只截 7 张图，7/7 个画面状态全部拿到 |
| 只读 PDF 文字层 | 第 2 页（扫描件）的结论和预算上限，覆盖率 50% | OCR 后 2/2 页 |
| 长截图直接看 | 整图缩到 0.31 倍，最后一行的交付时间看不清 | 切成 4 块，每块按 1.0 倍读 |
| 只读幻灯片正文 | 演讲备注里"已决定选 B"、隐藏页里"供应商可能延期两周" | 3/3 项 |
| 只读 Word 正文 | 批注"这一条要改，先别发" | 1/1 |
| 只读第一张工作表 | 隐藏表里的 130，和汇总表的 100 互相矛盾 | 2/2 个工作表 |

8 条关键信息，快速读取最多只能拿到其中 1 条；完整处理后，6 个输入的覆盖率全部达到 100%。

## 注意

- **覆盖率 100% 不等于全对**：它只说明每一部分都被处理过。识别错误要靠跨模态互证（`timeline-fusion` 会自动比对字幕和语音）和量化评测（`quality-eval`）。
- **`sound` 和 `speech` 两个指标**：`speech` 用的是 Silero VAD，和转写用的是同一个检测器；`sound` 是独立的能量检测，音乐和噪声也算在内。`sound` 的缺口要么是音乐，要么是漏转写，需要逐个确认（听一下，或者看 SenseVoice 给出的事件标签）。
- **`--vision-max`**：默认的 1568 是 Claude 的数值，其他模型请改成对应的上限。
- **抽帧估算是一个模型**：它描述的是"均匀抽 N 帧"这种策略的后果，不代表任何具体产品的实际行为。
