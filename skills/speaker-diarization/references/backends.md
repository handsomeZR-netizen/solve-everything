# 说话人分离后端：调用方式

> 下面三段代码依据各项目官方文档和示例整理，**没有在本仓库的测试中运行过**（需要 token 或额外的模型下载）。
> 接口会随版本变化，用之前先在一段几分钟、人数已知的录音上跑通，再用 `quality-eval/scripts/der.py` 对照人工标注检查。

三者最终都写成 RTTM，交给 `merge_speakers.py`：

```python
def write_rttm(rows, path, uri="audio"):
    with open(path, "w", encoding="utf-8") as fh:
        for start, end, spk in rows:
            fh.write(f"SPEAKER {uri} 1 {start:.2f} {end - start:.2f} <NA> <NA> {spk} <NA> <NA>\n")
```

## pyannote.audio

```python
# pip install pyannote.audio      需要 HF token，并在模型页面同意使用条款
import os
from pyannote.audio import Pipeline

pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1",
                                use_auth_token=os.environ["HF_TOKEN"])   # 新版本参数名可能是 token=
diar = pipe("audio.wav", num_speakers=3)          # 知道人数就传；不知道用 min_speakers / max_speakers
with open("diar.rttm", "w") as fh:
    diar.write_rttm(fh)
```

- token 只放环境变量，不要写进脚本或仓库。
- CPU 上 1 小时音频可能要跑相当长时间，先拿 5 分钟试。

## sherpa-onnx（纯 ONNX，CPU 友好）

需要两个模型：分割模型（pyannote segmentation 3.0 的 ONNX 版），以及中文声纹模型（例如 3D-Speaker eres2net）。下载地址见 sherpa-onnx 文档的 speaker diarization 页面。

```python
# pip install sherpa-onnx
import numpy as np, subprocess, sherpa_onnx

cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
    segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
        pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
            model="sherpa-onnx-pyannote-segmentation-3-0/model.onnx")),
    embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model="3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"),
    clustering=sherpa_onnx.FastClusteringConfig(num_clusters=3),   # 不知道人数时设 threshold
    min_duration_on=0.3, min_duration_off=0.5)
sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", "audio.wav", "-ac", "1", "-ar", str(sd.sample_rate),
                      "-f", "f32le", "-"], capture_output=True).stdout
segs = sd.process(np.frombuffer(raw, np.float32)).sort_by_start_time()
write_rttm([(s.start, s.end, f"SPK_{s.speaker}") for s in segs], "diar.rttm")
```

## FunASR（与 Paraformer 一起）

```python
from funasr import AutoModel
model = AutoModel(model="paraformer-zh", vad_model="fsmn-vad", punc_model="ct-punc", spk_model="cam++")
res = model.generate(input="audio.wav", batch_size_s=300)
rows = [(s["start"] / 1000, s["end"] / 1000, f"SPK_{s['spk']}") for s in res[0]["sentence_info"]]
write_rttm(rows, "diar.rttm")
```

FunASR 的说话人是按句给的。一句里有两个人说话的情况，它和 `diarize_lite` 一样拆不开。
