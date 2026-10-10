import hashlib
import importlib.metadata
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import torch
from fastapi import FastAPI
from fastapi.responses import FileResponse
from huggingface_hub import snapshot_download
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).parent
MODEL_ID = os.environ.get('MODEL_ID', 'google/embeddinggemma-2')
REVISION = os.environ.get('MODEL_REVISION', '914f7f89142e33e77833254d9c9b90c3cef7303b')
DOCUMENTS = json.loads((ROOT / 'data/corpus.json').read_text(encoding='utf-8'))
CURRENT = [d for d in DOCUMENTS if d['status'] == 'current']
LOCK = threading.Lock()
MODEL = None
INDEX = None
INFO = {}


@asynccontextmanager
async def lifespan(app):
    global MODEL, INDEX, INFO
    torch.set_num_threads(int(os.environ.get('TORCH_THREADS', '4')))
    started = time.perf_counter()
    print(f'Loading actual model {MODEL_ID}@{REVISION} on CPU float32', flush=True)
    checkpoint = Path(snapshot_download(repo_id=MODEL_ID, revision=REVISION))
    resolved = checkpoint.name
    assert resolved == REVISION, f'Snapshot revision mismatch: {resolved}'
    assert (checkpoint / 'model.safetensors').is_file()
    MODEL = SentenceTransformer(
        str(checkpoint), device='cpu',
        config_kwargs={'vision_config': None, 'audio_config': None},
        model_kwargs={'dtype': torch.float32},
    )
    load_seconds = time.perf_counter() - started
    started = time.perf_counter()
    texts = [f"title: {d['title']} | text: {d['text']}" for d in CURRENT]
    INDEX = MODEL.encode(texts, prompt='', normalize_embeddings=True, batch_size=4, show_progress_bar=True)
    index_seconds = time.perf_counter() - started
    assert INDEX.shape == (len(CURRENT), 768), INDEX.shape
    assert np.isfinite(INDEX).all()
    assert np.allclose(np.linalg.norm(INDEX, axis=1), 1, atol=1e-4)
    INFO = {
        'model_id': MODEL_ID, 'requested_revision': REVISION, 'resolved_revision': resolved,
        'loaded_from_snapshot': str(checkpoint),
        'checkpoint_blob': (checkpoint / 'model.safetensors').resolve().name,
        'architecture': MODEL[0].auto_model.__class__.__name__, 'device': str(MODEL.device),
        'dtype': str(MODEL.dtype), 'dimensions': 768,
        'parameters_loaded': sum(p.numel() for p in MODEL.parameters()),
        'torch_threads': torch.get_num_threads(), 'current_documents': len(CURRENT),
        'archived_documents_excluded': len(DOCUMENTS) - len(CURRENT),
        'load_seconds': round(load_seconds, 3), 'index_seconds': round(index_seconds, 3),
        'query_prompt': MODEL.prompts['Retrieval-query'], 'document_prompt': 'title: <title> | text: ',
        'corpus_sha256': hashlib.sha256((ROOT / 'data/corpus.json').read_bytes()).hexdigest(),
        'packages': {p: importlib.metadata.version(p) for p in ('torch', 'transformers', 'sentence-transformers', 'numpy', 'fastapi')},
        'fictional': True, 'retrieval_only': True,
    }
    (ROOT / 'results').mkdir(exist_ok=True)
    np.save(ROOT / 'results/document_embeddings.npy', INDEX)
    (ROOT / 'results/runtime.json').write_text(json.dumps(INFO, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(INFO, ensure_ascii=False), flush=True)
    yield


app = FastAPI(title='ネコネコインダストリー / EmbeddingGemma 2 検索実験', lifespan=lifespan)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=3, ge=1, le=10)


@app.get('/')
def home():
    return FileResponse(ROOT / 'index.html')


@app.get('/health')
def health():
    return {'ready': INDEX is not None, **INFO}


@app.get('/documents')
def documents():
    return DOCUMENTS


@app.post('/search')
def search(request: SearchRequest):
    started = time.perf_counter()
    with LOCK, torch.inference_mode():
        vector = MODEL.encode(request.query, prompt_name='Retrieval-query', normalize_embeddings=True)
    assert vector.shape == (768,) and np.isfinite(vector).all()
    scores = INDEX @ vector
    ranked = np.argsort(-scores)[:request.k]
    return {
        'query': request.query, 'latency_ms': round((time.perf_counter() - started) * 1000, 2),
        'model_id': MODEL_ID, 'revision': REVISION,
        'results': [{**CURRENT[int(i)], 'score': round(float(scores[i]), 6)} for i in ranked],
        'notice': '意味の近い文書を検索した結果です。スコアは正しさの確率ではありません。情報がない質問にも候補が出ます。回答生成・事実検証・権限制御は行いません。',
    }
