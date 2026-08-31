# Phase 0-F — ライブ受入検証（L4）実施計画

## 文書ステータス

- 決定日: **2026-08-31**
- ステータス: **実施基準として採用。実施は未完了**
- 対象: Mercari AdapterとUse caseを実Mercariへ向けて実測する手順と合格基準
- 実施方法の正本: [Test運用規約 §9](../development/test-policy.md#9-ライブ受入検証l4の実施規約)
- 合格基準の正本: [Adapter仕様 §10.3](phase-0-f-adapter-spec.md#103-ライブ受入検証)
- 検証条件: [Phase 0 共通検証プロトコル](poc-validation.md)
- 結果の記録先: `docs/phase-0/phase-0-f-live-acceptance-result.md`（実施時に作成する）

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
| 安全停止 | 401 / 403 / 429 / Challengeが3回連続で停止 | `RequestGate`が判定する |
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

### Step 2. 商品ページとの照合（`poc/mercapi`）

Auction価格が**商品ページの現在価格**と一致するかは、APIだけでは確認できない。
[0-F-1](../../poc/mercapi/auction-result.md)と同じ`auction_probe.py`のBrowser照合を使う。

```bash
cd poc/mercapi
# 実行手順は poc/mercapi/README.md を参照する
```

`src/backend`へPlaywrightを追加しない。本番で使わないBrowser依存をApplication Packageへ
持ち込まないためであり、実行回数を分けられる利点もある。

## 4. 測定項目と合格基準

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

## 5. 記録する内容

| 記録する | 記録しない |
|---|---|
| 実行日時、実行環境、Python Version | Cookie、DPoP、Token、Request Header |
| Fork commit SHAとCard Digger commit SHA | 生Response |
| 件数、率、ページ数、停止理由、Error Code | Seller名、商品Title、商品URL、商品ID |
| 安全停止の有無と連続拒否回数 | 画像本体 |

不一致が出た商品のIDは、Git管理外の`artifacts/`にだけ残す。結果文書には件数だけを書く。

## 6. 判定と不合格時の扱い

- 基準を1つでも満たさない場合、**Phase 0-Fを完了扱いにしない**
- Errorや安全停止を成功として隠さない。発生した事実と回数を記録する
- 条件差（実行環境、Version、時期）があれば結果へ明記する
- 安全停止が発動した場合は時間を置いて再実行する。回避を試みない

不合格の原因がAdapterの実装にある場合はAdapterを直す。原因がMercari側の仕様変更にある場合は、
コードだけで判断せず[Adapter仕様](phase-0-f-adapter-spec.md)と[TODO](../planning/todo.md)を
先に更新する。

## 7. 実行前チェックリスト

- [ ] `uv run pytest tests`がすべて成功している（L2 / L3）
- [ ] Forkの`pytest`がすべて成功している（L1）
- [ ] 依存が固定したFork commit SHAを指している
- [ ] `--plan`でRequest予算を確認した
- [ ] 3回連続の安全Errorで停止する準備をした（`max_retries=0`で実行される）
- [ ] 結果文書へ個人情報と生Responseを書かない準備をした

## 8. 実行しないこと

| 項目 | 理由 |
|---|---|
| CIからの実行 | [CIとMerge基準 §2](../development/ci-policy.md#2-ciで実行する範囲)の絶対規則 |
| 定期実行 | アクセス頻度条件を守れない |
| 失敗時の自動再実行 | 実施条件の「自動再試行なし」に反する |
| Rate Limitの意図的な誘発 | 検証条件に反する。観測できるのは「発生しなかった」ことまで |
| 認証・Proxy・複数Accountでの回避 | 共通検証プロトコルで禁止している |
