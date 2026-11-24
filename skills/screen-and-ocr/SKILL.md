---
name: screen-and-ocr
description: >-
  Read what is on screen without sampling blind: detect every screen state in a video (slides, cards,
  pages, popups), including flash cards that stay up for only about a second, ignore mouse pointers,
  camera tiles, live badges and chat panels, link bullet-by-bullet builds, mark scrolling and playback,
  save one clean frame per state, OCR images in proper reading order on CPU, and recover burned-in
  subtitles with their on-screen times as SRT. Use whenever text lives in pixels: short videos, tutorials,
  lectures, screen recordings, livestream replays, lyric videos and MVs, film subtitles, screenshots,
  whiteboard photos, scanned pages. 画面文字、屏幕闪现、PPT 翻页、OCR、硬字幕提取、歌词对轴、截图识字，都用这个。
---

# screen-and-ocr：画面上的每一个状态都要看到

很多关键信息只出现在画面上，而且只出现一下：短视频里闪过的口令和价格、课件某一页上的公式、弹窗里的提示。均匀抽帧是在**碰运气**，按画面变化截图才是**把每个状态都看到**。

## 1. 画面状态检测：slide_changes.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/slide_changes.py clip.mp4 --out slides/ \
    --crop 0,0,1280,620 \          # 只看内容区：排除字幕条、平台水印、评论区
    --mask 1104,8,160,90 \         # 要忽略的区域：摄像头小窗、直播角标、贴纸（可重复）
    [--fps 2] [--settle 1.0] [--area 0.012]
```

工作方式：

- 从 ffmpeg 流式读入 192 px 宽的灰度缩略图，内存占用不随视频长度增长。
- 一帧里变化的像素超过 `--area`（默认 1.2%）才算"在变"。鼠标指针、闪烁的小圆点不会触发。
- 画面静止 `--settle` 秒才算进入一个新的**稳定状态**；新画面和原来一样（弹窗出现又消失）就不切分。
- **闪现**：转场过程中，只要有一段连续 ≥ 2 个采样相同、而且和前后画面都不同的平台期，就记为 `flash` 状态，单独截图、单独 OCR。之前的版本只认稳定状态，两张各 1 秒的卡片被直接丢掉了，这就是加上这一条的原因。
- 持续变化超过 `--dynamic` 秒（滚动、播放）的记为 `dynamic` 段，每隔 `--dyn-every` 秒抽一张样张。
- 新内容只出现在原来空白背景上、并且面积不大的，判定为同一页的逐条动画（build），用同一个 `group` 串起来，`complete: true` 的那一帧内容最全。
- 稳定状态取**变化前的最后一帧**（逐条动画时这一帧最全），闪现取平台期的中点。

采样率决定了能抓到多短的闪现：2 fps（默认）能抓到 ≥ 1 秒的；更短的用 `--fps 4`。

实测（`examples/short-video`，50 秒，2 个 1 秒的闪现，右上角有一个一直跳动的红点）：只截了 7 张图，就拿到了 7/7 个状态；均匀抽 16 帧只能看到 1/2 个闪现，抽 8 帧一个都看不到。

## 2. OCR：ocr.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/ocr.py --segments slides/segments.json   # 给每个状态（包括闪现）填上 ocr
python ${CLAUDE_SKILL_DIR}/scripts/ocr.py shot1.png shots/ --out ocr.json
```

在 RapidOCR（PaddleOCR 模型的 ONNX 版，CPU 运行）之上做了这些事：

- **放大要有条件**：先按原尺寸识别；结果弱（没有字，或者最低分 < 0.8）且短边 < 720 时，再放大 2 倍识别一次，**按平均置信度**选更好的那次。测出来的两个坑：30 px 的字幕放大后整行检测不到；1 倍时正确的「12月6日20:00」，放大后变成「12月６日日2 20:00」，字反而更多。所以不能按"认出的字数"来挑。
- **阅读顺序**：按纵坐标把框聚成行，行内按横坐标排序。检测到竖直分栏的空白时，先读左栏再读右栏；跨栏的标题放在最前。
- 分数 < 0.5 的框丢弃并计数。
- 兼容旧包 `rapidocr_onnxruntime` 和新包 `rapidocr`（两者接口不同）。论文复现时要锁定版本。

## 3. 硬字幕：burned_subs.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/burned_subs.py clip.mp4 --crop 0,620,1280,100 --out subs/
python ${CLAUDE_SKILL_DIR}/scripts/burned_subs.py film.mp4 --crop 0,600,1280,120 --mode outline --fps 8 --out subs/
```

- `median` 模式：字幕条的背景取全片逐像素中值，"比背景亮、差异又大"的像素就是字形。适合静态或变化慢的背景，比如口播、歌词 MV、静态封面。
- `outline` 模式：亮像素紧挨着暗描边或阴影的才算字形。适合背景是运动画面的影视剧。
- 相邻帧字形掩码的 IoU 低于 0.5 就算换了一句，所以两句之间没有空隙也能切开。每句选文字像素最多的一帧（已经完全淡入）去 OCR。
- 输出 `subs.json`、`subs.srt`，以及每 20 句一页的拼图（截图 + 时间 + 识别结果）。

实测：7/7 句切分正确，但 OCR 错了 3 处：「帧」认成「顿」、多出一个「与」、漏掉一个「没」。所以字幕 OCR 不能单独当真值用，`timeline-fusion` 会把它和语音逐字比对。

花体、斜体、带阴影的字要自己做掩码。例如白墙上的白色斜体字带灰色阴影时，可以找"右下方 2–4 像素处有阴影"的像素作为字形，再剔除从底边长上来的频谱条。这比换 OCR 模型更管用。

## 避坑清单

- **先裁剪，再分析**：字幕条、水印、评论区、摄像头小窗都会被当成画面变化，用 `--crop` 和 `--mask` 排除。
- **滚动不是翻页**：滚动网页或文档时会被记成 `dynamic` 段，看它的样张即可，不要每帧都 OCR。
- **OCR 读不懂图**：图表、流程图、手写、截图里的 UI，直接把图片交给视觉模型看。
- **专名以画面为准**：标题、产品名、人名在画面上通常是对的，可以拿来纠正语音转写。拿不准时用 `speech-to-text/scripts/score_candidates.py` 确认。
- **内嵌字幕轨**：`input-audit` 或 `media-ingest` 报告有字幕轨时，直接提取，不要 OCR。
