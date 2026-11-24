---
name: screen-and-ocr
description: >-
  Read what is on screen: detect slide / page changes in screen recordings and lecture videos (ignoring
  mouse pointer, camera tiles and chat panels, linking bullet-by-bullet builds, flagging scrolling and
  video playback), save one clean frame per page, OCR images in proper reading order with RapidOCR on
  CPU, and recover burned-in (hard) subtitles with their on-screen times as SRT. Use whenever text lives
  inside pixels: shared slides in a meeting recording, lecture captures, tutorial videos, lyric videos and
  MVs, film subtitles, screenshots, photographed whiteboards and scanned pages. 录屏/PPT 翻页检测、屏幕文字、
  OCR、硬字幕提取、歌词字幕对时间轴、截图识字，都用这个。
---

# screen-and-ocr：屏幕上的字

会议里很多关键信息只出现在屏幕上：PPT 上的数字、表格、项目名的正确写法。把它们读出来，有两个用处：一是补充语音里没说的内容，二是**纠正语音识别的错字**。

## 1. 翻页检测：slide_changes.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/slide_changes.py talk.mp4 --out slides/ \
    --crop 0,0,1600,900 \          # 共享屏幕区域（排除字幕条、会议软件边栏）
    --mask 1600,0,320,180          # 要忽略的区域：摄像头小窗、弹幕、聊天区（可重复）
```

工作方式：

- 从 ffmpeg 流式读入 192 px 宽的灰度缩略图，内存占用不随视频长度增长。
- 一帧里变化像素超过 `--area`（默认 1.2%）才算"在变"，所以鼠标指针移动不会触发翻页。
- 进入变化状态后，要等画面静止 `--settle` 秒才算新的一页。静止下来的画面如果和原页一样（弹窗出现又消失），就不切页。
- 变化持续超过 `--dynamic` 秒（滚动网页、播放视频）记为 `dynamic` 段，每隔 `--dyn-every` 秒抽一帧样张。
- 新增内容只落在原先的空白背景上、且面积不大的，判定为同一页的逐条动画（build），用同一个 `group` 串起来，`complete: true` 的那一帧内容最全。
- 每一页保存一张全分辨率截图，选的是**翻页前的最后一个静止帧**，因为有逐条动画时这一帧内容最全。

实测（合成演示，带移动的鼠标指针和不断闪动的摄像头小窗）：3 页全部检出，翻页时刻误差在半秒以内，没有误报。

## 2. OCR：ocr.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/ocr.py --segments slides/segments.json   # 给每页填 ocr 字段
python ${CLAUDE_SKILL_DIR}/scripts/ocr.py shot1.png shots/ --out ocr.json     # 任意图片 / 文件夹
```

在 RapidOCR（PaddleOCR 模型的 ONNX 版）之上做了这些事：

- **自动放大，但有条件**：默认先按原尺寸识别，结果弱（没有文字或最低分 < 0.8）且图片短边 < 720 时，再放大 2 倍识别一次，取更好的那个。实测：30 px 高的字幕放大 2 倍后，检测反而失败、整行丢失；而 20 px 以下的小字不放大又会认错。所以不能一律放大。
- **阅读顺序**：按纵坐标把框聚成行，行内按横坐标排序。检测到竖直分栏的空白（gutter）时，先读左栏再读右栏；跨栏的标题放在最前面。
- **低分过滤**：score < 0.5 的框大多是乱码，丢弃并计数。
- **兼容两个包名**：旧的 `rapidocr_onnxruntime` 和新的 `rapidocr`，接口不同，脚本都支持。论文复现要锁定版本。

## 3. 硬字幕：burned_subs.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/burned_subs.py video.mp4 --crop 0,640,1280,80 --out subs/
python ${CLAUDE_SKILL_DIR}/scripts/burned_subs.py mv.mp4 --crop 0,600,1280,120 --mode outline --fps 8 --out subs/
```

- `median` 模式：字幕条背景取全片的逐像素中值，"比背景亮且差异大"的像素就是字形。适合静态或变化慢的背景（会议、歌词 MV、静态封面）。
- `outline` 模式：亮像素紧挨着暗描边或阴影的就是字形。适合背景是运动画面的影视剧。
- 相邻帧字形掩码的 IoU 低于 0.5 就算换了一句，所以两句之间没有空隙也能切开。每句选**文字像素最多的一帧**（完全淡入后）去 OCR。
- 输出 `subs.json`、`subs.srt` 和每 20 句一页的拼图（截图 + 时间 + 识别结果），方便一眼核对。

实测（合成演示）：10 句全部切准、识别正确，只有一句末尾多出一个"．"。

花体、斜体、带阴影的字要自己做掩码。例子：白墙背景上的白色斜体字带灰色阴影时，可以找"右下方 2–4 像素处有阴影"的像素作为字形，再剔除从底边长上来的频谱条。这比换 OCR 模型更管用。

## 避坑清单

- **先裁剪，再分析**：字幕条、会议软件的边栏、摄像头小窗都会被当成翻页，用 `--crop` 和 `--mask` 排除。
- **共享屏幕在滚动**：这不是翻页，但画面一直在变，会被记成 `dynamic` 段。看它的样张就够了，不要每帧都 OCR。
- **OCR 读不懂图**：柱状图、流程图、白板手写、截图里的 UI，直接把图片交给视觉模型看。表格可以先 OCR，再看图确认行列关系。
- **专名以屏幕为准**：项目名、产品名、人名在 PPT 上通常是对的，拿它去纠正语音转写（必要时用 `speech-to-text/scripts/score_candidates.py` 确认）。
- **颜色顺序**：引擎按 OpenCV 习惯吃 BGR。脚本已从 PIL 的 RGB 转成 BGR；自己调用引擎时注意。
- **嵌入的字幕轨**：`media-ingest/scripts/probe.py` 如果报告有字幕轨，直接提取，不要 OCR。
