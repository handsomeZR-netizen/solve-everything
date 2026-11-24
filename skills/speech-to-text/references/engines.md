# 其他 ASR 引擎：用法与注意事项

> 本文件中的 FunASR 代码依据其官方 README 整理，没有在本仓库的测试中运行过。用之前先拿一段已知内容的音频验证。

## FunASR Paraformer-zh（中文长音频）

```python
# pip install funasr modelscope
from funasr import AutoModel

model = AutoModel(model="paraformer-zh", vad_model="fsmn-vad", punc_model="ct-punc",
                  spk_model="cam++", device="cpu")
res = model.generate(input="audio.wav", batch_size_s=300, hotword="傅里叶 卷积")
for s in res[0].get("sentence_info", []):
    # start / end 单位是毫秒；spk 是聚类出来的说话人编号
    print(s["start"] / 1000, s["end"] / 1000, s.get("spk"), s["text"])
```

转成本仓库的格式：

- 每个 `sentence_info` 写一行 asr.jsonl：`{"start", "end", "text", "words": []}`。如果需要逐字时间戳，从 `timestamp` 字段构造 `words`。
- 有 `spk` 时，同时写一份 RTTM，交给 `speaker-diarization/scripts/merge_speakers.py`。

注意：

- 第一次运行要联网从 ModelScope 下载模型（约 1 GB 量级）。离线环境要预先下载好，再用本地路径。
- SeACo-Paraformer 支持热词，普通 paraformer-zh 对 `hotword` 的支持有限，以 README 为准。
- 中英混说、术语里夹英文缩写时，Whisper 往往更好。可以两者都跑，用 `quality-eval/scripts/cer.py` 在你自己的数据上比。

## Whisper 系列的选择（faster-whisper / CTranslate2）

| 模型 | 速度 (CPU int8) | 备注 |
|---|---|---|
| small | 快 | 草稿、试参数 |
| medium | 中 | 质量和速度的折中 |
| large-v3-turbo | 实测 RTF 0.6–1.8（视 CPU 负载） | 默认；解码器只有 4 层，比 large-v3 快很多 |
| large-v3 | 慢 | 最稳，但 CPU 上通常不值得 |

- `local_files_only=True`（`--local-only`）只用缓存，适合离线环境；缓存不完整时会直接报 `LocalEntryNotFoundError`。
- 模型名 `large-v3-turbo` 在 faster-whisper ≥ 1.1 中对应 `mobiuslabsgmbh/faster-whisper-large-v3-turbo`。

## 常见幻觉句（Whisper 中文）

脚本 `transcribe.py` 里的 `STRONG_HALLUCINATIONS` / `WEAK_HALLUCINATIONS` 是当前列表。遇到新的，就加进去：它们几乎都来自字幕组片尾、视频平台口播，在静音、音乐、掌声段出现。

判断方法：内容和上下文无关，且 `no_speech_prob` 高或 `avg_logprob` 低。
