// Mouse Jiggler for Digispark ATtiny85
// PCのスリープ/スクリーンセーバーを防止するマウスジグラー

#include <DigiMouse.h>

// マウスを動かす間隔（ミリ秒）
#define INTERVAL_MS 5000  // 5秒

// マウス移動量（ピクセル）
#define MOVE_PX 5

void setup() {
  DigiMouse.begin();
}

void loop() {
  DigiMouse.delay(INTERVAL_MS);
  DigiMouse.moveX(MOVE_PX);
  DigiMouse.delay(100);
  DigiMouse.moveX(-MOVE_PX);
}
