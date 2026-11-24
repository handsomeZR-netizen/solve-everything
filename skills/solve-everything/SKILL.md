---
name: solve-everything
description: >-
  Entry point and method for any task whose input is not plain text, or is too big to trust a single
  read: recordings, videos, short videos, screen captures, livestream replays, PDFs, scans, screenshots,
  slide decks, spreadsheets, folders of mixed files, songs, or another agent's output. First inventory
  the input, then turn every modality into timestamped, confidence-scored text with code, cross-check the
  modalities against each other, measure coverage, and only then let the LLM understand and write, with a
  coverage statement attached. Use it before summarising, answering questions about, comparing, analysing
  or handing off such input. 只要输入是音视频、短视频、录屏、PDF、扫描件、截图、PPT、表格、混合文件夹、歌曲或别的
  agent 的结果，或者你怀疑模型没看全，都先读这个 skill，再进入对应的子 skill。
---

# Solve Everything：先榨干输入，再要求输出

## 核心问题：LLM 真的处理完你的输入了吗？

模型的回答质量，上限是它**实际读到**的输入。问题在于，模型读漏了往往不会告诉你：

- 视频只抽了十几帧，一闪而过的口令、价格、某一页 PPT 根本没被采到；
- PDF 的扫描页没有文字层，在模型眼里就是一张白纸；
- 长截图被缩小到原来的三分之一，最后一行的关键信息糊成一片；
- PPT 的演讲备注、隐藏页，Word 的批注，Excel 的隐藏工作表，都不在"正文"里；
- 上游 agent 交过来的是一份摘要，摘要漏了什么，下游完全不知道。

这套 skill 的做法是：**代码负责把每种模态完整、可核对地转成文字，LLM 负责理解和表达，中间用一本账把"处理完了没有"算清楚。**

## 六步

| 步骤 | 做什么 | 子 skill |
|---|---|---|
| 0 盘点 | 输入一共有多少？快速读取会丢掉什么？ | `input-audit`（inventory） |
| 1 拆 | 抽音轨、帧、内嵌字幕；PDF 分页；Office 解包；大图切块 | `media-ingest`、`docs-and-images` |
| 2 感知 | 每种模态都转成"文字 + 时间戳/页码 + 置信度" | `speech-to-text`、`speaker-diarization`、`screen-and-ocr`、`music-and-sound`、`docs-and-images` |
| 3 对齐互证 | 合成一条时间线；字幕对语音、屏幕对口播、表格对表格 | `timeline-fusion`、`visual-verify` |
| 4 对账 | 覆盖率达标才往下走；列出缺口 | `input-audit`（coverage）、`quality-eval` |
| 5 表达 | 先定读者，再按"什么变了"选重点；结论先行；带覆盖声明；写完反查 | `expressive-output` |

音视频一条命令跑完第 0–4 步：`media-pipeline`。

## 按输入选路线

| 输入 | 路线 |
|---|---|
| 短视频、讲座、教程、直播回放、录屏 | `media-pipeline`（自动包含盘点、转写、画面变化、OCR、时间线、对账） |
| 播客、访谈、多人对话 | `media-pipeline --speakers N`，或者分步：speech-to-text → speaker-diarization |
| MV、带硬字幕的视频 | `media-pipeline --subs-crop ... --music [--no-vad]` |
| PDF、扫描件 | `docs-and-images/pdf_extract.py` → 扫描页用 `screen-and-ocr/ocr.py` |
| PPT、Word、Excel | `docs-and-images/office_extract.py`（备注、隐藏页、批注、隐藏表都会提取） |
| 长截图、海报、大图 | `docs-and-images/tile_image.py`，然后逐块看或 OCR |
| 一个混合文件夹 | 先跑 `input-audit/inventory.py`，按每个文件的推荐路线处理，最后跑 `coverage.py summary` |
| 别的 agent 交来的结果 | 先看覆盖声明；没有的话按"未验证"对待，关键结论回原文核对 |
| 要量化效果、写论文 | `quality-eval` |

## 贯穿始终的原则

1. **先盘点再动手。** 不知道总量，就不可能知道漏了多少。
2. **每一步都落盘。** 中间文件可以检查、可以重跑，也可以交给下一个 agent。
3. **时间戳和页码是主键。** 所有结论都能指回原文的某一秒、某一页。
4. **置信度一路带到底。** 低置信度的内容，要么核实，要么在终稿里标"存疑"。
5. **互证胜过猜测。** 字幕对语音、PPT 对口播、汇总表对原始表；两路来源不一致的地方，至少有一路是错的。
6. **能画成图就画成图。** 模型听不到声音，但看得到时间线图和拼图。
7. **覆盖率不达标，不下结论。** 处理不了的部分，在回答里明确写出来。
8. **不编造。** 原文没有的东西写"未明确"。

## 运行环境

- Python ≥ 3.10，PATH 上有 `ffmpeg` / `ffprobe`。默认全部在 CPU 上跑，不需要 GPU。
- 依赖按需安装：仓库根目录的 `requirements.txt` 按 skill 分了组。
- 子 skill 的脚本位置：`${CLAUDE_SKILL_DIR}/../<子skill>/scripts/<脚本>.py`。
- 各 skill 之间交换的文件格式见 [references/schemas.md](references/schemas.md)。新写的工具沿用这些格式，就能直接接进时间线和对账。

## 交付前自检

- 盘点：`ledger.md` 里的高危项都处理了吗？
- 对账：`coverage.md` 全部 OK 吗？没处理的部分写进回答了吗？
- 互证：`⚠` 标出的不一致都核实了吗？
- 表达：第一句是结论吗？每条关键信息都有时间戳或页码吗？`coverage_check.py` 通过了吗？
