---
name: visual-verify
description: >-
  Check multimodal processing by looking at it: render a fused timeline as pictures (speaker lanes,
  loudness, word-confidence stripe, slide spans with OCR titles, sound events), tile dozens of frames,
  slides or subtitle crops into captioned contact sheets, and overlay lyric spans on a vocal
  spectrogram, all sized so a vision model can read them without downscaling. Use after any automatic
  step whose errors are hard to see in text: speaker attribution, slide detection, subtitle timing,
  lyric sync, frame sampling, OCR coverage. 可视化核对、联系表、时间线图、对轴检查、抽查帧，都用这个。
---

# visual-verify：画成图，一眼看出错

模型听不到声音，但看得到图。很多错误在 JSON 里要逐行比对才找得到，画成图后一眼就能看出来：

- 某人的发言条跨过了翻页的边界：可能是两个人被并成了一段。
- 置信度条上有一块红色，正好落在一个人名上：要核实。
- 歌词竖线比人声起点早了半秒：对轴错了。
- 二十张"不同的幻灯片"里有三张其实一样：翻页检测误报了。

## 时间线图：timeline_plot.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/timeline_plot.py --timeline timeline.jsonl --audio audio.wav --out plots/tl
python ${CLAUDE_SKILL_DIR}/scripts/timeline_plot.py --timeline timeline.jsonl --row 120 --t0 600 --t1 1800 --out plots/part
```

每行 `--row` 秒（默认 60），从上到下依次是：时间刻度、响度、每个说话人一条（条内写着这句话的开头）、逐词置信度（红 < 0.5 < 黄 < 0.8 < 绿）、屏幕页（编号 + OCR 首行，灰色是 dynamic 段）、声音事件。宽 1500 px，每页高度不超过 1500 px，自动分页。

## 联系表：contact_sheet.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/contact_sheet.py --segments slides/segments.json --out sheets/slides --cols 3 --thumb 420
python ${CLAUDE_SKILL_DIR}/scripts/contact_sheet.py --dir frames/ --index frames/index.json --out sheets/frames
python ${CLAUDE_SKILL_DIR}/scripts/contact_sheet.py --subs subs/subs.json --out sheets/subs --cols 1 --thumb 900
```

图注会自动带上时间、编号和 OCR 文字。

## 频谱 + 歌词：见 `music-and-sound/scripts/vocal_map.py`

## 怎么看（核对清单）

| 看什么 | 正常 | 可疑 |
|---|---|---|
| 说话人条 | 轮流出现，和对话内容对得上 | 一个人的条异常短或几乎没有；条的边界和翻页边界巧合地重合 |
| 置信度条 | 大部分绿色 | 红黄集中在专名、数字上；整段发黄（可能是噪声或口音，换引擎试试） |
| 屏幕页 | 页数和实际一致 | 相邻两页标题相同（误切）；很长的一页（漏切，或 `--area` 太大） |
| 响度 | 说话处有起伏 | 有声音却没有任何说话人条（ASR 漏了，或被当作幻觉删了） |
| 联系表 | 每张都不同、都清晰 | 重复、模糊、截在动画中间 |

## 尺寸原则

- 一张图的长边不要超过约 1500 px，否则会被缩小，字就看不清。内容多就分页，脚本默认已经这么做。
- 图注的字号在缩略图上至少要 14 px。
- 每页只放需要一起比较的东西。50 张缩略图挤在一页，等于什么都没看。
