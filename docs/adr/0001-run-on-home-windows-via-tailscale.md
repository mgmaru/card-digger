# ADR 0001 — 家のWindowsで動かし、Tailscaleで繋ぐ

| 項目 | 内容 |
|---|---|
| 状態 | **決定（2026-11-08）**。ただし[同一Origin化](#未決--frontendが127001を見に行く問題)は未決 |
| 決めた人 | 利用者 |
| 影響する文書 | [mvp-spec §10](../product/mvp-spec.md#10-data取扱い)、[ci-policy §7](../development/ci-policy.md#7-やらないこと) |

## 背景

Phase 1の時点で、すでに使える状態になっている。**使いながら改善するために、開発機の外から
使えるようにしたい。**要件は利用者が出した次の3つである。

| # | 要件 |
|---|---|
| 1 | コストを極力抑える |
| 2 | コードの変更を容易に、安全に取り込める |
| 3 | **Windows・Mac・iPhoneの3台から使える** |

これまでの設計は**単一利用者のLocal実行**を前提にしている。Web化で次の4つにぶつかるので、
候補をこれで絞った。

| # | 今の約束 | Web化で起きること |
|---|---|---|
| A | 認証が無いので`127.0.0.1`にだけBindする（[mvp-spec §10](../product/mvp-spec.md#10-data取扱い)） | URLが届く人なら誰でも、利用者の回線からMercariへRequestを出させられる |
| B | 同時実行1・2秒間隔・安全停止は`MarketplaceAccess`が**1 Processの中で**保証する（[src/backend/README.md](../../src/backend/README.md#起動)） | 自動でInstanceを増やす基盤では、Mercariから見た総量の約束が壊れる |
| C | L4のライブ受入検証は**自宅回線から**通った（[結果](../phase-0/phase-0-f-live-acceptance-result.md)） | DatacenterのIPからMercariが拒否するかは**未検証**。拒否されるとは言っていない |
| D | Mercari規約の確認が未了（[todo](../planning/todo.md#利用規約・運用上の確認)） | 自分1人なら「公開」ではない。常時起動は「継続取得」に近づく |

## 決定1 — サーバーは家のWindowsデスクトップ

| 選択肢 | 月額 | A | B | C | 3台から | 判定 |
|---|---|---|---|---|---|---|
| 自宅のMac | 0円＋電気代 | ○ | ○ | ○ | ○ | 不採用。**常に起動しておけない** |
| **家のWindowsデスクトップ** | **0円＋電気代** | ○ | ○ | ○ | ○ | **採用** |
| Cloud Run（東京） | ほぼ0円（無料枠内） | IAP等が要る | `--max-instances=1`で可 | **未検証** | ○ | 不採用 |
| Fly.io（東京） | 約$2.19〜（256MB） | アプリ側に認証が要る | 1台に固定可 | **未検証** | ○ | 不採用 |
| Render・Vercel・Lambda | — | — | Lambdaは不可 | — | — | 東京リージョン無し、またはBを満たせない |

**理由。**

- **常に起動しておけるのがこの1台だった。**利用者の申告による
- **Cだけは時間をかけても潰せない。**Cloudは月額でほぼ並ぶが、Mercariが拒否するかは
  そこからL4を流すまで分からない。拒否されたら復旧手段が無い
  （[architecture §4.1](../development/architecture.md#41-外部アクセスの条件と2秒間隔の出所)の理由2）
- Bは何も変えずに守れる。1台・1 Processのまま

**払うもの。**

- **電気代。**常時起動していないPCなら増える。例えばアイドル50Wなら約36kWh/月、
  31円/kWhで約1,100円/月。**50Wは仮の値で、まだ測っていない**
- **CIはLinuxでしか検査していない。**Windowsで`pytest`が通るかは未確認

価格の出所（2026-11-08に確認）：
[Cloud Run pricing](https://cloud.google.com/run/pricing)、
[Fly.io Resource Pricing](https://fly.io/docs/about/pricing/)。

## 決定2 — 端末からはTailscaleで繋ぐ

| 選択肢 | 費用 | 端末側の準備 | 外から見えるもの | 判定 |
|---|---|---|---|---|
| **Tailscale** | **0円**（Personalは6人・端末数無制限） | 3台にアプリを入れる | **何も無い** | **採用** |
| Cloudflare Tunnel＋Access | 0円＋独自Domain（年1,500円前後〜） | Browserだけ | URL（認証の手前まで） | 不採用 |
| Routerのポート開放 | 0円 | 無し | **アプリそのもの** | 論外。Aを破る |

**理由。**コストを優先した。Domainが要らず、外から見えるURLも1つも無い。
**認証をアプリへ実装せずにAを守れる**のはこれだけだった。

出所：[Tailscale Pricing](https://tailscale.com/pricing/)、
[pricing v4（2026-04-08）](https://tailscale.com/blog/pricing-v4)。
**Personalプランは非商用に限る。**

## 決定3 — 入口は`tailscale serve`

| 選択肢 | やり方 | 判定 |
|---|---|---|
| uvicornをTailscaleのIPへBindする | `--host 100.x.y.z` | 不採用。起動時にTailscaleが先に上がっていないとBindに失敗する |
| `netsh interface portproxy` | `100.x.y.z:8080` → `127.0.0.1:8000` | 不採用。Firewall規則を自分で開ける。書き損じると家のLANにも見える |
| **`tailscale serve`** | `tailscale serve --bg 8000` | **採用** |

**理由。**uvicornは`127.0.0.1`にBindしたままでよい。**「`--host 0.0.0.0`を付けない」に
触れずに済む。**Firewall規則が要らず、Tailnetの外へは届かない。`--bg`で設定が残るので、
再起動してもTailscaleのサービスと一緒に戻る。

**払うもの。**HTTPSの証明書のため、**ホスト名が公開の証明書透明性Logに載る。**
PC名に個人情報を入れない。HTTPSで暗号化が増えるわけではない
（[問答 Q6](../questions/2026-11-08-reaching-home-server-from-devices.md#q6-tailscale-serveのhttpsで暗号化は増えるのか)）。
`127.0.0.1`のままで何が守られ何が守られないかは
[問答 Q4・Q5](../questions/2026-11-08-reaching-home-server-from-devices.md#q4-127001にbindしたままなぜ外から使えるのか)。

## この決定で変わらないこと

| 約束 | 理由 |
|---|---|
| Backendは`127.0.0.1`にBindする | 外への入口は`tailscale serve`が引き受ける |
| `--workers`を付けない | 1台・1 Processのまま |
| Mercariへは同時実行1・開始間隔2秒以上 | 変える理由が無い |
| L4は手動・低頻度 | Windowsに置いても無人で実行しない |
| Databaseを持たない | Web化しても利用者は1人のまま |

## 未決 — Frontendが`127.0.0.1`を見に行く問題

**このままではiPhoneから動かない。**`src/frontend/src/api/client.ts`の既定の接続先が
`http://127.0.0.1:8000`で、これは**Browserで動くJavaScriptが持つ値**である。入口を
転送しても、iPhoneで開いた画面はiPhone自身の8000番へAPIを呼びに行く。

| 選択肢 | 中身 | 転送 | CORS | 端末ごとのBuild |
|---|---|---|---|---|
| A | `VITE_API_BASE_URL`にTailscaleのURLを入れてBuildする | 2本 | 許可を変える | Windows本体用に別Buildが要る |
| B | FastAPIがBuild済みFrontendも返し、APIは同じOriginの`/api/...`で呼ぶ | 1本 | 関係なくなる | 不要 |

**Bを推す。**まだ利用者の承認を得ていないので、ここでは決めない。

## まだ検証していないこと

- Windowsで`uv run --frozen pytest tests`と`npm run test`が通るか
- 変更を取り込むScriptの形（[todo](../planning/todo.md#自宅windowsで使う2026-11-08決定)で追う）
- Windowsデスクトップの消費電力
- Mercari規約の確認（D）。**常時使い始める前に済ませる**

## 見直す条件

次のどれかが起きたら、このADRを開き直す。

- **Windowsが止まっていて、外出先から使えずに困った。**Cloud Run（決定1で不採用）を
  検討する。**その前にCloud Runの東京からL4を1回流し、Cを確かめる**
- 自宅回線からMercariに拒否された（安全停止が繰り返し発動する）
- 利用者が2人以上になった。Aの前提が変わる
