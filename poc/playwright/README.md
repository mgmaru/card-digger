# Playwright PoC

匿名・Headless ChromeでMercari Webを開き、ブラウザ自身が行う検索・商品詳細・Seller通信の
JSON ResponseをPlaywrightで取得します。[共通条件](../common/conditions.json)に従い、検索安定性、
検索Cursor、商品詳細、画像本体、Seller Profile、Seller商品一覧を一括測定します。

## 結果

[検証結果](result.md)の判定は **条件付き** です。必要データは高い取得率で得られましたが、
`created_time ASC`は実際には古い順にならず、Seller Web画面は販売中・取引中・売却済みを
一括取得するため、状態ごとの独立した取得枠を持てません。Browser起動・画面遷移のコストと
保守範囲も`mercapi`拡張案より大きく、採用方式ではなくFallback / 診断手段として残す判断です。

## 必要環境

- Node.js 20以上
- Google Chrome（既定: `/usr/bin/google-chrome`）
- ログイン、永続Cookie、明示Token、Proxyは不要

依存は固定しています。Playwright付属Browserはダウンロードせず、System Chromeを利用します。

```bash
cd poc/playwright
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install
```

## 検証を実行する

リポジトリルートから実行します。

```bash
cd poc/playwright
npm run poc
```

正式測定は自動再試行0回です。補足試験として検索試行だけ1回再試行する場合は次を使用できます。

```bash
npm run poc -- --retry-count 1
```

別のChromeや出力先を指定する場合:

```bash
npm run poc -- \
  --chrome /path/to/google-chrome \
  --output /path/to/summary.json
```

機械可読な結果は`artifacts/summary.json`へ出力します。Seller ID、商品ID等を含むため
`artifacts/`はGit管理外です。画像Bodyはデコード直後に破棄し、保存しません。

## テスト

```bash
cd poc/playwright
npm run typecheck
npm test
npm audit --audit-level=high
```

## 実装上の安全策

- 5検索はそれぞれ新しいNode.js Process / Browserで実行
- 正式測定の自動再試行は0回
- 外部操作の開始間隔は2秒以上、同時実行は1
- Browser内の画像・動画・Font Requestを遮断
- 401 / 403 / 429 / Challengeが主要取得操作で3回連続した場合は停止
- Cookie、DPoP、Request Header、生ResponseをArtifactへ保存しない
- 匿名画像GETは30秒、最大5 Redirect、20MiB上限で`sharp`デコード

Browser内のScript / API ResourceはMercari Web自身が並行取得するため、個々のSubresourceを
同時実行数1には固定できません。この共通条件との差異と背景EndpointのErrorは結果に記録しています。

## ファイル

- `src/run.ts`: 共通プロトコルの測定・集計ランナー
- `src/search-trial.ts`: 新しいProcess / Browserで行う独立検索試行
- `src/search.ts`: 検索通信Interceptと`pageToken`ページング
- `src/details.ts`: 商品詳細通信の取得
- `src/sellers.ts`: Seller Profile・商品一覧・`max_pager_id`ページング
- `src/images.ts`: 匿名画像GETと実デコード
- `src/normalize.ts`: 共通取得モデルへの正規化
- `test/normalize.test.ts`: 正規化、URL、再試行の単体テスト
- `result.md`: 2026-08-30の実測結果
