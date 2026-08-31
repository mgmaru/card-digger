# Phase 0-F — Auction情報の追加検証結果

## 判定

**合格。** AuctionをMVPへ含める。

- 販売形式の判定は商品ページを正として **20 / 20（100%）** 一致した
- Auctionの`price_yen`は検索`price`（= `highest_bid`）で、商品ページの現在価格と **10 / 10（100%）** 一致した
- 未入札・入札済み・終了予定時刻の欠落を区別できた
- 未知形状を`fixed_price`へ寄せない判定ルールを構成できた

ただし次の2点を制約として仕様へ反映する。

1. **Seller商品一覧は`with_auction=true`を送らないとAuction情報が返らない**
2. **検索・商品詳細・Seller商品一覧でAuction Fieldの形が3種類異なる**

検証条件と合格基準の正本は
[Auction情報の追加検証計画](../../docs/phase-0/phase-0-f-auction-validation.md)とする。

---

## 1. 実行環境

| 項目 | 値 |
|---|---|
| 実行日時 | `2026-08-31T08:01:53Z` 〜 `2026-08-31T08:03:58Z`（2分5秒） |
| Timezone | `Asia/Tokyo` |
| OS / Architecture | `macOS-26.5-arm64` / `arm64` |
| Runtime | `Python 3.11.15` |
| 対象commit | `20ba68fd42677997c4c91b4e4eb17c1e7e387efa`（`kynacio/mercapi` 0.4.2） |
| Card Digger commit | `594e8302418e5e553456984bf3a5aa27def48382` |
| 直接依存 | `httpx==0.27.2`, `playwright==1.55.0`, `ecdsa==0.19.2`, `python-jose==3.5.0`, `cryptography==50.0.1` |
| 認証状態 | 匿名。Login / 永続Cookie / 明示Token / Proxyなし |
| Browser | Google Chrome（Playwright `channel="chrome"`, Headless） |
| Command | `poc/mercapi/.venv/bin/python poc/mercapi/auction_probe.py` |

### 遵守した条件

| 条件 | 実測 |
|---|---|
| 同時実行数 | 1 |
| Request開始間隔 | 2秒以上 |
| 自動再試行 | 0回 |
| 検索Request上限3回 | **1回**で標本充足 |
| 安全停止 | 未発動 |

API Request 30件はすべて **HTTP 200**。401 / 403 / 429 / Challengeは **0件**。
商品ページ取得20件もすべて成功した。

> 本測定の前に、計測バグを含む試行を1回実施した（同条件・30 Request・全200）。
> 誤りは「Seller一覧のAuction Field名を`auction`と誤って探した」「ページ描画待ちが不足した」の2点で、
> Mercari側の応答差ではない。修正後の本測定だけを結果として採用する。

---

## 2. 標本

| 対象 | 最低標本 | 実測 |
|---|---:|---:|
| 検索の総ユニーク商品 | — | 119件 |
| オークション形式の検索商品 | 10件 | **16件**（詳細照合は10件） |
| 通常出品の検索商品 | 10件 | **103件**（詳細照合は10件） |
| 未知形状の検索商品 | — | **0件** |
| 各形式の商品詳細 | 各10件 | 各10件（合計20件） |
| 商品ページ照合 | — | 20件 |
| Auction商品を含むSeller | 最大3人 | 3人 |
| Seller Profile | — | 3人（各38 Field） |

Keywordは`ポケカ 引退品`のみ。1回の検索で両形式の最低標本を満たしたため、
代替Keywordは使用しなかった。

---

## 3. 販売形式の判定

### 3.1 経路ごとのField

**3経路でField名も型も異なる。** これが本検証の最大の所見である。

| 経路 | Field名 | キー | 値の型 | 命名 |
|---|---|---|---|---|
| 検索 | `auction` | `id` / `bidDeadline` / `totalBid` / `highestBid` / `initialPrice` | **すべて文字列** | camelCase |
| 商品詳細 | `auction_info` | `id` / `start_time` / `total_bids` / `initial_price` / `highest_bid` / `state` / `auction_type` / `expected_end_time` | 数値・文字列 | snake_case |
| Seller商品一覧 | `auction_info` | `id` / `bid_deadline` / `total_bid` / `initial_price` / `highest_bid` | 数値・文字列 | snake_case |

```text
検索         auction        { bidDeadline, highestBid, id, initialPrice, totalBid }        値はstr
商品詳細     auction_info   { auction_type, expected_end_time, highest_bid, id,
                             initial_price, start_time, state, total_bids }               値はint/str
Seller一覧   auction_info   { bid_deadline, highest_bid, id, initial_price, total_bid }   値はint/str
```

商品詳細だけが`state`と`auction_type`を持つ。Seller一覧は検索と同じ5項目をsnake_caseで返す。

### 3.2 通常出品での欠落形

| 経路 | 通常出品での値 | 実測 |
|---|---|---:|
| 検索 | `auction: null`（キーは常に存在） | 103 / 103 |
| 商品詳細 | `auction_info`キーごと**欠落** | 10 / 10 |
| Seller商品一覧 | `auction_info`キーごと**欠落** | 全件 |

検索では`null`、詳細とSeller一覧では**キー自体が存在しない**。空Objectは1件も観測されなかった。

### 3.3 `auction.id`は検索では空文字

| 経路 | `id`の実測 |
|---|---|
| 検索 `auction.id` | **空文字（長さ0）** — 16 / 16 |
| 商品詳細 `auction_info.id` | 9桁の数字文字列 |
| Seller一覧 `auction_info.id` | 9桁の数字文字列 |

**検索結果の`auction.id`をAuction判定に使ってはならない。** 空文字のため偽陰性になる。

### 3.4 採用する判定ルール

```text
1. Field（検索は auction、詳細とSeller一覧は auction_info）が
   欠落 / null / 空Object    → fixed_price
2. Objectで、既知キーを1つ以上含む → auction
3. Objectで、既知キーを1つも含まない → unknown
4. Object以外の型            → unknown
```

既知キーは経路ごとに次で判定する。

| 経路 | 既知キー |
|---|---|
| 検索 | `id`, `bidDeadline`, `totalBid`, `highestBid` |
| 商品詳細 / Seller一覧 | `id`, `start_time`, `total_bids`, `total_bid`, `initial_price`, `highest_bid`, `state`, `auction_type`, `expected_end_time`, `bid_deadline` |

### 3.5 一致率

| 比較 | 一致 | 率 |
|---|---:|---:|
| 検索判定 == 商品詳細判定 | 20 / 20 | **100%** |
| 検索判定 == 商品ページ表示（`auction`標本） | 10 / 10 | **100%** |
| 検索判定 == 商品ページ表示（`fixed_price`標本） | 10 / 10 | **100%** |
| `mercapi`モデルの`Item.auction_info is None` == 通常出品 | 20 / 20 | **100%** |

商品ページ側の判定には「`入札`の表示があるか」を用いた。「`入札`があり`購入手続きへ`がない」という
より厳しい規則でも同じく20 / 20一致した。

---

## 4. 価格

### 4.1 Field間の一致（Auction標本10件）

| 比較 | True | False |
|---|---:|---:|
| 検索`price` == 検索`auction.highestBid` | **10** | 0 |
| 検索`price` == 詳細`auction_info.highest_bid` | **10** | 0 |
| 詳細`price` == 詳細`auction_info.highest_bid` | **10** | 0 |
| 検索`auction.initialPrice` == 詳細`auction_info.initial_price` | **10** | 0 |
| 検索`price` == 詳細`auction_info.initial_price` | 7 | **3** |
| 詳細`initial_price` == 詳細`highest_bid` | 7 | **3** |

**乖離した3件は入札済みの3件と完全に一致した。** 未入札では開始価格と現在価格が等しく、
入札が入ると現在価格だけが上がる。

### 4.2 商品ページとの照合

| 指標 | 実測 |
|---|---:|
| 現在価格の一致 | **10 / 10（100%）** |
| 比較中の価格変動 | 0件 |

### 4.3 採用するMapping

```text
MarketplaceItem.price_yen
  = 検索 price
  = 検索 auction.highestBid
  = 詳細 auction_info.highest_bid
  → 取得時点の現在価格
```

- **`initial_price`（開始価格）は`price_yen`へ使わない。** 入札済み商品で実際と乖離する
- 通常出品は従来どおり`price`をそのまま使う
- 検索の`auction.*`は**文字列**のため、Adapterで整数へ変換する
- 確定落札額ではないため、UIでは「現在価格（取得時点）」と表示する

---

## 5. 入札件数・状態・終了予定時刻

### 5.1 状態の値域（Auction標本10件）

| Field | 観測値 | 件数 |
|---|---|---:|
| `state` | `STATE_NO_BID` | 7 |
| `state` | `STATE_ONGOING` | 3 |
| `auction_type` | `AUCTION_TYPE_NORMAL` | 10 |
| `total_bids` | `0` | 7 |
| `total_bids` | `1`以上 | 3 |

`state == STATE_NO_BID` と `total_bids == 0` は完全に一致した。
**未入札と入札済みを区別できる。** 終了済み（`finish_time`あり）の標本は0件だった。

### 5.2 終了予定時刻

| Field | 経路 | 型 | 存在 |
|---|---|---|---:|
| `expected_end_time` | 商品詳細 | **整数（epoch秒）** | 10 / 10 |
| `finish_time` | 商品詳細 | 整数（epoch秒） | 0 / 10 |
| `bidDeadline` | 検索 | **文字列（ISO 8601, 20文字, `Z`終端）** | 10 / 10 |
| `bid_deadline` | Seller一覧 | 文字列（ISO 8601, 20文字） | 全Auction商品 |

RFC 3339 / Asia/Tokyoへの変換は10 / 10成功した。

**検索`bidDeadline`と詳細`expected_end_time`は一致しない（3 / 10のみ一致）。**
不一致の7件はすべて未入札だった。

```text
未入札   終了予定は未確定。取得のたびに秒単位で動く（例 20:01:57 → 20:01:59）
入札済み 分単位で確定（例 20:14:00）。検索と詳細が一致する
```

メルカリガイドの「最初の入札後に終了予定が決まる」という仕様と整合する。

- **未入札のAuctionでは終了予定時刻を確定値として表示しない**
- 延長を推測して計算しない。Response値だけを扱う
- 欠落時に架空の終了時刻を生成しない

### 5.3 `mercapi`モデルのTimezone問題

固定版`mercapi`の`Extractors.get_datetime`は `datetime.fromtimestamp(float(x))` を使う。

```python
# mercapi/models/base.py
return Extractors.get_with(key, lambda x: datetime.fromtimestamp(float(x)))
```

戻り値は**Timezone情報を持たないnaive datetime**で、実行環境のLocal Timezoneに依存する。
[Adapter仕様 §6](../../docs/phase-0/phase-0-f-adapter-spec.md#6-domain型)は
Timezone付き`datetime`を要求するため、**Adapterで必ずUTCとして解釈し直す。**

---

## 6. Seller商品一覧への影響

### 6.1 `with_auction`の効果

Auction商品を持つSeller 3人の`on_sale`1ページ目を、`with_auction`ありとなしで比較した。

| Seller | 件数 | `with_auction=true`の`auction_info` | Parameter省略時の`auction_info` | `has_next` |
|---:|---:|---|---|---|
| 1 | 8 | populated 5 / absent 3 | **absent 8** | `false` |
| 2 | 25 | populated 4 / absent 21 | **absent 25** | `false` |
| 3 | 30 | populated 3 / absent 27 | **absent 30** | `true` |

| 観点 | 結果 |
|---|---|
| 件数差 | **0件**（3 Sellerとも同数） |
| 商品IDと順序 | **完全一致** |
| `pager_id` | 一致 |
| `meta.has_next` | 一致 |
| 状態Filter | 影響なし（`on_sale`のみが返る） |

**`with_auction`は件数・順序・Cursor・状態Filterに影響しない。**
`auction_info` Fieldを付けるかどうかだけが変わる。

### 6.2 制約

固定版`mercapi`の公開`items(profile_id)`は`with_auction`を送らない。

```python
# mercapi/mercapi.py
params={"seller_id": profile_id, "limit": 30, "status": "on_sale,trading,sold_out"}
```

さらに`SellerItem`モデルに`auction_info`が存在しないため、**公開APIのままではSeller商品の
Auction判定が構造的に不可能**である。Endpoint自体は`with_auction=true`で正しく返す。

→ [Fork](../../docs/phase-0/phase-0-f-adapter-spec.md#5-forkへ追加するpublic-api)へ
`with_auction`の送信と`auction_info`の保持を追加する。Sellerページングと同じ変更で対応できる。

---

## 7. 固定版`mercapi`モデルの過不足

| 項目 | 状況 | 影響 |
|---|---|---|
| `SearchResultItem.auction` | あり | 検索の判定に使える |
| `Auction.initialPrice` | **モデルに無い** | 開始価格が落ちる。MVPでは未使用のため影響なし |
| `Auction.id` | あり | ただし実データは空文字。判定に使えない |
| `Item.auction_info` | あり。optional扱い | 20 / 20で正しくNone / 値を返した |
| `AuctionInfo`の必須Field | `start_time`等が必須 | 形が変わると**例外ではなくNone**になる（後述） |
| `SellerItem.auction_info` | **モデルに無い** | Seller商品のAuction判定が不可能 |
| 日時 | naive `datetime` | Timezoneを付け直す必要がある |

### 静かな失敗の可能性

`Item`の`auction_info`は**optional**として定義されている。`AuctionInfo`の必須Field
（`state`など）が将来欠けると、`map_to_class`はParse Errorを投げず
`_report_incorrect_optional`でLogを出して**`auction_info = None`にする**。

その結果、**Auction商品が通常出品として通過する**。
[Adapter仕様の「未知形状を`fixed_price`へ寄せない」](../../docs/phase-0/phase-0-f-adapter-spec.md#6-domain型)に反するため、
**Adapterは`mercapi`モデルではなく判定ルールで形式を決め、未知形状は`unknown`にする。**

---

## 8. 合格基準との対応

| 合格基準 | 結果 |
|---|---|
| 通常・Auction各10件以上を取得している | ✅ 103件 / 16件 |
| 商品ページを正として販売形式の判定が各100%一致する | ✅ 10 / 10、10 / 10 |
| Auctionの`priceYen`に使用するFieldと意味を説明できる | ✅ `highest_bid` = 取得時点の現在価格 |
| 価格Fieldが商品ページの現在価格と95%以上一致する | ✅ 100% |
| 未入札、入札済み、終了予定時刻欠落を区別できる | ✅ `state`と`total_bids`で区別。欠落標本は0件 |
| 不明な形状を`fixed_price`へ誤変換せず`unknown`にできる | ✅ 既知キー方式で構成可能。実測の未知形状は0件 |
| 検索とSeller商品の両方を同じDomain型へ正規化できる | ⚠️ **Forkの拡張が前提**（§6.2） |
| 固定Fixtureで判定と価格のUnit Testを作成できる | ✅ 構造サンプル7件を出力済み |

---

## 9. 出力した構造サンプル

Fixtureの起点として、匿名化済みの構造サンプルを出力した。
実ID・実Title・実画像URL・Cookie・DPoP・生Responseは含まない。

```text
poc/mercapi/artifacts/structure-samples/
├── search/auction.json            16件をmerge
├── search/fixed_price.json       103件をmerge
├── item/auction.json              10件をmerge
├── item/fixed_price.json          10件をmerge
├── seller_items/with_auction.json
├── seller_items/without_auction.json
└── profile/profile.json            3件をmerge
```

`artifacts/`はGit管理外。Fixture化の規約は
[Test運用規約 §5](../../docs/development/test-policy.md#5-fixture規約)に従う。

---

## 10. Error・安全停止・条件差

| 項目 | 実測 |
|---|---:|
| API Request総数 | 30件 |
| HTTP 200 | 30件 |
| 401 / 403 / 429 / Challenge | **0件** |
| Timeout / Parse Error | 0件 |
| 商品ページ取得 | 20 / 20成功 |
| 安全停止 | 未発動 |
| 自動再試行 | 0回 |

条件差は次の1点。

- 前回PoC（Phase 0-B）は`Linux / Python 3.11.9`、本検証は`macOS / Python 3.11.15`。
  依存Versionは同一。

---

## 11. 仕様へ反映する内容

| 反映先 | 内容 |
|---|---|
| Adapter仕様 §6 | `price_yen` = `highest_bid`（取得時点の現在価格）。`initial_price`は使わない |
| Adapter仕様 §6 | 日時はnaiveのためUTCとして解釈し直す |
| Adapter仕様 §5 | Forkへ`with_auction`送信と`auction_info`保持を追加する |
| Adapter仕様 §7 | Seller商品も`with_auction=true`で取得する |
| Adapter仕様 §10.2 | 3経路のField形状差をAdapterで吸収する |
| MVP仕様 §5.1 | 販売形式Filterを有効化する |
| MVP仕様 §5.6 | 未入札のAuctionは終了予定時刻を確定値として表示しない |

---

## 12. 再検証が必要になる条件

- `auction` / `auction_info`のキー構成が変わったとき
- 検索`auction.id`が空文字でなくなったとき
- `state`に`STATE_NO_BID` / `STATE_ONGOING`以外の値が現れたとき
- `auction_type`に`AUCTION_TYPE_NORMAL`以外が現れたとき
- Seller一覧が`with_auction`なしでも`auction_info`を返すようになったとき
- 終了済みAuction（`finish_time`あり）を扱う必要が出たとき

本検証では終了済みAuctionと未知形状の標本を取得できていない。
この2つは`assumed`ではなく**未観測**として残し、合格の根拠に含めない。
