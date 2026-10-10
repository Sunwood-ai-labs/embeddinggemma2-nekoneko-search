"""google/embeddinggemma-2 の固定revisionをキャッシュへ取得する。初回だけネットワークが要る。"""
from common import MODEL_ID, MODEL_REVISION, snapshot

path = snapshot()
size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
print(f"{MODEL_ID}@{MODEL_REVISION}")
print(f"{path}  ({size / 1e9:.2f} GB)")
