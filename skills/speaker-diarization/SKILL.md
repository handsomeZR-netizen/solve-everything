---
name: speaker-diarization
description: >-
  Work out who spoke when and attach a speaker to every transcribed word: run a diarization backend
  (pyannote, sherpa-onnx / 3D-Speaker, FunASR cam++) or the zero-download lite baseline, merge it with
  word timestamps into speaker turns, fix the classic boundary errors, map SPK_0/SPK_1 to real names
  only with evidence, and score the result with DER. Use whenever a recording has more than one voice:
  meetings, interviews, podcasts, panel talks, phone calls, classroom audio, and whenever a transcript
  attributes lines to the wrong person. 说话人分离、谁说了什么、区分发言人、多人对话、SPK 编号对应真名，都用这个。
---

# speaker-diarization：谁在什么时候说了什么

纪要里"谁答应了什么"比"说了什么"更重要。说话人错了，待办就落到了错的人头上。

## 流程

1. **分离**：得到 `(start, end, SPK_x)` 片段，RTTM 或 JSON 格式。
2. **合并**：`merge_speakers.py` 把每个**词**分给与它重叠最多的说话人，再按"换人或停顿超过 1.2 秒"重新组成发言轮次。
3. **命名**：把 SPK_x 对应到真名，必须有依据。
4. **评测**（有标注时）：`quality-eval/scripts/der.py`。

```bash
# 没有任何模型时的基线（只要 librosa + scipy，CPU 上几秒钟）
python ${CLAUDE_SKILL_DIR}/scripts/diarize_lite.py audio.wav --asr asr.jsonl --speakers 3 --out diar.rttm
# 合并（diar 可以来自任何后端）
python ${CLAUDE_SKILL_DIR}/scripts/merge_speakers.py --asr asr.jsonl --diar diar.rttm --out turns.jsonl [--names names.json]
```

## 选后端

| 后端 | 质量 | 代价 |
|---|---|---|
| pyannote.audio | 通常最好 | 需要 HuggingFace token 并在网页上同意模型协议；CPU 上较慢 |
| sherpa-onnx（pyannote 分割 + 3D-Speaker 声纹） | 好，纯 ONNX | 需下载两个小模型 |
| FunASR cam++ | 和 Paraformer 一起跑时最省事 | 依赖 FunASR |
| `diarize_lite.py` | **弱基线**：MFCC 统计量 + 层次聚类 | 零下载 |

各后端的调用代码见 [references/backends.md](references/backends.md)，都输出 RTTM，后面的步骤不变。

`diarize_lite` 的实测：在合成演示（3 个 Windows TTS 声音、68 秒）上 DER 约 36%。对 MFCC 维度、音高、差分、Ward / k-means 做了网格搜索，聚类纯度一直停在 77–87%，这就是手工特征的上限。它适合"先跑通、先看个大概"；要交付的纪要请换用声纹嵌入类后端。相同 ASR 下换成正确的说话人标注（oracle 上界），说话人归属就完全正确了。论文里建议同时报告这两种条件。

## 已经处理的边界错误

- **两个人被并成一个 ASR 片段**：两人之间的停顿比 VAD 阈值短时就会出现。`diarize_lite` 按句末标点和 ≥ 0.35 秒的词间停顿把片段切成"单元"再聚类，`merge_speakers` 也是按词分配，而不是按片段。
- **停顿后的第一个词被拉长**：Whisper 常把停顿后的第一个词的起点往前拉进静音里（例如一个字持续 1.3 秒、结束得比下一个词早 0.7 秒），于是它被分给了上一个说话人。实测："那最晚什么时候能好？**我**"。`merge_speakers` 会识别时长不合理的词：片段首词以下一个词的起点为准，往前放回去；其他超长词只保留合理长度的尾部。日志里的 `over-long words tightened` 会显示处理了几个。
- **没有重叠的词**：0.5 秒内借用最近的说话人，否则标 `UNK`。

## 命名规则（不要猜）

1. 依据从强到弱：用户确认 > 自我介绍（"我是李工"）> 被点名后紧接着回应（"小陈你周五前通知客户" → 下一句"好的，我周五前发邮件"）> 职能推断。
2. 写一个 `names.json`：`{"SPK_0": "王总", "SPK_2": "小陈"}`，只写有依据的，然后用 `--names` 重新合并。
3. 推断出来的名字，在纪要里第一次出现时说明依据；没把握的保持"发言人 A"。把一件待办分配给错的人，比不写名字代价大得多。

## 输出后必看

`merge_speakers.py` 会打印每人发言时长、无归属的词数、短于 1 秒的轮次、触及重叠语音的轮次。

- 某人发言时长异常短（比如 1 秒），往往说明聚类把他并进了别人，或者拆出了一个只有噪声的类。
- 短轮次（"对""嗯"）和重叠段是错误最集中的地方，抽听这些。
- 用 `visual-verify/scripts/timeline_plot.py` 看说话人条：交替频繁、和换页边界奇怪地对齐，都值得怀疑。

## 其他坑

- 已知人数就传 `--speakers` / `num_speakers`，聚类会准很多。
- 声音相近的两个人（同性别、同口音）最容易混。如果只有一两处需要区分，直接根据内容和用户确认来定，比调参快。
- 远场麦克风 + 混响下，同一个人在不同位置的声音也会被分成两类：看发言时长和内容合并。
