# kynacio/mercapi PoC

商品検索、商品詳細、Seller Profile、Seller商品一覧を一つのWrapperで扱えるかを、
[`../common/conditions.json`](../common/conditions.json) の共通条件で検証します。

## 結果

[検証結果](result.md) の判定は **条件付き** です。基本データ、詳細、画像、Seller Profile・
商品一覧の取得は安定して成功しました。一方、`created_time ASC`は古い順になりません。

Seller商品一覧の追加検証では、Mercari Webが`max_pager_id`と`meta.has_next`を使って30件単位で
ページングすることを確認しました。販売中・売却済みも状態別に各2ページ、60ユニーク件を取得できました。
30件上限はMercari API自体の終端ではなく、固定版`mercapi`の公開メソッドと応答モデルの実装不足です。
ただし、現状の公開APIのままでは利用できないため、Wrapper拡張またはAdapter側の補完が必要です。

通常出品とAuctionの判定、価格の意味、終了予定時刻、Seller一覧への影響は既存PoCの対象外だったため、
[Auction情報の追加検証](../../docs/phase-0/phase-0-f-auction-validation.md)を別途実施した。
判定は **合格** で、詳細は[Auction検証結果](auction-result.md)に記録している。

- 販売形式の判定は商品ページを正として20 / 20一致した
- Auctionの価格は`highest_bid`（取得時点の現在価格）で、商品ページと10 / 10一致した
- Seller商品一覧は`with_auction=true`を送らないとAuction情報を返さない
- 検索・商品詳細・Seller商品一覧でAuction Fieldの形が3種類異なる

## セットアップ

リポジトリルートで実行します。`mercapi`は検証したGitコミットに固定しています。追加検証では
Playwright本体と、端末にインストール済みのGoogle Chromeを使用します。

```bash
python3 -m venv poc/mercapi/.venv
poc/mercapi/.venv/bin/python -m pip install -r poc/mercapi/requirements.txt
```

System Pythonが3.11未満の場合は、同じ固定commitを`uv`で構築できます。

```bash
uv venv --python 3.11 poc/mercapi/.venv
uv pip install --python poc/mercapi/.venv/bin/python -r poc/mercapi/requirements.txt
```

## 検証を実行する

```bash
poc/mercapi/.venv/bin/python poc/mercapi/run.py
```

実行中は同時実行数1、外部リクエスト開始間隔2秒以上を維持します。5回の検索試行はそれぞれ
新しいPythonプロセスで実行し、自動再試行はしません。401 / 403 / 429 / Challengeが3回連続した
場合は、回避を試みず残りのアクセスを停止します。

機械可読な測定結果は`artifacts/summary.json`へ出力します。`artifacts/`はSeller情報を含む可能性が
あるためGit管理外です。画像Bodyも保存しません。

## Seller商品一覧のページング追加検証

最初に通常PoCの`artifacts/summary.json`が必要です。実ブラウザでSellerページの「もっと見る」を操作し、
商品一覧APIのRequest / Responseを観測します。Seller IDや商品IDを含む詳細ArtifactはGit管理外です。

```bash
poc/mercapi/.venv/bin/python poc/mercapi/seller_paging_probe.py
```

観測した`max_pager_id`を使い、固定版`mercapi`のDPoP署名機構で販売中・売却済みを各2ページ取得します。
公開`Mercapi.items()`は使用せず、Wrapperへ同等の拡張が可能かを確かめる補足試験です。

```bash
poc/mercapi/.venv/bin/python poc/mercapi/seller_status_paging_probe.py
```

## Auction情報の追加検証

検索・商品詳細・Seller商品一覧・Seller Profileを1回の実行で観測し、販売形式の判定、価格Field、
終了予定時刻、`with_auction`の影響を確認します。商品ページとの照合には、端末にインストール済みの
Google Chromeを使用します。

```bash
poc/mercapi/.venv/bin/python poc/mercapi/auction_probe.py
```

ブラウザを使わずAPI側だけを確認する場合は`--skip-page-check`を付けます。

### 価格の照合方法

商品ページの価格要素（`[data-testid="price"]`、テキストは`現在 ¥900`）を読み、API値と
**1対1で比較**します。要素が読めなかった場合は`notComparable`として数え、**一致率へ含めません。**

2026-09-01までは「ページ本文から`¥`金額を全部拾い、API値がその中にあるか」という包含判定でした。
`現在の価格`というラベルを本文から探して見つからなかったためですが、実際のラベルは`現在`で、
要素には`data-testid`が付いていました。包含判定の結果は`containment`として併記し、
0-F-1の数値と比較できるようにしています。

実行中は同時実行数1、外部Request開始間隔2秒以上、自動再試行0回を維持します。生Responseはディスクへ
書き出さず、`artifacts/structure-samples/`へ匿名化済みの構造サンプルだけを出力します。
構造サンプルはFixtureの起点として使い、規約は
[Test運用規約](../../docs/development/test-policy.md)に従います。

## 未解決2件の追加観測

L4の2回の実行で残った問いを、1回の実行でまとめて観測します。Browserは使いません。

```bash
poc/mercapi/.venv/bin/python poc/mercapi/open_questions_probe.py
```

1. `num_sell_items`は累計販売件数か、出品件数か
2. `trading`（取引中）にAuction情報は付くか

結果は[未解決2件の追加観測結果](open-questions-result.md)に記録しています。判定は
**`num_sell_items`は累計販売件数ではない**、**`trading`にAuction情報は付かない**でした。

## `created`と`updated`の追加観測

`created`が編集で動くか、商品ページがどちらを表示しているかを、1回の実行で確かめます。
検索が両方の時刻を返すため、質問1にはほぼ追加Requestが要りません。

```bash
poc/mercapi/.venv/bin/python poc/mercapi/timestamp_probe.py
```

検索の並び順も同時に測ります（Phase 0-Bと同じ逆転数の手法を`created`と`updated`の両方へ）。

```bash
poc/mercapi/.venv/bin/python poc/mercapi/timestamp_probe.py --skip-page-check
```

結果は[`created`と`updated`の追加観測結果](timestamp-result.md)。判定は
**`created`は編集で動かない**（347件中254件が`updated > created`）、
**商品ページは`updated`を表示している**（3 / 3）、
**検索は`created`順ではなく`updated`の降順傾向があり、`order`パラメータは効いていない**でした。

`created`が「出品日時」かどうかは**商品ページに照合相手が無く、検証できません。**

## 商品の状態の追加観測

検索が返す`itemConditionId`が、買い手が商品ページで読む「商品の状態」と同じ意味かを確かめます。

```bash
poc/mercapi/.venv/bin/python poc/mercapi/condition_probe.py
```

対応表そのものはMercariが公開しています（master Endpoint `itemConditions`。Forkの
`docs/facets/conditions.json`に6件のsnapshot）。**未検証なのは番号と表示の結び付きだけ**なので、
実行は次の3つを見ます。

1. master Endpointの答えが、Forkのsnapshotと今も同じか（Request 1件）
2. 検索1ページが返す番号の内訳（欠落件数を含む）
3. 標本の商品ページ`[data-testid="商品の状態"]`と、表が与える表示名の**厳密比較**

包含一致は別に数え、一致率へ入れません。要素が見つからなければ**比較不能**として数え、
そのページが持っていた`data-testid`を記録します（次の実行を当てずっぽうにしないため）。

```bash
poc/mercapi/.venv/bin/python poc/mercapi/condition_probe.py --skip-page-check
poc/mercapi/.venv/bin/python poc/mercapi/condition_probe.py --skip-master
```

標本は番号ごとに巡回して選びます（既定: 番号あたり4件、上限20件）。
**現れなかった番号は未観測であり、合格ではありません。**
繰り返し実行するときは`--output`を分けてください。既定の出力先は同じで、**前回のartifactを上書きします。**

結果は[商品の状態の追加観測結果](condition-result.md)。判定は
**Forkのsnapshotはmaster Endpointと同一**、
**検索の`itemConditionId`は商品ページの表示と一致する**（番号1〜5で20 / 20）でした。
番号`6`（全体的に状態が悪い）は母集団239件で**未観測**です。

## テスト

```bash
poc/mercapi/.venv/bin/python -m unittest discover -s poc/mercapi -p 'test*.py' -v
```

## ファイル

- `run.py`: 共通プロトコルに従う非同期測定ランナー
- `seller_paging_probe.py`: PlaywrightでSellerページとページング通信を観測する補足ランナー
- `seller_status_paging_probe.py`: 観測済みパラメータで状態別2ページを取得する補足ランナー
- `test_run.py`: 正規化、エラー分類、安全停止の単体テスト
- `test_seller_paging_probe.py`: 対象選定、応答要約、Cursor引き継ぎの単体テスト
- `auction_probe.py`: Auction判定、価格、終了予定時刻、`with_auction`影響の検証ランナー
- `test_auction_probe.py`: 判定ルール、価格比較、構造サンプルのマスク、Cursorの単体テスト
- `open_questions_probe.py`: `num_sell_items`の意味と`trading`のAuction情報を観測するランナー
- `test_open_questions_probe.py`: 件数比較、Auction Field抽出、匿名化、安全停止の単体テスト
- `open-questions-result.md`: 2026-09-01の追加観測結果
- `timestamp_probe.py`: `created`と`updated`の意味を観測するランナー
- `test_timestamp_probe.py`: ラベル解析、標本選択、時刻比較の単体テスト
- `timestamp-result.md`: 2026-09-01の`created` / `updated`観測結果
- `condition_probe.py`: 検索の`itemConditionId`と商品ページの表示を突き合わせるランナー
- `test_condition_probe.py`: 表の解析、標本選択、比較判定、率の数え方の単体テスト
- `condition-result.md`: 2026-09-04の商品の状態の観測結果
- `auction-result.md`: 2026-08-31のAuction追加検証結果
- `requirements.txt`: mercapiの固定コミットと直接依存
- `result.md`: 2026-08-30実測結果とSellerページング追加検証
