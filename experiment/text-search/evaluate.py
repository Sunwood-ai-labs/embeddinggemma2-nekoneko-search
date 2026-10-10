"""Real HTTP evaluation; gold labels are not sent to the service."""
import hashlib
import json
import statistics
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
BASE = 'http://127.0.0.1:8080'
questions_path = ROOT / 'data/questions.json'
questions = json.loads(questions_path.read_text(encoding='utf-8'))


def get(path):
    return json.load(urllib.request.urlopen(BASE + path, timeout=60))


def search(query):
    req = urllib.request.Request(BASE + '/search', data=json.dumps({'query': query, 'k': 10}).encode(), headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=120))


rows = []
for q in questions['answerable']:
    response = search(q['query'])
    ids = [r['id'] for r in response['results']]
    rank = ids.index(q['expected']) + 1 if q['expected'] in ids else None
    rows.append({**q, 'rank': rank, 'response': response})
    print(f"{len(rows):02d} expected={q['expected']} top1={ids[0]} rank={rank}", flush=True)
unknown = [search(q) for q in questions['unanswerable']]
n = len(rows)
summary = {
    'n_queries': n,
    'top1_hits': sum(r['rank'] == 1 for r in rows),
    'hit_at_1': sum(r['rank'] == 1 for r in rows) / n,
    'hit_at_3': sum(r['rank'] is not None and r['rank'] <= 3 for r in rows) / n,
    'mrr_at_10': sum(1 / r['rank'] if r['rank'] else 0 for r in rows) / n,
    'median_query_ms': statistics.median(r['response']['latency_ms'] for r in rows),
    'mean_query_ms': statistics.mean(r['response']['latency_ms'] for r in rows),
    'max_query_ms': max(r['response']['latency_ms'] for r in rows),
}
report = {
    'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'runtime': get('/health'), 'method': questions['method'],
    'questions_sha256': hashlib.sha256(questions_path.read_bytes()).hexdigest(),
    'summary': summary, 'answerable_results': rows, 'unanswerable_results': unknown,
    'limitations': ['手作り24問・24現行文書の小規模実験であり一般性能の保証ではない', '社内情報・質問・正解は全て架空', '未収録の質問を拒否する閾値は未実装', '時系列判断は現行文書メタデータによる事前フィルタ', 'アクセス制御・回答生成・マルチモーダルは未実験'],
}
(ROOT / 'results/evaluation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
md = ['# ネコネコインダストリー 社内検索実験', '', '全て架空の情報を使い、Podman Compose内でEmbeddingGemma 2を実行した結果。', '', f"- モデル: `{report['runtime']['model_id']}`", f"- revision: `{report['runtime']['resolved_revision']}`", f"- CPU float32 / 768次元 / 現行文書24件 / 旧文書2件は事前除外", f"- 正解文書が1位: {summary['top1_hits']}/{n} ({summary['hit_at_1']:.1%})", f"- 正解文書が上位3件: {summary['hit_at_3']:.1%}", f"- MRR@10: {summary['mrr_at_10']:.4f}", f"- 検索時間中央値: {summary['median_query_ms']:.1f}ms (HTTPサービス内の計測、CPU)", '', '|質問|期待文書|検索1位|正解順位|', '|---|---|---|---|']
for r in rows:
    md.append(f"|{r['query']}|{r['expected']}|{r['response']['results'][0]['id']}|{r['rank'] or '圏外'}|")
md += ['', '## 社内情報に答えがない質問', '', '検索では必ず候補が返る。この候補を回答とみなすと誤回答になる。類似度は回答の正確さを表さない。', '']
for r in unknown:
    md.append(f"- 「{r['query']}」→ {r['results'][0]['id']} {r['results'][0]['title']} (score={r['results'][0]['score']})。質問の答えは文書にない。")
md += ['', '## 確認範囲', '', *['- ' + s for s in report['limitations']], '', '文書・質問はモデル実行前に固定し、評価結果を見て正解や質問を変更していない。検索スコアは実モデルが生成した正規化ベクトルの内積。詳細はevaluation.jsonとruntime.jsonを参照。']
(ROOT / 'results/REPORT.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
print(json.dumps(summary, indent=2), flush=True)
