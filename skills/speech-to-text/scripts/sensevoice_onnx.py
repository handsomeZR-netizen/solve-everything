#!/usr/bin/env python3
"""Second-opinion ASR with SenseVoice-Small (ONNX, CPU), plus emotion and audio-event tags.

Needs only numpy + onnxruntime + soundfile/scipy (or faster-whisper for decoding).
Model folder = the sherpa-onnx export: model.int8.onnx (or model.onnx) + tokens.txt.

usage:
  python sensevoice_onnx.py MODEL_DIR audio.wav --segments asr.jsonl --out sv.jsonl   # same spans as Whisper
  python sensevoice_onnx.py MODEL_DIR audio.wav --win 15 --out sv.jsonl               # fixed windows

Each output line: {"start","end","text","lang","emotion","event"}.
SenseVoice gives no timestamps: feed it spans you already have (VAD or Whisper segments),
then compare texts span by span. Disagreements are where a human should listen.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

TAG_RE = re.compile(r"<\|([^|]*)\|>")
EMOTIONS = {"HAPPY", "SAD", "ANGRY", "NEUTRAL", "FEARFUL", "DISGUSTED", "SURPRISED", "EMO_UNKNOWN"}
EVENTS = {"Speech", "BGM", "Applause", "Laughter", "Cry", "Sneeze", "Breath", "Cough", "Event_UNK"}


def load_audio(path, sr=16000):
    """Mono float32 via the ffmpeg CLI: works for any container and needs no PyAV."""
    import subprocess
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True)
    if out.returncode != 0:
        sys.exit("ffmpeg could not decode the audio:\n" + out.stderr.decode("utf-8", "replace"))
    return np.frombuffer(out.stdout, np.float32).copy()


class SenseVoice:
    def __init__(self, folder, threads=2):
        import onnxruntime as ort
        folder = Path(folder)
        onnx = folder / "model.int8.onnx"
        if not onnx.exists():
            onnx = folder / "model.onnx"
        opt = ort.SessionOptions()
        opt.intra_op_num_threads = threads
        opt.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(str(onnx), opt, providers=["CPUExecutionProvider"])
        meta = self.sess.get_modelmeta().custom_metadata_map
        self.meta = meta
        self.neg_mean = np.array(meta["neg_mean"].split(","), dtype=np.float32)
        self.inv_std = np.array(meta["inv_stddev"].split(","), dtype=np.float32)
        self.lfr_m = int(meta.get("lfr_window_size", 7))
        self.lfr_n = int(meta.get("lfr_window_shift", 6))
        self.scale = 1.0 if meta.get("normalize_samples", "0") == "1" else 32768.0
        self.vocab = {}
        for line in (folder / "tokens.txt").read_text(encoding="utf-8").splitlines():
            if line.strip():
                word, idx = line.rsplit(" ", 1)
                self.vocab[int(idx)] = word
        self._mel = None

    def lang_id(self, lang):
        return int(self.meta.get(f"lang_{lang}", self.meta.get("lang_auto", 0)))

    def fbank(self, y):
        """80-dim log-mel, 25 ms window / 10 ms hop, pre-emphasis 0.97: the Kaldi-style front end the model was trained on.
        Any mismatch here (window, mel count, scaling) gives fluent garbage with no error."""
        rows = np.lib.stride_tricks.sliding_window_view(y * self.scale, 400)[::160].copy()
        rows -= rows.mean(axis=1, keepdims=True)
        rows[:, 1:] -= 0.97 * rows[:, :-1].copy()
        rows[:, 0] *= 1 - 0.97
        power = np.abs(np.fft.rfft(rows * np.hamming(400), axis=1, n=512)) ** 2
        if self._mel is None:
            mel = lambda hz: 1127.0 * np.log1p(hz / 700.0)
            hz_mel = mel(np.arange(257) * 16000 / 512)
            edges = np.linspace(mel(20), mel(8000), 82)
            self._mel = np.stack([np.maximum(0, np.minimum((hz_mel - lo) / (mid - lo), (hi - hz_mel) / (hi - mid)))
                                  for lo, mid, hi in zip(edges, edges[1:], edges[2:])], axis=1)
        return np.log(np.maximum(power @ self._mel, np.finfo(np.float32).eps)).astype(np.float32)

    def lfr(self, f):
        """Low frame rate: stack 7 frames, hop 6 (from model metadata)."""
        half = (self.lfr_m - 1) // 2
        centers = np.arange(0, len(f), self.lfr_n)[:, None] + np.arange(-half, self.lfr_m - half)
        stacked = f[np.clip(centers, 0, len(f) - 1)].reshape(len(centers), -1)
        return (stacked + self.neg_mean) * self.inv_std

    def __call__(self, y, lang="zh", itn=True):
        if len(y) < 400:
            return {"text": "", "lang": None, "emotion": None, "event": None}
        x = self.lfr(self.fbank(y))
        norm = int(self.meta.get("with_itn" if itn else "without_itn", 14 if itn else 15))
        logits = self.sess.run(None, {
            "x": x[None].astype(np.float32), "x_length": np.array([len(x)], dtype=np.int32),
            "language": np.array([self.lang_id(lang)], dtype=np.int32),
            "text_norm": np.array([norm], dtype=np.int32)})[0]
        ids = logits[0].argmax(-1)
        ids = ids[np.r_[True, ids[1:] != ids[:-1]]]  # CTC: collapse repeats, then drop blank (0)
        raw = "".join(self.vocab.get(int(i), "") for i in ids if i)
        tags = TAG_RE.findall(raw)
        text = TAG_RE.sub("", raw).replace("▁", " ").strip()
        return {"text": text,
                "lang": next((t for t in tags if len(t) <= 4 and t.islower()), None),
                "emotion": next((t for t in tags if t in EMOTIONS), None),
                "event": next((t for t in tags if t in EVENTS), None)}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model_dir"); ap.add_argument("audio")
    ap.add_argument("--segments", help="JSONL with start/end (e.g. transcribe.py output)")
    ap.add_argument("--win", type=float, default=15.0, help="fixed window length when no --segments")
    ap.add_argument("--lang", default="zh", help="auto / zh / en / yue / ja / ko")
    ap.add_argument("--no-itn", action="store_true", help="keep numbers as spoken words")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    sr = 16000
    y = load_audio(args.audio, sr)
    if args.segments:
        spans = []
        with open(args.segments, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    spans.append((float(r["start"]), float(r["end"])))
    else:
        dur = len(y) / sr
        spans = [(t, min(t + args.win, dur)) for t in np.arange(0, dur, args.win)]

    sv = SenseVoice(args.model_dir, args.threads)
    with open(args.out, "w", encoding="utf-8") as fh:
        for a, b in spans:
            r = sv(y[int(a * sr):int(b * sr)], lang=args.lang, itn=not args.no_itn)
            r = {"start": round(float(a), 2), "end": round(float(b), 2), **r}
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"[{a:7.2f}-{b:7.2f}] {r['emotion'] or '-':8} {r['event'] or '-':9} {r['text']}", flush=True)


if __name__ == "__main__":
    main()
