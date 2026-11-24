# AGENTS.md：给所有 agent 协作者的一页纸协议

适用于任何会读取文件、录音、视频、截图、文件夹，或者读取另一个 agent 的输出的 agent，以及人。

## 核心问题

> 你真的处理完输入了吗？

模型很少主动说自己漏看了什么。所以"处理完了"必须是一个**可以检查的数字**，而不是一种感觉。

## 规则

1. **处理前先盘点。** 列出每个输入的总量（秒、帧、页、扫描页、幻灯片、演讲备注、隐藏页、批注、工作表、像素、字符），以及快速读取会丢掉什么。
   `python skills/input-audit/scripts/inventory.py <inputs> --out ledger.json --md ledger.md`
2. **每一步都落盘。** 中间结果带时间戳或页码，存成文件，不要只留在上下文里。
3. **不要盲目抽样。** 视频按画面变化截图（包括闪现），不要均匀抽 N 帧；文档全量解包，不只读正文；大图切块，不让它被缩小。
4. **互证。** 两路来源说的是同一件事时（字幕和语音、画面和口播、汇总表和明细表），逐项比对。不一致的地方至少有一边是错的：标出来，回到原文核实。
5. **对账。** 用中间文件对照盘点结果，算出覆盖率。低于阈值（默认 98%）时不下结论：先补缺口，补不了就写明。
   `python skills/input-audit/scripts/coverage.py summary --cov coverage.json --md coverage.md`
6. **每个回答都带覆盖声明。** 写明已处理了什么、没处理什么、哪些存疑。
7. **交接时带上账本。** 交给下一个 agent 时，附上 `ledger.md`、`coverage.md`、存疑清单和中间文件的路径。模板见 `skills/expressive-output/references/templates.md` 里的"Agent 交接单"。
8. **收到的结果没有覆盖声明，就按"未验证"处理。** 关键结论要回到原文的时间戳或页码核对。
9. **分工切块时记录范围。** 每块负责第几秒到第几秒、第几页到第几页；汇总前检查所有块合起来是否覆盖了全部输入。
10. **不编造。** 原文没有的写"未明确"；推断出来的，写明依据。

## 覆盖声明示例

> 已处理：视频 50 秒（语音 33/33 秒，画面 7/7 个状态，其中 2 个是闪现）、PDF 2/2 页（第 2 页为扫描件，已 OCR）、长截图分 4 块读取、PPT 2/2 页及 1 条演讲备注、Excel 2/2 个工作表（含 1 个隐藏表）。
> 未处理：notes.docx 中的 1 张嵌入图片。
> 存疑：口播和字幕有 7 处不一致，已对照原片改正；data.xlsx 的汇总表（100）和原始数据表（130）对不上，需要人来确认。

## 工具在哪

| 需要 | 脚本 |
|---|---|
| 盘点、对账 | `skills/input-audit/scripts/inventory.py`、`coverage.py` |
| 音视频一条命令 | `skills/media-pipeline/scripts/run_pipeline.py` |
| Office 全量解包 | `skills/docs-and-images/scripts/office_extract.py` |
| PDF、扫描页 | `skills/docs-and-images/scripts/pdf_extract.py` + `skills/screen-and-ocr/scripts/ocr.py` |
| 大图切块 | `skills/docs-and-images/scripts/tile_image.py` |
| 输出反查 | `skills/expressive-output/scripts/coverage_check.py` |

完整说明见 [README.md](README.md) 和各 skill 下的 `SKILL.md`。
