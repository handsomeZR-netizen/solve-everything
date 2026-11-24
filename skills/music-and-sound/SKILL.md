---
name: music-and-sound
description: >-
  Analyse music and non-speech sound: tempo, beats, a downbeat guess, onsets and loudness sections for
  cutting video to music, plus a centre-channel vocal map (mid/side + HPSS) that finds sung phrases and
  draws them as a timed spectrogram with lyric spans, so lyric timing can be checked by eye. Use for MVs,
  lyric videos, karaoke subtitles, beat-synced edits, music analysis, podcasts with music beds, and any
  time a song's timing must line up with text or picture. 节拍、BPM、卡点、歌词对时间轴、人声乐句、MV 剪辑，都用这个。
---

# music-and-sound：节奏、人声和对轴

## 节拍：beats.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/beats.py song.wav --out beats.json [--start 12.5 --dur 60] [--meter 4]
```

输出 `tempo`、`beats`、`downbeats`、`onsets`、按响度分的 `sections`（quiet / mid / loud，至少 4 秒一段）。

- **downbeat 是猜的**：取"每 4 拍中起音最强的那个相位"作为小节起点。卡点剪辑之前，用 `vocal_map.py --beats` 画出来，或者用耳朵确认。
- **速度可能差一倍**：节拍跟踪常把 140 BPM 判成 70，或者反过来。和听感不符时，把 beats 两两合并或插值，不要硬用。
- 实测：合成的 120 BPM 鼓点检测为 117.5 BPM，每拍间隔 0.51 秒；重音相位判断正确。

## 人声地图：vocal_map.py

```bash
python ${CLAUDE_SKILL_DIR}/scripts/vocal_map.py song.wav --png map.png                   # 乐句 -> map.json
python ${CLAUDE_SKILL_DIR}/scripts/vocal_map.py song.wav --png map.png --t0 20 --t1 80 \
    --lyrics lyrics.json --beats beats.json                                                # 叠加歌词和节拍
```

1. **中置声道提取**：主唱通常混在正中间。左右声道做 mid/side，保留 mid 明显强于 side 的频点（软掩码）。
2. **HPSS**：去掉打击乐成分，只留下谐波部分。
3. **乐句检测**：150–4000 Hz 能量做平滑，再用迟滞阈值（高于 0.16 开始、低于 0.09 结束），并合并间隔小于 0.16 秒的乐句。
4. **画图**：每行 20 秒频谱，上面有秒刻度，绿色条是乐句，蓝色刻度是节拍，青色竖线和文字是歌词起止。

实测：合成歌曲中 4 个人声乐句的起止误差都在 0.05 秒以内。

## 歌词对时间轴的推荐流程

1. 有官方 MV、歌词视频的：用 `screen-and-ocr/scripts/burned_subs.py` 直接读出每句歌词的出现时间，这是最准的来源。
2. 没有的：`speech-to-text/scripts/transcribe.py --no-vad --chunk 28 --overlap 2`（VAD 会把歌声当成静音切掉），得到粗略时间；再用 `vocal_map.py` 的乐句边界吸附每句的起止。
3. 把歌词时间写进 `lyrics.json`，叠到 `vocal_map.py` 的图上，用眼睛检查每一行的起点是否落在人声起点上。错位一眼就能看出来。

## 避坑

- `librosa.load` 默认 `sr=22050, mono=True`：会悄悄重采样，并把声道混成单声道。需要左右声道就写 `mono=False`（`vocal_map.py` 已经这么做）。
- mid/side 只对人声居中的立体声混音有效。单声道文件会跳过这一步，只做 HPSS，人声和伴奏分得没那么干净。效果不够时再考虑 Demucs 这类分离模型（需要额外安装，CPU 上很慢）。
- 和声、合唱、双轨叠唱会让乐句边界变宽；说唱段的乐句会碎成很多小段。这两种情况都以听感为准，手动修正。
