#!/usr/bin/env python3
"""One command from a meeting recording to a fused, checkable timeline (the input for the minutes).

Steps (each is skipped when its output already exists, so a long run can be resumed):
  1 probe        work/probe.json                 media-ingest/probe.py
  2 audio        work/audio.wav (16 kHz, loudnorm) media-ingest/extract.py
  3 asr          work/asr.jsonl                   speech-to-text/transcribe.py
  4 speakers     work/diar.rttm                   --diar FILE, or speaker-diarization/diarize_lite.py
  5 turns        work/turns.jsonl                 speaker-diarization/merge_speakers.py
  6 screen       work/slides/segments.json        screen-and-ocr/slide_changes.py + ocr.py  (video only)
  7 timeline     work/timeline.jsonl + .md        timeline-fusion/fuse.py
  8 pictures     work/plots/timeline_XX.png       visual-verify/timeline_plot.py
Then the LLM writes the minutes from work/timeline.md (see this skill's SKILL.md) and runs
expressive-output/coverage_check.py on the result.

usage:
  python run_pipeline.py meeting.mp4 --work work/ --speakers 3 --hotwords "北极星 P99 压测"
  python run_pipeline.py call.m4a --work work/ --diar pyannote.rttm --names names.json
  python run_pipeline.py talk.mp4 --work work/ --crop 0,0,1600,900 --mask 1600,0,320,180
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


def step(title, out, cmd, force):
    if out and os.path.exists(out) and not force:
        print(f"[skip] {title}: {out} exists")
        return
    print(f"[run ] {title}", flush=True)
    t = time.time()
    res = subprocess.run([sys.executable] + cmd)
    if res.returncode != 0:
        sys.exit(f"step '{title}' failed (exit {res.returncode})")
    print(f"[done] {title} in {time.time() - t:.0f}s", flush=True)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("media"); ap.add_argument("--work", required=True)
    ap.add_argument("--title", default=None)
    ap.add_argument("--track", type=int, default=0, help="audio track (see probe warnings)")
    ap.add_argument("--model", default="large-v3-turbo"); ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--lang", default="zh"); ap.add_argument("--hotwords"); ap.add_argument("--prompt")
    ap.add_argument("--speakers", type=int, default=0, help="number of speakers, if known")
    ap.add_argument("--diar", help="existing RTTM / JSON diarization (pyannote, sherpa-onnx, FunASR ...)")
    ap.add_argument("--names", help='JSON {"SPK_0": "王总"} confirmed by a human')
    ap.add_argument("--crop"); ap.add_argument("--mask", action="append", default=[])
    ap.add_argument("--skip-video", action="store_true")
    ap.add_argument("--force", action="store_true", help="redo every step")
    args = ap.parse_args()

    w = Path(args.work)
    w.mkdir(parents=True, exist_ok=True)
    f = args.force
    probe_json = str(w / "probe.json")
    if f or not os.path.exists(probe_json):
        out = subprocess.run([sys.executable, script("media-ingest", "probe.py"), args.media, "--json"],
                             capture_output=True)
        if out.returncode != 0:
            sys.exit(out.stderr.decode("utf-8", "replace"))
        Path(probe_json).write_bytes(out.stdout)
    probe = json.loads(Path(probe_json).read_text(encoding="utf-8"))
    for warn in probe["warnings"]:
        print(f"[warn] {warn}")
    has_video = any(not v.get("cover_art") for v in probe["video"]) and not args.skip_video

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
    step("asr", asr, cmd, f)

    diar = args.diar or str(w / "diar.rttm")
    if not args.diar:
        cmd = [script("speaker-diarization", "diarize_lite.py"), audio, "--asr", asr, "--out", diar]
        if args.speakers:
            cmd += ["--speakers", str(args.speakers)]
        step("speakers (lite baseline)", diar, cmd, f)
    turns = str(w / "turns.jsonl")
    cmd = [script("speaker-diarization", "merge_speakers.py"), "--asr", asr, "--diar", diar, "--out", turns]
    if args.names:
        cmd += ["--names", args.names]
    step("turns", turns, cmd, f or bool(args.names))

    slides_json = None
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

    tl, md = str(w / "timeline.jsonl"), str(w / "timeline.md")
    cmd = [script("timeline-fusion", "fuse.py"), "--asr", turns, "--out", tl, "--md", md,
           "--title", args.title or Path(args.media).stem, "--lang", "en" if args.lang == "en" else "zh"]
    if slides_json:
        cmd += ["--slides", slides_json]
    step("timeline", None, cmd, True)
    (w / "plots").mkdir(exist_ok=True)
    step("pictures", None, [script("visual-verify", "timeline_plot.py"), "--timeline", tl, "--audio", audio,
                            "--out", str(w / "plots" / "timeline")], True)
    print(f"\nnext: read {md} (and the pictures in {w / 'plots'}), write the minutes, "
          f"then run expressive-output/scripts/coverage_check.py")


if __name__ == "__main__":
    main()
