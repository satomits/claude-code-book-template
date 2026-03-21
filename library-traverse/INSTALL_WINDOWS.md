# Windows セットアップガイド

神奈川エリア図書館チェッカー (`library-traverse`) を Windows で使用するための手順です。

---

## 前提条件

- Windows 10 / 11
- インターネット接続

---

## 1. Git のインストール

[https://git-scm.com/download/win](https://git-scm.com/download/win) からインストーラーをダウンロードして実行します。

インストール時のオプションはデフォルトで問題ありません。

インストール確認:
```powershell
git --version
```

---

## 2. uv のインストール

[uv](https://docs.astral.sh/uv/) は Python と依存ライブラリを自動管理するツールです。

PowerShell を**管理者として実行**し、以下を貼り付けます:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

インストール後、**PowerShell を一度閉じて再度開いて**から確認します:

```powershell
uv --version
```

---

## 3. リポジトリのクローン

```powershell
git clone https://github.com/satomits/claude-code-book-template.git
cd claude-code-book-template\library-traverse
```

---

## 4. Python と依存ライブラリのインストール

```powershell
uv sync
```

uv が自動で適切な Python バージョンをインストールし、仮想環境を作成します。

---

## 5. Playwright ブラウザのインストール

図書館サイトのスクレイピングに Chromium ブラウザが必要です:

```powershell
uv run playwright install chromium
```

---

## 6. 設定ファイルの準備

```powershell
copy config.yaml.example config.yaml
```

`config.yaml` をメモ帳やエディタで開き、利用する図書館のカード番号とパスワードを記入します:

```yaml
libraries:
  yokohama:
    card_number: "あなたのカード番号"
    password: "あなたのパスワード"
  # 他の図書館は不要であればコメントアウトのまま
```

> **注意**: `config.yaml` には認証情報が含まれるため、Git にはコミットされません（`.gitignore` で除外済み）。

---

## 7. 実行

```powershell
# 基本実行（貸出・予約状況を表示）
uv run library-traverse

# 著者名を補完して表示（国立国会図書館APIを使用）
uv run library-traverse --detail

# PDF出力
uv run library-traverse --pdf result.pdf

# 著者名補完 + PDF出力
uv run library-traverse --detail --pdf result.pdf
```

---

## 更新方法

新しいバージョンを取得するには:

```powershell
cd claude-code-book-template
git pull origin main
cd library-traverse
uv sync
```

---

## トラブルシューティング

### `uv` コマンドが見つからない

PowerShell を閉じて開き直してください。それでも解決しない場合は、環境変数 PATH に `%USERPROFILE%\.local\bin` が含まれているか確認してください。

### ログインに失敗する

図書館のウェブサイトで直接ログインできるか確認してください。カード番号・パスワードに誤りがないか `config.yaml` を見直してください。

### 海老名・町田図書館でタイムアウトが発生する

これらの館はネットワーク環境によってアクセスできない場合があります。`config.yaml` からコメントアウトして除外してください。
