"""作成済みの索引を、日本語の質問で検索する。

使い方（コンテナ内）:
  python search.py "在宅勤務は週に何日まで？"            # 上位5件を表示
  python search.py --queries inputs/queries.jsonl       # {"id","question"} のJSONLをまとめて検索し out/results.jsonl へ
"""
import argparse
import json
import statistics
import time

import numpy as np

from common import OUT, QUERY_PROMPT_NAME, load_model

parser = argparse.ArgumentParser()
parser.add_argument("question", nargs="*")
parser.add_argument("--queries")
parser.add_argument("-k", type=int, default=5)
args = parser.parse_args()

chunks = [json.loads(line) for line in (OUT / "index.jsonl").open(encoding="utf-8")]
vectors = np.load(OUT / "index-vectors.npy")
model = load_model()


def rank(question: str):
    started = time.perf_counter()
    query = model.encode_query([question], prompt_name=QUERY_PROMPT_NAME, normalize_embeddings=True,
                               convert_to_numpy=True, batch_size=1, show_progress_bar=False)[0]
    scores = vectors @ query  # 正規化済みベクトルの内積 = cosine類似度
    order = np.argsort(-scores, kind="stable")
    chunk_ranking = [{"rank": r, "score": float(scores[p]), **{k: chunks[p][k] for k in ("chunk_id", "asset_id", "modality", "locator")}}
                     for r, p in enumerate(order, 1)]
    # 資料ごとの順位は、その資料で最も点の高いチャンクで決める
    asset_ranking, seen = [], set()
    for item in chunk_ranking:
        if item["asset_id"] not in seen:
            seen.add(item["asset_id"])
            asset_ranking.append({"rank": len(seen), "asset_id": item["asset_id"], "score": item["score"], "best_locator": item["locator"]})
    return chunk_ranking, asset_ranking, (time.perf_counter() - started) * 1000


if args.queries:
    times = []
    with open(args.queries, encoding="utf-8") as src, (OUT / "results.jsonl").open("w", encoding="utf-8", newline="\n") as dst:
        for line in filter(str.strip, src):
            q = json.loads(line)
            chunk_ranking, asset_ranking, ms = rank(q["question"])
            times.append(ms)
            dst.write(json.dumps({"query_id": q["id"], "query_text": q["question"], "elapsed_ms": round(ms, 4),
                                  "asset_ranking": asset_ranking, "chunk_ranking": chunk_ranking[:10]}, ensure_ascii=False) + "\n")
    print(f"{len(times)} queries, median {statistics.median(times):.1f} ms -> out/results.jsonl")
else:
    chunk_ranking, _, ms = rank(" ".join(args.question))
    print(f"{ms:.0f} ms")
    for item in chunk_ranking[:args.k]:
        print(f"{item['rank']}. {item['score']:.3f}  {item['asset_id']}  [{item['modality']}] {item['locator']}")
