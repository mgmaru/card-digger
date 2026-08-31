# Card Digger Documentation

文書は目的別に整理している。最初にProduct仕様を読み、作業時はPlanningと対象Phaseの技術文書を参照する。

## 推奨する読み順

1. [アプリコンセプト](product/concept.md)
2. [MVP実装仕様](product/mvp-spec.md)
3. [開発ロードマップ / TODO](planning/todo.md)
4. [Phase 0-E Mercari取得方式の選定結果](phase-0/phase-0-e-selection.md)
5. [Phase 0-F Mercari Adapter実装仕様](phase-0/phase-0-f-adapter-spec.md)
6. [Phase 0-F Auction情報の追加検証計画](phase-0/phase-0-f-auction-validation.md)
7. [mercapi Fork運用手順](development/mercapi-fork-operations.md)
8. [Test運用規約](development/test-policy.md)

## ディレクトリ

```text
docs/
├── README.md
├── product/
│   ├── concept.md
│   └── mvp-spec.md
├── planning/
│   └── todo.md
├── development/
│   ├── mercapi-fork-operations.md
│   └── test-policy.md
└── phase-0/
    ├── poc-validation.md
    ├── phase-0-e-selection.md
    ├── phase-0-f-auction-validation.md
    └── phase-0-f-adapter-spec.md
```

### `product/`

アプリの価値、利用者、MVPの機能・画面・API・完了条件を置く。

- [concept.md](product/concept.md): Productの目的、背景、将来像
- [mvp-spec.md](product/mvp-spec.md): MVP実装時の機能範囲と受入条件の正本

### `planning/`

Phase横断の作業順、進捗、未完了Taskを置く。

- [todo.md](planning/todo.md): 開発ロードマップとチェックリスト

### `development/`

Phaseをまたいで利用する開発・依存更新・Repository運用の手順を置く。

- [mercapi-fork-operations.md](development/mercapi-fork-operations.md):
  Fork作成、upstream取込、Card Diggerの依存SHA更新、切戻しの手順
- [test-policy.md](development/test-policy.md):
  Test層、Framework、配置、Fixtureの匿名化規則、実行時期、完了判定

### `phase-0/`

Mercari取得方式の技術検証、選定、Adapter設計を置く。

- [poc-validation.md](phase-0/poc-validation.md): 3方式の共通検証条件
- [phase-0-e-selection.md](phase-0/phase-0-e-selection.md): `mercapi`選定の根拠と制約
- [phase-0-f-auction-validation.md](phase-0/phase-0-f-auction-validation.md):
  通常出品とAuctionの判定・価格・終了時刻を確認する追加検証計画
- [phase-0-f-adapter-spec.md](phase-0/phase-0-f-adapter-spec.md): ForkとAdapterの実装仕様

## 配置ルール

- Productの振る舞い・受入条件は`product/`
- Phaseをまたぐ計画・進捗は`planning/`
- Phaseをまたぐ開発・依存・Repositoryの運用手順は`development/`
- 特定Phaseだけで使う調査・技術判断・実装仕様は`phase-N/`
- PoCの実行コードと方式別結果は引き続きRepository直下の`poc/`
- `docs/`直下には、このIndex以外の文書を増やさない
- 同じ決定を複数文書へ複製せず、正本へのLinkを置く
- 「何をテストするか」は各仕様書、「どうテストするか」は`development/test-policy.md`
