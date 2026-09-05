# Phase 0-F — ライブ受入検証（L4）実施計画

## 文書ステータス

- 決定日: **2026-08-31**
- 実施日: **2026-09-01**
- ステータス: **実施基準として採用。実施完了・判定は合格**
- 対象: Mercari AdapterとUse caseを実Mercariへ向けて実測する手順と合格基準
- 実施方法の正本: [Test運用規約 §9](../development/test-policy.md#9-ライブ受入検証l4の実施規約)
- 合格基準の正本: [Adapter仕様 §10.3](phase-0-f-adapter-spec.md#103-ライブ受入検証)
- 検証条件: [Phase 0 共通検証プロトコル](poc-validation.md)
- 結果の記録先: [ライブ受入検証結果](phase-0-f-live-acceptance-result.md)（2026-09-01に2回実施、いずれも**合格**。判定は第2回を採用）

## 用語

| 用語 | 意味 |
|---|---|
| **Runner** | 人が手で起動する実行用Script。自動Testと違い、実サービスへ接続して**実測値を記録する**ことが目的。Card Diggerでは`poc/mercapi/run.py`、`auction_probe.py`、本節の`live_acceptance.py`が該当する |
| Fixture | Testが読む固定入力データ。実通信の代わりに使う（[Test運用規約 §5](../development/test-policy.md#5-fixture規約)） |
| L1〜L3 | 外部通信しない自動Test Suite。Fixtureを入力にする |
| L4 | この文書が扱うライブ受入検証。Runnerで実Mercariへ接続する |

```text
自動Test    CIが起動 → Fixtureを読む   → 緑 / 赤
Runner      人が起動 → 実Mercariへ接続 → 実測値を書いたMarkdown
```

## 1. 目的

**L4はL1〜L3を実Mercariへ向けて再実行する作業ではない。** 確認している対象が違う。

```text
L1〜L3   コード  ←→  仕様        書いたコードが仕様どおりか
L4       仕様    ←→  実Mercari   仕様の前提が現実と合っているか
```

Fixtureは固定されているため、Mercariが応答形式を変えてもL1〜L3は緑のままになる。
これはBugではなくFixtureの性質であり、その盲点を埋める唯一の手段がL4である。

判定はGreen / RedではなくMarkdownの結果文書とする。

## 2. 実施条件

[Test運用規約 §9](../development/test-policy.md#9-ライブ受入検証l4の実施規約)と同一とする。

| 条件 | 値 | 実装 |
|---|---|---|
| 同時実行数 | 1 | `RequestGate`が直列化する |
| 外部Request開始間隔 | 2秒以上 | `RequestGate`が待機を入れる |
| 自動再試行 | **なし** | `RequestGate(max_retries=0)` |
| 安全停止 | 401 / 403 / 429 / Challengeが3回連続で停止。**この実行では解除しない** | `SafetyBrake(cooldown_seconds=NEVER)`。アプリの既定は60秒後に1回試すが、それはこの条件表と合わない（[アーキテクチャ §5.2](../development/architecture.md#一般名と比べると足りない部分が名前で分かった)） |
| 回避行為 | **行わない** | 認証・CAPTCHA回避・Proxy切替・複数Accountを使わない |

実行のたびに条件を守れているかを確認するのではなく、**条件を守る実装から実行する。**
Runnerは`--confirm`が無い限り1件も通信しない。

## 3. 実行手順

L4は2つのStepに分かれる。**Step 2はBrowserを使うため、`src/backend`ではなくPoC側で行う。**

### Step 1. API側の実測（`src/backend`）

```bash
cd src/backend
uv run python scripts/live_acceptance.py --plan        # Request予算を確認する
uv run python scripts/live_acceptance.py --confirm     # 実行する
```

`--plan`はRequest数と所要時間の上限を表示するだけで通信しない。実行前に必ず確認する。

出力は次の2つとする。

| 出力 | 内容 | Git |
|---|---|---|
| 標準出力のMarkdown | 合格基準との対応表。結果文書へ貼る | 結果文書として管理する |
| `src/backend/artifacts/live-acceptance.json` | 全実測値と不一致商品のID | **管理外** |

#### 標本の作り方

商品詳細20件は**販売形式ごとの枠**で選ぶ。読めないAuction（`unknown`）を先に全件取り、
残りをAuctionと通常出品へ交互に配る。片方が不足した分はもう片方へ回す。

2026-09-01の初回実行では、Auctionを優先して詰める旧規則により**20件すべてがAuction**になり、
「検索 vs 商品詳細」の一致率が通常出品を1件も含まないまま100%と表示された。
率だけでは偏りが見えないため、Runnerは**標本の販売形式内訳も併せて記録する。**

#### 終了済みAuctionの追跡（合格基準外）

検索は`status=on_sale`固定のため、終了済みAuctionは構造上現れない。一方、Sellerの`sold_out`には
現れうる。そこでSeller収集で`sold_out`かつAuction（または`unknown`）と判定された商品から
**最大5件だけ商品詳細を取得**し、`finish_time`・`state`・`winner_id`の有無を記録する。

- これは**合格基準ではない**。未観測のFixtureを`assumed`で作らずに済ませるための観測である
- Seller一覧の`auction_info`には`finish_time`が無いため、商品詳細でしか確認できない
- この1手順だけはDomain型が落とすFieldを読むため`mercapi`のモデルを直接参照する。
  Error分類だけはAdapterと同じ規則を適用し、安全停止の判定から外れないようにする
- `winner_id`は**有無だけ**を記録する。値は記録しない

### Step 2. 商品ページとの照合（`poc/mercapi`）

Auction価格が**商品ページの現在価格**と一致するかは、APIだけでは確認できない。
[0-F-1](../../poc/mercapi/auction-result.md)と同じ`auction_probe.py`のBrowser照合を使う。

```bash
cd poc/mercapi
# 実行手順は poc/mercapi/README.md を参照する
```

`src/backend`へPlaywrightを追加しない。本番で使わないBrowser依存をApplication Packageへ
持ち込まないためである。

#### 価格の照合方法

商品ページの価格要素（`[data-testid="price"]`）を読み、API値と**1対1で比較する。**

| 状態 | 扱い |
|---|---|
| 要素が読めて値が一致 | 一致 |
| 要素が読めて値が不一致 | **不一致**（入札で動いた場合は別に計上する） |
| **要素が読めない** | **`notComparable`。一致率へ含めない** |

要素が読めないときに、ページ全体から`¥`金額を拾う旧方式へ**黙って戻さない。**
戻すと「確認できなかった」が「一致した」として率に混ざる。

> **2026-09-01の変更。** それまでは「ページ本文の`¥`金額のどれかにAPI値が含まれるか」という
> 包含判定だった。`現在の価格`というラベルを本文から探して20ページ中0件だったためだが、
> 実際のラベルは`現在`で、価格要素には`data-testid`が付いていた。DOMを調べずに本文検索だけで
> 「手がかりなし」と判断したことが原因である。旧方式の結果は`containment`として併記し、
> 0-F-1・初回L4の数値と比較できるようにしている。

**この照合を`MercariAdapter`経由で行わない理由は§4に記載する。** Browserが必要という技術的都合
だけでなく、責務の分離にもとづく判断である。

## 4. なぜStep 2をAdapter経由で行わないのか

Step 2は`MercariAdapter`を通らず、`mercapi`の生の値と商品ページを直接比較する。
「実装したBackendの出力をページと突き合わせた方が厳密ではないか」という疑問が生じるため、
判断理由を残す。

### 4.1 責務の違い

| | `mercapi`（Fork） | `MercariAdapter` |
|---|---|---|
| 担うもの | HTTP、DPoP署名、JSON → Forkモデルへの解析 | 要求の組み立て、値の意味づけ、Error分類 |
| 答える問い | **どうやって取得するか** | **何を要求し、その値が何を意味するか** |

取得そのものは`mercapi`が担い、Adapterは1 Requestも送らない。
Adapterが決めるのは`with_auction=true`のような**要求の内容**と、返ってきた値の**解釈**である。

### 4.2 この照合が答える問い

商品ページとの照合が確かめているのは次の1点に尽きる。

> `highest_bid`は、買い手が画面で見る現在価格を意味するのか

これは**Mercari側の事実**についての問いであり、Card Diggerのコードについての問いではない。
[Test運用規約 §3](../development/test-policy.md#3-test層)のとおり、L4が答えるべきは
「仕様の前提が現実と合っているか」であって「書いたコードが仕様どおりか」ではない。

Adapterを通すと、1つの数字に2つの問いが乗る。

```text
不一致が出た → highest_bidの意味が変わったのか？
             → AdapterのField選択が壊れたのか？
             → 切り分けられない
```

生の値とページを比べれば、答えは前者だけに限定される。

### 4.3 Adapterの検査は実測より固定Fixtureの方が強い

「Adapterが誤って`initial_price`（開始価格）を使う」という失敗を、実測で捕まえられるかを考える。
[0-F-1の実測](../../poc/mercapi/auction-result.md)ではAuction 10件の内訳が次のとおりだった。

| 状態 | 件数 | `initial_price`と`highest_bid` |
|---|---:|---|
| 未入札（`STATE_NO_BID`） | **7** | **同じ値** |
| 入札済み | 3 | 乖離する |

**未入札では開始価格と現在価格が一致するため、バグがあっても7件は一致してしまう。**
標本が未入札に寄れば、誤りがあるのに100%一致と出る。実測はこの検査に向いていない。

Fixtureなら「開始価格300 / 現在価格1200」と必ず食い違う値を置けるため、誤りは確実に捕まる。
したがって「AdapterがどのFieldを選ぶか」はL2のFixture Testが担当する。

### 4.4 Adapterは実データでも検査されている

Step 2でAdapterを通さないことは、「Adapterが実Mercariに対して未検証」を意味しない。
**Step 1のRunnerは`MercariAdapter`を通して実Mercariから取得している。**

| 検査 | 答える問い | 経路 | 入力 |
|---|---|---|---|
| L2 | Adapterは仕様どおり変換するか | Adapterのみ | Fixture |
| **L4 Step 1** | 実データでもAdapterは成立するか | **Adapter → mercapi → 実Mercari** | 実応答 |
| **L4 Step 2** | `highest_bid`は現在価格を意味するか | **mercapi → 実Mercari** + 商品ページ | 実応答 + 画面 |

3つとも問いが1つずつで重なっていない。これが分離できている状態とする。

### 4.5 この判断を見直す契機

- Adapterが`price_yen`の決め方を変えたとき（Fixtureだけでなく実測でも確認する価値が出る）
- `highest_bid`以外のFieldを画面表示へ使うようになったとき
- Step 1とStep 2で同じ商品を追跡する必要が出たとき

## 5. 測定項目と合格基準

[Adapter仕様 §10.3](phase-0-f-adapter-spec.md#103-ライブ受入検証)を正本とする。

| # | 基準 | 標本 | Step |
|---|---|---:|---|
| 1 | 検索5回の成功率80%以上（100%を優先） | 5回 | 1 |
| 2 | 必須商品Field各100% | 収集した全商品 | 1 |
| 3 | 商品詳細のコンディション95%以上 | 20件 | 1 |
| 4 | 商品詳細のいいね95%以上 | 20件 | 1 |
| 5 | Seller Profileの名前90%以上 | 最大10人 | 1 |
| 6 | `on_sale`で2ページ目取得または1ページ終端 | 最大10人 | 1 |
| 7 | `sold_out`で2ページ目取得または1ページ終端 | 最大10人 | 1 |
| 8 | 販売形式の判定が標本各100%一致 | 検索 vs 商品詳細 / 検索 vs Seller一覧 | 1 |
| 9 | Auction価格が商品ページの取得時点価格と95%以上一致 | 10件以上 | **2** |
| 10 | 401 / 403 / 429 / Challengeを回避せず記録する | 全Request | 1 |

Seller数が10人に満たない場合は、取得できた全Sellerを母数とし、その事実を結果へ記載する。

### 基準2について

Adapterは必須Fieldが欠けた時点で操作を失敗させるため、**成功した検索の取得率は構造上100%になる。**
それでも測るのは、この率が合格基準そのものであり、Adapterが将来黙って除外へ変わった場合に
「測っていない」ではなく「100%を下回った」として現れるようにするためである。

## 6. 記録する内容

| 記録する | 記録しない |
|---|---|
| 実行日時、実行環境、Python Version | Cookie、DPoP、Token、Request Header |
| Fork commit SHAとCard Digger commit SHA | 生Response |
| 件数、率、ページ数、停止理由、Error Code | Seller名、商品Title、商品URL、商品ID |
| 安全停止の有無と連続拒否回数 | 画像本体 |

不一致が出た商品のIDは、Git管理外の`artifacts/`にだけ残す。結果文書には件数だけを書く。

## 7. 判定と不合格時の扱い

- 基準を1つでも満たさない場合、**Phase 0-Fを完了扱いにしない**
- Errorや安全停止を成功として隠さない。発生した事実と回数を記録する
- 条件差（実行環境、Version、時期）があれば結果へ明記する
- 安全停止が発動した場合は時間を置いて再実行する。回避を試みない

不合格の原因がAdapterの実装にある場合はAdapterを直す。原因がMercari側の仕様変更にある場合は、
コードだけで判断せず[Adapter仕様](phase-0-f-adapter-spec.md)と[TODO](../planning/todo.md)を
先に更新する。

## 8. 実行前チェックリスト

- [ ] `uv run pytest tests`がすべて成功している（L2 / L3）
- [ ] Forkの`pytest`がすべて成功している（L1）
- [ ] 依存が固定したFork commit SHAを指している
- [ ] `--plan`でRequest予算を確認した
- [ ] 3回連続の安全Errorで停止する準備をした（`max_retries=0`で実行される）
- [ ] 結果文書へ個人情報と生Responseを書かない準備をした

## 9. 実行しないこと

| 項目 | 理由 |
|---|---|
| CIからの実行 | [CIとMerge基準 §2](../development/ci-policy.md#2-ciで実行する範囲)の絶対規則 |
| 定期実行 | アクセス頻度条件を守れない |
| 失敗時の自動再実行 | 実施条件の「自動再試行なし」に反する |
| Rate Limitの意図的な誘発 | 検証条件に反する。観測できるのは「発生しなかった」ことまで |
| 認証・Proxy・複数Accountでの回避 | 共通検証プロトコルで禁止している |
