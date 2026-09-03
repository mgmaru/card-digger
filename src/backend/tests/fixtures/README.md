# Test Fixture一覧

L1〜L3のTestが読む**固定入力データ**。生ResponseのDumpではなく、観測した構造だけを写した
手書き・最小化・匿名化済みのJSONとする。規約は
[Test運用規約 §5](../../../../docs/development/test-policy.md#5-fixture規約)を正本とする。

> `pytest`の`@pytest.fixture`とは別物。Fileの読み込みは`load_fixture()`で明示的に区別する。

## 規則

- 生Response、Request Header、DPoP、Cookie、Tokenを含めない
- 実商品ID、実Seller名、実Title、実画像URLを含めない
- 1 Fixture = 1検証観点
- 観測していないField名・階層・型を発明しない
- 実値ではなく境界値（`1`、欠落、空Objectなど）を選ぶ

## 区分

| 区分 | 意味 |
|---|---|
| `observed` | 観測した構造を最小化・匿名化した |
| `derived` | 観測済み構造から値・Fieldの有無だけを変えた |
| `assumed` | 構造自体を観測できていない。**合格の根拠にしない** |

**`assumed`は0件。**

## 出所

観測元はいずれも[Auction情報の追加検証](../../../../poc/mercapi/auction-result.md)（2026-08-31、
upstream commit `20ba68fd42677997c4c91b4e4eb17c1e7e387efa`）で出力した構造サンプルとする。

| Fixture | 区分 | 派生元 | 取得元 | 検証観点 |
|---|---|---|---|---|
| `search/page_1_has_next.json` | observed | — | 検索 | 通常出品とAuctionが並ぶ1ページ目。`nextPageToken`を次Cursorにする |
| `search/page_2_end.json` | derived | `search/page_1_has_next.json` | 検索 | `nextPageToken`が空文字なら終端でCursorを返さない |
| `search/empty_end.json` | derived | `search/page_2_end.json` | 検索 | 0件の終端Pageを正常な応答として扱う |
| `search/auction_empty_object.json` | derived | `search/page_1_has_next.json` | 検索 | 空`auction`を`fixed_price`へ寄せず`unknown`にする |
| `search/auction_unknown_shape.json` | derived | `search/page_1_has_next.json` | 検索 | 未知キーだけの`auction`を`unknown`にする |
| `search/statuses.json` | derived | `search/page_1_has_next.json` | 検索 | `trading`を独立状態として保持し、未知Statusを`unknown`にする |
| `search/missing_created.json` | derived | `search/page_1_has_next.json` | 検索 | 出品日時欠落をParse Errorにする |
| `search/missing_updated.json` | derived | `search/page_1_has_next.json` | 検索 | 更新日時欠落をParse Errorにする |
| `search/missing_image.json` | derived | `search/page_1_has_next.json` | 検索 | 画像URL欠落をParse Errorにする |
| `search/no_price.json` | derived | `search/page_1_has_next.json` | 検索 | `isNoPrice`のPlaceholder価格を実価格として扱わない |
| `item/auction.json` | observed | — | 商品詳細 | `auction_info`の全Fieldを読み、`highest_bid`を価格にする |
| `item/fixed_price.json` | observed | — | 商品詳細 | `auction_info`欠落を通常出品にする |
| `item/auction_info_unknown_shape.json` | derived | `item/auction.json` | 商品詳細 | 未知形状の`auction_info`を`unknown`にする |
| `seller/profile.json` | observed | — | Seller Profile | 名前・評価件数・評価の内訳・出品件数を正規化する |
| `seller_items/page_1_has_next.json` | observed | — | Seller商品一覧 | `has_next=true`で末尾`pager_id`を次Cursorにする |
| `seller_items/page_2_end.json` | derived | `seller_items/page_1_has_next.json` | Seller商品一覧 | `has_next=false`でCursorを返さない |
| `seller_items/sold_out_end.json` | derived | `seller_items/page_2_end.json` | Seller商品一覧 | `sold_out`を状態別に取得する |
| `seller_items/empty_end.json` | derived | `seller_items/page_1_has_next.json` | Seller商品一覧 | 0件 + `has_next=false`を正常終端にする |
| `seller_items/with_auction.json` | observed | — | Seller商品一覧 | `with_auction=true`時だけAuction商品に`auction_info`が付く |
| `seller_items/unknown_auction_shape.json` | derived | `seller_items/with_auction.json` | Seller商品一覧 | 未知形状の`auction_info`を`unknown`にする |
| `seller_items/has_next_without_cursor.json` | derived | `seller_items/page_1_has_next.json` | Seller商品一覧 | 続きがあるのにCursorがない応答をParse Errorにする |

## `ratings`は`num_ratings`と揃えない

`seller/profile.json`は`num_ratings`が128、`ratings.good`が126である。**`created`と`updated`を
食い違わせているのと同じ理由。** 揃えると、Adapterが`ratings.good`のつもりで`num_ratings`を
読んでもTestが通ってしまう。`normal`と`bad`も別の値にしてあり、3つの取り違えを捕まえる。

内訳の構造は[Profile構造標本](../../../../poc/mercapi/artifacts/structure-samples/profile/profile.json)
（2026-09-01、3標本すべてに`good` / `normal` / `bad`の整数あり）に基づく。**合計が
`num_ratings`と一致するかは観測していない**ため、Fixtureでもその関係を作らない。

## Fixtureにしない異常系

401 / 403 / 429 / Timeout / 通信失敗は**Response Bodyの問題ではない**ため、Fixtureを作らず
Fake Fork Clientに例外を投げさせる（[Test運用規約 §5.4](../../../../docs/development/test-policy.md#54-異常系fixtureの作り方)）。
Mercariが実際にどうErrorを返すかは未観測であり、推測した形をTestしない。

## `created`と`updated`は必ず食い違わせる

すべてのFixtureで`updated`を`created`の9日後にしている。**同じ値では、Adapterが誤って
片方を読んでもTestが通ってしまう。**

これは`initial_price`（開始価格）と`highest_bid`（現在価格）を必ず食い違わせているのと
同じ理由である。実サービスでは一致することが多く（345件中92件が`created == updated`）、
実測ではこの誤りを捕まえられない。**Fixtureだけが捕まえられる。**

## 未観測として残っているもの

次の2つは標本を取得できていない。`assumed` Fixtureを作らず、未観測のまま残す。

- 終了済みAuction（`finish_time`あり）
- 検索・商品詳細・Seller商品一覧のいずれかで実際に現れた未知形状

### 終了済みAuctionについて（2026-09-01更新）

L4第2回で**探し方を追加した**。検索は`status=on_sale`固定のため構造上現れないが、Sellerの
`sold_out`には現れうる。そこで`sold_out`をAuction判定し、候補があれば商品詳細を引く手順を
Runnerへ入れた。

| 実行 | `sold_out`の取得件数 | Auction候補 | 記録の意味 |
|---|---:|---:|---|
| 第1回 | 642 | — | 販売形式を記録せず破棄。**調べていない** |
| 第2回 | 507 | **0** | 全件を判定した。**調べたが無かった** |

**「`sold_out`に終了済みAuctionは現れない」ことの証明ではない。** 原因は次のいずれかで、
**まだ切り分けられていない。**

| 候補 | 状況 |
|---|---|
| 対象の標本に無かっただけ | 可能性あり |
| APIから取得できない | 確定していない（upstreamのモデルには`finish_time`がある） |
| **探している状態が間違っている** | **有力。`trading`（取引中）を一度も要求していない** |
| Testで検証できない | **これは原因ではない。** 標本さえあればFixtureで担保できる |

`trading`（取引中）も2026-09-01に調べたが、23件中0件で**Auction情報は付いていなかった**
（[追加観測結果](../../../../poc/mercapi/open-questions-result.md)）。同じ実行の`on_sale`では
`auction_info`が返っているため、要求の誤りではない。

3状態すべてを観測して`auction_info`が付いたのは`on_sale`だけであり、
**進行中のAuctionにしかAuction情報が付かない**可能性が高い。そうであれば、Seller商品一覧から
終了済みAuctionを識別することは構造的にできない。

なお`trading`は**`status`が取る値**であり、Auction固有ではない（通常出品にもある）。
`search/statuses.json`は`derived`であり、**`trading`の実データは未観測**である。
切り分けの実験案と実測は
[ライブ受入検証結果 §12.6](../../../../docs/phase-0/phase-0-f-live-acceptance-result.md#126-終了済みauction合格基準外の観測)。

標本が得られるまで`assumed` Fixtureは作らない。
