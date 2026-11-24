---
name: media-ingest
description: >-
  Probe and unpack any audio/video file with ffprobe/ffmpeg before processing it: duration, streams,
  start_time, variable frame rate, rotation, multiple audio tracks, embedded subtitles; then extract a
  16 kHz mono wav, frames at a fixed rate (optionally cropped/scaled), single frames, or subtitle tracks.
  Use this whenever a recording, video, screen capture, livestream dump or voice memo is the input to
  anything else (ASR, OCR, minutes, subtitles, analysis), and whenever audio and video timings must line
  up. 拿到任何音视频文件、要转写/抽帧/抽音轨/对时间轴之前先用：先体检（probe），再提取（extract）。
---

# media-ingest：先体检，再拆封装

下游所有工具（ASR、OCR、对齐）都假设输入是干净的：一条音轨、固定帧率、时间从 0 开始。真实文件常常不是这样，而这些问题出错时不报错，只会让结果悄悄偏掉。所以第一步永远是 probe。

## 1. 体检

```bash
python ${CLAUDE_SKILL_DIR}/scripts/probe.py meeting.mp4          # 可读摘要 + warnings
python ${CLAUDE_SKILL_DIR}/scripts/probe.py meeting.mp4 --json   # 给程序用
```

逐条处理 warnings，常见的有：

| warning | 意味着什么 | 怎么办 |
|---|---|---|
| 多条音轨 | 录屏软件常把麦克风和系统声分开 | 各抽一条听 10 秒，选对的 `--track N`；两边都有人说话就分别转写再合并 |
| container start_time ≠ 0 | 不同工具算出的时间可能整体差这么多 | 音频和帧都用本脚本、同一个 `--ss` 提取 |
| 视频比音频晚/早 x 秒 | A/V 起点不同 | 融合时用 `fuse.py --shift-video` 补偿 |
| 可变帧率 (VFR) | 手机、会议软件录像常见；用帧序号推时间会漂 | 永远用 fps 滤镜重采样（本脚本就是这么做的），不要 `帧号/标称fps` |
| rotation | 手机竖拍 | ffmpeg 解码时已自动旋转，裁剪坐标按旋转后的画面算 |
| 内嵌字幕轨 | 已经有现成文本 | `extract.py subs`，比 OCR、ASR 都准 |
| 只有封面图 | 其实是音频文件 | 跳过所有视觉步骤 |

## 2. 提取

```bash
# 音频：16 kHz 单声道 PCM，会议加 --loudnorm 让小声的人也能被识别
python ${CLAUDE_SKILL_DIR}/scripts/extract.py audio  in.mp4 audio.wav --loudnorm [--track 1] [--ss 60 --t 300]
# 音乐分析要保留立体声
python ${CLAUDE_SKILL_DIR}/scripts/extract.py audio  song.mp4 song.wav --stereo --sr 22050
# 定频抽帧：先裁剪、缩放再输出，Python 只处理需要的区域；index.json 记录每帧时间
python ${CLAUDE_SKILL_DIR}/scripts/extract.py frames in.mp4 frames/ --fps 1 --crop 0,0,1600,900 --width 960
# 某一时刻的单帧
python ${CLAUDE_SKILL_DIR}/scripts/extract.py frame  in.mp4 754.2 shot.png --crop 140,526,1000,60
# 内嵌字幕轨
python ${CLAUDE_SKILL_DIR}/scripts/extract.py subs   in.mkv subs.srt --track 0
```

时间约定：`frames` 输出的第 i 帧时间是 `ss + i/fps`（fps 滤镜取最近帧，误差 ≤ 半帧）。

## 3. 避坑清单

- **内存**：一次性把所有帧读进内存，四分钟的歌没事，两小时 1080p 会议每秒 1 帧就是约 22 GB。要么像本 skill 和 `screen-and-ocr` 那样用管道边读边算，要么先在 ffmpeg 里 `crop` + `scale` 把帧变小。
- **`-ss` 放在 `-i` 前面**：快，而且在需要解码的场景下是精确的。但每个时间点都起一次 ffmpeg 很慢，要几百个时间点就改用一次 fps 滤镜批量抽。
- **解码音频别依赖 PyAV**：faster-whisper 自带的 `decode_audio` 走 PyAV，PyAV 19 起它直接报 `unexpected keyword argument 'metadata_errors'`。本仓库所有脚本都改用 `ffmpeg ... -f f32le -` 管道解码，任何能被 ffmpeg 打开的格式都行。
- **Windows 中文路径**：`cv2.imread` / `cv2.imwrite` 遇到中文路径会静默返回 None / False。用 PIL，或 `cv2.imdecode(np.fromfile(p, np.uint8), 1)` 和 `cv2.imencode('.png', img)[1].tofile(p)`。打印中文前 `sys.stdout.reconfigure(encoding="utf-8")`。
- **响度**：多人会议里离麦远的人音量可能低 15 dB 以上。`--loudnorm`（EBU R128 单遍）通常比任何降噪都更能提升识别率。不要默认加强降噪：ASR 模型见过大量带噪语音，降噪带来的伪影反而让识别变差、幻觉变多。要降噪就做 A/B，对比 CER。
- **采样率**：低于 16 kHz 的电话录音识别率会明显下降，probe 会提示；这种情况下 hotwords 和人工核对更重要。
- **超长文件**：3 小时以上建议先按议程或静音切成几段分别处理，每段保留在原文件中的起始偏移。
