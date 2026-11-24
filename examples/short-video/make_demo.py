#!/usr/bin/env python3
"""Build the synthetic test inputs with known ground truth.

1) inputs/clip.mp4: a 1-minute knowledge short video (Windows only: uses Windows TTS)
   - one narrator over a 96 BPM beat, music-only intro and outro (a place where ASR hallucinates)
   - 5 content cards plus 2 cards that flash for about a second with information that is
     NEVER spoken (a comment-section code and a livestream time): the classic thing a
     model that samples a few frames will miss
   - burned-in subtitles of the narration
2) document-style inputs that hide content from a quick read (cross-platform):
   report.pdf (page 2 is a scanned image), long_screenshot.png (1200x5000),
   deck.pptx (speaker notes + a hidden slide), notes.docx (a comment + an embedded image),
   data.xlsx (a hidden sheet)

Ground truth goes to truth/: narration.json / narration.txt, screen.json, keywords.txt, beats.json.
Everything is invented for testing.

usage: python make_demo.py --out build [--no-video]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

VOICE = "Microsoft Yaoyao"
# (card index, text shown as subtitle / truth, text spoken by TTS or None)
NARRATION = [
    (0, "你把一段视频丢给大模型，它真的看完了吗？", None),
    (0, "很多时候它只抽了十几帧，中间一闪而过的字，它根本没看到。", None),
    (1, "第一步，先盘点输入：视频多长，有几条音轨，PDF有几页。", "第一步，先盘点输入：视频多长，有几条音轨，P D F 有几页。"),
    (2, "第二步，全量转写，每一秒有声音的地方，都要有对应的文字。", None),
    (2, "转写里的幻觉句子要标出来，不能直接相信。", None),
    (3, "第三步，对账：哪些画面、哪些页、哪些片段没被处理，列成清单。", None),
    (4, "做到这三步，再让模型总结，结果才靠得住。", None),
]
CARDS = [
    ("LLM 真的看完你的视频了吗？", ["一段不到一分钟的短视频", "模型到底读到了多少？"]),
    ("第 1 步 · 盘点", ["时长 · 音轨 · 帧率", "页数 · 扫描页 · 隐藏内容"]),
    ("第 2 步 · 全量转写", ["有声音的每一秒都要有文字", "幻觉句标出来"]),
    ("第 3 步 · 对账", ["没处理的画面 / 页 / 片段", "列成清单再下结论"]),
    ("结果才靠得住", ["先榨干输入", "再要求输出"]),
]
FLASHES = [  # (after narration line i, duration s, title, lines): on screen only, never spoken
    (2, 1.2, "评论区口令", ["SE-0618"]),
    (5, 1.0, "下次直播", ["12 月 6 日 20:00"]),
]
KEYWORDS = ["大模型", "十几帧", "盘点", "音轨", "PDF", "全量转写", "幻觉", "对账", "清单", "总结"]
BPM = 96


def font(size):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "/System/Library/Fonts/PingFang.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    sys.exit("needs a CJK font")


def tts(lines, folder):
    jobs = [{"voice": VOICE, "text": spoken or text, "path": os.path.join(folder, f"u{i:02d}.wav")}
            for i, (_, text, spoken) in enumerate(lines)]
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
    shell = shutil.which("pwsh") or "powershell"  # pwsh sees the OneCore voices
    subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script], check=True)
    import soundfile as sf
    return [sf.read(j["path"], dtype="float32")[0] for j in jobs]


def beat_track(n, sr, bpm):
    t = np.arange(n) / sr
    out = np.zeros(n, np.float32)
    step = 60.0 / bpm
    rng = np.random.default_rng(3)
    k = 0
    for b in np.arange(0.0, n / sr, step / 2):
        i = int(b * sr)
        if k % 2 == 0:  # kick on the beat, accent every 4 beats
            m = min(n - i, int(0.15 * sr))
            env = np.exp(-np.arange(m) / sr * 25) * (1.0 if (k // 2) % 4 == 0 else 0.7)
            out[i:i + m] += (np.sin(2 * np.pi * 55 * np.arange(m) / sr) * env).astype(np.float32)
        m = min(n - i, int(0.04 * sr))  # hi-hat on every half beat
        out[i:i + m] += (rng.normal(0, 0.15, m) * np.exp(-np.arange(m) / sr * 120)).astype(np.float32)
        k += 1
    return out, [round(float(b), 3) for b in np.arange(0.0, n / sr, step)]


def draw(card, flash, sub, t, F):
    W, H = 1280, 720
    im = Image.new("RGB", (W, H), (14, 18, 32))
    d = ImageDraw.Draw(im)
    for y in range(0, H, 4):  # soft vertical gradient
        c = int(14 + 18 * y / H)
        d.line([0, y, W, y], fill=(c, c + 4, c + 22))
    title, lines = flash if flash else CARDS[card]
    if flash:
        d.rounded_rectangle([200, 150, 1080, 520], 28, fill=(250, 204, 21))
        d.text((640, 230), title, font=F["mid"], fill=(30, 30, 30), anchor="mm")
        d.text((640, 360), lines[0], font=F["huge"], fill=(20, 20, 20), anchor="mm")
    else:
        d.text((80, 90), title, font=F["big"], fill=(248, 250, 252))
        d.rectangle([80, 170, 80 + 120, 176], fill=(244, 114, 182))
        for i, line in enumerate(lines):
            d.text((90, 240 + i * 80), "· " + line, font=F["mid"], fill=(203, 213, 225))
        d.text((1150, 560), f"{card + 1}/5", font=F["small"], fill=(100, 116, 139))
    # a pulsing dot (like a live/recording indicator): small change, must not count as a new screen
    r = 8 + 4 * np.sin(t * 6)
    d.ellipse([1220 - r, 40 - r, 1220 + r, 40 + r], fill=(239, 68, 68))
    d.rectangle([0, 620, W, 720], fill=(0, 0, 0))
    if sub:
        d.text((640, 670), sub, font=F["sub"], fill=(255, 255, 255), anchor="mm")
    return im


def make_video(out, truth_dir):
    sr, fps = 16000, 10
    with tempfile.TemporaryDirectory() as tmp:
        clips = tts(NARRATION, tmp)
    lead, gap, tail = 2.0, 0.7, 4.0
    flash_after = {i: (d, ti, li) for i, d, ti, li in FLASHES}
    t, pieces = lead, [np.zeros(int(lead * sr), np.float32)]
    narration, screen, timeline = [], [], []  # timeline: (start, end, card, flash)
    card_start = {0: 0.0}
    for i, ((card, text, _), clip) in enumerate(zip(NARRATION, clips)):
        if card not in card_start:
            card_start[card] = t - 0.3
        narration.append({"start": round(t, 2), "end": round(t + len(clip) / sr, 2), "text": text})
        pieces += [clip, np.zeros(int(gap * sr), np.float32)]
        t += len(clip) / sr + gap
        if i in flash_after:  # silent pause while the flash card is up
            d, ti, li = flash_after[i]
            timeline.append((t, t + d, None, (ti, li)))
            pieces.append(np.zeros(int((d + 0.4) * sr), np.float32))
            t += d + 0.4
    pieces.append(np.zeros(int(tail * sr), np.float32))
    voice = np.concatenate(pieces)
    beats, beat_times = beat_track(len(voice), sr, BPM)
    mix = (voice * 0.9 + beats * 0.12).astype(np.float32)
    mix += np.random.default_rng(1).normal(0, 0.002, len(mix)).astype(np.float32)
    dur = len(mix) / sr

    import soundfile as sf
    wav = os.path.join(out, "_mix.wav")
    sf.write(wav, mix, sr)
    order = sorted(card_start.items(), key=lambda kv: kv[1])
    for k, (card, st) in enumerate(order):
        en = order[k + 1][1] if k + 1 < len(order) else dur
        for fs, fe, _, _ in timeline:  # a flash covers the card: the card is visible only before it
            if st < fs < en:
                en = fs
        screen.append({"start": round(max(0.0, st), 2), "end": round(en, 2), "kind": "card",
                       "text": CARDS[card][0] + " / " + " / ".join(CARDS[card][1])})
    for st, en, _, (ti, li) in timeline:
        screen.append({"start": round(st, 2), "end": round(en, 2), "kind": "flash", "text": ti + " / " + li[0]})
    screen.sort(key=lambda s: s["start"])

    F = {"huge": font(110), "big": font(60), "mid": font(42), "small": font(28), "sub": font(32)}
    mp4 = os.path.join(out, "clip.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1280x720", "-r", str(fps),
           "-i", "-", "-i", wav, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "22", "-c:a", "aac", "-b:a", "128k",
           "-shortest", mp4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(int(dur * fps) + 1):
        tt = i / fps
        flash = next((fl for st, en, _, fl in timeline if st <= tt < en), None)
        card = max([c for c, st in card_start.items() if st <= tt] or [0], key=lambda c: card_start[c])
        sub = next((u["text"] for u in narration if u["start"] <= tt < u["end"] + 0.2), "")
        proc.stdin.write(draw(card, flash, sub, tt, F).tobytes())
    proc.stdin.close()
    proc.wait()
    os.remove(wav)
    json.dump(narration, open(os.path.join(truth_dir, "narration.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(truth_dir, "narration.txt"), "w", encoding="utf-8").write("".join(u["text"] for u in narration))
    json.dump(screen, open(os.path.join(truth_dir, "screen.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"bpm": BPM, "beats": beat_times}, open(os.path.join(truth_dir, "beats.json"), "w", encoding="utf-8"))
    open(os.path.join(truth_dir, "keywords.txt"), "w", encoding="utf-8").write("\n".join(KEYWORDS) + "\n")
    print(f"{mp4}: {dur:.1f}s, {len(narration)} narration lines, {len(screen)} on-screen items "
          f"({sum(1 for s in screen if s['kind'] == 'flash')} flashes)")


def make_documents(out):
    F = font(30)
    # report.pdf: page 1 has a text layer, page 2 is a scanned image
    try:
        import fitz
        doc = fitz.open()
        p = doc.new_page()
        p.insert_text((72, 80), "示例报告：输入审计", fontname="china-s", fontsize=20)
        p.insert_text((72, 120), "本页有文字层，任何 PDF 读取工具都能读到。", fontname="china-s", fontsize=11)
        p.insert_text((72, 140), "第 2 页是扫描件：只读文字层时，它是一张白纸。", fontname="china-s", fontsize=11)
        scan = Image.new("RGB", (1240, 1754), "white")
        ImageDraw.Draw(scan).text((120, 220), "附件（扫描）：结论以本页为准，预算上限 3.5 万元", font=font(44), fill="black")
        tmp = os.path.join(out, "_scan.jpg")
        scan.save(tmp, quality=85)
        doc.new_page().insert_image(fitz.Rect(0, 0, 595, 842), filename=tmp)
        doc.save(os.path.join(out, "report.pdf"))
        os.remove(tmp)
    except ImportError:
        print("pymupdf missing: skipped report.pdf")
    # long screenshot: 1200 x 5000, key line near the bottom
    img = Image.new("RGB", (1200, 5000), (248, 248, 248))
    d = ImageDraw.Draw(img)
    for i in range(58):
        d.text((40, 40 + i * 84), f"第 {i + 1} 条消息：这是一张很长的聊天记录截图，用来测试缩放。", font=F, fill=(40, 40, 40))
    d.text((40, 4920), "最后一条：交付时间改到周四下午三点", font=F, fill=(200, 30, 30))
    img.save(os.path.join(out, "long_screenshot.png"))
    # deck.pptx: speaker notes + a hidden slide
    try:
        from pptx import Presentation
        prs = Presentation()
        s1 = prs.slides.add_slide(prs.slide_layouts[1])
        s1.shapes.title.text = "方案对比"
        s1.placeholders[1].text = "A 方案：快\nB 方案：稳"
        s1.notes_slide.notes_text_frame.text = "演讲备注：其实我们已经决定选 B，A 只是陪衬。"
        s2 = prs.slides.add_slide(prs.slide_layouts[1])
        s2.shapes.title.text = "备用页：风险清单"
        s2.placeholders[1].text = "供应商可能延期两周"
        s2._element.set("show", "0")
        prs.save(os.path.join(out, "deck.pptx"))
    except ImportError:
        print("python-pptx missing: skipped deck.pptx")
    # notes.docx: a comment + an embedded image
    try:
        import docx
        from docx.shared import Inches
        d2 = docx.Document()
        para = d2.add_paragraph("正文：按原计划推进。")
        thumb = os.path.join(out, "_thumb.png")
        Image.new("RGB", (400, 120), (255, 240, 200)).save(thumb)
        d2.add_picture(thumb, width=Inches(3))
        os.remove(thumb)
        try:
            d2.add_comment(para.runs, text="批注：这一条要改，先别发。", author="reviewer")
        except Exception:
            print("this python-docx cannot add comments: notes.docx has no comment")
        d2.save(os.path.join(out, "notes.docx"))
    except ImportError:
        print("python-docx missing: skipped notes.docx")
    # data.xlsx: a hidden sheet
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "汇总"
        ws.append(["项目", "金额"]); ws.append(["A", 100])
        h = wb.create_sheet("原始数据")
        h.append(["项目", "金额"]); h.append(["A", 130])
        h.sheet_state = "hidden"
        wb.save(os.path.join(out, "data.xlsx"))
    except ImportError:
        print("openpyxl missing: skipped data.xlsx")
    print(f"documents -> {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="build"); ap.add_argument("--no-video", action="store_true")
    args = ap.parse_args()
    inputs, truth = os.path.join(args.out, "inputs"), os.path.join(args.out, "truth")
    os.makedirs(inputs, exist_ok=True)
    os.makedirs(truth, exist_ok=True)
    make_documents(inputs)
    if not args.no_video:
        make_video(inputs, truth)


if __name__ == "__main__":
    main()
