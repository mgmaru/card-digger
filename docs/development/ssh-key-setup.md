# Macから家のWindowsへ、SSHの鍵で入る手順

## 文書ステータス

- 作成日: **2026-11-09**
- 対象: Mac（入る側）と、家のWindows（Windows標準のOpenSSHサーバー）
- 目的: MacからWindowsへ**鍵認証だけ**で入れるようにし、パスワードで入れる道を閉じる
- 根拠: ADR 0003の論点7（PR #48）で、「家のLANからも入れるまま、鍵認証だけにする（B）」と決めた
- **状態: 2026-11-09時点で、この手順を実機で最後まで通していない。**通したら結果で直し、この行を消す

なぜ鍵の方が安全か、何がまずいかは[南京錠の問答](../questions/2026-11-09-how-ssh-keys-prove-who-you-are.md)、
パスワードで家のLANから入れる状態がなぜ危ないかは[SSHの問答](../questions/2026-11-09-why-ssh-on-all-addresses-is-risky.md)にある。

## この手順書に書かないもの

**リポジトリは公開である。**次は説明用の書き方に置き換える。

| 書かない | この手順書での書き方 |
|---|---|
| Windowsのホスト名 | `<ホスト名>` |
| Windowsのユーザー名 | `<Windowsのユーザー名>` |
| tailnetの名前、IPアドレス | 書かない |
| **秘密鍵の中身** | 絶対に書かない・貼らない |
| 公開鍵の中身 | 漏れても困らないが、書く理由も無い |

鍵のファイル名（`id_ed25519`）や、鍵のコメントの例（`mac-to-windows`）は書いてよい。

## 全体の流れ

```mermaid
flowchart TD
    A["1. Macで鍵のペアを作る"] --> B["2. Windowsのアカウントが管理者か確かめる"]
    B --> C["3. 公開鍵をWindowsの棚に置く<br/>（Windowsの前で）"]
    C --> D{"4. 鍵で入れる？"}
    D -- "いいえ" --> T["トラブルシュートへ<br/>（パスワードはまだ切らない）"]
    D -- "はい" --> E["5. パスワードを切る<br/>（Windowsの前で）"]
    E --> F["6. 確かめる"]
```

**順番を守る。鍵で入れることを確かめる（4）より前に、パスワードを切らない（5）。**逆にすると締め出される。

## 1. Macで鍵のペアを作る

```bash
ssh-keygen -t ed25519 -C "mac-to-windows"
```

| 聞かれること | 答え |
|---|---|
| 保存先（`Enter file in which to save the key`） | そのままEnter（`~/.ssh/id_ed25519`） |
| パスフレーズ | **付ける。**秘密鍵のファイルを暗号化する（鍵を金庫に入れる） |

| `-C`を付ける理由 |
|---|
| 付けないと、鍵のコメントに**`Macのユーザー名@Macのホスト名`**が自動で入る。公開鍵をどこかに貼ったとき、それが見える |

できるもの。

| ファイル | 中身 | 扱い |
|---|---|---|
| `~/.ssh/id_ed25519` | 🔑 秘密鍵（`-----BEGIN OPENSSH PRIVATE KEY-----`で始まる） | **Macから出さない** |
| `~/.ssh/id_ed25519.pub` | 🔒 公開鍵（`ssh-ed25519 AAAA… mac-to-windows`の1行） | Windowsの棚に置く |

毎回パスフレーズを打たずに済むよう、macOSのキーチェーンに覚えさせる。

```bash
ssh-add --apple-use-keychain ~/.ssh/id_ed25519
```

`~/.ssh/config`の、Windowsへ入る`Host`の段落に3行を足す。

```text
Host <ホスト名>
  HostName <ホスト名>
  User <Windowsのユーザー名>
  Port 22
  IdentityFile ~/.ssh/id_ed25519
  AddKeysToAgent yes
  UseKeychain yes
```

## 2. Windowsのアカウントが管理者か確かめる

公開鍵の置き場所が、管理者かどうかで変わる（Windows標準のOpenSSHの既定）。Windowsのコマンドプロンプトで。

```bat
net localgroup administrators
```

| 一覧に`<Windowsのユーザー名>`が | 公開鍵の置き場所 |
|---|---|
| **ある（管理者）** | `C:\ProgramData\ssh\administrators_authorized_keys` |
| 無い（一般ユーザー） | `C:\Users\<Windowsのユーザー名>\.ssh\authorized_keys` |

## 3. 公開鍵をWindowsの棚に置く（Windowsの前で）

Macで公開鍵の1行を表示し、コピーする。

```bash
cat ~/.ssh/id_ed25519.pub
```

**`BEGIN … PRIVATE KEY`と表示されたら、それは秘密鍵である。コピーしない。**ファイル名に`.pub`が付いているかを確かめる。

### 管理者の場合（管理者のPowerShell）

スタートメニューで「PowerShell」を右クリックし、「管理者として実行」で開く。

```powershell
$key = 'ここにコピーした1行を貼る'
Add-Content -Path C:\ProgramData\ssh\administrators_authorized_keys -Value $key
# 管理者とSYSTEMだけが触れる権限にする（緩いとOpenSSHがこのファイルを無視する）
icacls.exe C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant "*S-1-5-32-544:F" /grant "*S-1-5-18:F"
```

| 書き方 | 意味 |
|---|---|
| `*S-1-5-32-544` | Administrators（管理者のグループ）。日本語のWindowsでも名前の違いを気にせず指定できる |
| `*S-1-5-18` | SYSTEM |
| `/inheritance:r` | 親フォルダーから引き継いだ権限を外す |

### 一般ユーザーの場合（PowerShell）

```powershell
New-Item -ItemType Directory -Force $env:USERPROFILE\.ssh | Out-Null
Add-Content -Path $env:USERPROFILE\.ssh\authorized_keys -Value 'ここにコピーした1行を貼る'
```

## 4. 鍵で入れることを確かめる（Mac）

```bash
ssh -o PasswordAuthentication=no <ホスト名>
```

| 結果 | 次 |
|---|---|
| **パスワードを聞かれずに入れた** | 5へ |
| 入れない | [トラブルシュート](#トラブルシュート)へ。**パスワードはまだ切らない**（いつもどおりパスワードで入れる） |

初めて鍵を使うときは、Macがキーチェーンのパスフレーズを聞くことがある。それは**Macの鍵の金庫を開けるもの**で、
Windowsのパスワードではない。

## 5. パスワードを切る（4が成功してから。Windowsの前で、管理者のPowerShell）

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

## 6. 確かめる（Mac）

| コマンド | 期待する結果 |
|---|---|
| `ssh <ホスト名>` | **入れる**（鍵で） |
| `ssh -o PubkeyAuthentication=no <ホスト名>` | **`Permission denied`で断られる**（パスワードの道が閉じた） |

## トラブルシュート

| 症状 | まず疑うこと |
|---|---|
| 鍵を置いたのにパスワードを聞かれる | **置き場所が違う**（2の管理者か一般ユーザーか）。**権限が緩い**（管理者の棚は`icacls`の結果が管理者とSYSTEMだけか） |
| 鍵を置いたのにパスワードを聞かれる | 貼った1行が欠けている・改行が混ざっている。`ssh-ed25519 AAAA…`で始まり、1行であるか |
| どの鍵を使っているか分からない | Macで`ssh -v <ホスト名>`。`Offering public key: … id_ed25519`が出るか |
| Windows側で何が起きたか知りたい | Windowsの「イベント ビューアー」→「アプリケーションとサービス ログ」→「OpenSSH」→「Operational」 |
| PowerShellのコマンドが「認識されていません」になる | **SSHで入った先はcmd**である。`powershell`と打ってから実行するか、`powershell -Command "…"`で呼ぶ。権限の問題ではない |

## 鍵を足す・取り替える・取り消す

| したいこと | やること |
|---|---|
| **別の端末からも入りたい** | その端末で1を行い、その公開鍵を3で**1行足す**。端末ごとに別のペアにする |
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
