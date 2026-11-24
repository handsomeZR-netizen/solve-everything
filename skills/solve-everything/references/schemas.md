# 共享数据格式

所有时间单位都是**秒**，从媒体文件开头算起（浮点，保留 2 位）。文本一律 UTF-8。示例取自 `examples/short-video`。

## ledger.json（input-audit/inventory.py）

```json
{"inputs": [{"file": "inputs/deck.pptx", "type": "office", "size_mb": 0.03,
  "units": {"slides": 2}, "parts": {"speaker_notes": 1, "hidden_slides": 1, "embedded_media": 0},
  "risks": [{"code": "speaker_notes", "severity": "high", "detail": "1 slide(s) carry speaker notes ..."}],
  "route": ["docs-and-images"], "status": "pending"}]}
```

`type` ∈ `video | audio | pdf | image | office | text | subtitle | archive | other`；`severity` ∈ `high | warn | info`。

## coverage.json（input-audit/coverage.py）

```json
{"items": [
  {"input": "clip.mp4", "kind": "audio", "coverage": 1.0,
   "measures": {"speech": {"active_s": 32.7, "covered_s": 32.7, "coverage": 1.0, "gaps": []},
                "sound":  {"active_s": 45.3, "covered_s": 36.5, "coverage": 0.81, "gaps": [[1.0, 2.2]]}},
   "orphan_text": [], "flagged": []},
  {"input": "clip.mp4", "kind": "video", "coverage": 1.0,
   "strategies": {"screen states | uniform 16 frames": {"seen": 6, "of": 7, "frames": 16}}},
  {"input": "report.pdf", "kind": "pdf", "pages": 2, "never_read": [], "coverage": 1.0},
  {"input": "long_screenshot.png", "kind": "image", "direct_scale": 0.314, "tiled_scale": 1.0, "coverage": 1.0},
  {"input": "deck.pptx", "kind": "office", "checked": [["speaker_notes", 1, 1]], "coverage": 1.0}]}
```

## asr.jsonl（speech-to-text/transcribe.py）

一行一句（长片段会按句末标点切开）：

```json
{"start": 13.12, "end": 18.9, "text": "第一步，先盘点输入，视频多长，有几条音柜，PDF有几页。",
 "avg_logprob": -0.21, "no_speech_prob": 0.01, "compression_ratio": 1.3,
 "words": [[13.12, 13.5, "第一", 0.98], [16.2, 16.6, "音柜", 0.41]],
 "flags": []}
```

`flags` 可能取值：`hallucination?`、`repetition`、`low_confidence`、`maybe_silence`（强幻觉默认已删除）。
旁边的 `asr.jsonl.meta.json` 记录模型、全部解码参数、耗时和 RTF。

## RTTM（speaker-diarization 的输入/输出）

标准 NIST 格式，一行一段：

```
SPEAKER <file> 1 <start> <duration> <NA> <NA> <speaker> <NA> <NA>
```

`merge_speakers.py` 也接受 JSON / JSONL：`{"start": 1.0, "end": 3.2, "speaker": "SPK_0"}`。

## turns.jsonl（speaker-diarization/merge_speakers.py）

```json
{"start": 27.69, "end": 34.32, "speaker": "嘉宾", "text": "……", "conf": 0.97, "n_words": 18,
 "overlap": false, "words": [[27.69, 27.99, "我", 0.97]]}
```

## segments.json（screen-and-ocr/slide_changes.py；ocr.py --segments 会补上 ocr 字段）

```json
[{"i": 1, "kind": "static", "start": 13.0, "end": 20.0, "rep_t": 19.5, "group": 1,
  "build": false, "complete": true, "file": "slide_001.png",
  "ocr": "第1步·盘点\n·时长·音轨·帧率", "ocr_lines": [{"text": "...", "score": 0.98, "box": [80, 90, 520, 150]}]},
 {"i": 2, "kind": "flash", "start": 20.0, "end": 21.0, "rep_t": 20.25, "file": "flash_002.png", "ocr": "评论区口令\nSE-0618"},
 {"i": 9, "kind": "dynamic", "start": 60.0, "end": 75.5, "samples": [{"t": 63.0, "file": "dyn_009_000630.png"}]}]
```

- `group` 相同的是同一页的逐条动画（build），`complete: true` 的那一帧内容最全。
- `flash` 是转场中只停留了不到 `--settle` 秒的画面（闪现的卡片、弹窗），它有自己的截图和 OCR。
- `dynamic` 是滚动、播放等持续变化的画面，附有样张。

## subs.json（screen-and-ocr/burned_subs.py）

```json
[{"i": 0, "start": 2.0, "end": 6.3, "text": "你把一段视频丢给大模型，它真的看完了吗？", "score": 0.97, "file": "sub_000.png"}]
```

## timeline.jsonl（timeline-fusion/fuse.py）

```json
{"t0": 13.12, "t1": 18.9, "src": "asr", "spk": null, "text": "……", "conf": 0.93, "words": [...]}
{"t0": 13.0, "t1": 20.0, "src": "slide", "text": "第1步·盘点\n...", "ref": "slide_001.png", "group": 1}
{"t0": 20.0, "t1": 21.0, "src": "flash", "text": "评论区口令\nSE-0618", "ref": "flash_002.png"}
{"t0": 13.4, "t1": 19.4, "src": "sub", "text": "第一步，先盘点输入：……", "xcheck": [["轨", "柜"]]}
{"t0": 50.2, "t1": 51.0, "src": "event", "text": "笑声"}
{"t0": 60.0, "t1": 60.0, "src": "note", "text": "评论区置顶：链接在简介"}
```

`src` ∈ `asr | slide | flash | sub | event | note`。`xcheck` 是字幕和同一时段语音的不一致之处，格式为
`[字幕里的字, 语音里的字]`，空字符串表示那一边没有。

## timeline.md（给 LLM 读的版本）

```markdown
## [00:13–00:20] 第2页 · 第1步·盘点
> 屏幕文字：第1步·盘点 / ·时长·音轨·帧率 / ·页数·扫描页·隐藏内容

- [00:13] 第一步，先盘点输入，视频多长，有几条音柜，PDF有几页。
- [00:13] 〔字幕〕第一步，先盘点输入：视频多长，有几条音轨，PDF有几页。
  - ⚠ 字幕/语音不一致（字幕在前，语音在后）：「轨」/「柜」
- [00:20] **〔屏幕闪现 1.0s〕评论区口令 / SE-0618** (flash_002.png)
```

`{…?}` 是低置信度的词。

## facts.json（expressive-output 的"先抽取"产物）

```json
[{"id": "H1", "kind": "hidden", "text": "评论区口令 SE-0618（屏幕闪现 1 秒）",
  "must": ["SE-0618"], "ref": "clip.mp4 00:20"}]
```

`kind` 建议取值：`decision | action | hidden | conflict | number | risk | context`。`must` 是成稿里必须出现的字符串。
比对前会做归一化：全角半角统一、去掉 Markdown 强调符、12月1号=12月1日、4万8=4.8万、毫秒=ms、这周=本周。
