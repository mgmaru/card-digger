# Card Digger Backend

Domain型、`MarketplacePort`、Mercari Adapter、収集Policy、そしてFrontendが使うHTTP APIを置く。
Databaseと認証は持たない。実装基準は次の文書を正本とする。

- [Mercari Adapter実装仕様](../../docs/phase-0/phase-0-f-adapter-spec.md)
- [MVP実装仕様](../../docs/product/mvp-spec.md)
- [Test運用規約](../../docs/development/test-policy.md)
- [mercapi Fork運用手順](../../docs/development/mercapi-fork-operations.md)

## 構成

```text
card_digger/
├── domain/
│   ├── models.py      # Domain型、収集Metadata、停止理由
│   ├── ports.py       # MarketplacePort、Clock、Sleeper
│   └── errors.py      # 共通Error Code、安全停止
├── application/
│   ├── collection.py       # Page収集、1回だけの再試行、安全停止、RequestPacer
│   ├── access.py           # Process全体で共有する外部アクセス制御
│   ├── collect_search.py
│   ├── analyze_seller.py
│   └── seller_knowledge.py # Titleだけを見る純粋関数。時計も通信も持たない
├── adapters/
│   ├── mercari.py       # 管理下のmercapi Fork経由の本番実装
│   ├── mock.py          # 外部通信しない実装
│   ├── error_mapping.py # 例外 → Error Codeの純粋関数
│   └── clock.py         # 実時計と実待機
└── api/
    ├── main.py          # 3 Endpointと、部品を1か所で組み立てるcreate_app
    └── schemas.py       # FrontendへのJSON。Domainより狭い

scripts/
├── live_acceptance.py   # ライブ受入検証（L4）。実Mercariへ通信する
└── acceptance_app.py    # E2E受入Flow用。Mock Adapterで同じApplicationを起動する
```

`domain`と`application`は`mercapi`をimportしない。この境界は
`tests/unit/test_layering.py`が静的に検査する。

実Mercariへ接続しうるのは`create_app()`（引数なしの場合）と`scripts/live_acceptance.py`の
2つだけで、**Testはどちらも通らない。**`scripts/acceptance_app.py`は同じ`create_app()`を
呼ぶが、**Mock Adapterを渡すので外へ出ない。**それを`tests/unit/test_acceptance_app.py`が
検査する。

## 依存

外部Clientは管理下Fork`mgmaru/mercapi`の**Test済みcommit SHA**へ固定する。Branch名や
Version範囲は指定しない。`pyproject.toml`と`uv.lock`の両方をコミットする。

```bash
uv sync --extra dev
```

Fork側の更新をここへ取り込む手順は
[mercapi Fork運用手順 §7](../../docs/development/mercapi-fork-operations.md#7-fork更新をcard-diggerへ反映する)。

## Test

L2（AdapterのUnit Test）、L3（Contract Test）、Backend API Testを自動Test Suiteとする。
**外部通信は行わない。**

```bash
uv run pytest tests              # L2 + L3 + API
uv run pytest tests/unit         # L2
uv run pytest tests/contract     # L3
uv run pytest tests/api          # Backend API（L3と同じ扱い）
```

## 起動

```bash
uv run uvicorn --factory card_digger.api.main:create_app --reload
```

`uvicorn`の既定Bind先は`127.0.0.1`である。**`--host 0.0.0.0`を付けない。** 認証が無いまま
LANへ公開することになる（[MVP仕様 §10](../../docs/product/mvp-spec.md#10-data取扱い)）。

**`--workers`も付けない。** 「同時実行数1・開始間隔2秒以上・同じ収集を二重に走らせない」は
`MarketplaceAccess`が1 Processの中で保証している。Processが増えるとそれぞれが自分の分だけを
見るようになり、Mercariから見た総量の約束が壊れる。

`create_app()`は引数なしで実Mercariへ繋ぐ。Mock Adapterで動かすときは`marketplace=`へ渡す。
**このコマンドは実Mercariへ通信する。**

### Mercariへ通信せずに起動する（E2E受入Flowと開発用）

```bash
uv run uvicorn --factory scripts.acceptance_app:create_acceptance_app --reload
```

**同じ`create_app()`を、Mock Adapterと止まった時計で組み立てたもの**である。
別のApplicationではないので、E2Eが通る経路は本番と同じものになる。

| | 本番 | 受入用 |
|---|---|---|
| Marketplace | Mercari | **`MockAdapter`（`SEED`から答える）** |
| Request間隔 | 2秒以上 | **0秒。**外へ出ないので守る相手がいない |
| 時計 | 実時計 | **止めてある。**`2年前`が来春`3年前`にならない |

種Dataが満たすべき条件（上限を跨ぐSeller、自力で終端に達する状態、3種の販売形式）は
`tests/unit/test_acceptance_app.py`が固定する。**Playwright側からは見えない前提**なので、
崩れたときに遠くで落ちないようにここで押さえる。

## ライブ受入検証（L4）

**自動Test Suiteに含めない。実Mercariへ接続する手動・低頻度の作業。**
条件・合格基準・記録内容は
[ライブ受入検証実施計画](../../docs/phase-0/phase-0-f-live-acceptance.md)を正本とする。

```bash
uv run python scripts/live_acceptance.py --plan      # Request予算を表示。通信しない
uv run python scripts/live_acceptance.py --confirm   # 実行する
```

`--confirm`が無い限り**1件も通信しない。** `--plan`はRequest数と所要時間の上限だけを表示する。

商品詳細の標本は販売形式ごとの枠で選び、内訳も記録する。1形式が多いだけで標本を占有すると、
一致率がその形式についてしか語れなくなるためである。売却済みAuctionが見つかった場合は
`--finished-auctions`（既定5件）まで商品詳細を引き、終了済みAuctionの有無を観測する。

| 項目 | 値 |
|---|---|
| 同時実行数 | 1 |
| Request開始間隔 | 2秒以上 |
| 自動再試行 | **なし**（`RequestGate(max_retries=0)`） |
| 安全停止 | 401 / 403 / 429 / Challengeが3回連続で以後の外部アクセスを停止 |

実測値は`artifacts/live-acceptance.json`へ書き出す（**Git管理外**）。標準出力のMarkdownを
結果文書へ貼る。結果文書にはSeller名・商品Title・商品URL・商品IDを書かない。

Auction価格と商品ページの照合だけは、Browserが必要なため`poc/mercapi/auction_probe.py`で
別途実施する。`src/backend`はPlaywrightに依存しない。

> `scripts/`はCIから呼ばれない。CIは`tests/`だけを実行する
> （[CIとMerge基準 §2](../../docs/development/ci-policy.md#2-ciで実行する範囲)）。

## 設計上の制約

| 制約 | 理由 |
|---|---|
| `MercariAdapter`はFork ClientをConstructorで受け取る | 外部通信なしで正規化とError分類を検証できる |
| `trading`を要求しないのはUse caseの判断で、Adapterの制約ではない | 表示要件が出たらApplication層だけで要求を足せる（[Adapter仕様 §8.2](../../docs/phase-0/phase-0-f-adapter-spec.md#tradingの扱い2026-09-01決定)） |
| Use caseは`Clock`と`Sleeper`を注入で受け取る | 30秒の上限と365日の基準を実時間を待たずに検証できる |
| Use caseは`MarketplacePort`だけに依存する | 同じContract TestをMock Adapterへも流せる |
| 間隔・同時実行・重複排除は`MarketplaceAccess`が1つだけ持つ | 相手（Mercari）が1つなので、総量の約束は共有された状態でしか守れない |
| 例外→Error Codeの変換は純粋関数 | 再現できない失敗もFixtureなしで網羅できる |

`datetime.now()`と`asyncio.sleep()`をAdapter / Use caseの内部で直接呼ばない。
Adapterの内部でFork Clientを生成しない。
