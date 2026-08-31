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

実行中は同時実行数1、外部Request開始間隔2秒以上、自動再試行0回を維持します。生Responseはディスクへ
書き出さず、`artifacts/structure-samples/`へ匿名化済みの構造サンプルだけを出力します。
構造サンプルはFixtureの起点として使い、規約は
[Test運用規約](../../docs/development/test-policy.md)に従います。

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
- `auction-result.md`: 2026-08-31のAuction追加検証結果
- `requirements.txt`: mercapiの固定コミットと直接依存
- `result.md`: 2026-08-30実測結果とSellerページング追加検証
