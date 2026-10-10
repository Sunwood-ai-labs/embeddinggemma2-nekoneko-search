# EmbeddingGemma 2 検索評価レポート

このレポートは検索ランキングを評価し、生成回答の正解率や計算能力は評価しない。testの一次成績は反復1。反復2・3は順位の再現性確認に使う。

## testの要約

- test一次成績（反復1、answerable 57問）: asset Hit@1 43/57、asset Hit@5 57/57、complete evidence@5 42/57。
- クエリ遅延（180回）: median 122.198 ms、p95 201.878 ms。
- 未回答test 3問（NKB-057/058/059）にも検索候補が返ったが、回答生成・拒否判定は評価していない。`unknown_scores.csv` の0件は不正/欠落スコアが0件という意味で、未回答問が0件という意味ではない。

## 入力と実行完全性

- test: 期待 180 calls、記録 180 calls、不足 0 calls。完全性: 確認。
- test: 57 answerable / 3 unanswerable。dev: 14 answerable / 1 unanswerable。
- scores が欠落・不正・非有限の順位行: 0 件（詳細は `unknown_scores.csv`）。
- 構造locatorがgold根拠と合った候補の本文文字列診断: 200 件（詳細は `fact_support_diagnostics.csv`）。本文なし/文字列不一致は主指標の失敗に数えない。
- gold位置表記の未解決: 0 件、indexへ結び付かない候補locator: 0 件（詳細は別CSV）。この件数はmodel false hit/missへ混ぜない。
- DOCXの物理ページ番号を明示改ページで検証できなかった位置: 6 件。これらはソースで一致したsection見出し単位へ限定して採点する。
- runner提供asset_rankingとchunk_rankingからの独立dedup照合: 195/195 calls一致。詳細は `asset_ranking_consistency.csv`。
- ranking品質の正式入力は attempt-05-query-threads4 のrawのみ。旧query attempt 01/03/04は保持したまま除外し、attempt-01のdocument timingだけを同じindex/vector SHAの由来記録として再利用した。旧aggregation contract c0 bodyは未保存（sha256=c0f0a2840b3f…）で、旧query成績を現契約へ再採点していない。

## 品質指標

Hit@k、MRR@10、根拠エントリ coverage は answerable 問題を分母に計算した。Fine evidence の主指標はgoldで指定したasset/pathとsource locatorへの到達を測り、生成回答やfacts理解の正解率は示さない。

| split | rep | 指標 | k | 値 | 分母 | 特記対象数 |
|---|---:|---|---:|---:|---:|---:|
| dev | 1 | asset_hit | 1 | 0.9286 | 14 | 0 |
| dev | 1 | asset_precision | 1 | 0.9286 | 14 | 0 |
| dev | 1 | fine_evidence_hit | 1 | 0.7857 | 14 | 0 |
| dev | 1 | fine_evidence_precision | 1 | 0.7857 | 14 | 0 |
| dev | 1 | complete_evidence | 1 | 0.6429 | 14 | 0 |
| dev | 1 | fine_evidence_coverage | 1 | 0.6964 | 14 | 0 |
| dev | 1 | fine_evidence_unit_fraction_coverage | 1 | 0.6964 | 14 | 0 |
| dev | 1 | asset_hit | 3 | 1.0000 | 14 | 0 |
| dev | 1 | asset_precision | 3 | 0.3571 | 14 | 0 |
| dev | 1 | fine_evidence_hit | 3 | 0.7857 | 14 | 0 |
| dev | 1 | fine_evidence_precision | 3 | 0.3571 | 14 | 0 |
| dev | 1 | complete_evidence | 3 | 0.7143 | 14 | 0 |
| dev | 1 | fine_evidence_coverage | 3 | 0.7679 | 14 | 0 |
| dev | 1 | fine_evidence_unit_fraction_coverage | 3 | 0.7857 | 14 | 0 |
| dev | 1 | asset_hit | 5 | 1.0000 | 14 | 0 |
| dev | 1 | asset_precision | 5 | 0.2143 | 14 | 0 |
| dev | 1 | fine_evidence_hit | 5 | 0.7857 | 14 | 0 |
| dev | 1 | fine_evidence_precision | 5 | 0.2429 | 14 | 0 |
| dev | 1 | complete_evidence | 5 | 0.7857 | 14 | 0 |
| dev | 1 | fine_evidence_coverage | 5 | 0.7857 | 14 | 0 |
| dev | 1 | fine_evidence_unit_fraction_coverage | 5 | 0.8214 | 14 | 0 |
| dev | 1 | asset_hit | 10 | 1.0000 | 14 | 0 |
| dev | 1 | asset_precision | 10 | 0.1071 | 14 | 0 |
| dev | 1 | fine_evidence_hit | 10 | 0.8571 | 14 | 0 |
| dev | 1 | fine_evidence_precision | 10 | 0.1357 | 14 | 0 |
| dev | 1 | complete_evidence | 10 | 0.8571 | 14 | 0 |
| dev | 1 | fine_evidence_coverage | 10 | 0.8571 | 14 | 0 |
| dev | 1 | fine_evidence_unit_fraction_coverage | 10 | 0.8571 | 14 | 0 |
| dev | 1 | asset_mrr | 10 | 0.9643 | 14 | 0 |
| dev | 1 | fine_evidence_mrr | 10 | 0.7946 | 14 | 0 |
| test | 1 | asset_hit | 1 | 0.7544 | 57 | 0 |
| test | 1 | asset_precision | 1 | 0.7544 | 57 | 0 |
| test | 1 | fine_evidence_hit | 1 | 0.6316 | 57 | 0 |
| test | 1 | fine_evidence_precision | 1 | 0.6316 | 57 | 0 |
| test | 1 | complete_evidence | 1 | 0.6140 | 57 | 0 |
| test | 1 | fine_evidence_coverage | 1 | 0.6228 | 57 | 0 |
| test | 1 | fine_evidence_unit_fraction_coverage | 1 | 0.6228 | 57 | 0 |
| test | 1 | asset_hit | 3 | 0.9298 | 57 | 0 |
| test | 1 | asset_precision | 3 | 0.3158 | 57 | 0 |
| test | 1 | fine_evidence_hit | 3 | 0.7193 | 57 | 0 |
| test | 1 | fine_evidence_precision | 3 | 0.2690 | 57 | 0 |
| test | 1 | complete_evidence | 3 | 0.7193 | 57 | 0 |
| test | 1 | fine_evidence_coverage | 3 | 0.7193 | 57 | 0 |
| test | 1 | fine_evidence_unit_fraction_coverage | 3 | 0.7368 | 57 | 0 |
| test | 1 | asset_hit | 5 | 1.0000 | 57 | 0 |
| test | 1 | asset_precision | 5 | 0.2070 | 57 | 0 |
| test | 1 | fine_evidence_hit | 5 | 0.7544 | 57 | 0 |
| test | 1 | fine_evidence_precision | 5 | 0.1789 | 57 | 0 |
| test | 1 | complete_evidence | 5 | 0.7368 | 57 | 0 |
| test | 1 | fine_evidence_coverage | 5 | 0.7456 | 57 | 0 |
| test | 1 | fine_evidence_unit_fraction_coverage | 5 | 0.7588 | 57 | 0 |
| test | 1 | asset_hit | 10 | 1.0000 | 57 | 0 |
| test | 1 | asset_precision | 10 | 0.1035 | 57 | 0 |
| test | 1 | fine_evidence_hit | 10 | 0.8070 | 57 | 0 |
| test | 1 | fine_evidence_precision | 10 | 0.1000 | 57 | 0 |
| test | 1 | complete_evidence | 10 | 0.7895 | 57 | 0 |
| test | 1 | fine_evidence_coverage | 10 | 0.7982 | 57 | 0 |
| test | 1 | fine_evidence_unit_fraction_coverage | 10 | 0.8041 | 57 | 0 |
| test | 1 | asset_mrr | 10 | 0.8550 | 57 | 0 |
| test | 1 | fine_evidence_mrr | 10 | 0.6898 | 57 | 0 |
| test | 2 | asset_hit | 1 | 0.7544 | 57 | 0 |
| test | 2 | asset_precision | 1 | 0.7544 | 57 | 0 |
| test | 2 | fine_evidence_hit | 1 | 0.6316 | 57 | 0 |
| test | 2 | fine_evidence_precision | 1 | 0.6316 | 57 | 0 |
| test | 2 | complete_evidence | 1 | 0.6140 | 57 | 0 |
| test | 2 | fine_evidence_coverage | 1 | 0.6228 | 57 | 0 |
| test | 2 | fine_evidence_unit_fraction_coverage | 1 | 0.6228 | 57 | 0 |
| test | 2 | asset_hit | 3 | 0.9298 | 57 | 0 |
| test | 2 | asset_precision | 3 | 0.3158 | 57 | 0 |
| test | 2 | fine_evidence_hit | 3 | 0.7193 | 57 | 0 |
| test | 2 | fine_evidence_precision | 3 | 0.2690 | 57 | 0 |
| test | 2 | complete_evidence | 3 | 0.7193 | 57 | 0 |
| test | 2 | fine_evidence_coverage | 3 | 0.7193 | 57 | 0 |
| test | 2 | fine_evidence_unit_fraction_coverage | 3 | 0.7368 | 57 | 0 |
| test | 2 | asset_hit | 5 | 1.0000 | 57 | 0 |
| test | 2 | asset_precision | 5 | 0.2070 | 57 | 0 |
| test | 2 | fine_evidence_hit | 5 | 0.7544 | 57 | 0 |
| test | 2 | fine_evidence_precision | 5 | 0.1789 | 57 | 0 |
| test | 2 | complete_evidence | 5 | 0.7368 | 57 | 0 |
| test | 2 | fine_evidence_coverage | 5 | 0.7456 | 57 | 0 |
| test | 2 | fine_evidence_unit_fraction_coverage | 5 | 0.7588 | 57 | 0 |
| test | 2 | asset_hit | 10 | 1.0000 | 57 | 0 |
| test | 2 | asset_precision | 10 | 0.1035 | 57 | 0 |
| test | 2 | fine_evidence_hit | 10 | 0.8070 | 57 | 0 |
| test | 2 | fine_evidence_precision | 10 | 0.1000 | 57 | 0 |
| test | 2 | complete_evidence | 10 | 0.7895 | 57 | 0 |
| test | 2 | fine_evidence_coverage | 10 | 0.7982 | 57 | 0 |
| test | 2 | fine_evidence_unit_fraction_coverage | 10 | 0.8041 | 57 | 0 |
| test | 2 | asset_mrr | 10 | 0.8550 | 57 | 0 |
| test | 2 | fine_evidence_mrr | 10 | 0.6898 | 57 | 0 |
| test | 3 | asset_hit | 1 | 0.7544 | 57 | 0 |
| test | 3 | asset_precision | 1 | 0.7544 | 57 | 0 |
| test | 3 | fine_evidence_hit | 1 | 0.6316 | 57 | 0 |
| test | 3 | fine_evidence_precision | 1 | 0.6316 | 57 | 0 |
| test | 3 | complete_evidence | 1 | 0.6140 | 57 | 0 |
| test | 3 | fine_evidence_coverage | 1 | 0.6228 | 57 | 0 |
| test | 3 | fine_evidence_unit_fraction_coverage | 1 | 0.6228 | 57 | 0 |
| test | 3 | asset_hit | 3 | 0.9298 | 57 | 0 |
| test | 3 | asset_precision | 3 | 0.3158 | 57 | 0 |
| test | 3 | fine_evidence_hit | 3 | 0.7193 | 57 | 0 |
| test | 3 | fine_evidence_precision | 3 | 0.2690 | 57 | 0 |
| test | 3 | complete_evidence | 3 | 0.7193 | 57 | 0 |
| test | 3 | fine_evidence_coverage | 3 | 0.7193 | 57 | 0 |
| test | 3 | fine_evidence_unit_fraction_coverage | 3 | 0.7368 | 57 | 0 |
| test | 3 | asset_hit | 5 | 1.0000 | 57 | 0 |
| test | 3 | asset_precision | 5 | 0.2070 | 57 | 0 |
| test | 3 | fine_evidence_hit | 5 | 0.7544 | 57 | 0 |
| test | 3 | fine_evidence_precision | 5 | 0.1789 | 57 | 0 |
| test | 3 | complete_evidence | 5 | 0.7368 | 57 | 0 |
| test | 3 | fine_evidence_coverage | 5 | 0.7456 | 57 | 0 |
| test | 3 | fine_evidence_unit_fraction_coverage | 5 | 0.7588 | 57 | 0 |
| test | 3 | asset_hit | 10 | 1.0000 | 57 | 0 |
| test | 3 | asset_precision | 10 | 0.1035 | 57 | 0 |
| test | 3 | fine_evidence_hit | 10 | 0.8070 | 57 | 0 |
| test | 3 | fine_evidence_precision | 10 | 0.1000 | 57 | 0 |
| test | 3 | complete_evidence | 10 | 0.7895 | 57 | 0 |
| test | 3 | fine_evidence_coverage | 10 | 0.7982 | 57 | 0 |
| test | 3 | fine_evidence_unit_fraction_coverage | 10 | 0.8041 | 57 | 0 |
| test | 3 | asset_mrr | 10 | 0.8550 | 57 | 0 |
| test | 3 | fine_evidence_mrr | 10 | 0.6898 | 57 | 0 |

### test modality別 Hit@1

| modality | answerable数 | asset Hit@1 | fine evidence Hit@1 | fine分母 |
|---|---:|---:|---:|---:|
| audio | 9 | 0.4444 | 0.0000 | 9 |
| document | 7 | 1.0000 | 0.8571 | 7 |
| mixed | 2 | 0.5000 | 0.5000 | 2 |
| pdf | 6 | 0.8333 | 0.8333 | 6 |
| presentation | 5 | 1.0000 | 0.8000 | 5 |
| spreadsheet | 8 | 0.2500 | 0.1250 | 8 |
| video | 20 | 0.9500 | 0.9500 | 20 |

Spreadsheet test asset Hit@1 は 2/8（25.0%）。これはgold指定Excelへのsource-retrieval比率であり、回答正答率・計算能力を表さない。独立検収ではHit@1 miss 6件中5件について、別資料にも同値または計算入力が見つかった（NKB-017/018/019/021/024）。ただし取得locator自体が答えを含む証拠とは限らず、NKB-024ではtop chunkが期限の行である。NKB-023（EXP102）の14,500取引行はD-HRに存在せず、確認されたrow-level source miss。goldで指定したExcelだけを数える指標は、別資料にある正当な代替根拠を網羅しない。個別の注記は `retrieval_failures.csv` に記録した。

## 音声・動画の区間粒度診断

audio_videoのfine coverageには、gold区間と重なり、かつcandidate区間の長さがgold区間以下（1e-6秒許容）のsegment-specific locatorだけを使った。長すぎる区間・ファイル全体のlocatorはfine unionから除外し、asset_hitは別のasset指標として保持する。この診断は区間locatorの検索粒度を示し、音声・映像内容の理解度ではない。
- asset hitはあるがfine entryが未完了の診断行: 112。長すぎて除外した重複区間を含む診断行: 87（全行は `fine_granularity_diagnostics.csv`）。

| split | rep | k | asset hitあり・fine未完了 | 長すぎるoverlap候補あり |
|---|---:|---:|---:|---:|
| test | 1 | 1 | 4 | 4 |
| test | 1 | 3 | 9 | 7 |
| test | 1 | 5 | 10 | 7 |
| test | 1 | 10 | 10 | 10 |
| dev | 1 | 1 | 6 | 0 |
| dev | 1 | 3 | 3 | 0 |
| dev | 1 | 5 | 2 | 1 |
| dev | 1 | 10 | 2 | 2 |

代表行（test/dev・rep1・k=5）:

| query | asset | gold区間 | fine coverage | 除外した候補 | 理由 |
|---|---|---|---:|---|---|
| NKB-035 | A-QA | 16.492-26.502s (segment 3) | 0.0000 | A-QA:0037|time:15.000-30.000s|15.000-30.000s | asset_hit_but_all_overlapping_source_intervals_exceed_gold_duration |
| NKB-040 | A-LOG | 21.835-29.336s (segment 3) | 0.0000 | なし | asset_hit_without_a_qualifying_segment_specific_interval |
| NKB-033 | A-QA | 9.155-16.092s (segment 2) | 0.0000 | A-QA:0036|time:0.000-15.000s|0.000-15.000s | asset_hit_but_all_overlapping_source_intervals_exceed_gold_duration |
| NKB-034 | A-QA | 16.492-26.502s (segment 3) | 0.0000 | なし | asset_hit_without_a_qualifying_segment_specific_interval |
| NKB-036 | A-QA | 38.337-48.458s (segment 5) | 0.0000 | A-QA:0038|time:30.000-45.000s|30.000-45.000s;A-QA:0039|time:45.000-60.973s|45.000-60.973s | asset_hit_but_all_overlapping_source_intervals_exceed_gold_duration |
| NKB-037 | A-QA | 48.858-60.973s (segment 6) | 0.0000 | A-QA:0039|time:45.000-60.973s|45.000-60.973s | asset_hit_but_all_overlapping_source_intervals_exceed_gold_duration |
| NKB-038 | A-LOG | 9.600-21.435s (segment 2) | 0.0000 | A-LOG:0040|time:0.000-15.000s|0.000-15.000s;A-LOG:0041|time:15.000-30.000s|15.000-30.000s | asset_hit_but_all_overlapping_source_intervals_exceed_gold_duration |
| NKB-039 | A-LOG | 9.600-21.435s (segment 2) | 0.0000 | A-LOG:0040|time:0.000-15.000s|0.000-15.000s | asset_hit_but_all_overlapping_source_intervals_exceed_gold_duration |
| NKB-041 | A-LOG | 41.251-48.952s (segment 5) | 0.0000 | なし | asset_hit_without_a_qualifying_segment_specific_interval |
| NKB-042 | A-LOG | 49.352-60.002s (segment 6) | 0.0000 | A-LOG:0043|time:45.000-60.002s|45.000-60.002s | asset_hit_but_all_overlapping_source_intervals_exceed_gold_duration |
| NKB-054 | A-LOG | 9.600-21.435s (segment 2) | 0.0000 | A-LOG:0040|time:0.000-15.000s|0.000-15.000s;A-LOG:0041|time:15.000-30.000s|15.000-30.000s | asset_hit_but_all_overlapping_source_intervals_exceed_gold_duration |
| NKB-056 | A-QA | 16.492-26.502s (segment 3) | 0.0000 | なし | asset_hit_without_a_qualifying_segment_specific_interval |

## 個別のretrieval failure

`retrieval_failures.csv` にanswerable queryのasset miss、fine evidence未到達、全根拠未完了、部分coverageをquery・repetition・cutoff別に保存した。全データのfailure行は 209 行。testの主成績（rep1, k=5）でのfailureは 15 行。

| query | modality/task | failure | gold asset | top asset | top locator |
|---|---|---|---|---|---|
| NKB-019 | spreadsheet/calculation | no_fully_covered_evidence_entry;not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | X-LOT | P-QA (0.7665), X-LOT (0.7471), V-F2 (0.7317) | P-QA|page:2 (0.7665); X-LOT|sheet:1:rows:6-6:cells:A6:G6 (0.7471); X-LOT|sheet:1:rows:7-7:cells:A7:G7 (0.7470) |
| NKB-021 | spreadsheet/calculation | no_fully_covered_evidence_entry;not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | X-LOT | A-QA (0.7263), P-QA (0.7106), A-LOG (0.6943) | A-QA|time:15.000-30.000s (0.7263); P-QA|page:2 (0.7106); A-QA|time:45.000-60.973s (0.6960) |
| NKB-023 | spreadsheet/calculation | no_fully_covered_evidence_entry;not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | X-EXP | D-HR (0.7020), P-QA (0.6583), A-LOG (0.6474) | D-HR|section:国内出張の交通費と宿泊費 (0.7020); P-QA|page:2 (0.6583); D-HR|section:経費精算の締切と紛失領収書 (0.6482) |
| NKB-024 | spreadsheet/calculation | no_fully_covered_evidence_entry;not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | X-EXP | D-HR (0.6997), A-QA (0.6913), S-PLAN (0.6879) | D-HR|section:経費精算の締切と紛失領収書 (0.6997); A-QA|time:15.000-30.000s (0.6913); S-PLAN|slide:6 (0.6879) |
| NKB-026 | spreadsheet/calculation | no_fully_covered_evidence_entry;not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | X-EXP | X-EXP (0.7538), D-HR (0.6978), A-LOG (0.6934) | X-EXP|sheet:1:rows:10-10:cells:A10:K10 (0.7538); X-EXP|sheet:1:rows:9-9:cells:A9:K9 (0.7112); D-HR|section:備品購入と稟議の承認区分 (0.6978) |
| NKB-033 | audio/lookup | no_fully_covered_evidence_entry;not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | A-QA | S-PLAN (0.7284), A-QA (0.7025), P-QA (0.6917) | S-PLAN|slide:3 (0.7284); A-QA|time:0.000-15.000s (0.7025); A-QA|time:45.000-60.973s (0.7009) |
| NKB-034 | audio/lookup | no_fully_covered_evidence_entry;not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | A-QA | P-QA (0.7235), A-QA (0.7204), S-PLAN (0.7133) | P-QA|page:2 (0.7235); A-QA|time:45.000-60.973s (0.7204); S-PLAN|slide:3 (0.7133) |
| NKB-036 | audio/causality | no_fully_covered_evidence_entry;not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | A-QA | A-QA (0.7473), S-PLAN (0.7244), P-QA (0.7206) | A-QA|time:30.000-45.000s (0.7473); A-QA|time:45.000-60.973s (0.7312); S-PLAN|slide:3 (0.7244) |
| NKB-037 | audio/lookup | no_fully_covered_evidence_entry;not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | A-QA | S-PLAN (0.7275), A-QA (0.7204), P-QA (0.6918) | S-PLAN|slide:3 (0.7275); A-QA|time:45.000-60.973s (0.7204); A-QA|time:0.000-15.000s (0.7160) |
| NKB-038 | audio/lookup | no_fully_covered_evidence_entry;not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | A-LOG | S-PLAN (0.7482), A-LOG (0.7362), A-QA (0.7102) | S-PLAN|slide:6 (0.7482); A-LOG|time:0.000-15.000s (0.7362); A-LOG|time:15.000-30.000s (0.7225) |
| NKB-039 | audio/lookup | no_fully_covered_evidence_entry;not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | A-LOG | A-LOG (0.7212), S-PLAN (0.6977), V-SAFE (0.6946) | A-LOG|time:0.000-15.000s (0.7212); S-PLAN|slide:6 (0.6977); V-SAFE|time:6.000-12.000s (0.6946) |
| NKB-041 | audio/lookup | no_fully_covered_evidence_entry;not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | A-LOG | V-SAFE (0.7258), S-PLAN (0.7137), A-QA (0.7084) | V-SAFE|time:12.000-18.000s (0.7258); V-SAFE|time:6.000-12.000s (0.7189); S-PLAN|slide:6 (0.7137) |
| NKB-042 | audio/lookup | no_fully_covered_evidence_entry;not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | A-LOG | A-LOG (0.7084), V-SAFE (0.6875), V-W3 (0.6815) | A-LOG|time:45.000-60.002s (0.7084); A-LOG|time:30.000-45.000s (0.6923); V-SAFE|time:18.000-24.000s (0.6875) |
| NKB-054 | audio/temporal_exception | no_fully_covered_evidence_entry;not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | A-LOG | A-LOG (0.7607), S-PLAN (0.7457), P-QA (0.6895) | A-LOG|time:0.000-15.000s (0.7607); S-PLAN|slide:6 (0.7457); A-LOG|time:15.000-30.000s (0.7065) |
| NKB-056 | mixed/cross_asset | not_all_evidence_entries_fully_covered;partial_interval_or_cell_coverage | A-QA;X-LOT | P-QA (0.7207), S-PLAN (0.7154), A-QA (0.7135) | P-QA|page:2 (0.7207); S-PLAN|slide:3 (0.7154); A-QA|time:45.000-60.973s (0.7135) |

## test検索時間

p95 は nearest-rank `ceil(0.95*n)`。初回は最初の test query call として扱い、warmed-only はその1回を除外する。

| 集計範囲 | 期待calls | 記録calls | 計測数 | 失敗数 | median ms | mean ms | p95 ms | max ms | 初回 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| test_all_calls | 180 | 180 | 180 | 0 | 122.20 | 130.48 | 201.88 | 277.53 | 136.22 |
| test_warmed_only | 179 | 179 | 179 | 0 | 121.90 | 130.45 | 213.57 | 277.53 | 未計測 |

## CPU実行・index作成・query段階

- 正式query run: attempt-05-query-threads4、status=complete、model revision `914f7f89142e33e77833254d9c9b90c3cef7303b`、device=cpu、dtype=torch.float32。query processのtorch threads=4、CPU limit=4 cores、memory limit=8589934592 bytes。
- query processのmodel load=8.854秒。query実行wall=33.548秒、query container wall=42.642秒。modelはquery call前にロード済み（first test call cold=False）で、上の1回あたりlatencyはこのmodel load時間を含まない。
- index作成は `attempt-01` の別記録を参照（正式query runでは同じindex/vectorを再利用）。63 chunks成功、errors=0、index SHA `2675ef297502febc2aaeed260d4f8aa4621d37afcc6e10445aabdbff24c6adda`。input extraction=20.084秒、document-process model load=10.478秒、document embedding wall=566.804秒、vector index write=0.055秒。
- index process thread setting: torch.set_num_threads(TORCH_THREADS) before model load; TORCH_THREADS=4 in compose environment。per-process thread readbackはmanifestに保存されていない（`index_process_thread_readback_serialized=False`）ため、index build中の実torch thread数は未確認。query processの4-thread readbackをindex処理へ流用していない。


## Unanswerable 問題

実際の未回答ケース一覧は `unanswerable.csv` に保存した（記録 10 行）。検索ヒットは回答可能性や正しい棄却の証明として扱わない。

## 制約と出力

全文字列によるrequired fact診断は `fact_support_diagnostics.csv` に分離した保守的な診断であり、ネイティブ音声・動画の内容理解や生成回答の正解率ではない。時間区間は全幅を連続して覆い、表計算の範囲は全セルが取得された場合にevidence entryをcoverage済みとする。部分時間/セルcoverage率は `fine_evidence_unit_fraction_coverage` に別記する。

出力: `metrics.json`, `quality_metrics.csv`, `modality_metrics.csv`, `retrieval_failures.csv`, `latency_summary.csv`, `unknown_scores.csv`, `unanswerable.csv`, `fact_support_diagnostics.csv`, `fine_granularity_diagnostics.csv`, `unresolved_gold_locators.csv`, `unresolved_candidates.csv`, `asset_ranking_consistency.csv`。
