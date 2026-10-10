# EmbeddingGemma 2 ネイティブ検索契約

確認日: 2026-10-10 (Asia/Tokyo)  
対象checkpoint: **google/embeddinggemma-2@914f7f89142e33e77833254d9c9b90c3cef7303b**

## 結論

このcheckpointは文章専用ではない。GoogleのモデルカードとTransformers公式実装は、text/image/audio/videoを同じ768次元ベクトル空間に埋め込むネイティブ対応を確認している。Sentence Transformers 6.1.0以上で画像・音声・動画を入力できる。既存アプリがロードするのは、設定でvisionとaudio towerを落とした271,002,624-paramのtext-onlyモデルであり、そのアプリ設定をモデル全体の能力として扱わない。

これは検索用embedding modelで、質問に回答文を生成しない。accuracy結果はgold対象の検索順位・根拠取得で評価し、回答生成の正解率とは呼ばない。

## 固定条件とバージョン

|項目|契約|
|---|---|
|Model ID / revision|google/embeddinggemma-2@914f7f89142e33e77833254d9c9b90c3cef7303b|
|Architecture|EmbeddingGemma2Model|
|Native modalities|text, image, audio, video; optional combinations are supported|
|Output|768 dimensions; Sentence Transformers model config sets cosine similarity|
|Framework|Sentence Transformers >=6.1.0; this project pins 6.1.0. Transformers >=5.0,<6.0; this project pins 5.19.0. PyTorch >=2.2. Python >=3.10.|
|Model-specific API availability|Transformers v5.19.0 contains EmbeddingGemma2Model and EmbeddingGemma2Processor; no remote-code trust switch is needed.|
|Modality extras|Install sentence-transformers[image,audio,video]==6.1.0 and keep transformers==5.19.0. ST v6.1.0 maps extras to Transformers vision/audio/video extras. torchcodec is needed only when passing its decoder objects; ordinary file paths are documented inputs when the processor can decode them.|

The pinned checkpoint config contains non-null vision_config and audio_config, plus a text config with embedding_dim=768. Its weights/config use bfloat16. The pinned Sentence Transformers config requires ST >=6.1.0, maps query/document prompts, and sets similarity_fn_name=cosine.

## Query/document prompt contract

The model card specifies asymmetric retrieval prefixes and explicitly says prefixes apply only to text; image/audio/video should be passed without a prefix.

|Input|Method and prompt|
|---|---|
|Text query for this 75-question QA retrieval benchmark|model.encode_query(question, prompt_name="QuestionAnswering"); prompt is task: question answering \| query: |
|General web/document search query|model.encode_query(question); prompt is task: search result \| query: |
|Text document or extracted text from office/PDF files|Without a title, model.encode_document(content) uses title: none \| text: . With a title, pass model.encode_document(content, prompt=f"title: {title} \| text: ") so the registered titleless prefix is replaced rather than duplicated.|
|Image/audio/video document|model.encode_document(media, prompt=""); explicitly override the registered document prefix with an empty string because the model-specific card says not to add a text task prefix to media-only inputs.|
|Media query|model.encode_query(media, prompt="") if the query itself is image/audio/video.|

In Sentence Transformers 6.1.0, prompt is an explicit override for prompt_name; an empty string means no prefix. Keep the method's query/document role while overriding the prefix for media. Freeze QuestionAnswering for this benchmark; do not change the prompt after inspecting test results.

## Minimal native search example

~~~python
import math
import numpy as np
import soundfile as sf
import torch
from scipy.signal import resample_poly
from sentence_transformers import SentenceTransformer

MODEL_ID = "google/embeddinggemma-2"
REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"

model = SentenceTransformer(
    MODEL_ID,
    revision=REVISION,
    device="cpu",
    model_kwargs={"dtype": torch.float32},
)
assert all(model.supports(modality) for modality in ("text", "image", "audio", "video"))


def mono_16khz_segments(path, segment_seconds=30):
    samples, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    samples = samples.mean(axis=1)
    if sample_rate != 16_000:
        divisor = math.gcd(sample_rate, 16_000)
        samples = resample_poly(
            samples, 16_000 // divisor, sample_rate // divisor
        ).astype(np.float32)
    segment_samples = segment_seconds * 16_000
    return [
        {"array": samples[start:start + segment_samples], "sampling_rate": 16_000}
        for start in range(0, len(samples), segment_samples)
    ]


question = "品質会議で報告された問題は何ですか？"
query = model.encode_query(
    question,
    prompt_name="QuestionAnswering",
    convert_to_tensor=True,
    normalize_embeddings=True,
)

# Split each ~60-second audio source into <=30-second segments first; see Audio limits.
media_documents = [
    {"image": r"inputs\slides\slide-01.png"},
    *[
        {"audio": segment}
        for segment in mono_16khz_segments(r"inputs\audio\quality_meeting.wav")
    ],
    {"video": r"inputs\video\f2_inspection.mp4"},
]
documents = model.encode_document(
    media_documents,
    prompt="",  # media-only inputs receive no text prefix per model card
    batch_size=1,
    convert_to_tensor=True,
    normalize_embeddings=True,
    processing_kwargs={
        "video": {
            "fps": 1,
            "max_frames": 32,
            "overflow_strategy": "uniform",
            "add_timestamps": False,
        }
    },
)
scores = model.similarity(query, documents)  # cosine, shape (1, number_of_candidates)
~~~

The example intentionally performs no text generation. Before using it on the benchmark, replace the example image with a rendered page/frame already produced as ordinary preprocessing; preserve asset ID and, for audio, segment start/end offsets. Run one complete full multimodal model load at a time. The existing app is already a separate, lighter text-only model instance.

### Lower-level Transformers route

The official path is AutoProcessor.from_pretrained(MODEL_ID, revision=REVISION) plus AutoModel.from_pretrained(..., dtype=torch.float32). The processor accepts images=[...], videos=[...], and audio=[...] without text, synthesizing media placeholders. With text, put the exact query/document instruction into the text string. Pool the model's last_hidden_state by the attention mask, then L2-normalize in float32. Sentence Transformers is the recommended path because it does media preprocessing, prompt routing, mask-aware mean pooling, and float32 normalization.

## Media and preprocessing limits

|Modality or source type|Accepted native input / required handling|
|---|---|
|Image|PIL image, image path, URL, NumPy/PyTorch array. Default visual soft-token budget is 280/image; allowed values are 70, 140, 280, 560, 1120.|
|Audio|Audio file path/URL when decoder support is present, or waveform array with sampling-rate metadata. Model card requires mono 16kHz. Processor in Transformers v5.19.0 uses 40ms/token and caps each audio segment at 750 soft tokens (~30s). Verify effective duration/token count; split longer clips into <=30s segments (with a fixed overlap policy) and aggregate result scores by asset while retaining chunk offsets.|
|Video|Video path/URL, or explicitly wrapped sampled frames. Default is 1fps, max 32 frames, uniform subsampling, timestamps off. Record these settings and any override; changing FPS/frame policy changes quality and cost.|
|DOCX/PDF/XLSX/PPTX|These are not direct processor modalities. Convert to extracted text for text search and/or render pages/slides/sheets to images for visual embedding. The extraction/rendering is upstream preprocessing, not automatic file-native model understanding. Do not count OCR/ASR output as native audio/video embedding.|

For this benchmark, the two existing WAVs are mono 22.05kHz and last 60.972880s / 60.001905s in the current ffprobe evidence. Convert/resample to 16kHz mono and account for that preprocessing separately. Their source evidence is in multimodal-benchmark/qa/A-QA-ffprobe.json and A-LOG-ffprobe.json.

## CPU float32 and resource limits

- Use float32 on CPU. The checkpoint defaults to bfloat16, but the model card says inference should use bfloat16 or float32 and explicitly prohibits float16: float16 can produce NaNs or silently degraded embeddings. Most CPUs should use float32 unless native CPU bfloat16 support has been proven on the target host.
- For the pinned Transformers 5.19.0 project, pass model_kwargs={"dtype": torch.float32}; the existing app and its runtime record already use this setting and report torch.float32. The model card also documents torch_dtype as the equivalent loading control.
- Full multimodal size is about 740M params per model card (Transformers docs report 744M). At 4 bytes/parameter this is approximately 2.96-2.98 GB of weights alone (about 2.76-2.78 GiB); peak RSS needs measurement and will be higher. The existing text-only app loaded exactly 271,002,624 params. Do not launch a full model alongside another full copy; the runner owns cold-load/RSS observations.
- Use inference_mode through the encode API. The fixed sample uses batch size 1 for heterogeneous media; measure any throughput batch-size tuning under a single frozen policy and record CPU model, logical/physical cores, PyTorch threads, batch size, precision, preprocessing time, load time, index time, per-query latency and peak RSS.

## Existing application distinction

The current app.py passes config_kwargs={"vision_config": None, "audio_config": None} when loading the checkpoint. Transformers v5.19.0 conditionally sets vision/audio towers to None for those config values and throws explicit errors if an image/video/audio feature is requested without its tower. The recorded app runtime reports CPU float32 and 271,002,624 parameters. That is evidence of the app's intentionally text-only instance; it is not evidence that the pinned full model lacks native modalities.

## Evaluation interpretation

The current run has 75 gold questions (71 answerable, 4 unanswerable; dev 15/test 60). This model returns embeddings/similarities, not answers. Report retrieval ranking metrics and no-answer/rejection behavior separately from answer generation. Any similarity threshold must be selected from dev only, fixed before test, and described as a retrieval/rejection policy rather than model-generated abstention.

## Sources (official primary sources)

- [Pinned Hugging Face model card and files](https://huggingface.co/google/embeddinggemma-2/tree/914f7f89142e33e77833254d9c9b90c3cef7303b)
- [Pinned config.json](https://huggingface.co/google/embeddinggemma-2/blob/914f7f89142e33e77833254d9c9b90c3cef7303b/config.json)
- [Pinned config_sentence_transformers.json](https://huggingface.co/google/embeddinggemma-2/blob/914f7f89142e33e77833254d9c9b90c3cef7303b/config_sentence_transformers.json)
- [Transformers EmbeddingGemma2 documentation](https://huggingface.co/docs/transformers/model_doc/embedding_gemma2)
- [Transformers v5.19.0 model implementation](https://github.com/huggingface/transformers/blob/v5.19.0/src/transformers/models/embedding_gemma2/modeling_embedding_gemma2.py)
- [Transformers v5.19.0 processor implementation](https://github.com/huggingface/transformers/blob/v5.19.0/src/transformers/models/embedding_gemma2/processing_embedding_gemma2.py)
- [Sentence Transformers input formats](https://sbert.net/docs/input_formats.html)
- [Sentence Transformers v6.1 installation and extras](https://sbert.net/docs/installation.html)
- [Sentence Transformers v6.1.0 package dependency metadata](https://github.com/huggingface/sentence-transformers/blob/v6.1.0/pyproject.toml)
- [Sentence Transformers encode API](https://sbert.net/docs/package_reference/sentence_transformer/model.html)

Local evidence: requirements.txt, app.py, results/runtime.json, multimodal-benchmark/manifest.json, and the two audio ffprobe JSONs listed above.

## Unverified by this research task

No full multimodal model was loaded and no image/audio/video embedding was executed here, to avoid a second large model load while the experiment runner owns the runtime. Native support and API contracts are verified from the pinned checkpoint metadata plus official versioned Transformers/Sentence Transformers docs and source. End-to-end media decoding, output shape/finite values, cold-load time, CPU throughput, peak RSS, and benchmark retrieval quality remain for the experiment runner to measure.
