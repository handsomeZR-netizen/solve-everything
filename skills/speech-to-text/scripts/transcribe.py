#!/usr/bin/env python3
"""Speech -> timestamped text with faster-whisper, tuned for Chinese and long, real-world recordings.

Output is JSONL, one segment per line:
  {"start": 12.34, "end": 15.6, "text": "...", "avg_logprob": -0.21, "no_speech_prob": 0.01,
   "compression_ratio": 1.3, "words": [[12.34, 12.6, "我们", 0.98], ...], "flags": []}
plus OUT.meta.json with the model, every decoding parameter and the run time (for reproducibility).

usage:
  python transcribe.py audio.wav --out asr.jsonl
  python transcribe.py audio.wav --out asr.jsonl --hotwords "傅里叶 卷积 Transformer" --prompt "机器学习课程。"
  python transcribe.py audio.wav --out asr.jsonl --no-vad --chunk 28 --overlap 2   # singing, whispering
  python transcribe.py audio.wav --out asr.jsonl --model small --threads 8           # quick draft

Segments that match well-known Whisper hallucinations ("字幕由Amara.org社区提供", "请不吝点赞订阅转发打赏"...)
are dropped; weaker suspects are kept but flagged so a human or the LLM can decide.
"""
import argparse
import inspect
import json
import math
import re
import sys
import time

# Phrases Whisper learned from subtitle credits; they appear on silence or music, almost never in real speech.
STRONG_HALLUCINATIONS = [
    r"amara\.org", r"明镜", r"点点栏目", r"不吝点赞", r"点赞.{0,3}订阅.{0,3}转发", r"订阅.{0,3}转发.{0,3}打赏",
    r"yoyo television", r"优优独播剧场", r"字幕志愿者", r"字幕由.{0,16}提供", r"本字幕.{0,10}(制作|提供)",
    r"subtitles by", r"please subscribe", r"like and subscribe",
]
# Phrases that are real speech often enough that we only flag them.
WEAK_HALLUCINATIONS = [
    r"^(谢谢|感谢)(大家)?(的)?(观看|收看|收听|聆听)", r"^thanks? (you )?for watching", r"^(谢谢|谢谢大家)[。！!.]*$",
    r"^请不要忘记", r"^我们下(期|次)再见",
]
STRONG_RE = [re.compile(p, re.I) for p in STRONG_HALLUCINATIONS]
WEAK_RE = [re.compile(p, re.I) for p in WEAK_HALLUCINATIONS]


def repeated(text, times=4):
    """True if some 2-8 char unit repeats `times` times in a row (Whisper's loop failure)."""
    t = re.sub(r"\s+", "", text)
    for n in range(2, 9):
        if re.search(r"(.{%d})\1{%d,}" % (n, times - 1), t):
            return True
    return False


def make_converter(enabled):
    if not enabled:
        return lambda s: s
    try:
        import opencc
    except ImportError:
        print("note: opencc not installed, skipping traditional->simplified (pip install opencc-python-reimplemented)",
              file=sys.stderr)
        return lambda s: s
    for cfg in ("t2s", "t2s.json"):
        try:
            conv = opencc.OpenCC(cfg)
            return conv.convert
        except Exception:
            continue
    return lambda s: s


ZH_PUNCT = {",": "，", "?": "？", "!": "！", ":": "：", ";": "；"}
CJK = re.compile(r"[㐀-鿿]")


def zh_punct(text):
    """Whisper often emits ASCII punctuation in Chinese; use full-width marks next to CJK characters."""
    out = []
    for i, c in enumerate(text):
        if c in ZH_PUNCT and (CJK.match(text[i - 1:i] or " ") or CJK.match(text[i + 1:i + 2] or " ")):
            out.append(ZH_PUNCT[c])
        elif c == "." and CJK.match(text[i - 1:i] or " ") and not text[i + 1:i + 2].isdigit():
            out.append("。")
        else:
            out.append(c)
    return "".join(out)


SENT_END = "。！？!?；;"


def split_sentences(rec, max_dur=12.0):
    """One record per sentence. With a music bed or very even pacing, VAD + Whisper can return a
    single 30-second segment; downstream steps (sections, speakers, cross-checks) need sentences."""
    ws = rec["words"]
    if len(ws) < 2:
        return [rec]
    groups, cur = [], []
    for w in ws:
        cur.append(w)
        tail = w[2].strip()[-1:]
        if tail in SENT_END or (tail in "，,、" and w[1] - cur[0][0] > max_dur):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    if len(groups) == 1:
        return [rec]
    out = []
    for g in groups:
        text = "".join(w[2] for w in g).strip()
        if not text:
            continue
        out.append({**rec, "start": g[0][0], "end": g[-1][1], "text": " ".join(text.split()), "words": g})
    return out


def flag_segment(seg, args):
    flags = []
    text = seg["text"].strip()
    if any(r.search(text) for r in STRONG_RE):
        flags.append("hallucination")
    elif any(r.search(text) for r in WEAK_RE):
        flags.append("hallucination?")
    if repeated(text) or seg["compression_ratio"] > 2.4:
        flags.append("repetition")
    if seg["avg_logprob"] < args.low_logprob:
        flags.append("low_confidence")
    if seg["no_speech_prob"] > 0.6 and seg["avg_logprob"] < -0.7:
        flags.append("maybe_silence")
    return flags


def to_record(s, offset, conv):
    words = []
    for w in s.words or []:
        words.append([round(offset + w.start, 2), round(offset + w.end, 2), conv(w.word), round(w.probability, 3)])
    return {
        "start": round(offset + s.start, 2), "end": round(offset + s.end, 2),
        "text": conv(s.text.strip()),
        "avg_logprob": round(s.avg_logprob, 3), "no_speech_prob": round(s.no_speech_prob, 3),
        "compression_ratio": round(s.compression_ratio, 3),
        "words": words,
    }


def load_audio(path, sr=16000):
    """Decode any audio/video to mono float32 with the ffmpeg CLI.
    (faster_whisper.decode_audio goes through PyAV, and some PyAV releases break it.)"""
    import subprocess
    import numpy as np
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True)
    if out.returncode != 0:
        sys.exit("ffmpeg could not decode the audio:\n" + out.stderr.decode("utf-8", "replace"))
    return np.frombuffer(out.stdout, np.float32).copy()


def supported_kwargs(model, kw):
    params = inspect.signature(model.transcribe).parameters
    dropped = [k for k in kw if k not in params]
    if dropped:
        print(f"note: this faster-whisper version ignores {dropped}", file=sys.stderr)
    return {k: v for k, v in kw.items() if k in params}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", help="any format ffmpeg/PyAV can read; 16 kHz mono wav is fastest")
    ap.add_argument("--out", required=True, help="output JSONL")
    ap.add_argument("--model", default="large-v3-turbo",
                    help="size name (tiny/small/medium/large-v3/large-v3-turbo) or a local CTranslate2 folder")
    ap.add_argument("--local-only", action="store_true", help="never download; use the HF cache only")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--compute", default=None, help="int8 (cpu default) / float16 (cuda default) / int8_float16")
    ap.add_argument("--threads", type=int, default=0, help="CPU threads, 0 = library default")
    ap.add_argument("--lang", default="zh", help="language code, or 'auto'")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--prompt", default=None,
                    help="initial prompt (first window only). Default for zh: '以下是普通话的句子，使用简体中文。'")
    ap.add_argument("--hotwords", default=None, help="names / terms, applied to every window")
    ap.add_argument("--fallback", action="store_true",
                    help="enable temperature fallback (0.0..1.0). More robust to loops, less deterministic")
    ap.add_argument("--no-vad", action="store_true", help="disable Silero VAD (use for singing / very soft speech)")
    ap.add_argument("--min-silence-ms", type=int, default=700, help="VAD: silence needed to split")
    ap.add_argument("--speech-pad-ms", type=int, default=300, help="VAD: padding kept around speech")
    ap.add_argument("--chunk", type=float, default=0.0,
                    help="seconds per manual chunk (0 = let the library handle long audio)")
    ap.add_argument("--overlap", type=float, default=2.0, help="overlap between manual chunks")
    ap.add_argument("--low-logprob", type=float, default=-1.0, help="flag segments below this avg_logprob")
    ap.add_argument("--keep-hallucinations", action="store_true", help="keep (but flag) strong hallucinations")
    ap.add_argument("--no-t2s", action="store_true", help="do not convert traditional to simplified Chinese")
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    compute = args.compute or ("float16" if args.device == "cuda" else "int8")
    t0 = time.time()
    model = WhisperModel(args.model, device=args.device, compute_type=compute,
                         cpu_threads=args.threads, local_files_only=args.local_only)
    load_s = time.time() - t0

    lang = None if args.lang == "auto" else args.lang
    prompt = args.prompt
    if prompt is None and lang in ("zh", None):
        prompt = "以下是普通话的句子，使用简体中文。"
    hotwords = args.hotwords
    if hotwords and (lang or "zh").startswith("zh") and not re.search(r"[，。、]", hotwords):
        # Bare space-separated hotwords become the only prompt of every later window, and an
        # unpunctuated prompt makes Whisper stop punctuating. Wrap them in a punctuated sentence.
        terms = [t for t in re.split(r"[\s,;]+", hotwords) if t]
        hotwords = "可能出现的词：" + "、".join(terms) + "。"
    kw = dict(
        language=lang, task="transcribe", beam_size=args.beam,
        temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0) if args.fallback else 0.0,
        condition_on_previous_text=False,  # the single most effective switch against repetition loops
        word_timestamps=True, initial_prompt=prompt or None, hotwords=hotwords or None,
        vad_filter=not args.no_vad,
        vad_parameters=dict(min_silence_duration_ms=args.min_silence_ms, speech_pad_ms=args.speech_pad_ms),
        no_speech_threshold=0.6, log_prob_threshold=-1.0, compression_ratio_threshold=2.4,
    )
    kw = supported_kwargs(model, kw)
    is_zh = (lang or "zh").startswith("zh")
    t2s = make_converter(not args.no_t2s and is_zh)
    conv = (lambda s: zh_punct(t2s(s))) if is_zh else t2s

    sr = 16000
    audio = load_audio(args.audio, sr)
    dur = len(audio) / sr
    records, info_lang = [], None
    t1 = time.time()
    if args.chunk and args.chunk > args.overlap:
        step = args.chunk - args.overlap
        starts = [i * step for i in range(max(1, math.ceil((dur - args.overlap) / step)))]
        for k, a in enumerate(starts):
            b = min(a + args.chunk, dur)
            lo = a + args.overlap / 2 if k > 0 else -1.0
            hi = b - args.overlap / 2 if b < dur else dur + 1.0
            segs, info = model.transcribe(audio[int(a * sr):int(b * sr)], **kw)
            info_lang = info_lang or info.language
            for s in segs:  # generator: decoding happens here
                mid = a + (s.start + s.end) / 2
                if lo <= mid < hi:  # each overlap zone is owned by exactly one chunk
                    records.append(to_record(s, a, conv))
            print(f"chunk {k + 1}/{len(starts)} {a:.1f}-{b:.1f}s", file=sys.stderr, flush=True)
    else:
        segs, info = model.transcribe(audio, **kw)
        info_lang = info.language
        for s in segs:
            records.append(to_record(s, 0.0, conv))
            print(f"[{s.start:7.2f}] {records[-1]['text']}", flush=True)
    asr_s = time.time() - t1

    records = [s for r in records for s in split_sentences(r)]
    kept, dropped = [], 0
    for r in records:
        r["flags"] = flag_segment(r, args)
        if "hallucination" in r["flags"] and not args.keep_hallucinations:
            dropped += 1
            continue
        kept.append(r)

    with open(args.out, "w", encoding="utf-8") as fh:
        for r in kept:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    meta = {"audio": args.audio, "duration_s": round(dur, 2), "model": args.model, "device": args.device,
            "compute_type": compute, "language": info_lang, "params": {k: v for k, v in kw.items()},
            "segments": len(kept), "dropped_hallucinations": dropped,
            "load_s": round(load_s, 1), "asr_s": round(asr_s, 1), "rtf": round(asr_s / max(dur, 1e-6), 3)}
    with open(args.out + ".meta.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1, default=str)
    flagged = sum(1 for r in kept if r["flags"])
    print(f"done: {len(kept)} segments ({flagged} flagged, {dropped} hallucinations dropped), "
          f"{dur:.0f}s audio in {asr_s:.0f}s (RTF {meta['rtf']})", file=sys.stderr)


if __name__ == "__main__":
    main()
