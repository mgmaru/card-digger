# kynacio/mercapi PoC

商品検索、商品詳細、Seller Profile、Seller商品一覧を一つのWrapperで扱えるかを、
[`../common/conditions.json`](../common/conditions.json) の共通条件で検証します。

## 結果

[検証結果](result.md) の判定は **条件付き** です。基本データ、詳細、画像、Seller Profile・
商品一覧の取得は安定して成功しました。一方、`created_time ASC`は古い順にならず、Seller商品一覧も
全状態合計30件に固定されておりページングできません。この2点を解決するまでは本採用を決定しません。

## セットアップ

リポジトリルートで実行します。`mercapi`は検証したGitコミットに固定しています。

```bash
python3 -m venv poc/mercapi/.venv
poc/mercapi/.venv/bin/python -m pip install -r poc/mercapi/requirements.txt
```

## 検証を実行する

```bash
poc/mercapi/.venv/bin/python poc/mercapi/run.py
```

実行中は同時実行数1、外部リクエスト開始間隔2秒以上を維持します。5回の検索試行はそれぞれ
新しいPythonプロセスで実行し、自動再試行はしません。401 / 403 / 429 / Challengeが3回連続した
場合は、回避を試みず残りのアクセスを停止します。

機械可読な測定結果は`artifacts/summary.json`へ出力します。`artifacts/`はSeller情報を含む可能性が
あるためGit管理外です。画像Bodyも保存しません。

## テスト

```bash
poc/mercapi/.venv/bin/python -m unittest discover -s poc/mercapi -p 'test*.py' -v
```

## ファイル

- `run.py`: 共通プロトコルに従う非同期測定ランナー
- `test_run.py`: 正規化、エラー分類、安全停止の単体テスト
- `requirements.txt`: mercapiの固定コミットと直接依存
- `result.md`: 2026-08-30実測結果
