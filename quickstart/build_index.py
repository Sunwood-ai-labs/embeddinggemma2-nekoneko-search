"""inputs/ の資料をチャンクに分け、EmbeddingGemma 2でベクトルにして out/ に保存する。

使い方（コンテナ内）: python build_index.py
"""
import json
import time
from pathlib import Path

import numpy as np

from chunking import chunk_folder
from common import OUT, VIDEO_PROCESSING, load_model

INPUTS = Path("/work/inputs")

chunks = chunk_folder(INPUTS, OUT / "derived")
assert chunks, "inputs/ に対応する資料がありません"
print(f"{len(chunks)} chunks from {len({c['asset_id'] for c in chunks})} files")

model = load_model()
common = {"normalize_embeddings": True, "convert_to_numpy": True, "batch_size": 1, "show_progress_bar": False}
vectors, started = [], time.perf_counter()
for i, chunk in enumerate(chunks, 1):
    t0 = time.perf_counter()
    if chunk["text"]:
        # 文章は「title: <題名> | text: 」を先頭に付けて埋め込む
        vec = model.encode_document([chunk["text"]], prompt=f"title: {chunk['title']} | text: ", **common)[0]
    else:
        # 音声・動画はファイルをそのまま渡す。文章用の接頭辞は付けない（prompt=""）
        kwargs = dict(common, prompt="")
        if chunk["modality"] == "video":
            kwargs["processing_kwargs"] = {"video": VIDEO_PROCESSING}
        vec = model.encode_document([{chunk["modality"]: chunk["media_path"]}], **kwargs)[0]
    chunk["embed_seconds"] = round(time.perf_counter() - t0, 3)
    vectors.append(vec)
    print(f"[{i}/{len(chunks)}] {chunk['chunk_id']} {chunk['modality']} {chunk['locator']} {chunk['embed_seconds']}s", flush=True)

matrix = np.stack(vectors).astype(np.float32)
assert np.isfinite(matrix).all()
OUT.mkdir(parents=True, exist_ok=True)
np.save(OUT / "index-vectors.npy", matrix, allow_pickle=False)
with (OUT / "index.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
    for chunk in chunks:
        stream.write(json.dumps(chunk, ensure_ascii=False) + "\n")
print(f"saved {matrix.shape} in {time.perf_counter() - started:.1f}s -> out/index-vectors.npy, out/index.jsonl")
