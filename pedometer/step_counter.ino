#include "DEV_Config.h"
#include "EPD.h"
#include "GUI_Paint.h"
#include <stdlib.h>
#include <Wire.h>

#define MAX_LINES 18            // Reduced by 2 to leave room for step count bar at bottom
#define MAX_CHARS_PER_LINE 50
#define LINE_HEIGHT 16

// LSM6DS3 I2C settings
#define LSM6DS3_ADDR    0x6A    // Try 0x6B if chip not detected
#define WHO_AM_I        0x0F
#define CTRL1_XL        0x10
#define CTRL2_G         0x11
#define CTRL10_C        0x19
#define TAP_CFG         0x58
#define STEP_COUNTER_L  0x4B
#define STEP_COUNTER_H  0x4C

#define REFRESH_INTERVAL_MS 5000  // 5 second refresh

UBYTE *BlackImage = NULL;
uint16_t lastStepCount = 0;
unsigned long lastRefresh = 0;

// ── LSM6DS3 helpers ──────────────────────────────────────────────────────────

void writeRegister(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(LSM6DS3_ADDR);
    Wire.write(reg);
    Wire.write(value);
    Wire.endTransmission();
}

uint8_t readRegister(uint8_t reg) {
    Wire.beginTransmission(LSM6DS3_ADDR);
    Wire.write(reg);
    Wire.endTransmission(false);
    Wire.requestFrom(LSM6DS3_ADDR, 1);
    return Wire.read();
}

uint16_t readStepCount() {
    uint8_t low  = readRegister(STEP_COUNTER_L);
    uint8_t high = readRegister(STEP_COUNTER_H);
    return ((uint16_t)high << 8) | low;
}

bool initLSM6DS3() {
    Wire.begin(21, 22);  // SDA=GPIO21, SCL=GPIO22
    delay(100);

    uint8_t whoAmI = readRegister(WHO_AM_I);
    if (whoAmI != 0x69) {
        printf("LSM6DS3 not found. WHO_AM_I=0x%02X (expected 0x69)\r\n", whoAmI);
        printf("Check wiring or try changing LSM6DS3_ADDR to 0x6B\r\n");
        return false;
    }
    printf("LSM6DS3 detected OK\r\n");

    writeRegister(CTRL1_XL, 0x20);   // Accel: 26Hz, +/-2g
    writeRegister(CTRL2_G,  0x20);   // Gyro:  26Hz, 250dps
    writeRegister(CTRL10_C, 0x3C);   // Enable embedded functions
    writeRegister(TAP_CFG,  0x40);   // Enable pedometer
    return true;
}

// ── Display helpers ──────────────────────────────────────────────────────────

void drawStepCountBar(uint16_t steps) {
    // Draw a divider line above the step count
    Paint_DrawLine(0, 270, 400, 270, BLACK, DOT_PIXEL_1X1, LINE_STYLE_SOLID);

    // Clear the bottom strip
    Paint_DrawRectangle(0, 271, 400, 300, WHITE, DOT_PIXEL_1X1, DRAW_FILL_FULL);

    // Build step string
    char stepStr[32];
    snprintf(stepStr, sizeof(stepStr), "Steps today: %u", steps);

    // Draw centered in the bottom strip (y=278 centers Font16 in a 29px strip)
    Paint_DrawString_EN(10, 278, stepStr, &Font16, BLACK, WHITE);
}

void refreshDisplay(uint16_t steps) {
    Paint_SelectImage(BlackImage);

    // Redraw text content from file
    FILE *file = fopen("test.txt", "r");
    if (file != NULL) {
        Paint_Clear(WHITE);
        char line[MAX_CHARS_PER_LINE + 1];
        int y_position = 10;
        int line_count = 0;

        while (fgets(line, sizeof(line), file) != NULL && line_count < MAX_LINES) {
            line[strcspn(line, "\n")] = 0;
            Paint_DrawString_EN(10, y_position, line, &Font12, BLACK, WHITE);
            y_position += LINE_HEIGHT;
            line_count++;
        }
        fclose(file);
    }

    drawStepCountBar(steps);
    EPD_4IN2_V2_Display(BlackImage);
}

// ── Setup ────────────────────────────────────────────────────────────────────

void setup() {
    printf("EPD + Step Counter Demo\r\n");

    // Init e-paper
    DEV_Module_Init();
    printf("e-Paper Init and Clear...\r\n");
    EPD_4IN2_V2_Init();
    EPD_4IN2_V2_Clear();
    DEV_Delay_ms(500);

    // Allocate image buffer
    UWORD Imagesize = ((EPD_4IN2_V2_WIDTH % 8 == 0)
        ? (EPD_4IN2_V2_WIDTH / 8)
        : (EPD_4IN2_V2_WIDTH / 8 + 1)) * EPD_4IN2_V2_HEIGHT;

    if ((BlackImage = (UBYTE *)malloc(Imagesize)) == NULL) {
        printf("Failed to allocate image buffer\r\n");
        while (1);
    }
    Paint_NewImage(BlackImage, EPD_4IN2_V2_WIDTH, EPD_4IN2_V2_HEIGHT, 0, WHITE);

    // Init accelerometer
    if (!initLSM6DS3()) {
        // Not fatal — display will still work, steps will read 0
        printf("Continuing without step counter\r\n");
    }

    // Initial draw
    lastStepCount = readStepCount();
    refreshDisplay(lastStepCount);
    lastRefresh = millis();

    printf("Setup complete. Refreshing every 5 seconds.\r\n");
}

// ── Loop ─────────────────────────────────────────────────────────────────────

void loop() {
    unsigned long now = millis();

    if (now - lastRefresh >= REFRESH_INTERVAL_MS) {
        lastStepCount = readStepCount();

        Serial.print("Steps: ");
        Serial.println(lastStepCount);

        EPD_4IN2_V2_Init();         // Re-init required before each display update
        refreshDisplay(lastStepCount);

        lastRefresh = now;
    }
}
