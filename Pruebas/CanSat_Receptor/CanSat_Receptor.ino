// CanSat - RECEPTOR (estacion terrena)
// ESP32 + SX1276 (clon Heltec WiFi LoRa 32 V2)
//
// Recibe los paquetes JSON del transmisor, los valida, responde "ACK:<n>",
// los muestra en la OLED y los reenvia por USB (Serial) a la laptop, una linea
// JSON por paquete, con "rssi" y "snr" agregados. El dashboard de Python
// (simulator/dashboard.py --serial COMx) lee esas lineas.
//
// Las lineas que NO empiezan con '{' son mensajes de diagnostico (empiezan con '#')
// y el dashboard las ignora.
//
// Librerias (Administrador de bibliotecas):
//   - LoRa         (Sandeep Mistry)
//   - U8g2         (oliver)
//   - ArduinoJson  (Benoit Blanchon, version 7)

#include <SPI.h>
#include <LoRa.h>
#include <U8g2lib.h>
#include <ArduinoJson.h>

#define FRECUENCIA   915E6
#define SIN_SENAL_MS 3000     // sin paquetes durante este tiempo -> "SIN SENAL"

// Pines SX1276
#define LORA_SCK   5
#define LORA_MISO  19
#define LORA_MOSI  27
#define LORA_SS    18
#define LORA_RST   14
#define LORA_DIO0  26

// Pines OLED SSD1306 (I2C)
#define OLED_SDA   4
#define OLED_SCL   15
#define OLED_RST   16

U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, OLED_RST, OLED_SCL, OLED_SDA);

volatile bool rxPendiente = false;
void alRecibir(int size) { rxPendiente = true; }

unsigned long recibidos = 0, errores = 0;
unsigned long ultimoRx = 0, ultimoOled = 0;
bool hayDatos = false;

// Ultimo paquete valido (para la OLED)
float vAlt = 0, vVel = 0, vTemp = 0, vPres = 0, vRoll = 0, vPitch = 0, vYaw = 0, vSnr = 0;
int vRssi = 0;
unsigned long vN = 0;

void pantalla(const char* l1, const char* l2 = "", const char* l3 = "", const char* l4 = "") {
  oled.clearBuffer();
  oled.setDrawColor(1);
  oled.drawBox(0, 0, 128, 15);
  oled.setDrawColor(0);
  oled.setFont(u8g2_font_7x13B_tr);
  oled.drawStr(3, 12, "RECEPTOR");
  oled.setFont(u8g2_font_6x10_tf);
  oled.drawStr(128 - 6 * 6 - 2, 11, "915MHz");
  oled.setDrawColor(1);
  oled.drawStr(0, 27, l1);
  oled.drawStr(0, 38, l2);
  oled.drawStr(0, 49, l3);
  oled.drawStr(0, 60, l4);
  oled.sendBuffer();
}

void actualizarOled() {
  if (!hayDatos) {
    pantalla("Esperando datos...", "", "", "");
    return;
  }
  char b1[32], b2[32], b3[32], b4[32];
  unsigned long edad = (millis() - ultimoRx) / 1000;
  if (millis() - ultimoRx > SIN_SENAL_MS) snprintf(b1, sizeof(b1), "SIN SENAL hace %lus", edad);
  else                                    snprintf(b1, sizeof(b1), "Alt:%.1fm V:%.1f", vAlt, vVel);
  snprintf(b2, sizeof(b2), "T:%.1fC P:%.2fkPa", vTemp, vPres);
  snprintf(b3, sizeof(b3), "R%.0f P%.0f Y%.0f", vRoll, vPitch, vYaw);
  snprintf(b4, sizeof(b4), "%ddBm SNR%.1f #%lu", vRssi, vSnr, vN);
  pantalla(b1, b2, b3, b4);
}

void procesarPaquete() {
  String msg = "";
  while (LoRa.available()) msg += (char)LoRa.read();
  int rssi = LoRa.packetRssi();
  float snr = LoRa.packetSnr();

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, msg);
  if (err || !doc["n"].is<unsigned long>() || !doc["alt"].is<float>()) {
    errores++;
    Serial.print("# paquete invalido (");
    Serial.print(err ? err.c_str() : "faltan campos");
    Serial.print("): ");
    Serial.println(msg);
    return;
  }

  recibidos++;
  unsigned long n = doc["n"];

  // ACK al transmisor (pausa corta para que ya este escuchando)
  delay(30);
  LoRa.beginPacket();
  LoRa.print("ACK:");
  LoRa.print(n);
  LoRa.endPacket();
  LoRa.receive();

  // Datos para la OLED
  vN = n;
  vAlt = doc["alt"];   vVel = doc["v"];    vTemp = doc["T"];  vPres = doc["p"];
  vRoll = doc["r"];    vPitch = doc["pi"]; vYaw = doc["y"];
  vRssi = rssi;        vSnr = snr;
  ultimoRx = millis();
  hayDatos = true;

  // Reenvio a la laptop: el mismo JSON + calidad del enlace
  doc["rssi"] = rssi;
  doc["snr"] = snr;
  serializeJson(doc, Serial);
  Serial.println();

  actualizarOled();
  ultimoOled = millis();
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("# == CanSat RECEPTOR ==");

  oled.begin();
  pantalla("Iniciando LoRa...");

  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_SS);
  LoRa.setPins(LORA_SS, LORA_RST, LORA_DIO0);
  if (!LoRa.begin(FRECUENCIA)) {
    Serial.println("# ERROR: no se pudo iniciar LoRa");
    pantalla("ERROR LoRa", "Revisa pines", "y antena");
    while (true) delay(1000);
  }
  // Deben ser IGUALES que en el transmisor
  LoRa.setSpreadingFactor(7);
  LoRa.setSignalBandwidth(125E3);
  LoRa.setSyncWord(0x12);
  LoRa.enableCrc();
  LoRa.onReceive(alRecibir);
  LoRa.receive();

  Serial.println("# LoRa OK, esperando paquetes");
  pantalla("LoRa OK", "Esperando datos...");
}

void loop() {
  if (rxPendiente) {
    rxPendiente = false;
    procesarPaquete();
  }
  if (millis() - ultimoOled >= 500) {
    ultimoOled = millis();
    actualizarOled();
  }
}
