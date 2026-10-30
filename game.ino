// =============================================================================
//  MÁY QUAY XÈNG 3 CUỘN FULLSCREEN (3-REEL SLOT MACHINE)
//  Dành cho Arduino Nano (ATmega328P) + ST7735 1.77" (160x128) + Còi Buzzer
//  
//  Task 1: Đồ họa máy quay xèng fullscreen 160x128 theo mẫu ảnh người dùng:
//          3 cuộn quay ánh kim loại vàng 3D, 10 mẫu biểu tượng slot sắc nét:
//          1. Dollar ($)   2. BAR         3. Cherry       4. Watermelon
//          5. Plum         6. Bell        7. YS           8. Diamond
//          9. Lemon       10. Star
//  Task 2: Hệ thống âm thanh còi buzzer (tiếng quay cạch cạch, tiếng khóa cuộn,
//          nhạc chiến thắng jackpot khi trúng 3 biểu tượng giống nhau).
//          Tỉ lệ trúng 3 cái giống nhau vừa phải (~28%) không quá khó.
//  Task 3: Giao diện thuần đồ họa 100% fullscreen, KHÔNG CHỮ, tự động quay vòng lặp.
//  Debug & Hardware Fixes:
//          - Sửa lỗi SPI pixel writing (SPI_WRITE16 thay cho no-op write16)
//          - Hỗ trợ đổi tab màn hình (BlackTab / RedTab / GreenTab) & Đảo màu (Invert)
//            lưu trực tiếp vào EEPROM qua Serial Monitor hoặc nút Pin 2.
//          - Serial Debug Monitor 115200 baud hiển thị rõ ràng từng trạng thái.
// =============================================================================

#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <SPI.h>
#include <EEPROM.h>
#include "slot_assets.h"

// -----------------------------------------------------------------------------
//  CẤU HÌNH CHÂN PHẦN CỨNG
// -----------------------------------------------------------------------------
#define TFT_CS      10
#define TFT_DC       9
#define TFT_RST      8
#define BUZZER_PIN   3
#define BUTTON_PIN   2   // Chân nút bấm tùy chọn (kéo lên INPUT_PULLUP)

Adafruit_ST7735 tft = Adafruit_ST7735(TFT_CS, TFT_DC, TFT_RST);

// -----------------------------------------------------------------------------
//  BẢNG MÀU RGB565 BỔ SUNG
// -----------------------------------------------------------------------------
#define C_BLACK       0x0000
#define C_WHITE       0xFFFF
#define C_RED         0xF800
#define C_GOLD_DARK   0x9C42
#define C_GOLD_BRIGHT 0xFFE0
#define C_CREAM       0xFFFE

// -----------------------------------------------------------------------------
//  CẤU TRÚC 3 CUỘN QUAY (3 REELS)
// -----------------------------------------------------------------------------
#define NUM_REELS      3
#define REEL_WIDTH    46
#define REEL_INNER_W  42
#define REEL_HEIGHT  120
#define SYM_SIZE      36
#define SLOT_HEIGHT   48   // Mỗi ô cao 48px (36px hình + 12px khoảng đệm)
#define STRIP_LEN     10   // 10 biểu tượng trên mỗi dải cuộn
#define TOTAL_STRIP_H (STRIP_LEN * SLOT_HEIGHT) // 480px

const uint8_t reel_x_pos[NUM_REELS] = { 6, 57, 108 };

// Dải biểu tượng trên 3 cuộn (chứa đầy đủ cả 10 mẫu biểu tượng 0..9)
const uint8_t strip0[STRIP_LEN] PROGMEM = { 0, 1, 2, 3, 4, 5, 6, 7, 8, 9 };
const uint8_t strip1[STRIP_LEN] PROGMEM = { 1, 3, 5, 7, 9, 0, 2, 4, 6, 8 };
const uint8_t strip2[STRIP_LEN] PROGMEM = { 2, 5, 8, 0, 3, 6, 9, 1, 4, 7 };

const uint8_t* const reelStrips[NUM_REELS] PROGMEM = {
  strip0, strip1, strip2
};

// Trạng thái từng cuộn
int16_t currentPos[NUM_REELS] = { 0, 0, 0 };
int16_t targetPos[NUM_REELS]  = { 0, 0, 0 };
uint8_t targetSym[NUM_REELS]  = { 0, 0, 0 };
uint8_t forceJackpotNext = 0; // 0=None, 1=Random Jackpot, 2=Force YS (6)
bool forceLoseNext = false;

// -----------------------------------------------------------------------------
//  CẤU HÌNH EEPROM CHO CÁC BIẾN THỂ MÀN HÌNH ST7735
// -----------------------------------------------------------------------------
#define EEPROM_MAGIC 0x5C

struct DisplayConfig {
  uint8_t magic;      // 0x5C
  uint8_t tabType;    // 0 = BLACKTAB (RGB), 1 = REDTAB (BGR), 2 = GREENTAB (Offset)
  uint8_t isInverted; // 0 = Bình thường, 1 = Đảo màu (Inverted IPS/ST7735S)
} config;

void saveConfig() {
  EEPROM.update(0, config.magic);
  EEPROM.update(1, config.tabType);
  EEPROM.update(2, config.isInverted);
}

void loadConfig() {
  config.magic      = EEPROM.read(0);
  config.tabType    = EEPROM.read(1);
  config.isInverted = EEPROM.read(2);

  if (config.magic != EEPROM_MAGIC || config.tabType > 2 || config.isInverted > 1) {
    config.magic      = EEPROM_MAGIC;
    config.tabType    = 0; // Mặc định BLACKTAB
    config.isInverted = 0; // Mặc định Normal
    saveConfig();
  }
}

// -----------------------------------------------------------------------------
//  TRUYỀN DỮ LIỆU SPI TỐC ĐỘ CAO CHO ARDUINO AVR
// -----------------------------------------------------------------------------
static inline void fastWritePixel(uint16_t color) {
#if defined(__AVR__)
  SPDR = (uint8_t)(color >> 8);
  while (!(SPSR & _BV(SPIF)));
  SPDR = (uint8_t)(color & 0xFF);
  while (!(SPSR & _BV(SPIF)));
#else
  tft.SPI_WRITE16(color);
#endif
}

static inline void fastFillColor(uint16_t color, uint8_t count) {
#if defined(__AVR__)
  uint8_t hi = (uint8_t)(color >> 8);
  uint8_t lo = (uint8_t)(color & 0xFF);
  while (count--) {
    SPDR = hi;
    while (!(SPSR & _BV(SPIF)));
    SPDR = lo;
    while (!(SPSR & _BV(SPIF)));
  }
#else
  tft.writeColor(color, count);
#endif
}

// -----------------------------------------------------------------------------
//  TASK 2: ÂM THANH CÒI BUZZER
// -----------------------------------------------------------------------------
void playBeep(uint16_t freq, uint16_t dur) {
  tone(BUZZER_PIN, freq, dur);
  delay(dur + 10);
  noTone(BUZZER_PIN);
  digitalWrite(BUZZER_PIN, LOW);
}

void soundSpinTick() {
  tone(BUZZER_PIN, 950, 10);
}

void soundReelLock(uint8_t reelIndex) {
  uint16_t freq = (reelIndex == 0) ? 600 : ((reelIndex == 1) ? 800 : 1100);
  playBeep(freq, (reelIndex == 2) ? 60 : 40);
}

// -----------------------------------------------------------------------------
//  VẼ ĐỒ HỌA MÁY QUAY XÈNG (TASK 1 & TASK 3: THUẦN ĐỒ HỌA KHÔNG CHỮ)
// -----------------------------------------------------------------------------

// Vẽ khung viền kim loại bo góc cho 3 cuộn (ôm khít bên ngoài, không bị đè)
void drawMachineBorders(uint16_t outerCol = C_GOLD_DARK, uint16_t innerCol = C_CREAM) {
  for (uint8_t r = 0; r < NUM_REELS; r++) {
    uint8_t rx = reel_x_pos[r];
    // Viền ngoài ánh kim đồng (y: 2..125, chiều cao 124)
    tft.drawRoundRect(rx, 2, REEL_WIDTH, REEL_HEIGHT + 4, 3, outerCol);
    // Viền trong vàng kim / kem lấp lánh (y: 3..124, chiều cao 122)
    tft.drawRoundRect(rx + 1, 3, REEL_WIDTH - 2, REEL_HEIGHT + 2, 2, innerCol);
  }
}

// Vẽ mũi tên chỉ vạch trả thưởng (Payline Indicators) bên trái và phải
void drawPaylineIndicators(bool highlight) {
  uint16_t colBody = highlight ? C_GOLD_BRIGHT : C_RED;
  uint16_t colTip  = highlight ? C_WHITE : C_GOLD_BRIGHT;

  // Cả mũi tên trái (0..5) và mũi tên phải (154..159)
  for (int8_t dy = -4; dy <= 4; dy++) {
    int16_t y = 64 + dy;
    uint8_t len = 5 - abs(dy);
    for (uint8_t x = 0; x <= len; x++) {
      uint16_t c = (x == len || abs(dy) >= 3) ? colTip : colBody;
      tft.drawPixel(x, y, c);
      tft.drawPixel(159 - x, y, c);
    }
  }
}

// Vẽ toàn bộ cột cuộn quay 42x120 pixels bằng luồng SPI tốc độ cao
void drawReelColumn(uint8_t reelIdx, int16_t pos) {
  uint8_t rx = reel_x_pos[reelIdx];
  const uint8_t* strip = (const uint8_t*)pgm_read_ptr(&reelStrips[reelIdx]);

  tft.startWrite();
  tft.setAddrWindow(rx + 2, 4, REEL_INNER_W, REEL_HEIGHT);

  // Tính toán vị trí bắt đầu tại y = 0 sao cho tại tâm y=60 tương ứng chính xác tâm ô pos
  int16_t strip_y = (pos - 42 + TOTAL_STRIP_H * 2) % TOTAL_STRIP_H;
  uint8_t sym_slot = strip_y / SLOT_HEIGHT;
  uint8_t sym_row  = strip_y % SLOT_HEIGHT;
  uint8_t sym_idx  = pgm_read_byte(&strip[sym_slot]);
  const uint8_t* bmp  = (const uint8_t*)pgm_read_ptr(&symbolBitmaps[sym_idx]);
  const uint16_t* pal = (const uint16_t*)symbolPalettes[sym_idx];

  for (uint8_t y = 0; y < REEL_HEIGHT; y++) {
    uint16_t bg = pgm_read_word(&reelGradient[y]);

    // 3 pixel lề trái cuộn
    fastFillColor(bg, 3);

    // 36 pixel thân biểu tượng (4-bit nibble indexed, 18 bytes)
    if (sym_row < 36) {
      uint16_t rowOffset = (uint16_t)sym_row * 18;

      for (uint8_t b_idx = 0; b_idx < 18; b_idx++) {
        uint8_t b  = pgm_read_byte(&bmp[rowOffset + b_idx]);
        uint8_t n0 = b >> 4;
        uint8_t n1 = b & 0x0F;

        fastWritePixel((n0 == 0) ? bg : pgm_read_word(&pal[n0]));
        fastWritePixel((n1 == 0) ? bg : pgm_read_word(&pal[n1]));
      }
    } else {
      // 12 pixel khoảng đệm giữa các biểu tượng
      fastFillColor(bg, 36);
    }

    // 3 pixel lề phải cuộn
    fastFillColor(bg, 3);

    // Tăng dòng cuộn không cần modulo
    sym_row++;
    if (sym_row >= SLOT_HEIGHT) {
      sym_row = 0;
      sym_slot++;
      if (sym_slot >= STRIP_LEN) sym_slot = 0;
      sym_idx = pgm_read_byte(&strip[sym_slot]);
      bmp  = (const uint8_t*)pgm_read_ptr(&symbolBitmaps[sym_idx]);
      pal  = (const uint16_t*)symbolPalettes[sym_idx];
    }
  }

  tft.endWrite();
}

// Áp dụng cấu hình màn hình
void applyDisplayConfig() {
  uint8_t opt = INITR_BLACKTAB;
  if (config.tabType == 1) opt = INITR_REDTAB;
  else if (config.tabType == 2) opt = INITR_GREENTAB;

  tft.initR(opt);
  tft.setRotation(1); // 160x128 landscape
  tft.invertDisplay(config.isInverted ? true : false);
  tft.fillScreen(C_BLACK);
}

// Vẽ toàn bộ máy quay xèng và trạng thái các cuộn
void drawSlotMachine() {
  tft.fillScreen(C_BLACK);
  drawMachineBorders();
  drawPaylineIndicators(false);

  for (uint8_t r = 0; r < NUM_REELS; r++) {
    drawReelColumn(r, currentPos[r]);
  }
}

// -----------------------------------------------------------------------------
//  LOGIC QUAY XÈNG VÀ TỈ LỆ TRÚNG
// -----------------------------------------------------------------------------

// Tìm vị trí ô cuộn để biểu tượng dừng ngay giữa tâm vạch trả thưởng
int16_t getSlotPosForSymbol(uint8_t reelIdx, uint8_t sym) {
  const uint8_t* strip = (const uint8_t*)pgm_read_ptr(&reelStrips[reelIdx]);
  for (uint8_t slot = 0; slot < STRIP_LEN; slot++) {
    if (pgm_read_byte(&strip[slot]) == sym) {
      return slot * SLOT_HEIGHT;
    }
  }
  return 0;
}

// Quyết định kết quả ván chơi với tỉ lệ vừa phải (~28% trúng 3 cái giống nhau)
void prepareNextSpin() {
  uint8_t roll = random(100);

  if (!forceLoseNext && (forceJackpotNext > 0 || roll < 28)) {
    // THẮNG JACKPOT (~28%): Cả 3 cuộn ra cùng 1 biểu tượng ("3 cái giống nhau")
    uint8_t winSym = (forceJackpotNext == 2) ? 6 : random(10);
    targetSym[0] = targetSym[1] = targetSym[2] = winSym;
    forceJackpotNext = 0;
  } else if (!forceLoseNext && roll < 58) {
    // SUÝT THẮNG (Near-Miss 30%): Cuộn 1 & 2 giống nhau, cuộn 3 kề cận tạo kịch tính
    uint8_t symA = random(10);
    targetSym[0] = targetSym[1] = symA;
    targetSym[2] = (symA + 1 + random(9)) % 10;
  } else {
    // VÁN BÌNH THƯỜNG (42%): Không có 3 biểu tượng giống nhau
    targetSym[0] = random(10);
    targetSym[1] = (targetSym[0] + 1 + random(9)) % 10;
    targetSym[2] = (targetSym[1] + 1 + random(9)) % 10;
    forceLoseNext = false;
  }

  // Đặt vị trí đích cho từng cuộn
  for (uint8_t r = 0; r < NUM_REELS; r++) {
    targetPos[r] = getSlotPosForSymbol(r, targetSym[r]);
  }

  Serial.print(F("[SPIN] "));
  Serial.print(targetSym[0]);
  Serial.print(' ');
  Serial.print(targetSym[1]);
  Serial.print(' ');
  Serial.println(targetSym[2]);
}

// Chờ cho nút bấm được nhả ra hoàn toàn (chống dội phím) và xóa đệm Serial
void waitButtonRelease() {
  while (digitalRead(BUTTON_PIN) == LOW) {
    delay(10);
  }
  delay(40);
  while (Serial.available() > 0) {
    Serial.read();
  }
}

// -----------------------------------------------------------------------------
//  GIAO TIẾP SERIAL MONITOR
// -----------------------------------------------------------------------------
void printConfigStatus() {
  Serial.print(F("[CFG] Tab=")); Serial.print(config.tabType);
  Serial.print(F(" Inv=")); Serial.println(config.isInverted);
}

bool handleSerialCommands() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    char lc = c | 0x20;
    if (lc == 'b' || lc == 'r' || lc == 'g') {
      config.tabType = (lc == 'b') ? 0 : ((lc == 'r') ? 1 : 2);
      saveConfig();
      applyDisplayConfig();
      printConfigStatus();
      return true;
    } else if (lc == 'i') {
      config.isInverted = !config.isInverted;
      saveConfig();
      tft.invertDisplay(config.isInverted ? true : false);
      printConfigStatus();
      return true;
    } else if (lc == 'w') {
      forceJackpotNext = 1;
      Serial.println(F("[CMD] Force JACKPOT!"));
      return true;
    } else if (lc == 'y') {
      forceJackpotNext = 2;
      Serial.println(F("[CMD] Force YS!"));
      return true;
    } else if (lc == 'l') {
      forceLoseNext = true;
      Serial.println(F("[CMD] Force LOSE!"));
      return true;
    } else if (c >= 32 || c == '\r' || c == '\n') {
      return true;
    }
  }
  return false;
}

// Kiểm tra nút bấm vật lý (có chống dội 25ms) hoặc lệnh Serial
bool checkTrigger() {
  if (handleSerialCommands()) return true;
  if (digitalRead(BUTTON_PIN) == LOW) {
    delay(25);
    if (digitalRead(BUTTON_PIN) == LOW) return true;
  }
  return false;
}

// -----------------------------------------------------------------------------
//  MÀN HÌNH 1: GIAO DIỆN BẮT ĐẦU (CÓ CHỮ BẮT ĐẦU TO)
// -----------------------------------------------------------------------------
static void drawBatDauText(int16_t x, int16_t y, uint16_t col) {
  tft.setTextColor(col);
  tft.setCursor(x, y);
  tft.print(F("BAT DAU"));
  // Dấu á trên chữ A thứ nhất
  tft.drawFastHLine(x + 23, y - 3, 5, col);
  tft.drawPixel(x + 22, y - 4, col);
  tft.drawPixel(x + 28, y - 4, col);
  tft.drawLine(x + 25, y - 5, x + 28, y - 8, col);

  // Gạch ngang chữ Đ
  tft.fillRect(x + 69, y + 10, 8, 2, col);

  // Dấu ầ trên chữ A thứ hai
  tft.drawLine(x + 94, y - 3, x + 97, y - 6, col);
  tft.drawLine(x + 97, y - 6, x + 100, y - 3, col);
  tft.drawLine(x + 93, y - 8, x + 95, y - 6, col);
}

void showStartScreen() {
redrawStart:
  tft.fillScreen(C_BLACK);
  waitButtonRelease();

  // Khung viền phong cách Arcade ánh kim
  tft.drawRoundRect(4, 4, 152, 120, 6, C_GOLD_DARK);
  tft.drawRoundRect(6, 6, 148, 116, 4, C_GOLD_BRIGHT);
  tft.drawRect(8, 8, 144, 112, 0x4208);

  // Tiêu đề phía trên
  tft.setTextSize(1);
  tft.setTextColor(C_GOLD_BRIGHT);
  tft.setCursor(29, 18);
  tft.print(F("* MAY QUAY XENG *"));

  // Đường trang trí ngăn cách
  tft.drawFastHLine(14, 32, 132, C_GOLD_DARK);

  // CHỮ BẮT ĐẦU TO (Size 3)
  tft.setTextSize(3);
  drawBatDauText(19, 48, 0x7800);       // Đổ bóng 3D
  drawBatDauText(17, 46, C_GOLD_BRIGHT); // Chữ chính vàng kim

  // Đường viền trang trí ngăn cách dưới
  tft.drawFastHLine(14, 82, 132, C_GOLD_DARK);

  // Đèn trang trí góc
  tft.drawPixel(10, 10, C_GOLD_BRIGHT);
  tft.drawPixel(149, 10, C_GOLD_BRIGHT);
  tft.drawPixel(10, 117, C_GOLD_BRIGHT);
  tft.drawPixel(149, 117, C_GOLD_BRIGHT);

  // Dòng nhắc nhở phía dưới
  tft.setTextSize(1);
  tft.setTextColor(C_WHITE);
  tft.setCursor(23, 96);
  tft.print(F("> BAM NUT DE QUAY <"));

  // Âm thanh báo màn hình sẵn sàng
  playBeep(880, 50);
  playBeep(1175, 80);

  Serial.println(F("[START] BAT DAU"));

  uint32_t lastBlink = millis();
  bool promptOn = true;

  while (true) {
    if (Serial.available() > 0) {
      char c = Serial.peek();
      char lc = c | 0x20;
      if (lc == 'b' || lc == 'r' || lc == 'g' || lc == 'i') {
        handleSerialCommands();
        goto redrawStart;
      } else {
        handleSerialCommands();
        break;
      }
    }

    if (digitalRead(BUTTON_PIN) == LOW) {
      delay(25);
      if (digitalRead(BUTTON_PIN) == LOW) {
        uint32_t pressStart = millis();
        while (digitalRead(BUTTON_PIN) == LOW) {
          if (millis() - pressStart > 2000) {
            config.tabType = (config.tabType + 1) % 3;
            saveConfig();
            playBeep(1500, 150);
            applyDisplayConfig();
            printConfigStatus();
            waitButtonRelease();
            goto redrawStart;
          }
          delay(10);
        }

        // Nhấn ngắn: Bắt đầu quay!
        playBeep(988, 50);
        playBeep(1319, 80);
        break;
      }
    }

    if (millis() - lastBlink > 400) {
      lastBlink = millis();
      promptOn = !promptOn;
      tft.setTextSize(1);
      tft.setTextColor(promptOn ? C_WHITE : C_BLACK, C_BLACK);
      tft.setCursor(23, 96);
      tft.print(F("> BAM NUT DE QUAY <"));
    }

    delay(15);
  }

  waitButtonRelease();
}

// -----------------------------------------------------------------------------
//  MÀN HÌNH 2: GIAO DIỆN PHÁO HOA KHI TRÚNG 3 CÁI GIỐNG NHAU (CHÚC MỪNG)
// -----------------------------------------------------------------------------
const uint16_t victoryNotes[14] PROGMEM = {
  523, 659, 784, 1046, // C5, E5, G5, C6
  784, 1046, 1318,     // G5, C6, E6
  1046, 1175, 1318, 1568, // C6, D6, E6, G6
  1318, 1568, 2093     // E6, G6, C7
};
const uint16_t victoryDurs[14] PROGMEM = {
  80, 80, 80, 160,
  80, 80, 240,
  90, 90, 90, 250,
  120, 120, 450
};

#define NUM_SPARKS 40
const int8_t fireworkDirs[NUM_SPARKS][2] PROGMEM = {
  {  16,   0 }, {  16,   3 }, {  15,   5 }, {  14,   7 },
  {  13,   9 }, {  11,  11 }, {   9,  13 }, {   7,  14 },
  {   5,  15 }, {   3,  16 }, {   0,  16 }, {  -3,  16 },
  {  -5,  15 }, {  -7,  14 }, {  -9,  13 }, { -11,  11 },
  { -13,   9 }, { -14,   7 }, { -15,   5 }, { -16,   3 },
  { -16,   0 }, { -16,  -3 }, { -15,  -5 }, { -14,  -7 },
  { -13,  -9 }, { -11, -11 }, {  -9, -13 }, {  -7, -14 },
  {  -5, -15 }, {  -3, -16 }, {   0, -16 }, {   3, -16 },
  {   5, -15 }, {   7, -14 }, {   9, -13 }, {  11, -11 },
  {  13,  -9 }, {  14,  -7 }, {  15,  -5 }, {  16,  -3 }
};

const uint16_t burstColors[8] PROGMEM = {
  C_GOLD_BRIGHT, 0x07FF, 0xF81F, 0x07E0, C_RED, C_WHITE, 0xFDE0, 0xFD20
};

struct SparkParticle {
  int16_t x, y, vx, vy;
  int8_t  lastPx, lastPy;
  uint8_t life;
};

static uint8_t nIdx = 0;
static uint32_t nStart = 0;
static uint16_t nDur = 0;

static void advanceFanfare() {
  if (nIdx < 14 && (millis() - nStart >= nDur + 20)) {
    nIdx++;
    if (nIdx < 14) {
      tone(BUZZER_PIN, pgm_read_word(&victoryNotes[nIdx]));
      nDur = pgm_read_word(&victoryDurs[nIdx]);
      nStart = millis();
    } else {
      noTone(BUZZER_PIN);
      digitalWrite(BUZZER_PIN, LOW);
    }
  }
}

void showFireworksScreen() {
  tft.fillScreen(C_BLACK);
  waitButtonRelease();
  Serial.println(F("[WIN-FIREWORKS]"));

  SparkParticle sparks[NUM_SPARKS];
  nIdx = 0;
  nDur = pgm_read_word(&victoryDurs[0]);
  tone(BUZZER_PIN, pgm_read_word(&victoryNotes[0]));
  nStart = millis();

  uint8_t burstCounter = 0;

  // Lặp liên tục cho đến khi người dùng bấm nút D2 hoặc gõ Serial
  while (true) {
    if (checkTrigger()) break;

    burstCounter++;
    // Tái phát nhạc chiến thắng sau mỗi 5 loạt pháo hoa để không khí luôn sôi động
    if (burstCounter % 5 == 0 && nIdx >= 14) {
      nIdx = 0;
      nDur = pgm_read_word(&victoryDurs[0]);
      tone(BUZZER_PIN, pgm_read_word(&victoryNotes[0]));
      nStart = millis();
    }

    int16_t burstX = random(25, 135);
    int16_t burstY = random(35, 75);
    uint16_t col = pgm_read_word(&burstColors[random(8)]);

    // 1. Quả pháo bay vút từ đáy màn hình lên với âm rít
    int16_t ry = 126;
    int16_t rx = burstX;
    while (ry > burstY) {
      if (checkTrigger()) goto exitFireworks;
      advanceFanfare();
      if (nIdx >= 14) {
        tone(BUZZER_PIN, 750 + (126 - ry) * 10, 8);
      }

      tft.drawPixel(rx, ry, C_GOLD_BRIGHT);
      delay(3);
      tft.drawPixel(rx, ry, C_BLACK);
      ry -= 4;
      if (random(2) == 0) rx += random(-1, 2);
      if (rx < 4) rx = 4;
      if (rx > 155) rx = 155;
    }

    // 2. Chớp lóe điểm nổ pháo hoa hình ngôi sao rực rỡ + tiếng nổ pop
    if (nIdx >= 14) {
      tone(BUZZER_PIN, 140, 25);
    }
    tft.drawFastHLine(burstX - 5, burstY, 11, C_WHITE);
    tft.fillRect(burstX, burstY - 5, 1, 11, C_WHITE);
    tft.fillRect(burstX - 2, burstY - 2, 5, 5, C_GOLD_BRIGHT);
    delay(20);
    tft.drawFastHLine(burstX - 5, burstY, 11, C_BLACK);
    tft.fillRect(burstX, burstY - 5, 1, 11, C_BLACK);
    tft.fillRect(burstX - 2, burstY - 2, 5, 5, C_BLACK);

    // 3. Khởi tạo 40 tia lửa pháo hoa (Bán kính nổ lớn, 3 lớp hạt đa tầng)
    int16_t baseSpd = random(72, 98);
    for (uint8_t i = 0; i < NUM_SPARKS; i++) {
      sparks[i].x = burstX << 8;
      sparks[i].y = burstY << 8;
      int8_t dx = (int8_t)pgm_read_byte(&fireworkDirs[i][0]);
      int8_t dy = (int8_t)pgm_read_byte(&fireworkDirs[i][1]);

      if (i % 3 == 0) {
        // Lớp ngoài tỏa rộng tối đa (Giant burst)
        sparks[i].vx = (dx * baseSpd) / 2;
        sparks[i].vy = (dy * baseSpd) / 2;
        sparks[i].life = random(32, 46);
      } else if (i % 3 == 1) {
        // Lớp giữa
        int16_t midSpd = (baseSpd * 3) / 4;
        sparks[i].vx = (dx * midSpd) / 2;
        sparks[i].vy = (dy * midSpd) / 2;
        sparks[i].life = random(24, 36);
      } else {
        // Lớp trong lấp lánh tâm nổ
        int16_t inSpd = (baseSpd * 9) / 16;
        sparks[i].vx = (dx * inSpd) / 2;
        sparks[i].vy = (dy * inSpd) / 2;
        sparks[i].life = random(18, 28);
      }
      sparks[i].lastPx = -1;
      sparks[i].lastPy = -1;
    }

    // 4. Di chuyển các tia lửa pháo hoa rơi rụng tự nhiên (trọng lực + lực cản)
    bool active = true;
    while (active) {
      if (checkTrigger()) goto exitFireworks;
      advanceFanfare();

      active = false;
      for (uint8_t i = 0; i < NUM_SPARKS; i++) {
        if (sparks[i].life > 0) {
          active = true;
          if (sparks[i].lastPx >= 0 && sparks[i].lastPy >= 0) {
            tft.drawPixel(sparks[i].lastPx, sparks[i].lastPy, C_BLACK);
          }
          sparks[i].x += sparks[i].vx;
          sparks[i].y += sparks[i].vy;
          sparks[i].vy += 7; // Trọng lực nhẹ rơi tự nhiên
          sparks[i].vx = (sparks[i].vx * 62) / 64; // Lực cản không khí
          sparks[i].vy = (sparks[i].vy * 62) / 64;

          int16_t px = sparks[i].x >> 8;
          int16_t py = sparks[i].y >> 8;
          if (px >= 0 && px < 160 && py >= 0 && py < 128) {
            uint16_t pCol = col;
            if (sparks[i].life > 34) pCol = C_WHITE;
            else if (sparks[i].life < 8) pCol = C_GOLD_DARK;
            else if (sparks[i].life < 4) pCol = C_RED;
            tft.drawPixel(px, py, pCol);
            sparks[i].lastPx = px;
            sparks[i].lastPy = py;
          } else {
            sparks[i].lastPx = -1;
            sparks[i].lastPy = -1;
          }
          sparks[i].life--;
        } else if (sparks[i].lastPx >= 0) {
          if (sparks[i].lastPy >= 0) {
            tft.drawPixel(sparks[i].lastPx, sparks[i].lastPy, C_BLACK);
          }
          sparks[i].lastPx = -1;
          sparks[i].lastPy = -1;
        }
      }
      delay(15);
    }
    delay(50);
  }

exitFireworks:
  noTone(BUZZER_PIN);
  digitalWrite(BUZZER_PIN, LOW);
  waitButtonRelease();
}

// -----------------------------------------------------------------------------
//  MÀN HÌNH 3: GIAO DIỆN KHÔNG TRÚNG (CHÚC BẠN MAY MẮN LẦN SAU)
// -----------------------------------------------------------------------------
void showLoseScreen() {
  tft.fillScreen(C_BLACK);
  waitButtonRelease();

  // Khung trang trí tao nhã
  tft.drawRoundRect(8, 8, 144, 112, 4, C_GOLD_DARK);
  tft.drawRect(10, 10, 140, 108, 0x5269);
  tft.fillRect(12, 12, 136, 104, 0x10A2);

  // Dòng chữ: CHÚC BẠN MAY MẮN LẦN SAU (cân đối khoảng cách, dấu không bị đè)
  tft.setTextSize(2);
  tft.setTextColor(C_WHITE);
  tft.setCursor(32, 28);
  tft.print(F("CHUC BAN"));
  // Dấu sắc trên chữ Ú (x=56..65)
  tft.drawLine(61, 25, 64, 22, C_WHITE);
  tft.drawLine(62, 25, 65, 22, C_WHITE);
  // Dấu nặng dưới chữ Ạ (x=104..113)
  tft.fillRect(108, 43, 2, 2, C_WHITE);

  tft.setTextColor(C_GOLD_BRIGHT);
  tft.setCursor(38, 52);
  tft.print(F("MAY MAN"));
  // Dấu á trên chữ Ắ (x=98..107)
  tft.drawFastHLine(101, 50, 4, C_GOLD_BRIGHT);
  tft.drawLine(103, 49, 105, 46, C_GOLD_BRIGHT);

  tft.setTextColor(C_CREAM);
  tft.setCursor(38, 76);
  tft.print(F("LAN SAU"));
  // Dấu ầ trên chữ Ầ (x=50..59)
  tft.drawLine(52, 74, 55, 71, C_CREAM);
  tft.drawLine(55, 71, 58, 74, C_CREAM);
  tft.drawLine(52, 69, 54, 71, C_CREAM);

  // Nhắc nhở bấm nút
  tft.setTextSize(1);
  tft.setTextColor(C_WHITE);
  tft.setCursor(20, 100);
  tft.print(F("> BAM DE TIEP TUC <"));

  // Âm thanh nhẹ nhàng (2 nốt trầm)
  playBeep(523, 140);
  playBeep(392, 220);

  Serial.println(F("[LOSE-SCREEN]"));

  // Chờ người dùng nhấn nút hoặc gõ Serial
  uint32_t lastBlink = millis();
  bool textVisible = true;
  while (true) {
    if (checkTrigger()) {
      playBeep(800, 50);
      break;
    }

    if (millis() - lastBlink > 400) {
      lastBlink = millis();
      textVisible = !textVisible;
      tft.setTextSize(1);
      tft.setTextColor(textVisible ? C_WHITE : 0x10A2, 0x10A2);
      tft.setCursor(20, 100);
      tft.print(F("> BAM DE TIEP TUC <"));
    }
    delay(15);
  }

  waitButtonRelease();
}

// -----------------------------------------------------------------------------
//  SETUP & MAIN LOOP
// -----------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);

  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  noTone(BUZZER_PIN);

  pinMode(BUTTON_PIN, INPUT_PULLUP);

  // Khởi tạo hạt giống ngẫu nhiên từ điện áp nhiễu chân analog
  randomSeed(analogRead(A0) + analogRead(A1) + micros());

  loadConfig();
  printConfigStatus();

  // Khởi động màn hình
  applyDisplayConfig();

  // Khởi tạo 3 vị trí biểu tượng ban đầu (Dollar)
  currentPos[0] = getSlotPosForSymbol(0, 0);
  currentPos[1] = getSlotPosForSymbol(1, 0);
  currentPos[2] = getSlotPosForSymbol(2, 0);

  Serial.println(F("[READY] Slot machine ready."));
}

void loop() {
  // 1. Hiển thị Giao diện Bắt đầu có chữ "BAT DAU" to
  showStartScreen();

  // 2. Chuyển sang Giao diện Máy quay xèng và vẽ các cuộn
  drawSlotMachine();

  // 3. Chuẩn bị kết quả vòng quay mới (Tỉ lệ ~28% trúng 3 cái giống nhau)
  prepareNextSpin();

  // 4. Chạy hoạt ảnh cuộn quay cuộn xuống tự nhiên (Spinning Animation downwards)
  uint8_t spinSpeed = 12; // Tốc độ trượt 12 pixel (chia hết cho SLOT_HEIGHT 48)
  uint16_t frameCount = 0;
  bool reelStopped[NUM_REELS] = { false, false, false };
  uint16_t reelLockFrame[NUM_REELS] = { 0, 0, 0 };

  const uint8_t minSpinReel0 = 16;   // Cuộn 0 quay tối thiểu 16 frame
  const uint8_t extraSpinReel1 = 12; // Cuộn 1 quay thêm ít nhất 12 frame sau khi Cuộn 0 khóa
  const uint8_t extraSpinReel2 = 14; // Cuộn 2 quay thêm ít nhất 14 frame sau khi Cuộn 1 khóa (kịch tính)

  Serial.println(F("[SPIN] Rolling reels..."));

  while (!reelStopped[0] || !reelStopped[1] || !reelStopped[2]) {
    frameCount++;

    // Tiếng cạch cạch cơ học nhịp nhàng mỗi 2 frame
    if (frameCount % 2 == 0) {
      soundSpinTick();
    }

    for (uint8_t r = 0; r < NUM_REELS; r++) {
      if (!reelStopped[r]) {
        bool canLock = false;
        if (r == 0) {
          if (frameCount >= minSpinReel0) canLock = true;
        } else if (r == 1) {
          if (reelStopped[0] && (frameCount - reelLockFrame[0] >= extraSpinReel1)) canLock = true;
        } else if (r == 2) {
          if (reelStopped[1] && (frameCount - reelLockFrame[1] >= extraSpinReel2)) canLock = true;
        }

        if (canLock) {
          int16_t dist = (currentPos[r] - targetPos[r] + TOTAL_STRIP_H) % TOTAL_STRIP_H;
          if (dist <= spinSpeed) {
            // Khóa cuộn tại vị trí đích chính xác
            currentPos[r] = targetPos[r];
            reelStopped[r] = true;
            reelLockFrame[r] = frameCount;
            drawReelColumn(r, currentPos[r]);
            soundReelLock(r);
            Serial.print(F("[LOCK] "));
            Serial.print(r);
            Serial.print(':');
            Serial.println(targetSym[r]);
            continue;
          }
        }
        // Tiếp tục cuộn quay xuống
        currentPos[r] = (currentPos[r] - spinSpeed + TOTAL_STRIP_H) % TOTAL_STRIP_H;
        drawReelColumn(r, currentPos[r]);
      }
    }

    handleSerialCommands();
    delay(8);
  }

  // 5. Đánh giá kết quả ván chơi
  bool isJackpot = (targetSym[0] == targetSym[1] && targetSym[1] == targetSym[2]);

  if (isJackpot) {
    // Nhấp nháy vạch trả thưởng 3 lần để người chơi nhìn rõ 3 biểu tượng trúng thưởng
    for (uint8_t k = 0; k < 3; k++) {
      drawPaylineIndicators(true);
      drawMachineBorders(C_WHITE, C_GOLD_BRIGHT);
      playBeep(1200, 60);
      drawPaylineIndicators(false);
      drawMachineBorders();
      delay(40);
    }
    delay(200);

    // Chuyển sang Giao diện pháo hoa chiến thắng (thuần đồ họa, không chữ)
    showFireworksScreen();
  } else {
    // Dừng quan sát kết quả 600ms
    delay(600);
    // Chuyển sang Giao diện Chúc bạn may mắn lần sau
    showLoseScreen();
  }

  // Sau khi nhấn nút, loop() tự động quay lại bước 1: Hiển thị lại Giao diện Bắt đầu!
}
