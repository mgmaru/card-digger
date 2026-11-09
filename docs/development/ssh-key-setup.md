# Macから家のWindowsへ、SSHの鍵で入る手順

## 文書ステータス

- 作成日: **2026-11-09**
- 対象: Mac（入る側）と、家のWindows（Windows標準のOpenSSHサーバー）
- 目的: MacからWindowsへ**鍵認証だけ**で入れるようにし、パスワードで入れる道を閉じる。
  **デプロイは専用の一般ユーザーで入る**
- 根拠: ADR 0003（PR #48）の論点7（家のLANからも入れるまま、鍵認証だけにする）と、
  論点8（デプロイは専用の一般ユーザーで動かす。管理者のSSHは鍵だけで残す）
- **状態: 2026-11-09時点で、この手順を実機で最後まで通していない。**通したら結果で直し、この行を消す

なぜ鍵の方が安全か、何がまずいかは[南京錠の問答](../questions/2026-11-09-how-ssh-keys-prove-who-you-are.md)、
パスワードで家のLANから入れる状態がなぜ危ないかは[SSHの問答](../questions/2026-11-09-why-ssh-on-all-addresses-is-risky.md)にある。

## この手順書に書かないもの

**リポジトリは公開である。**次は説明用の書き方に置き換える。

| 書かない | この手順書での書き方 |
|---|---|
| Windowsのホスト名 | `<ホスト名>` |
| 管理者のアカウント名 | `<管理者ユーザー>` |
| デプロイ用のアカウント名 | `<デプロイ用ユーザー>` |
| tailnetの名前、IPアドレス | 書かない |
| **秘密鍵の中身** | 絶対に書かない・貼らない |
| 公開鍵の中身 | 漏れても困らないが、書く理由も無い |

鍵のファイル名（`id_ed25519_admin`など）や、鍵のコメントの例（`mac-to-windows-admin`など）は書いてよい。

## 0. 2つのアカウントと、2組の鍵

**最小権限（必要な権限だけを与える）**に従い、SSHで入るアカウントを役割で分ける。鍵を盗まれたとき、
入られたアカウントにできることが、そのまま被害の大きさになるからである。

| アカウント | 種類 | 使う場面 | Macの鍵 | Windowsの棚（公開鍵の置き場所） |
|---|---|---|---|---|
| `<デプロイ用ユーザー>`（新しく作る） | **一般ユーザー** | **デプロイ**。Card Diggerを動かす | `~/.ssh/id_ed25519_deploy` | `C:\Users\<デプロイ用ユーザー>\.ssh\authorized_keys` |
| `<管理者ユーザー>`（今のアカウント） | 管理者 | Windowsの管理を遠隔で行うとき | `~/.ssh/id_ed25519_admin` | `C:\ProgramData\ssh\administrators_authorized_keys` |

**鍵も役割ごとに別のペアにする。**デプロイ用の鍵を盗まれても、管理者には入れない。

**公開鍵の置き場所は、自分で選ぶものではない。**入るアカウントが管理者なら`administrators_authorized_keys`、
一般ユーザーなら`authorized_keys`と、Windows標準のOpenSSHの既定で決まる。

## 全体の流れ

```mermaid
flowchart TD
    A["1. Macで鍵のペアを2組作る"] --> B["2. Windowsのアカウントを確かめる"]
    B --> C["3. 管理者の公開鍵を置く<br/>（Windowsの前で）"]
    C --> D["4. デプロイ用の一般ユーザーを作り、<br/>その人の公開鍵を置く（Windowsの前で）"]
    D --> E{"5. 2つとも鍵で入れる？"}
    E -- "いいえ" --> T["トラブルシュートへ<br/>（パスワードはまだ切らない）"]
    E -- "はい" --> F["6. パスワードを切る<br/>（Windowsの前で）"]
    F --> G["7. 確かめる"]
```

**順番を守る。鍵で入れることを確かめる（5）より前に、パスワードを切らない（6）。**逆にすると締め出される。

## 1. Macで鍵のペアを2組作る

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_admin  -C "mac-to-windows-admin"
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_deploy -C "mac-to-windows-deploy"
```

| 指定 | 意味 |
|---|---|
| `-f` | 鍵のファイル名。役割ごとに分ける |
| `-C` | 鍵のコメント。**付けないと`Macのユーザー名@Macのホスト名`が自動で入り**、公開鍵を貼ったときに見える |
| パスフレーズ（聞かれる） | **付ける。**秘密鍵のファイルを暗号化する（鍵を金庫に入れる） |

できるもの（2組それぞれ）。

| ファイル | 中身 | 扱い |
|---|---|---|
| `~/.ssh/id_ed25519_admin`、`~/.ssh/id_ed25519_deploy` | 🔑 秘密鍵（`-----BEGIN OPENSSH PRIVATE KEY-----`で始まる） | **Macから出さない** |
| `~/.ssh/id_ed25519_admin.pub`、`~/.ssh/id_ed25519_deploy.pub` | 🔒 公開鍵（`ssh-ed25519 AAAA… mac-to-windows-…`の1行） | Windowsの棚に置く |

毎回パスフレーズを打たずに済むよう、macOSのキーチェーンに覚えさせる。

```bash
ssh-add --apple-use-keychain ~/.ssh/id_ed25519_admin
ssh-add --apple-use-keychain ~/.ssh/id_ed25519_deploy
```

`~/.ssh/config`に、**入り口の名前を2つ**書く。同じWindowsでも、入るアカウントと使う鍵が違う。

```text
# 管理の作業
Host <ホスト名>
  HostName <ホスト名>
  User <管理者ユーザー>
  IdentityFile ~/.ssh/id_ed25519_admin
  IdentitiesOnly yes
  AddKeysToAgent yes
  UseKeychain yes

# デプロイ
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
| **`IdentitiesOnly yes`** | **指定した鍵だけを使う。**付けないと、Macが持つほかの鍵も順に試し、違う役割の鍵で入ってしまうことがある |

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

### `Administrator`アカウントが無効か

**管理者の棚（`administrators_authorized_keys`）は、管理者グループ全員で共有される。**ここに置いた鍵では、
このPCのどの管理者アカウントにも入れる。Windowsに最初から入っている`Administrator`アカウントが有効だと、
そちらにも入れてしまう。

```bat
net user Administrator | findstr アカウント有効
```

| 結果 | 対処 |
|---|---|
| `アカウント有効   No` | 問題なし |
| `アカウント有効   Yes` | 使っていなければ無効にする（管理者のPowerShellで`net user Administrator /active:no`） |

## 3. 管理者の公開鍵を置く（Windowsの前で、管理者のPowerShell）

スタートメニューで「PowerShell」を右クリックし、「管理者として実行」で開く。

Macで公開鍵の1行を表示し、コピーする。**`BEGIN … PRIVATE KEY`と表示されたら秘密鍵である。コピーしない。**

```bash
cat ~/.ssh/id_ed25519_admin.pub
```

```powershell
$key = 'ここにコピーした1行を貼る'
Add-Content -Path C:\ProgramData\ssh\administrators_authorized_keys -Value $key
# 管理者とSYSTEMだけが触れる権限にする（緩いとOpenSSHがこのファイルを無視する）
icacls.exe C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant "*S-1-5-32-544:F" /grant "*S-1-5-18:F"
```

| 書き方 | 意味 |
|---|---|
| `*S-1-5-32-544` | Administrators。日本語のWindowsでも名前の違いを気にせず指定できる |
| `*S-1-5-18` | SYSTEM |
| `/inheritance:r` | 親フォルダーから引き継いだ権限を外す |

権限を確かめる。

```powershell
icacls.exe C:\ProgramData\ssh\administrators_authorized_keys
```

`BUILTIN\Administrators:(F)`と`NT AUTHORITY\SYSTEM:(F)`の**2行だけ**なら正しい。ほかの名前が混ざっていると、
OpenSSHがこのファイルを無視する。

## 4. デプロイ用の一般ユーザーを作り、その人の公開鍵を置く（Windowsの前で）

### 4-1. ユーザーを作る（管理者のPowerShell）

```powershell
$pw = Read-Host -AsSecureString "デプロイ用ユーザーのパスワード"
New-LocalUser -Name "<デプロイ用ユーザー>" -Password $pw -Description "Card Digger deploy" -PasswordNeverExpires
Add-LocalGroupMember -SID S-1-5-32-545 -Member "<デプロイ用ユーザー>"   # Users（一般ユーザー）のグループ
```

| 注意 | 理由 |
|---|---|
| **管理者のグループ（`S-1-5-32-544`）には入れない** | 一般ユーザーにするのが目的 |
| パスワードは設定する | SSHはパスワードで入れなくする（6）が、タスクスケジューラーで「ログオンしていなくても動かす」設定にパスワードが要る。**SSHのパスワードとしては使えなくなる** |
| `-PasswordNeverExpires` | 期限切れでCard Diggerのタスクが動かなくなるのを避ける |

### 4-2. デプロイ用ユーザーのフォルダーを作る

ユーザーのフォルダー（`C:\Users\<デプロイ用ユーザー>`）は、**そのユーザーが初めてログオンしたときに作られる。**
`runas`で、そのユーザーとしてPowerShellを1つ開く（パスワードを聞かれる）。

```powershell
runas /user:<デプロイ用ユーザー> powershell
```

### 4-3. 公開鍵を置く（4-2で開いた、デプロイ用ユーザーのPowerShell）

Macでデプロイ用の公開鍵の1行を表示し、コピーする。

```bash
cat ~/.ssh/id_ed25519_deploy.pub
```

**4-2で開いたウィンドウ（デプロイ用ユーザーとして動いている）で**実行する。そのユーザー自身が作るので、
ファイルの持ち主と権限が正しくなる。

```powershell
New-Item -ItemType Directory -Force $env:USERPROFILE\.ssh | Out-Null
Add-Content -Path $env:USERPROFILE\.ssh\authorized_keys -Value 'ここにコピーした1行を貼る'
```

## 5. 2つとも鍵で入れることを確かめる（Mac）

```bash
ssh -o PasswordAuthentication=no <ホスト名>          # 管理者
ssh -o PasswordAuthentication=no <ホスト名>-deploy   # デプロイ用
```

| 結果 | 次 |
|---|---|
| **2つとも、パスワードを聞かれずに入れた** | 6へ |
| どちらかが入れない | [トラブルシュート](#トラブルシュート)へ。**パスワードはまだ切らない** |

入れたら、それぞれ`whoami`で、**意図したアカウントで入っているか**を確かめる。

初めて鍵を使うときは、Macがキーチェーンのパスフレーズを聞くことがある。それは**Macの鍵の金庫を開けるもの**で、
Windowsのパスワードではない。

## 6. パスワードを切る（5が成功してから。Windowsの前で、管理者のPowerShell）

**SSHで入った画面ではなく、Windowsの前で作業する。**設定を誤っても、Windowsの前なら直せる。

```powershell
notepad C:\ProgramData\ssh\sshd_config
```

`#PasswordAuthentication yes`の行を探し、先頭の`#`を消して`no`にし、保存する。

```text
PasswordAuthentication no
```

```powershell
Restart-Service sshd
```

## 7. 確かめる（Mac）

| コマンド | 期待する結果 |
|---|---|
| `ssh <ホスト名> whoami` | **入れる**。管理者のアカウント名が出る |
| `ssh <ホスト名>-deploy whoami` | **入れる**。デプロイ用のアカウント名が出る |
| `ssh -o PubkeyAuthentication=no <ホスト名>` | **`Permission denied`で断られる** |
| `ssh -o PubkeyAuthentication=no <ホスト名>-deploy` | **`Permission denied`で断られる** |

## トラブルシュート

| 症状 | まず疑うこと |
|---|---|
| 管理者で、鍵を置いたのにパスワードを聞かれる | **権限が緩い**（3の`icacls`の結果が管理者とSYSTEMの2行だけか） |
| デプロイ用で、鍵を置いたのにパスワードを聞かれる | `authorized_keys`を**管理者のウィンドウで作った**（持ち主が違う）。4-2で開いたデプロイ用ユーザーのウィンドウで作り直す |
| どちらでも、鍵を置いたのにパスワードを聞かれる | 貼った1行が欠けている・改行が混ざっている。`ssh-ed25519 AAAA…`で始まる1行か |
| どの鍵を使っているか分からない | Macで`ssh -v <ホスト名>-deploy`。`Offering public key: … id_ed25519_deploy`が出るか |
| 違うアカウントで入ってしまう | `~/.ssh/config`の`User`と`IdentityFile`、`IdentitiesOnly yes`があるか |
| Windows側で何が起きたか知りたい | Windowsの「イベント ビューアー」→「アプリケーションとサービス ログ」→「OpenSSH」→「Operational」 |
| PowerShellのコマンドが「認識されていません」になる | **SSHで入った先はcmd**である。`powershell`と打ってから実行するか、`powershell -Command "…"`で呼ぶ。権限の問題ではない |
| `net localgroup`が「システム エラー 1376」になる | グループ名の打ち間違い（`administrators`の`s`が抜けている）。`whoami /groups`で確かめる |

## 鍵を足す・取り替える・取り消す

| したいこと | やること |
|---|---|
| **別の端末からも入りたい** | その端末で1を行い、その公開鍵を3・4の棚に**1行足す**。端末ごとに別のペアにする |
| **秘密鍵が漏れた・Macを失くした** | 新しいペアを作って登録し、入れることを確かめてから、**棚から古い公開鍵の1行を消す**（[南京錠の問答 Q7](../questions/2026-11-09-how-ssh-keys-prove-who-you-are.md#q7-秘密鍵が自分の機械の外に出るのはどんなときか出てしまったらどうするか)） |
| 管理者ではSSHで入れないようにする | `sshd_config`に`AllowUsers <デプロイ用ユーザー>`を書き、`Restart-Service sshd`。管理の作業はWindowsの前で行う（ADR 0003 論点8。デプロイが回り始めてから検討する） |
| 鍵をやめる | 棚から公開鍵の行を消す |

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
