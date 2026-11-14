# Plant Monitor — Sensors Firmware Proposal

Firmware and hardware integration proposal for the sensor nodes defined in [the project README](../README.md).

## Hardware Components

From [../README.md](../README.md):
- **MCU:** WiFi ESP8266 (ESP-12E) — NodeMCU V3 Lua (CH340)
- **Air sensor:** DHT22 Temperature and Humidity sensor
- **Soil sensor:** Keyestudio KS0049 soil humidity sensor
- **Battery:** 3.7V 1100mAh Li-Po battery

Additional supporting components required for safe operation and deep sleep:
- **10 kΩ resistor** — pull-up on DHT22 `DATA` (omit if using a 3-pin DHT22 breakout module with a built-in pull-up)
- **470 Ω resistor** (or Schottky diode, cathode to `D0`) — connects `D0` to `RST` for deep-sleep wakeups without interfering with USB flashing
- **TP4056 charger/protection module + 3.3V LDO regulator** (rated `≥ 500 mA`, e.g. `AP2112K-3.3`) with a **100–470 µF capacitor** across `3V3`/`GND` *(or a 5V boost module wired to `VIN`)* — protects the Li-Po from over-discharge and prevents `4.2V` full-charge voltage from damaging the `3.3V` ESP8266

---

## Circuit Diagram

```text
   3.7V 1100mAh Li-Po
     (+)           (-)
      |             |
  +---v-------------v---+
  |  TP4056 Protection  |  <-- Over-discharge protection + USB charging
  |   + 3.3V LDO*       |      (*e.g. AP2112K-3.3 >=500mA, or 5V Boost -> VIN)
  +---+-------------+---+
      | 3.3V        | GND
      |             +---------------------------------------+
      |             |                                       |
      |    +--------v--------+                              |
      |    |    NodeMCU V3   |                              |
      |    |  (ESP8266 12E)  |                              |
      |    |                 |                              |
      +--->| 3V3         GND |------------------------------+
      |    |                 |                              |
      |    |        D0/GPIO16|---[ 470 Ω ]---+              |
      |    |             RST |---------------+              |
      |    |                 |  (remove jumper when         |
      |    |                 |   flashing over USB)         |
      |    |                 |                              |
      |    |        D2/GPIO4 |-------------------+          |
      |    |                 |                   |          |
      |    |       D5/GPIO14 |-------+           |          |
      |    |                 |       |           |          |
      |    |              A0 |---+   |           |          |
      |    +-----------------+   |   |           |          |
      |                          |   |           |          |
      |  [10 kΩ]                 |   |           |          |
      |     |                    |   |           |          |
      +-----+--------------------+---+--+        |          |
      |     |                    |   |  |        |          |
      |     +--------------------+---+--+----+   |          |
      |                          |   |  |    |   |          |
      |    +---------------------+   |  |    |   |          |
      |    |      +------------------+  |    |   |          |
      |    |      |                     |    |   |          |
   +--v----v------v--+               +--v----v---v------+   |
   |  S    +      -  |               | VCC  DATA   GND  |   |
   | Keyestudio      |               |     DHT22        |   |
   | KS0049 Soil     |               +------------------+   |
   +-----------------+                                      |
             |                                              |
             +----------------------------------------------+
```

### Pin-to-Pin Wiring

| From | To | Purpose |
|---|---|---|
| Li-Po (`+` / `-`) | TP4056 + 3.3V LDO | Over-discharge protection and steady `3.3V` regulation |
| 3.3V LDO Out | NodeMCU `3V3` + DHT22 `VCC` | Main `3.3V` supply rail |
| Power `GND` | NodeMCU `GND` + DHT22 `GND` + KS0049 `-` | Common ground |
| NodeMCU `D2` (`GPIO4`) | DHT22 `DATA` | Digital temperature & humidity signal |
| `3V3` | DHT22 `DATA` (via `10 kΩ`) | Pull-up resistor *(if not built into DHT22 module)* |
| NodeMCU `D5` (`GPIO14`) | KS0049 `+` (`VCC`) | Switched power—enabled only ~100 ms per reading to avoid probe electrolysis |
| NodeMCU `A0` | KS0049 `S` (`Signal`) | Analog moisture reading (`0–3.3V` via NodeMCU onboard voltage divider) |
| NodeMCU `D0` (`GPIO16`) | NodeMCU `RST` (via `470 Ω` or Schottky diode) | Deep-sleep hardware wake pulse |

### Safety & Flashing Notes
1. **Disconnect the battery / external `3V3` LDO before connecting USB**, so the onboard AMS1117 regulator and external regulator do not fight on the `3V3` rail.
2. If you wire `D0` to `RST` with a plain jumper instead of a resistor/diode, **unplug the jumper while flashing**, then reconnect it afterward.

---

## Toolchain & Firmware Proposal (PlatformIO)

Use **PlatformIO** (`espressif8266` platform, `nodemcuv2` board, Arduino framework).

### Proposed `platformio.ini`

```ini
[env:nodemcuv2]
platform = espressif8266
board = nodemcuv2
framework = arduino
monitor_speed = 115200
lib_deps =
  adafruit/DHT sensor library@^1.4.6
  adafruit/Adafruit Unified Sensor@^1.1.14
  bblanchon/ArduinoJson@^7.0.0
```

### Execution Lifecycle

Because `ESP.deepSleep()` resets the ESP8266 on wakeup (wiping normal RAM and resetting `millis()` to `0`), the firmware persists a small `RtcData` struct in the ESP8266's **512-byte RTC user memory** (which survives deep sleep and clears on power loss or manual reset):

1. On boot, check `ESP.getResetInfoPtr()->reason == REASON_DEEP_SLEEP_AWAKE` and validate RTC memory (`magic` + `checksum`). If it is a fresh power-on, initialize `uptimeMs = 0` and `bootCount = 1`; otherwise increment `bootCount`.
2. Wait ~2s after boot for the DHT22 to stabilize, then read temperature (°C) and air humidity (%).
3. Drive `D5` (`SOIL_PWR_PIN`) `HIGH` for ~100 ms, average 5 samples from `A0`, drive `D5` `LOW`, and map the raw value (`0–1023`) to `0–100%` using calibrated `SOIL_DRY_RAW` and `SOIL_WET_RAW` constants.
4. Connect to Wi-Fi in station mode (`15s` timeout).
5. Send an HTTP `POST` to the backend API (`../backend/README.md`) with `X-API-Key` and JSON body including `uptimeSeconds` and `bootCount`:
   ```json
   {
     "deviceId": "AA:BB:CC:DD:EE:FF",
     "temperatureC": 23.4,
     "humidityPct": 54.2,
     "soilMoisturePct": 41,
     "uptimeSeconds": 908,
     "bootCount": 2
   }
   ```
6. Save `uptimeMs += millis() + (SLEEP_SECONDS * 1000ULL)` back to RTC memory, disconnect Wi-Fi, and enter `ESP.deepSleep(SLEEP_SECONDS * 1000000ULL)` (e.g., 15 minutes).

> **Note on drift:** The ESP8266 internal sleep oscillator can drift slightly (~1–5%), so `uptimeSeconds` is an estimate of battery runtime. The backend also records exact UTC timestamps (`ts`) for every reading.

### Proposed `src/main.cpp`

```cpp
#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <DHT.h>
#include <ArduinoJson.h>
extern "C" {
  #include "user_interface.h"
}

// Wi-Fi & API config (move to a gitignored secrets.h before committing)
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* API_URL   = "http://your-api-host:8000/api/readings"; // Use WiFiClientSecure for https://
const char* API_KEY   = "change-me";

// Pins (NodeMCU labels -> GPIO)
#define DHT_PIN        D2    // GPIO4
#define DHT_TYPE       DHT22
#define SOIL_PWR_PIN   D5    // GPIO14
#define SOIL_ADC_PIN   A0

// Calibrate using raw A0 readings in dry air vs. water
const int SOIL_DRY_RAW = 850;
const int SOIL_WET_RAW = 350;

// Deep sleep interval (15 minutes)
const uint64_t SLEEP_SECONDS = 15 * 60;

// RTC memory struct (must be a multiple of 4 bytes)
const uint32_t RTC_MAGIC = 0x504C4E54; // "PLNT"
struct RtcData {
  uint32_t magic;
  uint32_t bootCount;
  uint64_t uptimeMs;
  uint32_t checksum;
};

RtcData rtcData;
DHT dht(DHT_PIN, DHT_TYPE);

uint32_t calcChecksum(const RtcData& data) {
  return data.magic ^ data.bootCount ^ (uint32_t)(data.uptimeMs & 0xFFFFFFFF) ^
         (uint32_t)(data.uptimeMs >> 32);
}

void loadRtcState() {
  bool wokeFromSleep = (ESP.getResetInfoPtr()->reason == REASON_DEEP_SLEEP_AWAKE);
  bool validRtc = ESP.rtcUserMemoryRead(0, (uint32_t*)&rtcData, sizeof(rtcData)) &&
                  rtcData.magic == RTC_MAGIC &&
                  rtcData.checksum == calcChecksum(rtcData);

  if (wokeFromSleep && validRtc) {
    rtcData.bootCount += 1;
  } else {
    rtcData.magic = RTC_MAGIC;
    rtcData.bootCount = 1;
    rtcData.uptimeMs = 0;
  }
}

void saveRtcStateBeforeSleep() {
  rtcData.uptimeMs += millis() + (SLEEP_SECONDS * 1000ULL);
  rtcData.checksum = calcChecksum(rtcData);
  ESP.rtcUserMemoryWrite(0, (uint32_t*)&rtcData, sizeof(rtcData));
}

int readSoilPercent() {
  digitalWrite(SOIL_PWR_PIN, HIGH);
  delay(100);

  long sum = 0;
  for (int i = 0; i < 5; i++) {
    sum += analogRead(SOIL_ADC_PIN);
    delay(10);
  }
  digitalWrite(SOIL_PWR_PIN, LOW);

  int raw = sum / 5;
  int pct = map(raw, SOIL_DRY_RAW, SOIL_WET_RAW, 0, 100);
  return constrain(pct, 0, 100);
}

bool connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(250);
  }
  return WiFi.status() == WL_CONNECTED;
}

void postReading(float tempC, float humidity, int soilPct) {
  WiFiClient client;
  HTTPClient http;

  if (!http.begin(client, API_URL)) {
    Serial.println("HTTP begin failed");
    return;
  }

  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);

  uint64_t totalUptimeSec = (rtcData.uptimeMs + millis()) / 1000ULL;

  JsonDocument doc;
  doc["deviceId"] = WiFi.macAddress();
  doc["temperatureC"] = tempC;
  doc["humidityPct"] = humidity;
  doc["soilMoisturePct"] = soilPct;
  doc["uptimeSeconds"] = totalUptimeSec;
  doc["bootCount"] = rtcData.bootCount;

  String payload;
  serializeJson(doc, payload);

  int statusCode = http.POST(payload);
  Serial.printf("POST status: %d\n", statusCode);
  if (statusCode > 0) {
    Serial.println(http.getString());
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  loadRtcState();

  pinMode(SOIL_PWR_PIN, OUTPUT);
  digitalWrite(SOIL_PWR_PIN, LOW);

  dht.begin();
  delay(2000);

  float humidity = dht.readHumidity();
  float tempC = dht.readTemperature();
  int soilPct = readSoilPercent();

  if (isnan(humidity) || isnan(tempC)) {
    Serial.println("Failed to read DHT22");
  } else if (connectWiFi()) {
    postReading(tempC, humidity, soilPct);
  } else {
    Serial.println("Wi-Fi connection timeout");
  }

  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);

  saveRtcStateBeforeSleep();
  Serial.println("Entering deep sleep...");
  ESP.deepSleep(SLEEP_SECONDS * 1000000ULL);
}

void loop() {
  // Unused with deep sleep
}
```

> **HTTPS note:** If targeting a Google Cloud Function (`https://...`) instead of a local LAN server, switch `WiFiClient` to `BearSSL::WiFiClientSecure` and set trust anchors (or `client.setInsecure()` while prototyping).

---

## Build & Deploy (macOS)

1. Verify the CH340 USB-serial device appears when plugged in:
   ```sh
   ls /dev/cu.*   # expect /dev/cu.usbserial-* or /dev/cu.wchusbserial*
   ```
2. Flash and open serial monitor with PlatformIO:
   ```sh
   pio run --target upload
   pio device monitor -b 115200
   ```
