---
name: quality-eval
description: >-
  Measure how good a multimodal pipeline really is, the way a paper or a skeptical user would: character
  error rate for Chinese ASR with fair normalisation (full/half width, traditional/simplified, Chinese
  numerals vs digits) plus keyword recall for names and numbers, diarization error rate with optimal
  speaker mapping and collar, fact coverage of written summaries, a time-to-find user study protocol,
  ablation design and public datasets. Use when comparing ASR engines or settings, tuning hotwords/VAD,
  validating diarization, evaluating meeting-minutes or summarisation quality, or writing the experiment
  section of a thesis or paper on multimodal processing. 评测、CER、DER、对比实验、消融、论文实验设计，都用这个。
---

# quality-eval：用数字说话

"感觉好多了"在论文里不算数，在调参时也靠不住。每个环节都有自己的指标，而且**总体指标会掩盖最重要的错误**：CER 只有 3%，可是每个人名都错了，这样的纪要照样不能用。

## ASR：cer.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/cer.py --ref ref.txt --hyp hyp.txt --num --keywords kw.txt --show 15 --json m.json
python ${CLAUDE_SKILL_DIR}/scripts/cer.py --ref-jsonl truth.jsonl --hyp-jsonl asr.jsonl --num --t2s
```

- 中文用 **CER**（字错误率），不用 WER。
- 归一化：NFKC（全角转半角）、小写、去掉标点和空白；`--t2s` 繁转简；`--num` 把中文数字转成阿拉伯数字（十二月五号 → 12月5号，P九十九 → P99）。不开 `--num` 时，"十二月"和"12月"会算 3 个错，ITN 写法的差异可能占掉大半个 CER。
- `--keywords`：人名、术语、数字的召回率。纪要质量主要看这个。
- 输出错误片段（`…大概4[8万 → 万8]这个…`），方便归类分析错误。
- 实现：向量化的编辑距离（逐行累计最小值技巧），几万字也能秒级算完；超大输入只算距离，不回溯对齐。

`--num` 的局限："四万八"在口语里是 48000，脚本会按字面转成"4万8"；"一二三"按逐位读。数字密集的语料，建议人工统一写法后再评。

## 说话人：der.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/der.py --ref truth.rttm --hyp diar.rttm [--collar 0.25]
```

DER = (漏检 + 虚警 + 混淆) / 参考语音总时长，以 10 ms 为一帧计算；用匈牙利算法求假设说话人到参考说话人的最优映射；每个参考边界前后 `--collar` 秒不计分（行业惯例 0.25 秒）。会分别报告三项的秒数，看清楚错在哪一类。

## 纪要 / 摘要

- **事实覆盖**：人工从原文标出决定、待办、数字，作为 `facts.json`，再用 `expressive-output/scripts/coverage_check.py` 算保留比例。
- **事实一致性**：纪要里每条陈述能否在原文中找到依据（时间戳）。抽样人工判断，报告"无依据陈述"的比例。
- **查找时间**（最能体现"一眼看到"）：给受试者 5–10 个问题（"李工要交什么？什么时候交？"），记录他们从纪要中找到正确答案所用的时间和正确率；对比不同的输出形式（自由摘要 vs 分层纪要）。
- 长度 / 信息密度：在覆盖率相同时，越短越好。
- ROUGE 只作参考：它奖励的是用词重合，不是有用。

## 消融实验怎么设计

一次只改一个变量，在同一批数据上比较：

| 变量 | 比较 | 看什么 |
|---|---|---|
| hotwords | 无 / 有（裸词表）/ 有（包装成带标点的句子） | 关键词召回；**标点是否丢失** |
| VAD | 开 / 关 + 重叠切块 | 幻觉句数量、句首句尾漏字 |
| 引擎 | Whisper / SenseVoice / Paraformer / 两者融合 | CER、关键词召回、RTF |
| 屏幕文字纠错 | 无 / 用 OCR 纠正专名 / 加候选打分 | 专名准确率 |
| 说话人 | 基线 / 嵌入类后端 / oracle 标注（上界） | DER，以及待办归属正确率 |
| 输出方法 | 一遍总结 / 先抽取再写再反查 | 事实覆盖、无依据陈述、查找时间 |

每组都报告运行环境（CPU 型号、线程数）、模型版本和 RTF。`transcribe.py` 的 `.meta.json` 已经记录了参数。

## 公开数据集（使用前请自行核实获取方式和许可）

- 中文会议：AliMeeting（M2MeT 挑战赛）、AISHELL-4（都有说话人标注）
- 中文会议摘要：VCSum
- 英文会议：AMI、ICSI；基于查询的会议摘要：QMSum

## 本仓库演示数据上的结果（合成、68 秒、3 人，仅作流程验证）

| 环节 | 结果 |
|---|---|
| ASR（large-v3-turbo, CPU int8, 带热词） | CER 0.92%，关键词召回 94%（漏的是 "4.8万" 被写成 "4万8"） |
| 说话人（diarize_lite 基线） | DER 35.5% |
| 翻页检测 | 3/3，无误报（画面中有移动的鼠标指针和闪动的摄像头小窗） |
| 硬字幕 | 10/10 句切分正确，文字正确 |
| 纪要事实覆盖 | 8/8 |

合成语音比真实会议容易得多。这些数字只证明流程能跑通，不代表真实场景的性能。
