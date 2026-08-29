# marvinody/mercari PoC

`created_time + ASC` による古い順検索が現在も利用できるかを最短で検証するためのディレクトリです。

## 結果

[検証結果](result.md) の判定は **早期撤退** です。検索と画像取得は成功しましたが、
`created_time + ASC` は実際の出品日時を古い順に並べず、商品詳細モデルと現行レスポンスにも
互換性がありませんでした。Seller ProfileおよびSeller商品一覧のAPIも実装されていません。

## セットアップ

リポジトリルートで実行します。

```bash
python3 -m venv poc/mercari/.venv
poc/mercari/.venv/bin/python -m pip install -r poc/mercari/requirements.txt
```

## 検証を実行する

```bash
poc/mercari/.venv/bin/python poc/mercari/run.py
```

検証条件は [`../common/conditions.json`](../common/conditions.json) から読み込みます。
実行中は同時実行数1、外部リクエスト間隔2秒以上を維持し、5回の検索試行はそれぞれ新しい
Pythonプロセスで行います。401 / 403 / 429 / Challengeが3回連続すると、回避を試みず停止します。

機械可読な実行結果は `artifacts/summary.json` に出力されます。`artifacts/` はSeller情報を含む
可能性があるためGit管理外です。画像Bodyも保存しません。

## テスト

```bash
poc/mercari/.venv/bin/python -m unittest discover -s poc/mercari -p 'test*.py' -v
```

## ファイル

- `run.py`: 共通プロトコルに従う測定ランナー
- `test_run.py`: 正規化とエラー分類の単体テスト
- `requirements.txt`: 直接依存の固定
- `result.md`: 2026-08-30実測結果
