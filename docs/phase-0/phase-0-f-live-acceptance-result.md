# Phase 0-F — ライブ受入検証（L4）結果

## 判定

**合格。** [合格基準](phase-0-f-adapter-spec.md#103-ライブ受入検証)の10項目すべてを満たした。

- 検索5回の成功率 **5 / 5（100%）**
- 必須商品Field **1185 / 1185（100%）**
- 商品詳細のコンディション・いいね **各20 / 20（100%）**
- Seller Profileの名前 **10 / 10（100%）**
- `on_sale` / `sold_out`のページング **各10 / 10（100%）**
- 販売形式の判定 **検索 vs 商品詳細 20 / 20、検索 vs Seller一覧 24 / 24（各100%）**
- Auction価格 vs 商品ページの取得時点価格 **10 / 10（100%）**
- 401 / 403 / 429 / Challenge **0件**（API Request 123件はすべてHTTP 200）
- 安全停止 **未発動**、自動再試行 **0回**

条件・手順・合格基準の正本は[ライブ受入検証実施計画](phase-0-f-live-acceptance.md)、
記録規約の正本は[Test運用規約 §9](../development/test-policy.md#9-ライブ受入検証l4の実施規約)とする。

この文書は実測の記録である。**判定はGreen / RedではなくMarkdownとする**という規約に従い、
率・件数・停止理由・Error Codeだけを残し、Seller名・商品Title・商品URL・商品ID・生Responseは
含めない。不一致商品のIDはGit管理外の`artifacts/`にだけ残る（本実行では0件）。

---

## 1. 実行環境

| 項目 | Step 1（`src/backend`） | Step 2（`poc/mercapi`） |
|---|---|---|
| 実行開始 | `2026-09-01T05:09:45Z` | `2026-09-01T05:14:18Z` |
| 実行終了 | `2026-09-01T05:12:50Z` | `2026-09-01T05:16:29Z` |
| 所要時間 | 3分04秒 | 2分11秒 |
| Runtime | Python 3.11.15 | Python 3.11.15 |
| OS / Architecture | `macOS-26.5-arm64-arm-64bit` | `macOS-26.5-arm64-arm-64bit` |
| 対象`mercapi` commit | Fork `b3bdec98d7ed56d0e3f1270f9852a2a170c5896c` | upstream `20ba68fd42677997c4c91b4e4eb17c1e7e387efa` |
| Card Digger commit | `c49ba1b48bc2db7385612212468f51dfbe1ebbaa` | `c49ba1b48bc2db7385612212468f51dfbe1ebbaa` |
| Command | `uv run python scripts/live_acceptance.py --confirm` | `poc/mercapi/.venv/bin/python poc/mercapi/auction_probe.py` |
| Browser | 使用しない | Google Chrome（Playwright 1.55.0, `channel="chrome"`） |
| 認証状態 | 匿名。Login / 永続Cookie / 明示Token / Proxyなし | 同左 |
| 検索Keyword | `ポケカ 引退品` | `ポケカ 引退品` |

Step 2が`src/backend`ではなくPoC側で、かつ`MercariAdapter`を通らない理由は
[実施計画 §4](phase-0-f-live-acceptance.md#4-なぜstep-2をadapter経由で行わないのか)にある。
本実行はその分離のまま実施した。

### 遵守した実施条件

| 条件 | 要求 | Step 1の実測 | Step 2の実測 |
|---|---|---|---|
| 同時実行数 | 1 | 1（`RequestGate`が直列化） | 1（`RequestLimiter`が直列化） |
| Request開始間隔 | 2秒以上 | 2.0秒以上 | 2.0秒以上 |
| 自動再試行 | なし | **0回**（`RequestGate(max_retries=0)`） | **0回** |
| 安全停止 | 3回連続で停止 | 未発動（連続拒否0回） | 未発動 |
| 回避行為 | 行わない | 行っていない | 行っていない |

### 実行前チェックリスト（[実施計画 §8](phase-0-f-live-acceptance.md#8-実行前チェックリスト)）

| 項目 | 結果 |
|---|---|
| `uv run pytest tests`（L2 / L3） | **214 passed / 0 failed** |
| Forkの`pytest`（L1） | **94 passed / 0 failed** |
| 依存が固定Fork commit SHAを指している | `pyproject.toml` / `uv.lock` / `direct_url.json` / Fork HEADの4点が`b3bdec98`で一致 |
| `--plan`でRequest予算を確認した | 最大180 Request、間隔2秒として最短6分 |
| 自動再試行なしで実行する準備 | `--confirm`実行時に`max_retries=0`で構築される |
| 個人情報と生Responseを書かない準備 | 本文書は率・件数のみ。実測値はGit管理外の`artifacts/`へ |

---

## 2. Request数

| 対象 | 予算（`--plan`） | 実測 |
|---|---:|---:|
| Step 1 検索 | 最大50 | **10**（5試行 × 2ページ） |
| Step 1 商品詳細 | 20 | **20** |
| Step 1 Seller Profile | 10 | **10** |
| Step 1 Seller商品一覧 | 最大100 | **53** |
| Step 1 小計 | 最大180 | **93** |
| Step 2 API | — | **30** |
| Step 2 商品ページ（Browser） | — | **20** |
| 合計（API） | — | **123** |

予算どおりにならなかったのは、検索が2ページで最低目標に達し、Sellerの多くが1ページで
終端したためである。

---

## 3. 合格基準との対応

| # | 基準 | 標本 | 実測 | 判定 |
|---|---|---:|---|:---:|
| 1 | 検索5回の成功率80%以上（100%を優先） | 5回 | 5 / 5（**100%**） | 合格 |
| 2 | 必須商品Field各100% | 1185件 | 1185 / 1185（**100%**） | 合格 |
| 3 | 商品詳細のコンディション95%以上 | 20件 | 20 / 20（**100%**） | 合格 |
| 4 | 商品詳細のいいね95%以上 | 20件 | 20 / 20（**100%**） | 合格 |
| 5 | Seller Profileの名前90%以上 | 10人 | 10 / 10（**100%**） | 合格 |
| 6 | `on_sale`で2ページ目取得または1ページ終端 | 10人 | 10 / 10（**100%**） | 合格 |
| 7 | `sold_out`で2ページ目取得または1ページ終端 | 10人 | 10 / 10（**100%**） | 合格 |
| 8 | 販売形式の判定が標本各100%一致 | 20件 / 24件 | 20 / 20、24 / 24（**各100%**） | 合格 |
| 9 | Auction価格が商品ページの取得時点価格と95%以上一致 | 10件 | 10 / 10（**100%**） | 合格 |
| 10 | 401 / 403 / 429 / Challengeを回避せず記録する | 全Request | **0件**（API 123件すべて200） | 合格 |

Seller数は10人に達したため、母数の読み替えは行っていない。

### 基準2の読み方

Adapterは必須Fieldが欠けた時点で操作を失敗させるため、
[実施計画 §5](phase-0-f-live-acceptance.md#基準2について)のとおり、**成功した検索の取得率は
構造上100%になる。** 本実行の100%は「Adapterが黙って除外へ変わっていない」ことの記録であり、
Mercariが常に全Fieldを返すことの証明ではない。

### 基準5の付随観測

Profileは名前だけでなく評価と累計販売件数も測った。いずれも合格基準の対象外だが記録する。

| 項目 | 実測 |
|---|---|
| 名前 | 10 / 10（100%） |
| 評価（`star_rating_score`） | 10 / 10（100%） |
| 累計販売件数（`num_sell_items`） | 10 / 10（100%） |

---

## 4. 検索（Step 1）

### 4.1 各試行

| 試行 | ページ | ユニーク | 重複 | 上限破棄 | 365日以上 | 停止理由 | 部分 |
|---:|---:|---:|---:|---:|---:|---|---|
| 1 | 2 | 237 | 0 | 0 | 1 | `target_reached` | — |
| 2 | 2 | 237 | 0 | 0 | 1 | `target_reached` | — |
| 3 | 2 | 237 | 0 | 0 | 1 | `target_reached` | — |
| 4 | 2 | 237 | 0 | 0 | 1 | `target_reached` | — |
| 5 | 2 | 237 | 0 | 0 | 1 | `target_reached` | — |

5試行すべてが同一の件数・同一の期間（最古`2025-05-29T05:32:33Z`、最新`2026-09-01T05:00:34Z`）を
返した。**ページ間の重複は0件**で、Cursorの引き継ぎに欠落・巻き戻りはなかった。

- 停止理由はすべて`target_reached`（100件以上 かつ 365日以上が1件以上）
- `reached_end`は`false`。`truncated`は`true`。**これはMercariの全件ではなく、この実行が
  到達した範囲である**と`CollectionMeta`が申告している
- `partial`は5試行とも`false`。Errorによる打ち切りは発生していない

### 4.2 販売形式の内訳

| 販売形式 | 5試行合計 | 1試行あたり |
|---|---:|---:|
| `fixed_price` | 1070 | 214 |
| `auction` | 115 | 23 |
| `unknown` | **0** | 0 |

未知形状は1件も観測されなかった。[Auction追加検証](../../poc/mercapi/auction-result.md#12-再検証が必要になる条件)と
同じく、**未知形状と終了済みAuctionは「合格」ではなく「未観測」として残す。**

### 4.3 並び順（合格基準外の観測）

`SORT_CREATED_TIME` + `ORDER_ASC`はForkが警告を出すとおり公式Web Appでは非対応で、
本実行でも古い順にはならなかった。最古（2025-05-29）と最新（2026-09-01）が同じ2ページに
混在しており、Phase 0-Bの所見が現在も成立している。

Adapterは応答の並び順を信頼せず、並べ替えをApplication側で行う設計になっているため、
**この事実は仕様どおりであり不合格要因ではない。**

---

## 5. 商品詳細（Step 1）

| 項目 | 実測 |
|---|---|
| 標本 | 20件 |
| 取得成功 | 20 / 20（100%） |
| コンディション | 20 / 20（100%） |
| いいね | 20 / 20（100%） |
| 販売形式の一致（検索 vs 商品詳細） | 20 / 20（100%） |
| 価格の一致（検索 vs 商品詳細） | 20 / 20（100%） |
| 不一致として記録した商品 | 0件 |

### 標本の偏り（限界として記録する）

Runnerは「未知形状 → Auction → 通常出品」の順に標本を選ぶ。1試行の検索結果に含まれる
Auctionは23件で20件を上回るため、**この20件はすべてAuctionだった。**

したがって本実行の「検索 vs 商品詳細」100%は、**Auctionについての一致であり、通常出品に
ついては検証していない。** 通常出品の一致はStep 2で別に10 / 10を確認している（§6）。

Runnerは標本の販売形式内訳を`artifacts/`へ記録していない。上記は選定規則と検索内訳からの
導出であり、直接の記録ではない。次回以降のためにRunnerへ内訳の記録を追加する価値がある
（[§9](#9-次に見直す点)）。

---

## 6. Auction価格と商品ページの照合（Step 2）

Browserで商品ページを開き、`mercapi`の生の値と突き合わせた。**Adapterを通していない。**
この照合が答える問いは「`highest_bid`は買い手が画面で見る現在価格を意味するのか」の1点に限る。

### 6.1 標本

| 対象 | 最低標本 | 実測 |
|---|---:|---:|
| 検索のユニーク商品 | — | 118件 |
| Auction | 10件 | **10件** |
| 通常出品 | 10件 | **10件** |
| 未知形状 | — | **0件** |
| 商品ページ照合 | — | 20件（すべてHTTP 200） |

### 6.2 価格の一致

| 指標 | 実測 |
|---|---:|
| 現在価格の一致 | **10 / 10（100%）** |
| 比較中の価格変動 | 0件 |

### 6.3 標本の入札状況

[実施計画 §4.3](phase-0-f-live-acceptance.md#43-adapterの検査は実測より固定fixtureの方が強い)は、
未入札のAuctionでは開始価格と現在価格が一致するため、Field選択の誤りが実測では隠れると指摘する。
本実行の内訳は次のとおり。

| 状態 | 件数 | `initial_price`と`highest_bid` |
|---|---:|---|
| 未入札（`STATE_NO_BID` / `total_bids=0`） | **5** | 同じ値 |
| 入札済み（`STATE_ONGOING`） | **5** | **乖離する** |

**乖離した5件でも商品ページと一致した。** 0-F-1（未入札7 / 入札済み3）より入札済みの割合が
高く、この照合としては前回より強い標本である。

ただしこれは基準9を満たす根拠であって、[実施計画 §4.3](phase-0-f-live-acceptance.md#43-adapterの検査は実測より固定fixtureの方が強い)の
判断を覆すものではない。**「AdapterがどのFieldを選ぶか」の検査はL2のFixture Testが担当する**
という分担は変えない。

### 6.4 販売形式の判定（商品ページを正とする）

| 比較 | 一致 | 率 |
|---|---:|---:|
| 検索判定 == 商品ページ（Auction標本） | 10 / 10 | 100% |
| 検索判定 == 商品ページ（通常出品標本） | 10 / 10 | 100% |
| 検索判定 == 商品詳細判定 | 20 / 20 | 100% |

「`入札`の表示があるか」と「`入札`があり`購入手続きへ`がない」の両規則で同じ結果になった。

### 6.5 3経路のField形状

0-F-1で記録した3経路の差（検索は`auction`／camelCase／文字列、商品詳細とSeller一覧は
`auction_info`／snake_case）は本実行でも変化していなかった。

| 経路 | 観測したキー構成 |
|---|---|
| 検索 | `bidDeadline,highestBid,id,initialPrice,totalBid` |
| 商品詳細 | `auction_type,expected_end_time,highest_bid,id,initial_price,start_time,state,total_bids` |
| Seller一覧（`with_auction=true`） | `bid_deadline,highest_bid,id,initial_price,total_bid` |

`with_auction`を送らない場合、Seller一覧は`auction_info`を1件も返さない点も再現した。
**[再検証が必要になる条件](../../poc/mercapi/auction-result.md#12-再検証が必要になる条件)は
いずれも発生していない。**

---

## 7. Seller（Step 1）

### 7.1 ページング

Seller IDは記録しない。表の番号は取得順の連番である。

| Seller | `on_sale`ページ | 件数 | 終端 | 停止理由 | `sold_out`ページ | 件数 | 終端 | 停止理由 |
|---:|---:|---:|:---:|---|---:|---:|:---:|---|
| 1 | 2 | 38 | ○ | `end_of_results` | 4 | 100 | — | `max_items` |
| 2 | 4 | 100 | — | `max_items` | 4 | 100 | — | `max_items` |
| 3 | 4 | 100 | ○ | `end_of_results` | 1 | 20 | ○ | `end_of_results` |
| 4 | 1 | 6 | ○ | `end_of_results` | 1 | 1 | ○ | `end_of_results` |
| 5 | 1 | 3 | ○ | `end_of_results` | 4 | 100 | ○ | `end_of_results` |
| 6 | 3 | 90 | ○ | `end_of_results` | 4 | 100 | — | `max_items` |
| 7 | 1 | 6 | ○ | `end_of_results` | 1 | 21 | ○ | `end_of_results` |
| 8 | 1 | 3 | ○ | `end_of_results` | 1 | 0 | ○ | `end_of_results` |
| 9 | 4 | 100 | — | `max_items` | 4 | 100 | — | `max_items` |
| 10 | 4 | 100 | — | `max_items` | 4 | 100 | — | `max_items` |

基準6・7は「2ページ目を取得できたか、または1ページで終端したか」を問う。

| 状態 | 2ページ目を取得 | 1ページで終端 | 基準を満たさない | 率 |
|---|---:|---:|---:|---:|
| `on_sale` | 6人 | 4人 | **0人** | 10 / 10（100%） |
| `sold_out` | 6人 | 4人 | **0人** | 10 / 10（100%） |

- **ページ間の重複は全20収集で0件。** Cursorの引き継ぎは正しく機能した
- 停止理由は`end_of_results` 12件、`max_items` 8件。`max_pages`・`max_duration`・`error`・
  `safety_stop`は0件
- `max_items`で止まった収集では、ページ内の超過分を`discarded_by_limit_count`として計上した
  （Seller 1: 20件、Seller 2: 40件、Seller 3: 10件、Seller 5: 6件、Seller 6: 20件、
  Seller 9: 40件、Seller 10: 40件）。**黙って捨てていない**
- Seller 8の`sold_out`は0件で正常終端した。Errorではない

### 7.2 販売形式の一致（検索 vs Seller商品一覧）

検索とSeller商品一覧の両方に現れた商品は24件で、**24 / 24（100%）**で判定が一致した。
不一致として記録した商品は0件である。

---

## 8. Error・安全停止

| 項目 | 実測 |
|---|---:|
| API Request総数 | 123件（Step 1: 93、Step 2: 30） |
| HTTP 200 | 123件 |
| 401 / 403 / 429 / Challenge | **0件** |
| Timeout / Parse Error | 0件 |
| 商品ページ取得（Browser） | 20 / 20成功 |
| 自動再試行 | **0回** |
| 連続する拒否 | 0回 |
| 安全停止 | **未発動** |
| 観測したError Code | なし |

観測できたのは「発生しなかった」ことまでである。
[実施計画 §9](phase-0-f-live-acceptance.md#9-実行しないこと)のとおり、Rate Limitを意図的に
誘発する試験は行っていない。

---

## 9. 次に見直す点

不合格項目はないため、仕様の変更は行わない。次の3点は改善余地として記録する。

| # | 内容 | 理由 |
|---|---|---|
| 1 | Runnerが商品詳細標本の販売形式内訳を記録していない | §5の偏りを導出ではなく記録から言えるようにする |
| 2 | 未知形状・終了済みAuctionの実測標本が0件 | 実サービスで再現できない。L2のFixtureで担保する現状を継続する |
| 3 | 通常出品の「検索 vs 商品詳細」一致がStep 1で測れていない | Step 2で10 / 10を確認しているが、経路が異なる |

いずれも**本実行の合否には影響しない。** 1と3は次回L4までにRunnerを直す候補とする。

---

## 10. 再実行が必要になる条件

- Fork依存SHAを更新したとき（[Fork運用手順 §7](../development/mercapi-fork-operations.md#7-fork更新をcard-diggerへ反映する)）
- Adapterが`price_yen`の決め方を変えたとき
- `auction` / `auction_info`のキー構成、`state`の値域、`auction_type`の値域が変わったとき
- 検索`auction.id`が空文字でなくなったとき
- Seller一覧が`with_auction`なしでも`auction_info`を返すようになったとき
- Phase完了判定・Release前（[Test運用規約 §9](../development/test-policy.md#9-ライブ受入検証l4の実施規約)）

---

## 11. 出力

| 出力 | 場所 | Git |
|---|---|---|
| 本結果文書 | `docs/phase-0/phase-0-f-live-acceptance-result.md` | 管理する |
| Step 1の全実測値 | `src/backend/artifacts/live-acceptance.json` | **管理外** |
| Step 1の標準出力 | `src/backend/artifacts/live-acceptance-stdout.log` | **管理外** |
| Step 2の全実測値 | `poc/mercapi/artifacts/auction-summary.json` | **管理外** |
| Step 2の構造サンプル | `poc/mercapi/artifacts/structure-samples/`（7件） | **管理外** |

Step 2の構造サンプルは0-F-1と同じ7件を再出力した。既存のFixture
（`src/backend/tests/fixtures/`）は本実行では変更していない。
