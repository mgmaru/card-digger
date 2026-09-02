# `frontend-design` — 取り込みの記録

## 何をどこから持ってきたか

| 項目 | 値 |
|---|---|
| 出所 | `claude-plugins-official` Marketplaceの`frontend-design` plugin |
| 上流 | <https://github.com/anthropics/claude-plugins-official/tree/main/plugins/frontend-design> |
| 取り込んだFile | `skills/frontend-design/SKILL.md`、`skills/frontend-design/LICENSE.txt` |
| Marketplace SHA | `0e3f501d0f4acb2a3406f645b1e0f80056c22e8c` |
| `SKILL.md` SHA-256 | `d91970639e9f5c37682ac7ab60094d35f1c7c1f38d731bd56396563aee10c1d3` |
| 取り込み日 | 2026-09-02 |
| License | Apache License 2.0（[LICENSE.txt](LICENSE.txt)）。著作権者 Anthropic |

**`SKILL.md`は一切改変していない。** Apache 2.0 §4(b)の「改変したFileに明示する」義務が
発生しないよう、Card Digger向けの補足はこのFileへ分けている。

## なぜUser領域ではなくRepositoryへ置いたか

`claude plugin install`（user scope）だと、**このRepositoryをCloneした環境にSKILLが付いてこない。**
Frontendの見た目に関する判断基準がRepositoryの外にあると、
[アーキテクチャ §1](../../../docs/development/architecture.md)が問題にしている
「決定の在り処が分からない」状態を、Design側で作り直すことになる。

`.claude/skills/`へ置けばGit管理下に入り、SKILLの変更もPRのdiffに出る。

## Card Diggerで使うときの境界

**このSKILLは視覚の方針だけに使い、画面の文言には使わない。**

[MVP仕様](../../../docs/product/mvp-spec.md)は画面に出す日本語文言そのものを確定させている
（§5.4の取得範囲表示、§5.6の掲載日の断り書き、§6.3の取得上限表記、§7.7のSeller Knowledge）。
一方`SKILL.md`の`More on writing in design`はCTAや空状態の書き方を指示するため、
そのまま適用すると確定済みの文言と衝突する。

衝突したときはMVP仕様が勝つ。**これは`SKILL.md`自身の指示でもある。**

> Where the brief pins down a visual direction, follow it exactly — the brief's own words always win.

| 使う | 使わない |
|---|---|
| 色（4〜6色）、書体、Type scale、余白 | 画面文言・Label・Error文の生成 |
| Layoutの構造、情報の階層 | §5.4 / §5.6 / §6.3 / §7.7 の確定文言の言い換え |
| `partial=true`の警告色の決定（§5.4が「警告色」としか書いていない箇所） | 取得範囲・限界の断り書きの省略や要約 |
| 品質下限（Responsive、Keyboard focus、`prefers-reduced-motion`、Contrast） | |

品質下限は[MVP仕様 §3.3](../../../docs/product/mvp-spec.md#33-共通ui)の
「Keyboardで主要操作へ到達できること」「MobileとDesktopで利用可能なLayout」と重なる。

## 更新するとき

上流が変わっても自動では追随しない。追随する場合は上表のSHAを更新し、
差分を読んでからCommitする。
