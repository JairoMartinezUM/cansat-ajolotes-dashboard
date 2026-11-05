// Prueba de enlace LoRa con OLED y ECO - ESP32 + SX1276 (clon Heltec WiFi LoRa 32 V2 / TTGO LoRa32 V1)
// Librerias requeridas (Administrador de bibliotecas):
//   - "LoRa" de Sandeep Mistry
//   - "U8g2" de oliver
//
// Cargar con MODO_EMISOR = true en una placa y false en la otra.
// La pantalla OLED indica el rol (EMISOR / RECEPTOR) en el encabezado.
//
// ECO: el receptor responde cada paquete con "ECO:<mensaje>".
//      El emisor espera ese eco y muestra si llego (y cuanto tardo).

#include <SPI.h>
#include <LoRa.h>
#include <U8g2lib.h>

#define MODO_EMISOR true     // true = emisor, false = receptor
#define FRECUENCIA  915E6    // 863~928 MHz -> 915 MHz (México/América)
#define TIMEOUT_ECO 1500     // ms que espera el emisor por el eco

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

#if MODO_EMISOR
const char* ROL = "EMISOR";
#else
const char* ROL = "RECEPTOR";
#endif

int contador = 0;       // paquetes enviados (emisor) o recibidos (receptor)
int ecosOk = 0;         // solo emisor: ecos recibidos correctamente

// Dibuja la pantalla: encabezado con el rol + hasta 4 lineas de texto
void pantalla(const char* l1, const char* l2 = "", const char* l3 = "", const char* l4 = "") {
  oled.clearBuffer();

  // Encabezado invertido con el rol y la frecuencia
  oled.setDrawColor(1);
  oled.drawBox(0, 0, 128, 15);
  oled.setDrawColor(0);
  oled.setFont(u8g2_font_7x13B_tr);
  oled.drawStr(3, 12, ROL);
  oled.setFont(u8g2_font_6x10_tf);
  oled.drawStr(128 - 6 * 6 - 2, 11, "915MHz");

  // Cuerpo
  oled.setDrawColor(1);
  oled.drawStr(0, 27, l1);
  oled.drawStr(0, 38, l2);
  oled.drawStr(0, 49, l3);
  oled.drawStr(0, 60, l4);

  oled.sendBuffer();
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println(MODO_EMISOR ? "== EMISOR LoRa ==" : "== RECEPTOR LoRa ==");

  oled.begin();
  pantalla("Iniciando LoRa...");

  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_SS);
  LoRa.setPins(LORA_SS, LORA_RST, LORA_DIO0);

  if (!LoRa.begin(FRECUENCIA)) {
    Serial.println("ERROR: no se pudo iniciar LoRa. Revisa pines/antena.");
    pantalla("ERROR LoRa", "Revisa pines", "y antena");
    while (true) delay(1000);
  }

  // Parametros que deben ser IGUALES en ambas placas
  LoRa.setSpreadingFactor(7);
  LoRa.setSignalBandwidth(125E3);
  LoRa.setSyncWord(0x12);

  Serial.println("LoRa OK");
#if MODO_EMISOR
  pantalla("LoRa OK", "Listo para enviar");
#else
  pantalla("LoRa OK", "Esperando paquetes...");
#endif
}

void loop() {
  char b1[32], b2[32], b3[32], b4[32];

#if MODO_EMISOR
  // ---- Enviar ----
  String texto = "Hola CanSat #" + String(contador);
  Serial.print("Enviando: ");
  Serial.println(texto);

  snprintf(b1, sizeof(b1), "Enviando #%d", contador);
  pantalla(b1);

  LoRa.beginPacket();
  LoRa.print(texto);
  LoRa.endPacket();
  unsigned long t0 = millis();

  // ---- Esperar eco ----
  bool eco = false;
  int rssi = 0;
  float snr = 0;
  unsigned long rtt = 0;
  String esperado = "ECO:" + texto;

  while (millis() - t0 < TIMEOUT_ECO) {
    if (LoRa.parsePacket()) {
      String r = "";
      while (LoRa.available()) r += (char)LoRa.read();
      if (r == esperado) {
        rtt = millis() - t0;
        rssi = LoRa.packetRssi();
        snr = LoRa.packetSnr();
        eco = true;
        break;
      }
    }
  }

  contador++;
  snprintf(b1, sizeof(b1), "Paquete #%d", contador - 1);
  if (eco) {
    ecosOk++;
    snprintf(b2, sizeof(b2), "ECO OK  RTT:%lums", rtt);
    snprintf(b3, sizeof(b3), "RSSI:%d SNR:%.1f", rssi, snr);
    Serial.print("Eco OK  RTT: ");
    Serial.print(rtt);
    Serial.print(" ms  RSSI: ");
    Serial.print(rssi);
    Serial.print(" dBm  SNR: ");
    Serial.println(snr);
  } else {
    snprintf(b2, sizeof(b2), "SIN ECO!");
    snprintf(b3, sizeof(b3), "Timeout %d ms", TIMEOUT_ECO);
    Serial.println("SIN ECO (timeout)");
  }
  snprintf(b4, sizeof(b4), "Ecos: %d/%d", ecosOk, contador);
  pantalla(b1, b2, b3, b4);

  delay(1000);
#else
  int tam = LoRa.parsePacket();
  if (tam) {
    String msg = "";
    while (LoRa.available()) msg += (char)LoRa.read();
    int rssi = LoRa.packetRssi();
    float snr = LoRa.packetSnr();
    contador++;

    Serial.print("Recibido: '");
    Serial.print(msg);
    Serial.print("'  RSSI: ");
    Serial.print(rssi);
    Serial.print(" dBm  SNR: ");
    Serial.println(snr);

    // Responder con el eco (pequena pausa para que el emisor pase a escuchar)
    delay(100);
    LoRa.beginPacket();
    LoRa.print("ECO:");
    LoRa.print(msg);
    LoRa.endPacket();
    Serial.println("Eco enviado");

    snprintf(b1, sizeof(b1), "%.20s", msg.c_str());
    snprintf(b2, sizeof(b2), "RSSI: %d dBm", rssi);
    snprintf(b3, sizeof(b3), "SNR : %.1f dB", snr);
    snprintf(b4, sizeof(b4), "Recibidos:%d eco>OK", contador);
    pantalla(b1, b2, b3, b4);
  }
#endif
}
