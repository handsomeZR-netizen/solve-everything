---
name: expressive-output
description: >-
  Turn processed material (a fused timeline, transcript, OCR text, document extraction, research notes)
  into output people can use at a glance without losing what matters: decide the reader and the
  decision they face, select by "what changed" rather than "what was said longest", put the conclusion
  first, layer the rest (one-liner, decisions, owner/deadline table, per-topic detail, quotes with
  timestamps, doubts), write concrete checkable sentences with no filler, then extract-first and
  back-check every fact, number, name and date before delivering. Use whenever writing meeting minutes,
  summaries, briefs, lecture notes, interview write-ups, video or podcast digests, reports for a boss or
  client, or when the user complains an output is long-winded, vague, misses points or "sounds like AI".
  总结、纪要、汇报、笔记、提炼重点、写得有表现力、不说废话、一眼看到重点，都用这个。
---

# expressive-output：让人一眼看到要的，又不丢重点

写之前先想清楚两件事：**谁看**，以及**他看完要做什么**。后面的每条规则都是从这里推出来的。

## 第 1 步：定读者

同一场会，不同的人要找的东西不同：

| 读者 | 要找什么 | 放在哪里 |
|---|---|---|
| 决策者 | 定了什么、有什么风险、哪些事等他拍板 | 一句话 + "需要拍板" |
| 执行者 | 我要做什么、什么时候交、找谁 | 待办表（按人一扫就到） |
| 缺席者 | 发生了什么、为什么这么定 | 议题展开 |
| 核实的人 | 原话是什么 | 原话摘录 + 时间戳 |

用户没说读者是谁时，用固定的分层结构，让每种读者都在固定位置找到自己要的。知道读者是谁时，把和他相关的内容放到最上面（"你的待办"）。

## 第 2 步：选重点，看"什么变了"

不要按讨论时长分配篇幅。讨论了 40 分钟的议题，最重要的往往是最后那句"那就这么定了"。

判断一条信息该不该往前放：**会前和会后相比，这件事的状态有没有变？**

- 决定：定了方案或日期，否决了提议
- 承诺：谁答应做什么、什么时候
- 数字：预算、指标、时间点变了
- 意外：延期、超支、方向调整
- **分歧和未决**：最容易被丢掉，却最有用，因为后面还要处理

寒暄、背景、来回讨论的过程、复述，要么压成一句"为什么这么定"，要么不写。

删除测试：**删掉这一条，读者会不会做错事或漏掉事？** 不会就删。

## 第 3 步：先抽取，再写作，最后反查

直接一遍写"总结"最容易丢中间的内容，也容易被平均化。分三步做：

1. **抽取**：通读输入（例如 `timeline.md`），把所有决定、承诺、数字、日期、分歧、未决问题列进 `facts.json`，每条带时间戳和 `must` 字段（成稿里必须出现的字符串）。这一步只求全，不管好不好看。格式见 `solve-everything/references/schemas.md`。
2. **写作**：从清单里挑选、排序，套用下面的结构写成文。
3. **反查**：

```bash
python ${CLAUDE_SKILL_DIR}/scripts/coverage_check.py --output minutes.md --facts facts.json --source timeline.md --lint
```

- `--facts`：每条事实的 `must` 字符串都要出现（比对前会归一化：全半角、12月1号=12月1日、4万8=4.8万、毫秒=ms、这周=本周）。缺一条就退出码 1。
- `--source`：原文里的数字、日期、金额、百分比，凡是成稿没出现的都列出来。不是每个数字都要写进去，但每个没写的都应该是**有意**省略的。
- `--lint`：找出"深入讨论、达成共识、值得注意的是、总的来说、赋能、闭环……"这类空话。

实测：演示纪要 8/8 条事实保留，原文硬信息无遗漏，空话 0 处；一句"本次会议围绕项目进度展开了深入讨论，与会人员各抒己见，达成共识"则 0/8。

## 第 4 步：结构，结论先行，细节往后放而不是删掉

"一眼看到"和"不丢重点"并不矛盾，靠分层解决：重要的在上，次要的在下，原话兜底。读者读到哪层停下都行，信息都还在。

默认结构（会议纪要，其他体裁见 [references/templates.md](references/templates.md)）：

```markdown
# <会议名> · 纪要
<日期> · <参会人> · <时长/来源>

**一句话**：<最重要的变化 + 前提条件 + 最大的未决事项>

## 需要拍板          ← 只有确实有待决事项时才写
## 待办              ← 表格：谁 | 做什么 | 截止 | 原话时间戳
## 议题              ← 每个议题：结论 / 原因 / 分歧或未决
## 原话              ← 关键表态的原话 + 时间戳
## 存疑              ← 低置信度、推断出来的名字、相互矛盾的数字
```

格式跟着内容走：对比用表格，步骤用编号列表，因果和理由用短段落。不要整篇都写成列表，列表会把"因为……所以……"切断。

## 第 5 步：文风

对比：

> ✗ 本次会议围绕项目进度展开了深入讨论，与会人员各抒己见，就性能优化、上线时间等问题达成了一定共识。
>
> ✓ 上线从 12/1 推迟到 12/15，条件是接口 P99 从 800 ms 降到 300 ms 以下；李工 12/5 前出压测报告。

- 每句话都要有具体的人、事、数字或日期。写完问一句"这句能被核对吗"，不能就是空话。
- 关键表态用原话。"王总：这个月必须上"比"领导强调了时间的重要性"有力得多，也更可信。
- 同一个东西始终用同一个叫法。前面叫"接口"，后面就别变成"服务""API"。
- 原文没有的字段写"未明确"，不要为了读着顺而补齐。推断出来的内容说明依据。
- 数字以最可靠的来源为准（PPT、文档 > 语音转写），并保持写法统一。
- 语气看场合：内部纪要可以只写关键词；发给客户的要写完整的句子、正式一些。
- 不用：三段式排比、"不仅……更是……"、无出处的"有人认为"、结尾的空泛升华、表情符号。

## 第 6 步：交付前的两个问题

- 没来的人看完，能不能直接接着干活？
- 有没有哪个参会者看完会说"我不是这个意思"，或者"这件事怎么没写"？

两个问题有任何一个答不上来，回到第 3 步。
