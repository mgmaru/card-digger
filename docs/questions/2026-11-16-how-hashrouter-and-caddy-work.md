# `HashRouter`とCaddyは、それぞれどうやってSPA fallbackの穴を扱うのか — 2026-11-16の問答

[ADR 0002 論点1の検証](../adr/0002-switch-deploy-target-by-configuration.md#検証の結果2026-11-11途中)で、
`tailscale serve`は`/sellers/abc123`を直接開くと404を返した（SPA fallbackができない）。
その手当てが**D（`HashRouter`）**と**Caddy**である。利用者が「C＋DとC＋Caddyの説明、特に`HashRouter`とCaddyの仕組み」を問い、
その答えをまとめる。Q1〜Q9が`HashRouter`、Q10〜Q14がCaddy、Q15が2つの比べ方である。

**この文書は、`HashRouter`とCaddyがどう動き、Card Diggerで何が変わるかを説明する。DとCaddy（とE）のどれを選ぶか、
なぜ選ぶかは[ADR 0002](../adr/0002-switch-deploy-target-by-configuration.md#d-ルーティングをhashrouterにしてspa-fallbackを無くすb・cと組み合わせる)が持つ。**
再読み込みでBrowserが何を捨て、なぜ404になるかは[再読み込みの問答](2026-11-15-what-a-reload-throws-away.md)にある。
この文書はその続きで、そこで説明したことは繰り返さない。

| # | 問い |
|---|---|
| Q1 | [`HashRouter`は何をするものか](#q1-hashrouterは何をするものか) |
| Q2 | [URLの`#`より後ろは、なぜサーバーへ送られないのか](#q2-urlのより後ろはなぜサーバーへ送られないのか) |
| Q3 | [ルーターは`#`の後ろをどう読むのか](#q3-ルーターはの後ろをどう読むのか) |
| Q4 | [画面の中でSellerへ移るとき、何が起きるのか](#q4-画面の中でsellerへ移るとき何が起きるのか) |
| Q5 | [`/#/sellers/abc123`で再読み込みすると、何が起きるのか](#q5-sellersabc123で再読み込みすると何が起きるのか) |
| Q6 | [JSは`/sellers/abc123`をAPIでフェッチするのか](#q6-jsはsellersabc123をapiでフェッチするのか) |
| Q7 | [「戻る」、ブックマーク、無い住所、古い形のURLではどうなるのか](#q7-戻るブックマーク無い住所古い形のurlではどうなるのか) |
| Q8 | [Card Diggerでは、どこを変えることになるのか](#q8-card-diggerではどこを変えることになるのか) |
| Q9 | [`HashRouter`にすると、何が気になるのか](#q9-hashrouterにすると何が気になるのか) |
| Q10 | [Caddyとは何か。どこに置くのか](#q10-caddyとは何かどこに置くのか) |
| Q11 | [Caddyfileはどう読むのか](#q11-caddyfileはどう読むのか) |
| Q12 | [`/sellers/abc123`で再読み込みすると、Caddyの中で何が起きるのか](#q12-sellersabc123で再読み込みするとcaddyの中で何が起きるのか) |
| Q13 | [Caddyだからできることは何か](#q13-caddyだからできることは何か) |
| Q14 | [Windowsで動かすとき、何が要るのか](#q14-windowsで動かすとき何が要るのか) |
| Q15 | [`HashRouter`とCaddyは、何が違うのか](#q15-hashrouterとcaddyは何が違うのか) |

## Q1. `HashRouter`は何をするものか

**画面の住所を、URLの`#`より後ろに置くルーターである。**`#`より後ろはサーバーへ送られないので、
サーバーは何を開かれても`/`しか頼まれない。**「知らない住所」がサーバーへ届かなくなる**ので、SPA fallbackが要らなくなる。

SPA fallbackの穴への手当ては、向きが2つある。

| 手当て | 考え方 | 「知らない住所」は |
|---|---|---|
| **D（`HashRouter`）** | **住所を、サーバーへ送られない場所に移す** | サーバーへ届かない（穴を避ける） |
| Caddy | サーバーに「知らない住所なら`index.html`」を教える | 届くが、`index.html`が返る（穴を埋める） |

| | 今（`BrowserRouter`） | D（`HashRouter`） |
|---|---|---|
| Seller画面のURL | `https://<PC名>.ts.net/sellers/abc123` | `https://<PC名>.ts.net/#/sellers/abc123` |
| ルーターが読むところ | パス（`/sellers/abc123`） | `#`の後ろ（`/sellers/abc123`） |
| 再読み込みでサーバーへ届くパス | `/sellers/abc123`（`dist/`に無い → 404） | **`/`だけ**（`dist/index.html`がある → 返る） |
| サーバーに要るもの | SPA fallback | **ファイルを配ることだけ** |

```mermaid
flowchart LR
    subgraph NOW["今：BrowserRouter"]
        direction TB
        U1["https://…/sellers/abc123"] --> S1["サーバーへ届く：/sellers/abc123"]
        S1 --> R1["dist/ に無い → 404"]
    end
    subgraph D["D：HashRouter"]
        direction TB
        U2["https://…/#/sellers/abc123"] --> S2["サーバーへ届く：/ だけ<br/>（#/sellers/abc123 は送らない）"]
        S2 --> R2["dist/index.html → 返る"]
        R2 --> J2["JSが #/sellers/abc123 を読み<br/>Seller画面を描く"]
    end
```

## Q2. URLの`#`より後ろは、なぜサーバーへ送られないのか

**`#`より後ろ（フラグメント）は、もともと「ページの中のどこを見せるか」を表す部分で、ブラウザーだけが使うものだからである。**

URLは、部分ごとに役割が決まっている。

```text
https://<PC名>.ts.net/sellers/abc123?x=1#section
└──────────┬─────────┘└──────┬──────┘└─┬┘└───┬──┘
       どこへ              パス       クエリ  フラグメント
  ←───────────── サーバーへ送る ──────────→ ←送らない→
```

| 部分 | 役割 | サーバーへ送るか |
|---|---|---|
| `https://<PC名>.ts.net` | どのサーバーへ | 送る（接続先とHostヘッダー） |
| `/sellers/abc123` | パス。サーバーの中の何か | 送る |
| `?x=1` | クエリ。サーバーへの追加の指示 | 送る |
| `#section` | **フラグメント。ページの中の位置** | **送らない** |

フラグメントの本来の使い方は、ページの中の見出しへ飛ぶことである（`#section`なら`id="section"`の見出しへ）。
ページの中の位置は、届いたページをBrowserが表示するときの話なので、サーバーは知らなくてよい。
**どのBrowserでも、HTTPの要求にフラグメントは載らない。**

`HashRouter`が使う性質は、もう1つある。**フラグメントだけを変えても、Browserはページを読み直さない。**
ページの中のリンク（`#section`）を押しても画面が白くならないのと同じである。

| 性質 | `HashRouter`での使い道 |
|---|---|
| フラグメントはサーバーへ送られない | 再読み込みしても、サーバーには`/`しか届かない（[Q5](#q5-sellersabc123で再読み込みすると何が起きるのか)） |
| フラグメントだけ変えても、ページを読み直さない | 画面を移っても、ページを捨てない（[Q4](#q4-画面の中でsellerへ移るとき何が起きるのか)） |
| フラグメントの変化も、Browserの履歴に残る | 「戻る」が使える（[Q7](#q7-戻るブックマーク無い住所古い形のurlではどうなるのか)） |

## Q3. ルーターは`#`の後ろをどう読むのか

**`#`の後ろを、今のパスと同じものとして読む。**なので、画面の型の書き方は変わらない。

2026-11-16時点の`src/frontend/package.json`の`react-router`は8.3.1である。その`HashRouter`の中身
（`node_modules/react-router/dist/development/lib/router/history.js`の`createHashHistory`）は、次のことをしている。

| 仕事 | 中身 | 例 |
|---|---|---|
| 今の住所を読む | `window.location.hash`から先頭の`#`を除き、パス・クエリ・フラグメントに分ける | `#/sellers/abc123` → パス`/sellers/abc123` |
| リンク先を作る | 行き先の前に`#`を付ける | `<Link to="/sellers/abc123">` → `href="#/sellers/abc123"` |
| 住所を変える | Browserの履歴機能（History API）の`pushState`で、`#`つきのURLを積む | アドレスバーが`…/#/sellers/abc123`になる |

読んだパスを型に当てはめる仕事は、`BrowserRouter`と同じである。`src/frontend/src/App.tsx`の`AppRoutes`の型は、そのまま使える。

```tsx
<Route path="/" element={<SearchPage />} />
<Route path="/sellers/:sellerId" element={<SellerPage />} />
```

```mermaid
flowchart LR
    A["アドレスバー<br/>https://…/#/sellers/abc123"] --> B["window.location.hash<br/>#/sellers/abc123"]
    B --> C["先頭の # を除く<br/>/sellers/abc123"]
    C --> D{"型に当てはめる"}
    D -- "/sellers/:sellerId" --> E["SellerPage<br/>sellerId = abc123"]
    D -- "/" --> F["SearchPage"]
```

| | `BrowserRouter` | `HashRouter` |
|---|---|---|
| 住所を読む場所 | `window.location.pathname` | `window.location.hash`（`#`を除く） |
| 型の書き方（`path="/sellers/:sellerId"`） | 同じ | 同じ |
| `<Link to="/sellers/…">`の書き方 | 同じ | 同じ（`#`はルーターが付ける） |
| `useParams()`で取れる値 | `abc123` | `abc123` |

## Q4. 画面の中でSellerへ移るとき、何が起きるのか

**今の`BrowserRouter`と同じく、ページを捨てずに、データだけをサーバーへ頼む。**違うのは、アドレスバーに`#`が入ることだけである。

```mermaid
sequenceDiagram
    autonumber
    actor User as 利用者
    participant JS as Card DiggerのJS<br/>（HashRouter・SellerPage）
    participant B as Browser本体
    participant TS as tailscale serve
    participant API as uvicorn＋FastAPI

    User->>B: 検索結果のSellerを押す（href="#/sellers/abc123"）
    B->>JS: クリックの通知
    Note over JS: Linkが普通のページ移動を止める
    JS->>B: pushStateでアドレスバーを<br/>…/#/sellers/abc123 にする
    Note over B,TS: ページは捨てない。サーバーへは何も送らない
    Note over JS: # の後ろ /sellers/abc123 を型に当てはめ<br/>sellerId = "abc123"
    JS->>B: Seller画面の型を描く（取得中）
    JS->>TS: GET /api/sellers/abc123/analysis
    TS->>API: そのまま渡す（/api の振り分け）
    API-->>JS: JSON
    JS->>B: Seller画面を描き直す
```

| 順番 | 誰が | 何をする | サーバーへ頼むか |
|---|---|---|---|
| 1 | JS（`Link`） | 普通のページ移動を止める | 頼まない |
| 2 | JS（ルーター） | アドレスバーを`…/#/sellers/abc123`にする | **頼まない** |
| 3 | JS（ルーター） | `#`の後ろを型に当てはめ、Seller画面の型を出す | 頼まない |
| 4 | JS（`SellerPage`） | `/api/sellers/abc123/analysis`を頼む | **頼む（データ）** |
| 5 | JS | 届いたJSONを型に流し込む | — |

`Link`が止めなかったとしても（JSが動く前に押したなど）、変わるのはフラグメントだけなので、Browserはページを読み直さない。

## Q5. `/#/sellers/abc123`で再読み込みすると、何が起きるのか

**サーバーには`/`だけが届き、`index.html`が返る。届いたJSが`#`の後ろを読み、Seller画面を描く。**

```mermaid
sequenceDiagram
    autonumber
    actor User as 利用者
    participant B as Browser本体
    participant TS as tailscale serve
    participant JS as Card DiggerのJS
    participant API as uvicorn＋FastAPI

    User->>B: …/#/sellers/abc123 で再読み込み
    Note over B: ページを丸ごと捨てる<br/>（HTML・JS・Reactの状態が消える）
    B->>TS: GET /（#/sellers/abc123 は送らない）
    Note over TS: / → dist\index.html がある
    TS-->>B: 200 index.html
    B->>TS: GET /assets/index-….js（キャッシュにあれば省ける）
    TS-->>B: JS
    B->>JS: JSを実行する
    Note over JS: アドレスバーの # の後ろ<br/>/sellers/abc123 を読む<br/>→ SellerPage、sellerId = "abc123"
    JS->>B: Seller画面の型を描く（取得中）
    JS->>API: GET /api/sellers/abc123/analysis（tailscale serve経由）
    API-->>JS: JSON
    JS->>B: Seller画面を描く
```

| 順番 | 何が起きるか | サーバーに届くもの |
|---|---|---|
| 1 | Browserがページを丸ごと捨てる | — |
| 2 | Browserがアドレスバーのページを頼む。**フラグメントは載せない** | **`GET /`** |
| 3 | `tailscale serve`が`dist\index.html`を返す | — |
| 4 | Browserが`index.html`の`<script src>`を見て、JSを頼む | `GET /assets/index-….js` |
| 5 | JS（ルーター）が`#`の後ろを読み、Seller画面の型を出す | — |
| 6 | JS（`SellerPage`）がデータを頼む | `GET /api/sellers/abc123/analysis` |
| 7 | 届いたJSONでSeller画面を描く | — |

**今の`BrowserRouter`と比べると、違うのは2と5だけである。**

| 順番 | `BrowserRouter`（今） | `HashRouter`（D） |
|---|---|---|
| 2でサーバーに届くもの | `GET /sellers/abc123` → `dist/`に無い → **404で止まる** | **`GET /`** → `index.html`が返る |
| 5でルーターが読む場所 | パス | `#`の後ろ |
| 3〜4、6〜7 | （2で止まるので起きない） | 今の画面の中の移動と同じ |

## Q6. JSは`/sellers/abc123`をAPIでフェッチするのか

**しない。JSがフェッチするのは`/api/sellers/abc123/analysis`である。**`/sellers/abc123`と`/api/sellers/abc123/analysis`は別の住所である。

| パス | 何の住所か | 使う者 | どこにあるか |
|---|---|---|---|
| `/sellers/abc123`（`#`の後ろ） | **画面**の住所 | ルーター | `App.tsx`の型（`/sellers/:sellerId`） |
| `/api/sellers/abc123/analysis` | **データ**の住所 | `SellerPage`（`useSellerAnalysis`経由） | Backendの`/api`。`tailscale serve`がuvicornへ渡す |

画面の住所は、ルーターが「Seller画面だ」「IDは`abc123`だ」と知るためのものである。そこから取り出した`abc123`で、
`src/frontend/src/api/client.ts`の`sellerAnalysis()`がデータの住所
（`` `/api/sellers/${encodeURIComponent(sellerId)}/analysis` ``）を組み立てる。

```mermaid
flowchart LR
    A["画面の住所<br/>#/sellers/abc123"] -- "ルーターが型に当てはめる" --> B["sellerId = abc123"]
    B -- "client.ts の sellerAnalysis() が組み立てる" --> C["データの住所<br/>/api/sellers/abc123/analysis"]
    C -- "fetch" --> D["uvicorn＋FastAPI"]
```

**`HashRouter`にしても、データの住所は変わらない。**`/api/...`はBrowserの`fetch`で頼むもので、ルーターを通らないからである。
`tailscale serve`の`/api`の振り分け（[手順書の5-1](../development/windows-tailscale-serve-checks.md#5-1-apiの渡し先をパスつきにする2の手当て)）もそのまま使える。

## Q7. 「戻る」、ブックマーク、無い住所、古い形のURLではどうなるのか

| 場面 | 何が起きるか |
|---|---|
| **「戻る」を押す** | `pushState`で積んだ履歴を1つ戻る。Browserが`popstate`を知らせ、ルーターが`#`の後ろを読み直して検索画面を描く。**ページは捨てない**ので、検索結果は残る（`SearchProvider`がRouterの外にあるため） |
| **ブックマークやiPhoneへ送ったURLから開く** | 再読み込みと同じ（[Q5](#q5-sellersabc123で再読み込みすると何が起きるのか)）。サーバーには`/`だけが届く |
| **`/#/foo`のような無い住所** | サーバーには`/`が届き、`index.html`が返る。ルーターが`/foo`をどの型にも当てられず、2026-11-16時点では見出しだけの空白になる。SPA fallbackを入れた場合と同じである（[再読み込みの問答 Q10](2026-11-15-what-a-reload-throws-away.md#q10-無いパスでも画面が出たら利用者はあると思ってしまわないか)） |
| **古い形のURL（`/sellers/abc123`、`#`なし）** | サーバーに`/sellers/abc123`が届き、`tailscale serve`は404を返す。`HashRouter`にする前のURLをブックマークしていた場合に起きる |
| **`#`の後ろが空（`https://<PC名>.ts.net/`）** | ルーターは`/`として読み、検索画面を描く |

```mermaid
sequenceDiagram
    autonumber
    actor User as 利用者
    participant B as Browser本体
    participant JS as Card DiggerのJS

    Note over B: 履歴：…/#/ → …/#/sellers/abc123（今ここ）
    User->>B: 「戻る」を押す
    Note over B: 履歴を1つ戻る。ページは捨てない
    B->>JS: popstateを知らせる
    Note over JS: # の後ろ / を読む → SearchPage
    JS->>B: 検索画面を描く（検索結果はメモリーに残っている）
```

## Q8. Card Diggerでは、どこを変えることになるのか

**ルーターを替える1か所と、URLの形を確かめているE2Eの1か所である。**2026-11-16時点で調べた。

| 場所 | 今 | Dにすると |
|---|---|---|
| `src/frontend/src/App.tsx`の`import` | `import { BrowserRouter, Route, Routes } from "react-router";` | `BrowserRouter`を`HashRouter`に |
| `src/frontend/src/App.tsx`の`App` | `<BrowserRouter>…</BrowserRouter>` | `<HashRouter>…</HashRouter>` |
| `src/frontend/e2e/acceptance.spec.ts`の141行目 | URLが`/sellers/<ID>`で**終わる**ことを確かめる | `#/sellers/<ID>`で終わることを確かめる |

変えなくてよいもの。

| 場所 | 変えなくてよい理由 |
|---|---|
| `AppRoutes`の型（`path="/"`、`path="/sellers/:sellerId"`） | ルーターが`#`の後ろを同じように読む（[Q3](#q3-ルーターはの後ろをどう読むのか)） |
| `<Link to="/sellers/…">`（`ItemCard.tsx`など）、`<Link to="/">`（`SellerPage.tsx`） | `#`はルーターが付ける |
| `useParams()` | 取れる値が同じ |
| `src/frontend/src/api/client.ts`（`/api/...`） | ルーターを通らない（[Q6](#q6-jsはsellersabc123をapiでフェッチするのか)） |
| Componentのテスト（`tests/SellerPage.test.tsx`など） | `MemoryRouter`の下で`AppRoutes`や画面を動かしており、`BrowserRouter`を使っていない |
| E2Eの`page.goto("/")` | `/`は今と同じく開ける |
| `tailscale serve`の振り分け | `/`をフォルダーに向けたままでよい（2026-11-11の確かめの1・2のとおり） |
| Backend | 何も知らない |

`window.location`を直接読む・書くコードや、`href="/…"`を直に書いたリンクが無いことも、2026-11-16に確かめた。

## Q9. `HashRouter`にすると、何が気になるのか

| 気になること | 中身 | Card Diggerでは |
|---|---|---|
| **URLに`#`が入る** | `https://<PC名>.ts.net/#/sellers/abc123`。見た目だけで、動きは変わらない | 利用者が見て気になるか |
| **ページの中の見出しへ飛ぶ`#`と取り合いになる** | `#`の後ろはルーターが使うので、`#section`で見出しへ飛ぶ使い方ができない | 2026-11-16時点で、そういうリンクは無い |
| **サーバーが画面の住所を知らない** | サーバーには`/`しか届かないので、サーバー側で画面ごとに何かをする（SSR、画面ごとのアクセス記録など）ことができない | Card DiggerはCSRで、サーバーは画面を知らない作り（[画面を組み立てる問答 Q5](2026-11-08-who-builds-the-screen.md#q5-画面にデータを埋め込むのはuvicornかbrowserか)）なので、失うものは無い |
| **検索エンジン** | `#`の後ろは別のページとして扱われにくい | Tailnetの中だけで使うので関係ない |
| **React Routerの位置づけ** | `HashRouter`は「サーバーの設定でSPA fallbackができないとき」の手段とされる。普通はきれいなURL（`BrowserRouter`）を使う | 今回は`tailscale serve`がSPA fallbackをできない（2026-11-11の確かめの3）。その場面にあたる |
| **前の判断を開き直す** | `BrowserRouter`は2026-09のFrontend基盤（#11）で選んだもの | ADR 0002のDの「デメリット」に書いてある |
| **古い形のURL** | `HashRouter`にする前の`/sellers/abc123`は404のまま | [Q7](#q7-戻るブックマーク無い住所古い形のurlではどうなるのか) |

**サーバー側から見ると、`HashRouter`は「どの画面か」をサーバーへ一切伝えない作りである。**
サーバーはファイルを配るだけになり、SPA fallbackを含め、画面のことを何も知らなくてよくなる。
これは、[ADR 0002](../adr/0002-switch-deploy-target-by-configuration.md#d-ルーティングをhashrouterにしてspa-fallbackを無くすb・cと組み合わせる)が
Dを「どの配り手でも動く」と書いている理由と同じことである。

## Q10. Caddyとは何か。どこに置くのか

**Caddyは汎用のWebサーバーである（nginxの仲間）。**`tailscale serve`の後ろに置き、**画面のファイルを配る役だけ**を任せる。
「知らない住所なら`index.html`」を、Caddyの設定に書く。

| | `tailscale serve` | Caddy | uvicorn |
|---|---|---|---|
| 何者か | Tailscaleに付いている入口の機能 | 汎用のWebサーバー | Pythonのアプリを動かすサーバー |
| 得意なこと | tailnetの中にHTTPSで出す。パスで振り分ける | **細かい規則でファイルを配る**。中継もできる | FastAPIを動かす |
| SPA fallback | できない（2026-11-11の確かめの3） | **できる** | （Card DiggerではAPIだけ） |

Caddyは、Go言語で書かれた実行ファイル1つ（Windowsなら`caddy.exe`）で動く。設定は`Caddyfile`という文章で書く。
HTTPS証明書を自動で取る機能が有名だが、Card Diggerでは`tailscale serve`がHTTPSを受け持つので使わない。

```mermaid
flowchart LR
    D["iPhone・Mac"] -- "https://（PC名）.ts.net/…<br/>HTTPS" --> TS["tailscale serve<br/>（入口。HTTPSを受ける）"]
    TS -- "/api/*" --> U["uvicorn<br/>127.0.0.1:8000"]
    TS -- "/*（ここが変わる）" --> C["Caddy<br/>127.0.0.1:8080"]
    C -- "読む" --> F["C:\card-digger\current\dist"]
```

| 変わるところ | 今（2026-11-11の確かめ） | C＋Caddy |
|---|---|---|
| `tailscale serve`の`/`の行き先 | `current\dist`（**フォルダー**） | `http://127.0.0.1:8080`（**Caddyというサーバー**） |
| `tailscale serve`の`/api`の行き先 | `http://127.0.0.1:8000/api` | 同じ |
| `dist`を読むのは | `tailscale serve` | Caddy |

`tailscale serve`とCaddyの間はWindowsの中だけの通信なので、HTTPでよい。Caddyは`127.0.0.1`でだけ待つので、Windowsの外から直接は届かない。

## Q11. Caddyfileはどう読むのか

画面の配信に要るのは、次の5行である（**例。2026-11-16時点で、Windowsで試していない**）。

```text
http://127.0.0.1:8080 {
    root * C:\card-digger\current\dist
    try_files {path} /index.html
    file_server
}
```

| 部分 | 呼び名 | 意味 |
|---|---|---|
| `http://127.0.0.1:8080 { … }` | サイトのアドレス | この住所に来た要求には、`{ }`の中の規則を使う。先頭が`http://`なので、HTTPSを使わず証明書も取りに行かない |
| `root * …\dist` | ディレクティブ（下準備） | ファイルを探すフォルダーを決める。`*`は「どの要求にも」 |
| `try_files {path} /index.html` | ディレクティブ（**パスの書き換え**） | 候補を順に探し、最初にあったものへ**Caddyの中だけで**パスを書き換える。**SPA fallbackの本体** |
| `file_server` | ディレクティブ（返事を作る） | 最後に決まったパスのファイルを返す |

**Caddyは、ディレクティブを書いた順ではなく、決まった順に実行する。**この5行なら「下準備（`root`）→ 書き換え（`try_files`）→ 返事を作る（`file_server`）」の順である。
`file_server`を先頭に書いても、`try_files`の後に動く。

```mermaid
flowchart LR
    R["要求<br/>GET /sellers/abc123"] --> A["root<br/>探す場所を決める"]
    A --> B["try_files<br/>候補を探し<br/>パスを書き換える"]
    B --> C["file_server<br/>ファイルを返す"]
    C --> S["返事"]
```

## Q12. `/sellers/abc123`で再読み込みすると、Caddyの中で何が起きるのか

**`try_files`が「`dist\sellers\abc123`は無い、`dist\index.html`はある」と確かめ、パスを`/index.html`に書き換える。
`file_server`が`index.html`を返す。**ブラウザーには書き換えを伝えないので、アドレスバーは`/sellers/abc123`のまま変わらない。

`try_files {path} /index.html`は、2つの仕事を1行にまとめたものである。

1. **探す:** 候補を左から順に、`root`のフォルダーの中で探す（候補1：`{path}`＝頼まれたパスそのもの、候補2：`/index.html`）
2. **書き換える:** 最初に見つかった候補に、要求のパスを書き換える

```mermaid
sequenceDiagram
    autonumber
    actor User as 利用者
    participant B as Browser本体
    participant TS as tailscale serve
    participant C as Caddy
    participant FS as current\dist<br/>（フォルダー）
    participant JS as Card DiggerのJS
    participant API as uvicorn＋FastAPI

    User->>B: …/sellers/abc123 で再読み込み
    Note over B: ページを丸ごと捨てる
    B->>TS: GET /sellers/abc123
    Note over TS: / の振り分け → Caddyへ
    TS->>C: GET /sellers/abc123
    Note over C: root：探す場所は current\dist
    C->>FS: 候補1：sellers\abc123 はある？
    FS-->>C: 無い
    C->>FS: 候補2：index.html はある？
    FS-->>C: ある
    Note over C: try_files：パスを /index.html に書き換える<br/>（Caddyの中だけ。ブラウザーには伝えない）
    C->>FS: file_server：index.html を読む
    FS-->>C: 中身
    C-->>TS: 200 index.html
    TS-->>B: 200 index.html（URLは /sellers/abc123 のまま）
    B->>TS: GET /assets/index-….js
    TS->>C: そのまま渡す
    C-->>B: JS（候補1で見つかる）
    B->>JS: JSを実行する
    Note over JS: パス /sellers/abc123 を読む<br/>→ SellerPage、sellerId = "abc123"
    JS->>API: GET /api/sellers/abc123/analysis（tailscale serve経由。Caddyは通らない）
    API-->>JS: JSON
    JS->>B: Seller画面を描く
```

要求ごとに並べると、次のとおりである。

| 頼まれたパス | 候補1（`{path}`） | 候補2（`/index.html`） | `file_server`が返すもの |
|---|---|---|---|
| `/` | `dist\`（フォルダー）→ ある | — | フォルダーの中の`index.html` |
| `/assets/index-bNhsAk3q.js` | `dist\assets\index-bNhsAk3q.js` → ある | — | そのJS |
| `/sellers/abc123` | `dist\sellers\abc123` → **無い** | `dist\index.html` → ある | **`index.html`** |
| `/assets/missing.js` | 無い | `dist\index.html` → ある | `index.html`（下の注意） |

**書き換えと転送（redirect）は違う。**

| | Caddyの`try_files`（書き換え） | 転送 |
|---|---|---|
| ブラウザーに伝えるか | 伝えない。Caddyの中だけ | 「`/`へ行け」と伝える |
| アドレスバー | `/sellers/abc123`のまま | `/`に変わる |
| 描かれる画面 | Seller画面 | 検索画面 |

**無いJSにも`index.html`が返る。**ブラウザーはHTMLをJSとして読もうとして失敗する。普段は起きないが、デプロイの途中で
古いページが新しいJSを探したときなどに起き得る。避けたければ、`/assets`の下だけfallbackしないと書ける（例）。

```text
http://127.0.0.1:8080 {
    root * C:\card-digger\current\dist
    @notAssets not path /assets/*
    try_files @notAssets {path} /index.html
    file_server
}
```

`@notAssets`は**マッチャー**と呼ぶ。「この条件に合う要求にだけ、このディレクティブを使う」という印である。
この形なら、`/assets/missing.js`は候補1で見つからず書き換えもされないので、`file_server`が404を返す。

## Q13. Caddyだからできることは何か

**配り方を細かく決められる。**代表が、[ADR 0002の共通のデメリット2](../adr/0002-switch-deploy-target-by-configuration.md#同じoriginにする選択肢b・b・cに共通するデメリット)に挙げたキャッシュの指示である。
`tailscale serve`には、この指示を書く設定が無い。

| ファイル | ブラウザーにどう使わせたいか | 理由 |
|---|---|---|
| `index.html` | **毎回、新しいか確かめさせる** | デプロイ後に古い`index.html`を使うと、古いJSを読み続ける |
| `assets\index-….js`など | **長く使わせる** | 中身が変わると名前（`-bNhsAk3q`）も変わる。同じ名前なら中身は同じ |

```text
    header /assets/* Cache-Control "public, max-age=31536000, immutable"
    header Cache-Control "no-cache"
```

（例。2行の当たり方の順番は、組むときに確かめる。）

## Q14. Windowsで動かすとき、何が要るのか

**見守るプログラムが1つ増える。**

| 要ること | 中身 |
|---|---|
| 置く | `caddy.exe`を1つ置く。インストーラーは無く、ファイルを置くだけ |
| 起動 | `caddy run --config <Caddyfileの場所>`。uvicornと同じく、タスクスケジューラーで起動時に立ち上げる。Windowsのサービスとして登録する手もある |
| 設定を変えたとき | `caddy reload`で、止めずに読み直せる |
| 管理用の口 | **Caddyは既定で`localhost:2019`に管理用の口を開く**（設定を外から変えるためのもの）。使わないなら、Caddyfileの先頭の`{ admin off }`で閉じられる |
| 入口を変える | 管理者が`tailscale serve`の`/`を`http://127.0.0.1:8080`に替える（最初の1回だけ。`tailscale serve`はデプロイ用ユーザーが変えられない） |
| 確かめ直す | Caddyを動かすアカウントで`current`のジャンクションをたどれるか。`current`を向け直したら、Caddyが新しい`dist`を配るか |
| 設定の置き場所 | `Caddyfile`と起動の手順を`deploy/windows-tailscale/`に置く（[ADR 0002 論点4](../adr/0002-switch-deploy-target-by-configuration.md#決定2026-11-09-同じリポジトリのdeployデプロイ先)） |
| 更新 | 新しい版が出たら、`caddy.exe`を手で入れ替える |
| 止まったとき | **画面が出なくなる。**APIは生きているが、画面が届かない |

```mermaid
flowchart TD
    subgraph WIN["家のWindows（常駐するもの）"]
        TS["tailscale serve<br/>（Tailscaleのサービス。管理者が設定）"]
        U["uvicorn<br/>（タスクスケジューラー）"]
        C["Caddy<br/>（タスクスケジューラー）← 増える"]
    end
    TS -- "/api" --> U
    TS -- "/" --> C
    C --> F["current\dist"]
```

## Q15. `HashRouter`とCaddyは、何が違うのか

**どちらも、再読み込みで`index.html`が届くようにする。向きが逆である。**

| | D（`HashRouter`） | Caddy |
|---|---|---|
| 考え方 | 画面の住所を、**サーバーへ送られない場所**（`#`の後ろ）に移す | **サーバーに**「知らない住所なら`index.html`」を教える |
| 「知らない住所」 | サーバーへ届かない（穴を避ける） | 届くが、`index.html`が返る（穴を埋める） |
| 仕組みが書いてある場所 | **どこにも書かれていない。**ブラウザーの性質（フラグメントを送らない）に頼る | **`Caddyfile`の`try_files`の1行に書いてある** |
| 読んで分かるか | ブラウザーの性質を知らないと、なぜ404にならないかが読み取れない | 設定を読めば分かる |
| その性質・設定は崩れるか | 崩れない。フラグメントを送らないのはURLの標準で、どのブラウザーでも同じ | 崩れない。ただし設定はCIでTestされない |
| URL | `/#/sellers/abc123` | `/sellers/abc123` |
| 変える場所 | `src/`（[Q8](#q8-card-diggerではどこを変えることになるのか)）。CIで守れる | Windowsと`deploy/`。手で確かめる |
| Windowsで常駐するもの | uvicornだけ | uvicorn＋Caddy |
| キャッシュの指示 | 書けない | 書ける（[Q13](#q13-caddyだからできることは何か)） |
| クラウドへ移るとき | どの配り手でもそのまま動く | 移り先の入口で、同じ規則を書き直す |

**利用者の見立て（2026-11-16）。**Caddyは「見つからなければ`index.html`」を明示的に書くので分かりやすい。
`HashRouter`は、ブラウザーの性質を知らないと、正しく動く理由が分からない。

この見立ては、上の表の「仕組みが書いてある場所」と「読んで分かるか」の行にあたる。`HashRouter`が頼る性質は標準で決まっているので、
**知らなくても動きは崩れない。崩れるのは、読む人の理解である。**

`tailscale serve`だけで組むE（`/`を`index.html`に向ける）も、
「知らない住所にも`index.html`」を入口の設定で表す点でCaddyと同じ向きにある。動くかは[手順書の5-2](../development/windows-tailscale-serve-checks.md#5-2-をindexhtmlに向ける5adr-0002のe)で確かめる。
