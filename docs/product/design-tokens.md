# 視覚方針 — 色・書体・余白

## 文書ステータス

- 作成日: **2026-09-02**
- ステータス: **未決。決めるときの制約だけが確定している**
- 対象: 色、書体、Type scale、余白、Badgeの表現を決めるときの制約と、決めた値
- 前提: [MVP実装仕様](mvp-spec.md) / [アーキテクチャと用語](../development/architecture.md)
- 作業項目: [TODO 1-V](../planning/todo.md#1-v-視覚方針)

**まだ何も決まっていない。** [MVP仕様 §2.2](mvp-spec.md#frontend-styling2026-09-02決定)がCSS Modulesを
選んだところで止まっており、**そのCSSへ何を書くかは未決**である。

**この文書は作業一覧ではない。** 何を決めるかは[TODO 1-V](../planning/todo.md#1-v-視覚方針)が持つ。
ここが引き受けるのは**決めるときに効く制約**と、**決まった値とその理由**である。

## 1. この文書がある理由

**見た目の決定を引き受ける文書が無かった。** 既存の文書はそれぞれ別のものを引き受けている。

| 文書 | 引き受けているもの |
|---|---|
| [MVP仕様](mvp-spec.md) | 機能、画面挙動、画面に出す文言、完了条件 |
| [アーキテクチャ](../development/architecture.md) | 層、依存の向き、固有語 |
| [CIとMerge基準](../development/ci-policy.md) | Job、Merge、Branch |
| [TODO](../planning/todo.md) | **作業の進捗** |
| **この文書** | **色、書体、余白、Badgeの見え方と、その理由** |

**画面ごとに分けなかった理由。** 検索画面もSeller画面も同じ色と書体を使う。画面ごとに決めると、
2つ目へ着手するときに「決め直すのか」が分からなくなる。

## 2. 決めるときの制約

### 2.1 文言は決め直さない

**この文書は見た目だけを引き受ける。** 画面に出す日本語はMVP仕様が確定させており、
そちらが正本である。

| 確定済み | 場所 |
|---|---|
| 取得範囲・停止理由の表示 | [§5.4](mvp-spec.md#54-検索結果metadata) |
| 掲載日と更新日時の断り書き | [§5.6](mvp-spec.md#56-商品card) |
| Seller取得上限の表記 | [§6.3](mvp-spec.md#63-取得上限の表記) |
| Seller Knowledgeの表示 | [§7.7](mvp-spec.md#77-表示内容) |

`.claude/skills/frontend-design`を使うときの境界も同じで、
[そのREADME](../../.claude/skills/frontend-design/README.md)に書いてある。

### 2.2 依存を増やさない

[MVP仕様 §2.2](mvp-spec.md#frontend-styling2026-09-02決定)がCSS Modulesを選んでいる。
Component LibraryもIcon SetもWeb Fontの読み込みも、入れるならPackage表の更新と
選定理由が要る。

### 2.3 この製品は情報密度の高い道具である

Landing pageではない。**取得範囲・停止理由・限界の断り書きが常に画面に出ている**設計であり、
それらを目立たなくする方向の判断は、[MVP完了条件](mvp-spec.md#mvp完了条件)の
「Mercari全体だと誤認させる表示がない」に反する。

### 2.4 日本語で成立すること

画面の文言はすべて日本語である。欧文向けの行長・行間・字面の指針をそのまま当てられない。

### 2.5 `形式不明`を`通常出品`に見せない

[MVP仕様 §5.6](mvp-spec.md#56-商品card)のBadgeは3種ある。

```text
通常出品 / オークション / 形式不明
```

**`形式不明`が`通常出品`に見えると、進行中の入札を、そのまま払える価格の隣に並べることになる。**
[アーキテクチャ §5.3](../development/architecture.md#53-一般名を持たない固有語)の
`SaleFormat.UNKNOWN`を`FIXED_PRICE`へ畳まない理由と同じである。

### 2.6 品質下限

[MVP仕様 §3.3](mvp-spec.md#33-共通ui)が要求している。Keyboard focusが見えること、
`prefers-reduced-motion`を尊重すること、Mobile / Desktopの両方で使えること。

## 3. 決めた値

**未決。** 決まった時点でここへ書く。**値だけを書かず、選んだ理由を必ず添える。**

| 項目 | 値 | 選んだ理由 |
|---|---|---|
| 基本の色 4〜6 | 未決 | |
| `partial=true`の警告色 | **未決**（[§5.4](mvp-spec.md#54-検索結果metadata)は「警告色」としか書いていない） | |
| 書体 | 未決 | |
| Type scale | 未決 | |
| 余白の段階 | 未決 | |
| Grid列数（Mobile / Desktop） | 未決 | |

値はCSS変数として1か所へ置く。この表とCSSは同じ変更で直す。
