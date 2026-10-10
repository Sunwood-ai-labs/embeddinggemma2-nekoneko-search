# EmbeddingGemma 2 は、Word・Excel・音声・動画をまとめて検索できるのか。架空企業の社内資料14点と75問で測った

Googleが2026年10月6日に公開した埋め込みモデル EmbeddingGemma 2 を、Podman Compose上のCPUだけで動かしました。架空企業「ネコネコインダストリー」のWord・PDF・Excel・PowerPoint・音声・動画あわせて14資料を1つの索引に入れ、日本語の質問で探した結果、答えの載った資料が1位に出たのは57問中43問（75.4%）、上位5件まで見れば57問すべてでした。検索1回の時間は中央値122ミリ秒です。

![正解資料が何位までに入るか](https://raw.githubusercontent.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search/main/assets/chart-hit.png)

## わかったこと

1. **上位5件を見せる検索なら取りこぼしがなかった。** 1位だけを見ると57問中43問、上位3件で53問、上位5件で57問です。3回くり返しても1位の資料は毎回同じでした。
2. **動画は強く、Excelと音声は1位を逃しやすかった。** 動画を答えとする質問は20問中19問で1位。Excelは8問中2問、音声は9問中4問でした。外した質問では、同じ話題を文章で書いたPDFやスライドが上に来ています。
3. **検索は速く、動画の登録は遅い。** 質問1件は中央値122ミリ秒で返ります。一方、6秒の動画1区間をベクトルにするのにCPUで約25秒かかり、資料の登録時間の90%を動画が占めました。

この結果は、文字の多い訓練用アニメーション5本と合成音声2本を含む、手作りの小さな資料セットでのものです。実写の動画、実際の会議録音、数千件の文書にそのまま当てはまる数字ではありません。また、測ったのは「資料を探し当てる力」で、質問に文章で答える力は測っていません。

## EmbeddingGemma 2 とは

埋め込みモデルは、文章や画像を「意味の近さを比べられる数字の列」（ベクトル）に変えるモデルです。質問と資料をどちらもベクトルにしておけば、言い回しが違っても意味の近い資料を探せます。答えの文章は作りません。返すのは「どの資料が近いか」の順位です。

EmbeddingGemma 2 の特徴は、文章だけでなく画像・音声・動画も同じ種類のベクトルに変えられることです。音声を文字に起こしたり、動画に説明文を付けたりしなくても、日本語の質問から音声や動画の区間を直接探せます。

| 項目 | 公式の記載 |
| --- | --- |
| 公開日 | 2026年10月6日 |
| 開発元 | Google |
| 入力 | 文章（コードを含む）、画像、音声、動画 |
| 出力 | 768次元のベクトル。512・256・128次元に切り詰め可能 |
| 大きさ | 約7.4億パラメータ。文章だけなら約2.7億 |
| 入力の上限 | 8,192トークン。音声はモノラル16kHz、動画は既定で毎秒1フレーム |
| 対応言語 | 100以上 |
| ライセンス | Apache 2.0 |

出典は次の3つです（2026年10月10日に確認）。

- [Googleの発表記事](https://blog.google/innovation-and-ai/technology/developers-tools/embeddinggemma-2/)
- [EmbeddingGemma 2 モデルカード](https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2)
- [Hugging Faceのモデルページ](https://huggingface.co/google/embeddinggemma-2)

## 何を試したのか

登場するものは3つです。

| 登場するもの | 役割 | たとえると |
| --- | --- | --- |
| EmbeddingGemma 2 | 資料と質問をベクトルに変える | 資料の中身を覚えて、棚の場所を決める司書 |
| Sentence Transformers 6.1.0 | モデルを呼び出すライブラリ | 司書に依頼を伝える受付 |
| Podman Compose | モデルを動かす箱（コンテナ）を用意する | 司書が働く部屋 |

実験は2段階で行いました。

1. **文章だけの予備実験。** 架空の社内規程24文書に、言い換えた質問24問を投げる。
2. **資料の形式を混ぜた本測定。** Word・PDF・Excel・PowerPoint・音声・動画の14資料に、75問を投げる。この記事の主な数字はこちらです。

資料はすべて、この実験のために作った架空の内容です。ペット用品メーカーという設定で、在宅勤務規程、出張費、製品の異音調査、製造実績、倉庫の放送、検査や梱包の訓練動画などを用意しました。動画は実写ではなく、日本語の文字と色が切り替わる24秒の無音アニメーションです。

![5本の動画の各工程](https://raw.githubusercontent.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search/main/assets/video-contact-sheet.png)

## 実験のやり方

### 資料を検索単位に分ける

14資料を、次の決まりで63個の検索単位に分けました。区切り方は質問を見る前に決め、結果を見て変えていません。

| 形式 | 区切り方 | モデルへの渡し方 |
| --- | --- | --- |
| Word・PDF・PowerPoint | 見出し、ページ、スライドごと | 抜き出した文章 |
| Excel | データ1行ごと。列見出しとセル番地つき | 抜き出した文章 |
| 音声（約60秒が2本） | 15秒ごと | 音声ファイルそのまま |
| 動画（24秒が5本） | 6秒ごと | 動画ファイルそのまま |

Office文書とPDFは、モデルが直接読める形式ではないので文章を抜き出しています。音声と動画は文字起こしをせず、区間のファイルをそのままモデルに渡しました。台本、正解、質問リストは索引に入れていません。

### 質問と採点

75問のうち、15問を調整用、60問を本番用に分けました。本番用60問の内訳は、資料に答えがある57問と、資料に答えがない3問です。精度は57問で数えます。

質問には、たとえば次のようなものがあります。

- 「在宅勤務はいつまでにどのシステムで申請する？」（Word）
- 「9月のF2の3ロットの生産台数の合計は？」（Excel）
- 「倉庫放送で案内した10月16日の出荷締切時刻は？」（音声）
- 「W3梱包動画の正規箱のラベルは何色？」（動画）

採点は2段階です。

- **資料が当たったか。** 答えの載った資料が、検索結果の何位に出たか。
- **箇所まで当たったか。** 答えの載ったページ、行、時間の区間まで、上位5つの検索単位に入ったか。

速度は、本番用60問を3回くり返した180回で測りました。モデルを読み込んだ後、質問をベクトルにして63単位と照合し終えるまでの時間です。

## 結果

### 資料の形式ごとの差

![資料の形式ごとの1位正解数](https://raw.githubusercontent.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search/main/assets/chart-modality.png)

| 資料の形式 | 1位が正解 | 上位3件 | 上位5件 |
| --- | ---: | ---: | ---: |
| Word | 7 / 7 | 7 / 7 | 7 / 7 |
| PowerPoint | 5 / 5 | 5 / 5 | 5 / 5 |
| 動画 | 19 / 20 | 20 / 20 | 20 / 20 |
| PDF | 5 / 6 | 6 / 6 | 6 / 6 |
| 複数資料の照合 | 1 / 2 | 2 / 2 | 2 / 2 |
| 音声 | 4 / 9 | 8 / 9 | 9 / 9 |
| Excel | 2 / 8 | 5 / 8 | 8 / 8 |
| 合計 | 43 / 57 | 53 / 57 | 57 / 57 |

良かった点は3つあります。

- 文字起こしをしていない動画が、20問中19問で1位に出ました。「正規箱のラベルは何色？」のように、画面の色を問う質問でも正しい動画の正しい6秒区間が1位でした。
- WordとPowerPointは全問で1位でした。
- 上位5件に広げると、どの形式も取りこぼしがありません。

一方、Excelは8問中2問、音声は9問中4問にとどまりました。この2つの数字の読み方は、次の「原因の切り分け」で説明します。

答えの箇所まで含めた採点では、必要な箇所がすべて上位5つの検索単位にそろったのは57問中42問（73.7%）でした。

### 検索の速さ

![検索1回の時間の分布](https://raw.githubusercontent.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search/main/assets/chart-latency.png)

| 指標 | 値 |
| --- | ---: |
| 中央値 | 122ミリ秒 |
| 95%点 | 202ミリ秒 |
| 最大 | 278ミリ秒 |
| モデルの読み込み | 8.9秒 |

時間のほとんどは質問をベクトルに変える処理で、63単位との照合は1ミリ秒未満でした。通信の時間は含みません。モデルの読み込みは起動時に1回だけかかります。

### 資料の登録にかかる時間

![形式ごとの登録時間](https://raw.githubusercontent.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search/main/assets/chart-indexing.png)

| 入力 | 単位数 | 合計 | 1単位の中央値 |
| --- | ---: | ---: | ---: |
| 動画（6秒の区間） | 20 | 505秒 | 24.6秒 |
| 音声（15秒の区間） | 8 | 39秒 | 4.9秒 |
| 文章 | 35 | 17秒 | 0.4秒 |

63単位の登録は、全体で9分27秒かかりました。その大半は動画です。24秒の動画1本を登録するのに、CPUでは約1分40秒かかる計算になります。登録は資料を追加したときに1回だけ行う処理で、検索のたびにはかかりません。メモリは、コンテナ全体で最大約4.3GBでした。

### 文章だけの予備実験

最初に行った文章だけの実験では、24文書に対する24問すべてで、期待した文書が1位でした。「家で仕事したい。週に何日までで、いつ申請すればいい？」のように、文書と違う言い回しの質問でも在宅勤務規程が先頭に出ています。検索時間の中央値は130ミリ秒でした。

![在宅勤務の質問に対する検索画面](https://raw.githubusercontent.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search/main/assets/search-ui.jpg)

この予備実験では、画像と音声の部品を読み込まない設定を使っています。読み込んだパラメータは約2.7億で、本測定の約7.4億とは別の構成です。

## 原因の切り分け

Excelと音声の数字が低い理由を、手元の結果から確かめました。

| 疑った要因 | 確かめ方 | 結果 | 判定 |
| --- | --- | --- | --- |
| Excelと同じ数値が別の資料にもある | 外した6問の1位の資料を読む | 5問は、1位のPDFやWordにも同じ数値か計算の材料があった | 6問中5問はこれで説明できる |
| Excelの行を本当に取りこぼした | 同上 | 1問は、経費の取引行がExcelにしかなく、1位は一般的な出張規程だった | 1問は実際の取りこぼし |
| 音声より、同じ話題の文章が上に来る | 音声で外した5問の1位を見る | 4問はスライドかPDF、1問は動画が1位。正解の音声は4問で2位、1問で4位 | 傾向は確認。理由は未特定 |
| 音声の区切りが粗い | 区間と正解の時間を比べる | 15秒の区間は、正解の区間（7〜12秒）より毎回長い | 箇所の採点が0問になる原因 |
| 実行のたびに結果が揺れる | 同じ60問を3回実行 | 1位の資料は3回とも同じ | 揺れは原因ではない |
| 音声を文字に起こせば改善する | 文字起こしした文章を索引に入れて比べる | 未実施 | 不明 |

Excelの「8問中2問」は、質問が指定したExcelファイルが1位になった数です。たとえば「9月20日のF2ロットの工程内不良率は？」という質問では、同じ数値が載った品質通知のPDFが1位、Excelが2位でした。利用者から見れば1位の資料でも答えは見つかります。この数字は、Excelの中身を理解できなかった割合ではありません。

音声の「箇所まで当たった数」は9問中0問ですが、これは区切り方の影響です。今回の採点は、正解の区間より長い検索単位を「箇所が当たった」と数えない決まりにしていました。15秒の区間は正解の区間より必ず長いので、音声を聞き取れたかどうかに関係なく0問になります。

### 資料にない質問にも候補は出る

資料に答えがない3問でも、検索結果は返りました。

| 質問 | 1位の資料 | 類似度 |
| --- | --- | ---: |
| 社長の自宅住所と個人携帯の番号は？ | 品質会議の音声 | 0.700 |
| 2027年度の売上予測と営業利益率は？ | 品質会議の音声 | 0.678 |
| ロンドンの海外出張の宿泊費上限はいくら？ | 勤務ガイド（国内出張の節） | 0.769 |

答えがある57問の1位の類似度は0.684〜0.827で、中央値は0.763です。3問目の0.769はこの中央値より高く、類似度の大小だけでは「資料に答えがない」と見分けられませんでした。検索結果をそのまま答えとして扱う使い方には、別の仕組みが要ります。

## 舞台裏

環境づくりと測定の途中で起きたことを、時刻順にまとめます（2026年10月10日、日本時間）。

| 時刻 | 起きたこと | 対応 |
| --- | --- | --- |
| 10:21 | 新しいPodmanマシンで、一般ユーザー用の接続口がエラーになった | 同じマシンの管理者用の接続口を使ってComposeを実行 |
| 10:30 | 文章だけの設定でも、モデルの読み込みがTorchVision不足で止まった | CPU版TorchVisionを追加して再構築 |
| 10:33 | 自作の版確認が、ライブラリから版番号を取れずに止まった | 固定した版をローカルに取得し、そのフォルダから読み込む方式に変更 |
| 12:36 | 音声と動画を読むためのライブラリが不足していた | ffmpeg、PyAV、librosa、torchcodecを追加 |
| 13:05 | 63単位の登録後、質問ファイルの置き場所の指定違いで検索が始まらなかった | 保存済みのベクトルを使い、検索だけを再開 |
| 13:10 | 検索が予定の4スレッドではなく1スレッドで動いていた | その結果は採用せず、4スレッドで測り直し |
| 13:46 | 別担当の再集計で、補助指標12行に数え方の差が見つかった | 事前に決めた定義に合わせて集計を修正。主な数字は変わらず |

採用した測定は5回目の実行です。それ以前の4回は、条件違いや記録処理の失敗のため正式な結果から外し、記録だけを残しました。集計は、実行担当とは別の担当が生の検索結果から計算し直し、精度120行、形式別560行、速度2行、質問別180行がすべて一致することを確かめています。

## 評価と次に試すこと

| 観点 | 良い点 | 課題 |
| --- | --- | --- |
| 精度 | 上位5件なら57問すべてで正解資料が入る | 1位だけでは4問に1問を外す |
| 資料の形式 | 動画を文字起こしなしで探せる | 音声は同じ話題の文章に負けやすい |
| 速度 | CPUだけで検索1回が約0.1秒 | 動画の登録は実時間の約4倍かかる |
| 運用 | Apache 2.0で、手元のPCだけで動く | 資料にない質問を類似度では見分けられない |

この実験からは言えないことがあります。

- 実写の動画や、複数人が話す実際の録音での精度。今回の動画は画面に日本語の文字が多く、質問文にも動画の名前が入っています。
- 数百件、数千件の資料での精度と速度。今回は14資料・63単位です。
- 質問に文章で答えたときの正解率。検索した資料を言語モデルに渡して答えさせる部分は作っていません。
- GPUでの速度、ほかの埋め込みモデルとの比較。

次に試す価値があるものを挙げます。

- [ ] 音声を文字に起こした文章も索引に入れ、音声そのままの場合と比べる
- [ ] 音声の区切りを15秒より短くして、箇所の当たり方を見る
- [ ] 画面に文字のない実写の動画で、同じ形式の質問を試す
- [ ] 上位5件を言語モデルに渡し、答えの正解率と「資料にない」の判定を測る
- [ ] GPUで動画の登録時間を測る

## 動かし方

同じ仕組みを、自分の資料で試せます。コードは [embeddinggemma2-nekoneko-search](https://github.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search) にあります。

### 用意するもの

| 必要なもの | 目安 |
| --- | --- |
| PodmanまたはDocker（Composeつき） | Windows、macOS、Linux |
| メモリ | コンテナに8GB |
| ディスク | モデルの重みに約3GB、イメージに数GB |
| 資料 | docx、pdf、xlsx、pptx、txt、md、wav、mp3、mp4 など |

GPUは不要です。モデルのダウンロードに、Hugging Faceのログインは要りません。

### 1. モデルを取得する

```bash
git clone https://github.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search.git
cd embeddinggemma2-nekoneko-search/quickstart
podman compose build
podman compose run --rm bench python fetch_model.py
```

Dockerの場合は `podman` を `docker` に読み替えます。モデルは実験と同じ版に固定してあります。

```python
MODEL_REVISION = os.environ.get("MODEL_REVISION", "914f7f89142e33e77833254d9c9b90c3cef7303b")

def load_model() -> SentenceTransformer:
    torch.set_num_threads(TORCH_THREADS)
    # CPUではfloat32を使う。モデルカードはfloat16を使わないよう明記している。
    model = SentenceTransformer(str(snapshot()), device="cpu", model_kwargs={"dtype": torch.float32})
```

全文は [quickstart/common.py](https://github.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search/blob/main/quickstart/common.py) です。

### 2. 資料を登録する

`quickstart/inputs/` に資料を置いて、索引を作ります。手元に資料がなければ、リポジトリの `benchmark/inputs/` にある架空のWord・PDF・Excel・PowerPointをコピーして試せます。

```bash
cp -r ../benchmark/inputs/* inputs/
podman compose run --rm bench python build_index.py
```

文章と、音声・動画とで、モデルへの渡し方が違います。

```python
if chunk["text"]:
    # 文章は「title: <題名> | text: 」を先頭に付けて埋め込む
    vec = model.encode_document([chunk["text"]], prompt=f"title: {chunk['title']} | text: ", **common)[0]
else:
    # 音声・動画はファイルをそのまま渡す。文章用の接頭辞は付けない（prompt=""）
    kwargs = dict(common, prompt="")
    if chunk["modality"] == "video":
        kwargs["processing_kwargs"] = {"video": VIDEO_PROCESSING}
    vec = model.encode_document([{chunk["modality"]: chunk["media_path"]}], **kwargs)[0]
```

全文は [quickstart/build_index.py](https://github.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search/blob/main/quickstart/build_index.py)、資料の区切り方は [quickstart/chunking.py](https://github.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search/blob/main/quickstart/chunking.py) です。動画は6秒につき約25秒かかるので、最初は短いもので試してください。

### 3. 検索する

```bash
podman compose run --rm bench python search.py "在宅勤務は週に何日まで？"
```

質問は「質問応答」用の接頭辞を付けてベクトルにし、登録済みのベクトルとの内積で順位を付けます。

```python
query = model.encode_query([question], prompt_name=QUERY_PROMPT_NAME, normalize_embeddings=True,
                           convert_to_numpy=True, batch_size=1, show_progress_bar=False)[0]
scores = vectors @ query  # 正規化済みベクトルの内積 = cosine類似度
order = np.argsort(-scores, kind="stable")
```

全文は [quickstart/search.py](https://github.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search/blob/main/quickstart/search.py) です。出力は次の形で、左から順位、類似度、資料名、形式、箇所です。

```text
1. 0.808  hr_policy  [document] section:在宅勤務規程 2026年10月改定
2. 0.772  hr_policy  [document] section:経費精算の締切と紛失領収書
3. 0.755  hr_policy  [document] section:年次有給休暇と半日休暇
4. 0.739  archived_remote_2025  [pdf] page:1
5. 0.737  hr_policy  [document] section:育児短時間勤務制度
```

4位には、廃止済みの旧規程（PDF）も出ています。新旧の区別は検索だけでは付かないので、古い資料は索引に入れないか、結果の表示で分けます。類似度は0.7〜0.8に集まります。数字の大きさは「正しさの確率」ではなく、順位を決めるための値として読んでください。

### 4. 採点する

質問と正解のリストがあれば、資料単位の正解数を出せます。リポジトリに入っている実験の生の検索結果で試すと、この記事と同じ数字になります。

```bash
python quickstart/score.py results/multimodal/raw/test-query-results.jsonl benchmark/gold.jsonl
```

```text
modality         n   Hit@1   Hit@3   Hit@5   MRR@10
all             57   43/57   53/57   57/57    0.855
audio            9    4/9     8/9     9/9     0.694
spreadsheet      8    2/8     5/8     8/8     0.519
video           20   19/20   20/20   20/20    0.975
```

全文は [quickstart/score.py](https://github.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search/blob/main/quickstart/score.py) です。自分の資料で採点するときは、`search.py --queries` で検索結果をまとめて出力し、`benchmark/gold.jsonl` と同じ形の正解ファイルを用意します。

### リポジトリの中身

| フォルダ | 内容 |
| --- | --- |
| quickstart | 自分の資料で試すための一式 |
| experiment | 実験で実際に動かしたスクリプトと設定 |
| benchmark | 架空の社内資料（文書のみ）、質問75問、正解 |
| results | 実測結果。生の検索結果、集計CSV、実行環境の記録 |
| docs | 実測レポート、独立再集計、事前調査メモ |
| assets | グラフと生成スクリプト |

`experiment/` のスクリプトは、実験時のフォルダ構成と音声・動画の素材を前提にしています。音声2本と動画5本はリポジトリに含めていないため、そのままでは本測定を再現できません。処理内容の参照用です。`quickstart/` の確認状況は、リポジトリのREADMEに書いています。

## 実行条件と指標の定義

### 実行条件

| 項目 | 値 |
| --- | --- |
| モデル | google/embeddinggemma-2、revision 914f7f89 |
| 精度・次元 | float32、768次元、全744,371,488パラメータ |
| ライブラリ | Sentence Transformers 6.1.0、Transformers 5.19.0、PyTorch 2.14.1（CPU） |
| 実行基盤 | Podman Compose、WSL2、Python 3.12 |
| CPU・メモリ | Core i7-13620H、コンテナに4コア・8GB |
| 質問の接頭辞 | task: question answering \| query: |
| 文章の接頭辞 | title: 題名 \| text: |
| 音声・動画 | 接頭辞なし。動画は毎秒1フレーム、最大32フレーム |
| 実行方法 | 1件ずつ直列。ネットワークは切断 |

### 指標の定義

| 指標 | 定義 |
| --- | --- |
| 1位が正解（Hit@1） | 資料ごとの順位で、正解の資料が1位。資料の点は、その資料で最も高い検索単位の点 |
| 上位k件（Hit@k） | 正解の資料がk位以内。正解が複数ある質問は、最も上位の1つで判定 |
| MRR@10 | 正解が1位なら1、2位なら0.5、3位なら0.33として平均した値。今回は0.855 |
| 箇所まで全部そろう | 必要なページ・行・時間の区間が、上位5つの検索単位にすべて入る |
| 検索時間 | 質問の文字列を受け取ってから、順位を作り終えるまで。通信と記録の書き込みは含まない |
| 95%点 | 180回を小さい順に並べた171番目の値 |

指標の限界も書いておきます。

- 分母が小さい形式があります。PowerPointは5問、複数資料の照合は2問です。1問の当たり外れで割合が大きく動きます。
- 正解の資料は質問ごとに1つ（照合の質問は2つ）に決めてあります。別の資料に同じ答えがあっても、外れとして数えます。
- 調整用15問と本番用60問は、同じ資料から作っています。未知の業務への強さを保証する分け方ではありません。
- 資料の登録時間は、4スレッドの設定で実行しましたが、実際に使われたスレッド数の記録が残っていません。検索時間は4スレッドで動いたことを記録で確認しています。

## 参考リンク

- [Google: EmbeddingGemma 2 の発表記事](https://blog.google/innovation-and-ai/technology/developers-tools/embeddinggemma-2/)
- [EmbeddingGemma 2 モデルカード](https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2)
- [Hugging Face: google/embeddinggemma-2](https://huggingface.co/google/embeddinggemma-2)
- [TransformersのEmbeddingGemma 2ドキュメント](https://huggingface.co/docs/transformers/model_doc/embedding_gemma2)
- [Sentence Transformers](https://sbert.net/)
- [この実験のリポジトリ](https://github.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search)
- [実測レポート（全指標）](https://github.com/Sunwood-ai-labs/embeddinggemma2-nekoneko-search/blob/main/docs/REPORT.md)

#EmbeddingGemma2 #Google #埋め込みモデル #マルチモーダル検索 #RAG #Podman #生成AI
