#!/usr/bin/env python3
"""One command: any audio or video -> audited, fused, checkable input for an LLM.

Steps (each skipped when its output exists, so long runs resume; --force redoes all):
  0 inventory   work/ledger.md                  input-audit/inventory.py     (what is in there, what a quick pass drops)
  1 audio       work/audio.wav                  media-ingest/extract.py      (16 kHz mono, loudness-normalised)
  2 asr         work/asr.jsonl                  speech-to-text/transcribe.py
  3 speakers    work/turns.jsonl                speaker-diarization/*        (only with --speakers N, --diarize or --diar FILE)
  4 screen      work/slides/segments.json       screen-and-ocr/slide_changes.py + ocr.py   (video only)
  5 subtitles   work/subs/subs.json             screen-and-ocr/burned_subs.py               (only with --subs-crop)
  6 music       work/beats.json                 music-and-sound/beats.py                    (only with --music)
  7 timeline    work/timeline.jsonl + .md       timeline-fusion/fuse.py
  8 pictures    work/plots/timeline_XX.png      visual-verify/timeline_plot.py
  9 coverage    work/coverage.md                input-audit/coverage.py      (exit code 1 if below --min)
Then the LLM reads work/ledger.md, work/coverage.md, work/timeline.md and the pictures, and writes
the output with expressive-output.

usage:
  python run_pipeline.py clip.mp4 --work work/
  python run_pipeline.py lecture.mp4 --work work/ --crop 0,0,1600,900 --mask 1600,0,320,180 --hotwords "傅里叶 卷积"
  python run_pipeline.py podcast.m4a --work work/ --speakers 2
  python run_pipeline.py mv.mp4 --work work/ --subs-crop 0,600,1280,120 --music --no-vad
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]


def script(skill, name):
    p = SKILLS / skill / "scripts" / name
    if not p.exists():
        sys.exit(f"missing {p}: install the whole solve-everything plugin, not this skill alone")
    return str(p)


def step(title, out, cmd, force, check=True):
    if out and os.path.exists(out) and not force:
        print(f"[skip] {title}: {out} exists")
        return 0
    print(f"[run ] {title}", flush=True)
    t = time.time()
    res = subprocess.run([sys.executable] + cmd)
    if check and res.returncode != 0:
        sys.exit(f"step '{title}' failed (exit {res.returncode})")
    print(f"[done] {title} in {time.time() - t:.0f}s", flush=True)
    return res.returncode


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("media"); ap.add_argument("--work", required=True); ap.add_argument("--title")
    ap.add_argument("--track", type=int, default=0, help="audio track (the inventory lists them)")
    ap.add_argument("--model", default="large-v3-turbo"); ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--lang", default="zh"); ap.add_argument("--hotwords"); ap.add_argument("--prompt")
    ap.add_argument("--no-vad", action="store_true", help="singing / whispering: chunked decoding without VAD")
    ap.add_argument("--speakers", type=int, default=0, help="number of speakers (turns on diarization)")
    ap.add_argument("--diarize", action="store_true", help="diarize with an unknown speaker count")
    ap.add_argument("--diar", help="existing RTTM / JSON diarization from a stronger backend")
    ap.add_argument("--names", help='JSON {"SPK_0": "name"} confirmed by a human')
    ap.add_argument("--crop", help="screen area to watch for changes, x,y,w,h")
    ap.add_argument("--mask", action="append", default=[], help="area to ignore (camera tile, chat panel)")
    ap.add_argument("--subs-crop", help="burned-in subtitle band x,y,w,h (turns on subtitle extraction)")
    ap.add_argument("--music", action="store_true", help="also analyse tempo / beats")
    ap.add_argument("--skip-video", action="store_true")
    ap.add_argument("--min", type=float, default=0.98, help="coverage threshold for the final audit")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    w = Path(args.work)
    w.mkdir(parents=True, exist_ok=True)
    f = args.force
    ledger = str(w / "ledger.json")
    step("inventory", ledger, [script("input-audit", "inventory.py"), args.media, "--out", ledger,
                               "--md", str(w / "ledger.md")], f)
    entry = json.loads(Path(ledger).read_text(encoding="utf-8"))["inputs"][0]
    has_video = entry["type"] == "video" and not args.skip_video
    for r in entry["risks"]:
        if r["severity"] != "info":
            print(f"[risk] {r['code']}: {r['detail']}")

    audio = str(w / "audio.wav")
    step("audio", audio, [script("media-ingest", "extract.py"), "audio", args.media, audio,
                          "--track", str(args.track), "--loudnorm"], f)
    asr = str(w / "asr.jsonl")
    cmd = [script("speech-to-text", "transcribe.py"), audio, "--out", asr, "--model", args.model,
           "--lang", args.lang, "--threads", str(args.threads)]
    if args.local_only:
        cmd.append("--local-only")
    if args.hotwords:
        cmd += ["--hotwords", args.hotwords]
    if args.prompt:
        cmd += ["--prompt", args.prompt]
    if args.no_vad:
        cmd += ["--no-vad", "--chunk", "28", "--overlap", "2"]
    step("asr", asr, cmd, f)

    speech_src = asr
    if args.speakers or args.diarize or args.diar:
        diar = args.diar or str(w / "diar.rttm")
        if not args.diar:
            cmd = [script("speaker-diarization", "diarize_lite.py"), audio, "--asr", asr, "--out", diar]
            if args.speakers:
                cmd += ["--speakers", str(args.speakers)]
            step("speakers (lite baseline)", diar, cmd, f)
        speech_src = str(w / "turns.jsonl")
        cmd = [script("speaker-diarization", "merge_speakers.py"), "--asr", asr, "--diar", diar, "--out", speech_src]
        if args.names:
            cmd += ["--names", args.names]
        step("turns", speech_src, cmd, f or bool(args.names))

    slides_json = subs_json = None
    if has_video:
        sd = w / "slides"
        slides_json = str(sd / "segments.json")
        cmd = [script("screen-and-ocr", "slide_changes.py"), args.media, "--out", str(sd)]
        if args.crop:
            cmd += ["--crop", args.crop]
        for m in args.mask:
            cmd += ["--mask", m]
        step("screen changes", slides_json, cmd, f)
        segs = json.loads(Path(slides_json).read_text(encoding="utf-8"))
        if f or not any("ocr" in s for s in segs):
            step("screen OCR", None, [script("screen-and-ocr", "ocr.py"), "--segments", slides_json], True)
        if args.subs_crop:
            subs_json = str(w / "subs" / "subs.json")
            step("burned-in subtitles", subs_json, [script("screen-and-ocr", "burned_subs.py"), args.media,
                                                    "--crop", args.subs_crop, "--out", str(w / "subs")], f)
    if args.music:
        step("beats", str(w / "beats.json"), [script("music-and-sound", "beats.py"), audio,
                                              "--out", str(w / "beats.json")], f)

    tl, md = str(w / "timeline.jsonl"), str(w / "timeline.md")
    cmd = [script("timeline-fusion", "fuse.py"), "--asr", speech_src, "--out", tl, "--md", md,
           "--title", args.title or Path(args.media).stem, "--lang", "en" if args.lang == "en" else "zh"]
    if slides_json:
        cmd += ["--slides", slides_json]
    if subs_json:
        cmd += ["--subs", subs_json]
    step("timeline", None, cmd, True)
    (w / "plots").mkdir(exist_ok=True)
    step("pictures", None, [script("visual-verify", "timeline_plot.py"), "--timeline", tl, "--audio", audio,
                            "--out", str(w / "plots" / "timeline")], True)

    cov = str(w / "coverage.json")
    if os.path.exists(cov):
        os.remove(cov)
    name = Path(args.media).name
    step("coverage: audio", None, [script("input-audit", "coverage.py"), "audio", "--media", audio, "--asr", asr,
                                   "--name", name, "--cov", cov], True)
    if slides_json:
        cmd = [script("input-audit", "coverage.py"), "video", "--segments", slides_json, "--name", name, "--cov", cov,
               "--duration", str(entry["units"].get("seconds") or 0)]
        if subs_json:
            cmd += ["--subs", subs_json]
        step("coverage: video", None, cmd, True)
    rc = step("coverage: summary", None, [script("input-audit", "coverage.py"), "summary", "--cov", cov,
                                          "--md", str(w / "coverage.md"), "--min", str(args.min)], True, check=False)
    print(f"\nread: {w / 'ledger.md'}, {w / 'coverage.md'}, {md}, pictures in {w / 'plots'}")
    if rc:
        print("coverage below threshold: look at the listed gaps before writing anything")


if __name__ == "__main__":
    main()
