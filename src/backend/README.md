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

ライブ受入検証（L4）は自動Test Suiteに含めない。実Mercariへ接続する手動・低頻度の作業であり、
[Test運用規約 §9](../../docs/development/test-policy.md#9-ライブ受入検証l4の実施規約)の
実施条件（同時実行数1、間隔2秒以上、自動再試行なし、3回連続の安全Errorで停止）に従って
専用Scriptと手順書から実行する。

## 設計上の制約

| 制約 | 理由 |
|---|---|
| `MercariAdapter`はFork ClientをConstructorで受け取る | 外部通信なしで正規化とError分類を検証できる |
| Use caseは`Clock`と`Sleeper`を注入で受け取る | 30秒の上限と365日の基準を実時間を待たずに検証できる |
| Use caseは`MarketplacePort`だけに依存する | 同じContract TestをMock Adapterへも流せる |
| 例外→Error Codeの変換は純粋関数 | 再現できない失敗もFixtureなしで網羅できる |

`datetime.now()`と`asyncio.sleep()`をAdapter / Use caseの内部で直接呼ばない。
Adapterの内部でFork Clientを生成しない。
