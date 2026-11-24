# 演示：北极星项目周会（合成数据）

一场 68 秒的合成会议，用来端到端验证整套 skill。人物、项目和数字全部是虚构的。

## 素材是怎么做的

`make_demo.py`（仅限 Windows）用三个 Windows TTS 声音（Kangkang、Huihui、Yaoyao）分别扮演王总、李工、小陈，念 10 句台词。画面是 1280×720、10 fps，里面有：

- 3 页幻灯片，在说话人切换话题时翻页
- 一个一直在动的鼠标指针（翻页检测必须忽略它）
- 右上角一个不停闪动的"摄像头小窗"（用 `--mask` 屏蔽）
- 底部的硬字幕（测试 `burned_subs.py`）
- 低噪声，以及结尾 4 秒静音（测试幻觉过滤）

```bash
python make_demo.py --out build        # 生成 build/demo.mp4 和真值文件
```

仓库里不包含音视频文件（TTS 输出不便再分发），只包含真值和处理结果。

## 文件

| 文件 | 内容 |
|---|---|
| `truth.json` / `truth.txt` / `truth.rttm` / `keywords.txt` | 真值：每句话的起止、说话人、文字；关键词列表 |
| `output/asr.jsonl` (+ `.meta.json`) | `transcribe.py` 的输出和全部参数 |
| `output/diar_lite.rttm` | `diarize_lite.py` 基线的说话人结果 |
| `output/turns.jsonl` | 词级合并后的发言轮次（用真值说话人，即 oracle 条件） |
| `output/timeline.jsonl` / `output/timeline.md` | 融合后的时间线 |
| `output/timeline.png` / `output/slides.png` / `output/burned_subs_sheet.png` | 核对用的图 |
| `output/score_candidates.json` | 「王总 / 网总 / 汪总」和「4万8 / 48万 / 14万8」的打分结果 |
| `facts.json` | 从时间线抽取出来的 8 条事实 |
| `minutes.md` | 按 `expressive-output` 写的纪要 |

## 复现

```bash
python make_demo.py --out build
python ../../skills/meeting-minutes/scripts/run_pipeline.py build/demo.mp4 --work work \
    --speakers 3 --hotwords "北极星 P99 压测 王总 李工 小陈" --crop 0,0,1280,640 --mask 1104,8,160,90
python ../../skills/quality-eval/scripts/cer.py --ref truth.txt --hyp-jsonl work/asr.jsonl --num --keywords keywords.txt
python ../../skills/quality-eval/scripts/der.py --ref truth.rttm --hyp work/diar.rttm
# oracle 说话人条件（上界）：
python ../../skills/speaker-diarization/scripts/merge_speakers.py --asr work/asr.jsonl --diar truth.rttm --out work/turns.jsonl
python ../../skills/expressive-output/scripts/coverage_check.py --output minutes.md --facts facts.json --source output/timeline.md --lint
```

## 结果

| 环节 | 结果 |
|---|---|
| ASR（large-v3-turbo，CPU int8，带热词） | CER 0.92%（2 字），关键词召回 17/18（"4.8万"被写成"4万8"）；RTF 0.6–1.8，随 CPU 负载变化 |
| 第二意见（SenseVoice ONNX） | 与 Whisper 的分歧集中在两处：00:27 句首（「或12月5号」，切段边界吃掉了"我"）和 00:48 的金额写法（48000 / 4万8），正是需要人核对的地方 |
| 说话人（diarize_lite） | DER 35.5%（漏检 8.8 s，混淆 9.8 s） |
| 说话人（oracle） | 词级合并后 10 个发言轮次全部归属正确，其中 2 个被拉长的词做了修正 |
| 翻页检测 | 3/3，翻页时刻误差 ≤ 0.5 s，无误报 |
| 硬字幕 | 10/10 句，文字全对（一句末尾多了一个"．"） |
| 候选打分 | 王总 -0.15 > 网总 -0.58 > 汪总 -0.77；4万8 -0.57 > 48万 -4.35 > 14万8 -4.68 |
| 纪要 | 事实 8/8，原文硬信息 0 遗漏，空话 0 处 |

合成语音比真实会议容易得多。这些数字证明流程能跑通、各环节能被测量，不代表真实场景的性能。
