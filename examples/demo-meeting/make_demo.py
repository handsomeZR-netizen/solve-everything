#!/usr/bin/env python3
"""Build a small, fully synthetic meeting recording with known ground truth (Windows only).

Three Windows TTS voices play three fictional people in a 90-second project meeting. Three
slides are shown with a moving mouse pointer and a flickering "camera tile" in the corner
(both must be ignored by slide detection), burned-in subtitles at the bottom, low background
noise, and four seconds of silence at the end (a classic place for Whisper to hallucinate).

Outputs in --out (default: ./build):
  demo.mp4      1280x720, 10 fps, AAC mono 16 kHz
  truth.json    every utterance: start, end, speaker, text
  truth.rttm    speaker ground truth, for der.py
  truth.txt     reference transcript, for cer.py
  keywords.txt  names / numbers / terms, for cer.py --keywords
All names and the project are invented.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

VOICES = {"王总": "Microsoft Kangkang", "李工": "Microsoft Huihui", "小陈": "Microsoft Yaoyao"}
# (slide, speaker, text shown/ground truth, text spoken by TTS)
SCRIPT = [
    (0, "王总", "好，我们开始。今天就三件事：上线时间、接口性能，还有服务器预算。", None),
    (0, "小陈", "原定12月1号上线，客户那边已经在问了。", "原定十二月一号上线，客户那边已经在问了。"),
    (1, "李工", "现在接口的P99是800毫秒，目标是300毫秒以内。按现在的进度，12月1号肯定来不及。",
     "现在接口的P九十九是八百毫秒，目标是三百毫秒以内。按现在的进度，十二月一号肯定来不及。"),
    (1, "王总", "那最晚什么时候能好？", None),
    (1, "李工", "我12月5号之前出压测报告。如果顺利，12月15号可以上线。",
     "我十二月五号之前出压测报告。如果顺利，十二月十五号可以上线。"),
    (1, "王总", "行，那就定12月15号，前提是P99降到300毫秒以下。小陈，你这周五之前通知客户。",
     "行，那就定十二月十五号，前提是P九十九降到三百毫秒以下。小陈，你这周五之前通知客户。"),
    (1, "小陈", "好的，我周五前发邮件。", None),
    (2, "李工", "另外，压测还需要再加两台服务器，大概4.8万。", "另外，压测还需要再加两台服务器，大概四万八。"),
    (2, "王总", "这个我要再看一下预算，下周一给答复。", None),
    (2, "小陈", "那我先按两台准备采购单，等王总确认。", None),
]
SLIDES = [
    ("北极星项目 · 周会", ["2026-11-24", "议程", "1. 上线时间", "2. 接口性能", "3. 服务器预算"]),
    ("接口性能", ["当前 P99：800 ms", "目标 P99：≤ 300 ms", "压测报告：12/5 前"]),
    ("服务器预算", ["追加压测服务器 2 台", "预估 4.8 万元", "待审批"]),
]
KEYWORDS = ["北极星", "王总", "李工", "小陈", "P99", "800毫秒", "300毫秒", "12月1号", "12月5号", "12月15号",
            "压测报告", "周五", "4.8万", "下周一", "采购单"]


def font(size):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    sys.exit("needs a Chinese font (msyh.ttc)")


def tts(lines, folder):
    """Synthesise each line with Windows SAPI into 16 kHz mono wav files."""
    jobs = [{"voice": VOICES[spk], "text": spoken or text, "path": os.path.join(folder, f"u{i:02d}.wav")}
            for i, (_, spk, text, spoken) in enumerate(lines)]
    spec = os.path.join(folder, "jobs.json")
    json.dump(jobs, open(spec, "w", encoding="utf-8"), ensure_ascii=False)
    ps = r"""
Add-Type -AssemblyName System.Speech
$jobs = Get-Content -Raw -Encoding UTF8 '%s' | ConvertFrom-Json
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($j in $jobs) {
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $s.SelectVoice($j.voice); $s.Rate = 1
  $s.SetOutputToWaveFile($j.path, $fmt); $s.Speak($j.text); $s.Dispose()
}
""" % spec.replace("'", "''")
    script = os.path.join(folder, "tts.ps1")
    open(script, "w", encoding="utf-8-sig").write(ps)
    # PowerShell 7 (pwsh) sees the OneCore voices (Kangkang, Yaoyao); Windows PowerShell 5 only sees Huihui
    import shutil
    shell = shutil.which("pwsh") or "powershell"
    subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script], check=True)
    import soundfile as sf
    return [sf.read(j["path"], dtype="float32")[0] for j in jobs]


def draw_slide(k, t, sub, f_title, f_body, f_sub, rng):
    W, H = 1280, 720
    im = Image.new("RGB", (W, H), (246, 247, 250))
    d = ImageDraw.Draw(im)
    title, body = SLIDES[k]
    d.rectangle([0, 0, W, 96], fill=(31, 58, 110))
    d.text((60, 22), title, font=f_title, fill=(255, 255, 255))
    for i, line in enumerate(body):
        d.text((80, 150 + i * 70), line, font=f_body, fill=(30, 34, 44))
    d.text((W - 120, 610), f"{k + 1}/3", font=f_body, fill=(150, 150, 160))
    # camera tile (top right) with changing noise: must be masked out
    tile = (rng.random((90, 160)) * 80 + 60).astype(np.uint8)
    im.paste(Image.fromarray(tile).convert("RGB"), (W - 176, 8))
    # mouse pointer wandering over the slide: must be ignored by the area threshold
    px, py = 640 + 300 * np.sin(t * 0.7), 380 + 120 * np.cos(t * 1.1)
    d.polygon([(px, py), (px, py + 22), (px + 6, py + 16), (px + 14, py + 24)], fill=(10, 10, 10))
    # burned-in subtitle band
    d.rectangle([0, 640, W, 720], fill=(18, 18, 18))
    if sub:
        w = d.textlength(sub, font=f_sub)
        d.text(((W - w) / 2, 656), sub, font=f_sub, fill=(255, 255, 255))
    return im


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="build")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    sr, fps = 16000, 10
    with tempfile.TemporaryDirectory() as tmp:
        clips = tts(SCRIPT, tmp)
    gap, lead = 0.6, 1.0
    pieces, truth, t = [np.zeros(int(lead * sr), np.float32)], [], lead
    for (slide, spk, text, _), clip in zip(SCRIPT, clips):
        truth.append({"start": round(t, 2), "end": round(t + len(clip) / sr, 2), "speaker": spk,
                      "slide": slide, "text": text})
        pieces += [clip, np.zeros(int(gap * sr), np.float32)]
        t += len(clip) / sr + gap
    pieces.append(np.zeros(int(4.0 * sr), np.float32))  # trailing silence
    audio = np.concatenate(pieces)
    rng = np.random.default_rng(7)
    audio = (audio * 0.8 + rng.normal(0, 0.002, len(audio))).astype(np.float32)
    dur = len(audio) / sr

    import soundfile as sf
    wav = os.path.join(args.out, "_audio.wav")
    sf.write(wav, audio, sr)
    slide_start = {}
    for u in truth:
        slide_start.setdefault(u["slide"], u["start"] - 0.3)
    f_title, f_body, f_sub = font(46), font(38), font(30)
    mp4 = os.path.join(args.out, "demo.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1280x720", "-r", str(fps),
           "-i", "-", "-i", wav, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-c:a", "aac",
           "-b:a", "96k", "-shortest", mp4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(int(dur * fps) + 1):
        tt = i / fps
        k = max([s for s, st in slide_start.items() if st <= tt] or [0])
        sub = next((u["text"] for u in truth if u["start"] <= tt < u["end"] + 0.2), "")
        proc.stdin.write(draw_slide(k, tt, sub, f_title, f_body, f_sub, rng).tobytes())
    proc.stdin.close()
    proc.wait()
    os.remove(wav)

    json.dump(truth, open(os.path.join(args.out, "truth.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "truth.rttm"), "w", encoding="utf-8") as fh:
        for u in truth:
            fh.write(f"SPEAKER demo 1 {u['start']:.2f} {u['end'] - u['start']:.2f} <NA> <NA> {u['speaker']} <NA> <NA>\n")
    open(os.path.join(args.out, "truth.txt"), "w", encoding="utf-8").write("".join(u["text"] for u in truth))
    open(os.path.join(args.out, "keywords.txt"), "w", encoding="utf-8").write("\n".join(KEYWORDS) + "\n")
    print(f"{mp4}: {dur:.1f}s, {len(truth)} utterances, 3 speakers, 3 slides")


if __name__ == "__main__":
    main()
