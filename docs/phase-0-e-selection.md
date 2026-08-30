# Phase 0-E — Mercari取得方式の選定結果

## 結論

- 決定日: **2026-08-30**
- 判定: **`kynacio/mercapi`方式を本採用**
- 採用する構成: **検証済みコミット`20ba68fd42677997c4c91b4e4eb17c1e7e387efa`を基準にした管理下のFork + Mercari Adapter**
- Playwrightの扱い: **仕様調査・障害診断用PoCとしてのみ保持し、MVPの実行経路には含めない**
- `marvinody/mercari`の扱い: **不採用**

Card DiggerのMVPでは、Mercariデータの取得に`mercapi`方式だけを使用する。固定版の公開
`items()`にはSeller商品の状態Filterとページングがないため、そのまま採用するのではなく、
管理下のForkで公開APIと応答モデルを小さく拡張してからMercari Adapterの内側へ閉じ込める。

この決定は、技術的な取得方式の選定である。公開・商用・継続取得を許可する判断ではなく、
それらへ進む前にはMercariの最新の利用規約と許容される利用方法を別途確認する。

## 選定対象の定義

採用対象は、単にPyPIやGitHub上の`mercapi`をそのまま呼ぶ構成ではない。次を一つの
**`mercapi`方式**として採用する。

```text
Application
    ↓
Mercari Adapter
    ↓
管理下のmercapi Fork（固定commit）
    ↓
Mercariの非公開Endpoint
```

Forkへ加える変更はSeller商品一覧の公開APIとモデルに限定する。

- `status`を呼出側で指定可能にする
- `max_pager_id`を次ページRequestへ渡せるようにする
- 商品の`pager_id`を保持する
- Responseの`meta.has_next`を保持する
- `SellerItemsPage`として`items`、`hasNext`、`nextMaxPagerId`を返す
- 空Response、Cursor欠落、重複、`has_next=false`を安全に処理する

ApplicationやDomain層からForkの固有型やPrivate Memberを直接参照しない。依存バージョンは
範囲指定ではなくcommit SHAで固定し、更新はContract Testと実測を通した明示的な操作にする。

## 根拠にした検証

次の同日実測結果を選定根拠とした。

- [`marvinody/mercari`の結果](../poc/mercari/result.md)
- [`kynacio/mercapi`の結果](../poc/mercapi/result.md)
- [Playwrightの結果](../poc/playwright/result.md)
- [共通検証プロトコル](poc-validation.md)

3方式は、キーワード`ポケカ 引退品`、販売中、`created_time ASC`、匿名アクセス、5回の
独立検索試行など、共通条件で測定されている。Phase 0-A〜0-Cは同日、同じOS / Architecture、
Proxyなしで実行され、Phase 0-Bの本測定開始からPhase 0-Cの開始までは約4時間10分だった。

## 選定基準ごとの判断

優先順位は[`docs/todo.md`](todo.md)に定義した順番をそのまま使った。点数の合計ではなく、
上位要件を満たした候補の中で、安定性、保守範囲、性能を比較した。

| 優先 | 評価項目 | `mercari` | `mercapi` + 拡張 | Playwright | 判断 |
|---:|---|---|---|---|---|
| 1 | 必要データ | 詳細0 / 20、Seller非対応 | 一覧100 / 100、詳細20 / 20、Profile 10 / 10 | 同左 | `mercari`を除外 |
| 2 | 古い販売中商品へ到達 | 5ページ目で365日超 | 7ページ目で365日超 | 1ページ目で365日超 | 3方式とも到達 |
| 3 | Seller商品一覧 | 非対応 | 応答10 / 10。Endpoint拡張で31件目以降と状態別取得を確認 | 応答10 / 10。ただしWebは3状態一括 | 状態別取得できる`mercapi`を優先 |
| 4 | 画像 | URL 100 / 100、本体20 / 20 | URL 100 / 100、本体20 / 20 | URL 100 / 100、本体20 / 20 | 差なし |
| 5 | 安定性 | 検索は成功、詳細は全件解析失敗 | 主要72 RequestがすべてHTTP 200 | 主要取得は成功、背景Errorを122件観測 | `mercapi`を優先 |
| 6 | 実装・保守 | 詳細・Sellerを広く自作する必要あり | Sellerページ公開APIへ変更を限定可能 | Browser、DOM、通信Interceptが必要 | `mercapi`を優先 |
| 7 | 性能 | 比較対象外 | 検索中央値260.85ms | 検索中央値2,279.17ms | `mercapi`が約8.7倍高速 |

### `mercapi`を選ぶ決定的な理由

1. MVPに必要な検索、商品詳細、Seller Profileの全標本を正常に解析できた。
2. Seller一覧の30件上限はMercari APIの総取得上限ではなく、固定版Wrapperの公開APIと
   モデルの不足だと切り分けられた。
3. 代表1 Sellerについて、Browser観測では`max_pager_id`による5ページ・150ユニーク件、
   `mercapi`の署名機構を使う状態別補足試験では`on_sale`と`sold_out`を個別に
   各2ページ・60ユニーク件取得できた。
4. 必要な修正点が`status`、`max_pager_id`、`pager_id`、`meta.has_next`に限定され、
   Browser方式より変更影響を狭い境界へ閉じ込められる。
5. 正式測定では401 / 403 / 429、Timeout、Parse Error、Challengeがすべて0件だった。

### Playwrightを本採用しない理由

Playwrightも必要データの取得率は高く、Seller商品を30ページ、851ユニーク件取得できた。
しかし、現行Web画面は販売中・取引中・売却済みを一括取得するため、1 / 10人で販売中商品の
独立した停止条件を満たせなかった。加えて、Browser、画面遷移、DOM、通信Intercept、複数の
非公開Endpointを保守する必要があり、検索も`mercapi`より約8.7倍遅かった。

Mercari Webが生成する有効な通信を観測できる点は有用なため、PoCコードは次の用途に限定して残す。

- Mercari側のRequest / Response仕様が変わったときの調査
- `mercapi` ForkのContractが壊れたときの比較診断
- Cursor、Header、Endpoint変更の再確認

障害時にApplicationが自動でPlaywrightへ切り替わるFallbackは実装しない。障害を隠して負荷と
保守経路を増やすためである。主要取得が壊れた場合は安全に停止し、Playwright PoCで原因を診断して
から、`mercapi` Forkまたは選定自体を見直す。

### `marvinody/mercari`を不採用にする理由

検索と古い商品への到達は成功したが、本方式を選ぶ上で重要な差別化要因だった
`created_time ASC`は機能しなかった。さらに商品詳細は現行Responseとの不整合で20 / 20件が
解析失敗し、Seller ProfileとSeller商品一覧も実装されていない。修正範囲がSellerページングだけに
留まる`mercapi`と比べ、Fork保守の範囲が大きすぎる。

## 古い順要件についての制約

**3方式ともServer側の古い順検索には失敗した。** したがって、今回の選定は「Mercari内の
販売中商品を漏れなく最古順で取得できる」と証明したものではない。

`mercapi`では7ページ・825ユニーク件を取得してから365日超の商品へ到達できたため、古い候補を
探索するためのページング能力は確認できた。一方、取得済みデータのClient側ソートでは、未取得ページに
さらに古い商品がある可能性を排除できない。

Phase 0-F / Phase 1では、次の制約を仕様とUIへ明示する。

- 検索はRequest数、最大ページ数、最大件数、実行時間を制限して収集する
- 古い順表示は**「取得した範囲内で古い順」**と定義する
- 取得範囲、最終取得ページ、最古日時、打ち切り理由を結果に保持する
- Server側の全件最古順であるかのような表示や説明をしない

この制約でMVPの価値が不足する場合は、検索範囲の拡張や別の探索方法を追加検証し、解決するまで
「Mercari全体の古い順」を製品要件として完了扱いにしない。

## 追加検証

方式選定のためにPhase 0-A〜0-Cを再実行する必要はない。ただし、選んだ構成を実装可能な状態に
するため、次をPhase 0-Fの完了条件とする。

### Phase 0-Fで必須

- 管理下の`mercapi` Forkへ`SellerItemsPage`と状態別ページングを実装する
- 固定Response Fixtureで次を自動テストする
  - 状態別Request
  - 2ページ以上のCursor引き継ぎ
  - `has_next=false`による終端
  - 空Response
  - `has_next=true`なのに末尾`pager_id`がない異常Response
  - ページ間の重複検出
  - `trading`の正規化
- ライブ検証で最大10 Sellerについて、`on_sale`と`sold_out`を個別に取得し、各状態で
  2ページ目取得または1ページ終端を確認する
- 商品検索、詳細、Profile、Seller一覧の必須FieldをContract Testで検証する
- Adapter外からFork固有型とPrivate Memberを参照していないことをテストする
- 401 / 403 / 429 / Challengeの3回連続時に停止し、認証回避を試みないことを確認する

### Phase 1開始前に仕様化する

- 検索ページングのRequest数・件数・時間上限と打ち切り理由
- 「取得範囲内で古い順」というUI表記
- `trading`を`unknown`のまま扱うか、購入不可として別状態にするか
- 日次・週次の長期安定性を確認する低頻度の監視方法

### 公開・商用・継続取得の前に必須

- [Mercariの公式ガイド](https://help.jp.mercari.com/guide/articles/900/)を含む最新の利用規約と、
  許容される利用方法を確認する
- 取得頻度、保存期間、保存項目、Seller公開情報の扱いを決める
- 大規模クロールを前提にせず、運用上の停止基準を定める

## 採用継続・再選定の基準

次のいずれかが起きた場合、Applicationから別方式へ自動切替せずアクセスを停止し、Playwright PoCで
仕様差分を診断する。

- 検索、詳細、Profile、Seller一覧の主要Endpointで401 / 403 / 429 / Challengeが3回連続する
- 必須項目の取得率が共通検証プロトコルの合格目安を下回る
- Cursor欠落や重複によりSeller一覧の安全な終端を判定できない
- Forkの修正範囲がSellerページングとResponse互換修正を超えて継続的に拡大する
- 利用規約または許容される利用方法と両立できないことが判明する

診断後も安全かつ小さな修正で復旧できなければ、Phase 0-Eの選定を再度開き、Playwrightを含む
候補を同じ共通条件で再評価する。
