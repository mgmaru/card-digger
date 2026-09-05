# Card Digger Documentation

文書は目的別に整理している。最初にProduct仕様を読み、作業時はPlanningと対象Phaseの技術文書を参照する。

## 推奨する読み順

1. [アプリコンセプト](product/concept.md)
2. [MVP実装仕様](product/mvp-spec.md)
3. [商品画面 実装仕様](product/item-screen-spec.md)
4. [視覚方針 — 色・書体・余白](product/design-tokens.md)
5. [開発ロードマップ / TODO](planning/todo.md)
6. [Phase 0-E Mercari取得方式の選定結果](phase-0/phase-0-e-selection.md)
7. [Phase 0-F Mercari Adapter実装仕様](phase-0/phase-0-f-adapter-spec.md)
8. [Phase 0-F Auction情報の追加検証計画](phase-0/phase-0-f-auction-validation.md)
9. [Phase 0-F ライブ受入検証実施計画](phase-0/phase-0-f-live-acceptance.md)
10. [Phase 0-F ライブ受入検証結果](phase-0/phase-0-f-live-acceptance-result.md)
11. [アーキテクチャと用語](development/architecture.md)
12. [mercapi Fork運用手順](development/mercapi-fork-operations.md)
13. [Test運用規約](development/test-policy.md)
14. [CIとMerge基準](development/ci-policy.md)

振り返りは実装に必要ではないが、同じ失敗を繰り返さないために残す。

- [検証の落とし穴（2026-09-01）](retrospectives/2026-09-01-verification-pitfalls.md)

## ディレクトリ

```text
docs/
├── README.md
├── product/
│   ├── concept.md
│   ├── design-tokens.md
│   ├── item-screen-spec.md
│   └── mvp-spec.md
├── planning/
│   └── todo.md
├── development/
│   ├── architecture.md
│   ├── ci-policy.md
│   ├── mercapi-fork-operations.md
│   └── test-policy.md
├── retrospectives/
│   └── 2026-09-01-verification-pitfalls.md
└── phase-0/
    ├── poc-validation.md
    ├── phase-0-e-selection.md
    ├── phase-0-f-auction-validation.md
    ├── phase-0-f-adapter-spec.md
    ├── phase-0-f-live-acceptance.md
    └── phase-0-f-live-acceptance-result.md
```

### `product/`

アプリの価値、利用者、MVPの機能・画面・API・完了条件を置く。

- [concept.md](product/concept.md): Productの目的、背景、将来像
- [mvp-spec.md](product/mvp-spec.md): **MVPの3画面**（検索・Seller・Seller Knowledge）の正本
- [item-screen-spec.md](product/item-screen-spec.md):
  **商品画面**（商品1件について買うかを決める画面）の振る舞いと受入条件の正本。**2026-09-05設計**
- [design-tokens.md](product/design-tokens.md):
  色・書体・余白・Badgeの見え方を決めるときの制約と、決めた値。**2026-09-02決定**

### `planning/`

Phase横断の作業順、進捗、未完了Taskを置く。

- [todo.md](planning/todo.md): 開発ロードマップとチェックリスト

### `development/`

Phaseをまたいで利用する開発・依存更新・Repository運用の手順を置く。

- [architecture.md](development/architecture.md):
  層とimportの向き、**状態の寿命（どこに置くかは何についての事実かで決まる）**、外部依存と
  2秒間隔の出所、Card Digger固有語と一般名の対応、Marketplace追加時に触る場所
- [mercapi-fork-operations.md](development/mercapi-fork-operations.md):
  Fork作成、upstream取込、Card Diggerの依存SHA更新、切戻しの手順
- [test-policy.md](development/test-policy.md):
  用語、Testの目的と役割、Test層、Framework、配置、Fixtureの匿名化規則、実行時期、完了判定
- [ci-policy.md](development/ci-policy.md):
  CIで実行する範囲、PR運用、Merge基準、Branch保護

### `retrospectives/`

うまくいかなかったことと、そこから何を学んだかを置く。**実装のための文書ではない。**

- [2026-09-01-verification-pitfalls.md](retrospectives/2026-09-01-verification-pitfalls.md):
  ライブ受入検証が全項目100%で合格した後に見つかった、6つの測定上の落とし穴と対策

仕様・手順の正本は各仕様書に置き、この配下には**判断の経緯と教訓だけ**を書く。
古くなっても消さない。当時そう考えたという記録自体に価値があるため。

### `phase-0/`

Mercari取得方式の技術検証、選定、Adapter設計を置く。

- [poc-validation.md](phase-0/poc-validation.md): 3方式の共通検証条件
- [phase-0-e-selection.md](phase-0/phase-0-e-selection.md): `mercapi`選定の根拠と制約
- [phase-0-f-auction-validation.md](phase-0/phase-0-f-auction-validation.md):
  通常出品とAuctionの判定・価格・終了時刻を確認する追加検証計画
- [phase-0-f-adapter-spec.md](phase-0/phase-0-f-adapter-spec.md): ForkとAdapterの実装仕様
- [phase-0-f-live-acceptance.md](phase-0/phase-0-f-live-acceptance.md):
  実Mercariへ接続するライブ受入検証（L4）の条件、手順、合格基準
- [phase-0-f-live-acceptance-result.md](phase-0/phase-0-f-live-acceptance-result.md):
  2026-09-01に実施したライブ受入検証（L4）の実測値と判定

## 配置ルール

- Productの振る舞い・受入条件は`product/`
- **画面が増えたら、その画面の仕様は`product/<画面>-spec.md`へ分ける**（[下記](#画面が増えたときmvp-specへ足さない)）
- Phaseをまたぐ計画・進捗は`planning/`
- Phaseをまたぐ開発・依存・Repositoryの運用手順は`development/`
- 特定Phaseだけで使う調査・技術判断・実装仕様は`phase-N/`
- 失敗の経緯と教訓は`retrospectives/`（実装の正本にはしない）
- PoCの実行コードと方式別結果は引き続きRepository直下の`poc/`
- **検証結果は、それを出したコードの隣に置く**（[下記](#検証結果はそれを出したコードの隣に置く)）
- `docs/`直下には、このIndex以外の文書を増やさない
- 同じ決定を複数文書へ複製せず、正本へのLinkを置く
- **進捗の`- [ ]`は`planning/todo.md`だけに置く**（[下記](#checkboxは3種類ある)）
- 「何をテストするか」は各仕様書、「どうテストするか」は`development/test-policy.md`
- 「どんな構造で、どの語が何を指すか」は`development/architecture.md`
- 「いつ自動実行し、何を満たしたらMergeするか」は`development/ci-policy.md`

### 画面が増えたとき、`mvp-spec`へ足さない

**2026-09-05に決めた。** [mvp-spec.md](product/mvp-spec.md)は自分の対象を
「Search MVP、Seller画面、Seller Knowledge Indicator」と宣言している。
**新しい画面をここへ足すと、その1文が言えなくなる。**

| 書くもの | どこ |
|---|---|
| **MVPの3画面への変更** | [product/mvp-spec.md](product/mvp-spec.md)。Phase 1クローズ後も、この3画面ならここ |
| **新しい画面** | **`product/<画面>-spec.md`（新規）** |
| 画面をまたぐ色・書体・余白 | [product/design-tokens.md](product/design-tokens.md) |
| 層・Port・依存の向き・外部アクセスの条件 | [development/architecture.md](development/architecture.md) |

**新しいPortを足すのも`architecture.md`である。** 画面の仕様書に層の判断を書かない。

### 検証結果は、それを出したコードの隣に置く

**2026-09-05に明文化した。** それまで実態としてそう置かれていたが、規則がどこにも無く、
「方式別結果は`poc/`」としか書いていなかった。**`condition-result.md`も`photos-result.md`も
「方式別結果」ではない**（方式はもう1つに決まっている）ので、規則が答えられていなかった。

| 検証の種類 | 結果の置き場所 | 例 |
|---|---|---|
| **`poc/`のProbeが出した** | **そのProbeの隣** | [poc/mercapi/condition-result.md](../poc/mercapi/condition-result.md) |
| **`src/`を動かして測った**（L4を含む） | **`docs/phase-N/`** | [phase-0-f-live-acceptance-result.md](phase-0/phase-0-f-live-acceptance-result.md) |
| **コードが無い。利用者が使って測った** | **`docs/phase-N/`** | Phase 2の「説明文に地雷が何割書かれているか」 |

**理由は再実行である。** Probeは何度も走らせるものなので、コードと結果が離れていると
「どのコードがこの数字を出したか」を毎回探すことになる。
コードが無い測定にはその相手がいないので、Phaseの文書が引き受ける。

**判断の要約はこれらへ複製しない。** [planning/todo.md](planning/todo.md)と各仕様書からLinkする。

## checkboxは3種類ある

**混ぜると、終わった作業が未完了に見える。** 2026-09-02に4文書へ散っていた進捗を
`planning/todo.md`へ寄せたときに、この区別を決めた。

| 種類 | 性質 | 置き場所 |
|---|---|---|
| **作業の進捗** | 一度潰したら終わり | **`planning/todo.md`だけ** |
| **使い回すチェックリスト** | **実行のたびに使う。永久に`[ ]`が正しい** | その手順の文書 |
| **受入条件** | 完了の定義 | その仕様の文書 |

2つ目を`todo.md`へ寄せてはならない。Fork運用手順やMerge基準は「次に作業するとき開くもの」で
あって進捗ではなく、todoへ混ぜると使いたいときに見つからない。

| 例 | 種類 |
|---|---|
| [todo.md](planning/todo.md)のPhase別Task | 進捗 |
| [ci-policy.md](development/ci-policy.md)のMerge基準 | 使い回す |
| [test-policy.md](development/test-policy.md)の「Testを追加するとき」 | 使い回す |
| [mercapi-fork-operations.md](development/mercapi-fork-operations.md)の手順 | 使い回す |
| [phase-0-f-live-acceptance.md](phase-0/phase-0-f-live-acceptance.md)の実施前確認 | 使い回す |
| [検証の落とし穴](retrospectives/2026-09-01-verification-pitfalls.md)の指標を疑う問い | 使い回す |
| [mvp-spec.md](product/mvp-spec.md)のMVP完了条件 | 受入条件 |
| 各Phaseの「効率的に絞れるか」（[§20](product/concept.md#20-効率的かは利用者にしか答えられない2026-09-05決定)） | 受入条件。**Phaseごとに1つ置き、利用者が答える** |
| [phase-0-e-selection.md](phase-0/phase-0-e-selection.md)の`[x]` | 受入条件（達成済み） |

**仕様書は「何をTestするか」を定義するが、済んだかどうかは追わない。** それは進捗であり、
[todo.md](planning/todo.md)が持つ。
