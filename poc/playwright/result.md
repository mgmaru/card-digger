# PoC検証結果: `Playwright`

## 結論

- 実行日: **2026-08-30 18:06:17〜18:09:01 JST**
- 判定: **`条件付き`（Fallback / 診断手段として有用。本採用は非推奨）**
- 要約:
  - 匿名・Headless Chromeの検索は5 / 5成功した。各試行119〜120件、検索時間中央値2,279.17msだった。
  - `/v2/entities:search`のJSONを取得し、Web URLの`page_token=v1:1`からBrowser自身に次ページ通信を送らせた。2ページで238ユニーク件、重複0件を取得した。
  - 最初の100件に365日超の商品が2件あり、最古は`2024-04-15T10:22:28+09:00`だった。
  - 一覧の必須項目・画像URL・出品日時・Seller IDは各100 / 100、詳細のコンディション・いいね数は各20 / 20、匿名画像GET・実デコードは20 / 20、Seller Profile・名前は各10 / 10成功した。
  - Seller商品一覧は30ページ、延べ851ユニーク件、Seller内重複0件を取得した。10 / 10人で2ページ目取得または1ページ終端を判定し、20個の`max_pager_id`がすべて前ページ末尾`pager_id`と一致した。
  - ただし検索Request / Responseが`SORT_CREATED_TIME + ORDER_ASC`を保持していても、238件の隣接237組中152組で日時が逆転し、古い順ではなかった。
  - Seller Web画面は`status=on_sale,trading,sold_out`を一括指定する。状態別に分類はできたが、1人は売却済み100件上限へ先に達し、販売中が16件のまま独立停止条件まで進めなかった。純粋なPlaywright画面操作では状態ごとの取得枠を保証できない。
  - 主要Endpointの401 / 403 / 429とChallengeは0件。一方、Webアプリの背景通信では匿名Affiliate確認403が64件、関連する商品候補400が39件、Campaign 404が19件発生した。主要データ取得には影響しなかったが、Browser方式固有のNoiseと通信量になる。
  - `mercapi`拡張案は同じSeller Endpointを状態別に取得でき、検索中央値260.85msでBrowserも不要である。必要な拡張範囲が`status`、`max_pager_id`、`meta.has_next`、`pager_id`に限定されるため、本採用は`mercapi`拡張案を優先し、Playwrightは仕様調査・回帰診断用に残すのが妥当と判断した。

## 判定根拠

| 採用候補の条件 | 結果 | 判定 |
|---|---|---|
| 匿名・Headlessで安定検索 | 5 / 5成功 | ○ |
| 100件以上取得 | 2ページ、238ユニーク件 | ○ |
| 365日超へ到達 | 最初の100件に2件 | ○ |
| Server側の古い順 | 152 / 237組で日時逆転 | **×** |
| 必要な商品情報 | 一覧100 / 100、詳細20 / 20 | ○ |
| 画像本体 | 匿名GET・デコード20 / 20 | ○ |
| Seller Profile | 10 / 10 | ○ |
| Seller 31件目以降 | 9 / 10人で31件以上。残り1人は11件で終端 | ○ |
| Seller状態別の分類 | 販売中334、売却済み455、取引中62 | ○ |
| Seller状態ごとの独立ページング | Webは3状態一括。1 / 10人で販売中の独立停止条件未達 | **×** |
| Cursor / 終端 | Cursor 20 / 20一致、3人で`has_next=false` | ○ |
| Browserコスト・保守範囲 | 検索約2.3秒、実コード1,883行、DOM / 通信Intercept依存 | △ |

必要データを取得する能力は十分にある。しかしCard DiggerのSeller Knowledgeでは販売状態ごとの取得枠と
再現可能なページングが重要であり、Browser画面の一括Filterは不利である。速度、依存範囲、実装量まで
含めると、Phase 0-Bで確認した`mercapi`の小規模な公開API拡張の方がAdapter基盤に適している。

## 実行環境

| 項目 | 値 |
|---|---|
| Git commit | `4d6664c40ebe6d749f0d411c2c2c173dfe1fccb8` |
| OS / Architecture | `Linux 6.18.33.2-microsoft-standard-WSL2 / x86_64` |
| Runtime | `Node.js v23.6.1` |
| Browser | `Google Chrome 144.0.7559.109` |
| Playwright | `1.55.1` |
| Image decoder | `sharp 0.35.4` |
| TypeScript / Node types | `5.9.2` / `24.3.0` |
| Browser mode | Headless |
| Login / persistent Cookie / explicit Token / Proxy | すべて不要 |
| Resource blocking | Browser内の`image` / `media` / `font` |
| Command | `cd poc/playwright && npm run poc` |
| 全体実行時間 | **164.74秒** |
| npm audit | High以上を含め0件 |

検証開始時点のHEADを記録した。作業ツリーにはPhase 0-BとPhase 0-Cの未コミットファイルがある。
Playwright付属Browserはダウンロードせず、System Chromeを`executablePath`で指定した。

## 検索条件

- Conditions: [`../common/conditions.json`](../common/conditions.json) schema version 2
- Keyword: `ポケカ 引退品`
- Status: `STATUS_ON_SALE`
- Sort / Order: `SORT_CREATED_TIME` / `ORDER_ASC`
- Category / price: 指定なし
- Locale / timezone: `ja-JP` / `Asia/Tokyo`
- Authentication: ログインなし
- 正式測定の自動再試行: 0回
- 外部操作の開始間隔: 2秒以上
- Browser操作の同時実行: 1

### 共通条件との差異

実Browser内ではDocument、JavaScript、API等のSubresourceをMercari Webが並行取得するため、個々の
外部Requestを同時実行数1には固定できない。Browserで開始する検索、商品詳細、Seller画面操作と匿名画像GETは
直列化し、開始間隔を2秒以上とした。不要な画像・動画・Fontは遮断した。この差異のため、速度はWrapperの
単一API Requestと完全に同条件ではない。

検索は1ページ目で主要停止条件を満たした。真のページング可否を確認するため、`nextPageToken=v1:1`を
Web URLの`page_token`へ渡して2ページ目を補足取得した。直接API Requestを再構成せず、Browser自身が
DPoPを生成した通信だけを測定した。

Seller画面には販売状態切替Controlがなく、Requestは3状態一括だった。共通プロトコルに従いResponse取得後に
`listingStatus`で分類した。状態ごとの独立上限を厳密には守れない点は成功扱いで隠さず、制約として記録する。

## 検索安定性

各試行は新しいNode.js Process、Browser、Contextで実行した。自動再試行は行っていない。

| 試行 | 成否 | 取得件数 | 必須項目あり | 検索時間ms | Process全体ms | Browser起動ms | API / Navigation | エラー |
|---:|---|---:|---:|---:|---:|---:|---|---|
| 1 | 成功 | 119 | 119 | 2,279.17 | 2,403.75 | 72.14 | 200 / 200 | なし |
| 2 | 成功 | 119 | 119 | 2,455.45 | 2,566.71 | 62.47 | 200 / 200 | なし |
| 3 | 成功 | 119 | 119 | 2,085.38 | 2,197.37 | 64.37 | 200 / 200 | なし |
| 4 | 成功 | 120 | 120 | 2,257.17 | 2,367.57 | 60.98 | 200 / 200 | なし |
| 5 | 成功 | 119 | 119 | 2,295.01 | 2,407.26 | 64.91 | 200 / 200 | なし |

- 検索成功率: **5 / 5 = 100%**
- 検索時間 中央値 / 最大: **2,279.17ms / 2,455.45ms**
- Process全体 中央値 / 最大: **2,403.75ms / 2,566.71ms**
- Browser起動 中央値 / 最大: **64.37ms / 72.14ms**
- 検索Endpointの401 / 403 / 429、Timeout、Parse Error、Challenge: **各0件**

`mercapi`の検索中央値260.85msに対し、Playwrightは約8.7倍だった。Browser起動自体は約64msだが、
Mercari WebのDocument / Script読込と検索API発火を待つ時間が支配的である。

## 検索ページング

| Page / Cursor | HTTP | 取得 | 新規 | 重複 | 累計 | ページ内最古（JST） | 次Cursor | 古い商品 |
|---|---:|---:|---:|---:|---:|---|---|---|
| 1 / `""` | 200 | 120 | 120 | 0 | 120 | 2024-04-15 10:22:28 | `v1:1` | あり |
| 2 / `v1:1` | 200 | 118 | 118 | 0 | 238 | 2026-02-28 16:19:18 | `v1:2` | なし |

- 主要停止理由: 1ページ目で100ユニーク件以上、かつ365日超へ到達
- 補足停止理由: 2ページ目取得成功後に停止
- 全出現 / ユニーク / 重複: **238 / 238 / 0**
- 100件以上取得: **成功**
- 365日以上前へ到達: **成功（最初の100件に2件）**
- Client側ソート: **なし**
- Server側の古い順: **失敗**

### Browser通信で確認した検索Cursor

Page 1のRequest / Response要点:

```text
POST https://api.mercari.jp/v2/entities:search
pageSize: 120
pageToken: ""
searchCondition.sort: SORT_CREATED_TIME
searchCondition.order: ORDER_ASC
searchCondition.status: [STATUS_ON_SALE]

response.meta.nextPageToken: v1:1
```

Page 2は次のWeb URLを開いた。

```text
https://jp.mercari.com/search?...&page_token=v1%3A1
```

Browserが生成したPOST Bodyの`pageToken`は`v1:1`、Responseは`nextPageToken=v1:2`だった。
URL ParameterをBrowser側Requestへ正しく引き継げるため、真のCursorページングを再現できる。

### `created_time ASC`の検証

- RequestとResponseの両方で`SORT_CREATED_TIME / ORDER_ASC`を確認した。
- 238件の隣接237組中、後続商品の日時が前商品より古くなる逆転が**152回**あった。
- 取得1件目は2026-08-28で、直後には2026-08-30の商品が並んだ。
- 全体最古の2024-04-15商品はPage 1の途中に現れた。
- Page 2の最古は2026-02-28で、Page 1の最古より新しい。

したがってParameterが受理・反映表示されることと、検索結果が実際に昇順になることは別である。
クライアント側で238件を並べ替えることは可能だが、未取得範囲の最古商品を保証しないため代替とはしない。

## 取得データ例

| # | 商品ID | タイトル | 価格 | 出品日時（JST） | 状態 |
|---:|---|---|---:|---|---|
| 1 | `m54727136082` | ポケモンカードまとめ売り メガフラエッテsar 引退品 汎用カード ar | ¥4,300 | 2026-08-28 18:56:23 | `on_sale` |
| 2 | `m52864126919` | ポケカ引退汎用まとめ売り | ¥20,000 | 2026-08-30 18:04:42 | `on_sale` |
| 3 | `m59074798153` | ポケモンカード ヤヤコマ シール 3枚セット ポケカ | ¥500 | 2026-08-30 18:03:59 | `on_sale` |
| 4 | `m74763733816` | ポケモンカード 映画公開記念ランダムパック2009 3枚セット | ¥2,800 | 2026-08-30 18:03:47 | `on_sale` |
| 5 | `m14993320915` | 【引退品】ポケモンカード AR 被りなしまとめ売り | ¥160,000 | 2026-08-30 18:03:43 | `on_sale` |

365日超の商品は次の2件だった。

| 商品ID | タイトル | 価格 | 出品日時（JST） |
|---|---|---:|---|
| `m77751020781` | ポケモンカード プレミアムトレーナーボックスex パック無し カードのみ | ¥4,555 | 2024-09-29 21:04:42 |
| `m32189609501` | 【新品】ポケモンカード スタートデッキ&スターターセット | ¥5,800 | 2024-04-15 10:22:28 |

検索関連度自体は取得方式比較の合否外だが、固定Keywordと直接関係が薄いタイトルも含まれた。
MVPでは除外Keyword・関連度Filterが別途必要になる。

## データ取得率

一覧項目は取得順の最初の100ユニーク商品を母数とする。

| 項目 | 成功数 / 母数 | 取得率 | 取得元フィールド | 補完・生成方法 |
|---|---:|---:|---|---|
| 商品ID | 100 / 100 | 100% | 検索`items[].id` | なし |
| 商品タイトル | 100 / 100 | 100% | 検索`items[].name` | なし |
| 価格 | 100 / 100 | 100% | 検索`items[].price` | Integer化 |
| 商品URL | 100 / 100 | 100% | `id`, `itemType` | Mercari / Shops別に生成 |
| 商品画像URL | 100 / 100 | 100% | `thumbnails`, `photos[].uri` | HTTPS URLを重複排除 |
| 出品日時 | 100 / 100 | 100% | 検索`items[].created` | UNIX秒→RFC 3339 |
| 販売状態 | 100 / 100 | 100% | 検索`items[].status` | `on_sale`へ正規化 |
| 商品コンディション | 20 / 20 | 100% | 詳細`data.item_condition` | 詳細追加Request |
| いいね数 | 20 / 20 | 100% | 詳細`data.num_likes` | 詳細追加Request |
| Seller ID | 100 / 100 | 100% | 検索`items[].sellerId` | なし |
| 出品者名 | 10 / 10 | 100% | Profile`data.name` | Profile追加Request |

検索Responseの`isLiked`はいいね数に利用していない。0以上の整数`num_likes`だけを成功とした。

## 商品詳細

商品ページを直列に開き、`GET /items/get?id=...`のResponseを取得した。

| # | 商品ID | 詳細 | いいね | Condition ID | コンディション | 時間ms | エラー |
|---:|---|---|---:|---:|---|---:|---|
| 1 | `m54727136082` | 成功 | 2 | 4 | やや傷や汚れあり | 2,003.43 | なし |
| 2 | `m52864126919` | 成功 | 0 | 4 | やや傷や汚れあり | 1,808.04 | なし |
| 3 | `m59074798153` | 成功 | 0 | 3 | 目立った傷や汚れなし | 1,708.57 | なし |
| 4 | `m74763733816` | 成功 | 0 | 3 | 目立った傷や汚れなし | 1,705.00 | なし |
| 5 | `m14993320915` | 成功 | 0 | 3 | 目立った傷や汚れなし | 1,754.86 | なし |
| 6 | `m61515849416` | 成功 | 0 | 3 | 目立った傷や汚れなし | 1,745.37 | なし |
| 7 | `m47131174415` | 成功 | 0 | 2 | 未使用に近い | 1,733.13 | なし |
| 8 | `m85625845287` | 成功 | 0 | 3 | 目立った傷や汚れなし | 1,694.87 | なし |
| 9 | `m77751020781` | 成功 | 6 | 1 | 新品、未使用 | 1,727.07 | なし |
| 10 | `m64101578004` | 成功 | 3 | 5 | 傷や汚れあり | 1,665.31 | なし |
| 11 | `m22797488531` | 成功 | 6 | 2 | 未使用に近い | 1,771.00 | なし |
| 12 | `m89470833207` | 成功 | 1 | 5 | 傷や汚れあり | 1,771.91 | なし |
| 13 | `m14793240291` | 成功 | 1 | 2 | 未使用に近い | 1,760.45 | なし |
| 14 | `m94461013893` | 成功 | 1 | 4 | やや傷や汚れあり | 1,590.22 | なし |
| 15 | `m52364932700` | 成功 | 1 | 1 | 新品、未使用 | 1,747.87 | なし |
| 16 | `m95680098974` | 成功 | 3 | 3 | 目立った傷や汚れなし | 1,667.35 | なし |
| 17 | `m98543269939` | 成功 | 2 | 2 | 未使用に近い | 1,580.36 | なし |
| 18 | `m44182907239` | 成功 | 3 | 6 | 全体的に状態が悪い | 1,732.02 | なし |
| 19 | `m32970383484` | 成功 | 7 | 3 | 目立った傷や汚れなし | 1,920.08 | なし |
| 20 | `m26938974057` | 成功 | 0 | 5 | 傷や汚れあり | 1,819.52 | なし |

- 詳細Endpoint成功: **20 / 20**
- いいね数取得: **20 / 20**
- コンディション取得: **20 / 20**
- Seller ID / Seller名埋込み: **20 / 20**
- 詳細時間 中央値 / 最大: **1,739.25ms / 2,003.43ms**
- 追加Request: **20**

## 画像本体取得

Cookie、Token、RefererなしのNode.js匿名GETを行い、Bodyを`sharp`で実デコードした。
Bodyは検証直後に破棄した。

| # | 商品ID | HTTP | Content-Type | Bytes | Decode | Redirect | 時間ms |
|---:|---|---:|---|---:|---|---:|---:|
| 1 | `m54727136082` | 200 | `image/webp` | 14,050 | WebP | 0 | 106.28 |
| 2 | `m52864126919` | 200 | `image/webp` | 5,728 | WebP | 0 | 18.43 |
| 3 | `m59074798153` | 200 | `image/webp` | 6,030 | WebP | 0 | 22.65 |
| 4 | `m74763733816` | 200 | `image/webp` | 8,214 | WebP | 0 | 19.38 |
| 5 | `m14993320915` | 200 | `image/webp` | 13,464 | WebP | 0 | 22.51 |
| 6 | `m61515849416` | 200 | `image/webp` | 16,854 | WebP | 0 | 25.47 |
| 7 | `m47131174415` | 200 | `image/webp` | 16,246 | WebP | 0 | 21.88 |
| 8 | `m85625845287` | 200 | `image/webp` | 9,096 | WebP | 0 | 19.30 |
| 9 | `m77751020781` | 200 | `image/webp` | 8,276 | WebP | 0 | 19.87 |
| 10 | `m64101578004` | 200 | `image/webp` | 11,470 | WebP | 0 | 18.12 |
| 11 | `m22797488531` | 200 | `image/webp` | 4,040 | WebP | 0 | 24.36 |
| 12 | `m89470833207` | 200 | `image/webp` | 8,250 | WebP | 0 | 17.91 |
| 13 | `m14793240291` | 200 | `image/webp` | 7,440 | WebP | 0 | 21.08 |
| 14 | `m94461013893` | 200 | `image/webp` | 14,534 | WebP | 0 | 18.83 |
| 15 | `m52364932700` | 200 | `image/webp` | 9,206 | WebP | 0 | 16.87 |
| 16 | `m95680098974` | 200 | `image/webp` | 12,834 | WebP | 0 | 21.89 |
| 17 | `m98543269939` | 200 | `image/webp` | 13,878 | WebP | 0 | 19.70 |
| 18 | `m44182907239` | 200 | `image/webp` | 9,438 | WebP | 0 | 18.89 |
| 19 | `m32970383484` | 200 | `image/webp` | 4,878 | WebP | 0 | 17.40 |
| 20 | `m26938974057` | 200 | `image/webp` | 9,324 | WebP | 0 | 18.13 |

- 匿名GET・デコード成功: **20 / 20（100%）**
- Format: 全件WebP
- Body size: **4,040〜16,854 bytes**
- Redirect: 0件
- Session補足試験: 不要

## Seller Profile

検索順で最初の10ユニークSellerを対象にした。個人情報を結果文書へ掲載せず、詳細はGit管理外Artifactだけに保存する。

- Profile取得: **10 / 10**
- Seller名: **10 / 10**
- 評価件数: 49〜15,906、中央値229
- 星評価: 全員5
- Score: 49〜15,672、中央値223
- `num_sell_items`: 42〜15,779、中央値202
- 追加Profile Request: **10**

## Seller商品一覧

Seller Webは次のEndpointを使用した。

```text
GET https://api.mercari.jp/items/get_items
  seller_id=[MASKED]
  limit=30
  with_auction=true
  exclude_archived_item=true
  status=on_sale,trading,sold_out
```

次ページは直前ページ末尾商品の`pager_id`を`max_pager_id`に渡し、Responseの`meta.has_next`で終端を判定した。

| Seller標本 | Page | ユニーク | 販売中 | 売却済み | 取引中 | 重複 | 最終`has_next` | 販売中停止 | 売却済み停止 |
|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| 1 | 3 | 90 | 20 | 69 | 1 | 0 | `true` | 20件到達 | 20件到達 |
| 2 | 2 | 48 | 6 | 35 | 7 | 0 | `false` | 終端 | 20件到達 |
| 3 | 3 | 90 | 65 | 24 | 1 | 0 | `true` | 20件到達 | 20件到達 |
| 4 | 2 | 60 | 27 | 24 | 9 | 0 | `true` | 20件到達 | 20件到達 |
| 5 | 1 | 11 | 5 | 5 | 1 | 0 | `false` | 終端 | 終端 |
| 6 | 3 | 90 | 56 | 30 | 4 | 0 | `true` | 20件到達 | 20件到達 |
| 7 | 3 | 90 | 46 | 44 | 0 | 0 | `true` | 20件到達 | 20件到達 |
| 8 | 4 | 120 | 16 | 104 | 0 | 0 | `true` | 他状態100件で停止 | 20件到達 |
| 9 | 4 | 102 | 17 | 83 | 2 | 0 | `false` | 終端 | 20件到達 |
| 10 | 5 | 150 | 76 | 37 | 37 | 0 | `true` | 20件到達 | 20件到達 |

- 一覧Response成功: **10 / 10**
- `on_sale`を含むResponse成功: **10 / 10**
- `sold_out`を含むResponse成功: **10 / 10**
- 合計: **30ページ、851ユニーク件**
- 状態内訳: 販売中334、売却済み455、取引中62
- Seller内重複: **0件**
- 31件以上取得: **9 / 10人**。残り1人は11件で正しく終端
- 2ページ目取得: **9 / 10人**
- 2ページ目取得または1ページ終端: **10 / 10人**
- 次ページCursor一致: **20 / 20ページ**
- `meta.has_next=false`到達: **3 / 10人**
- 販売中の有効停止条件へ到達: **9 / 10人**
- 売却済みの有効停止条件へ到達: **10 / 10人**

Seller 8では売却済みが104件に達した時点で、販売中は16件だった。一括Responseを続けると
売却済みの100件上限をさらに超えるため停止した。販売中だけを追加取得する画面Controlはなく、
この1人について状態別の独立停止条件を満たせなかった。

### Phase 0-Bとの比較

- Endpoint、`limit=30`、`max_pager_id`、`meta.has_next`、商品`pager_id`はPhase 0-B追加検証と一致した。
- Browserが送るCursorは20 / 20ページで前ページ末尾`pager_id`と一致した。
- 30件はAPIの総上限ではなく、Browserは31件目以降を継続取得できる。
- ただしBrowser Web UIは3状態一括だけで、`mercapi`署名機構の補足試験で成功した`status=on_sale`または`status=sold_out`の独立指定を行わない。
- Seller Knowledgeの状態別母数を確実に揃える用途では、`mercapi`へ状態・Cursor・終端を公開する拡張が有利である。

### Seller商品フィールド

851件についてID、タイトル、価格、URL、画像URL、出品日時、いいね数を取得できた。販売中・売却済み789件は
状態も正規化できた。`trading` 62件は共通モデルに専用状態がないため`unknown`として分離した。

## エラーとアクセス制限

主要取得Endpointと匿名画像の87 Request相当はすべて成功した。

| 対象 | 401 | 403 | 429 | Timeout | Parse Error | Challenge |
|---|---:|---:|---:|---:|---:|---:|
| 検索・詳細・Profile・Seller一覧・画像 | 0 | 0 | 0 | 0 | 0 | 0 |

一方、主要測定ContextでBrowserが自動送信した背景通信には次のErrorがあった。

| HTTP | Endpoint | 件数 | 影響 |
|---:|---|---:|---|
| 403 | `/services/affiliate/user/v1/current_user` | 64 | 匿名利用者確認。主要取得に影響なし |
| 400 | `/v2/products:search` | 39 | 関連Product候補。主要取得に影響なし |
| 404 | `/v2/campaigns/component:get` | 19 | Campaign表示。主要取得に影響なし |

この122件は商品詳細ページ等のWebアプリが自動発火した通信で、検索安定性の子Processは集計外である。
したがってBrowser方式全体の背景Error総数の下限であり、総数ではない。

安全停止の連続ErrorはCard Diggerが必要とする主要Endpointを対象に判定した。匿名Affiliate 403は
非ログイン状態を確認するOptional通信であり、主要EndpointがHTTP 200を継続していたため回避操作はせず
背景Errorとして記録した。Target Endpointの連続401 / 403 / 429、Challengeは0件で、安全停止は発動しなかった。

Rate Limit特定の負荷試験、認証回避、CAPTCHA回避、Proxy切替は行っていない。

## 再試行方法

正式測定は`--retry-count 0`で、自動再試行を行わない。補足検索試験では次を利用できる。

```bash
npm run poc -- --retry-count 1
```

これは失敗した独立検索Processを2秒以上待って1回だけ作り直す。再試行Helperは「初回失敗→2回目成功」の
Unit Testを持つ。正式結果と補足結果を混在させないため、商品詳細・Seller・画像は操作単位で自動再試行せず、
失敗分類をArtifactへ残す。401 / 403 / 429 / Challengeが3回連続した場合は再試行せず停止する。

## 実装・保守性

| 項目 | 値・根拠 |
|---|---|
| 実コード行数 | `src/*.ts` 1,883行（空行と`//`開始行を除く。物理1,999行） |
| テスト | 8件、121行 |
| Runtime直接依存 | 2（Playwright、sharp） |
| 開発直接依存 | 2（TypeScript、`@types/node`） |
| セットアップ | `npm install`、TypeScript build。System Chromeが別途必要 |
| Browser / Cookie / Token / 手作業 | Headless Browser必須。Cookie / 明示Token / Login / 手作業は不要 |
| 独自実装 | Process分離、Intercept、URL→Cursor引継ぎ、正規化、画像GET・decode、Seller DOM操作、停止条件、計測・集計 |
| テスト / 型 | Strict TypeScript、正規化・URL・再試行Unit Test |
| 依存監査 | `npm audit`: 0 vulnerabilities |
| 実装の複雑さ | **高** |
| 仕様変更への耐性 | **低〜中** |

Request署名・一時鍵を自前実装せずBrowserへ委ねられる点は強い。しかし次に依存する。

- Mercari検索・商品詳細・Profile・Seller Web画面が対象APIを発火すること
- 検索URLの`page_token`がPOST Bodyへ引き継がれること
- Seller画面に「もっと見る」Buttonが存在すること
- `/v2/entities:search`、`/items/get`、`/users/get_profile`、`/items/get_items`のResponse構造
- Chrome / Playwright実行環境とBrowser ProcessのResource

破損検知は型、必須Field、Cursor一致、重複、Challenge、Unit Testで行うが、Wrapper方式より変更影響面が広い。

## `mercapi`拡張案との比較

| 項目 | `mercapi` + Sellerページ拡張 | Playwright |
|---|---|---|
| 検索中央値 | 260.85ms | 2,279.17ms |
| Browser | 本測定は不要 | 必須 |
| 基本項目・詳細・画像 | 100% | 100% |
| Seller Profile | 10 / 10 | 10 / 10 |
| Seller 31件目以降 | Endpoint拡張で確認済み | 9人で取得、1人は11件終端 |
| 状態別Filter | Endpointで個別指定可能 | Web UIは3状態一括 |
| Cursor / 終端 | `max_pager_id` / `meta.has_next`を公開モデルへ追加 | Browser通信から取得可能 |
| 独自保守 | Wrapper公開API・Modelの小規模拡張 | Browser、DOM、Intercept、正規化Runner全体 |
| 背景通信Error | 正式測定0 | 背景403 / 400 / 404が多数 |
| 推奨用途 | 本番Adapter候補 | 調査、仕様変更時の診断、Fallback |

Playwrightの主要メリットは、Mercari Webが有効な署名・Headerを生成するため認証方式の変化へ追従しやすいこと。
一方、現時点では`mercapi`もDPoPを安定生成でき、拡張が必要なのはSellerページング情報の公開だけである。
総合するとMVP Adapterは`mercapi`拡張を優先する。

## うまくいかなかった点

1. **古い順にならない**
   - Request / Responseは`created_time ASC`を保持するが、152 / 237組で日時が逆転した。
   - 未取得範囲を保証できないため、取得後Sortは根本解決にならない。
2. **Seller状態を独立してページングできない**
   - Web UIは販売中・取引中・売却済みを一括取得し、状態切替Controlがない。
   - 1 / 10人で一方の状態が100件へ先に達し、もう一方は20件未満のまま停止した。
3. **Browser内の全通信を同時実行数1にできない**
   - 操作を直列化し不要Resourceを遮断したが、Document / Script / APIのSchedulingはWebアプリ側が行う。
4. **背景Endpointで多数のErrorが発生する**
   - 主要データは全成功したが、匿名確認や関連表示の403 / 400 / 404が122件観測された。
5. **実装量が大きい**
   - 共通測定Runnerを含め1,883実コード行で、DOMと複数Endpointの両方を保守する必要がある。
6. **検索結果件数が試行間で1件変動した**
   - 119〜120件。市場の出品・状態変化と考えられ、必須Field取得率・検索成否には影響しなかった。

## 追加検証が必要な事項

- `created_time ASC`が機能しない仕様を前提に、古い候補を実用的なRequest数で集める停止戦略を設計する。
- `mercapi`へ`SellerItemsPage`、状態Filter、`max_pager_id`、`hasNext`を追加し、Playwright実測と同じ10 Sellerで比較する。
- `trading`を`unknown`のまま扱うか、購入不可として`sold_out`側に集約するかDomain設計で決める。
- Playwrightを診断用に残す場合、固定FixtureとTarget EndpointのContract Testを追加する。
- 少数Seller、売却済み偏重Seller、販売中偏重Sellerを固定Fixture化し、一括Filter停止条件を回帰Testする。
- Browser背景Endpointを安全に遮断して通信量を減らせるか、画面機能への影響と合わせて確認する。
- 公開・商用・継続取得へ進む前に、Mercari利用規約と許容される利用方法を再確認する。

## 再現手順

リポジトリルートで実行する。

```bash
cd poc/playwright
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install
npm run typecheck
npm test
npm audit --audit-level=high
npm run poc
```

機械可読な結果は`poc/playwright/artifacts/summary.json`へ生成される。このDirectoryはSeller ID・商品IDを
含むためGit管理外である。Cookie、DPoP、Request Header、生Response、画像Bodyは保存しない。
