---
name: media-pipeline
description: >-
  One command from any audio or video (short videos, lectures, tutorials, interviews, podcasts, screen
  recordings, livestream replays, music videos) to audited, fused, checkable input for an LLM: inventory,
  loudness-normalised audio, guarded Whisper transcription split into sentences, optional speaker
  diarization, screen-change detection that also catches one-second flash cards, OCR, burned-in subtitles,
  beats, a timeline with automatic subtitle-vs-speech cross-checks, timeline pictures, and a coverage
  report that fails loudly when parts of the input were never processed. Use whenever a recording has to
  be understood, summarised, quoted, searched, turned into notes or handed to another agent.
  视频/音频一条命令处理、短视频拆解、录屏、讲座、访谈、播客、直播回放、MV，都用这个。
---

# media-pipeline：一条命令，把音视频榨干

```bash
python ${CLAUDE_SKILL_DIR}/scripts/run_pipeline.py clip.mp4 --work work/
python ${CLAUDE_SKILL_DIR}/scripts/run_pipeline.py lecture.mp4 --work work/ --crop 0,0,1600,900 --mask 1600,0,320,180 --hotwords "傅里叶 卷积"
python ${CLAUDE_SKILL_DIR}/scripts/run_pipeline.py podcast.m4a --work work/ --speakers 2
python ${CLAUDE_SKILL_DIR}/scripts/run_pipeline.py short.mp4 --work work/ --crop 0,0,1280,620 --subs-crop 0,620,1280,100 --music
python ${CLAUDE_SKILL_DIR}/scripts/run_pipeline.py mv.mp4 --work work/ --subs-crop 0,600,1280,120 --music --no-vad
```

| 步骤 | 产物 | 来自 |
|---|---|---|
| 0 盘点 | `ledger.md`（多长、几条音轨、帧率、内嵌字幕、抽帧会漏什么） | `input-audit` |
| 1 音频 | `audio.wav`（16 kHz、响度归一） | `media-ingest` |
| 2 转写 | `asr.jsonl`（按句切分、带逐词置信度、幻觉过滤） | `speech-to-text` |
| 3 说话人 | `turns.jsonl`（`--speakers N`、`--diarize` 或 `--diar FILE` 时才做） | `speaker-diarization` |
| 4 画面 | `slides/segments.json` + 每个状态一张截图 + OCR（闪现单独截） | `screen-and-ocr` |
| 5 硬字幕 | `subs/subs.json`、`.srt`（给了 `--subs-crop` 时才做） | `screen-and-ocr` |
| 6 节拍 | `beats.json`（`--music`） | `music-and-sound` |
| 7 时间线 | `timeline.md`（按画面分节；字幕和语音自动互证；闪现加粗） | `timeline-fusion` |
| 8 图 | `plots/timeline_XX.png` | `visual-verify` |
| 9 对账 | `coverage.md`（低于 `--min` 时提示：先补缺口，再写东西） | `input-audit` |

已经有产物的步骤会自动跳过，中断后可以接着跑；`--force` 全部重跑。

## 跑完之后，按这个顺序读

1. `ledger.md`：有没有多音轨、可变帧率之类的风险？有的话调整参数重跑。
2. `coverage.md`：语音和画面的覆盖率达标了吗？缺口在哪几秒？
3. `plots/timeline_XX.png`：说话人条、置信度红块、画面状态条（黄色的是闪现）。
4. `timeline.md`：通读。重点看 `⚠ 字幕/语音不一致`、`{…?}` 低置信度词和**〔屏幕闪现〕**。
5. 用 `expressive-output` 写最终的输出：笔记、摘要、拆解、交接单都可以，并附上覆盖声明。

## 参数怎么选

- **画面区域**：`--crop` 只框内容区，把字幕条、平台水印、评论区、边栏排除出去；`--mask` 屏蔽摄像头小窗、直播间的动态贴纸。
- **短视频**：画面信息密度高、闪现多。默认 2 fps 能抓到 ≥ 1 秒的闪现；更短的闪现请直接运行 `screen-and-ocr/scripts/slide_changes.py --fps 4`。
- **唱歌、ASMR、耳语**：加 `--no-vad`，避免人声被当成静音切掉。
- **多人**：知道人数就传 `--speakers N`。有更强的说话人分离结果，就用 `--diar` 传进来。
- **专有名词**：传 `--hotwords`；跑完后对可疑词用 `speech-to-text/scripts/score_candidates.py` 让音频裁决。

## 实测（`examples/short-video`，50 秒合成短视频）

- 画面：7/7 个状态，包括 2 个只出现 1 秒的闪现（均匀抽 16 帧只能看到其中 1 个）。
- 语音：33/33 秒有文字，CER 2.7%；音乐前奏和尾奏没有产生幻觉句。
- 字幕：7 句全部切准；和语音互证，发现 7 处不一致（语音错 4 处，OCR 错 3 处）。
- 节拍：95.7 BPM（真实值 96）。
