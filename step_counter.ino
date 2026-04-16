#include <Wire.h>

#define LSM6DS3_ADDR       0x6A  // I2C address (0x6B if SDO pin is high)

// Register addresses
#define WHO_AM_I           0x0F
#define CTRL1_XL           0x10  // Accelerometer control
#define CTRL2_G            0x11  // Gyroscope control
#define CTRL10_C           0x19  // Enable embedded functions (step counter)
#define TAP_CFG            0x58  // Enable pedometer
#define STEP_COUNTER_L     0x4B  // Step count low byte
#define STEP_COUNTER_H     0x4C  // Step count high byte
#define FUNC_SRC           0x53  // Function source / step detected flag

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

void initLSM6DS3() {
  // Accelerometer: 26Hz, +/-2g range
  writeRegister(CTRL1_XL, 0x20);

  // Gyroscope: 26Hz, 250dps range
  writeRegister(CTRL2_G, 0x20);

  // Enable embedded functions (required for pedometer)
  writeRegister(CTRL10_C, 0x3C);

  // Enable pedometer in TAP_CFG
  writeRegister(TAP_CFG, 0x40);
}

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);  // SDA = GPIO21, SCL = GPIO22

  delay(100);

  // Confirm chip is detected
  uint8_t whoAmI = readRegister(WHO_AM_I);
  if (whoAmI == 0x69) {
    Serial.println("LSM6DS3 detected OK");
  } else {
    Serial.print("Unexpected WHO_AM_I: 0x");
    Serial.println(whoAmI, HEX);
    Serial.println("Check wiring - SDA=21, SCL=22, VCC=3.3V, GND=GND");
    while (1);  // Halt if chip not found
  }

  initLSM6DS3();
  Serial.println("Pedometer initialized. Walk around to count steps.");
}

void loop() {
  uint16_t steps = readStepCount();

  Serial.print("Steps: ");
  Serial.println(steps);

  delay(1000);  // Print step count every second
}
