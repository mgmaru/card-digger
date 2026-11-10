# Macから家のWindowsへ、SSHの鍵で入る手順

## 文書ステータス

- 作成日: **2026-11-09**
- 対象: Mac（入る側）と、家のWindows（Windows標準のOpenSSHサーバー）
- 目的: MacからWindowsへ、**デプロイ用の一般ユーザー**と、**踏み台として使う管理者**の2つで、
  **鍵認証だけ**で入れるようにする。**パスワードで入る道は閉じる**
- 根拠: ADR 0003（PR #48）の論点7（家のLANからも入れるまま、鍵認証だけにする）と、
  論点8（デプロイは専用の一般ユーザーで動かす。管理者は踏み台として鍵だけで残す）
- **状態: 実機で通したのは、1（鍵のペアを作る、2026-11-09）、3〜5（デプロイ用ユーザーを作り、鍵で入れることを
  確かめた、2026-11-10）。5-2（管理者の鍵）の途中、6以降はまだ通していない。**最後まで通したら結果で直し、この行を消す

なぜ鍵の方が安全か、何がまずいかは[南京錠の問答](../questions/2026-11-09-how-ssh-keys-prove-who-you-are.md)、
パスワードで家のLANから入れる状態がなぜ危ないかは[SSHの問答](../questions/2026-11-09-why-ssh-on-all-addresses-is-risky.md)にある。

## この手順書に書かないもの

**リポジトリは公開である。**次は説明用の書き方に置き換える。

| 書かない | この手順書での書き方 |
|---|---|
| Windowsのホスト名 | `<ホスト名>` |
| 管理者のアカウント名 | `<管理者ユーザー>` |
| デプロイ用のアカウント名 | `<デプロイ用ユーザー>` |
| `~/.ssh/config`の、管理者として入る`Host`の名前 | `<管理者の入り口>` |
| 踏み台の先の仮想マシンの住所 | `<踏み台の先>` |
| `~/.ssh/config`の、踏み台の先へ入る`Host`の名前（`ProxyJump`を書いている段落） | `<踏み台の先の入り口>` |
| tailnetの名前、IPアドレス | 書かない |
| **秘密鍵の中身** | 絶対に書かない・貼らない |
| 公開鍵の中身 | 漏れても困らないが、書く理由も無い |

鍵のファイル名（`id_ed25519_deploy`）や、鍵のコメントの例（`mac-to-windows-deploy`）は書いてよい。

## 0. どのアカウントで入るか

**最小権限（必要な権限だけを与える）**に従う。鍵を盗まれたとき、入られたアカウントにできることが、
そのまま被害の大きさになるからである。

| アカウント | 種類 | 使い方 | SSHで入れるか | Macの鍵 |
|---|---|---|---|---|
| `<デプロイ用ユーザー>`（新しく作る） | **一般ユーザー** | **デプロイ**。Card Diggerを動かす | **入れる（鍵だけ）** | `~/.ssh/id_ed25519_deploy` |
| `<管理者ユーザー>`（今のアカウント） | 管理者 | **踏み台**（`ProxyJump`）。Windowsの先の仮想マシンへ通り抜ける。Windowsの管理はWindowsの前で行う | **入れる（鍵だけ）** | `~/.ssh/id_ed25519_jump` |

**管理者も鍵で残す理由。**別のプロジェクト（ルーターの自作）で、Windowsを踏み台にして仮想マシンへ入っている。
パスワードを閉じると、管理者にも鍵が要る。

**鍵は役割ごとに別のペアにする。**デプロイ用の鍵が盗まれても、管理者（踏み台）には入れない。逆も同じ。

**管理者の鍵を盗まれると、Windowsのすべてを取られうる。**踏み台に要るのは「通り抜けること」だけなので、
後で**踏み台だけに絞る**（[8](#8-管理者を踏み台だけに絞る後で行う)）。一度に変えるものを少なくするため、まず鍵にすることだけを行う。

## 全体の流れ

```mermaid
flowchart TD
    A["1. Macでデプロイ用の鍵を1組作る"] --> B["2. Windowsのアカウントを確かめる"]
    B --> C["3. デプロイ用の一般ユーザーを作る<br/>（Windowsの前で）"]
    C --> D["4. 公開鍵を送り、その人の棚に置く<br/>（Macで送り、Windowsの前で置く）"]
    D --> E{"5. デプロイ用ユーザーで<br/>鍵で入れる？"}
    E -- "いいえ" --> T["トラブルシュートへ<br/>（sshd_configはまだ変えない）"]
    E -- "はい" --> H["5-2. 管理者（踏み台）の鍵を置く<br/>Windowsと仮想マシンへ入れるか確かめる"]
    H --> F["6. パスワードを閉じる<br/>（Windowsの前で）"]
    F --> G["7. 確かめる"]
    G -.-> J["8. 管理者を踏み台だけに絞る<br/>（後で）"]
```

**順番を守る。2つのアカウントとも鍵で入れることを確かめる（5、5-2）より前に、`sshd_config`を変えない（6）。**
鍵が通らないままパスワードを閉じると、締め出される。踏み台の先の仮想マシンにも入れなくなる。

## 1. Macでデプロイ用の鍵を1組作る

### 1-1. パスフレーズを作る

パスフレーズは、**Macに保存する秘密鍵のファイルを暗号化する**ためのものである（鍵を金庫に入れる。
[南京錠の問答 Q5](../questions/2026-11-09-how-ssh-keys-prove-who-you-are.md#q5-秘密鍵のパスフレーズは何をしているのか)）。
**ファイルを盗まれた後に、盗んだ人の手元で総当たりされる**ので、SSHのログインのような「何回か間違えたら止まる」
仕組みが無い。**当てられにくさが、そのまま強さになる。**

| 決め方 | 理由 |
|---|---|
| **長くする**（単語4〜5個、または16文字以上） | 当てられにくさは、記号の多さより長さで決まる |
| **ほかのどこでも使っていないもの** | Windowsのパスワードなどの使い回しは、片方が漏れるともう片方も開く |
| **自分に関係する情報を入れない** | 名前、誕生日、ユーザー名、ホスト名は推測されやすい |
| **チャット・文書・リポジトリに書かない** | 秘密鍵と同じ扱い |

**ふだんは打たない**（1-3でmacOSのキーチェーンに覚えさせる）ので、覚えにくい長い文字列でよい。

#### 作り方A：パスワード管理ツールで作る（2026-11-09はこれで作った）

macOSの「**パスワード**」アプリ（iCloudキーチェーン）や1Passwordで新しい項目を作ると、**強力なパスワードを自動で作る**。
作った値はそのまま保存される。項目の名前は「Mac→Windows デプロイ用SSH鍵」など、何の鍵か分かるようにする。

#### 作り方B：ターミナルで作る

```bash
# 文字の並び（約32文字）
openssl rand -base64 24 | pbcopy

# 単語の並び（覚えたいとき）。macOSの英単語の一覧から、暗号に使える乱数で5個選ぶ
python3 -c "import secrets; w=open('/usr/share/dict/words').read().split(); print('-'.join(secrets.choice(w) for _ in range(5)))" | pbcopy
```

| 部分 | 意味 |
|---|---|
| `\| pbcopy` | **画面に表示せず、クリップボードに入れる**。覗かれない、画面の履歴に残らない |
| `secrets` | パスワードを作るためのPythonの乱数。普通の`random`は予測されうるので使わない |

使ったら、同じ値をパスワード管理ツールにも保存し、**クリップボードを空にする**。

```bash
pbcopy < /dev/null
```

### 1-2. 鍵のペアを作る

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_deploy -C "mac-to-windows-deploy"
```

| 指定 | 意味 |
|---|---|
| `-f` | 鍵のファイル名。役割が分かる名前にする |
| `-C` | 鍵のコメント。**付けないと`Macのユーザー名@Macのホスト名`が自動で入り**、公開鍵を貼ったときに見える |
| パスフレーズ（2回聞かれる） | 1-1で作ったものを**貼り付ける**。画面には表示されない |
| `-a 100`（任意） | パスフレーズを試す1回あたりの計算を重くし、総当たりを遅くする（既定は16）。代わりに自分が鍵を使うときも少し待つことがある。上のコマンドには入れていない |

できるもの。

| ファイル | 中身 | 扱い |
|---|---|---|
| `~/.ssh/id_ed25519_deploy` | 🔑 秘密鍵（`-----BEGIN OPENSSH PRIVATE KEY-----`で始まる） | **Macから出さない** |
| `~/.ssh/id_ed25519_deploy.pub` | 🔒 公開鍵（`ssh-ed25519 AAAA… mac-to-windows-deploy`の1行） | Windowsの棚に置く |

できたかを確かめる（中身は表示しない）。

```bash
ls -l ~/.ssh/id_ed25519_deploy ~/.ssh/id_ed25519_deploy.pub   # 秘密鍵が -rw------- （自分だけが読める）か
ssh-keygen -lf ~/.ssh/id_ed25519_deploy.pub                   # 256 … mac-to-windows-deploy (ED25519) と出るか
```

2026-11-09に、どちらも期待どおりだった（秘密鍵は`-rw-------`、`256 … mac-to-windows-deploy (ED25519)`）。

### 1-3. キーチェーンに覚えさせ、入り口を書く

毎回パスフレーズを打たずに済むよう、macOSのキーチェーンに覚えさせる。

```bash
ssh-add --apple-use-keychain ~/.ssh/id_ed25519_deploy
```

`~/.ssh/config`に、デプロイ用の入り口を書く。

```text
Host <ホスト名>-deploy
  HostName <ホスト名>
  User <デプロイ用ユーザー>
  IdentityFile ~/.ssh/id_ed25519_deploy
  IdentitiesOnly yes
  AddKeysToAgent yes
  UseKeychain yes
```

| 指定 | 意味 |
|---|---|
| `IdentityFile` | この入り口で使う鍵 |
| **`IdentitiesOnly yes`** | **指定した鍵だけを使う。**付けないと、Macが持つほかの鍵も順に試してしまう |

管理者として入っていた既存の`Host <ホスト名>`の段落は、6の後は使えなくなる。残しておいてもよいし、消してもよい。

## 2. Windowsのアカウントを確かめる

### 自分のアカウントが管理者か

Windowsのコマンドプロンプトで。どちらか1つでよい。

```bat
net localgroup administrators
```

```bat
whoami /groups | findstr S-1-5-32-544
```

| 確かめ方 | 管理者なら |
|---|---|
| `net localgroup administrators` | メンバーに`<管理者ユーザー>`がある。**`administrators`の最後の`s`を忘れると「システム エラー 1376」になる**（2026-11-09に起きた） |
| `whoami /groups \| findstr S-1-5-32-544` | `BUILTIN\Administrators`の行が出る。`S-1-5-32-544`はどのWindowsでも共通の管理者グループの番号で、名前の打ち間違いが起きない |

3以降の「管理者のPowerShell」は、このアカウントで開く。

### `Administrator`アカウントが無効か

Windowsに最初から入っている`Administrator`アカウントは、ふだん使わない管理者アカウントである。
有効なまま残っていること自体が危ない。

```bat
net user Administrator | findstr アカウント有効
```

| 結果 | 対処 |
|---|---|
| `アカウント有効   No` | 問題なし |
| `アカウント有効   Yes` | 使っていなければ無効にする（管理者のPowerShellで`net user Administrator /active:no`） |

## 3. デプロイ用の一般ユーザーを作る（Windowsの前で、管理者のPowerShell）

スタートメニューで「PowerShell」を右クリックし、「管理者として実行」で開く。

```powershell
$pw = Read-Host -AsSecureString "デプロイ用ユーザーのパスワード"
New-LocalUser -Name "<デプロイ用ユーザー>" -Password $pw -Description "Card Digger deploy" -PasswordNeverExpires
Add-LocalGroupMember -SID S-1-5-32-545 -Member "<デプロイ用ユーザー>"   # Users（一般ユーザー）のグループ
```

| 注意 | 理由 |
|---|---|
| **管理者のグループ（`S-1-5-32-544`）には入れない** | 一般ユーザーにするのが目的 |
| パスワードは設定する | タスクスケジューラーで「ログオンしていなくても動かす」設定にパスワードが要る。**6の後は、SSHのパスワードとしては使えない** |
| `-PasswordNeverExpires` | 期限切れでCard Diggerのタスクが動かなくなるのを避ける |

パスワードは、パスフレーズと同じく**パスワード管理ツール（iCloudキーチェーンなど）で作って保存する。**
項目名は「Windows <デプロイ用ユーザー>」など、何のパスワードか分かるようにする。

### 3-1. パスワードを必須にする（落とし穴）

**`New-LocalUser`で作ると、パスワードを指定しても「パスワードを必須とする」設定が`No`になることがある**
（2026-11-10に起きた）。`No`は**空のパスワードでも許される**という意味である。作成時の`Read-Host`で何も入れずに
Enterを押していると、**パスワードが空のアカウント**になっている。

確実にするため、パスワードを入れ直し、必須にする。

```powershell
net user <デプロイ用ユーザー> *                  # パスワードを入れ直す（表示されない。2回聞かれる）
net user <デプロイ用ユーザー> /passwordreq:yes   # パスワードを必須にする
net user <デプロイ用ユーザー> /passwordchg:no    # 任意。本人に変えさせない（タスクに覚えさせたパスワードとずれない）
```

### 3-2. できたかを確かめる

```bat
net user <デプロイ用ユーザー>
```

| 項目（日本語のWindowsの表示） | 期待する値 | 意味 |
|---|---|---|
| `アカウント有効` | `Yes` | 使える状態 |
| `パスワード有効期間` | `無期限` | `-PasswordNeverExpires`が効いている |
| **`パスワードあり`** | **`Yes`** | **3-1が効いている。`No`なら3-1をやり直す** |
| **`所属しているローカル グループ`** | **`*Users`だけ** | **一般ユーザーになっている。`*Administrators`が無いこと** |
| `最終ログオン日時` | `なし` | まだログオンしていない（4-1で初めてログオンする） |

`net user`を**名前なしで**実行すると、ユーザーの一覧だけが出る。名前を付けて実行する。

PowerShellなら、グループを番号で確かめられる（日本語のWindowsでも名前の違いを気にしなくてよい）。

```powershell
Get-LocalGroupMember -SID S-1-5-32-545 | Where-Object Name -like '*\<デプロイ用ユーザー>'   # Users：1行出ればよい
Get-LocalGroupMember -SID S-1-5-32-544 | Where-Object Name -like '*\<デプロイ用ユーザー>'   # Administrators：何も出なければよい
```

### 3-3. 使っていないアカウントが有効になっていないか

```powershell
Get-LocalUser | Format-Table Name, Enabled, Description
```

**有効（`Enabled`が`True`）なのは、利用者のアカウントとデプロイ用ユーザーの2つだけ**が望ましい。
`Administrator`や`Guest`が有効なら、使っていなければ無効にする（`Disable-LocalUser -Name <名前>`）。
Windowsの機能が使っているかもしれないアカウント（名前に心当たりが無いもの）は、**何のアカウントか確かめてから**無効にする。

## 4. デプロイ用ユーザーの公開鍵を置く（Windowsの前で）

### 4-1. デプロイ用ユーザーとしてPowerShellを開く

ユーザーのフォルダー（`C:\Users\<デプロイ用ユーザー>`）は、**そのユーザーが初めてログオンしたときに作られる。**
`runas`で、そのユーザーとしてPowerShellを1つ開く（パスワードを聞かれる）。

```powershell
runas /user:<デプロイ用ユーザー> powershell
```

**管理者のアカウントから、デプロイ用ユーザーのフォルダーは開けない。これが正しい。**エクスプローラーで開こうとして
「このフォルダーにアクセスする許可がありません」と出ても、**「続行」を押さない。**押すとWindowsがフォルダーの権限を
書き換えて管理者を足し、SSHサーバーが「権限が緩い」と判断して`authorized_keys`を無視することがある。
中身は、4-1で開いたデプロイ用ユーザーのウィンドウから見る（`Get-ChildItem $env:USERPROFILE`）。

### 4-2. 公開鍵をWindowsへ送る（Mac）

**MacとWindowsは別の機械なので、Macでコピーした文字はWindowsでそのまま貼れない。**公開鍵をファイルとして送る。
公開鍵は見られても困らないので、送り方は何でもよい（メモアプリやメールでもよい）。ここでは、**この時点ではまだ管理者で
SSHできる**ので、`scp`で送る。

```bash
scp ~/.ssh/id_ed25519_deploy.pub <管理者の入り口>:C:/Users/Public/deploy-key.pub
```

| 部分 | 意味 |
|---|---|
| `~/.ssh/id_ed25519_deploy.pub` | 送るファイル。**`.pub`が付いていることを確かめる**（秘密鍵を送らない） |
| `<管理者の入り口>` | `~/.ssh/config`で、管理者として入るために書いてある**`Host`の名前**（ホスト名そのものではない。下の注意） |
| `C:/Users/Public/` | Windowsの「パブリック」フォルダー。**どのユーザーからも読める**ので、デプロイ用ユーザーのウィンドウから取り出せる |

管理者（Windows）のパスワードを聞かれる。`ファイル名 100% …`と出れば送れている。
「ファイルが見つからない」といったエラーになったら、パスの先頭に`/`を付けて`<管理者の入り口>:/C:/Users/Public/deploy-key.pub`で試す。

**注意：`<管理者の入り口>`は`Host`の名前を使う。**`~/.ssh/config`に次のように書いてあるなら、使うのは`win`である。

```text
Host win              ← これを使う（ssh や scp で使う名前）
  HostName <ホスト名>  ← 実際の接続先
  User <管理者ユーザー>
```

ホスト名（`HostName`の値）を直接書くと、この段落の`User`が使われず、**Macのユーザー名で入ろうとして断られる**
（`<Macのユーザー名>@<ホスト名>'s password:`と聞かれる。2026-11-10に起きた）。

### 4-3. 公開鍵を置く（4-1で開いた、デプロイ用ユーザーのPowerShell）

**4-1で開いたウィンドウ（デプロイ用ユーザーとして動いている）で**実行する。そのユーザー自身が作るので、
ファイルの持ち主と権限が正しくなる。

```powershell
whoami                                                   # <ホスト名>\<デプロイ用ユーザー> と出ることを確かめる
New-Item -ItemType Directory -Force $env:USERPROFILE\.ssh | Out-Null
Get-Content C:\Users\Public\deploy-key.pub | Add-Content $env:USERPROFILE\.ssh\authorized_keys
Get-Content $env:USERPROFILE\.ssh\authorized_keys        # ssh-ed25519 AAAA… mac-to-windows-deploy の1行が出るか
Remove-Item C:\Users\Public\deploy-key.pub               # 受け渡しに使ったファイルを片付ける
```

| 行 | 確かめること |
|---|---|
| `whoami` | **デプロイ用ユーザーと出ること。**管理者と出たら管理者のウィンドウで、鍵が違うフォルダーに置かれてしまう |
| 4行目の`Get-Content` | **`ssh-ed25519 AAAA… mac-to-windows-deploy`の1行。**`BEGIN … PRIVATE KEY`なら秘密鍵を送っている（[南京錠の問答 Q7](../questions/2026-11-09-how-ssh-keys-prove-who-you-are.md#q7-秘密鍵が自分の機械の外に出るのはどんなときか出てしまったらどうするか)に従い、鍵を作り直す） |

**`scp`はファイルをコピーするだけである。**SSHサーバーが鍵を探すのは、決まった場所の決まった名前のファイル
（`C:\Users\<デプロイ用ユーザー>\.ssh\authorized_keys`）だけである。送っただけでは鍵で入れない（2026-11-10に起きた）。
名前が1文字でも違う（`authorized_key`、`authorized_keys.txt`など）と見つけられない。

3行目で「パスが見つかりません」と出たら、送り先が違っている。次で探す。

```powershell
Get-ChildItem C:\Users\Public -Filter *.pub
Get-ChildItem $env:USERPROFILE -Filter *.pub          # デプロイ用ユーザーとして送った場合はここ
```

## 5. デプロイ用ユーザーで、鍵で入れることを確かめる（Mac）

```bash
ssh -o PasswordAuthentication=no <ホスト名>-deploy whoami
```

| 結果 | 次 |
|---|---|
| **パスワードを聞かれずに、デプロイ用のアカウント名が出た** | 6へ |
| 入れない、または違うアカウント名が出た | [トラブルシュート](#トラブルシュート)へ。**`sshd_config`はまだ変えない** |

初めて鍵を使うときは、Macがキーチェーンのパスフレーズを聞くことがある。それは**Macの鍵の金庫を開けるもの**で、
Windowsのパスワードではない。

### 「入れた」が鍵によるものか確かめる

**6でパスワードを閉じるまでは、鍵が断られてもSSHはパスワードを試す。**デプロイ用ユーザーのWindowsのパスワードを
入れて入れてしまうと、鍵が効いていないことに気づけない（2026-11-10に起きた）。鍵だけで入れるかは、
パスワードを使わない指定で、何が起きたかを表示して確かめる。

```bash
ssh -v -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no -o BatchMode=yes <ホスト名>-deploy whoami 2>&1 \
  | grep -E "Offering public key|Server accepts key|Authenticated to|Permission denied"
```

| 出た行 | 意味 |
|---|---|
| `Offering public key: … id_ed25519_deploy` | Macが鍵を差し出した |
| **`Server accepts key: … id_ed25519_deploy`** | **Windowsが鍵を受け付けた。**これが出れば鍵で入れている |
| `Authenticated to <ホスト名>` | 入れた |
| `Offering…`の次に`Permission denied` | **Windowsが鍵を断った。**4-3（棚に置けているか）をやり直す |

`-o BatchMode=yes`は、パスワードやパスフレーズの入力を求められたら、入力を待たずに止まる指定である。
パスフレーズはキーチェーン（1-3）から読まれるので、止まらない。

## 5-2. 管理者（踏み台）の鍵を置き、確かめる

**踏み台として使う管理者にも、鍵を置く。**流れはデプロイ用と同じだが、**置き場所が違う。**

### 5-2-1. Macで鍵を作り、入り口に書く

1-1〜1-3と同じ。**パスフレーズはデプロイ用とは別に作る。**

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_jump -C "mac-to-windows-jump"
ssh-add --apple-use-keychain ~/.ssh/id_ed25519_jump
```

`~/.ssh/config`の、管理者として入る段落（`<管理者の入り口>`）に4行を足す。**踏み台の先の段落（`ProxyJump`を書いている段落）は
触らない。**`ProxyJump <管理者の入り口>`は、この段落の設定（鍵を含む）を使ってWindowsへ入る。

```text
Host <管理者の入り口>
  HostName <ホスト名>
  User <管理者ユーザー>
  Port 22
  IdentityFile ~/.ssh/id_ed25519_jump
  IdentitiesOnly yes
  AddKeysToAgent yes
  UseKeychain yes
```

### 5-2-2. 公開鍵を送り、**管理者の棚**に置く

Macで（この時点ではまだパスワードで入れる）：

```bash
scp ~/.ssh/id_ed25519_jump.pub <管理者の入り口>:C:/Users/Public/jump-key.pub
```

Windowsの前で、**管理者として実行したPowerShell**で：

```powershell
Get-Content C:\Users\Public\jump-key.pub | Add-Content C:\ProgramData\ssh\administrators_authorized_keys
icacls.exe C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant "*S-1-5-32-544:F" /grant "*S-1-5-18:F"
Get-Content C:\ProgramData\ssh\administrators_authorized_keys   # ssh-ed25519 AAAA… mac-to-windows-jump の行があるか
icacls.exe C:\ProgramData\ssh\administrators_authorized_keys    # Administrators と SYSTEM の2行だけか
Remove-Item C:\Users\Public\jump-key.pub
```

**落とし穴：管理者の鍵を`$env:USERPROFILE\.ssh\authorized_keys`に置いても、使われない**（2026-11-10に起きた）。
Windowsの`sshd_config`には、もともと次の段落がある。管理者グループの人については、**管理者の棚だけを見る。**

```text
Match Group administrators
       AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys
```

| 鍵を置いた場所 | 管理者のとき | 一般ユーザーのとき |
|---|---|---|
| `C:\Users\<名前>\.ssh\authorized_keys`（`$env:USERPROFILE`） | **見ない（無視される）** | 見る |
| `C:\ProgramData\ssh\administrators_authorized_keys` | **見る** | 見ない |

間違えて`$env:USERPROFILE`に置いたときは、その行を管理者の棚へ移し、間違えた方を片付ける
（**管理者として実行したPowerShell**でも、`$env:USERPROFILE`は自分のフォルダーのままである）。

```powershell
(Select-String -Path $env:USERPROFILE\.ssh\authorized_keys -Pattern 'mac-to-windows-jump').Line |
  Add-Content C:\ProgramData\ssh\administrators_authorized_keys
icacls.exe C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant "*S-1-5-32-544:F" /grant "*S-1-5-18:F"
Get-Content $env:USERPROFILE\.ssh\authorized_keys   # mac-to-windows-jump の1行だけなら、下で消す
Remove-Item $env:USERPROFILE\.ssh\authorized_keys   # ほかの行もあるときは消さず、その1行だけを取り除く
```

### 5-2-3. 確かめる（Mac。パスワードを閉じる前に）

```bash
ssh -v -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no -o BatchMode=yes <管理者の入り口> whoami 2>&1 \
  | grep -E "Offering public key|Server accepts key|Authenticated to|Permission denied"
ssh <踏み台の先の入り口> hostname     # 踏み台の先の仮想マシンへ、今までどおり入れるか
```

| 確かめること | 期待する結果 |
|---|---|
| 管理者の入り口 | `Server accepts key: … id_ed25519_jump`が出る |
| 踏み台の先 | 今までどおり入れる。**ここで入れなければ6へ進まない** |

**踏み台の先の仮想マシンへの入り方は、Windowsの設定に影響されない。**`ProxyJump`では認証が2回、別々に行われる。

```text
① Mac ──認証──> Windows（踏み台）                 ← 変わるのはここだけ（パスワード → 鍵）
② Mac ──認証──> 仮想マシン（Windowsを通り抜けて） ← 仮想マシン自身の認証。Windowsの設定は関係ない
```

①が鍵で通れば、②は今までどおりである。

## 6. パスワードを閉じる（5と5-2が成功してから。Windowsの前で、管理者のPowerShell）

**SSHで入った画面ではなく、Windowsの前で作業する。**設定を誤っても、Windowsの前なら直せる。

```powershell
Copy-Item C:\ProgramData\ssh\sshd_config C:\ProgramData\ssh\sshd_config.bak   # 控え
notepad C:\ProgramData\ssh\sshd_config
```

次の2点を直して保存する。

| 直すところ | 書き方 | 意味 |
|---|---|---|
| `#PasswordAuthentication yes`の行 | 先頭の`#`を消して`PasswordAuthentication no` | **全員、**パスワードでは入れない |
| ファイルの**`Match`で始まる行より前**に1行足す | `AllowUsers <デプロイ用ユーザー> <管理者ユーザー>` | **この2人しか入れない**（許可リスト） |

**`AllowUsers`は`Match`の行より前に書く。**`Match`の後ろに書いた設定は、すべてその`Match`の中として扱われる。

**`sshd_config`は1つで、全員に効く。**デプロイ用の設定だけをするつもりでも、書き方しだいで管理者（踏み台）にも効く。
特定のユーザーだけに効かせたいときは、ファイルの一番最後に`Match User <名前>`の段落を書く。

書き間違いを確かめてから、再起動する（`sshd_config`は起動するときに読み込まれる）。

```powershell
& 'C:\Windows\System32\OpenSSH\sshd.exe' -t   # 何も出なければ正しい。エラーなら再起動しない
Restart-Service sshd
```

元に戻すときは、控えを戻して再起動する。

```powershell
Copy-Item C:\ProgramData\ssh\sshd_config.bak C:\ProgramData\ssh\sshd_config -Force
Restart-Service sshd
```

## 7. 確かめる（Mac）

| コマンド | 期待する結果 |
|---|---|
| `ssh <ホスト名>-deploy whoami` | **入れる**。デプロイ用のアカウント名が出る |
| `ssh <管理者の入り口> whoami` | **入れる**（鍵で） |
| `ssh <踏み台の先の入り口> hostname` | **今までどおり入れる** |
| `ssh -o PubkeyAuthentication=no <ホスト名>-deploy` | **`Permission denied`で断られる**（パスワードの道が閉じた） |
| `ssh -o PubkeyAuthentication=no <管理者の入り口>` | **`Permission denied`で断られる** |

## 8. 管理者を踏み台だけに絞る（後で行う）

**6・7が動いてから、別の機会に行う。**踏み台に要るのはWindowsを**通り抜けること**だけで、Windowsでコマンドを
打つ必要は無い。`ProxyJump`は通信の転送（SSHの`direct-tcpip`）だけを使うので、コマンドの実行を禁じても踏み台は動く。

`sshd_config`の**一番最後**に足す。

```text
Match User <管理者ユーザー>
    PermitTTY no
    ForceCommand cmd /c echo This account is for ProxyJump only.
    AllowTcpForwarding local
    PermitOpen <踏み台の先>:22
    X11Forwarding no
    AllowAgentForwarding no
    PermitTunnel no
```

| 行 | 意味 |
|---|---|
| `PermitTTY no`、`ForceCommand …` | `ssh <管理者の入り口>`と打っても、メッセージを出して切れる。Windowsでコマンドを打てない |
| `AllowTcpForwarding local` | `ProxyJump`に要る「通り抜け」だけを許す |
| `PermitOpen <踏み台の先>:22` | **通り抜けの行き先を1つに絞る。**さらに先の仮想マシンへは、その仮想マシンから進むので、Windowsからの行き先はこれで足りる |
| 残りの3行 | 使わない転送を閉じる |

| | 絞る前 | 絞った後 |
|---|---|---|
| 管理者の鍵を盗まれたら | **Windowsのすべて** | 踏み台の先の22番へ通り抜けられるだけ |

**`ForceCommand`は`scp`も止める。**絞った後は、管理者の入り口で`scp`（5-2-2）はできない。鍵の受け渡しは、
デプロイ用ユーザーで送るか、Windowsの前で行う。

## トラブルシュート

| 症状 | まず疑うこと |
|---|---|
| 鍵を置いたのにパスワードを聞かれる | **棚に置けていない。**`scp`で送っただけで、4-3をやっていない（2026-11-10に起きた）。デプロイ用ユーザーのウィンドウで`Get-Content $env:USERPROFILE\.ssh\authorized_keys`が1行を返すか |
| **管理者**で、鍵を置いたのに断られる | **管理者の鍵を`$env:USERPROFILE\.ssh\authorized_keys`に置いた**（2026-11-10に起きた）。管理者は管理者の棚（`C:\ProgramData\ssh\administrators_authorized_keys`）しか見ない（5-2-2） |
| 踏み台の先の仮想マシンへ入れない | ①Windowsへの認証で止まっていないか（`ssh -v <管理者の入り口>`）。②8を行った後なら、`PermitOpen`の行き先が合っているか |
| 鍵を置いたのにパスワードを聞かれる | `authorized_keys`を**管理者のウィンドウで作った**（持ち主が違う）。4-1で開いたデプロイ用ユーザーのウィンドウで作り直す |
| 「入れた」のに、5の確認で`Permission denied`になる | パスワードで入っていた。[「入れた」が鍵によるものか確かめる](#入れたが鍵によるものか確かめる) |
| `<Macのユーザー名>@<ホスト名>'s password:`と聞かれ、断られる | `ssh`・`scp`に**ホスト名を直接書いた。**`~/.ssh/config`の`Host`の名前（入り口の名前）を使う（4-2の注意） |
| `~/.ssh/config line N: no argument after keyword "…"`と出て、どこにも繋がらない | `~/.ssh/config`のN行目に**余計な文字だけの行**がある（2026-11-10に`6`だけの行で起きた）。1行でも壊れると**ファイル全体が読めず、すべての入り口が使えなくなる**。その行を消す。直ったかは`ssh -G <入り口> \| grep -E "^(hostname\|user\|identityfile) "`で、繋がずに確かめられる |
| 管理者のアカウントで、デプロイ用ユーザーのフォルダーが開けない | **正しい状態。「続行」を押さない**（4-1の注意） |
| 鍵を置いたのにパスワードを聞かれる | 貼った1行が欠けている・改行が混ざっている。`ssh-ed25519 AAAA…`で始まる1行か |
| どの鍵を使っているか分からない | Macで`ssh -v <ホスト名>-deploy`。`Offering public key: … id_ed25519_deploy`が出るか |
| 違うアカウントで入ってしまう | `~/.ssh/config`の`User`と`IdentityFile`、`IdentitiesOnly yes`があるか |
| 6の後、デプロイ用ユーザーでも入れない | `AllowUsers`のユーザー名の綴り。`Match`の段落の中に書いていないか |
| Windows側で何が起きたか知りたい | Windowsの「イベント ビューアー」→「アプリケーションとサービス ログ」→「OpenSSH」→「Operational」 |
| PowerShellのコマンドが「認識されていません」になる | **SSHで入った先はcmd**である。`powershell`と打ってから実行するか、`powershell -Command "…"`で呼ぶ。権限の問題ではない |
| `net localgroup`が「システム エラー 1376」になる | グループ名の打ち間違い（`administrators`の`s`が抜けている）。`whoami /groups`で確かめる |

## 鍵を足す・取り替える・取り消す

| したいこと | やること |
|---|---|
| **別の端末からもデプロイしたい** | その端末で1を行い、その公開鍵を4の棚に**1行足す**。端末ごとに別のペアにする |
| **秘密鍵が漏れた・Macを失くした** | 新しいペアを作って登録し、入れることを確かめてから、**棚から古い公開鍵の1行を消す**（[南京錠の問答 Q7](../questions/2026-11-09-how-ssh-keys-prove-who-you-are.md#q7-秘密鍵が自分の機械の外に出るのはどんなときか出てしまったらどうするか)） |
| **パスフレーズを忘れた** | 下の「パスフレーズを忘れたら」 |
| 鍵をやめる | 棚から公開鍵の行を消す |

### パスフレーズを忘れたら

**パスフレーズが分からない秘密鍵は、もう使えない**（金庫の番号を忘れた金庫と同じ）。**新しい鍵を作り、古い鍵は
Mac側とWindows側の両方から片付ける。**

```text
1. Macで新しい鍵のペアを作る（1-1〜1-3。ファイル名は古いものと分ける）
2. 新しい🔒（公開鍵）をWindowsの棚に1行足す            ← Windowsの前で
3. 新しい鍵で入れることを確かめる
4. Windowsの棚から、古い🔒の行を消す                    ← いちばん大事
5. Macから、古い🔑と古い🔒のファイルを消す
```

| 消すもの | 理由 |
|---|---|
| **Windowsの棚の、古い公開鍵の行**（4） | 古い秘密鍵は「今は開けられない」だけで、ファイルは残っている。将来ファイルとパスフレーズが両方漏れたら、まだ入れてしまう。**棚から外せば、古い鍵は二度と使えない** |
| Macの古い鍵のファイル（5） | 使えない鍵を残す理由が無い。どれが今の鍵か迷う元になる |

順番は「**新しい方で入れることを確かめてから、古い方を外す**」（締め出されないため）。

**忘れても、同じMacではすぐには困らない。**1-3でパスフレーズをキーチェーンに覚えさせているからである。
困るのは、Macを入れ直したときやキーチェーンが消えたときである。**パスワード管理ツールにも保存しておく。**

棚（`authorized_keys`）の1行が、1つの南京錠である。行を消せば、その鍵ではもう入れない。

## 初めて繋ぐとき・門番の顔が変わったとき

初めて繋ぐと、Windowsの「顔」（ホストの鍵の指紋）を信じるか聞かれる。

```text
The authenticity of host '<ホスト名>' can't be established.
ED25519 key fingerprint is SHA256:…
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

Windowsの前で、Windowsの指紋を表示して見比べられる。

```powershell
ssh-keygen -lf C:\ProgramData\ssh\ssh_host_ed25519_key.pub
```

**`REMOTE HOST IDENTIFICATION HAS CHANGED!`が出たら、理由が分かるまで繋がない。**
Windowsを入れ直した・OpenSSHを入れ直したなど、思い当たる理由が無ければ、偽の門番を疑う
（[南京錠の問答 Q8](../questions/2026-11-09-how-ssh-keys-prove-who-you-are.md#q8-偽の門番を信じて作業してしまうことは実際にあるのか)）。
