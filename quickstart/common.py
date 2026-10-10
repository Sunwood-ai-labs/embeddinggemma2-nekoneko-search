"""モデルの読み込みと共通設定。実験（experiment/multimodal/run_experiment.py）と同じ値に固定している。"""
import os
from pathlib import Path

import torch
from huggingface_hub import snapshot_download
from sentence_transformers import SentenceTransformer

MODEL_ID = os.environ.get("MODEL_ID", "google/embeddinggemma-2")
MODEL_REVISION = os.environ.get("MODEL_REVISION", "914f7f89142e33e77833254d9c9b90c3cef7303b")
TORCH_THREADS = int(os.environ.get("TORCH_THREADS", "4"))
QUERY_PROMPT_NAME = "QuestionAnswering"  # "task: question answering | query: "
VIDEO_PROCESSING = {"fps": 1, "max_frames": 32, "overflow_strategy": "uniform", "add_timestamps": False}
OUT = Path("/work/out")


def snapshot() -> Path:
    """固定したrevisionの重みを取得し、そのローカルパスを返す（2回目以降はキャッシュを使う）。"""
    path = Path(snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION))
    assert path.name == MODEL_REVISION, f"revision mismatch: {path.name}"
    return path


def load_model() -> SentenceTransformer:
    torch.set_num_threads(TORCH_THREADS)
    # CPUではfloat32を使う。モデルカードはfloat16を使わないよう明記している。
    model = SentenceTransformer(str(snapshot()), device="cpu", model_kwargs={"dtype": torch.float32})
    unsupported = [m for m in ("text", "image", "audio", "video") if not model.supports(m)]
    assert not unsupported, f"unsupported modalities: {unsupported}"
    return model
