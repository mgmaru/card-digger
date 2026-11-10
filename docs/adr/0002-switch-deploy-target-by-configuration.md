# ADR 0002 — デプロイ先を設定だけで切り替えられる形にする

| 項目 | 内容 |
|---|---|
| 状態 | **決定（2026-11-11）。**論点2・3・4・5は2026-11-09、**論点1は2026-11-11にCに決めた。**Cの中で`tailscale serve`だけで足りるか（SPA fallbackなど）は、[Windowsでの検証](#決める前の検証windows15分ほどmercariへは通信しない)で決める |
| 決める人 | 利用者 |
| 前提とする方針 | [architecture §8 デプロイ先をソースコードに持たない](../development/architecture.md#8-デプロイ先をソースコードに持たない2026-11-08決定)（決定済み） |
| 引き継ぐもの | [ADR 0001の未決](0001-run-on-home-windows-via-tailscale.md#未決--frontendが127001を見に行く問題)（Frontendが`127.0.0.1`を見に行く問題） |

## 背景

[ADR 0001](0001-run-on-home-windows-via-tailscale.md)で、家のWindowsで動かしTailscaleで繋ぐと
決めた。ただ、**将来クラウド（Cloud Run、AWSなど）へ移る可能性がある。**利用者の要求は次のとおり。

> デプロイは設定などに逃したい。設定を変えるだけでデプロイ先を変えたい。ソースコードを直すようなことはしたくない。

この要求は[architecture §8](../development/architecture.md#8-デプロイ先をソースコードに持たない2026-11-08決定)
として方針になった。**このADRは、それをどう実現するかの選択肢を並べる。**

今のコードには、方針に反するものが1つある。`src/frontend/src/api/client.ts`の既定の接続先
`http://127.0.0.1:8000`は、画面を開いた端末とBackendが同じ機械にあるときしか正しくない。
iPhoneから開くとiPhone自身へ向かい、動かない。

## 論点は5つ

| # | 論点 | 依存 |
|---|---|---|
| 1 | [画面とAPIを、同じOriginから返すか](#論点1--画面とapiを同じoriginから返すか) | — |
| 2 | [デプロイ先固有の値を、どう渡すか](#論点2--デプロイ先固有の値をどう渡すか) | — |
| 3 | [何をデプロイするか（成果物の形）](#論点3--何をデプロイするか成果物の形) | — |
| 4 | [デプロイ先ごとのファイルを、どこに置くか](#論点4--デプロイ先ごとのファイルをどこに置くか) | — |
| 5 | [`VITE_API_BASE_URL`を残すか](#論点5--vite_api_base_urlを残すか) | 論点1 |

各論点の最後に**提案者（Claude）の推奨**を書く。**推奨であって決定ではない。**

## 論点1 — 画面とAPIを、同じOriginから返すか

### Originとは何か（レビューで出た問い）

> 別Originにするというのは、フロントエンドとバックエンドでURLを変えるということか

**URL全体ではなく、URLのうちOriginの部分（スキーム・ホスト・ポート）が違うことを指す。**
パスが違うだけでは別Originにならない。

```text
https://PC名.ts.net:443/api/search?keyword=ポケカ
└─┬──┘ └────┬────┘└┬┘└────┬────┘└──────┬──────┘
スキーム   ホスト    ポート    パス         クエリ
└────────── Origin ──────────┘
```

**3つが全部同じなら同じOrigin、1つでも違えば別Originである。**

| 画面のURL | APIのURL | 違う部分 | 判定 |
|---|---|---|---|
| `https://PC名.ts.net/` | `https://PC名.ts.net/api/search` | パスだけ | **同じOrigin**（B・C） |
| `http://127.0.0.1:5173/` | `http://127.0.0.1:8000/api/search` | **ポート** | **別Origin（今の開発構成）** |
| `https://card-digger.vercel.app/` | `https://PC名.ts.net/api/search` | **ホスト** | 別Origin（Aの典型） |
| `https://example.com/` | `https://api.example.com/search` | **ホスト**（サブドメインも別扱い） | 別Origin |
| `http://PC名.ts.net/` | `https://PC名.ts.net/api/search` | **スキーム**（とポート） | 別Origin |

**今の開発構成は、すでにポート違いの別Originである。**`src/backend/card_digger/api/main.py`の
`DEFAULT_ALLOWED_ORIGINS`がViteの5173番をCORSで許可しているのは、そのためである。

別Originかどうかで、次の2つが決まる。

| | 同じOrigin | 別Origin |
|---|---|---|
| JSがAPIの場所を書く必要 | **無い。**パスだけ書けば、Browserが今のページのOriginを補う | **ある。**Browserは補えないので、Originまで含めた絶対URLが要る（`VITE_API_BASE_URL`など） |
| CORS | 不要 | **必要。**APIのサーバーが「このOriginからの呼び出しを許す」と返さないと、BrowserはJSに結果を渡さない |

**Aが[方針](../development/architecture.md#8-デプロイ先をソースコードに持たない2026-11-08決定)に反するのは、
左の行による。**別Originでは、デプロイ先のURLをどこかに書く必要があり、それがBuild成果物に入る。

### 選択肢

| | A. 別Origin（URLを埋め込む） | B. 同じOrigin（FastAPIが画面も返す） | B′. 同じOrigin（同じProcessの中で、APIと画面の配信を分ける） | C. 同じOrigin（前段のProxyが振り分ける） |
|---|---|---|---|---|
| 中身 | Build時に`VITE_API_BASE_URL`へAPIのURLを入れる。画面は別の場所から配る | `npm run build`の`dist/`を、**APIのアプリ（`create_app()`）が**返す。JSは`/api/...`を相対パスで呼ぶ | APIのアプリと画面の配信アプリを**別々に作り**、起動の入口で`/api`と`/`に束ねる（FastAPIの`mount`）。JSは相対パス | nginx・Caddy・`tailscale serve`などが`/api/*`をuvicornへ、それ以外を`dist/`へ振り分ける。JSは相対パス |
| デプロイ先を替えるとき | **Buildし直す**（URLが焼き込まれる）。CORSの許可も変える | **何もしない** | **何もしない** | Proxyの設定を書き直す。**SPA fallbackもデプロイ先ごとに解き直す** |
| 1つのBuildが全端末で動くか | 動かない。Windows本体用とTailnet用でBuildが分かれる | **動く** | **動く** | **動く** |
| CORS | 必要 | 不要 | 不要 | 不要 |
| 動かすProcess | uvicorn＋画面の配り手 | **uvicornだけ** | **uvicornだけ** | uvicorn＋Proxy（`tailscale serve`で済めば増えない） |
| APIのコードがFrontendを知るか | 知らない | **知る**（下の「Bの問題」） | **知らない。**両方を知るのは起動の入口だけ | 知らない |
| 開発時 | 今と同じ | Viteに`/api`の中継（`server.proxy`）を足す | Bと同じ | Bと同じ |
| `src/`の変更 | `client.ts`は変えなくてよい | `client.ts`（相対パス化）、`main.py`（`dist/`配信） | `client.ts`（相対パス化）、画面の配信を別のmoduleに、起動の入口 | `client.ts`（相対パス化）だけ |
| 向いている場面 | 画面をCDN（Vercel・Netlifyなど）で配る。APIを複数のClientが使う | 画面とAPIを一緒に運用する、小〜中規模 | Bと同じ。責務を分けておきたいとき | 静的ファイルを大量に配る。Proxyが既にある |

### Bの問題 — APIがFrontendの事情を知ってしまう（レビューで出た指摘）

> APIサーバーの責務を考えた時に、フロントエンドの`dist/`の構成まで知っているのはおかしい

**指摘のとおりである。**Bでは、APIのアプリ（`create_app()`の対応表）が次の4つを知る。

| # | APIが知ってしまうこと | 本来の持ち主 |
|---|---|---|
| 1 | `dist/`というBuild成果物の場所 | デプロイ先（環境変数で外へ出せる） |
| 2 | `index.html`が入口であること | Vite（Buildツール） |
| 3 | **`/sellers/abc123`のようなURLに`index.html`を返すべきこと**（SPA fallback） | **Frontendのルーティング方式**（`BrowserRouter`を選んだこと） |
| 4 | `/api/`以外のパスはFrontendのものであること | 画面とAPIの間のURLの分け方 |

1は環境変数で外に出せるが、**2〜4はFrontendの事情**であり、APIの対応表に入るのは責務として不自然である。

### 同じOriginにする選択肢（B・B′・C）に共通するデメリット

Bの問題（責務）とは別に、**画面をBuild済みのファイルとして配る限り、どの選択肢にも残るもの。**

| # | デメリット | 重さ | 何で扱うか |
|---|---|---|---|
| 1 | **開発と本番で、画面の届き方が違う。**開発はViteの中継、本番は`dist/`の配信。**E2Eは開発の道しか通らない**ので、本番の道（SPA fallback、静的ファイル配信）が壊れても自動Testで気づけない | **大** | Build済みの`dist/`を使ってE2Eを1本流す仕組みを足す |
| 2 | **キャッシュ。**Browserが`index.html`を古いまま使うと、デプロイ後も古いJSが動く。`index.html`は毎回確認させ、ハッシュ付きの`assets/`は長く使わせる、という**Viteの出力の性質を知った設定**が要る | 中 | 画面の配り手（B′なら配信アプリ、Cならproxy）に閉じ込める。**Bだとこの知識もAPIに入る** |
| 3 | **画面だけ直しても、uvicornの再起動が要る**（B・B′）。再起動すると`MarketplaceAccess`の状態（安全停止の待ち時間など）も消える | 小 | 利用者1人なら困らない。代わりに画面とAPIの版がずれない |
| 4 | ファイルを配るので、パスの細工（`/../`）で`dist/`の外を読ませない対策が要る | 小 | Starletteの`StaticFiles`が対策を持つ。Testで固定する |
| 5 | Pythonで静的ファイルを配るのは、nginxやCDNより遅い（B・B′） | 無視できる | 利用者1人 |

### Cの補足 — 入口は何が担うか

**Windowsでは`tailscale serve`が担える見込みがある。**2026-11-09に公式ドキュメントで確かめたこと。

| 問い | 公式ドキュメントの記述 | 判定 |
|---|---|---|
| パスごとに振り分けられるか | `--set-path`でURLのパスごとに配信先を決められる | **できる** |
| ディレクトリを配れるか | 配信先にはファイル・ディレクトリ・ローカルのサービスを指定できる | **できる** |
| `/sellers/abc123`の再読み込みに`index.html`を返せるか（SPA fallback） | 記述が無い。ディレクトリは「単純な一覧として表示する」とある | **できない見込み。未確認** |
| `/api`へ渡すとき、パスの先頭（`/api`）を削るか | 公式の記述では確認できない。第三者の解説には「削る」とある | **未確認。**削られるとuvicornには`/search`が届き、APIが壊れる |

出所：[tailscale serve command](https://tailscale.com/docs/reference/tailscale-cli/serve)、
[tailscale funnel command](https://tailscale.com/kb/1311/tailscale-funnel)、
[第三者の解説](https://www.ssdnodes.com/learn/tailscale-serve-command-cheat-sheet)。

**クラウドでは、設定で組める定石がある。**

| デプロイ先 | 入口 | 静的ファイルの置き場 | API |
|---|---|---|---|
| AWS | CloudFront | S3 | App Runner・ECS |
| GCP | Firebase Hostingの書き換え規則、またはロードバランサー | Firebase Hosting、Cloud Storage | Cloud Run |

Cloud Run単体には振り分け役が無いので、コンテナの中にnginxを足す形（Processが2つになる）は避け、
上の定石を使う。**費用はまだ調べていない。**

### D. ルーティングを`HashRouter`にして、SPA fallbackを無くす（B′・Cと組み合わせる）

Bの問題の3と、Cの未確認点は、Frontendが`BrowserRouter`を使っていることから生じる。
`HashRouter`に変えると、URLは`/#/sellers/abc123`になる。**`#`より後ろはサーバーへ送られない**ので、
再読み込みしてもサーバーへの要求は`GET /`だけになり、**サーバーは普通の静的ファイル配信で済む。**

| | `BrowserRouter`のまま | D. `HashRouter`にする |
|---|---|---|
| URL | `/sellers/abc123` | `/#/sellers/abc123` |
| 再読み込みでサーバーへ行く要求 | `GET /sellers/abc123` | `GET /` |
| サーバーに要るもの | SPA fallback | **静的ファイル配信だけ** |
| どの配り手でも動くか | SPA fallbackができる配り手に限る | **どれでも動く**（`StaticFiles`、`tailscale serve`、CDN） |

D単独では選択肢にならない（画面を誰が配るかは別に決める）。**B′かCと組み合わせる。**

### メリット・デメリット

| | メリット | デメリット |
|---|---|---|
| A | `src/`の変更が最小。画面とAPIを別々の場所に置ける | **方針に反する。**デプロイ先のURLがBuild成果物に入るので、替えるたびにBuildし直す。CORSの許可も替える。Windows本体からとTailnetからで別Buildになる |
| B | 1つのBuildがどこでも動く。Processが1つなので契約1（1 Process）とも素直に合う。CORSが要らない | **APIがFrontendの事情（`dist/`、`index.html`、SPA fallback、キャッシュ）を知る。**加えて共通のデメリット1〜5 |
| B′ | Bの利点をすべて保つ。**APIのコードはFrontendを知らない。**両方を知るのは起動の入口（もともと「部品を組み立てる唯一の場所」）だけ | 部品が1つ増える（画面の配信アプリ）。共通のデメリット1〜5（2は配信アプリに閉じ込められる） |
| C | 責務の分離が最もきれい。アプリは相対パスにするだけ。静的ファイル配信はProxyの得意分野。クラウドの定石（CloudFront＋S3など）と同じ形。画面だけの変更でuvicornを再起動しない | **振り分けの設定が、デプロイ先ごとに要る**（`src/`ではない）。設定はCIでTestされない。`tailscale serve`でSPA fallbackができるかは未確認。クラウドの入口の費用は未調査。共通のデメリット1・2・4 |
| D | SPA fallbackが不要になり、配り手を選ばない。サーバー側の知識が「ファイルを配る」だけになる | **URLに`#`が入る。**ルーティング方式は2026-09のFrontend基盤（#11）で決めたもので、その判断を開き直す。既存のLinkやTestの書き換えが要る |

### 決定（2026-11-11）— C

**利用者が決めた。**画面とAPIを同じOriginから返し、**振り分けは前段の入口が担う。**Windowsでは`tailscale serve`が入口になる。
APIのアプリは画面を知らない。理由は下の「Cを推す理由」のとおり。

**Cの中身は、Windowsでの検証で決まる。**下の[検証](#決める前の検証windows15分ほどmercariへは通信しない)の結果の表のとおり、
`tailscale serve`だけで足りるか、D（`HashRouter`）かCaddyを組み合わせるかが分かれる。D・Caddyのどちらにするかは、
その場合に利用者が選ぶ。B′には戻らない見込みだが、検証の1か2が期待どおりでなければ、改めて決める。

**2026-11-10にWindowsで分かったことのうち、Cに関わるもの**（[ADR 0003](0003-deploy-changes-to-the-target.md#windowsで確かめたこと2026-11-10)）。

| 分かったこと | Cへの影響 |
|---|---|
| `tailscale serve`は管理者のものとして動き、デプロイ用ユーザーは設定を読むことも変えることもできない | 入口の設定は、最初の1回だけ管理者がWindowsの前で行う。デプロイのたびには触らない |
| 版は`current`（デプロイ用ユーザーが作るジャンクション）で切り替える | 入口は`current\dist`を配ることになる。**Tailscaleのサービスがそのジャンクションをたどれるかは、まだ分からない**（検証に加える） |

### 推奨 — C（Windowsでの検証を条件とする）

| 日付 | 推奨 | 変えた理由 |
|---|---|---|
| 2026-11-08 | B | — |
| 2026-11-08 | B′ | レビューで「APIがFrontendの`dist/`の構成まで知っているのはおかしい」と指摘された |
| **2026-11-09** | **C** | **レビューで利用者がCを推した。**下の理由で提案者も同意した |

**2026-11-09、利用者は「B′かC」と絞った。A（別Origin）とB（APIのアプリが画面も返す）は採らない。**
DはB′・Cと組み合わせる選択肢として残る。

#### 利用者が挙げた理由と、提案者の補正

| 利用者の理由 | 提案者の見立て |
|---|---|
| 形としてCが一番きれいで、責務も分かれている | **そのとおり** |
| B′は実装が要るが、CはProxyを置いて設定だけで行ける | **ほぼそのとおり。**ただし`client.ts`の相対パス化とViteの中継は、同じOriginにする以上**B′でもCでも要る。**差は「画面の配信アプリをPythonで書くか」である |
| B′の画面配信は、今回のWindowsのためだけの機能になり、クラウドでは不要になりうる | **半分違う。**B′はクラウドでも1つのコンテナとしてそのまま動く。デプロイ先ごとに追加の仕事が出るのはCの方である。ただしクラウドでのCは、設定で組める定石（上の表）に乗る |
| 実務なら、責務をきっちり分けられてコストが低いCを選ぶ | **正しい。**静的ファイルを置き場とCDNで配り、`/api`だけをAPIへ回すのは、クラウドで最も標準的な構成である |

#### Cを推す理由

1. **責務が部品の境界で分かれる。**静的ファイルの配信とAPIは別の仕事である。入口はパスで振り分けて
   `dist/`をそのまま渡し、uvicorn＋FastAPIはAPIだけを返す。Bの問題（APIがFrontendの事情を知る）が、
   コードの規律ではなく**部品の境界**で無くなる。キャッシュの設定も入口が持つので、APIへ漏れない
2. **[方針](../development/architecture.md#8-デプロイ先をソースコードに持たない2026-11-08決定)とそのまま一致する。**
   最初の1回の`src/`の変更（`client.ts`の相対パス化、Viteの中継）の後に増えるのは、**入口の設定だけ**である。
   B′のように画面の配信アプリをPythonで書いて保守する必要が無い
3. **クラウドでの定石と同じ形になる。**AWSならCloudFront＋S3、GCPならFirebase Hostingやロードバランサー。
   デプロイ先を替えるとき、**入口の設定を書き換えるだけ**で、APIは同じものを持っていける。
   APIのコンテナはAPIだけを持てばよい
4. **画面だけの変更でuvicornを再起動しなくてよい。**`dist/`を差し替えるだけで画面が更新される。
   `MarketplaceAccess`の状態（安全停止の待ち時間など）が消えない。共通のデメリット3が無くなる
5. **CSRだから成り立つ。**配られる静的ファイルはデータを知らないので、誰が配ってもよい。
   CSRの性質をそのまま生かした形である

#### Cの弱点

| 弱点 | 内容 | 扱い |
|---|---|---|
| **Windowsでの未確認点** | `tailscale serve`がSPA fallbackをできるか（できない見込み）、`/api`のパスを削るか | 下の検証で決める |
| 振り分けの設定はCIでTestされない | 設定はWindowsやクラウド側にあり、pytestもE2Eも通らない | 設定と確認手順を`deploy/<デプロイ先>/`に置き、デプロイのたびに手で確かめる。必要ならCIでProxyを立ててE2Eを流す（共通のデメリット1の手当てと兼ねる） |
| デプロイ先ごとに振り分けを書く | 設定ではあるが、書くのは毎回 | 方針の範囲内（`src/`は触らない） |
| Windows本体からも`ts.net`で開く | uvicornの`127.0.0.1:8000`はAPIしか返さない | WindowsもTailnetに入っているので困らない |

#### 決める前の検証（Windows、15分ほど。Mercariへは通信しない）

1. `tailscale serve`でディレクトリ（`dist/`）を`/`に配れるか
2. `--set-path /api`で8000番へ渡したとき、uvicornに`/api/health`のまま届くか、`/health`に削られるか
3. `/sellers/abc123`を直接開いたときに、`index.html`が返るか、404になるか
4. **（2026-11-11に足した）**配るディレクトリが`current\dist`（デプロイ用ユーザーが作ったジャンクション）を通るとき、配れるか

| 結果 | 選ぶもの | Windowsで常駐するもの |
|---|---|---|
| 1〜3がすべて期待どおり | **C（`tailscale serve`だけ）** | 増えない |
| 1・2は期待どおり、3が404 | **C＋D**（`HashRouter`。URLに`#`）か**C＋Caddy**（SPA fallbackをCaddyが担う）。**利用者が選ぶ** | C＋Dは増えない／C＋Caddyは1つ増える |
| 1か2が期待どおりでない | C＋Caddy、またはB′に戻る | — |

**検証の結果を書き込んで、この論点を決定にする。**

#### 検証の結果（2026-11-11。途中）

手順と出た文は[`tailscale serve`の確かめの手順書](../development/windows-tailscale-serve-checks.md)にある。

| # | 確かめ | 結果 |
|---|---|---|
| 1 | `dist/`を`/`に配れるか | **できた**（`index.html`と`assets/`の下のファイル） |
| 2 | `/api`のパス | **入口は`/api`を削って渡した**（`path=/health`）。**渡し先を`http://127.0.0.1:8000/api`とパスつきで書くと、`/api/health`のまま届いた**（クエリも届いた）。**書き方で解決する** |
| 3 | `/sellers/abc123`を直接開いたとき | **404**（`404 page not found`）。`tailscale serve`だけではSPA fallbackができない |
| 4 | `current\dist`（デプロイ用ユーザーが作ったジャンクション）を通して配れるか | **配れた。**`current`を向け直すだけで新しい画面が配られるかは、**まだ確かめていない** |

**結果の表の「1・2は期待どおり、3が404」にあたる。C＋DかC＋Caddyを、利用者が選ぶ（まだ選んでいない）。**

| | C＋D：`HashRouter`にする | C＋Caddy：もう1つ入口を置く |
|---|---|---|
| URL | **`#`が入る**（`/#/sellers/abc123`） | 今のまま |
| Windowsで常駐するもの | 増えない | **Caddyが1つ増える** |
| 変えるもの | Frontendのルーティング（`src/`とTest） | Caddyの設定（`deploy/`）。`src/`は変えない |
| クラウドへ移るとき | どの配り手でも動く | 入口ごとに同じ規則を書き直す |

**提案者はC＋Dを推す。**利用者は1人で、URLに`#`が入って困る場面がほとんど無い（検索エンジンに載せない、人と共有しない）。
常駐するものを増やさず、デプロイ先を選ばなくなる。ただし、ルーティングの方式は2026-09のFrontend基盤（#11）で決めたもので、その判断を開き直す。

## 論点2 — デプロイ先固有の値を、どう渡すか

渡す値は、論点1の選び方で変わる。

| 値 | 例（Windows） | 例（Cloud Run） | B・B′で渡す先 | Cで渡す先 |
|---|---|---|---|---|
| 待つアドレス | `127.0.0.1` | `0.0.0.0` | uvicorn | uvicorn |
| 待つポート | `8000` | 基盤が`$PORT`で渡す | uvicorn | uvicorn |
| Build済みFrontendの場所 | `C:\…\src\frontend\dist` | イメージ内、または静的ファイルの置き場 | **アプリ** | **入口の設定**（アプリは知らない） |

| | a. 環境変数 | b. 設定ファイル（`.env`、TOMLなど） | c. 起動コマンドの引数 | d. デプロイ先ごとの入口関数をコードに書く |
|---|---|---|---|---|
| 中身 | `CARD_DIGGER_FRONTEND_DIST`などを読む | 決まった場所のファイルを読む | `uvicorn --host … --port …` | `create_app_for_windows()`、`create_app_for_cloud_run()`… |
| クラウド基盤との相性 | **良い。**Cloud Run・AWSとも環境変数で渡すのが標準 | 普通。ファイルをイメージに入れるかMountする | 良い。起動コマンドは基盤で指定できる | — |
| Windowsでの扱い | タスクスケジューラーやScriptで設定する | ファイルを1つ置く | Scriptに書く | — |
| 方針との関係 | 満たす | 満たす | 満たす | **反する。**デプロイ先が増えるたびに`src/`が増える |

**メリット・デメリット**

| | メリット | デメリット |
|---|---|---|
| a | どの基盤でも同じやり方。コードの読む場所が1つ | 設定し忘れに気づきにくい。**起動時に検査して止める**必要がある |
| b | 値が1か所に並んで見える。Gitで差分を追える | 秘密情報を入れる日が来ると扱いが難しい。クラウドではMountの手間が増える |
| c | uvicorn自身の値（アドレス・ポート・Process数）はもともとここで渡すもの | アプリ固有の値（`dist/`の場所）は渡せない |
| d | 書くのが簡単 | **方針に反する** |

### 決定（2026-11-09）— uvicorn自身の値は起動コマンドの引数、アプリの値は環境変数

**利用者が決めた**（提案者の推奨どおり）。`--host`・`--port`はuvicornの引数として渡す。
論点1でCを選べば、**アプリに渡す値は今のところ無い**（`dist/`の場所は入口の設定が持つ）。
B′を選んだ場合は、`dist/`の場所を環境変数として渡し、アプリは**起動時に1回だけ読み**、
無い・指す先に`index.html`が無い場合は起動を止める。

**選ばなかった理由。**b（設定ファイル）は、秘密情報を入れる日に扱いが難しく、クラウドではファイルを置く手間が増える。
d（デプロイ先ごとの入口関数）は方針に反する。

## 論点3 — 何をデプロイするか（成果物の形）

| | i. ソースを置き、その場でBuildする | ii. コンテナイメージ | iii. CIがBuildしたArchive |
|---|---|---|---|
| 中身 | Windowsで`git pull`→`npm ci && npm run build`→`uv sync --frozen` | Dockerfileで`dist/`とBackendを1つのイメージにする | GitHub Actionsが`dist/`と依存を固めたzipを作り、Windowsはそれを展開する |
| Windowsに要るもの | Git、Node.js、uv | **Docker Desktop**（WSL2） | uv（`dist/`はBuild済み） |
| クラウドへ移るとき | Dockerfileを**その時に足す**（`src/`は変えない） | **同じイメージを持っていく** | 基盤に合わせて形を変える |
| 戻すとき | 前のcommitをcheckoutしてBuildし直す | 前のイメージのTagで起動する | 前のArchiveを展開する |
| WindowsでTestが通るか | **確かめる必要がある**（CIはLinuxだけ） | **気にしなくてよい**（中身はLinux） | 確かめる必要がある |

**メリット・デメリット**

| | メリット | デメリット |
|---|---|---|
| i | 部品が最も少ない。今すぐ始められる | Windowsで毎回Buildする。Windows固有の失敗がありうる。Node.jsをWindowsに入れる |
| ii | **どこでも同じ成果物。**クラウドへ移るのが最も小さい。Windows固有の問題が消える | Docker Desktopの導入・常駐・メモリ。Windowsの起動時に自動で上げる設定が要る。コンテナの中では`--host 0.0.0.0`になる（下の補足） |
| iii | Buildが1か所（CI）に集まる。Windowsが軽くなる | **ci-policy §7「Deploy / Release Pipeline」「Secretsを要するJob」をやらない、を開き直す**ことになる |

### 決定（2026-11-09）— ADR 0003で決めた

**この論点はADR 0003（PR #48）の論点2で決めた。**正本はそちらである。要点だけ置く。

| もの | 決定 |
|---|---|
| Frontend（`dist/`） | **CIがLinuxで1回だけBuildし、保存する。Windowsはそれを持ってくる**（iiiに近い） |
| Backend | commit SHAのソース＋`uv.lock`。依存はWindowsで`uv sync --locked` |
| コンテナ（ii） | 今は使わない。クラウドへ移る時に足しても`src/`は変わらない |

**当初の推奨（i：Windowsでビルド）は採らなかった。**利用者が「Windowsでビルドすると、GitHubのコードと
動いているコードが違うことになる」とし、一度だけビルドして同じものを持っていく形（Build once, deploy many）を選んだ。

**補足：コンテナと`0.0.0.0`。**コンテナの中では、外（基盤）から届く口が`0.0.0.0`しかない。
誰が届くかは基盤の入口が決める。[src/backend/README.md](../../src/backend/README.md#起動)の
「`--host 0.0.0.0`を付けない」はPCへ直接置く場合の約束なので、iiを選ぶ時に例外として書き足す。

## 論点4 — デプロイ先ごとのファイルを、どこに置くか

起動Script、変更を取り込むScript、手順書、（将来の）Dockerfileの置き場所。

| | 同じリポジトリの`deploy/<デプロイ先>/` | 別のリポジトリ | 置かない（各サービスの管理画面と手作業だけ） |
|---|---|---|---|
| 例 | `deploy/windows-tailscale/`、将来`deploy/cloud-run/` | `card-digger-deploy` | — |
| `src/`との距離 | 別ディレクトリ。`src/`は触らない | 完全に別 | — |
| アプリの変更と揃えるか | **同じcommitで揃えられる**（環境変数の名前を変えたときなど） | 2つのリポジトリを揃える必要がある | 手順が記録に残らない |
| PRの運用 | **CLAUDE.mdとci-policy §4の「PRを経由する」に`deploy/`を足す** | 別に決める | — |

**メリット・デメリット**

| | メリット | デメリット |
|---|---|---|
| `deploy/` | アプリとデプロイ手順の食い違いを同じPRで防げる。デプロイ先を足す＝ディレクトリを1つ足す | リポジトリにデプロイ先の情報が入る（秘密情報は入れない約束が要る） |
| 別リポジトリ | アプリのリポジトリが純粋になる | 1人開発では管理の手間が倍になる |
| 置かない | 何も増えない | 再現できない。Windowsが壊れたとき元に戻せない |

### 決定（2026-11-09）— 同じリポジトリの`deploy/<デプロイ先>/`

**利用者が決めた**（提案者の推奨どおり）。最初は`deploy/windows-tailscale/`である。方針の「`src/`に持たない」は、
リポジトリに持たないことではない。

| 合わせて決めたこと | 内容 |
|---|---|
| `deploy/`も**Pull Requestを経由する** | `src/`と同じく、動くものを置くから。[CLAUDE.md](../../CLAUDE.md)と[ci-policy §4](../development/ci-policy.md#4-pr運用)に足した |
| **秘密情報を置かない** | 公開リポジトリである。GitHubへのログインなどはWindowsだけが持つ（ADR 0003（PR #48）の論点7） |
| **例外：SSHの鍵の手順書は`docs/development/`に置く** | 利用者が決めた（2026-11-09）。`deploy/`には、デプロイScriptや設定のような**動かすもの**を置く。手順書はPR #51 |

**選ばなかった理由。**別リポジトリは、1人開発では2つを揃える手間が倍になる。置かない形は、Windowsが壊れたときに再現できない。

## 論点5 — `VITE_API_BASE_URL`を残すか

### 決定（2026-11-09）— 消す

**利用者が決めた。**前提は、論点1でA（別Origin）を採らないこと（2026-11-09に利用者がB′かCに絞った）。
B′とCのどちらになっても、この決定は変わらない。

### 何を消すか

`src/frontend/src/api/client.ts`の次の部分。

```ts
const DEFAULT_BASE_URL = "http://127.0.0.1:8000";

function baseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  return (typeof configured === "string" && configured.length > 0
    ? configured
    : DEFAULT_BASE_URL
  ).replace(/\/$/, "");
}

// 呼び出し側
response = await fetch(`${baseUrl()}${path}`, { ... });
```

変更後は`fetch(path, { ... })`になる。`path`は`"/api/search"`のような、`/`から始まるパスである。

| 消すもの | 理由 |
|---|---|
| `import.meta.env.VITE_API_BASE_URL`を読む行 | どこからも設定されていない。同じOriginでは要らない |
| `DEFAULT_BASE_URL = "http://127.0.0.1:8000"` | **iPhoneから動かない原因。**[architecture §8.3](../development/architecture.md#83-今この方針に反しているもの)の1 |
| `baseUrl()` | 上の2つを組み合わせるだけの関数 |

### 事実（2026-11-08に調べた）

この変数を読むのは`client.ts`だけで、`.env`・CI・文書のどこからも設定されていない。
2026-09のFrontend基盤（#11）で入ってから使われていない。**今の開発サーバーは既定値だけで動いている。**

### なぜ別Originだと必要で、同じOriginだと要らないのか（レビューで出た問い）

**Browserが自動で補えるのは、画面をもらった場所（Origin）だけである。**

| | 画面の場所 | APIの場所 | `fetch("/api/search")`の行き先 | JSに書く必要があるもの |
|---|---|---|---|---|
| 同じOrigin | `https://PC名.ts.net/` | `https://PC名.ts.net/api/…` | `https://PC名.ts.net/api/search` ✓ | **パスだけ** |
| 別Origin | `https://card-digger.vercel.app/` | `https://PC名.ts.net/api/…` | `https://card-digger.vercel.app/api/search` ✗ | **Originまで含めた絶対URL** |

別Originでは、APIの絶対URLが場面ごとに違う（開発は`127.0.0.1:8000`、Windowsは`PC名.ts.net`…）。
ソースに書けば方針に反するので、Build時に環境変数で渡す。`VITE_API_BASE_URL`はそのための口だった。
仕組みは[静的ファイルの問答](../questions/2026-11-08-what-static-files-are.md)と
[画面とAPIの問答 Q6](../questions/2026-11-08-who-builds-the-screen.md#q6-browserは何をしているのかパスは誰が作るのか)にある。

### `VITE_`の環境変数は、Build時に焼き込まれる

`VITE_`で始まる環境変数は、サーバーが実行時に読むものではない。**Viteが`npm run build`のときに、
JSの中へ文字列として埋め込む。**Browserで動くJSはサーバーの環境変数を読めない。

```js
// ソース
const configured = import.meta.env.VITE_API_BASE_URL;
// Build後（イメージ）
const configured = "https://PC名.ts.net";
```

**Aが方針に反するのはこのためである。**環境変数という設定で渡してはいるが、Build成果物の中身が
デプロイ先ごとに変わり、デプロイ先を替えるたびにBuildし直す。

### 同じOriginなら、Frontendが知るのはAPIの「中身」だけ

| | Frontendが知る必要があるか |
|---|---|
| APIのパス、メソッド、JSONの形、状態コードの意味 | **知る。**どこにデプロイしても変わらない |
| ホスト名、ポート、`http`か`https`か、間のProxy | **知らない。**デプロイ先ごとに変わる |

**パスは必ず`/`から始める。**`api/search`（`/`なし）は今いるページのパスを基準にするので、
`/sellers/abc123`から呼ぶと`/sellers/api/search`へ行ってしまう。今の`client.ts`は、
すべて`/`から始めている（`"/api/search"`、`` `/api/sellers/${…}/analysis` ``、`"/api/health"`）。

### 開発ではViteの開発サーバーを使い続ける（レビューで出た問い）

> Viteを立ち上げないとホットリロードは効かないのでは。`dist/`で配る方法だと使えないのでは

**`dist/`で配るのはデプロイ先だけである。開発では今までどおりViteの開発サーバーとホットリロードを使う。**

| | 開発（手元） | デプロイ先 |
|---|---|---|
| 画面を配るもの | **Viteの開発サーバー**（`npm run dev`、5173番） | `dist/`（入口が配る） |
| ホットリロード | **効く** | 効かない（コードを書き換えないので要らない） |
| `/api`の届き方 | **Viteが8000番へ中継**（`vite.config.ts`の`server.proxy`） | 入口がuvicornへ転送 |
| 起動コマンド | **今と同じ**（`npm run dev`＋uvicorn） | — |

**変数を消すだけでは、開発にもiPhoneにも何も起きない**（今は既定値しか使われていないため）。
効くのは相対パス化で、それは**Viteの中継と同じPRで入れる。**中継が無いと、開発で検索が404になる。

| 同じPRに入れるもの | 中身 |
|---|---|
| `client.ts` | `baseUrl()`まわりを消し、`fetch(path)`にする |
| `vite.config.ts` | `server.proxy: { "/api": "http://127.0.0.1:8000" }` |
| `src/frontend/tests/api/client.test.ts` | 期待値を`"/api/sellers/a%20b%2Fc/analysis"`（Originなし）にする。絶対URLを書き戻すと落ちる |
| E2E | 変更なし。5173番を開いて検索するので、中継が切れれば落ちる |

この変更はB′でもCでも同じなので、**論点1の検証を待たずに入れられる。****2026-11-09に#46でマージした。**手元で、Build結果のJSに`127.0.0.1:8000`が含まれないこと、E2Eが通ること、`server.proxy`を外すとE2Eが落ちることを確かめた。

### 選ばなかった方（残す）

| | 内容 |
|---|---|
| 残すメリット | 変更が最小。いつかAへ移る口が残る |
| 選ばなかった理由 | 設定すると別Origin＋CORSの構成へ戻る口になる。**誰も使っていない設定項目が残る。**Aへ移る日が来たら、理由と一緒に足せばよい |

## 推奨の組み合わせ（提案）

| 論点 | 推奨 |
|---|---|
| 1 | **C（前段の入口が振り分ける）。Windowsでの検証を条件とする** |
| 2 | **決定：**uvicorn自身の値は起動コマンドの引数。Cならアプリに渡す値は今のところ無い |
| 3 | **決定（ADR 0003）：**FrontendはCIで1回だけBuildして持ってくる。Backendはソース＋`uv.lock`。コンテナはクラウドへ移る時 |
| 4 | **決定：**`deploy/<デプロイ先>/` |
| 5 | **消す（2026-11-09決定）** |

この組み合わせで、デプロイ先ごとに変わるもの。**`src/`の列が空になることが、方針を満たした証拠である。**

| 変わるもの | 置き場所 | Windows＋Tailscale | Cloud Run | AWS（App Runner・ECSなど） |
|---|---|---|---|---|
| 待つ場所 | 起動コマンド | `127.0.0.1:8000` | `0.0.0.0:$PORT` | `0.0.0.0:<設定したポート>` |
| 振り分け（`/`は静的ファイル、`/api`はuvicorn） | 入口の設定 | `tailscale serve`（検証の結果次第でCaddy） | Firebase Hosting、またはロードバランサー | CloudFront |
| `dist/`の置き場所 | 入口の設定 | Windowsの`dist/` | Firebase Hosting、Cloud Storage | S3 |
| 認証 | 基盤の設定 | Tailnet | IAPなど | Cloudflare Access、Cognitoなど |
| 1 Processに固定 | 起動コマンド／基盤の設定 | uvicornを1つ起動 | 最大Instance数1 | 最大Instance数1 |
| Buildと常駐 | `deploy/<デプロイ先>/` | PowerShell＋タスクスケジューラー | Dockerfile（APIだけ）＋静的ファイルの上げ方 | Dockerfile（APIだけ）＋静的ファイルの上げ方 |
| 外からの住所 | 基盤 | MagicDNS（`PC名.ts.net`） | 基盤が発行するURL | 基盤が発行するURL |
| **`src/`** | — | — | **変更なし** | **変更なし** |

**どの組み合わせでも残るもの。**クラウドへ移るとMercariから見えるIPがDatacenterのものになる。
これはコードでも設定でも吸収できないので、[契約4](../development/architecture.md#82-アプリがデプロイ先に求めること契約)
（その回線からL4を1回通す）で扱う。

## 決めた後に直すもの

- [論点1の検証](#決める前の検証windows15分ほどmercariへは通信しない)の結果を書き込む
- ~~論点5の変更（`client.ts`、`vite.config.ts`、Test）をPRにする~~ **済み（2026-11-09、#46）**
- この文書の状態を「決定」にし、選ばなかった選択肢に理由を残す
- [ADR 0001の未決](0001-run-on-home-windows-via-tailscale.md#未決--frontendが127001を見に行く問題)を閉じる
- [architecture §8.3](../development/architecture.md#83-今この方針に反しているもの)の表を更新する
- 論点4で`deploy/`を選んだら、CLAUDE.mdと[ci-policy §4](../development/ci-policy.md#4-pr運用)の「PRを経由する」に`deploy/`を足す
- 論点3でiiを選んだら、[src/backend/README.md](../../src/backend/README.md#起動)にコンテナの例外を書く
- [todo](../planning/todo.md#自宅windowsで使う2026-11-08決定)の「直し方を決める」を閉じる
