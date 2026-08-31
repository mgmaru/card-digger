# Card Digger Backend

Domain型、`MarketplacePort`、Mercari Adapter、収集Policyを置く。Phase 0-Fの範囲では
画面もHTTP APIも持たない。実装基準は次の文書を正本とする。

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
│   ├── collection.py  # Request間隔、1回だけの再試行、安全停止、Page収集
│   ├── collect_search.py
│   └── analyze_seller.py
└── adapters/
    ├── mercari.py       # 管理下のmercapi Fork経由の本番実装
    ├── mock.py          # 外部通信しない実装
    ├── error_mapping.py # 例外 → Error Codeの純粋関数
    └── clock.py         # 実時計と実待機

scripts/
└── live_acceptance.py   # ライブ受入検証（L4）。唯一実Mercariへ接続する
```

`domain`と`application`は`mercapi`をimportしない。この境界は
`tests/unit/test_layering.py`が静的に検査する。

## 依存

外部Clientは管理下Fork`mgmaru/mercapi`の**Test済みcommit SHA**へ固定する。Branch名や
Version範囲は指定しない。`pyproject.toml`と`uv.lock`の両方をコミットする。

```bash
uv sync --extra dev
```

Fork側の更新をここへ取り込む手順は
[mercapi Fork運用手順 §7](../../docs/development/mercapi-fork-operations.md#7-fork更新をcard-diggerへ反映する)。

## Test

L2（AdapterのUnit Test）とL3（Contract Test）だけを自動Test Suiteとする。
**外部通信は行わない。**

```bash
uv run pytest tests              # L2 + L3
uv run pytest tests/unit         # L2
uv run pytest tests/contract     # L3
```

## ライブ受入検証（L4）

**自動Test Suiteに含めない。実Mercariへ接続する手動・低頻度の作業。**
条件・合格基準・記録内容は
[ライブ受入検証実施計画](../../docs/phase-0/phase-0-f-live-acceptance.md)を正本とする。

```bash
uv run python scripts/live_acceptance.py --plan      # Request予算を表示。通信しない
uv run python scripts/live_acceptance.py --confirm   # 実行する
```

`--confirm`が無い限り**1件も通信しない。** `--plan`はRequest数と所要時間の上限だけを表示する。

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
| Use caseは`Clock`と`Sleeper`を注入で受け取る | 30秒の上限と365日の基準を実時間を待たずに検証できる |
| Use caseは`MarketplacePort`だけに依存する | 同じContract TestをMock Adapterへも流せる |
| 例外→Error Codeの変換は純粋関数 | 再現できない失敗もFixtureなしで網羅できる |

`datetime.now()`と`asyncio.sleep()`をAdapter / Use caseの内部で直接呼ばない。
Adapterの内部でFork Clientを生成しない。
