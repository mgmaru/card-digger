# Macから家のWindowsへ、SSHの鍵で入る手順

## 文書ステータス

- 作成日: **2026-11-09**
- 対象: Mac（入る側）と、家のWindows（Windows標準のOpenSSHサーバー）
- 目的: Macから**デプロイ用の一般ユーザー**として、**鍵認証だけ**でWindowsへ入れるようにする。
  **パスワードで入る道と、管理者で入る道は閉じる**
- 根拠: ADR 0003（PR #48）の論点7（家のLANからも入れるまま、鍵認証だけにする）と、
  論点8（デプロイは専用の一般ユーザーで動かす。管理者用の鍵は作らず、管理者ではSSHで入れない）
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

鍵のファイル名（`id_ed25519_deploy`）や、鍵のコメントの例（`mac-to-windows-deploy`）は書いてよい。

## 0. どのアカウントで入るか

**最小権限（必要な権限だけを与える）**に従う。鍵を盗まれたとき、入られたアカウントにできることが、
そのまま被害の大きさになるからである。

| アカウント | 種類 | 使い方 | SSHで入れるか | Macの鍵 |
|---|---|---|---|---|
| `<デプロイ用ユーザー>`（新しく作る） | **一般ユーザー** | **デプロイ**。Card Diggerを動かす | **入れる（鍵だけ）** | `~/.ssh/id_ed25519_deploy`の1組 |
| `<管理者ユーザー>`（今のアカウント） | 管理者 | Windowsの管理。**Windowsの前で行う** | **入れない** | **作らない** |

**管理者用の鍵を作らない理由。**管理者の作業は「最初の1回」か「まれ」で、家にあるデスクトップなのでWindowsの前で
できる。**作らなければ、漏れることも無い。**SSHで入られたときの最悪も、Card Diggerの範囲に留まる。

**鍵を作らないだけでは足りない。**作業前は、管理者が**パスワードで**入れる。最後に`sshd_config`の
`AllowUsers`で、入れるユーザーをデプロイ用だけにして閉じる（6）。

## 全体の流れ

```mermaid
flowchart TD
    A["1. Macでデプロイ用の鍵を1組作る"] --> B["2. Windowsのアカウントを確かめる"]
    B --> C["3. デプロイ用の一般ユーザーを作る<br/>（Windowsの前で）"]
    C --> D["4. その人の公開鍵を置く<br/>（Windowsの前で）"]
    D --> E{"5. デプロイ用ユーザーで<br/>鍵で入れる？"}
    E -- "いいえ" --> T["トラブルシュートへ<br/>（sshd_configはまだ変えない）"]
    E -- "はい" --> F["6. パスワードと管理者の道を閉じる<br/>（Windowsの前で）"]
    F --> G["7. 確かめる"]
```

**順番を守る。デプロイ用ユーザーで鍵で入れることを確かめる（5）より前に、`sshd_config`を変えない（6）。**
6が終わると、管理者ではSSHで入れなくなる。作業はずっとWindowsの前で行う。

## 1. Macでデプロイ用の鍵を1組作る

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_deploy -C "mac-to-windows-deploy"
```

| 指定 | 意味 |
|---|---|
| `-f` | 鍵のファイル名。役割が分かる名前にする |
| `-C` | 鍵のコメント。**付けないと`Macのユーザー名@Macのホスト名`が自動で入り**、公開鍵を貼ったときに見える |
| パスフレーズ（聞かれる） | **付ける。**秘密鍵のファイルを暗号化する（鍵を金庫に入れる） |

できるもの。

| ファイル | 中身 | 扱い |
|---|---|---|
| `~/.ssh/id_ed25519_deploy` | 🔑 秘密鍵（`-----BEGIN OPENSSH PRIVATE KEY-----`で始まる） | **Macから出さない** |
| `~/.ssh/id_ed25519_deploy.pub` | 🔒 公開鍵（`ssh-ed25519 AAAA… mac-to-windows-deploy`の1行） | Windowsの棚に置く |

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

## 4. デプロイ用ユーザーの公開鍵を置く（Windowsの前で）

### 4-1. デプロイ用ユーザーとしてPowerShellを開く

ユーザーのフォルダー（`C:\Users\<デプロイ用ユーザー>`）は、**そのユーザーが初めてログオンしたときに作られる。**
`runas`で、そのユーザーとしてPowerShellを1つ開く（パスワードを聞かれる）。

```powershell
runas /user:<デプロイ用ユーザー> powershell
```

### 4-2. 公開鍵を置く（4-1で開いた、デプロイ用ユーザーのPowerShell）

Macで公開鍵の1行を表示し、コピーする。**`BEGIN … PRIVATE KEY`と表示されたら秘密鍵である。コピーしない。**
ファイル名に`.pub`が付いているかを確かめる。

```bash
cat ~/.ssh/id_ed25519_deploy.pub
```

**4-1で開いたウィンドウ（デプロイ用ユーザーとして動いている）で**実行する。そのユーザー自身が作るので、
ファイルの持ち主と権限が正しくなる。

```powershell
New-Item -ItemType Directory -Force $env:USERPROFILE\.ssh | Out-Null
Add-Content -Path $env:USERPROFILE\.ssh\authorized_keys -Value 'ここにコピーした1行を貼る'
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

## 6. パスワードと管理者の道を閉じる（5が成功してから。Windowsの前で、管理者のPowerShell）

**SSHで入った画面ではなく、Windowsの前で作業する。**設定を誤っても、Windowsの前なら直せる。

```powershell
notepad C:\ProgramData\ssh\sshd_config
```

次の2点を直して保存する。

| 直すところ | 書き方 | 意味 |
|---|---|---|
| `#PasswordAuthentication yes`の行 | 先頭の`#`を消して`PasswordAuthentication no` | パスワードでは入れない |
| ファイルの**`Match`で始まる行より前**に1行足す | `AllowUsers <デプロイ用ユーザー>` | **このユーザーしか入れない**（許可リスト）。管理者は鍵を持っていても入れない |

**`AllowUsers`は`Match`の行より前に書く。**Windowsの`sshd_config`の末尾には、もともと
`Match Group administrators`で始まる段落がある。その中に書くと、意図と違う効き方をする。

```powershell
Restart-Service sshd
```

## 7. 確かめる（Mac）

| コマンド | 期待する結果 |
|---|---|
| `ssh <ホスト名>-deploy whoami` | **入れる**。デプロイ用のアカウント名が出る |
| `ssh -o PubkeyAuthentication=no <ホスト名>-deploy` | **`Permission denied`で断られる**（パスワードの道が閉じた） |
| `ssh <管理者ユーザー>@<ホスト名>` | **`Permission denied`で断られる**（管理者の道が閉じた） |

## トラブルシュート

| 症状 | まず疑うこと |
|---|---|
| 鍵を置いたのにパスワードを聞かれる | `authorized_keys`を**管理者のウィンドウで作った**（持ち主が違う）。4-1で開いたデプロイ用ユーザーのウィンドウで作り直す |
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
