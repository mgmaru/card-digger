# Card Digger

大量出品・引退品の中から、確認する価値が高いトレーディングカード商品を効率よく絞り込むための、マーケットプレイス検索・出品者分析ツールです。

Phase 0-A〜0-Eの技術検証を完了し、Mercari取得には **`kynacio/mercapi`方式**を選定しました。
Phase 0-FとMVPの実装仕様を確定し、Auction情報の追加検証も**合格**しました。管理下の
`mercapi` ForkへSeller商品の状態別ページングと`with_auction`を追加し、Domain型・
`MarketplacePort`・Mercari Adapter・収集Policyを`src/backend`へ実装しました。
2026-09-01のライブ受入検証（L4）も**合格**し、**Phase 0-Fは完了**しました。次はPhase 1のMVPです。

L4は同日に2回実施しています。1回目は全項目合格したものの、標本の偏りと判定規則の緩さという
**測定側の弱点**が見つかったため、方針を直して2回目を実行しました（判定は2回目を採用）。
経緯と教訓は[検証の落とし穴](docs/retrospectives/2026-09-01-verification-pitfalls.md)にまとめています。

## ドキュメント

- [ドキュメント一覧](docs/README.md)
- [アプリコンセプト](docs/product/concept.md)
- [MVP実装仕様](docs/product/mvp-spec.md)
- [開発ロードマップ / TODO](docs/planning/todo.md)
- [Phase 0-E Mercari取得方式の選定結果](docs/phase-0/phase-0-e-selection.md)
- [Phase 0-F Mercari Adapter実装仕様](docs/phase-0/phase-0-f-adapter-spec.md)
- [Phase 0-F Auction情報の追加検証計画](docs/phase-0/phase-0-f-auction-validation.md) / [実測結果](poc/mercapi/auction-result.md)
- [Phase 0-F ライブ受入検証実施計画](docs/phase-0/phase-0-f-live-acceptance.md) / [実測結果](docs/phase-0/phase-0-f-live-acceptance-result.md)
- [Test運用規約](docs/development/test-policy.md)
- [CIとMerge基準](docs/development/ci-policy.md)

## リポジトリ構成

```text
card-digger/
├── README.md
├── docs/
│   ├── README.md
│   ├── product/       # コンセプト・MVP仕様
│   ├── planning/      # ロードマップ・TODO
│   ├── development/   # Fork運用・Test運用規約・CI
│   └── phase-0/       # PoC条件・選定・Adapter仕様
├── tools/             # 文書Link検査などの補助Script
├── poc/
│   ├── common/        # 共通条件・結果テンプレート
│   ├── mercari/       # marvinody/mercari の検証
│   ├── mercapi/       # kynacio/mercapi の検証
│   └── playwright/    # ブラウザ経由方式の検証
└── src/
    └── backend/       # Domain、Use case、Mercari Adapter
```

各PoCは依存関係や実行手順が異なるため、検証に着手する段階でそれぞれのディレクトリ内に環境を構築します。

## 開発を始める

```bash
git clone https://github.com/mgmaru/card-digger.git
cd card-digger
```

リポジトリ共通の依存パッケージや必須環境変数はありません。依存はBackend / Frontendそれぞれの
ディレクトリで固定します。Backendは[`src/backend/README.md`](src/backend/README.md)を参照してください。

```bash
cd src/backend
uv sync --extra dev
uv run pytest tests
```

秘密情報が必要になった場合は`.env`を直接共有せず、値を含まない`.env.example`を追加します。

## 開発方針

1. 3つの取得方式を同じ条件で検証した
2. 必要な商品・Seller情報を取得できる方式として`kynacio/mercapi`を選定した
3. 選定方式をMercari Adapterの内側に閉じ込める仕様を確定した
4. Domain型とAdapterを実装し、取得方式をAdapterの内側へ閉じ込めた
5. 検索・画像一覧・Seller分析を備えたMVPを実装する

検証条件と採用基準の詳細は[TODO](docs/planning/todo.md)を参照してください。

## 注意事項

検証対象には非公式API Wrapperやブラウザ自動化が含まれます。実装・運用時は対象サービスの利用規約を確認し、アクセス頻度、認証情報、取得データを適切に扱ってください。
