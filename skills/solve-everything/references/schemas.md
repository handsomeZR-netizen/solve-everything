# 共享数据格式

所有时间单位都是**秒**，从媒体文件开头算起（浮点，保留 2 位）。文本一律 UTF-8。

## asr.jsonl（speech-to-text/transcribe.py）

一行一个片段：

```json
{"start": 12.34, "end": 15.6, "text": "现在接口的P99是800毫秒。",
 "avg_logprob": -0.21, "no_speech_prob": 0.01, "compression_ratio": 1.3,
 "words": [[12.34, 12.6, "现在", 0.98], [12.6, 12.9, "接口", 0.95]],
 "flags": ["low_confidence"]}
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
{"start": 27.69, "end": 34.32, "speaker": "李工", "text": "我12月5号之前出压测报告。",
 "conf": 0.97, "n_words": 18, "overlap": false, "words": [[27.69, 27.99, "我", 0.97], ...]}
```

## segments.json（screen-and-ocr/slide_changes.py，ocr.py --segments 会补 ocr 字段）

```json
[{"i": 0, "kind": "static", "start": 0.0, "end": 14.0, "rep_t": 13.5, "group": 0,
  "build": false, "complete": true, "file": "slide_000.png",
  "ocr": "接口性能\n当前 P99：800 ms", "ocr_lines": [{"text": "...", "score": 0.98, "box": [x0, y0, x1, y1]}]},
 {"i": 1, "kind": "dynamic", "start": 14.0, "end": 30.5, "samples": [{"t": 17.0, "file": "dyn_001_000170.png"}]}]
```

`group` 相同的是同一页的逐条动画（build），`complete: true` 的那一帧内容最全。

## subs.json（screen-and-ocr/burned_subs.py）

```json
[{"i": 0, "start": 1.0, "end": 8.7, "text": "好，我们开始。", "score": 0.97, "file": "sub_000.png"}]
```

## timeline.jsonl（timeline-fusion/fuse.py）

```json
{"t0": 35.76, "t1": 44.36, "src": "asr", "spk": "王总", "text": "...", "conf": 0.98, "words": [...]}
{"t0": 14.5, "t1": 48.5, "src": "slide", "text": "接口性能\n...", "ref": "slide_001.png", "group": 1}
{"t0": 50.2, "t1": 51.0, "src": "event", "text": "笑声"}
{"t0": 60.0, "t1": 60.0, "src": "note", "text": "聊天区：链接已发群里"}
```

`src` ∈ `asr | slide | sub | event | note`。

## timeline.md（给 LLM 读的版本）

```markdown
## [00:14–00:48] 第2页 · 接口性能
> 屏幕文字：接口性能 / 当前 P99：800 ms / 目标 P99：≤ 300 ms

- [00:14] 李工：现在接口的P99是800毫秒……
- [00:48] 李工：……大概{4?}万8。     ← {…?} 是低置信度词
```

## facts.json（expressive-output 的"先抽取"产物）

```json
[{"id": "A1", "kind": "action", "text": "李工 12月5日前出压测报告",
  "must": ["李工", "压测报告", "12月5"], "ref": "00:27"}]
```

`kind` 建议取值：`decision | action | open | number | risk | context`。`must` 是成稿里必须出现的字符串（比对前会做归一化：全半角、12月1号=12月1日、4万8=4.8万、毫秒=ms）。
