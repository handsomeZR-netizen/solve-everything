---
name: expressive-output
description: >-
  Turn processed material (a fused timeline, transcript, OCR, extracted documents, research notes, another
  agent's results) into output people and agents can act on at a glance without losing what matters:
  decide the reader and what they will do next, select by what changed, what is hidden and what conflicts
  rather than by what took the most space, put the conclusion first, layer the rest (one-liner, what needs
  a decision, key facts with sources, detail, quotes, doubts, a coverage statement), write concrete
  checkable sentences with no filler, then extract-first and back-check every fact, number, name and date
  before delivering. Use for summaries, briefs, notes, video breakdowns, reports, answers about long
  inputs, and agent-to-agent handoffs, and whenever an output is long-winded, vague, misses points or
  sounds like AI. 总结、汇报、笔记、拆解、交接、提炼重点、不说废话、一眼看到重点，都用这个。
---

# expressive-output：让人一眼看到要的，又不丢重点

写之前先回答两个问题：**谁看**，以及**他看完要做什么**。下面每条规则都是从这两个问题推出来的。

## 第 1 步：定读者

| 读者 | 他要找什么 | 放在哪里 |
|---|---|---|
| 做决定的人 | 结论、风险、哪些事等他拍板 | 一句话 + "需要你确认" |
| 干活的人 | 我要做什么、什么时候、依据在哪 | 行动清单 |
| 没看过原材料的人 | 发生了什么、为什么 | 展开部分 |
| 下一个 agent | 处理了什么、没处理什么、哪些不可信、文件在哪 | 交接单（覆盖声明 + 存疑 + 依据路径） |
| 核实的人 | 原文怎么说的 | 原话或原文 + 时间戳/页码 |

用户没说读者是谁时，用固定的分层结构，让每种读者都能在固定位置找到自己要的。知道读者是谁时，把跟他有关的内容放到最上面。

## 第 2 步：选重点

不要按材料占了多少篇幅来分配笔墨。讲了 40 分钟的东西，最重要的往往是最后一句定论；PPT 正文写了十条，真正的决定可能藏在演讲备注里。

判断一条信息要不要往前放，问这三个问题：

1. **什么变了？** 决定、承诺、数字、日期、方向，前后不一样的地方。
2. **什么藏着？** 只在屏幕上闪了一秒的、只在扫描页上的、只在批注、备注、隐藏表里的。藏得越深，越可能被别人漏掉，也就越值得写出来。
3. **什么对不上？** 汇总和明细不一致、正文和批注冲突、字幕和语音不同。至少有一边是错的，这正是读者最需要知道的。

背景、寒暄、反复的过程、复述，要么压成一句"为什么"，要么不写。

删除测试：**删掉这一条，读者会不会做错事、漏掉事？** 不会就删。

## 第 3 步：先抽取，再写作，最后反查

一遍直接写"总结"，最容易丢掉中间的内容，也容易把所有东西写成一个调子。分三步：

1. **抽取**：通读输入（`timeline.md`、`document.md`、`office/*.md`……），把所有决定、行动、数字、日期、隐藏信息、矛盾、未决问题列进 `facts.json`，每条带出处和 `must` 字段（成稿里必须出现的字符串）。这一步只求全，不求好看。格式见 `solve-everything/references/schemas.md`。
2. **写作**：从清单里挑选、排序，按下面的结构写。
3. **反查**：

```bash
python ${CLAUDE_SKILL_DIR}/scripts/coverage_check.py --output summary.md --facts facts.json --source timeline.md --lint
```

- `--facts`：每条事实的 `must` 字符串都要出现，缺一条退出码就是 1。比对前会归一化：全角半角统一、去掉 Markdown 强调符、12月1号=12月1日、4万8=4.8万、毫秒=ms。
- `--source`：原文里的数字、日期、金额、百分比，凡是成稿里没出现的都列出来。不是每个数字都得写，但每个没写的都应该是有意省略。
- `--lint`：找出"深入讨论、达成共识、值得注意的是、总的来说、赋能、闭环……"这类空话。

实测：`examples/short-video/handoff.md` 保留了 12/12 条事实，空话 0 处。反查时发现过一次"假漏"：`**没**被处理` 里的 Markdown 加粗把关键词拆开了，现在归一化时已经会去掉强调符。

## 第 4 步：结构，结论先行，细节往后放而不是删掉

"一眼看到"和"不丢重点"靠分层来同时做到：重要的放上面，次要的放下面，原文兜底。读者读到哪一层停下都行，信息都还在。

```markdown
# <标题>
<来源 · 范围 · 日期>

**一句话**：<最重要的结论 + 前提 + 最大的未决事项>

## 需要你确认      ← 只在确实有待决事项时才写
## 关键信息        ← 表格：信息 | 出处（时间戳/页码） | 为什么重要
## 展开            ← 每个主题：结论 / 依据 / 分歧或未决
## 原话 / 原文     ← 关键表述原样引用 + 出处
## 存疑            ← 低置信度、推断出来的、互相矛盾的
## 覆盖声明        ← 处理了什么、没处理什么（来自 input-audit）
```

其他体裁（Agent 交接单、短视频拆解、讲座笔记、访谈整理、文档速读、决策简报、行动清单）见 [references/templates.md](references/templates.md)。

格式跟着内容走：对比用表格，步骤用编号列表，因果和理由用短段落。不要整篇都写成列表，列表会把"因为……所以……"切断。

## 第 5 步：文风

> ✗ 本视频围绕大模型处理输入的问题进行了深入探讨，从多个维度给出了全面的建议，具有重要的参考价值。
>
> ✓ 视频讲了三步：先盘点输入总量，再全量转写，最后对账列出没处理的部分。另外有两条信息只在屏幕上闪了 1 秒，口播里没有：评论区口令 SE-0618，下次直播 12 月 6 日 20:00。

- 每句话都要有具体的东西：人、数字、日期、出处。写完问一句"这句能被核对吗"，不能就是空话。
- 关键表述用原话，比转述有力，也更可信。
- 同一个东西始终用同一个叫法。
- 原文没有的写"未明确"，推断出来的说明依据，不确定的放进"存疑"。
- 数字以最可靠的来源为准（文档、屏幕 > 语音转写），写法前后统一。
- 语气看读者：内部可以只写关键词，对外要写完整的句子。
- 不用三段式排比、"不仅……更是……"、无出处的"有人认为"、结尾的空泛升华。

## 第 6 步：交付前问三句

- 没看过原材料的人看完，能不能直接开始干活？
- 下一个 agent 拿到这份东西，知不知道哪些可以信、哪些要复查？
- 原材料的作者看完，会不会说"我不是这个意思"或者"这条怎么没写"？

任何一句答不上来，就回到第 3 步。
