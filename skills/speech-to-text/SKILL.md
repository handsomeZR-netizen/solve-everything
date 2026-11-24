---
name: speech-to-text
description: >-
  Turn speech into timestamped, confidence-scored text that is good enough to build minutes, subtitles
  or analysis on: faster-whisper with tuned defaults for Chinese (simplified output, punctuation,
  hallucination filtering, repetition-loop guards, hotwords, VAD or overlapped chunking), SenseVoice ONNX
  as a fast second opinion with emotion and laughter/applause tags, and forced-alignment scoring that
  lets the audio decide between candidate spellings of names, terms and numbers. Use whenever audio has
  to become text: meetings, lectures, interviews, podcasts, voice memos, video dialogue, song lyrics, and
  whenever a transcript has wrong names, traditional characters, made-up sentences or repeated lines.
  语音转文字、转写、字幕、ASR、识别不准、人名识别错、繁体、幻觉、重复，都用这个。
---

# speech-to-text：把声音变成可信的文字

目标不是"有文字"，而是**带时间戳、带置信度、关键信息可核实**的文字。纪要里错一个人名或数字，比错十个虚词严重得多。

## 选引擎

| 引擎 | 强项 | 弱项 | 本仓库 |
|---|---|---|---|
| faster-whisper large-v3-turbo | 中英混说、标点、逐词时间戳、稳 | 静音处会编句子；CPU 上 RTF 约 0.6–1.8 | `transcribe.py`（主力） |
| SenseVoice-Small (ONNX) | 很快；带情绪、笑声/掌声等事件标签 | 基础版没有时间戳 | `sensevoice_onnx.py`（第二意见） |
| FunASR Paraformer-zh | 中文会议最强之一；VAD+标点+逐字时间戳+说话人一条龙；热词 | 中英混说较弱；模型从 ModelScope 下载 | 见 [references/engines.md](references/engines.md) |

默认：Whisper 出主稿，SenseVoice 交叉核对，拿不准的地方用候选打分裁决。

## 主稿：transcribe.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/transcribe.py audio.wav --out asr.jsonl \
    --hotwords "北极星 P99 压测 王总 李工" [--prompt "项目周会。"] [--model large-v3-turbo] [--local-only]
# 唱歌、耳语等会被 VAD 误切的素材：关 VAD，手动重叠切块
python ${CLAUDE_SKILL_DIR}/scripts/transcribe.py song_vocal.wav --out lyr.jsonl --no-vad --chunk 28 --overlap 2
```

输出格式见 `solve-everything/references/schemas.md`；`asr.jsonl.meta.json` 记录了全部参数和 RTF，可以直接写进论文。

默认值和原因：

- `language="zh"`、`initial_prompt="以下是普通话的句子，使用简体中文。"`：不给提示时 Whisper 经常输出繁体、不加标点。剩下的繁体由 opencc 兜底转换。
- `condition_on_previous_text=False`：防止"一句话无限重复"最有效的开关。代价是段与段之间的连贯性略差。
- `temperature=0.0`：结果可复现。遇到顽固的重复循环可以加 `--fallback`，打开温度回退。
- `word_timestamps=True`：说话人对齐、低置信度标注、时间线都靠它。
- VAD 默认开启，`min_silence_duration_ms=700`，避免一句话被切成两半。

### 已经踩过的坑（都在脚本里处理了）

1. **幻觉句**：静音或纯音乐段会冒出"字幕由Amara.org社区提供""请不吝点赞订阅转发打赏"之类训练数据里的句子。强特征的直接删除，"谢谢观看"这类弱特征只标 `hallucination?`，交给人或 LLM 判断。完整列表在脚本开头。
2. **hotwords 让标点消失**：`initial_prompt` 只作用于第一个 30 秒窗口（关掉 condition_on_previous_text 后尤其如此），之后每个窗口的提示词只剩 hotwords。如果 hotwords 是空格分隔的词表，Whisper 会照着这种格式输出无标点的文本。实测：加上 `--hotwords "北极星 P99 王总"` 后整段转写都没了标点。脚本会把它包装成一句带标点的话（"会议中可能出现：北极星、P99、王总。"），问题就消失了。
3. **半角标点**：中文里常出现 `,` `?`，脚本会把与汉字相邻的标点统一成全角。
4. **`segs` 是生成器**：`transcribe()` 立刻返回，真正的识别发生在遍历时。计时、多进程时别被骗。
5. **PyAV 版本**：faster-whisper 的 `decode_audio` 在 PyAV 19 上会崩，脚本改用 ffmpeg 管道解码。
6. **两个人被并成一段**：两人之间的停顿短于 VAD 阈值时，会出现在同一个 segment 里。说话人分离要按词或按句处理（`speaker-diarization` 已处理）。
7. **数字写法**：Whisper 会把"四万八"写成"4万8"、"48000"或"4.8万"，同一个模型不同次运行也不一样。评测时用 `quality-eval/scripts/cer.py --num`，成稿时以 PPT 或文档上的写法为准。

## 第二意见：SenseVoice

```bash
python ${CLAUDE_SKILL_DIR}/scripts/sensevoice_onnx.py MODEL_DIR audio.wav --segments turns.jsonl --out sv.jsonl
```

`MODEL_DIR` 是 sherpa-onnx 导出的 SenseVoice（`model.int8.onnx` + `tokens.txt`）。用与主稿相同的片段边界逐段比对：两者一致的地方基本可信；**不一致的片段才需要人去听**，这比通读全文省力得多。输出里的 `emotion` / `event` 可以交给 `timeline-fusion` 写成"（笑声）"。

坑：特征前端（80 维 fbank、25 ms 窗、预加重、LFR 7/6、CMVN）是手写的，必须和训练时一致，否则输出流畅但全错，而且不报错。语言和 ITN 的 id 从模型元数据读取（`lang_zh=3`、`with_itn=14`）。换模型后先拿一段已知内容的音频验证。

## 裁决：让声音决定是哪个词

LLM 擅长猜"这里可能是哪几个词"，声学模型擅长判断"哪个和声音对得上"。把两者结合起来：

```bash
python ${CLAUDE_SKILL_DIR}/scripts/score_candidates.py audio.wav --start 59.2 --end 63.4 \
    --cand "等王总确认" --cand "等网总确认" --cand "等汪总确认"
# 批量：--cases cases.json  ([{"start","end","candidates":[...]}])
```

流程：

1. 在时间线里找出可疑处：`{词?}` 标记、和 PPT 或参会名单不一致的专名、两个引擎结果不同的地方。
2. 根据上下文、PPT OCR 和名单，列出 2–5 个候选**整句**。
3. 打分。脚本会只比较候选之间不同的那部分词的平均对数概率（`focus_logprob`）；差距小于 0.1 时会提示"太接近，问人"。

演示数据上的实测：「王」-0.15 对「网」-0.58；「4万8」-0.57 对「48万」-4.35。

限制：片段不超过 30 秒；用到了 `find_alignment` 等内部接口（每个候选单独对齐，batch 维度必须是 1），升级 faster-whisper 前先锁版本测一遍。

## 什么时候需要人

- 片段被标了 `low_confidence`、`hallucination?` 或 `repetition`。
- 两个引擎的结果不同，而且涉及人名、数字或决定。
- 候选打分差距小于 0.1。

把这些片段的时间戳列给用户，比让用户从头核对整份稿子友好得多。
