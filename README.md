# Card Digger

大量出品・引退品の中から、確認する価値が高いトレーディングカード商品を効率よく絞り込むための、マーケットプレイス検索・出品者分析ツールです。

Phase 0-A〜0-Eの技術検証を完了し、Mercari取得には **`kynacio/mercapi`方式**を選定しました。
Phase 0-FとMVPの実装仕様を確定し、現在は管理下の`mercapi` Forkを準備する段階です。
Seller商品の状態別ページングは、検証済みコミットを基準にしたForkへ追加します。

## ドキュメント

- [アプリコンセプト](docs/concept.md)
- [開発ロードマップ / TODO](docs/todo.md)
- [Phase 0 共通検証プロトコル](docs/poc-validation.md)
- [Phase 0-E Mercari取得方式の選定結果](docs/phase-0-e-selection.md)
- [Phase 0-F Mercari Adapter実装仕様](docs/phase-0-f-adapter-spec.md)
- [MVP実装仕様](docs/mvp-spec.md)

## リポジトリ構成

```text
card-digger/
├── README.md
├── docs/
│   ├── concept.md
│   ├── todo.md
│   ├── phase-0-e-selection.md
│   ├── phase-0-f-adapter-spec.md
│   └── mvp-spec.md
├── poc/
│   ├── common/        # 共通条件・結果テンプレート
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

Phase 0-F実装開始前の時点では、リポジトリ共通の依存パッケージや必須環境変数はありません。
実装時はBackend / Frontendの依存を固定し、秘密情報が必要になった場合は`.env`を直接共有せず、
値を含まない`.env.example`を追加します。

## 開発方針

1. 3つの取得方式を同じ条件で検証した
2. 必要な商品・Seller情報を取得できる方式として`kynacio/mercapi`を選定した
3. 選定方式をMercari Adapterの内側に閉じ込める仕様を確定した
4. 検索・画像一覧・Seller分析を備えたMVPを実装する

検証条件と採用基準の詳細は [TODO](docs/todo.md) を参照してください。

## 注意事項

検証対象には非公式API Wrapperやブラウザ自動化が含まれます。実装・運用時は対象サービスの利用規約を確認し、アクセス頻度、認証情報、取得データを適切に扱ってください。
