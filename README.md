# Card Digger

大量出品・引退品の中から、確認する価値が高いトレーディングカード商品を効率よく絞り込むための、マーケットプレイス検索・出品者分析ツールです。

現在は **Phase 0（技術検証）** です。UIや本体機能の開発に入る前に、Mercariから検索結果・出品日時・画像・Seller情報などを安定して取得できる方式を比較し、1つに選定します。

## ドキュメント

- [アプリコンセプト](docs/concept.md)
- [開発ロードマップ / TODO](docs/todo.md)

## リポジトリ構成

```text
card-digger/
├── README.md
├── docs/
│   ├── concept.md
│   └── todo.md
├── poc/
│   ├── mercari/       # marvinody/mercari の検証
│   ├── mercapi/       # kynacio/mercapi の検証
│   └── playwright/    # ブラウザ経由方式の検証
└── src/               # 採用方式決定後のアプリケーション実装
```

各PoCは依存関係や実行手順が異なるため、検証に着手する段階でそれぞれのディレクトリ内に環境を構築します。

## 開発を始める

```bash
git clone https://github.com/mgmaru/card-digger.git
cd card-digger
```

Phase 0-1時点では、リポジトリ共通の依存パッケージや必須環境変数はありません。各PoCのセットアップ方法は、それぞれのREADMEに追記します。秘密情報が必要になった場合は `.env` を直接共有せず、値を含まない `.env.example` を追加します。

## 開発方針

1. 3つの取得方式を同じ条件で検証する
2. 必要な商品・Seller情報を安定して取得できる方式を1つ選ぶ
3. 外部ライブラリをMercari Adapterの内側に閉じ込める
4. 検索・画像一覧・Seller分析を備えたMVPを実装する

検証条件と採用基準の詳細は [TODO](docs/todo.md) を参照してください。

## 注意事項

検証対象には非公式API Wrapperやブラウザ自動化が含まれます。実装・運用時は対象サービスの利用規約を確認し、アクセス頻度、認証情報、取得データを適切に扱ってください。
