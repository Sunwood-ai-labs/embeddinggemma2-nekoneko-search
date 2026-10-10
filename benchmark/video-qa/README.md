# 動画ごとのQA一覧

5本の動画に対応する評価者用QA。ExcelはVIDEO_QA.xlsxの動画ID別5シート。各CSV/Markdown/JSONLは動画1本ずつ。正解のない実行用はqueries-*.jsonl。

| 動画 | QA数 | QA一覧 | CSV | 質問のみ |
|---|---:|---|---|---|
| [F2検査台の作業記録](../../inputs/video/f2_inspection.mp4) | 6 | [V-F2.md](V-F2.md) | [CSV](V-F2.csv) | [JSONL](queries-V-F2.jsonl) |
| [W3梱包ラインの作業記録](../../inputs/video/w3_packing.mp4) | 5 | [V-W3.md](V-W3.md) | [CSV](V-W3.csv) | [JSONL](queries-V-W3.jsonl) |
| [C1ソフト更新の訓練記録](../../inputs/video/c1_update.mp4) | 5 | [V-C1.md](V-C1.md) | [CSV](V-C1.csv) | [JSONL](queries-V-C1.jsonl) |
| [倉庫の安全点検訓練記録](../../inputs/video/warehouse_safety.mp4) | 5 | [V-SAFE.md](V-SAFE.md) | [CSV](V-SAFE.csv) | [JSONL](queries-V-SAFE.jsonl) |
| [W3ポンプ整備の訓練記録](../../inputs/video/w3_maintenance.mp4) | 5 | [V-W3-M.md](V-W3-M.md) | [CSV](V-W3-M.csv) | [JSONL](queries-V-W3-M.jsonl) |

[動画別QA Excel](../VIDEO_QA.xlsx)
F2検査の6問には、PDFの音規格と照合する複数資料の問いNKB-055を含みます。他の動画は各5問。動画を参照する問は計26問、全体QAは75問です。
複数の時刻区間を根拠にする動画質問では、Excelの開始/終了秒は区間全体の最小開始～最大終了です。根拠欄・goldには各区間を個別に残します。
