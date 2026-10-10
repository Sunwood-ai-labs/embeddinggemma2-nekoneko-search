"""results/ の実測値から、記事・README用のグラフ（SVG）を作る。

使い方（リポジトリ直下で）: python assets/make_charts.py
"""
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INK, SUB, GRID, TRACK, ACCENT, CARD = '#111827', '#6B7280', '#D1D5DB', '#EEF0F2', '#1A73E8', '#FFFFFF'
FONT = "font-family=\"'Segoe UI','Hiragino Sans','Yu Gothic UI','Meiryo','Noto Sans JP',sans-serif\""
W = 880


def frame(h, title, subtitle, body):
    return '\n'.join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" width="{W}" height="{h}" role="img" aria-label="{title}" {FONT}>',
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{h - 1}" rx="12" fill="{CARD}" stroke="{GRID}"/>',
        f'<text x="32" y="44" font-size="20" font-weight="700" fill="{INK}">{title}</text>',
        f'<text x="32" y="70" font-size="13.5" fill="{SUB}">{subtitle}</text>',
        *body, '</svg>'])


def write(name, svg):
    (ROOT / 'assets' / name).write_text(svg, encoding='utf-8', newline='\n')
    print('wrote', name)


with (ROOT / 'results/multimodal/attempt-05-test-query-outcomes-latency.csv').open(encoding='utf-8-sig') as stream:
    calls = list(csv.DictReader(stream))
# 精度は1回目の実行（repetition=1）のうち、資料に答えがある質問だけで数える
scored = [r for r in calls if r['repetition'] == '1' and r['answerable'] == 'True']
N = len(scored)


def count(rows, column):
    return sum(r[column] == 'True' for r in rows)


def bar_rows(rows, x0, bw, y0, rh, bh=24):
    """rows: (label, note, value, total)。横棒と「値 / 分母」を描く。"""
    body = []
    for i, (label, note, v, total) in enumerate(rows):
        y = y0 + i * rh
        w = v / total * bw
        body += [
            f'<text x="32" y="{y + 14}" font-size="15" font-weight="700" fill="{INK}">{label}</text>',
            f'<text x="32" y="{y + 32}" font-size="12" fill="{SUB}">{note}</text>',
            f'<rect x="{x0}" y="{y}" width="{bw}" height="{bh}" rx="4" fill="{TRACK}"/>',
            f'<rect x="{x0}" y="{y}" width="{w:.1f}" height="{bh}" rx="4" fill="{ACCENT}"><title>{label}: {v}/{total}</title></rect>',
            f'<text x="{x0 + bw + 12}" y="{y + 18}" font-size="16" font-weight="700" fill="{INK}">{v}<tspan font-weight="400" fill="{SUB}"> / {total}</tspan>'
            f'<tspan font-size="13" font-weight="400" fill="{SUB}">　{v / total * 100:.1f}%</tspan></text>',
        ]
    return body


# ---- 1. 全体：何位までに正解資料が入るか ----
h1, h3, h5 = (count(scored, f'asset_hit_at_{k}') for k in (1, 3, 5))
complete5 = count(scored, 'complete_evidence_at_5')
rows = [
    ('1位が正解資料', '検索結果の先頭が、答えの載った資料', h1, N),
    ('上位3件に正解資料', '', h3, N),
    ('上位5件に正解資料', '', h5, N),
    ('根拠の箇所まで全部そろう', '上位5つの検索単位に、必要なページ・行・区間がすべて入る', complete5, N),
]
x0, bw, y0, rh = 400, 300, 100, 58
write('chart-hit.svg', frame(
    y0 + len(rows) * rh + 4, f'正解資料が1位は{N}問中{h1}問。上位5件まで見れば{h5}問すべて',
    f'EmbeddingGemma 2。14資料・63検索単位に対する、答えのある質問{N}問の検索結果', bar_rows(rows, x0, bw, y0, rh)))

# ---- 2. 資料の形式別：1位が正解資料だった質問 ----
LABEL = {'video': ('動画', '6秒ごとの区間をそのまま入力'), 'document': ('Word', '見出しごとの文章'),
         'presentation': ('PowerPoint', 'スライドごとの文章'), 'pdf': ('PDF', 'ページごとの文章'),
         'audio': ('音声', '15秒ごとの区間をそのまま入力'), 'spreadsheet': ('Excel', '1行ごとの文章'),
         'mixed': ('複数資料の照合', '音声とExcelの両方が必要')}
by = defaultdict(list)
for r in scored:
    by[r['modality']].append(r)
order = sorted(by, key=lambda m: (-count(by[m], 'asset_hit_at_1') / len(by[m]), -len(by[m])))
rows = [(LABEL[m][0], LABEL[m][1], count(by[m], 'asset_hit_at_1'), len(by[m])) for m in order]
x0, bw, y0, rh = 300, 300, 124, 50
body = [
    f'<text x="{x0}" y="104" font-size="12.5" fill="{SUB}">1位が正解資料だった質問</text>',
    f'<text x="750" y="104" font-size="12.5" fill="{SUB}">上位3件なら</text>',
] + bar_rows(rows, x0, bw, y0, rh, bh=22)
for i, m in enumerate(order):
    y = y0 + i * rh
    body.append(f'<text x="750" y="{y + 17}" font-size="14" fill="{INK}">{count(by[m], "asset_hit_at_3")}<tspan fill="{SUB}"> / {len(by[m])}</tspan></text>')
v, e, a = by['video'], by['spreadsheet'], by['audio']
write('chart-modality.svg', frame(
    y0 + len(rows) * rh + 4,
    f'動画は{len(v)}問中{count(v, "asset_hit_at_1")}問で1位。Excelは{len(e)}問中{count(e, "asset_hit_at_1")}問、音声は{len(a)}問中{count(a, "asset_hit_at_1")}問',
    'EmbeddingGemma 2。質問が指定した資料の形式ごとに、その資料が1位になった数', body))

# ---- 3. 検索1回の時間の分布 ----
ms = sorted(float(r['elapsed_ms']) for r in calls)
median = statistics.median(ms)
p95 = ms[math.ceil(0.95 * len(ms)) - 1]  # nearest-rank
lo, hi, step = 80, 280, 10
bins = [0] * ((hi - lo) // step)
for value in ms:
    bins[min(int((value - lo) // step), len(bins) - 1)] += 1
x0, pw, y0, ph = 70, 760, 120, 210
top = max(bins)


def sx(value):
    return x0 + (value - lo) / (hi - lo) * pw


body = [f'<line x1="{x0}" x2="{x0 + pw}" y1="{y0 + ph}" y2="{y0 + ph}" stroke="{GRID}"/>']
for i, n in enumerate(bins):
    if n:
        bh = n / top * ph
        x = sx(lo + i * step)
        body += [
            f'<rect x="{x + 2:.1f}" y="{y0 + ph - bh:.1f}" width="{pw / len(bins) - 4:.1f}" height="{bh:.1f}" rx="3" fill="{ACCENT}"><title>{lo + i * step}〜{lo + (i + 1) * step}ms: {n}回</title></rect>',
            f'<text x="{x + pw / len(bins) / 2:.1f}" y="{y0 + ph - bh - 6:.1f}" font-size="11.5" text-anchor="middle" fill="{SUB}">{n}</text>',
        ]
for value in range(lo, hi + 1, 40):
    body.append(f'<text x="{sx(value):.1f}" y="{y0 + ph + 20}" font-size="12" text-anchor="middle" fill="{SUB}">{value}</text>')
for value, label, dy in ((median, f'中央値 {median:.0f}ms', 0), (p95, f'95%点 {p95:.0f}ms', 0)):
    body += [
        f'<line x1="{sx(value):.1f}" x2="{sx(value):.1f}" y1="{y0 - 22}" y2="{y0 + ph}" stroke="{INK}" stroke-dasharray="5 4" stroke-width="1.5"/>',
        f'<text x="{sx(value) + 8:.1f}" y="{y0 - 12 + dy}" font-size="13" font-weight="700" fill="{INK}">{label}</text>',
    ]
body.append(f'<text x="{x0 + pw / 2}" y="{y0 + ph + 44}" font-size="12.5" text-anchor="middle" fill="{SUB}">質問1件の検索時間（ミリ秒）。棒の上の数字は回数</text>')
write('chart-latency.svg', frame(
    y0 + ph + 64, f'検索1回は中央値{median:.0f}ミリ秒。{len(ms)}回の95%が{p95:.0f}ミリ秒以内',
    'EmbeddingGemma 2、CPU 4スレッド。モデル読み込み後に、質問を埋め込んで63単位と照合するまでの時間', body))

# ---- 4. 索引作成：形式ごとの埋め込み時間 ----
timings = [json.loads(line) for line in (ROOT / 'results/multimodal/raw/document-embedding-timings.jsonl').open(encoding='utf-8')]
sec = defaultdict(list)
for t in timings:
    sec['text' if t['input_representation'] == 'derived_text' else t['modality']].append(t['elapsed_ms'] / 1000)
total = sum(sum(v) for v in sec.values())
rows = [('動画', '6秒の区間', 'video'), ('音声', '15秒の区間', 'audio'), ('文章', 'Office・PDFから抜き出した文章', 'text')]
x0, bw, y0, rh = 400, 280, 100, 58
body = []
for i, (label, unit, key) in enumerate(rows):
    y = y0 + i * rh
    s = sum(sec[key])
    w = s / total * bw
    body += [
        f'<text x="32" y="{y + 14}" font-size="15" font-weight="700" fill="{INK}">{label}<tspan font-size="12.5" font-weight="400" fill="{SUB}">　{len(sec[key])}単位</tspan></text>',
        f'<text x="32" y="{y + 32}" font-size="12" fill="{SUB}">{unit}。1単位あたり中央値 {statistics.median(sec[key]):.1f}秒</text>',
        f'<rect x="{x0}" y="{y}" width="{bw}" height="24" rx="4" fill="{TRACK}"/>',
        f'<rect x="{x0}" y="{y}" width="{max(w, 2):.1f}" height="24" rx="4" fill="{ACCENT}"><title>{label}: {s:.1f}秒</title></rect>',
        f'<text x="{x0 + bw + 12}" y="{y + 18}" font-size="16" font-weight="700" fill="{INK}">{s:.0f}秒<tspan font-size="13" font-weight="400" fill="{SUB}">　{s / total * 100:.0f}%</tspan></text>',
    ]
write('chart-indexing.svg', frame(
    y0 + len(rows) * rh + 4, f'資料の登録にかかった{total:.0f}秒のうち、{sum(sec["video"]) / total * 100:.0f}%は動画',
    f'EmbeddingGemma 2、CPU。{len(timings)}検索単位を1つずつベクトルにした時間の合計', body))
