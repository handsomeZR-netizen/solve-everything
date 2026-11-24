#!/usr/bin/env python3
"""Pull the parts other tools need out of a media file, with ffmpeg.

  python extract.py audio  IN OUT.wav [--track 0] [--sr 16000] [--stereo] [--loudnorm] [--ss S] [--t D]
  python extract.py frames IN OUTDIR  [--fps 1] [--crop x,y,w,h] [--width 1280] [--ss S] [--t D] [--fmt jpg]
  python extract.py frame  IN SECONDS OUT.png [--crop x,y,w,h]
  python extract.py subs   IN OUT.srt [--track 0]

Times written by `frames` (index.json) are seconds from the start of the file
timeline: t = ss + i / fps. Audio extracted with the same --ss shares that origin.
"""
import argparse
import json
import os
import subprocess
import sys


def ffmpeg(args):
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y"] + args
    try:
        res = subprocess.run(cmd, capture_output=True)
    except FileNotFoundError:
        sys.exit("ffmpeg not found: install it and put it on PATH")
    if res.returncode != 0:
        sys.exit("ffmpeg failed:\n" + res.stderr.decode("utf-8", "replace"))


def crop_filter(spec):
    if not spec:
        return []
    x, y, w, h = (int(float(v)) for v in spec.split(","))
    return [f"crop={w}:{h}:{x}:{y}"]


def seek(ss):
    return ["-ss", f"{ss:.3f}"] if ss else []  # before -i: fast, and accurate because we decode


def cmd_audio(a):
    args = seek(a.ss) + ["-i", a.input]
    if a.t:
        args += ["-t", f"{a.t:.3f}"]
    args += ["-map", f"0:a:{a.track}", "-vn", "-ar", str(a.sr), "-ac", "2" if a.stereo else "1"]
    if a.loudnorm:
        # one-pass EBU R128 to about -20 LUFS: quiet speakers become usable, no clipping
        args += ["-af", "loudnorm=I=-20:TP=-2:LRA=11"]
    args += ["-c:a", "pcm_s16le", a.output]
    ffmpeg(args)
    print(f"wrote {a.output}")


def cmd_frames(a):
    os.makedirs(a.outdir, exist_ok=True)
    vf = [f"fps={a.fps}"] + crop_filter(a.crop)
    if a.width:
        vf.append(f"scale={a.width}:-2")
    args = seek(a.ss) + ["-i", a.input]
    if a.t:
        args += ["-t", f"{a.t:.3f}"]
    pattern = os.path.join(a.outdir, f"f_%06d.{a.fmt}")
    args += ["-an", "-vf", ",".join(vf), "-start_number", "0"]
    if a.fmt == "jpg":
        args += ["-q:v", "2"]
    args += [pattern]
    ffmpeg(args)
    files = sorted(f for f in os.listdir(a.outdir) if f.startswith("f_") and f.endswith("." + a.fmt))
    index = [{"file": f, "t": round((a.ss or 0) + i / a.fps, 3)} for i, f in enumerate(files)]
    with open(os.path.join(a.outdir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=0)
    print(f"wrote {len(files)} frames + index.json to {a.outdir}")


def cmd_frame(a):
    args = ["-ss", f"{a.seconds:.3f}", "-i", a.input, "-frames:v", "1", "-update", "1"]
    vf = crop_filter(a.crop)
    if vf:
        args += ["-vf", ",".join(vf)]
    args += [a.output]
    ffmpeg(args)
    print(f"wrote {a.output}")


def cmd_subs(a):
    ffmpeg(["-i", a.input, "-map", f"0:s:{a.track}", a.output])
    print(f"wrote {a.output}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("audio", help="extract one audio track as PCM wav")
    p.add_argument("input"); p.add_argument("output")
    p.add_argument("--track", type=int, default=0, help="audio track index (0:a:N)")
    p.add_argument("--sr", type=int, default=16000)
    p.add_argument("--stereo", action="store_true", help="keep two channels (music / mid-side work)")
    p.add_argument("--loudnorm", action="store_true", help="normalise loudness (recommended for meetings)")
    p.add_argument("--ss", type=float, default=0.0); p.add_argument("--t", type=float, default=0.0)
    p.set_defaults(fn=cmd_audio)

    p = sub.add_parser("frames", help="sample frames at a fixed rate")
    p.add_argument("input"); p.add_argument("outdir")
    p.add_argument("--fps", type=float, default=1.0)
    p.add_argument("--crop", help="x,y,w,h in displayed (rotated) pixels")
    p.add_argument("--width", type=int, default=0, help="scale to this width after crop")
    p.add_argument("--fmt", choices=["jpg", "png"], default="jpg")
    p.add_argument("--ss", type=float, default=0.0); p.add_argument("--t", type=float, default=0.0)
    p.set_defaults(fn=cmd_frames)

    p = sub.add_parser("frame", help="grab one frame at a time")
    p.add_argument("input"); p.add_argument("seconds", type=float); p.add_argument("output")
    p.add_argument("--crop")
    p.set_defaults(fn=cmd_frame)

    p = sub.add_parser("subs", help="dump an embedded subtitle track")
    p.add_argument("input"); p.add_argument("output")
    p.add_argument("--track", type=int, default=0)
    p.set_defaults(fn=cmd_subs)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
