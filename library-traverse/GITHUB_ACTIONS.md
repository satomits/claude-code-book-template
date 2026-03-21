# GitHub Actions + GitHub Pages セットアップ

毎朝自動で図書館の貸出・予約状況を取得し、スマホのブラウザで確認できます。

---

## 仕組み

```
毎朝 7:00 → GitHub Actions が自動実行
         → 10館のデータを取得
         → モバイル対応HTMLを生成
         → GitHub Pages に公開
         → スマホで https://satomits.github.io/claude-code-book-template/ を開く
```

---

## セットアップ手順

### 1. CONFIG_YAML シークレットを登録する

GitHubリポジトリの **Settings → Secrets and variables → Actions → New repository secret** を開きます。

- **Name**: `CONFIG_YAML`
- **Secret**: `config.yaml` の中身をそのまま貼り付け

```yaml
libraries:
  yokohama:
    card_number: "あなたのカード番号"
    password: "あなたのパスワード"
  sagamihara:
    card_number: "あなたのカード番号"
    password: "あなたのパスワード"
  # 使わない館はこのファイルに書かなくてよい
```

**Save secret** をクリックして保存します。

> 認証情報はGitHubのサーバーに暗号化されて保存され、ログにも表示されません。

---

### 2. GitHub Pages を有効化する

GitHubリポジトリの **Settings → Pages** を開きます。

- **Source**: `GitHub Actions`

Save は不要です（選択するだけで有効になります）。

---

### 3. 動作確認（手動実行）

GitHubリポジトリの **Actions → 図書館状況チェック → Run workflow** をクリックします。

数分後に完了したら、以下のURLをスマホで開きます:

```
https://satomits.github.io/claude-code-book-template/
```

---

## スケジュール

デフォルトでは毎日 **7:00 JST** に自動実行されます。

変更する場合は `.github/workflows/library-check.yml` の `cron` を編集します:

```yaml
- cron: '0 22 * * *'   # 7:00 JST
- cron: '30 21 * * *'  # 6:30 JST
- cron: '0 0 * * *'    # 9:00 JST
```

---

## ホームスクリーンに追加（スマホ）

Safariまたは Chrome でページを開き、「ホーム画面に追加」すると、アプリのように起動できます。
