#!/usr/bin/env python3
"""Look at a media file before touching it.

Prints duration, container start_time, every stream, and the warnings that most
often break later alignment: non-zero start_time, A/V start offset, variable
frame rate, rotation, several audio tracks, embedded subtitle tracks, cover art.

usage:
  python probe.py INPUT           # readable summary
  python probe.py INPUT --json    # machine-readable
"""
import argparse
import json
import subprocess
import sys


def run_ffprobe(path):
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", path]
    try:
        out = subprocess.run(cmd, capture_output=True, check=False)
    except FileNotFoundError:
        sys.exit("ffprobe not found: install ffmpeg and put it on PATH")
    if out.returncode != 0:
        sys.exit(out.stderr.decode("utf-8", "replace").strip())
    return json.loads(out.stdout.decode("utf-8", "replace"))


def _ratio(text):
    try:
        a, b = (float(x) for x in str(text).split("/"))
        return a / b if b else None
    except ValueError:
        return None


def _rotation(stream):
    rot = (stream.get("tags") or {}).get("rotate")
    if rot is not None:
        return int(float(rot)) % 360
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            return int(float(side["rotation"])) % 360
    return 0


def summarise(info):
    fmt = info.get("format", {})
    res = {
        "file": fmt.get("filename"),
        "container": fmt.get("format_name"),
        "duration": float(fmt.get("duration") or 0),
        "start_time": float(fmt.get("start_time") or 0),
        "size_mb": round(int(fmt.get("size") or 0) / 1e6, 1),
        "video": [], "audio": [], "subtitle": [], "other": [],
        "warnings": [],
    }
    for s in info.get("streams", []):
        kind = s.get("codec_type")
        tags = s.get("tags") or {}
        item = {"index": s.get("index"), "codec": s.get("codec_name"),
                "start_time": float(s.get("start_time") or 0),
                "language": tags.get("language"),
                "title": tags.get("title") or tags.get("handler_name")}
        if kind == "video":
            if (s.get("disposition") or {}).get("attached_pic"):
                item["cover_art"] = True
            rot = _rotation(s)
            w, h = s.get("width"), s.get("height")
            if rot in (90, 270):
                w, h = h, w  # ffmpeg auto-rotates on decode, so this is what you will get
            r_fps, avg_fps = _ratio(s.get("r_frame_rate")), _ratio(s.get("avg_frame_rate"))
            item.update(width=w, height=h, rotation=rot, r_fps=r_fps, avg_fps=avg_fps)
            item["vfr_suspect"] = bool(r_fps and avg_fps and abs(r_fps - avg_fps) / r_fps > 0.01)
            res["video"].append(item)
        elif kind == "audio":
            item.update(sample_rate=int(s.get("sample_rate") or 0),
                        channels=s.get("channels"), layout=s.get("channel_layout"))
            res["audio"].append(item)
        elif kind == "subtitle":
            res["subtitle"].append(item)
        else:
            res["other"].append(item)

    w = res["warnings"]
    video = [v for v in res["video"] if not v.get("cover_art")]
    if not res["audio"]:
        w.append("no audio stream: nothing to transcribe")
    if len(res["audio"]) > 1:
        names = ", ".join(f"0:a:{i} ({a.get('title') or a.get('language') or a['codec']}, {a['channels']}ch)"
                          for i, a in enumerate(res["audio"]))
        w.append(f"{len(res['audio'])} audio tracks ({names}); pick one with --track / -map 0:a:N, "
                 "screen recorders often put mic and system sound on separate tracks")
    if res["video"] and not video:
        w.append("video stream is only cover art: treat this as an audio file")
    if abs(res["start_time"]) > 0.001:
        w.append(f"container start_time = {res['start_time']:.3f}s: times from different tools may "
                 "disagree by this much; extract audio and frames with the same tool and the same -ss")
    if video and res["audio"]:
        off = video[0]["start_time"] - res["audio"][0]["start_time"]
        if abs(off) > 0.04:
            w.append(f"video starts {off:+.3f}s relative to audio: shift one timeline before fusing")
    for v in video:
        if v["vfr_suspect"]:
            w.append(f"stream {v['index']} looks like variable frame rate (r={v['r_fps']:.3f}, "
                     f"avg={v['avg_fps']:.3f}): never derive time from frame index; resample with the fps filter")
        if v["rotation"]:
            w.append(f"stream {v['index']} has rotation {v['rotation']}: decoded frames are already rotated, "
                     f"so crop boxes refer to the rotated {v['width']}x{v['height']} picture")
    if res["subtitle"]:
        w.append(f"{len(res['subtitle'])} embedded subtitle track(s): extract them "
                 "(extract.py subs IN out.srt) before trying OCR or ASR")
    for a in res["audio"][:1]:
        if a["sample_rate"] and a["sample_rate"] < 16000:
            w.append(f"audio sample rate is {a['sample_rate']} Hz (< 16 kHz): expect weaker ASR")
    if res["duration"] > 3 * 3600:
        w.append("longer than 3 h: process in chunks and stream frames instead of loading them")
    return res


def print_human(r):
    print(f"{r['file']}  [{r['container']}]  {r['duration']:.2f}s  {r['size_mb']} MB  "
          f"start_time={r['start_time']:.3f}")
    for v in r["video"]:
        tag = " (cover art)" if v.get("cover_art") else ""
        fps = f"{v['avg_fps']:.3f}" if v.get("avg_fps") else "?"
        print(f"  video #{v['index']} {v['codec']} {v['width']}x{v['height']} fps={fps} "
              f"rot={v['rotation']} start={v['start_time']:.3f}{tag}")
    for i, a in enumerate(r["audio"]):
        print(f"  audio 0:a:{i} (#{a['index']}) {a['codec']} {a['sample_rate']}Hz {a['channels']}ch "
              f"lang={a['language']} title={a['title']} start={a['start_time']:.3f}")
    for i, s in enumerate(r["subtitle"]):
        print(f"  subtitle 0:s:{i} (#{s['index']}) {s['codec']} lang={s['language']} title={s['title']}")
    if r["warnings"]:
        print("warnings:")
        for x in r["warnings"]:
            print("  - " + x)
    else:
        print("no warnings")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = ap.parse_args()
    res = summarise(run_ffprobe(args.input))
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print_human(res)


if __name__ == "__main__":
    main()
