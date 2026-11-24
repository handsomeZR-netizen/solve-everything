# 示例：一个藏着 8 条信息的文件夹

一个文件夹，6 个文件，全部是合成的。里面有 8 条关键信息，都放在常见读取方式看不到的地方。用来回答一个问题：**LLM 真的处理完你的输入了吗？**

| 文件 | 藏了什么 | 常见的快速读取 |
|---|---|---|
| `clip.mp4`（50 秒知识短视频） | 两张只出现 1 秒、口播里没提的卡片：评论区口令 `SE-0618`、下次直播 `12月6日 20:00` | 均匀抽 8 帧看到 0/2，抽 16 帧看到 1/2 |
| `report.pdf` | 第 2 页是扫描件："结论以本页为准，预算上限 3.5 万元" | 只读文字层，这一页是空白 |
| `long_screenshot.png`（1200×5000） | 最后一行："交付时间改到周四下午三点" | 整图缩到 0.31 倍，30 px 的字只剩 9 px |
| `deck.pptx` | 演讲备注"其实已经决定选 B"；隐藏页"供应商可能延期两周" | 只读幻灯片正文 |
| `notes.docx` | 批注"这一条要改，先别发"；1 张嵌入图片 | 只读正文 |
| `data.xlsx` | 隐藏表"原始数据"里 A = 130，汇总表里却是 100 | 默认只读第一张表 |

视频本身还做了这些设计：背景铺了 96 BPM 的鼓点，开头 2 秒、结尾 4 秒只有音乐（容易诱发幻觉句）；右上角有一个一直跳动的红点（变化检测必须忽略它）；底部有硬字幕。

## 生成

```bash
python make_demo.py --out build             # 视频需要 Windows TTS（pwsh 能用 Yaoyao 等中文声音）
python make_demo.py --out build --no-video  # 只生成文档，任何系统都能跑
```

仓库里不包含生成出来的输入文件，只有真值（`truth/`）和处理结果（`output/`）。

## 复现

```bash
S=../../skills
python $S/input-audit/scripts/inventory.py build/inputs --out ledger.json --md ledger.md
python $S/media-pipeline/scripts/run_pipeline.py build/inputs/clip.mp4 --work work \
    --crop 0,0,1280,620 --subs-crop 0,620,1280,100 --music
python $S/input-audit/scripts/coverage.py video --segments work/slides/segments.json --truth truth/screen.json --duration 50.35
python $S/quality-eval/scripts/cer.py --ref truth/narration.txt --hyp-jsonl work/asr.jsonl --keywords truth/keywords.txt
python $S/docs-and-images/scripts/pdf_extract.py build/inputs/report.pdf --out work/report
python $S/screen-and-ocr/scripts/ocr.py work/report/page_002.png --out work/report/ocr.json
python $S/docs-and-images/scripts/tile_image.py build/inputs/long_screenshot.png --out work/tiles
python $S/docs-and-images/scripts/office_extract.py build/inputs/deck.pptx build/inputs/notes.docx build/inputs/data.xlsx --out-dir work/office
python $S/expressive-output/scripts/coverage_check.py --output handoff.md --facts facts.json --lint
```

## 结果

| 环节 | 结果 |
|---|---|
| 盘点 | 6 个文件，7 个高危风险全部报出（[`output/ledger.md`](output/ledger.md)） |
| 画面 | 变化检测只截 7 张图，7/7 个状态（含 2 个闪现）；均匀抽 8/16/32 帧分别看到 5/6/6 个状态，闪现分别只看到 0/1/1 个（[`output/screen_sampling.txt`](output/screen_sampling.txt)、[`output/flash_sampling.txt`](output/flash_sampling.txt)） |
| 语音 | 覆盖 33/33 秒；CER 2.68%，关键词召回 9/10；音乐段没有产生幻觉句 |
| 硬字幕 | 7/7 句切分正确，OCR 的 CER 为 2.01% |
| 互证 | 字幕和语音有 7 处不一致，对应两边全部 7 处识别错误（语音 4 处，OCR 3 处） |
| 文档 | PDF 2/2 页、长图 1.0 倍、Office 部件全部提取（快速读取：PDF 50%，长图 0.31 倍） |
| 节拍 | 95.7 BPM（真实值 96） |
| 输出 | [`handoff.md`](handoff.md) 通过反查：12/12 条事实，空话 0 处 |
| 对账 | [`output/coverage.md`](output/coverage.md)：7 项全部 100%；快速读取版本 [`output/coverage_quick_read.md`](output/coverage_quick_read.md) 判为 FAIL |

## 开发中被这个例子逼出来的修复

- **变化检测最初漏掉了两张闪现卡片**：只认"静止 1 秒"的画面，1 秒的卡片在 2 fps 下只有 2 个采样，等不到稳定就被丢了。现在转场中的平台期会单独记为 `flash`。
- **时间线里闪现消失了**：它落在两节之间 1 秒的空隙里。现在各节首尾相接。
- **ASR 返回一个 35 秒的"句子"**：背景音乐让 VAD 连成一片。现在按句末标点切开。
- **OCR 放大反而出错**：1 倍时「12月6日20:00」是对的，放大 2 倍后变成「12月６日日2 20:00」，字还更多。现在按平均置信度而不是字数来选。
- **事实反查误报**：`**没**被处理` 里的加粗把关键词拆开了。现在比对前会去掉 Markdown 强调符。
- **coverage.py 写 JSON 崩溃**：numpy float32 不能序列化。

这些修复都已经写进了对应 skill 的"坑"一节。
