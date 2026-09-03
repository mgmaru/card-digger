# CIとMerge基準

## 文書ステータス

- 決定日: **2026-08-31**
- ステータス: **Card DiggerとForkの両Repositoryへ適用**
- 対象: 自動実行するTestの範囲、PR運用、Merge基準、Branch保護
- Test層の定義: [Test運用規約](test-policy.md)
- Fork運用: [mercapi Fork運用手順](mercapi-fork-operations.md)

「**何をテストするか**」は各仕様書、「**どうテストするか**」は[Test運用規約](test-policy.md)、
「**いつ自動で走らせ、何を満たしたらMergeするか**」をこの文書の正本とする。

---

## 1. 目的

Testは書かれているだけでは機能しない。**実行されて初めて壊れを検知できる。**

| 課題 | CIが解決すること |
|---|---|
| 実行が人の記憶に依存する | pushとPRのたびに自動実行する |
| 依存更新のGateが形骸化する | [Fork運用手順 §6.2](mercapi-fork-operations.md#62-取込後の検証)のGateを機械が判定する |
| 赤の常態化に気付かない | 失敗が即座に見える |
| Documentの相互Linkが静かに壊れる | 見出し変更によるLink切れを検知する |

---

## 2. CIで実行する範囲

```text
L1  ForkのUnit Test        ─┐
L2  AdapterのUnit Test      ├─ CIで実行する（外部通信なし）
L3  Contract Test          ─┘
L4  ライブ受入検証           ─── CIで実行しない（実Mercariへ通信する）
```

### 絶対規則

> **CIからL4を実行しない。**
> PoCのRunner（`run.py`、`auction_probe.py`、`seller_paging_probe.py`、
> `seller_status_paging_probe.py`）をCIのどのJobからも呼ばない。
> CIは`test*.py`の探索だけを行う。

理由は[Test運用規約 §9](test-policy.md#9-ライブ受入検証l4の実施規約)のアクセス頻度条件であり、
CIの並列実行や再実行はこの条件を守れない。

---

## 3. Repositoryごとの構成

### 3.1 `card-digger`

`.github/workflows/ci.yml`。契機は`main`へのpushとPull Request。

| Job | 内容 | 導入時期 |
|---|---|---|
| `docs` | 相対Link、見出しAnchor、code fenceの検査（`tools/check_docs_links.py`） | 導入済み |
| `poc` | `poc/mercapi`のUnit Test | 導入済み |
| `frontend` | `npm ci` → `typecheck` → `test` → `build`（`src/frontend`） | **2026-09-02追加** |
| `backend` | `uv run pytest`によるL2 / L3（`src/backend`） | 導入済み |
| `e2e` | PlaywrightによるE2E受入Flow。**Chromiumのみ、390pxと1280pxの2幅** | **2026-09-03追加** |

`frontend` Jobは`src/frontend/package.json`の3つのScriptに依存する。

| Script | 中身 | 落ちたときに分かること |
|---|---|---|
| `typecheck` | `tsc --noEmit` | 型の不整合。**Testとbuildが通っても落ちうる**（[MVP仕様 §2.2](../product/mvp-spec.md#22-固定したpackage-version2026-09-02)） |
| `test` | `vitest run` | Component / 単体の失敗 |
| `build` | `vite build` | 本番Buildだけで出る設定・解決の失敗 |

Node.jsのVersionはJob内で`26`に固定する。根拠は
[MVP仕様 §2.2](../product/mvp-spec.md#22-固定したpackage-version2026-09-02)。

#### Guardは外した（2026-09-02）

`src/frontend`ができるまでの間、このJobは`package.json`の有無を見るGuardを持ち、
**緑のまま何も検査しない**期間があった。`src/frontend`を作った同じCommitでGuardを外し、
4Stepすべてが常に走るようにした。

| | Guardがあった間 | 現在 |
|---|---|---|
| `npm ci` / `typecheck` / `test` / `build` | `package.json`が無ければSkip | 常に実行 |
| 何も検査しなかったことの申告 | Workflow logへ`::warning::` | 不要になった |

> **緑であることと、検査したことは別である。** Guardを外すまでの期間はこの区別が
> 必要だった。記録として残す。形は
> [検証の落とし穴 §3](../retrospectives/2026-09-01-verification-pitfalls.md)の
> 「構造上100%にしかならない指標」と同じである。

#### `e2e` Jobを足した（2026-09-03）

**外部へ出ない。** 駆動するBackendは`scripts/acceptance_app.py`で、本番の`create_app()`へ
Mock Adapterを渡しただけのものである。[§2](#2-ciで実行する範囲)の「CIからL4を実行しない」に
触れない。

| 項目 | 値 | 理由 |
|---|---|---|
| Browser | **`chromium`だけ** | 単一利用者のLocal実行。install時間がいちばん短い |
| 幅 | **390pxと1280px** | [視覚方針](../product/design-tokens.md)が変える変数は600pxを境に4つだけ。両側を1つずつ踏めば分岐は尽きる |
| Request間隔 | **0秒** | Mercariへ出ないので守る相手がいない。2秒間隔はUnit Testが実測で守る |
| 失敗時 | traceをArtifactへ上げる（7日） | Browserの中で何が起きたかは、logだけでは分からない |

**BackendとFrontendの両方が要るのでJobを分けた。** 既存の`frontend` / `backend` Jobの
Stepにすると、片方のJobがもう片方の環境を丸ごと持つことになる。

### 3.2 `mgmaru/mercapi`

upstream由来の`.github/workflows/check.yaml`をそのまま使う。**新規に作らない。**

| Job | 内容 |
|---|---|
| `Linting` | `black --check mercapi/ tests/` |
| `Unit test` | Python 3.9 / 3.10 / 3.11 / 3.12 / 3.13で`pytest --record-mode=none` |

- Forkは既定でActionsが無効のため、一度だけ有効化が必要
- `--record-mode=none`は既定値だが、**設定変更で実通信へ化けないよう明示**する
- 使用しないworkflow（`Publish to PyPI`、`Publish to TestPyPI`、`Build and publish docs`）は
  誤実行を避けるため無効化する

---

## 4. PR運用

1人開発のため、**GitHubは自分のPull Requestを自分で承認できない。**
したがって承認者数を要求せず、機械が判定できる基準だけをGateにする。

| 変更対象 | 運用 |
|---|---|
| `src/`、`poc/`、`tools/`、`.github/` | **Pull Requestを経由する** |
| `docs/`、`README.md`、`CLAUDE.md` | `main`への直接pushを許容する |
| Fork（`mgmaru/mercapi`） | 目的ごとにBranchを分け、`--no-ff`で`main`へMergeする |

Branchは目的ごとに分ける。実装と無関係な修正を同じBranchへ混ぜない。

| 接頭辞 | 用途 |
|---|---|
| `feat/` | 機能追加 |
| `fix/` | 不具合修正 |
| `chore/` | 整形、CI設定、依存更新 |
| `docs/` | 文書のみの変更 |

---

## 5. Merge基準

次をすべて満たしたときにMergeする。

- [ ] CIのすべてのJobが成功している
- [ ] Testの結果が基準線から**悪化していない**
- [ ] 変更がBranchの目的の範囲に収まっている
- [ ] 仕様を変えた場合、対応する文書を同じ変更で更新している
- [ ] 実測値・commit SHA・判断理由を記録すべき変更では、記録が済んでいる

### 基準線の考え方

「全Green」を常に前提にしない。upstream由来の既知の失敗のように、
**こちらの責任ではない赤**が存在しうる。その場合は原因と件数を記録し、
「悪化させない」ことを基準にする。

現在の基準線は[TODO](../planning/todo.md)へ記録する。

### Merge後もBranchを消さない（2026-09-02決定）

**Merge時に`--delete-branch`を付けない。** GitHubのRepository設定
「Automatically delete head branches」も有効にしない。

[§6](#6-branch保護)がSquashまたはRebaseを要求するため、**Merge後の`main`にはBranch上の
個々のcommitが残らない。** 1つのcommitへ潰れる。Branchを消すと、潰れる前の過程を
参照する手段が無くなる。

| 残すと参照できるもの |
|---|
| 途中のcommitの分け方と、その順序 |
| 失敗した試行と、それを戻した経緯 |
| PRのDiffが指すcommit（Branchが消えると到達不能になりうる） |

**`main`の`Allow deletions`が「無効」なのとは別の話である。** あちらは`main`そのものを
消せなくする設定で、こちらはMerge済みのfeature branchの扱いを指す。

> 溜まったBranchが読みにくくなった場合は、消すのではなく命名か一覧の見方で対処する。
> **消すのは元に戻せない。**

---

## 6. Branch保護

`card-digger`の`main`へ設定する（**0-F-4で設定済み**）。

| 設定 | 値 | 理由 |
|---|---|---|
| Require status checks | **有効** | CIの成功をMergeの必須条件にする |
| Require approvals | **無効** | 1人開発では自己承認ができず、全変更が止まる |
| Require linear history | 有効 | 履歴を追いやすくする |
| Allow force push | **無効** | 参照中のcommitを到達不能にしない |
| Include administrators | **無効** | §4の「`docs/`は直接pushを許容する」を成立させる |
| Allow deletions | **無効** | `main`を消せないようにする |

必須Statusは`Docs links`、`PoC unit tests`、`Frontend unit and component tests`、
`Backend unit and contract tests`、`E2E acceptance flow`の5つとする
（2026-09-02に`Frontend`、2026-09-03に`E2E`を追加）。

> **この文書を直しただけでは、GitHubの設定は変わらなかった。** `Frontend`をこの表へ書いた時点では
> 必須Statusは3つのままで、**Frontendが赤でもMergeできる状態が残っていた。** 気付いたのは、
> `main`へのdocs直接pushでGitHubが`3 of 3 required status checks`と返したときである。
> 同日中に設定を4つへ揃えた。
>
> **設定値を書いた文書は、設定そのものではない。** 変えたら`gh api .../branches/main/protection`で
> 実際の値を確認する。

Linear historyを要求するため、Pull RequestはSquashまたはRebaseでMergeする。
Merge commitは`main`へ作らない。

Forkの`main`にも同じ考え方を適用する。ただし
[Fork運用手順 §8](mercapi-fork-operations.md#8-問題発生時の戻し方)のとおり、
Card Diggerが参照中のcommitを到達不能にしないことを最優先とする。

---

## 7. やらないこと

| 項目 | 理由 |
|---|---|
| **L4のCI実行** | アクセス頻度条件を守れない |
| Coverage率のGate | [Test運用規約 §11](test-policy.md#11-やらないこと)で除外済み |
| 定期実行（cron） | 外部通信や無人実行を常態化させない |
| Deploy / Release Pipeline | 公開Serviceではなく、単一利用者のLocal実行を前提とする |
| PRの承認必須化 | 1人開発では機能しない |
| CIからの自動Merge | 判断を機械へ委ねない |
| Secretsを要するJob | 現時点で必要な秘密情報がない |
