---
name: meeting-minutes
description: >-
  End-to-end meeting minutes from a recording: one command runs probe, audio extraction, Whisper
  transcription with hotwords, speaker diarization and word-level merge, slide-change detection and
  OCR on shared screens, timeline fusion and timeline pictures; then the minutes are written from the
  fused timeline with the expressive-output method (reader-first, decisions / owner-deadline table /
  open questions, timestamps as evidence) and back-checked against extracted facts. Use whenever the user
  has a meeting, call, standup, review, interview panel, class discussion or webinar recording (Tencent
  Meeting / Zoom / Teams / Feishu exports, phone recordings, OBS captures) and wants minutes, a summary,
  action items, decisions or "who said what". 会议纪要、会议录音整理、录像总结、待办提取、谁答应了什么，都用这个。
---

# meeting-minutes：从录音录像到可信的纪要

## 1. 一条命令准备好输入

```bash
python ${CLAUDE_SKILL_DIR}/scripts/run_pipeline.py meeting.mp4 --work work/ \
    --speakers 4 --hotwords "北极星 P99 压测 王总 李工" \
    [--crop 0,0,1600,900 --mask 1600,0,320,180]   # 共享屏幕区域 / 要忽略的摄像头小窗
    [--diar pyannote.rttm]                         # 已有更强的说话人分离结果就直接用
    [--names names.json] [--track 1] [--local-only]
```

依次运行 probe → 抽音频（loudnorm）→ 转写 → 说话人（默认 `diarize_lite` 基线）→ 词级合并 → 翻页检测和 OCR（有视频时）→ 融合 → 画时间线图。每一步的输出都已存在时会自动跳过，中断后可以接着跑；`--force` 全部重跑。各步骤的细节和坑，见同名子 skill。

开始之前问用户（或从上下文判断）：大概有几个人？有没有参会名单、议程、项目术语（作为 hotwords）？纪要给谁看？

## 2. 读输入，先核对

1. 看 `work/probe.json` 里的 warnings（多音轨、A/V 偏移……），必要时调整参数重跑。
2. 看 `work/plots/timeline_XX.png`：说话人条、置信度红块、翻页（核对清单见 `visual-verify`）。
3. 通读 `work/timeline.md`。

## 3. 修正说话人和可疑词

- **命名**：用自我介绍、点名后的回应、用户提供的名单推断，写进 `names.json` 后用 `--names` 重跑（只会重做合并以后的步骤）。没有依据的保持"发言人 A"。规则见 `speaker-diarization`。
- **可疑词**：`{…?}` 标记的人名、数字、术语，先对照屏幕文字和名单；还拿不准的，列出候选整句，用 `speech-to-text/scripts/score_candidates.py` 让音频裁决。
- 修正结果写进"存疑"一节，说明依据。

## 4. 写纪要

按 `expressive-output` 的方法写：

1. 抽取 `facts.json`：所有决定、待办（谁/做什么/截止）、数字、分歧、未决问题，每条带时间戳和 `must` 字段。
2. 按模板写成文：一句话 → 需要拍板 → 待办表 → 议题 → 原话 → 存疑。
3. 反查：`python ${CLAUDE_SKILL_DIR}/../expressive-output/scripts/coverage_check.py --output minutes.md --facts facts.json --source work/timeline.md --lint`。

演示：`examples/demo-meeting/` 里有一场 68 秒的合成会议，包含输入时间线、纪要、facts.json 和时间线图。

## 5. 长会议（> 1 小时）

- timeline.md 按节（按页或每 5 分钟）分批读，每批输出该节的 facts 和要点。
- 汇总时，把各批 facts 合并去重（同一件事前后被提到多次时，以**最后一次**的说法为准，并记下变化过程），再写成文。
- 不要用"摘要的摘要"代替原文。汇总阶段遇到矛盾，回到对应时间戳的原文去看。

## 交付时告诉用户

- 用了哪个说话人分离后端（基线还是 pyannote 等），哪些名字是推断出来的。
- "存疑"一节里有哪些需要他确认的地方，按时间戳列出，方便他直接跳到录音去听。
- 中间文件在哪里（`work/`），以便复查或重跑。
