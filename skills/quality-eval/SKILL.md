---
name: quality-eval
description: >-
  Measure how good a multimodal pipeline really is, the way a reviewer or a skeptical user would: input
  coverage (what fraction of seconds, screen states, pages, sheets was processed), character error rate
  for Chinese ASR and OCR with fair normalisation (full/half width, traditional/simplified, Chinese
  numerals vs digits) plus keyword recall, diarization error rate with optimal speaker mapping and collar,
  fact coverage of written outputs, a time-to-find user study, ablation design and public benchmarks. Use
  when comparing engines or settings, validating a pipeline, evaluating summaries or handoffs, or writing
  the experiment section of a thesis or paper. 评测、覆盖率、CER、DER、对比实验、消融、论文实验设计，都用这个。
---

# quality-eval：用数字说话

"感觉好多了"在论文里不算数，调参时也靠不住。每个环节都有自己的指标，而且**总体指标会掩盖最重要的错误**：CER 只有 3%，可每个人名都错了，这样的输出照样不能用；CER 是 0，可一半页面根本没读过，同样不能用。

## 0. 先量覆盖，再量正确

覆盖率回答"处理了多少"，正确率回答"处理得对不对"。前者是后者的前提，见 `input-audit/scripts/coverage.py`。论文里建议两者都报告：

| 层次 | 指标 | 工具 |
|---|---|---|
| 覆盖 | 语音秒数覆盖、画面状态召回、页面覆盖、Office 部件覆盖、有效分辨率 | `coverage.py` |
| 识别 | CER（ASR / OCR）、关键词召回、DER | `cer.py`、`der.py` |
| 表达 | 事实覆盖、无依据陈述比例、查找时间 | `expressive-output/scripts/coverage_check.py`、人工 |

## 1. 识别：cer.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/cer.py --ref ref.txt --hyp hyp.txt --num --keywords kw.txt --show 15 --json m.json
python ${CLAUDE_SKILL_DIR}/scripts/cer.py --ref-jsonl truth.jsonl --hyp-jsonl asr.jsonl --num --t2s
```

- 中文用 **CER**（字错误率），不用 WER。ASR 和 OCR（比如硬字幕）都可以这样评。
- 归一化：NFKC（全角转半角）、小写、去掉标点和空白；`--t2s` 繁转简；`--num` 把中文数字转成阿拉伯数字（十二月五号 → 12月5号）。不开 `--num` 时，"十二月"和"12月"会算 3 个错，ITN 写法的差异可能占掉大半个 CER。
- `--keywords`：人名、术语、数字的召回率，这对下游输出影响最大。
- 输出错误片段，比如 `…有几条音[轨 → 柜]pdf有…`，方便给错误归类。
- 实现：向量化的编辑距离（逐行累计最小值），几万字也能秒级算完。

`--num` 的局限："四万八"在口语里是 48000，脚本按字面转成"4万8"；"一二三"按逐位读。数字密集的语料，建议先人工统一写法再评。

## 2. 说话人：der.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/der.py --ref truth.rttm --hyp diar.rttm [--collar 0.25]
```

DER = (漏检 + 虚警 + 混淆) / 参考语音总时长。按 10 ms 一帧计算，用匈牙利算法求假设说话人到参考说话人的最优映射；每个参考边界前后 `--collar` 秒不计分（惯例取 0.25 秒）。三项会分别报告秒数。

## 3. 输出质量

- **事实覆盖**：人工从原文标出关键事实，写成 `facts.json`，再用 `coverage_check.py` 计算保留了多少。
- **藏匿信息召回**：只出现在闪现画面、扫描页、备注、批注、隐藏表里的事实，单独统计召回率。这是"输入有没有榨干"最直接的证据。
- **事实一致性**：输出里每条陈述能不能在原文中找到依据（时间戳 / 页码）。抽样人工判断，报告"无依据陈述"的比例。
- **查找时间**：给受试者 5–10 个问题，记录他们从输出中找到正确答案用了多久、答对多少。比较不同的输出形式，比如自由摘要和分层输出。
- ROUGE 只作参考：它奖励的是用词重合，不是有用。

## 4. 消融怎么设计

一次只改一个变量，用同一批数据：

| 变量 | 比较 | 看什么 |
|---|---|---|
| 视频读取 | 均匀 N 帧 / 固定 fps / 变化检测（含闪现） | 画面状态召回、藏匿信息召回、帧数（成本） |
| 文档读取 | 只读文字层 / + 扫描页 OCR / + Office 全量解包 / + 大图切块 | 页面和部件覆盖、藏匿信息召回 |
| hotwords | 无 / 裸词表 / 包装成带标点的句子 | 关键词召回；**标点有没有丢** |
| VAD | 开 / 关 + 重叠切块 | 幻觉句数量、句首句尾漏字 |
| 引擎 | Whisper / SenseVoice / Paraformer / 互证 | CER、关键词召回、RTF |
| 互证 | 无 / 字幕↔语音 / + 候选打分 | 专名和数字准确率 |
| 说话人 | 基线 / 嵌入类后端 / oracle 标注（上界） | DER、行动项归属正确率 |
| 输出方法 | 一遍总结 / 先抽取再写再反查 | 事实覆盖、无依据陈述、查找时间 |

每一组都报告运行环境（CPU、线程数）、模型版本和 RTF。`transcribe.py` 的 `.meta.json` 已经记录了这些参数。

## 5. 公开基准（使用前请自行核实获取方式和许可）

- 中文 ASR：AISHELL-1、WenetSpeech
- 说话人分离：VoxConverse
- 长视频理解：Video-MME、LongVideoBench
- 文档理解：DocVQA、ChartQA

## 本仓库示例上的结果（`examples/short-video`，合成数据，只用来验证流程）

| 环节 | 结果 |
|---|---|
| 画面状态（变化检测，7 张截图） | 7/7；其中 2 个 1 秒闪现：均匀抽 8 帧 0/2，抽 16 帧 1/2 |
| ASR（large-v3-turbo，CPU int8，背景有鼓点） | CER 2.68%，关键词召回 9/10；语音覆盖 33/33 秒 |
| 硬字幕 OCR | CER 2.01%（3 处错，其中一处漏掉了「没」） |
| 字幕↔语音互证 | 7 处不一致，覆盖了两边全部 7 处识别错误 |
| 文档 | PDF 2/2 页、长图 1.0 倍、PPT/Word/Excel 部件全部提取（快速读取：PDF 50%，长图 0.31 倍） |
| 交接单事实覆盖 | 12/12 |
| 节拍 | 95.7 BPM（真实 96） |

合成数据比真实场景简单得多。这些数字证明各个环节能跑通、能被量化，不代表真实场景下的性能。
