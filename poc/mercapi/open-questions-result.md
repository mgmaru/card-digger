# 未解決2件の追加観測結果

## 判定

| 質問 | 結果 |
|---|---|
| **1. `num_sell_items`は何を数えているか** | **累計販売件数ではない。** 全状態の出品総数と一致した |
| **2. `trading`にAuction情報は付くか** | **付かなかった。** 23件中0件 |

質問1は**MVPの表示要件に影響する。** [MVP実装仕様](../../docs/product/mvp-spec.md)と
[TODO 1-3](../../docs/planning/todo.md)が「Profileの**累計販売件数**表示」としており、
Domain型も`Seller.total_sales_count`という名前で保持している。**どちらも実態と合っていない。**

---

## 1. 実行環境

| 項目 | 値 |
|---|---|
| 実行日時 | `2026-09-01T09:10:51Z` 〜 `09:11:31Z`（40秒） |
| Runtime | Python 3.11.15 |
| OS / Architecture | `macOS-26.5-arm64-arm-64bit` |
| Card Digger commit | `6ae332a081b23d14a43f77c74c2bb66490b98f36` |
| 対象`mercapi` | upstream `20ba68fd42677997c4c91b4e4eb17c1e7e387efa` |
| Command | `poc/mercapi/.venv/bin/python poc/mercapi/open_questions_probe.py` |
| 認証状態 | 匿名。Login / 永続Cookie / 明示Token / Proxyなし |

| 条件 | 実測 |
|---|---|
| 同時実行数 | 1 |
| Request開始間隔 | 2秒以上 |
| 自動再試行 | **0回** |
| 安全停止 | 未発動（連続拒否0回） |
| Request総数 | **21件**。すべてHTTP 200 |

標本はSeller 5人。各Sellerについて Profile 1件と、`on_sale` / `trading` / `sold_out`を
**状態ごとに1ページずつ**（`with_auction=true`）取得した。

| 状態 | 取得件数 | うち`auction_info`あり |
|---|---:|---:|
| `on_sale` | 100 | **4** |
| `trading` | 23 | **0** |
| `sold_out` | 135 | **0** |

---

## 2. 質問1 — `num_sell_items`は累計販売件数ではない

### 2.1 比較

`num_sell_items`を、実際に返ってきた件数の組み合わせと突き合わせた。
**全状態が1ページ以内で終端したSellerだけが判定に使える**（打ち切られていると比較できない）。

| Seller | `num_sell_items` | `on_sale` | `trading` | `sold_out` | 全状態が終端 | 判定 |
|---:|---:|---:|---:|---:|:---:|---|
| 1 | 267 | 30 | 3 | 30 | — | 打ち切り |
| 2 | 89 | 30 | 9 | 30 | — | 打ち切り |
| 3 | 732 | 30 | 7 | 20 | — | 打ち切り |
| **4** | **29** | **1** | **3** | **25** | **○** | **`all_states`** |
| 5 | 53 | 9 | 1 | 30 | — | 打ち切り |

Seller 4 で **1 + 3 + 25 = 29** が `num_sell_items` と**完全一致**した。
候補4つのうち一致したのは1つだけである。

| 解釈 | Seller 4での値 | `num_sell_items`(29)と一致 |
|---|---:|:---:|
| `sold_out`のみ（＝累計販売件数） | 25 | — |
| `sold_out` + `trading` | 28 | — |
| `on_sale`のみ | 1 | — |
| **全状態の合計** | **29** | **○** |

### 2.2 評価件数による裏づけ

判定できたSellerは1人だけで、**それだけでは弱い。** ただし独立した根拠がもう1つある。

| Seller | `num_sell_items` | `num_ratings` |
|---:|---:|---:|
| 4 | **29** | **247** |
| 5 | 53 | 86 |

**Seller 4は評価247件に対し`num_sell_items`が29しかない。** 評価は取引ごとに付くため、
累計販売件数が29なら247の評価は成立しない。Seller 5も評価が上回る。

**`num_sell_items`が累計販売件数でないことは、この2点で説明がつく。**

### 2.3 他に販売件数を持つFieldは無い

Profileに存在する`num_`で始まるFieldは3つだけだった。

```text
num_ratings      評価件数
num_sell_items   出品件数（本検証の対象）
num_ticket       用途不明。未調査
```

**`num_sold_items`も`num_trading_items`も存在しない。** つまりProfileから累計販売件数は
取得できない。

### 2.4 仕様へ反映すべきこと

| 対象 | 現状 | 実態 |
|---|---|---|
| Domain型 | `Seller.total_sales_count` | 販売数ではなく**出品数** |
| [MVP仕様](../../docs/product/mvp-spec.md) | 「Profileの累計販売件数表示」 | 累計販売件数は**取得できない** |
| [TODO 1-3](../../docs/planning/todo.md) | 同上 | 同上 |

> **反映済み（2026-09-01）。** Domain型は`Seller.listed_item_count`へ改名し、
> MVP仕様・concept・TODOの表示要件も「出品件数」へ直した。根拠は
> [Adapter仕様 §6.3](../../docs/phase-0/phase-0-f-adapter-spec.md#63-listed_item_countは販売件数ではない)。

**このまま画面に「累計販売件数 29」と出すと、評価247件のSellerに対して誤った数字を示す。**
[Test運用規約 §2.3](../../docs/development/test-policy.md#23-静かな失敗の例)の言う静かな失敗に当たる。

### 2.5 限界

- **判定できたSellerは1人。** 残り4人は`sold_out`が30件（1ページ上限）で打ち切られ、比較できなかった
- 打ち切られないSellerは出品数が少ないSellerに偏る
- `num_ticket`は未調査

**「累計販売件数ではない」ことの根拠は十分だが、「全状態の出品数である」と断定するには
標本が足りない。** 打ち切られないSellerを増やして再確認する余地がある。

---

## 3. 質問2 — `trading`にAuction情報は付かなかった

### 3.1 実測

| Seller | `trading`件数 | うち`auction_info`あり |
|---:|---:|---:|
| 1 | 3 | 0 |
| 2 | 9 | 0 |
| 3 | 7 | 0 |
| 4 | 3 | 0 |
| 5 | 1 | 0 |
| **合計** | **23** | **0** |

### 3.2 要求は正しく行われている（対照）

同じ実行の`on_sale`では、**`auction_info`が4件返っている。**

```text
on_sale   100件 → auction_info あり 4件（bid_deadline,highest_bid,id,initial_price,total_bid）
trading    23件 → auction_info あり 0件
sold_out  135件 → auction_info あり 0件
```

**`with_auction=true`は効いている。** `trading`と`sold_out`の0件は、要求の誤りではない。

### 3.3 状態ごとの観測状況（L4と合わせた累計）

| 状態 | 観測した件数 | `auction_info`あり | 出所 |
|---|---:|---:|---|
| `on_sale` | 451 | **30** | L4第2回 351件 + 本検証 100件 |
| `trading` | 23 | **0** | 本検証のみ |
| `sold_out` | 642 | **0** | L4第2回 507件 + 本検証 135件 |

**3状態すべてを観測し、Auction情報が付いたのは`on_sale`だけだった。**

### 3.4 新しい仮説

これまで「終了済みAuctionは`trading`にいるのではないか」と考えていた（`expected_winner_period_end_time`の存在から）。
**その仮説は支持されなかった。**

代わりに次の仮説が立つ。

> **`auction_info`は進行中のAuctionにしか付かない。** 終了するとAuction情報自体が落ちる。

これが正しければ、**Seller商品一覧から終了済みAuctionを識別することは構造的にできない。**
Auctionだった商品も、終了後は通常出品と区別が付かなくなる。

### 3.5 まだ確定していない

`trading` 23件は少なく、終了済みAuctionが偶然含まれなかった可能性を排除できない。
`sold_out` 642件は相応の量だが、**同一商品を追跡していない**ため、
「Auctionだった商品が終了後どうなるか」を直接見たわけではない。

決着させるには**実験2（同一商品の追跡）**が要る。

```text
現在 on_sale のAuction（bid_deadline あり）のIDを控える
        ↓ 1〜2日待つ
商品詳細を再取得して status と auction_info の変化を見る
```

商品詳細（`items/get`）は`include_auction=true`を常に送っており、状態Filterも無いため、
**終了後の姿を直接観測できる唯一の経路**である。

---

## 4. 記録しなかったもの

Cookie、DPoP、Token、Header、生Response、Seller名、商品Title、商品URLは記録していない。
Seller IDと商品IDはGit管理外の`artifacts/open-questions.json`にだけ残る。
本文書には件数とField名だけを書いている。

---

## 5. 次にやること

| # | 内容 | 優先 |
|---|---|---|
| 1 | ~~`Seller.total_sales_count`の名称とMVPの表示要件を実態へ合わせる~~ | **完了**（2026-09-01。`listed_item_count`へ改名） |
| 2 | 打ち切られないSellerを増やし、`num_sell_items = 全状態の合計`を再確認する | 中 |
| 3 | 実験2（Auctionの追跡）で終了後の姿を観測する | 中。1〜2日の待ちが要る |
| 4 | `num_ticket`の用途を確認する | 低 |
