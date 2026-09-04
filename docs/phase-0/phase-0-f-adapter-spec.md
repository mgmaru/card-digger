# Phase 0-F — Mercari Adapter実装仕様

## 文書ステータス

- 決定日: **2026-08-30**
- 最終更新日: **2026-09-04**（`item_condition`の根拠区分を`observed`へ改めた）
- ステータス: **実装基準として採用**
- 対象: Phase 0-Fの`mercapi` Fork、Mercari Adapter、取得Policy、Contract Test
- 前提: [Phase 0-Eの選定結果](phase-0-e-selection.md)
- Product側の挙動: [MVP実装仕様](../product/mvp-spec.md)
- Repository運用: [mercapi Fork運用手順](../development/mercapi-fork-operations.md)
- Test実施方法: [Test運用規約](../development/test-policy.md)
- 追加検証: [Auction情報の追加検証計画](phase-0-f-auction-validation.md) / [実測結果](../../poc/mercapi/auction-result.md)

この文書はPhase 0-Fの正本とする。実装中に判断が分かれた場合は、コードだけで挙動を決めず、
この文書とTODOを先に更新する。

## 1. 目的

Applicationと`mercapi`の間に安定した境界を作り、Mercari側やForkの型・Parameter変更を
Adapterの内側へ閉じ込める。

```mermaid
flowchart LR
    A[Application / Use case] --> B[MarketplacePort]
    B --> C[MercariAdapter]
    C --> D[管理下のmercapi Fork]
    D --> E[Mercari Endpoint]
```

Phase 0-Fでは画面を作らない。PythonのDomain型、Interface、Adapter、収集Policy、Mock、Testを
完成させ、Phase 1から利用できる状態を作る。

## 2. 決定事項

| 項目 | 決定 |
|---|---|
| Adapter実装言語 | Python 3.11以上。採用ライブラリ`mercapi`と同じProcessで利用する |
| 採用方式 | 管理下の`kynacio/mercapi` Forkだけを本番取得経路にする |
| 依存固定 | Branch名やVersion範囲ではなく、検証済みcommit SHAへ固定する |
| Application境界 | `MarketplacePort`だけを参照し、`mercapi`の型を参照しない |
| Seller一覧 | `on_sale`と`sold_out`を別Request・別Cursorで取得する |
| `trading` | Domain上は独立状態として保持する。MVPでは専用収集を行わない |
| 販売形式 | `fixed_price` / `auction` / `unknown`をDomainで保持し、未知形状を通常出品へ寄せない |
| Auction | 追加検証に**合格**。検索・Seller一覧の両方で有効化する |
| Auction価格 | `highest_bid`（取得時点の現在価格）を`price_yen`にする。`initial_price`は使わない |
| 日時 | `mercapi`はnaive `datetime`を返すため、AdapterでLocal Timezoneとして解釈しUTCへ変換する |
| 古い順 | Server側の順序を信用せず、取得範囲内だけをApplication側でSortする |
| 商品詳細 | Adapterに用意するが、MVP検索一覧では自動取得しない |
| Playwright | 自動Fallbackに使わず、仕様調査・障害診断用PoCに限定する |
| 永続化 | Phase 0-Fでは行わない。実行時にCookie、Token、生Response、画像本体を保存しない |
| Test Fixture | 生Responseではなく、匿名化・最小化した構造標本をGit管理する |
| テスト可能性 | 時計、待機、Fork ClientをAdapter / Use caseの内部で生成せず注入する |

Raw Fieldから`SaleFormat`と`price_yen`へのMappingは
[Auction追加検証の実測結果](../../poc/mercapi/auction-result.md)を根拠とし、§6.1に確定値を記載する。
実測していない形（終了済みAuction、未知形状）は`unknown`として扱い、推測で実装しない。

## 3. 責務の境界

### 3.1 `mercapi` Forkの責務

Forkには、Mercariを利用する一般的なPython Clientとして成立する機能だけを追加する。

- Seller商品一覧で状態を指定できる
- Seller商品一覧で`with_auction`を指定できる
- Seller商品の`auction_info`をResponseモデルへ保持する
- `max_pager_id`をRequestへ渡せる
- 各Seller商品の`pager_id`をResponseモデルへ保持する
- `meta.has_next`をResponseモデルへ保持する
- 次ページ用Cursorを公開型から取得できる
- 既存の`items(profile_id)`との後方互換を維持する
- 固定Response FixtureによるUnit Testを持つ

Card Digger固有の次の処理はForkへ入れない。

- 最大ページ数、最大件数、最大実行時間
- 365日以上前を探す停止条件
- ページ間の重複排除
- Client側の古い順・価格順Sort
- Seller Knowledgeの分類とScore
- Card DiggerのError表示文言
- Application用Cacheや永続化

### 3.2 Mercari Adapterの責務

- `mercapi`モデルをDomain型へ変換する
- URL、日時、価格、販売状態、販売形式を正規化する
- Auctionの価格を取得時点のSnapshotとして扱い、確定落札額へ変換しない
- 販売形式の未知形状を`SaleFormat.UNKNOWN`として保持する
- 必須Field欠落を成功扱いにしない
- `mercapi`例外・HTTP Errorを共通Errorへ分類する
- `MarketplacePort`を実装する
- ForkのPublic APIだけを利用する

### 3.3 Application / Use caseの責務

- 複数ページの収集と停止条件
- 商品IDによる重複排除
- Phase 1へ渡す取得範囲・最古・最新日時・取得時刻・打ち切り理由のMetadata
- Seller Knowledgeの計算
- Loadingと手動再実行

## 4. 管理下Forkの作成・更新手順

作成、Remote設定、upstream取込、依存SHA更新、切戻しの実作業は
[mercapi Fork運用手順](../development/mercapi-fork-operations.md)を正本とする。
実装開始前にGitHub上で`kynacio/mercapi`をForkし、Card Diggerとは別Repositoryとして管理する。

```text
kynacio/mercapi
    ↓ Fork
mgmaru/mercapi
    ↓ 特定commitを依存指定
card-digger
```

Fork元の変更は自動で取り込まず、Card DiggerもForkのBranchではなくTest済みcommit SHAへ固定する。
upstreamからForkへの取込と、ForkからCard Diggerへの依存更新を別々にレビュー・検証する。

## 5. Forkへ追加するPublic API

名称は上流のCoding Styleに合わせて調整できるが、次の情報と挙動は変更しない。

実装済みのPublic APIは次のとおり（Fork `b3bdec9`時点）。

```python
@dataclass
class SellerItemsPage:
    items: list[SellerItem]
    has_next: bool
    next_max_pager_id: int | None = None

@dataclass
class SellerItemAuctionInfo:
    id_: str | None = None
    bid_deadline: str | None = None
    total_bid: int | None = None
    initial_price: int | None = None
    highest_bid: int | None = None

async def items_page(
    profile_id: str,
    statuses: Sequence[str],
    *,
    limit: int = 30,
    max_pager_id: int | None = None,
    with_auction: bool = False,
) -> SellerItemsPage | None:
    ...
```

`pager_id`は実測で**10桁の整数**だったため、Cursorは`int`で扱う。Domainの
`PageInfo.next_cursor`は`str | None`のままとし、**Adapterが文字列へ変換する**。
Sellerが存在しない場合（HTTP 404）は`None`を返す。

### Parameter規則

- `profile_id`: 空文字を拒否する
- `statuses`: `on_sale`、`trading`、`sold_out`だけを許可し、1件以上を必須にする
- `limit`: `1..30`。MVPでは30固定で使う
- `max_pager_id`: 1ページ目は`None`、2ページ目以降は直前Responseの値を使う。型は`int`
- `with_auction`: `true`のときだけResponseに`auction_info`が付く。件数・順序・Cursor・状態Filterは変わらない
- `SellerItem`は`auction_info`を保持する。省略時と非Auction商品ではキーごと欠落する

### Response規則

- `items`はResponse順を保持する
- `has_next=false`なら`next_max_pager_id=None`にする
- `has_next=true`なら、末尾商品の`pager_id`を`next_max_pager_id`にする
- `has_next=true`なのに商品が空、または末尾`pager_id`がない場合はParse Errorにする
- Cursorを推測・生成しない
- Unknown Fieldは無視できるが、必須Field欠落はErrorにする
- `meta.has_next`が欠落している場合もParse Errorにする
- `exclude_archived_item`は送らない。PoCのBrowser観測では送られていたが、Public APIの
  Parameterには含めない。件数差が問題になればライブ受入検証で検出する

### 5.1 0-F-4で追加したFork側の修正

Adapterを実装する過程で、**この仕様をForkのPublic APIだけでは満たせない箇所**が2つ見つかった。
どちらもCard Digger側では回避できないため、Forkを修正してから依存SHAを固定した。

| # | 症状 | 修正 |
|---|---|---|
| 1 | 商品詳細の未知形状Auctionが通常出品として通過する | `AuctionInfo`の全Fieldをoptionalにした |
| 2 | HTTP 401 / 403 / 429 / 5xxがParse Errorとして届く | 404以外のError StatusでRaiseするようにした |

#### 1. 未知形状のAuctionが通常出品になる

`Item.auction_info`はoptionalとして定義されているため、`AuctionInfo`の必須Field
（`state`など）が欠けると`map_to_class`はParse Errorを投げず、Logだけ出して
`auction_info = None`にする。これは`auction_info`が最初から無い通常出品と**区別できない**。

§6.1の「Objectだが既知キーを1つも含まない → UNKNOWN」を、Card Digger側では実装できない。
そこで0-F-3で`SellerItemAuctionInfo`へ既に採用していた「全Fieldをoptionalにし、未知形状を
全None instanceとして保存する」方式へ`AuctionInfo`も揃えた。

#### 2. Error StatusがParse Errorになる

Forkは404だけを判定した後、Response Bodyをそのままmapperへ渡していた。401 / 403 / 429 / 5xxは
想定外のBodyとしてParse Errorになり、**Statusも理由も失われる**。

§9のError分類はRate Limitを他と区別することが前提であり、
`unauthorized_401` / `forbidden_403` / `rate_limited_429`が実通信から到達不能では
3回連続の安全停止が機能しない。404以外のError StatusでRaiseするよう修正した。
404の意味は変えない（商品・Sellerなしは`None`のまま）。

PoCはこの2点を`api._client`へのEvent Hook追加で回避していたが、
§3.2「ForkのPublic APIだけを利用する」に反するためAdapterでは採用しない。

## 6. Domain型

Pythonの`dataclass(frozen=True)`または同等の不変Modelとして定義する。日時はTimezone付き
`datetime`、金額は日本円の整数、Collectionは呼出側で変更できない型を使う。

```python
class ListingStatus(str, Enum):
    ON_SALE = "on_sale"
    TRADING = "trading"
    SOLD_OUT = "sold_out"
    UNKNOWN = "unknown"

class SaleFormat(str, Enum):
    FIXED_PRICE = "fixed_price"
    AUCTION = "auction"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class ItemCondition:
    id: str | None
    name: str | None

@dataclass(frozen=True)
class MarketplaceItem:
    id: str
    title: str
    price_yen: int
    url: str
    image_urls: tuple[str, ...]
    created_at: datetime
    updated_at: datetime          # 最終更新。商品ページが表示しているのはこちら
    listing_status: ListingStatus
    sale_format: SaleFormat
    seller_id: str
    item_condition: ItemCondition | None = None
    like_count: int | None = None

@dataclass(frozen=True)
class RatingBreakdown:
    good: int                       # 件数。尺度を持たないので画面へ出せる
    normal: int
    bad: int

@dataclass(frozen=True)
class Seller:
    id: str
    name: str
    rating: float | None
    rating_count: int | None
    rating_breakdown: RatingBreakdown | None   # 3つ揃うか、丸ごと無いか
    listed_item_count: int | None   # 出品件数。販売件数ではない
    url: str

@dataclass(frozen=True)
class PageInfo:
    has_next: bool
    next_cursor: str | None

@dataclass(frozen=True)
class SearchPage:
    items: tuple[MarketplaceItem, ...]
    page_info: PageInfo

@dataclass(frozen=True)
class SellerItemsPage:
    items: tuple[MarketplaceItem, ...]
    requested_status: ListingStatus
    page_info: PageInfo
```

### 必須Field

| 型 | 必須Field |
|---|---|
| `MarketplaceItem` | ID、Title、1円以上の価格、HTTPS URL、1件以上の画像URL、出品日時、状態、販売形式、Seller ID |
| `Seller` | ID、名前、HTTPS Seller URL |
| Page | `has_next`と整合するCursor |

必須Fieldが欠けたRecordは黙って除外しない。Field名と操作を含むParse Errorとして、その取得操作を
失敗させる。`SaleFormat.UNKNOWN`は未知形状を表す有効値であり、`FIXED_PRICE`へ変換しない。
`item_condition`、`like_count`、評価、評価件数、評価の内訳、販売件数だけはNullableとする。
評価の内訳は`good` / `normal` / `bad`が**3つ揃うか、丸ごと無いか**の2状態しか取らない。
Forkが3つを自分の`Ratings`の必須Fieldとして宣言しているため、欠けた1つを含むObjectは届かない。

`price_yen`は、通常出品では販売価格、Auctionでは取得時点の現在価格とする。
Auctionの開始価格や確定落札額で代用しない。

### 6.1 Auction Fieldの正規化

[実測結果](../../poc/mercapi/auction-result.md)で確定した内容とする。**3経路でField名も型も異なる。**

| 経路 | Field名 | キー | 値の型 |
|---|---|---|---|
| 検索 | `auction` | `id` / `bidDeadline` / `totalBid` / `highestBid` / `initialPrice` | **すべて文字列** |
| 商品詳細 | `auction_info` | `id` / `start_time` / `total_bids` / `initial_price` / `highest_bid` / `state` / `auction_type` / `expected_end_time` | 数値・文字列 |
| Seller商品一覧 | `auction_info` | `id` / `bid_deadline` / `total_bid` / `initial_price` / `highest_bid` | 数値・文字列 |

#### `SaleFormat`の判定

```text
1. Fieldが 欠落 / null / 空Object     → FIXED_PRICE
2. Objectで既知キーを1つ以上含む      → AUCTION
3. Objectだが既知キーを1つも含まない  → UNKNOWN
4. Object以外の型                     → UNKNOWN
```

- **検索の`auction.id`は空文字のため、判定に使わない**
- `mercapi`の`Item.auction_info`が`None`かどうかを判定根拠にしない。
  必須Fieldが欠けると例外ではなく`None`になり、Auctionが通常出品として通過する
- 通常出品は検索で`auction: null`、詳細とSeller一覧ではキーごと欠落する

#### 価格

```text
price_yen = 検索 price = auction.highestBid = auction_info.highest_bid
```

- `initial_price`（開始価格）は`price_yen`へ使わない。入札済み商品で現在価格と乖離する
- 検索の`auction.*`は文字列のため整数へ変換する

#### 日時

- `expected_end_time`、`start_time`はepoch秒。`bidDeadline` / `bid_deadline`はISO 8601文字列
- `mercapi`は`datetime.fromtimestamp()`でnaive `datetime`を返す。詳細は§6.2
- 未入札（`state=STATE_NO_BID`、`total_bids=0`）の終了予定時刻は確定値ではない。確定値として扱わない
- 欠落時に架空の終了時刻を生成せず、延長を推測しない

### 6.2 naive `datetime`の解釈

`mercapi`の`Extractors.get_datetime`は`datetime.fromtimestamp(float(x))`を使う。

```python
# 返り値はTimezone情報を持たない
datetime.fromtimestamp(1756600000)
```

**この値はUTCではなく、実行環境のLocal Timezoneで表した時刻である。**
UTCとして解釈し直すとLocal Offset分ずれる。開発機（`Asia/Tokyo`）では9時間ずれ、
出品日時の表示と365日基準の判定が両方とも誤る。

したがってAdapterは、Pythonにおけるnaive値の意味どおり**Local Timezoneとして解釈**し、
UTCへ変換する。

```python
value.astimezone(timezone.utc)
```

`astimezone()`はnaive値を実行環境のLocal Timezoneとみなすため、TZ設定にかかわらず
元の瞬間を復元できる。`TZ=UTC`の環境では「UTCとして解釈し直す」と同じ結果になる。

> 2026-08-31以前のこの文書は「UTCとして解釈し直す」と記載していた。0-F-4の実装時に
> `TZ=UTC`以外の環境で成立しないことが判明したため訂正した。Phase 0-BのPoC
> （[`normalize_search_item`](../../poc/mercapi/result.md)）は当初からLocal解釈で実装されており、
> 実測結果はこの訂正の影響を受けない。

### 6.3 Field対応表 — どこから来て、意味に根拠があるか

`num_sell_items`を`total_sales_count`（累計販売件数）と誤って名付けた原因は、
**改名に2種類あることを区別していなかった**ことにある。

| 種類 | 例 | 根拠 |
|---|---|---|
| **転記** | `num_ratings` → `rating_count` | **不要。** 意味は変わらず、命名規則の違いだけ |
| **主張** | `num_sell_items` → `total_sales_count` | **必要。** `sell`（出品）→ `sales`（販売）で意味が変わっている |

主張には、[Fixture規約](../development/test-policy.md#5-fixture規約)と同じ語彙で根拠区分を付ける。

| 区分 | 意味 | 扱い |
|---|---|---|
| `observed` | 外部の正（商品ページなど）と**値を突き合わせた** | 画面へ出してよい |
| `derived` | 他の観測から論理的に導ける | 画面へ出してよい |
| `assumed` | **まだ検証していない** | **塞ぐべきTask。** 画面へ出す前に潰す |
| `unverifiable` | **検証する手段が存在しない**（照合相手が無い） | **塞げない。** 出すなら限界を明示する |

`assumed`と`unverifiable`は違う。前者は「やっていない」、後者は「やる方法が無い」。
**前者はTODOに置く。後者はTODOに置かない**（永久に閉じないため）。限界として記録する。

#### `MarketplaceItem`

| Domain Field | 出所 | 種別 | 根拠区分 | 根拠 |
|---|---|---|---|---|
| `id` | `id_` | 転記 | — | — |
| `title` | `name` | 主張 | `derived` | 商品ページに`data-testid="name"`がある。**値は突き合わせていない** |
| `price_yen` | `real_price` / `price` / `auction.highest_bid` | **主張** | **`observed`** | 商品ページの価格要素と10 / 10一致（[L4 §12.8](phase-0-f-live-acceptance-result.md#128-auction価格と商品ページの照合step-2)） |
| `url` | `id`から生成 | 生成 | `observed` | 20 / 20でHTTP 200 |
| `image_urls` | `photos` / `thumbnails` | 転記 | `observed` | 画像本体の取得・デコードに成功（Phase 0-B） |
| **`created_at`** | **`created`** | **主張** | **`unverifiable`** | 商品ページに照合相手が無い。下記 |
| **`updated_at`** | **`updated`** | 転記 | **`observed`** | 商品ページの経過時間と3 / 3一致（[観測結果](../../poc/mercapi/timestamp-result.md)） |
| `listing_status` | `status` | 転記 | `observed` | `on_sale` / `trading` / `sold_out`の3値を実際に観測した |
| `sale_format` | `auction` / `auction_info`の有無 | **主張** | **`observed`** | 商品ページを正として20 / 20一致 |
| `seller_id` | `seller_id` / `seller.id_` | 転記 | `observed` | この値でProfileを取得できる |
| `item_condition` | `item_condition` / `item_condition_id` | 転記 | **`observed`** | 検索の`item_condition_id`が商品ページの`[data-testid="商品の状態"]`と20 / 20一致（[観測結果](../../poc/mercapi/condition-result.md)）。番号`6`は**未観測**。表示名はMercariのmaster Endpointが正本 |
| `like_count` | `num_likes` | 転記 | `derived` | 商品ページに`data-testid="icon-heart-button"`がある。**値は突き合わせていない** |
| **`seller_is_inactive`** | **`seller.is_inactive`** | **転記** | **`unverifiable`** | 商品詳細139 / 139が保持し、同一Sellerの別商品と12 / 12一致。**照合相手が存在しない**（[観測結果](../../poc/mercapi/inactive-result.md)）。下記 |

#### `Seller`

| Domain Field | 出所 | 種別 | 根拠区分 | 根拠 |
|---|---|---|---|---|
| `id` | `id_` | 転記 | — | — |
| `name` | `name` | 転記 | — | — |
| `rating` | `star_rating_score` | 主張 | **`assumed`** | **スケール未確認。** 5段階か100点かを観測していない |
| `rating_count` | `num_ratings` | 転記 | — | — |
| `rating_breakdown` | `ratings`（`good` / `normal` / `bad`） | 転記 | — | Profile構造標本3 / 3で`good` / `normal` / `bad`の整数を持つ（[構造サンプル](../../poc/mercapi/auction-result.md#9-出力した構造サンプル)。**`artifacts/`はGit管理外**）。**件数であり尺度を持たない** |
| `listed_item_count` | `num_sell_items` | **主張** | **`observed`** | §6.4 |
| `url` | `id`から生成 | 生成 | `observed` | Sellerページを開ける |

#### `seller_is_inactive`は転記であって主張ではない（2026-09-05決定）

商品詳細Responseの`seller`は**18項目**を持ち、Forkが写しているのは17項目である
（残る1つは`region_code`）。`is_inactive`は
[2026-09-04の実測](../../poc/mercapi/inactive-result.md)を経てDomainへ載せた。

| 分かったこと | 状態 |
|---|---|
| `seller`は常に`is_inactive`を持つ | **確定。** 139 / 139。厳密に真偽値で、非真偽値0件 |
| 出品者についての事実である（商品ごとに変わらない） | **確定。** 同一Sellerの別商品と12 / 12一致 |
| **買い手に見える対応物がある** | **`unverifiable`。** Sellerページ・商品ページを両群で開き、`data-testid`の語彙全体（25〜70個）と候補語11語で比べて差が出ない |
| **「休眠」を指す** | **未確定。** Trueは登録の新しい小規模な口座に寄り、登録日の範囲は両群で完全に重なる |

**`unverifiable`なので載せられる。** `assumed`（やっていない）なら塞ぐべきTaskだが、
これは**やる手段が無い**——この値はMercariの画面に現れないと考えられ、
API＋DOMという検証手段は今後も成立しない。`created_at`と同じ区分であり、
**限界を画面へ書いたうえで出す**（[MVP仕様 §6.2](../product/mvp-spec.md#非アクティブを出す2026-09-05決定)）。

**画面の語が「非アクティブ」なのは転記だからである。** `is_inactive`から意味が動いていない。
「休眠中」「退会済み」は意味を選ぶ**主張**にあたり、根拠が無いので使わない。

##### `MarketplaceItem`に置く理由

**出品者についての事実だが、商品Responseが運ぶ。** `seller_id`と同じ形である。

| 経路 | `is_inactive` |
|---|---|
| 検索 | **無い**（`seller` object自体が無い） |
| **商品詳細** | **ある** |
| Seller商品一覧 | **無い** |
| **Seller Profile** | **無い**（全37項目を確認） |

Profileに無い以上、`Seller`型へは置けない。置けば**Profileから作った`Seller`が常に`None`を持つ**
ことになり、「取得元によって埋まったり埋まらなかったりするField」を型が抱える。

##### 欠落を`False`にしない

Fork側の型は`Optional[bool]`である。**「Mercariが何も言っていない」と「Mercariがそうでないと
言った」は別の答え**であり、区別を落とすと、Mercariが何も言っていない出品者について
Mercariが活動中と言ったことにしてしまう。Adapterは真偽値以外を`None`にする——
`"false"`は真、`0`は偽と評価されるため、型を見ずに通すと形の変化がそのまま答えになる。

#### 規則

- **`assumed`の主張を画面へ出さない。** 出す必要が生じたら、先に観測して`observed`へ上げる
- **`unverifiable`を画面へ出すときは、限界を画面に書く。** 塞げないものを黙って出さない
- 主張を新設・改名するときは、根拠を1行で書く。**書けないなら元の名前に近い名前を使う**
  （`num_sell_items` → `sell_item_count`なら何も主張していない）
- 値を突き合わせていないものを`observed`と書かない。**要素の存在は値の一致ではない**

#### `created_at`が`unverifiable`である理由（2026-09-01観測）

実測は[`created`と`updated`の追加観測結果](../../poc/mercapi/timestamp-result.md)。

**分かったこと。**

| 主張 | 状態 | 根拠 |
|---|---|---|
| 編集・再出品で`created`は動かない | **確定** | 検索347件のうち**254件が`updated > created`**。更新されても`created`はそのまま。最大182日の差。矛盾例0件 |
| 商品ページは`created`を表示しない | **確定** | ページの経過時間は**`updated`と3 / 3で一致**。`created`が10日前・2日前の標本でもページは`updated`を表示した |
| `created`は**出品日時**である | **`unverifiable`** | 商品ページに照合相手が存在しない |

**`created`は動かない安定した「始まりの時刻」**であることまでは実測で言える。
それを「出品日時」と呼ぶ最後の一歩だけが、照合相手が無いため確認できない。

`updated`は**商品ページが商品の経過時間として表示している値**であり`observed`。
ただしページ側にラベル文字が無いため、「Mercariが更新日と呼んでいる」ことは確認していない。

#### `updated_at`を持つ理由

**検証できている唯一の時刻軸である。** `created_at`が`unverifiable`なのに対し、
`updated_at`は商品ページの表示と一致することを確認している。

| | `created_at` | `updated_at` |
|---|---|---|
| 意味の根拠 | **`unverifiable`** | **`observed`** |
| 商品ページ | 表示されない | **表示されている** |
| 動くか | 編集されても動かない（345件中253件で確認） | 編集で動く |
| 答える問い | いつ出品されたか | **いつ最後に触られたか** |

MVPは両方を並び替えの軸にする（[MVP仕様 §5.5](../product/mvp-spec.md)）。
「更新が古い順」は**長く触られていない出品**を前に出すため、
[Product目的](../product/concept.md)の「放置された引退品」に最も近い。

必須Fieldとする。3経路すべてのForkモデルが必須で宣言しており、**`updated`を持たない商品は
そもそも届かない。** 任意にすると、観測されたことのない状態を型が表現することになる。

> **表示ラベルの注意。** 商品ページの経過時間には**ラベル文字が無い**。
> 「Mercariが更新日と呼んでいる」ことは確認していないため、画面では
> 「Mercariの商品ページに表示される経過時間」のように、**確認できた事実だけを書く。**

#### 画面への影響

**同じ商品に対して、Mercariは`updated`基準の経過時間を、Card Diggerは`created`基準の
経過日数を表示する。** 両者は食い違う（観測例では「1時間前」と「10日前」）。

これは誤りではなく、**別の時刻を見ている**ことによる。利用者が両方の画面を見たときに
混乱しないよう、[MVP仕様](../product/mvp-spec.md)へ限界の表示を要件として入れる。

#### 現在`assumed`の1件

| Field | 何が未確認か | いつ潰すか |
|---|---|---|
| `rating` | 星評価のスケール（5段階か否か） | Seller画面へ評価を出す前 |

L4では`5.0`が返っていたが、取りうる範囲を観測していない。100点満点なら「5.0」は
極端に低い評価を意味する。**`assumed`なので、画面へ出さない。**

**画面には`rating_breakdown`を出す**（[MVP仕様 §6.2](../product/mvp-spec.md#評価は件数の内訳で出す2026-09-03決定)）。
件数は尺度を持たないため、この`assumed`を塞がずに評価を表示できる。
**`rating`を出す必要が生じたときだけ、先に観測して`observed`へ上げる。**

### 6.4 `listed_item_count`は販売件数ではない

Profileの`num_sell_items`を`Seller.listed_item_count`へ写す。**出品件数であって、
累計販売件数ではない。**

2026-09-01の[追加観測](../../poc/mercapi/open-questions-result.md)で次を確認した。

| 根拠 | 内容 |
|---|---|
| 件数の一致 | 全状態が1ページで終端したSellerで、`on_sale` 1 + `trading` 3 + `sold_out` 25 = **29**が`num_sell_items`と完全一致した。他の解釈はいずれも不一致 |
| 評価件数との矛盾 | **評価247件に対し`num_sell_items`が29**のSellerがいた。累計販売が29なら247の評価は成立しない |
| 代替Fieldの不在 | Profileの`num_`系Fieldは`num_ratings` / `num_sell_items` / `num_ticket`の3つだけ。**`num_sold_items`は存在しない** |

> **2026-09-01の訂正。** この型は当初`total_sales_count`という名前で、
> [MVP実装仕様](../product/mvp-spec.md)も「累計販売件数」として表示する想定だった。
> 実測と食い違うため改名した。旧名のままなら、評価247件のSellerに
> 「累計販売件数 29」と表示していた。

**Profileから累計販売件数は取得できない。** 販売実績を示す必要が出た場合は、
取得できた`sold_out`の件数を「取得範囲内の売却済み件数」として示す。Profileの累計値を
販売件数として読み替えない。

判定できたSellerは1人であり、「全状態の合計と一致する」ことの標本は足りない。
**「販売件数ではない」ことは確定、「出品件数である」ことは有力**という状態で記録する。

## 7. Marketplace Interface

```python
class MarketplacePort(Protocol):
    async def search_items_page(
        self,
        keyword: str,
        cursor: str | None = None,
    ) -> SearchPage:
        ...

    async def get_item(self, item_id: str) -> MarketplaceItem:
        ...

    async def get_seller(self, seller_id: str) -> Seller:
        ...

    async def get_seller_items_page(
        self,
        seller_id: str,
        status: ListingStatus,
        cursor: str | None = None,
    ) -> SellerItemsPage:
        ...
```

### Interface規則

- `search_items_page`はMVPでは`on_sale`、カテゴリ・価格指定なし、
  `SORT_CREATED_TIME / ORDER_ASC`固定で要求する
- 検索は`withAuction=true`で通常出品とAuctionをまとめて取得し、
  販売形式Filterのための追加Requestは行わない
- `SORT_CREATED_TIME / ORDER_ASC`は検証条件を維持するため送るだけで、順序保証には使わない
- AdapterはServer側の古い順を保証しない
- `get_item`は画面から明示的に必要になった場合だけ呼ぶ
- Seller商品は`on_sale`と`sold_out`を一つずつ指定する
- Seller商品は`with_auction=true`で取得する。省略すると`auction_info`が返らず判定できない
- `UNKNOWN`はRequest Parameterとして使用できない
- Applicationへ`mercapi` Object、生Response、DPoP、Header、Cookieを返さない

## 8. 収集Policy

複数ページを集める処理はAdapterではなくUse case層へ置く。すべて同時実行数1、外部Requestの
開始間隔2秒以上とする。

### 8.1 商品検索

| 項目 | MVP値 |
|---|---:|
| 販売状態 | `on_sale`固定 |
| 並び | `SORT_CREATED_TIME` + `ORDER_DESC`（**検索が受け付ける唯一の時間順**） |
| 価格帯 | `price_min` / `price_max`をMercariへ渡す。**取得範囲を変える** |
| 古い商品の暫定基準 | 365日以上（**件数の報告にだけ使う**） |
| 最低目標 | **置かない**（[MVP仕様 §5.3](../product/mvp-spec.md#最低目標を外した2026-09-03)） |
| 最大ページ | 10ページ |
| 最大ユニーク商品 | 1,000件 |
| 最大経過時間 | 30秒 |
| ページ間重複 | 商品IDで除外し、件数を記録 |

次のいずれかで停止する。

1. 次ページがない
2. 10ページへ到達した
3. 1,000ユニーク商品へ到達した
4. 30秒へ到達した
5. 安全停止または取得Errorが発生した

**2026-09-03に「最低目標を満たした」を外した。** `created`で測っていたため、
`updated`を探すというProductの目的と軸が食い違っていた。理由は
[MVP仕様 §5.3](../product/mvp-spec.md#最低目標を外した2026-09-03)。

#### 並びは`ORDER_DESC`しか送らない（2026-09-03）

以前は`ORDER_ASC`を送っていたが、**`mercapi`の`_allowed_sorting`に無い組み合わせ**であり、
公式アプリも送らない。Mercariは`order`を無視して既定の並びを返すため、
**要求している並びと実際に得ている並びが食い違っていた。** 実態に合わせた。

なお`SORT_CREATED_TIME`という名前に反し、返る並びは`updated`の降順に傾いている
（隣接ペアの降順破れが`updated` 21%、`created` 40%。
[観測結果](../../poc/mercapi/timestamp-result.md)）。
**Mercariの「新しい順」は`updated`で並んでいる。**

#### 価格帯はMercariへ渡す（2026-09-03）

`price_min` / `price_max`は**並べ替えとページングの前に**適用されるため、
帯を狭めると同じ予算がより小さな母集団の上に落ちる。
**`updated`の降順を逆にできない以上、奥へ届く手段はこれだけである。**
理由は[MVP仕様 §5.3](../product/mvp-spec.md#価格帯だけが到達範囲を変える2026-09-03)。

`None`はForkが0へ畳み、APIでは「下限なし」を意味する。

検索結果には必ず、取得ページ数、取得ユニーク件数、重複件数、最古・最新日時、取得時刻、
365日以上の商品数、停止理由、Server側の完全な古い順ではないことを付与する。
掲載日と販売形式のFilterは取得後にFrontendが適用し、この収集Policyの停止条件には使用しない。

#### 並び替えはApplication側で行う（2026-09-01明記）

**Server側の並び順を信用しない。** Adapterは`sort_by` / `sort_order`を送るが、
返ってきた順序をそのまま画面へ出さず、**取得し終えた集合をApplication側で並べ替える。**

##### なぜ送るのに信用しないのか

Adapterが送っているのは[共通検証プロトコル](poc-validation.md)の条件を保つためであり、
順序を当てにしているからではない。実測は次のとおり（[観測結果](../../poc/mercapi/timestamp-result.md)）。

| 送った順序 | `created`の並び | `updated`の並び |
|---|---|---|
| `CREATED_TIME` + `ASC`（古い順） | **順不同**（破れ60%） | 部分的に降順（破れ21%） |
| `CREATED_TIME` + `DESC`（新しい順） | **順不同**（破れ60%） | 部分的に降順（破れ21%） |

- **`order`パラメータは結果に影響していない。** ASCとDESCで並びが完全に一致した
- **Mercariに「古い順」という選択肢が無い。** `mercapi`の`_allowed_sorting`は
  おすすめ順・新しい順・価格順・いいね順の5組だけで、`CREATED_TIME + ASC`を含まない
- `SortBy.SORT_CREATED_TIME`の定義自体に`# Correct order is not guaranteed`とある

##### 何を保証し、何を保証しないか

| | |
|---|---|
| 保証する | **取得した範囲の中での**並び替え |
| 保証しない | Mercari全体での古い順。取得範囲外に、より古い商品が存在しうる |

[MVP仕様 §5](../product/mvp-spec.md)の`created_asc` / `created_desc` / `updated_asc` / `updated_desc` / `price_asc` / `price_desc`は
すべてこの範囲内の並び替えである。**画面にもその旨を表示する。**

##### この方針を変えない理由

Mercariが将来「古い順」を提供したとしても、次の3つが残るため並び替えはApplication側に置く。

1. **ページをまたいで重複排除している。** 除外後の並びはServerの並びではない
2. **MVPは4種類の並び替えを提供する。** Mercariが持たない順序（古い順）を含む
3. **順序が保証されないことを実測している。** 保証の無いものを画面の前提にしない

最大件数に達するPageが上限を超える場合は、Response順の先頭から上限までを採用し、残りを
破棄した件数もMetadataへ記録する。Seller商品でも同じ規則を使う。

### 8.2 Seller商品

`on_sale`と`sold_out`を別々に収集する。

| 項目 | 1状態あたりのMVP値 |
|---|---:|
| Page size | 30件 |
| 最大ページ | 5ページ |
| 最大ユニーク商品 | 100件 |
| 最大経過時間 | 30秒 |
| ページ間重複 | 商品IDで除外し、件数を記録 |

次のいずれかで停止する。

1. `has_next=false`
2. 5ページへ到達した
3. 100ユニーク商品へ到達した
4. 30秒へ到達した
5. 安全停止または取得Errorが発生した

「Sellerの全商品」「全出品に占める比率」とは表現せず、状態ごとの取得数と打ち切り有無を返す。

#### `trading`の扱い（2026-09-01決定）

出品状態は`on_sale` / `trading`（取引中）/ `sold_out`の3つある。**要求するかどうかと、
返ってきた値をどう扱うかは別の決定**であり、次のとおり分けて決める。

| 決定 | 内容 | 理由 |
|---|---|---|
| **要求** | **`trading`を要求しない** | [MVP実装仕様](../product/mvp-spec.md)が販売中と売却済みの2画面と定めており、表示先が無い。1 Sellerあたり最大5ページ増える |
| **正規化** | **`trading`を`trading`のまま保持する。`sold_out`や`unknown`へ寄せない** | 下記 |

要求しているのは**Application層の`analyze_seller`**である。AdapterもForkも3状態すべてを
要求でき、`ListingStatus.TRADING`は`_REQUESTABLE_STATUSES`に含まれる。
**能力の制約ではなく、収集Policyの選択である。**

##### 要求していないのに、正規化で潰さない理由

要求していない状態でも、**商品詳細（`get_item`）には状態Filterが存在しない。**

| 経路 | 状態Filter | `trading`が返る可能性 |
|---|---|---|
| 検索 | `status=on_sale`を送る | 低い（未確認） |
| Seller商品一覧 | 要求した状態だけが返る（[0-F-1 §6.1](../../poc/mercapi/auction-result.md)で確認） | 低い |
| **商品詳細** | **無し。IDで引くだけ** | **ある** |

検索で見つけた商品を数分後に詳細取得する間に、その商品が購入されれば`trading`になる。
**`trading`はCard Diggerへ実際に到達しうる。**

そのとき`sold_out`へ丸めると、次の2つを取り違える。

```text
sold_out   取引完了。基本的に元へ戻らない
trading    取引中。キャンセルや支払い期限切れで on_sale へ戻りうる（未確定の状態）
```

Seller Knowledgeを「売れた率」で測る場合、未確定の`trading`を売却済みへ数えると
**過大評価**になる。また[Test運用規約 §2.3](../development/test-policy.md#23-静かな失敗の例)は
「`trading`を`unknown`や`sold_out`へ変換する」を**静かな失敗の例**として挙げている。

丸めても**Requestは1件も減らない。** 検知能力だけを失う選択になるため、行わない。

##### 後から要求する場合に必要な作業

**要求しないという決定は、いつでも覆せる。** Fork・Adapter・Domainは`trading`を扱える状態に
あり、必要な変更は**Application層に閉じる。** Fork変更も依存SHA更新も不要である。

| | 対象 | 状況 |
|---|---|---|
| ✅ | `ListingStatus.TRADING` | 定義済み |
| ✅ | `_REQUESTABLE_STATUSES` | `TRADING`を含む。Adapterは要求を受け付ける |
| ✅ | `listing_status()`の正規化 | `trading` / `ITEM_STATUS_TRADING`の両表記に対応済み。L2 Testで固定 |
| ✅ | Forkの`items_page(statuses=...)` | `SELLER_ITEM_STATUSES`に`"trading"`を含む |
| ⬜ | `Operation.SELLER_TRADING` | **未定義。** 下記 |
| ⬜ | `_seller_operation()`の分岐 | `SOLD_OUT`以外を`SELLER_ON_SALE`にしている |
| ⬜ | `SellerAnalysis.trading` | Fieldの追加 |
| ⬜ | `analyze_seller`の収集呼び出し | 3状態目の追加と、失敗時の`_not_collected` |
| ⬜ | Test | 収集とContractの追加 |
| ⬜ | [MVP実装仕様](../product/mvp-spec.md) | 表示要件の変更 |
| ⬜ | Request予算 | 1 Sellerあたり最大5ページ増える |

**唯一の注意点は`Operation`である。** `SELLER_TRADING`が無いため、いま`trading`を要求すると
**その失敗が`seller_on_sale`として記録される。** 要求側を実装する際は、Error Codeの
記録先を先に足す。要求していない現在は発生しない。

##### この決定を見直す契機

- 画面へ「取引中」を表示する要件が出たとき（**そのとき初めて要求側を実装する**）
- Seller Knowledgeの特徴量で「売れた」の定義に`trading`を含めると決めたとき（Phase 1-4）
- 終了済みAuctionの調査で`trading`を観測する必要が出たとき（単発Probe。収集Policyは変えない）

なお**`trading`の実データはまだ1件も観測していない。** `trading`を扱うFixtureは
`derived`であり、観測から起こしたものではない。

### 8.3 停止理由

```python
class CollectionStopReason(str, Enum):
    TARGET_REACHED = "target_reached"
    END_OF_RESULTS = "end_of_results"
    MAX_PAGES = "max_pages"
    MAX_ITEMS = "max_items"
    MAX_DURATION = "max_duration"
    ERROR = "error"
    SAFETY_STOP = "safety_stop"
```

取得結果が途中まで存在しても、`ERROR`または`SAFETY_STOP`を成功完了として隠さない。UIが
部分結果であることを表示できるMetadataを返す。

## 9. Errorと再試行

共通Error Codeは次に固定する。

| Code | 例 | 自動再試行 |
|---|---|---|
| `invalid_input` | 空Keyword、不正Status | しない |
| `unauthorized_401` | HTTP 401 | しない |
| `forbidden_403` | HTTP 403 | しない |
| `rate_limited_429` | HTTP 429 | しない |
| `not_found_404` | 商品・Sellerなし | しない |
| `timeout` | 規定時間超過 | 1回まで |
| `network_error` | 一時的な通信失敗 | 1回まで |
| `upstream_5xx` | Mercari側5xx | 1回まで |
| `parse_error` | 必須Field、Cursor不整合 | しない |
| `challenge` | CAPTCHA / Challenge | しない |
| `unsupported` | 未対応操作 | しない |
| `unknown` | 分類不能 | しない |

再試行は同じ操作を2秒以上空けて1回だけ行い、回数を結果へ残す。再試行と待機時間も最大経過時間へ
含める。401 / 403 / 429 / Challengeが
主要操作で合計3回連続した場合は、その実行の以後の外部アクセスを停止する。認証回避、CAPTCHA回避、
Proxy切替、複数Accountによる回避は行わない。

## 10. Test方針

この節は**何をテストするか**を定義する。Framework、配置、Fixtureの作り方、実行時期、完了判定は
[Test運用規約](../development/test-policy.md)を正本とする。

| 層 | 節 | 外部通信 | 実行 |
|---|---|:---:|---|
| L1 ForkのUnit Test | 10.1 | なし | 変更ごと |
| L2 AdapterのUnit Test | 10.2 | なし | 変更ごと |
| L3 Contract Test | 10.2 | なし | 変更ごと |
| L4 ライブ受入検証 | 10.3 | あり | 手動・低頻度。自動Test Suiteへ入れない |

### 10.1 ForkのUnit Test

- `status=on_sale`、`status=sold_out`を個別送信する
- 複数状態をカンマ区切りへ変換する
- 2ページ目で前ページ末尾`pager_id`を送信する
- `meta.has_next=false`でCursorを返さない
- 空Response + `has_next=false`を正常終端にする
- 空Response + `has_next=true`をParse Errorにする
- 末尾`pager_id`欠落をParse Errorにする
- 既存`items(profile_id)`の互換性を維持する

### 10.2 AdapterのUnit / Contract Test

- `mercapi`型がDomain型へ正規化される
- `trading`を`unknown`や`sold_out`へ変換しない
- 通常出品、Auction、未知形状をそれぞれ`SaleFormat`へ変換する
- 検索の`auction.id`が空文字でもAUCTIONと判定する
- 検索・商品詳細・Seller商品一覧の3形状を同じ`SaleFormat`へ正規化する
- 文字列の`highestBid`を整数の`price_yen`へ変換する
- naive `datetime`から元の瞬間を復元し、Timezone付きで返す（Process Timezoneに依存しない）
- Auctionの取得時点価格を正規化し、開始価格や確定価格へ読み替えない
- 検索とSeller商品で同じ販売形式Mappingを使用する
- 必須Field欠落でParse Errorになる
- ForkのPrivate Memberを使わない
- 最大ページ・件数・時間・重複の各停止理由を判定できる
- Error分類と1回だけの再試行を確認する
- 3回連続の安全Errorで停止する
- Mock Adapterが同じ`MarketplacePort` Contractを満たす

### 10.3 ライブ受入検証

共通検証プロトコルと同じ低頻度条件で実施する。

- 検索5回の成功率80%以上。100%を優先する
- 必須商品Field各100%
- Auction追加検証が合格し、販売形式の判定が標本各100%一致する
- Auction価格Fieldが商品ページの取得時点価格と95%以上一致する
- 商品詳細20件のコンディション・いいね各95%以上
- Seller Profile 10人の名前90%以上
- 最大10 Sellerの`on_sale` / `sold_out`で、状態ごとに2ページ目取得または1ページ終端
- ページ間Cursor一致、重複数、終端理由を記録する
- 401 / 403 / 429 / Challengeを回避せず記録する

Seller数が10人に満たない場合は、取得できた全Sellerを母数とし、その事実を結果へ記載する。

実施結果は[ライブ受入検証結果](phase-0-f-live-acceptance-result.md)を正本とする。
2026-09-01に**2回実施**し、いずれも10項目すべて合格した。**判定は第2回を採用する。**

第1回の後に測定側の弱点（標本の偏り、内訳の未記録、価格照合が包含判定）が見つかったため、
標本を販売形式ごとの枠へ変更し、内訳の記録と価格要素との厳密比較を加えて再実行した。
**合格基準・実施条件・標本サイズは変更していない。** 差分は
[結果 §12.1](phase-0-f-live-acceptance-result.md#121-何を変えどの弱点が解消したか)。

## 11. Phase 0-F完了条件

- [x] 管理下のForkが作成され、ライセンスと著作権表示が維持されている
- [x] ForkのSellerページングPublic APIとUnit Testが完成している
- [x] Card DiggerがForkのTest済みcommit SHAへ固定されている
- [x] Auction追加検証の結果文書が完成し、合否とMappingが仕様へ反映されている
- [x] Domain型と`MarketplacePort`が定義されている
- [x] Mercari AdapterとMock Adapterが実装されている
- [x] 収集Policy、重複排除、停止理由、安全停止が実装されている
- [x] ForkとAdapterの全自動Test（L1〜L3）が成功している
- [x] Fixtureが[Test運用規約 §5](../development/test-policy.md#5-fixture規約)の匿名化規則を満たしている
- [x] 時計、待機、Fork Clientが注入可能になっている
- [x] ライブ受入検証（L4）が合格し、結果文書が追加されている
- [x] Application / Domain層に`mercapi`型とPrivate Memberが漏れていない
- [x] [MVP実装仕様](../product/mvp-spec.md)から利用できる状態になっている

## 12. Phase 0-Fで実装しないもの

- Web UIとHTTP API
- Databaseと永続Cache
- 定期実行・Background Job
- Auctionの入札・購入・自動更新・Countdown・終了通知
- Playwright Fallback
- Seller Knowledge計算
- 画像本体の保存・Proxy
- Mercari以外のMarketplace
