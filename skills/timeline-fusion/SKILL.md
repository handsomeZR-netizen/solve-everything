---
name: timeline-fusion
description: >-
  Fuse every modality into one timeline: speech (with or without speakers), on-screen states and OCR,
  one-second flash cards, burned-in subtitles, sound events (laughter, applause, emotion), chat logs or
  notes, all on one clock with offsets applied; automatically cross-check subtitles against speech and mark
  every disagreement; write timeline.jsonl for code and a sectioned timeline.md (one section per screen,
  low-confidence words marked) that an LLM can read end to end. Use after speech-to-text / screen-and-ocr
  and before writing any summary, notes, breakdown, analysis or handoff of a recording.
  多模态对齐、合并语音和画面、字幕和语音互证、时间线、给 LLM 准备输入，都用这个。
---

# timeline-fusion：所有东西放到一条时间线上，再互相核对

LLM 应该读到的是一份"带页码的逐字稿"：每个画面上写了什么、这段时间里说了什么、哪里一闪而过了什么、哪个字没听清、哪里字幕和声音对不上。

```bash
python ${CLAUDE_SKILL_DIR}/scripts/fuse.py --asr asr.jsonl|turns.jsonl --slides slides/segments.json \
    [--subs subs/subs.json] [--events sv.jsonl] [--notes chat.jsonl] \
    [--shift-asr 0] [--shift-video -0.4] --out timeline.jsonl --md timeline.md --title "标题" [--lang zh|en]
```

## 输出

`timeline.md` 长这样（真实输出，来自 `examples/short-video`）：

```markdown
- 字幕与语音不一致：7 处（逐条标在字幕下方；至少有一边是错的，以原片为准）

## [00:13–00:20] 第2页 · 第1步·盘点
> 屏幕文字：第1步·盘点 / ·时长·音轨·顿率 / ·页数·扫描页·隐藏内容 / 2/5

- [00:13] 第一步，先盘点输入，视频多长，有几条音柜，PDF有几页。
- [00:13] 〔字幕〕第一步，先盘点输入：视频多长，有几条音轨，PDF有几页。
  - ⚠ 字幕/语音不一致（字幕在前，语音在后）：「轨」/「柜」
- [00:20] **〔屏幕闪现 1.0s〕评论区口令 / SE-0618** (flash_002.png)

## [00:32–00:40] 第4页 · 第3步·对账
- [00:32] 第三步，对账，哪些画面，哪些页，哪些片段没被处理。
- [00:32] 〔字幕〕第三步，对账：哪些画面、哪些页、哪些片段被处理，列成清单。
  - ⚠ 字幕/语音不一致（字幕在前，语音在后）：「∅」/「没」
```

上面这一段里同时有三种错误：语音识别把「音轨」听成「音柜」，屏幕 OCR 把「帧率」认成「顿率」，字幕 OCR 漏掉了一个「没」，意思正好反了。单看任何一路来源都发现不了，放在一起就一目了然。

- **分节**：有画面状态就按画面分节（同一页的逐条动画合成一节，标题取 OCR 的第一行）；没有就每 `--section` 秒（默认 5 分钟）一节。各节首尾相接，两页之间的内容（闪现、停顿）归到前一节，不会漏掉。
- **闪现**：只停留约一秒的画面单独成行，加粗并附截图文件名。这类内容往往口播里没有。
- **互证**：每句字幕都会和同一时段（±3 秒窗口，再裁到真正匹配的那一段）的语音逐字比对，所有不一致都写在字幕下面。比对时只看字母和数字，标点差异不算。
- **低置信度**：概率低于 `--low`（默认 0.45）的连续词用 `{…?}` 包起来。
- **事件**：SenseVoice 给出的笑声、掌声、非中性情绪，挂在重叠的那句话后面，写成"（笑声）"。
- 文件头写有时长、各来源的条数、发言时长（有说话人时）和不一致的总数。

`timeline.jsonl` 是同样内容的结构化版本，格式见 `solve-everything/references/schemas.md`。

## 原则和坑

- **同一个时钟**：所有来源都换算成"距文件开头的秒数"。`input-audit` 或 `media-ingest` 报告了 A/V 偏移时，用 `--shift-video` 或 `--shift-asr` 补偿。
- **融合时不丢信息**：低置信度、标记、来源、互证结果都保留下来。删减是写作阶段的事，而且要有意识地删。
- **互证不是投票**：两路来源不一致时，脚本不判断谁对。以原片为准（听一下、看截图），或者用 `speech-to-text/scripts/score_candidates.py` 让音频裁决。
- **重复内容**：有字幕时，同一句话会以"语音"和"字幕"各出现一次。这是故意的：读者需要看到两边才能判断。
- **屏幕文字太长**：每节只放前 400 字，全文看 `segments.json` 里的 `ocr` 字段或截图。
- **其他带时间的信息**：评论区、弹幕、聊天记录、手写笔记，只要有时间，就做成 `{"start", "end", "text"}` 的 JSONL，用 `--notes` 加进来。
- **超长内容**：timeline.md 一次读不完时，按节分批读，每批先抽取要点，最后汇总。汇总时，要把要点和对应的原文段落一起交给模型，不要只给要点。
