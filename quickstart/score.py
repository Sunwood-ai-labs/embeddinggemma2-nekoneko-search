"""検索結果を正解データと照らし、資料単位の Hit@k と MRR@10 を出す。標準ライブラリだけで動く。

使い方:
  python quickstart/score.py results/multimodal/raw/test-query-results.jsonl benchmark/gold.jsonl

- 検索結果: 1行1質問のJSONL。query_id と asset_ranking（rank, asset_id）を持つ。search.py --queries の出力と同じ形。
  repetition があれば 1 回目だけを採点する。
- 正解: 1行1質問のJSONL。id, answerable, modality, evidence[].asset_id を持つ。
- 回答できない質問（answerable=false）は分母に入れない。正解資料が複数ある質問は、最も上位の1つで判定する。
"""
import json
import sys
from collections import defaultdict


def load(path):
    with open(path, encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


results, gold = load(sys.argv[1]), {g["id"]: g for g in load(sys.argv[2])}
rows = []
for r in results:
    g = gold.get(r["query_id"])
    if r.get("repetition", 1) != 1 or g is None or not g["answerable"]:
        continue
    wanted = {e["asset_id"] for e in g["evidence"]}
    rank = next((a["rank"] for a in r["asset_ranking"] if a["asset_id"] in wanted), None)
    rows.append((g["modality"], rank))

groups = defaultdict(list)
for modality, rank in rows:
    groups["all"].append(rank)
    groups[modality].append(rank)

print(f"{'modality':<14}{'n':>4}{'Hit@1':>8}{'Hit@3':>8}{'Hit@5':>8}{'MRR@10':>9}")
for name in ["all"] + sorted(k for k in groups if k != "all"):
    ranks = groups[name]
    n = len(ranks)
    hits = [sum(r is not None and r <= k for r in ranks) for k in (1, 3, 5)]
    mrr = sum(1 / r for r in ranks if r is not None and r <= 10) / n
    print(f"{name:<14}{n:>4}" + "".join(f"{h:>5}/{n:<2}" for h in hits) + f"{mrr:>9.3f}")
