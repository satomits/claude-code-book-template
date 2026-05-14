# マウスジグラー作成マニュアル

Digispark ATtiny85を使ったマウスジグラーの作成手順。
USBに挿すだけでマウスカーソルが定期的に動き、PCのスリープやスクリーンセーバーを防止する。

## 必要なもの

- Digispark ATtiny85 USB開発ボード（1個、数百円程度）
- Arduino IDE
- USBポートのあるPC（書き込み用）

## 1. Arduino IDEのセットアップ

### Digisparkボードの追加

1. Arduino IDEを開く
2. **環境設定** > **追加のボードマネージャのURL** に以下を追加:
   ```
   https://raw.githubusercontent.com/digistump/arduino-boards-index/master/package_digistump_index.json
   ```
3. **ツール** > **ボード** > **ボードマネージャ** を開く
4. `Digistump AVR Boards` を検索してインストール

### ボードの選択

- **ツール** > **ボード** > **Digispark (Default - 16.5mhz)**

## 2. スケッチの書き込み

1. `mouse.ino` をArduino IDEで開く
2. **アップロード**ボタンをクリック
3. コンパイルが完了すると `Please plug in the device...` と表示される
4. **このメッセージが出てからDigisparkをUSBに挿す**（既に挿していてはダメ）
5. 数秒で書き込みが完了する

### 書き込みがうまくいかない場合

- USBハブを経由せず、PCに直接挿す
- 別のUSBポートを試す
- macOSの場合、libusb が必要な場合がある

## 3. 使い方

書き込み済みのDigisparkをPCのUSBポートに挿すだけ。

- 5秒ごとにマウスカーソルが右に5px動き、すぐ左に5px戻る
- 動きは極めて小さく、作業の邪魔にならない
- 抜けば即停止

## 4. カスタマイズ

`mouse.ino` の定数を変更することで動作を調整できる。

| 定数 | デフォルト値 | 説明 |
|------|-------------|------|
| `INTERVAL_MS` | `5000` | マウスを動かす間隔（ミリ秒） |
| `MOVE_PX` | `5` | マウスの移動量（ピクセル） |

## 仕様

- フラッシュメモリ使用量: 2660バイト / 6650バイト（40%）
- RAM使用量: 92バイト / 512バイト（17%）
