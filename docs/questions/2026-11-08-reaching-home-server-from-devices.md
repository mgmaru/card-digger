# 家のPCで動くアプリへ、他の端末から繋ぐ — 2026-11-08の問答

[ADR 0001](../adr/0001-run-on-home-windows-via-tailscale.md)を決める途中で利用者が出した問いと、
その答えをまとめる。**何を選んだかと、なぜそれを選んだかはADRが正本である。**
ここには、その判断を読むために必要な**仕組みの説明**だけを置く。

| # | 問い |
|---|---|
| Q1 | [なぜiPhoneから開くと`127.0.0.1:8000`では動かないのか](#q1-なぜiphoneから開くと1270018000では動かないのか) |
| Q2 | [同じOriginにすると、なぜCORSが要らなくなるのか](#q2-同じoriginにするとなぜcorsが要らなくなるのか) |
| Q3 | [ポート転送するなら、`netsh`と`tailscale serve`は何が違うのか](#q3-ポート転送するならnetshとtailscale-serveは何が違うのか) |
| Q4 | [`127.0.0.1`にBindしたまま、なぜ外から使えるのか](#q4-127001にbindしたままなぜ外から使えるのか) |
| Q5 | [`127.0.0.1`のままにすると、何が守られて何が守られないのか](#q5-127001のままにすると何が守られて何が守られないのか) |
| Q6 | [`tailscale serve`のHTTPSで、暗号化は増えるのか](#q6-tailscale-serveのhttpsで暗号化は増えるのか) |
| Q7 | [なぜInstanceが自動で増える基盤では駄目なのか](#q7-なぜinstanceが自動で増える基盤では駄目なのか) |

## Q1. なぜiPhoneから開くと`127.0.0.1:8000`では動かないのか

**`127.0.0.1`は「自分自身」を指すアドレスで、誰にとっての自分かは、その接続を出した機械で決まる。**

FrontendのJavaScriptは、配った側のサーバーではなく**画面を開いた端末のBrowserの中で動く。**
`src/frontend/src/api/client.ts`の既定の接続先は`http://127.0.0.1:8000`なので、

| 画面を開いた端末 | `127.0.0.1:8000`が指すもの | 結果 |
|---|---|---|
| Windows本体 | Windowsの8000番（uvicorn） | 動く |
| iPhone | **iPhone自身の8000番** | 何も居ないので失敗する |

**サーバー側の入口をどう転送しても直らない。**直すのは「Browserがどこへ問い合わせるか」である
（直し方はQ2）。

## Q2. 同じOriginにすると、なぜCORSが要らなくなるのか

Originは**スキーム・ホスト・ポートの3つ組**である。`https://pc.example.ts.net`と
`https://pc.example.ts.net:8000`は、ポートが違うので別のOriginになる。

BrowserはあるOriginのページから**別のOriginへのRequest**を出すとき、相手が許可したか
（CORSのHeader）を確かめる。今の開発構成はこうなっている。

| | Origin |
|---|---|
| 画面（Vite開発サーバー） | `http://127.0.0.1:5173` |
| API（uvicorn） | `http://127.0.0.1:8000` |

ポートが違うので別Originになり、`card_digger/api/main.py`がCORSで5173番を許可している。

**FastAPIがBuild済みの画面も返し、APIを相対パス`/api/...`で呼べば**、画面とAPIは同じOriginになる。
Browserは確認をしないので、CORSの許可を広げる必要が無い。開いたURLがWindowsの`localhost`でも
iPhoneからの`ts.net`でも、相対パスなので同じBuildがそのまま動く。

## Q3. ポート転送するなら、`netsh`と`tailscale serve`は何が違うのか

どちらも「外から来た接続を受けて、PC内の`127.0.0.1:8000`へ渡す」役割で、やることは同じである。
違うのは、**誰がどこで待つか**である。

| | `netsh interface portproxy` | `tailscale serve` |
|---|---|---|
| 待つ口 | 指定したIPとポート。自分で決める | Tailnet側の口だけ |
| Windowsファイアウォール | 受信規則を自分で開ける | 不要 |
| 書き損じたとき | 家のLANにも見える | Tailnetの外には出ない |
| HTTPS | 無い | 証明書を自動で取る |

## Q4. `127.0.0.1`にBindしたまま、なぜ外から使えるのか

**BindはサーバーがどのNetworkの口で待つかを決める。**

| Bind先 | 受け付ける接続 |
|---|---|
| `127.0.0.1` | **同じPCの中から**来た接続だけ |
| `0.0.0.0` | そのPCのすべての口（有線LAN、Wi-Fi、Tailscaleの仮想NIC…）から来た接続 |

普通に外へ出すなら`0.0.0.0`が要る。`tailscale serve`はこう繋ぐので要らない。

```text
iPhone ──(Tailnet / WireGuard)──> [Windows] tailscaled ──(PC内で新しく接続)──> 127.0.0.1:8000 uvicorn
```

外からの接続を受けるのは、**同じWindowsで動くTailscaleのプロセス**である。そこからPCの中で
改めて`127.0.0.1:8000`へ繋ぎ直す（Reverse Proxy）。uvicornから見ると、相手は同じPCの中に居る。

**副作用。**uvicornのLogに出る相手のアドレスは、どの端末から来ても`127.0.0.1`になる。

## Q5. `127.0.0.1`のままにすると、何が守られて何が守られないのか

**認証を持たないアプリを、認証を持つTailscaleの裏に隠すことになる。入口が1つになる。**

守られるもの。

| 相手 | なぜ届かないか |
|---|---|
| 同じWi-Fiに居る他人の端末・家族の端末・IoT機器 | uvicornがLANの口で待っていない |
| RouterのUPnPやポート開放の設定ミス | 同上。転送されても待つ者が居ない |
| Windowsファイアウォールで誤って「許可」を押す | `127.0.0.1`へのBindでは、そもそも聞かれない |
| Tailscaleアカウントに入っていない端末 | `tailscale serve`が通さない |

**届いてしまったら何が起きるか。**このアプリは認証を持たない。繋がった人は、
**利用者の自宅IPからMercariへRequestを出させられる。**安全停止を発動させたり、
回線ごと拒否されるきっかけを作れる。入口を閉じたいときは`tailscale serve reset`で閉じる。

守られないもの。

| 相手 | 理由 | 今の状態 |
|---|---|---|
| Windowsで動く他のプロセス（マルウェアを含む） | 同じPCの中に居る | 対策しない |
| WindowsのBrowserで開いた悪意あるページ | Browserは同じPCの中から`127.0.0.1`へRequestを出せる | 応答の読み取りはCORSで止まる。APIは`Content-Type: application/json`を要求するので、事前確認（preflight）で止まる |
| 同上、DNS rebinding | 攻撃者のDomainを`127.0.0.1`へ解決させると、Browserからは同じOriginに見える。CORSでは防げない | **未対策。**Hostヘッダーを`127.0.0.1`と`<PC名>.ts.net`に限る（FastAPIの`TrustedHostMiddleware`）と防げる |
| Tailnetに招いた他人の端末 | Tailscaleの認証を通る | 今は利用者の3台だけ。招いたら[ADRを見直す](../adr/0001-run-on-home-windows-via-tailscale.md#見直す条件) |

## Q6. `tailscale serve`のHTTPSで、暗号化は増えるのか

**増えない。**Tailnet内の通信は、端末間ですでにWireGuardで暗号化されている。HTTPSは、
その中にTLSをもう1枚重ねるだけである。

増えるのは2つ。

- **BrowserがSecure Contextとして扱う。**iPhoneのSafariで「安全ではない」と出ない
- **`https://<PC名>.<tailnet>.ts.net`という名前で開ける**

**払うもの。**証明書はLet's Encryptが発行するので、**ホスト名が公開の証明書透明性Log
（Certificate Transparency Log）に載る。**名前が知られてもTailnetの外からは届かないが、
PC名に個人情報を入れない。使うには、管理画面でMagicDNSとHTTPS証明書を有効にしておく必要がある。

## Q7. なぜInstanceが自動で増える基盤では駄目なのか

「同時実行1・開始間隔2秒以上・連続3回拒否で止まる」は、**1つのProcessのMemoryの中にある
`MarketplaceAccess`が数えている**（[architecture §4.1](../development/architecture.md#41-外部アクセスの条件と2秒間隔の出所)）。

Processが2つになると、それぞれが自分の分しか数えない。

| | 1 Process | 2 Process |
|---|---|---|
| Mercariから見た同時実行 | 1 | **最大2** |
| 安全停止までに拒否される回数 | 3 | **最大6** |

Cloud Runの既定やLambdaは、Requestが増えるとInstanceを自動で増やす。同じ理由で、
uvicornに`--workers`を付けない（[src/backend/README.md](../../src/backend/README.md#起動)）。
**家のWindowsで1 Processとして動かせば、何も変えずに守れる。**
