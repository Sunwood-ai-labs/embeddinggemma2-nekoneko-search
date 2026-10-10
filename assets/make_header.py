"""README用のヘッダー画像（assets/header.svg）を、実測値から作る。

使い方（リポジトリ直下で）: python assets/make_header.py
"""
import csv
import statistics
import xml.dom.minidom
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
A, A2 = '#4285F4', '#8AB4F8'
SANS = "font-family=\"'Segoe UI','Helvetica Neue',Helvetica,Arial,sans-serif\""
MONO = 'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"'

with (ROOT / 'results/multimodal/attempt-05-test-query-outcomes-latency.csv').open(encoding='utf-8-sig') as stream:
    calls = list(csv.DictReader(stream))
scored = [r for r in calls if r['repetition'] == '1' and r['answerable'] == 'True']
n = len(scored)
h1 = sum(r['asset_hit_at_1'] == 'True' for r in scored)
h5 = sum(r['asset_hit_at_5'] == 'True' for r in scored)
median = statistics.median(float(r['elapsed_ms']) for r in calls)
by = defaultdict(list)
for r in scored:
    by[r['modality']].append(r['asset_hit_at_1'] == 'True')
rows = [('DOCX', 'document'), ('PPTX', 'presentation'), ('MP4', 'video'), ('PDF', 'pdf'), ('WAV', 'audio'), ('XLSX', 'spreadsheet')]

out = [
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 420" width="1280" height="420" role="img" aria-label="EmbeddingGemma 2 x Neko-Neko Industry: multimodal retrieval field test">',
    '<defs>',
    '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0B0F14"/><stop offset="0.6" stop-color="#0D1420"/><stop offset="1" stop-color="#0E1A30"/></linearGradient>',
    f'<radialGradient id="glow" cx="0.82" cy="0.25" r="0.6"><stop offset="0" stop-color="{A}" stop-opacity="0.24"/><stop offset="1" stop-color="{A}" stop-opacity="0"/></radialGradient>',
    f'<linearGradient id="title" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="{A2}"/></linearGradient>',
    '<pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0H0V32" fill="none" stroke="#FFFFFF" stroke-opacity="0.035"/></pattern>',
    '<clipPath id="r"><rect width="1280" height="420" rx="20"/></clipPath>',
    '</defs>',
    '<g clip-path="url(#r)">',
    '<rect width="1280" height="420" fill="url(#bg)"/><rect width="1280" height="420" fill="url(#grid)"/><rect width="1280" height="420" fill="url(#glow)"/>',
    f'<g {SANS}>',
    f'<rect x="64" y="70" width="250" height="30" rx="15" fill="{A}" fill-opacity="0.14" stroke="{A}" stroke-opacity="0.55"/>',
    f'<text x="189" y="90" text-anchor="middle" font-size="13" font-weight="700" letter-spacing="2" fill="{A2}">MULTIMODAL EMBEDDING</text>',
    '<text x="64" y="170" font-size="58" font-weight="800" fill="url(#title)" letter-spacing="-1">EmbeddingGemma 2</text>',
    f'<text x="64" y="218" font-size="26" font-weight="600" fill="#9CA3AF"><tspan fill="{A}">×</tspan> Neko-Neko Industry</text>',
    '<text x="64" y="254" font-size="19" fill="#6B7280">Docs, sheets, slides, audio and video in one search index</text>',
    '</g>',
]
for i, (big, small) in enumerate([(f'{h1} / {n}', 'right file at rank 1'), (f'{h5} / {n}', 'right file in top 5'), (f'{median:.0f} ms', 'median query, CPU')]):
    x = 64 + i * 200
    out.append(f'<g {SANS}><rect x="{x}" y="304" width="186" height="64" rx="12" fill="#FFFFFF" fill-opacity="0.04" stroke="#FFFFFF" stroke-opacity="0.10"/>'
               f'<text x="{x + 18}" y="332" font-size="22" font-weight="800" fill="#F9FAFB">{big}</text>'
               f'<text x="{x + 18}" y="354" font-size="12.5" fill="#9CA3AF" letter-spacing="0.4">{small}</text></g>')
out += [
    '<rect x="700" y="52" width="552" height="316" rx="16" fill="#000000" fill-opacity="0.28" stroke="#FFFFFF" stroke-opacity="0.08"/>',
    f'<text x="722" y="82" {MONO} font-size="12" fill="#6B7280" letter-spacing="1">RIGHT FILE AT RANK 1, BY FORMAT</text>',
    f'<text x="1230" y="82" text-anchor="end" {MONO} font-size="12" fill="#6B7280">{n} questions</text>',
]
x0, bw = 792, 340
for i, (tag, key) in enumerate(rows):
    y = 104 + i * 42
    hits, total = sum(by[key]), len(by[key])
    out += [
        f'<text x="722" y="{y + 15}" {MONO} font-size="13" font-weight="700" fill="#D1D5DB">{tag}</text>',
        f'<rect x="{x0}" y="{y}" width="{bw}" height="20" rx="10" fill="#FFFFFF" fill-opacity="0.05"/>',
        f'<rect x="{x0}" y="{y}" width="{hits / total * bw:.1f}" height="20" rx="10" fill="{A}"/>',
        f'<text x="1230" y="{y + 15}" text-anchor="end" {MONO} font-size="13" fill="#F9FAFB">{hits}/{total}</text>',
    ]
out += [f'<rect x="0" y="0" width="6" height="420" fill="{A}"/>', '</g></svg>']
svg = '\n'.join(out)
xml.dom.minidom.parseString(svg)  # XMLとして読めることを確かめる
(ROOT / 'assets/header.svg').write_text(svg, encoding='utf-8', newline='\n')
print('wrote header.svg')
