# Proof of Concept

Mercariから必要なデータを取得する3方式を、[`docs/planning/todo.md`](../docs/planning/todo.md)に
定義した共通条件で比較します。

3方式の検証と比較は完了し、Phase 0-Eでは`kynacio/mercapi`方式を選定しました。判断根拠、
未解決の古い順要件、追加検証は
[選定結果](../docs/phase-0/phase-0-e-selection.md)を参照してください。

| ディレクトリ | 検証対象 | 主な確認事項 |
|---|---|---|
| `mercari/` | `marvinody/mercari` | `created_time + ASC`、ページング、Seller ID |
| `mercapi/` | `kynacio/mercapi` | 商品検索、商品詳細、Seller Profile・商品一覧 |
| `playwright/` | Playwright経由 | 検索レスポンス取得、ページング、Headless動作 |

PoC間で実装を共有しすぎず、取得できる項目、エラー、速度、再現手順を方式ごとに記録します。

共通条件は [`common/conditions.json`](common/conditions.json)、測定方法は
[`docs/phase-0/poc-validation.md`](../docs/phase-0/poc-validation.md)、結果の書式は
[`common/result-template.md`](common/result-template.md) を使用します。
