import json
from pathlib import Path

root = Path(__file__).parent
docs = json.loads((root / 'data/corpus.json').read_text(encoding='utf-8'))
lines = ['# ネコネコインダストリー株式会社 社内情報', '', 'この会社、人物、製品、システム、制度、数値は全て実験用の架空情報です。既存システムから取得したデータではありません。', '', '検索用原本は data/corpus.json。現行24文書と廃止済み2文書を収録。', '']
for d in docs:
    lines.extend([f"## {d['id']} {d['title']}", '', f"担当: {d['department']} / 状態: {'現行' if d['status']=='current' else '廃止済み・検索対象外'}", '', d['text'], ''])
(root / 'COMPANY.md').write_text('\n'.join(lines), encoding='utf-8')
