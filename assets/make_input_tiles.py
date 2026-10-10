"""入力資料14点の中身がわかるタイル画像（assets/inputs-*.jpg）を作る。

ページ画像・動画のフレーム・音声ファイルは実験フォルダ（multimodal-benchmark）にあり、このリポジトリには
含めていない。作り直すときは、そのフォルダを引数で渡す。ヘッドレスChromeとPillowが要る。

使い方（リポジトリ直下で）: python assets/make_input_tiles.py <multimodal-benchmarkのパス>
"""
import array
import html
import json
import math
import os
import subprocess
import sys
import wave
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]).resolve()
CHROME = os.environ.get('CHROME', 'C:/Program Files/Google/Chrome/Application/chrome.exe')
INK, SUB, GRID, TRACK, ACCENT = '#111827', '#6B7280', '#D1D5DB', '#F3F4F6', '#1A73E8'
W, PAD, GAP, LABEL_H, HEAD_H = 1760, 32, 16, 46, 100

CSS = f"""
*{{box-sizing:border-box;margin:0}}
body{{width:{W}px;background:#fff;font-family:'Segoe UI','Hiragino Sans','Yu Gothic UI','Meiryo','Noto Sans JP',sans-serif;color:{INK}}}
.card{{width:{W}px;border:1px solid {GRID};border-radius:16px;padding:0 {PAD}px {PAD}px;overflow:hidden}}
.head{{height:{HEAD_H}px;padding-top:26px}}
h1{{font-size:28px;font-weight:700}}
.sub{{font-size:17px;color:{SUB};margin-top:6px}}
.grid{{display:grid;gap:{GAP}px;margin-top:{GAP}px}}
.grid:first-of-type{{margin-top:0}}
.tile{{border:1px solid {GRID};border-radius:10px;overflow:hidden;background:#fff}}
.label{{height:{LABEL_H}px;display:flex;align-items:center;gap:10px;padding:0 12px;border-bottom:1px solid {GRID};white-space:nowrap;overflow:hidden}}
.chip{{font:700 13px ui-monospace,Consolas,monospace;color:#fff;background:{ACCENT};border-radius:6px;padding:3px 8px}}
.name{{font-size:16px;font-weight:700}}
.note{{font-size:13.5px;color:{SUB}}}
.pic{{background:{TRACK};display:flex;justify-content:center;align-items:flex-start;overflow:hidden}}
.pic img{{height:100%;width:100%;object-fit:contain;object-position:top}}
.pic.cover img{{object-fit:cover;object-position:left top}}
.audio{{padding:14px 18px;background:#fff;display:block}}
.line{{font-size:16.5px;line-height:30px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.line b{{font:700 13.5px ui-monospace,Consolas,monospace;color:{ACCENT};display:inline-block;width:132px}}
"""


def img(path, cover=False):
    return ('cover' if cover else ''), f'<img src="{(SRC / path).as_uri()}">'


def waveform(wav_path, width, height, cuts=()):
    """音声の振幅をSVGにする。cuts は検索単位の境目（秒）。"""
    with wave.open(str(wav_path)) as w:
        samples = array.array('h', w.readframes(w.getnframes()))
        duration = w.getnframes() / w.getframerate()
    step = max(1, len(samples) // width)
    peak = max(1, max(abs(s) for s in samples))
    mid = height / 2
    bars = []
    for x in range(width):
        chunk = samples[x * step:(x + 1) * step]
        if chunk:
            a = max(abs(s) for s in chunk) / peak * (mid - 4)
            bars.append(f'<line x1="{x}" x2="{x}" y1="{mid - a:.1f}" y2="{mid + a:.1f}" stroke="{ACCENT}"/>')
    for c in cuts:
        x = c / duration * width
        bars.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{height}" stroke="{INK}" stroke-dasharray="5 4" stroke-width="1.5"/>'
                    f'<text x="{x + 5:.1f}" y="14" font-size="13" fill="{INK}">{c:.0f}秒</text>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" style="display:block;background:{TRACK};border-radius:6px">{"".join(bars)}</svg>'


def build(name, title, subtitle, sections):
    """sections: [(列数, 画像部分の高さ, [(ID, 名前, 補足, (class, 中身のHTML))...])]"""
    parts, total = [], HEAD_H + PAD + 2
    for i, (cols, pic_h, tiles) in enumerate(sections):
        rows = math.ceil(len(tiles) / cols)
        total += rows * (LABEL_H + pic_h + 2) + (rows - 1) * GAP + (GAP if i else 0)
        cells = ''.join(
            f'<div class="tile"><div class="label"><span class="chip">{chip}</span><span class="name">{html.escape(label)}</span>'
            f'<span class="note">{html.escape(note)}</span></div><div class="pic {cls}" style="height:{pic_h}px">{body}</div></div>'
            for chip, label, note, (cls, body) in tiles)
        parts.append(f'<div class="grid" style="grid-template-columns:repeat({cols},minmax(0,1fr))">{cells}</div>')
    page = (f'<!doctype html><meta charset="utf-8"><style>{CSS}</style><div class="card"><div class="head"><h1>{html.escape(title)}</h1>'
            f'<div class="sub">{html.escape(subtitle)}</div></div>{"".join(parts)}</div>')
    tmp_html, tmp_png = ROOT / 'assets' / f'_{name}.html', ROOT / 'assets' / f'_{name}.png'
    tmp_html.write_text(page, encoding='utf-8')
    subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--allow-file-access-from-files',
                    f'--window-size={W},{total}', f'--screenshot={tmp_png}', tmp_html.as_uri()],
                   check=True, capture_output=True)
    Image.open(tmp_png).convert('RGB').save(ROOT / 'assets' / f'{name}.jpg', quality=88, optimize=True)
    tmp_html.unlink()
    tmp_png.unlink()
    print(f'wrote {name}.jpg ({W}x{total})')


timings = json.loads((SRC / 'sources/audio-timings.json').read_text(encoding='utf-8'))


def audio_tile(asset_id, wav, inner_w, full=True):
    cuts = (15, 30, 45)
    svg = waveform(SRC / wav, inner_w, 110 if full else 150, cuts if full else ())
    if not full:
        return 'audio', svg
    lines = ''.join(f'<div class="line"><b>{t["start_seconds"]:.1f}–{t["end_seconds"]:.1f}秒</b>{html.escape(t["text"])}</div>'
                    for t in timings if t['asset_id'] == asset_id)
    return 'audio', svg + f'<div style="margin-top:10px">{lines}</div>'


col3 = (W - 2 * PAD - 2 - 2 * GAP) / 3
VIDEOS = [('V-F2', 'F2検査', 'f2_inspection.mp4'), ('V-W3', 'W3梱包', 'w3_packing.mp4'), ('V-C1', 'C1ソフト更新', 'c1_update.mp4'),
          ('V-SAFE', '倉庫安全点検', 'warehouse_safety.mp4'), ('V-W3-M', 'W3ポンプ整備', 'w3_maintenance.mp4')]

# ---- 1. 全14資料の一覧 ----
thumb = lambda p: img(p, cover=True)
col5 = int((W - 2 * PAD - 2 - 4 * GAP) / 5)
build('inputs-overview', '検索対象にした14資料', 'ネコネコインダストリー（架空）。Word 2・PDF 2・Excel 2・PowerPoint 1・音声 2・動画 5', [(5, 190, [
    ('D-HR', '勤務ガイド', 'Word 2ページ', thumb('qa/hr_policy/page-1.png')),
    ('D-IT', 'セキュリティガイド', 'Word 1ページ', thumb('qa/security_guide/page-1.png')),
    ('P-QA', '品質通知', 'PDF 2ページ', thumb('qa/quality-1.png')),
    ('P-OLD', '旧在宅勤務規程', 'PDF 廃止済み', thumb('qa/archive-1.png')),
    ('X-LOT', '製造実績', 'Excel', thumb('qa/production-preview.png')),
    ('X-EXP', '経費申請例', 'Excel', thumb('qa/expenses-preview.png')),
    ('S-PLAN', 'Q4計画', 'PowerPoint 6枚', thumb('qa/slide-1.png')),
    ('A-QA', '品質会議', '音声 61秒', audio_tile('A-QA', 'inputs/audio/quality_meeting.wav', col5 - 38, full=False)),
    ('A-LOG', '倉庫放送', '音声 60秒', audio_tile('A-LOG', 'inputs/audio/warehouse_announcement.wav', col5 - 38, full=False)),
    *[(vid, label, '動画 24秒', thumb(f'qa/integrated-{vid}-9s.png')) for vid, label, _ in VIDEOS],
])])

# ---- 2. Word と PDF ----
build('inputs-documents', 'WordとPDF（4資料・全6ページ）', '各ページの上部。見出しごと、ページごとに区切り、抜き出した文章をモデルに渡した', [(3, int(col3 * 2002 / 1547 * 0.6), [
    ('D-HR', '勤務ガイド', 'Word 1/2ページ', img('qa/hr_policy/page-1.png', cover=True)),
    ('D-HR', '勤務ガイド', 'Word 2/2ページ', img('qa/hr_policy/page-2.png', cover=True)),
    ('D-IT', 'セキュリティガイド', 'Word 1ページ', img('qa/security_guide/page-1.png', cover=True)),
    ('P-QA', '品質通知', 'PDF 1/2ページ', img('qa/quality-1.png', cover=True)),
    ('P-QA', '品質通知', 'PDF 2/2ページ', img('qa/quality-2.png', cover=True)),
    ('P-OLD', '旧在宅勤務規程', 'PDF 廃止済み', img('qa/archive-1.png', cover=True)),
])])

# ---- 3. Excel と PowerPoint ----
build('inputs-office', 'ExcelとPowerPoint（3資料）', 'Excelは1行ごと、PowerPointは1スライドごとに区切り、抜き出した文章をモデルに渡した', [
    (2, 300, [
        ('X-LOT', '製造実績', 'Excel 3ロットの生産数・不良数', img('qa/production-preview.png')),
        ('X-EXP', '経費申請例', 'Excel 3件の申請と上限超過', img('qa/expenses-preview.png')),
    ]),
    (3, int(col3 * 9 / 16), [('S-PLAN', 'Q4計画', f'PowerPoint {n}/6枚', img(f'qa/slide-{n}.png')) for n in range(1, 7)]),
])

# ---- 4. 音声 ----
inner = W - 2 * PAD - 2 - 36
build('inputs-audio', '音声（2資料・各約60秒）', '合成音声の読み上げ。点線は15秒ごとの検索単位の境目。下の文は読み上げた内容で、索引には入れていない', [(1, 110 + 10 + 6 * 30 + 30, [
    ('A-QA', '品質会議', '音声 61.0秒', audio_tile('A-QA', 'inputs/audio/quality_meeting.wav', inner)),
    ('A-LOG', '倉庫放送', '音声 60.0秒', audio_tile('A-LOG', 'inputs/audio/warehouse_announcement.wav', inner)),
])])

# ---- 5. 動画 ----
col4 = (W - 2 * PAD - 2 - 3 * GAP) / 4
build('inputs-video', '動画（5資料・各24秒）', '文字と色が切り替わる無音の訓練用アニメーション。6秒ごとの4区間を、動画のままモデルに渡した', [(4, int(col4 * 9 / 16), [
    (vid, label, f'{s - 3}〜{s + 3}秒の区間', img(f'qa/integrated-{vid}-{s}s.png'))
    for vid, label, _ in VIDEOS for s in (3, 9, 15, 21)
])])
