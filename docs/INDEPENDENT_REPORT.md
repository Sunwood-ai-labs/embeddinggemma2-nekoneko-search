# EmbeddingGemma 2 独立再集計

以下の表は固定契約、attempt-05の正式raw、gold/locator対応表から独立に計算した。analysis担当がsecondary precisionの関連chunk判定を修正し、再集計後の正式表との全行照合が完了した。旧12行の差分と修正履歴は`fine-evidence-precision-discrepancy.json`を参照。

## 正式集計との独立照合

| 表 | 照合結果 |
|---|---|
| `quality_metrics.csv` | 120/120行の値・分母・特記対象数が独立再集計と一致。先行照合で不一致だった`fine_evidence_precision`の12行も修正後に一致。 |
| `modality_metrics.csv` | 560/560行の値・分母・除外数が一致。 |
| `latency_summary.csv` | 2/2行一致（全180 call、初回後179 call）。 |
| `attempt-05-test-query-outcomes-latency.csv` | 180 raw call行。rep1の全体・7形式についてasset Hit、fine Hit、complete evidence、unit fraction coverageの128集約照合が一致。 |

先行照合では`fine_evidence_precision`のk=3/5/10で12行に差が出た（例: test rep1 k=3で正式0.245614、独立0.269006）。契約は、有効なgranularityのsource locatorがgold注釈に一部でも重なればchunk relevantとするため、analysis担当がprecisionの関連判定のみ修正し再集計した。修正後は12行を含むquality全120行が一致し、ランキング・gold・主Hit/coverageは変更されていない。初回差分と契約/helperの行番号は`fine-evidence-precision-discrepancy.json`に記録した。

## 固定条件と数値

- 正式候補: `attempt-05-query-threads4`、`google/embeddinggemma-2` revision `914f7f89142e33e77833254d9c9b90c3cef7303b`。dev 15件、test 180件（60問×3反復）、エラー0。query実行時PyTorch thread数4で、raw validation/run resultはpass。
- test rep1の回答可能57問: asset Hit@1 **43/57 (75.4%)**、Hit@3 **53/57 (93.0%)**、Hit@5 **57/57 (100.0%)**。Fine evidence Hit@1 **36/57 (63.2%)**、完全根拠@5 **42/57**。
- test全180回のelapsed中央値 **122.198 ms**、nearest-rank p95 **201.878 ms**、最初のquery **136.215 ms**。query stageのモデルロードは8.854秒。モデルは最初のquery前にロード済みで、63件の既存文書vectorを再利用したため、冷間起動と全資料の抽出・再埋め込みを含むend-to-end時間ではない。

## 読み方とケース確認

- Excel Hit@1 **2/8=25%**はgold指定Excel assetへの検索比率で、回答正答率・計算能力ではない。6 miss中5件（NKB-017/018/019/021/024）は、非gold資料に同値または計算入力が確認されている。NKB-023はD-HRの一般上限だけでは14,500円の実取引行を得られず、gold Excelのsource miss。NKB-024はtop asset D-HRがHitだが、top chunkは期限節で日当記載chunkを取得したとは判定しない。
- 音声goldは8 interval entries、mapped chunk参照は12件。各参照は固定15秒区間を基準にした切り出し（末尾の結合を含む）で、全12件が対応するgold区間より長い。契約に従いfine interval coverageへ寄与せず、audio asset hitとは分けている。これは区間粒度の制約であり音声内容理解率ではない。
- 代表的なH@1 source miss: NKB-023は取引行X-EXPがrank 5、topは汎用出張規程D-HR。NKB-038は10/16の出荷締切13:00を問うが、topは10/21計画S-PLAN、gold音声A-LOGはrank 2。NKB-051は保留品棚/タグを問うがtopはA-LOG、gold動画V-W3はrank 2。既存`qa/V-W3-15s.png`で棚C-03/赤タグを確認した。
- 未回答3問もrank結果があり、top asset/scoreは NKB-057 A-QA (0.7004),NKB-058 A-QA (0.6783),NKB-059 D-HR (0.7686)。閾値付き棄却や未回答精度は評価していない。旧方針P-OLDは明示的な旧規程問NKB-014/016でtop1、現行P-QA gold testのtop5には確認されなかった。
- 測定対象は検索ランキングとlocator coverage。生成回答の正解率、ASR、新規の大規模Visual QAは評価していない。

## CSV

- `independent-test-primary-metrics.csv`: test rep1全体、cutoff別の独立指標。
- `independent-test-modality-metrics.csv`: test rep1のmodality別指標。
- `independent-test-latency.csv`: 180 call全体、最初のquery後179件、初回callの遅延。
- `attempt-05-test-query-outcomes-latency.csv`: attempt-05 rawから作成した180行。query、gold asset、top1、asset/fine/complete hit、coverage、各call遅延を収録。unanswerableのhit指標欄は空欄。
- `fine-evidence-precision-discrepancy.json`: 正式secondary precisionとの不一致12行、契約とhelperの根拠。

raw test SHA256 `390fba17dcd82f76d0199d6323ce326baf4a80e999abca79a0ae291fd7495f56`; attempt manifest SHA256 `663cf6dc7003a03447808555b68523d02d496eb9d33a1f930fa343d59a9c39af`; independent receipt SHA256 `5b22284e16d4dba08977095a159a86ae1d259405fc9325b03fca598988382830`.
