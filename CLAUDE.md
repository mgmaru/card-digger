# Card Digger

Mercariの大量出品・引退品を検索し、画像で一次選別し、SellerがTCGに詳しそうかを確認する道具。
**単一利用者のLocal実行。** 認証もDatabaseも持たない。

## まず読むもの

**[docs/README.md](docs/README.md)が文書の索引であり、どの文書が何を引き受けるかを定義している。**
ここに要点を複製しない。役割が決まっているので、迷ったらそこを見る。

| 知りたいこと | 正本 |
|---|---|
| 今やること・進捗 | [docs/planning/todo.md](docs/planning/todo.md) |
| 機能・画面・API・完了条件 | [docs/product/mvp-spec.md](docs/product/mvp-spec.md) |
| 色・書体・余白 | [docs/product/design-tokens.md](docs/product/design-tokens.md) |
| 層・依存の向き・固有語 | [docs/development/architecture.md](docs/development/architecture.md) |
| CI・PR・Merge・Branch | [docs/development/ci-policy.md](docs/development/ci-policy.md) |
| Testの層と運用 | [docs/development/test-policy.md](docs/development/test-policy.md) |

## 破りやすい約束

どれも文書に根拠がある。**変えるときは、その文書を同じ変更で直す。**

- **進捗の`- [ ]`は`docs/planning/todo.md`だけに置く。** 仕様書は「何をやるか」を定義し、
  済んだかは追わない（[配置ルール](docs/README.md#checkboxは3種類ある)）
- **`src/` `poc/` `tools/` `.github/`はPull Requestを経由する。** `docs/`と`README.md`は
  `main`へ直接pushしてよい（[§4](docs/development/ci-policy.md#4-pr運用)）
- **Merge後もBranchを消さない。** Squashで潰れる前のcommitはBranchにしか残らない
  （[§5](docs/development/ci-policy.md#5-merge基準)）
- **Mercariへは同時実行1・開始間隔2秒以上。** 根拠が無い保守的な値だが、緩める理由も無い
  （[§4.1](docs/development/architecture.md#41-外部アクセスの条件と2秒間隔の出所)）
- **L4（ライブ受入検証）だけが実Mercariへ接続する。** 手動・低頻度。CIから絶対に呼ばない
- **`uvicorn`に`--workers`も`--host 0.0.0.0`も付けない**（[src/backend/README.md](src/backend/README.md)）

## 動かす

```bash
# Frontend（http://127.0.0.1:5173）
cd src/frontend && npm run dev

# Backend（http://127.0.0.1:8000）
cd src/backend && uv run uvicorn --factory card_digger.api.main:create_app --reload

# Backend（Mercariへ通信しない。E2E受入Flowと、画面だけ触りたいとき）
cd src/backend && uv run uvicorn --factory scripts.acceptance_app:create_acceptance_app --reload
```

CIと同じ検査をローカルで通すとき。

```bash
cd src/frontend && npm ci && npm run typecheck && npm run test && npm run build
cd src/backend  && uv run --frozen pytest tests
python3 tools/check_docs_links.py
```

## 文書を書くとき

**同じ判断を2か所に書かない。** 迷ったら「この文書は何を引き受けるか」を1文で言う。
言えなければ置き場所が間違っている。値を書くときは**選んだ理由と出所**を添える。
