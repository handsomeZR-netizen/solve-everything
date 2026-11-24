---
name: timeline-fusion
description: >-
  Fuse every modality into one timeline: speaker turns, on-screen slide text, burned-in subtitles,
  sound events (laughter, applause, emotion), chat logs or manual notes, all aligned to the same
  clock with offsets applied, written as timeline.jsonl for code and as a sectioned timeline.md
  (one section per slide, low-confidence words marked) that an LLM can read end to end. Use after
  speech-to-text / speaker-diarization / screen-and-ocr and before writing any summary, minutes,
  notes or analysis of a recording. 多模态对齐、合并语音和 PPT、时间线、给 LLM 准备输入，都用这个。
---

# timeline-fusion：把所有东西放到一条时间线上

LLM 看到的东西应该像一份"带页码的逐字稿"：每页 PPT 上写了什么，这段时间里谁说了什么，哪里有笑声，哪个词没听清。有了这样的输入，总结的质量会稳定很多。

```bash
python ${CLAUDE_SKILL_DIR}/scripts/fuse.py --asr turns.jsonl --slides slides/segments.json \
    [--subs subs/subs.json] [--events sv.jsonl] [--notes chat.jsonl] \
    [--shift-asr 0] [--shift-video -0.4] --out timeline.jsonl --md timeline.md --title "北极星周会" [--lang zh|en]
```

## 输出

`timeline.md` 长这样（真实输出，来自合成演示）：

```markdown
## [00:14–00:48] 第2页 · 接口性能
> 屏幕文字：接口性能 / 当前 P99：800 ms / 目标 P99：≤ 300 ms / 压测报告：12/5 前

- [00:14] 李工：现在接口的P99是800毫秒，目标是300毫秒以内。按现在的进度，12月1号肯定来不及。
- [00:24] 王总：那最晚什么时候能好？
- [00:27] 李工：我12月5号之前出压测报告。如果顺利，12月15号可以上线。
...
- [00:48] 李工：另外，压测还需要再加两台服务器，大概{4?}万8。
```

- **分节**：有幻灯片就按页分节（同一页的逐条动画合成一节，标题取 OCR 第一行）；没有就每 `--section` 秒（默认 5 分钟）一节。`dynamic` 段（滚动、播放）单独成节，并列出样张。
- **归属**：每句话按"中点落在哪一节"归属，不会重复出现，也不会丢失。
- **低置信度**：概率低于 `--low`（默认 0.45）的连续词用 `{…?}` 包起来。这是给 LLM 和人看的"这里要小心"的信号。
- **事件**：SenseVoice 给出的笑声、掌声和非中性情绪，挂到重叠的那句话后面，写成"（笑声）"。
- **标记**：ASR 的 flags 写成 `[!repetition]` 之类。
- 文件头写有时长、各来源条数、每人发言时长。

`timeline.jsonl` 是同样内容的结构化版本（格式见 `solve-everything/references/schemas.md`），给 `visual-verify/scripts/timeline_plot.py` 和你自己的程序用。

## 原则和坑

- **同一个时钟**：所有来源都换算成"距文件开头的秒数"。`media-ingest/scripts/probe.py` 报告了 A/V 偏移时，用 `--shift-video` 或 `--shift-asr` 补偿；分段转写时别忘了加上每段的起点偏移。
- **不要在融合时丢信息**：低置信度、标记、来源都保留下来。删减是写作阶段的事，而且是有意识的删减。
- **重复内容**：重叠切块的 ASR 在 `transcribe.py` 里已按"重叠区只归一个块"去重。如果你自己合并多个来源（比如两条音轨），按时间重叠加文本相似度去重。
- **屏幕文字太长**：每节只放前 400 字。需要全文时看 `segments.json` 里的 `ocr`，或者直接看截图。
- **额外的时间信息**：聊天记录、议程、手写笔记，只要有时间，就做成 `{"start", "end", "text"}` 的 JSONL，用 `--notes` 加进来。会议里"链接发群里了"这类信息常常只在聊天区。
- **超长会议**：timeline.md 太长、一次读不完时，按节分批读，每批先写分节摘要，最后汇总。汇总时，要把分节摘要和对应的原文段落一起给模型，不要只给摘要（见 `expressive-output`）。
