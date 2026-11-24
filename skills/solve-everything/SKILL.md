---
name: solve-everything
description: >-
  多模态任务的总入口与方法论：先把音频、视频、会议录像、屏幕录制、PDF、扫描件、截图、歌曲拆开，
  用代码转成带时间戳和置信度的结构化文本，再交给 LLM 对齐、纠错、理解和表达。Use this skill first
  whenever the user gives any non-text input (recording, video, meeting, lecture, podcast, interview,
  screen capture, scanned document, screenshot, song) and wants it transcribed, summarized, turned into
  minutes / notes / subtitles / a report, searched or analysed, or asks how to design a multimodal
  pipeline. 用户只要丢来音视频、录屏、扫描件、图片或歌曲，想要转写、总结、会议纪要、笔记、字幕、检索、
  分析，或者问"多模态该怎么做"，都先读这个 skill 规划流程，再进入对应的子 skill。
---

# Solve Everything：更好的输入，才有更好的输出

LLM 读不了声音，也常常看不清视频里的小字。但只要把每种模态先转成**带时间戳、带置信度的文本**，它就能把所有信息放在一起理解。这套 skill 的分工是：

- **代码负责感知**：信号 → 符号。ffmpeg 拆封装，Whisper / SenseVoice 转写，RapidOCR 读屏幕，librosa 听节奏。
- **LLM 负责理解**：对齐、纠错、判断重点、组织表达，以及决定下一步该再看哪里。

输入整理得越干净，输出就越好。大部分"模型总结得不好"，根子在输入：转写错了人名、漏了 PPT 上的数字、两个人的话被当成一个人说的。

## 五步法

| 步骤 | 做什么 | 子 skill |
|---|---|---|
| 1 拆 | 先 probe 再提取：音轨、帧、内嵌字幕、PDF 页面 | `media-ingest`、`docs-and-images` |
| 2 感知 | 每个模态转成文本 + 时间戳 + 置信度 | `speech-to-text`、`speaker-diarization`、`screen-and-ocr`、`music-and-sound`、`docs-and-images` |
| 3 对齐 | 合成一条时间线（JSONL 给程序，Markdown 给 LLM） | `timeline-fusion` |
| 4 核对 | 画成图看、跨模态互证、低置信度标出、候选打分、量化评测 | `visual-verify`、`quality-eval`、`speech-to-text`（score_candidates） |
| 5 表达 | 先定读者，再选重点，结论先行，写完反查 | `expressive-output` |

一条命令跑完会议场景的 1–4 步：`meeting-minutes`。

## 按输入选路线

| 用户给了 | 路线 | 关键产物 |
|---|---|---|
| 会议录像 / 录音 | `meeting-minutes`（内部串起其余 skill） | `timeline.md`、纪要 |
| 讲座、课程、带 PPT 的录屏 | media-ingest → speech-to-text → screen-and-ocr(slide_changes + ocr) → timeline-fusion → expressive-output | 分页笔记 |
| 播客、访谈、电话录音 | speech-to-text → speaker-diarization → timeline-fusion → expressive-output | 按人分段的稿子 |
| 带硬字幕的视频（MV、影视、短视频） | screen-and-ocr(burned_subs) | `subs.srt` + 时间 |
| 视频里有内嵌字幕轨 | media-ingest(probe 会提示) → extract subs | `.srt`，不用 OCR |
| PDF、扫描件、长截图、海报 | docs-and-images(pdf_extract / tile_image) + screen-and-ocr(ocr) | `document.md`、表格 CSV |
| 歌曲、MV 素材 | music-and-sound(beats / vocal_map) + visual-verify | 节拍、人声乐句、对轴图 |
| "效果到底怎么样" / 写论文 | quality-eval | CER、DER、关键信息召回 |

## 贯穿所有步骤的原则

1. **先看再做。** 任何音视频先跑 `media-ingest/scripts/probe.py`。多音轨、可变帧率、非零 start_time、旋转、内嵌字幕，这些问题一条 warning 就能提前发现，否则往往要返工一小时。
2. **每一步都落盘。** 中间文件（asr.jsonl、segments.json、timeline.jsonl）可检查、可重跑、可写进论文的方法部分。不要把整段流程塞进一次调用里。
3. **时间戳是主键。** 所有模态都对齐到"距文件开头的秒数"。偏移量（A/V 起点差、分段起点）在融合时统一加上。
4. **置信度一路带到底。** 低置信度的词在时间线里标成 `{词?}`，终稿里的人名、数字、日期如果来自低置信度片段，要么核实，要么标"存疑"。
5. **互证胜过猜测。** PPT 上的字可以纠正语音里的错字；两个 ASR 引擎结果不一致的地方，才值得人去听；拿不准的人名，让 LLM 列候选、让声学模型打分（`speech-to-text/scripts/score_candidates.py`）。
6. **能画成图就画成图。** 模型听不到声音，但看得到频谱、时间线、拼图。错位和漏检在图上一眼就能看出来（`visual-verify`）。
7. **不编造。** 原文没有的负责人、截止时间写"未明确"；推断出来的说话人身份要说明依据，或请用户确认。

## 运行环境

- Python ≥ 3.10，`ffmpeg` / `ffprobe` 在 PATH 上。全部脚本默认 CPU，无需 GPU。
- 按需安装：仓库根目录的 `requirements.txt` 列了各组依赖（asr / ocr / audio / docs）。
- 子 skill 的脚本位置：`${CLAUDE_SKILL_DIR}/../<子skill>/scripts/<脚本>.py`（作为插件安装或复制到同一个 skills 目录下时都成立）。
- 各 skill 之间交换的文件格式见 [references/schemas.md](references/schemas.md)。写新工具时沿用这些格式，就能直接接入时间线。

## 交付前自检

- 输入：probe 的 warning 是否都处理了？用的是哪条音轨？
- 感知：抽查 3 段转写对着原声听过吗？幻灯片切页数和实际一致吗？
- 对齐：时间线图上说话人条、页面条、置信度条对得上吗？
- 表达：读者是谁？第一句是不是结论？每条决定/待办有没有时间戳依据？`coverage_check.py` 过了吗？
