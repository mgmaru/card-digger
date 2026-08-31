# Phase 0-F — Auction情報の追加検証計画

## 文書ステータス

- 作成日: **2026-08-31**
- ステータス: **実行前。Auction対応をMVPへ実装する前の必須Gate**
- 対象: 固定commit `20ba68fd42677997c4c91b4e4eb17c1e7e387efa`の`kynacio/mercapi`
- 関連仕様: [Mercari Adapter実装仕様](phase-0-f-adapter-spec.md)
- Product要件: [MVP実装仕様](../product/mvp-spec.md)
- Test実施方法: [Test運用規約](../development/test-policy.md)

## 1. 目的

通常出品とオークション形式を安全に判定し、価格を誤解させずにCard Diggerへ表示できるか確認する。

既存PoCでは検索とSeller商品一覧のRequestにAuctionを含めているが、Auction Fieldを共通モデルへ
正規化しておらず、次の点は未検証である。

- 通常出品とオークションを判別するFieldと欠落時の意味
- 検索結果の`price`がオークション商品の何の価格を表すか
- 入札件数、開始価格、最高入札額、終了予定時刻の整合性
- 検索、商品詳細、Seller商品一覧でのField形状の差
- `with_auction`がSeller商品件数、状態、Cursorへ与える影響

「Auction Fieldがある」「`withAuction=true`でRequestしている」だけではMVP採用の根拠にしない。

## 2. Product上の前提

メルカリのオークションは、開始価格以上で入札し、終了時点の最高入札額で購入する形式である。
最初の入札後に終了予定が決まり、終了間際の入札や出品者の操作により終了時刻が変わり得る。

そのためMVPでは次を前提とする。

- Auction情報は検索取得時点のSnapshotであり、リアルタイム値とは表示しない
- 入札、落札、購入、自動更新、Countdownを実装しない
- 通常価格とAuction現在価格を同じ意味の確定価格として表示しない
- 最終確認と操作はMercariの商品ページで行う

公式仕様は[メルカリガイド「オークション機能」](https://help.jp.mercari.com/guide/articles/1925/)を
実行時にも再確認する。

## 3. 検証条件

### 3.1 共通条件

- 匿名アクセス
- Login、永続Cookie、明示Token、Proxyを使用しない
- 同時実行数1
- 外部Request開始間隔2秒以上
- 自動再試行0回
- 401 / 403 / 429 / Challengeが合計3回連続したら停止する
- Cookie、DPoP、Header、生Response、Seller名を結果文書へ保存しない
- 画像Bodyを保存しない

### 3.2 標本

最初に`ポケカ 引退品`を1回検索する。標本が不足する場合だけ`ポケモンカード`等の一般的な
Keywordを追加し、検索Requestは最大3回までとする。

| 対象 | 最低標本 | 上限 |
|---|---:|---:|
| オークション形式の検索商品 | 10件 | 20件 |
| 通常出品の検索商品 | 10件 | 20件 |
| 各形式の商品詳細 | 各10件 | 合計20件 |
| Auction商品を含むSeller | 取得できた最大3人 | 3人 |

最低標本へ到達しない場合は、得られた全件を記録したうえで「標本不足」とし、推測で合格にしない。

## 4. 確認するField

実際のResponseと固定版`mercapi`の公開モデルを照合する。Field名が変わっている場合は、観測した
Field名と型を結果へ記録する。

| 取得元 | 確認候補 | 確認内容 |
|---|---|---|
| 検索結果 | `auction` | 通常出品での欠落・`null`・空Object、Auctionでの存在 |
| 検索結果 | `auction.id` | Auction判定に利用できる安定したIDか |
| 検索結果 | `bidDeadline` | 型、Timezone、未入札時の値 |
| 検索結果 | `totalBid` | 型、0件時、表示上の入札件数との一致 |
| 検索結果 | `highestBid` | `price`および表示上の現在価格との一致 |
| 商品詳細 | `auction_info` | 検索結果のAuction判定との一致 |
| 商品詳細 | `initial_price` | 開始価格との一致 |
| 商品詳細 | `highest_bid` | 現在価格との一致 |
| 商品詳細 | `expected_end_time` | Timezone、延長後の更新、欠落条件 |
| 商品詳細 | `state` / `auction_type` | 状態と形式の値域 |
| Seller商品 | Auction Field | 検索・詳細と同じ判定が可能か |

## 5. 検証手順

### 5.1 検索結果

1. `withAuction=true`で検索する
2. Auction Fieldの有無で候補を分類する
3. 通常・Auctionから標本を選ぶ
4. 商品ページの販売形式表示と照合する
5. 判定一致率、Field欠落率、未知形状数を記録する

### 5.2 価格

Auction標本ごとに次を同じ取得時点で比較する。

```text
検索結果 price
検索結果 auction.highestBid
商品詳細 auction_info.initial_price
商品詳細 auction_info.highest_bid
Mercari商品ページの現在価格
```

`priceYen`へ何を割り当てるかは、この比較結果が出るまで決定しない。入札によって比較中に価格が
変化した場合は不一致として数えず、変化を確認できた標本として別記する。

### 5.3 終了予定時刻

- 未入札と入札済みを分ける
- RFC 3339へ変換してTimezoneを明示する
- 商品ページ表示との一致を確認する
- 終了間際の延長を推測して計算せず、Response値だけを扱う
- 欠落時に架空の終了時刻を生成しない

### 5.4 Seller商品一覧

Auction商品を出品している最大3 Sellerで、販売中商品の1ページ目を確認する。

- `with_auction=true`でAuction商品が含まれるか
- `with_auction=false`またはParameter省略時の件数差
- 状態別Filterと`pager_id` / `meta.has_next`への影響
- 検索結果と同じ`SaleFormat`判定を適用できるか

## 6. 合格基準

### 6.1 AuctionをMVPへ含められる条件

- 通常・Auction各10件以上を取得している
- 商品ページを正として販売形式の判定が各100%一致する
- Auctionの`priceYen`に使用するFieldと意味を説明できる
- 価格Fieldが商品ページの取得時点の現在価格と95%以上一致する
- 未入札、入札済み、終了予定時刻欠落を区別できる
- 不明な形状を`fixed_price`へ誤変換せず`unknown`にできる
- 検索とSeller商品の両方を同じDomain型へ正規化できる
- 固定Fixtureで判定と価格のUnit Testを作成できる

### 6.2 合格しない場合

1. `withAuction=false`でAuctionを確実に除外できるなら、MVPを通常出品だけへ縮小する
2. 除外も判定も不安定なら、`SaleFormat.UNKNOWN`として保持し、形式Filterを有効化しない
3. どちらの場合も通常出品と断定して表示せず、MVP仕様とAdapter仕様を実測結果に合わせて更新する

## 7. MVPへ採用する最小範囲

合格後もMVPへ含めるのは次だけとする。

- `fixed_price` / `auction` / `unknown`への正規化
- 検索結果の販売形式Badge
- `すべて` / `通常出品` / `オークション`Filter
- Auction商品の「現在価格（取得時点）」表示
- Mercari商品ページへのLink

次はMVPへ含めない。

- Card Diggerからの入札・購入
- Auction終了時刻の自動更新
- 残り時間Countdown
- 入札履歴一覧
- 自動再取得、終了通知、落札監視
- Auction専用の価格予測やOpportunity Score

## 8. 結果の記録

### 8.1 結果文書

実行後は`poc/mercapi/auction-result.md`へ次を記録する。

- 実行日時、環境、固定commit SHA
- KeywordとRequest数
- 通常・Auctionの標本数
- 判定一致率と未知形状
- 価格・入札件数・終了予定時刻のField対応
- Seller一覧への影響
- Error、安全停止、条件差
- 合否と採用するDomain mapping
- 追加検証または再検証条件

結果文書が完成するまで、Auction対応をPhase 0-F完了扱いにしない。

### 8.2 Fixture用の構造サンプル

[合格基準 §6.1](#61-auctionをmvpへ含められる条件)は「固定Fixtureで判定と価格のUnit Testを
作成できる」ことを条件にしている。検証後にField形状を再確認するためのライブRequestを
追加で発生させないため、**この検証と同じ実行内で**Fixtureの起点を出力する。

```text
検証実行
   │
   ├─→ auction-result.md        判定・比率・合否（Git管理）
   │
   └─→ artifacts/               Git管理外
         構造サンプル（Field名・型・存在有無・マスク済み値）
                │
                └─→ 手作業で匿名化・最小化 ─→ tests/fixtures/
```

#### 出力する経路

Phase 0-A〜0-Cの`artifacts/`は残っておらず、`result.md`にField名はあるが型・`null`・欠落・
Object全体の形は残っていない。**Phase 0-Fで必要になるFixtureの根拠は、この実行だけが持つ。**
そのため、Auction判定に直接必要な経路だけでなく、次の4経路すべてを出力する。

| 経路 | 用途 | Auction判定に必要か |
|---|---|:---:|
| 検索結果 | 販売形式判定、`SearchPage`の正規化 | 必要 |
| 商品詳細 | 価格・終了予定時刻の照合、`get_item` | 必要 |
| Seller商品一覧 | `pager_id` / `meta.has_next`、ForkのUnit Test | 必要 |
| Seller Profile | `Seller`型の正規化 | 不要 |

Seller Profileは本検証の判定には使わないが、**後日ライブ実行を追加しないため**、§3.2で選んだ
Seller（最大3人）について同じ実行内で取得する。Request数は最大3件増える。同時実行数1、
開始間隔2秒以上の条件は変更しない。

#### 出力する内容

| 出力する | 出力しない |
|---|---|
| Field名とJSONの型 | 実商品ID、実Seller ID、Seller名 |
| 存在 / `null` / 欠落の別 | 実商品Title、実画像URL |
| 値の形式（桁数、Timezone表記など） | Cookie、DPoP、Header、Token |
| 通常出品・Auction・未知形状の各1件以上 | 生ResponseそのままのDump |
| `meta`と末尾商品の`pager_id` | 画像Body |

匿名化規則と保存先の境界は[Test運用規約 §5](../development/test-policy.md#5-fixture規約)・
[§6](../development/test-policy.md#6-生responseの取り扱い境界)に従う。
