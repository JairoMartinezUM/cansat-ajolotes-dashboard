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
// Radio configurado para MAXIMO ALCANCE (a costa de velocidad): 20 dBm, BW 125 kHz,
// codificacion 4/8, preambulo 12 y SF alto (SF10 por defecto). Debe coincidir con el
// transmisor. El boton PRG (GPIO0) cambia el SF: 7 -> 8 -> 9 -> 10; pulsarlo en AMBAS
// placas (con las dos cerca). Cuenta los paquetes perdidos por huecos en "n".
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

// ---- Radio: maximo alcance (igual que el transmisor) ----
#define POTENCIA_DBM   20
#define ANCHO_BANDA    125E3
#define CODIF_CR       8
#define PREAMBULO      12
#define PIN_BOTON      0           // PRG
#define JSON_BYTES_MAX 125
#define ACK_BYTES      10
#define PAUSA_ACK_MS   30          // pausa antes de responder el ACK

const uint8_t PERFILES_SF[] = {7, 8, 9, 10};
const int N_PERFILES = sizeof(PERFILES_SF);
int perfil = 3;                    // SF10 al arrancar

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

unsigned long recibidos = 0, errores = 0, perdidos = 0, ultimoN = 0;
unsigned long ultimoRx = 0, ultimoOled = 0, ultimoBoton = 0;
unsigned long sinSenalMs = 5000;   // sin paquetes durante este tiempo -> "SIN SENAL"
bool hayDatos = false;

// Ultimo paquete valido (para la OLED)
float vAlt = 0, vVel = 0, vTemp = 0, vPres = 0, vSnr = 0;
int vRssi = 0;
unsigned long vN = 0;

void pantalla(const char* l1, const char* l2 = "", const char* l3 = "", const char* l4 = "") {
  char der[16];
  snprintf(der, sizeof(der), "SF%d %ddBm", PERFILES_SF[perfil], POTENCIA_DBM);

  oled.clearBuffer();
  oled.setDrawColor(1);
  oled.drawBox(0, 0, 128, 15);
  oled.setDrawColor(0);
  oled.setFont(u8g2_font_7x13B_tr);
  oled.drawStr(3, 12, "RECEPTOR");
  oled.setFont(u8g2_font_6x10_tf);
  oled.drawStr(128 - 6 * strlen(der) - 2, 11, der);
  oled.setDrawColor(1);
  oled.drawStr(0, 27, l1);
  oled.drawStr(0, 38, l2);
  oled.drawStr(0, 49, l3);
  oled.drawStr(0, 60, l4);
  oled.sendBuffer();
}

// Tiempo en el aire de un paquete (formula del datasheet del SX1276)
float tiempoAireMs(int bytes, int sf) {
  float ts = pow(2, sf) / ANCHO_BANDA * 1000.0;
  bool ldro = (sf >= 11 && ANCHO_BANDA <= 125E3);
  float num = 8.0 * bytes - 4.0 * sf + 28 + 16;
  float den = 4.0 * (sf - (ldro ? 2 : 0));
  float simbolos = 8 + fmaxf(ceilf(num / den) * CODIF_CR, 0.0f);
  return (PREAMBULO + 4.25) * ts + simbolos * ts;
}

void aplicarPerfil() {
  int sf = PERFILES_SF[perfil];
  LoRa.idle();
  LoRa.setSpreadingFactor(sf);
  LoRa.setSignalBandwidth(ANCHO_BANDA);
  LoRa.setCodingRate4(CODIF_CR);
  LoRa.setPreambleLength(PREAMBULO);
  LoRa.setSyncWord(0x12);
  LoRa.setTxPower(POTENCIA_DBM, PA_OUTPUT_PA_BOOST_PIN);
  LoRa.enableCrc();
  LoRa.receive();

  // El transmisor manda cada ~ (aire JSON + ACK + margen). Se da por perdida la senal
  // si pasan ~2.5 periodos sin paquetes.
  float aireJson = tiempoAireMs(JSON_BYTES_MAX, sf);
  float aireAck = tiempoAireMs(ACK_BYTES, sf);
  float periodo = max(1000.0f, aireJson + PAUSA_ACK_MS + aireAck + 400);
  sinSenalMs = 2.5 * periodo + 1000;

  recibidos = errores = perdidos = ultimoN = 0;
  hayDatos = false;
  ultimoRx = millis();
  Serial.printf("# Perfil SF%d | %d dBm | CR 4/%d | periodo esperado=%.0f ms\n",
                sf, POTENCIA_DBM, CODIF_CR, periodo);
}

void actualizarOled() {
  if (!hayDatos) {
    bool largo = (millis() - ultimoRx) > sinSenalMs;
    pantalla("Esperando datos...", "", "", largo ? "Revisa el perfil SF" : "");
    return;
  }
  char b1[32], b2[32], b3[32], b4[32];
  unsigned long edad = (millis() - ultimoRx) / 1000;
  if (millis() - ultimoRx > sinSenalMs) snprintf(b1, sizeof(b1), "SIN SENAL hace %lus", edad);
  else                                  snprintf(b1, sizeof(b1), "Alt:%.1fm V:%.1f", vAlt, vVel);
  snprintf(b2, sizeof(b2), "T:%.1fC P:%.2fkPa", vTemp, vPres);
  snprintf(b3, sizeof(b3), "SNR:%.1f Perd:%lu", vSnr, perdidos);
  snprintf(b4, sizeof(b4), "%ddBm #%lu", vRssi, vN);
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

  unsigned long n = doc["n"];
  if (!hayDatos || n <= ultimoN) perdidos = 0;      // primer paquete, o el transmisor se reinicio
  else perdidos += n - ultimoN - 1;                 // huecos en la numeracion = paquetes perdidos
  ultimoN = n;
  recibidos++;

  // ACK al transmisor (pausa corta para que ya este escuchando)
  delay(PAUSA_ACK_MS);
  char ack[16];
  snprintf(ack, sizeof(ack), "ACK:%lu", n);
  LoRa.beginPacket();
  LoRa.print(ack);
  LoRa.endPacket();
  LoRa.receive();

  // Datos para la OLED
  vN = n;
  vAlt = doc["alt"];   vVel = doc["v"];   vTemp = doc["T"];   vPres = doc["p"];
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
  pinMode(PIN_BOTON, INPUT_PULLUP);

  oled.begin();
  pantalla("Iniciando LoRa...");

  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_SS);
  LoRa.setPins(LORA_SS, LORA_RST, LORA_DIO0);
  if (!LoRa.begin(FRECUENCIA)) {
    Serial.println("# ERROR: no se pudo iniciar LoRa");
    pantalla("ERROR LoRa", "Revisa pines", "y antena");
    while (true) delay(1000);
  }
  LoRa.onReceive(alRecibir);
  aplicarPerfil();

  Serial.println("# LoRa OK, esperando paquetes");
  pantalla("LoRa OK", "Esperando datos...");
}

void loop() {
  // Boton PRG: siguiente perfil (pulsar tambien en el transmisor)
  if (digitalRead(PIN_BOTON) == LOW && millis() - ultimoBoton > 400) {
    ultimoBoton = millis();
    perfil = (perfil + 1) % N_PERFILES;
    aplicarPerfil();
    actualizarOled();
  }

  if (rxPendiente) {
    rxPendiente = false;
    procesarPaquete();
  }
  if (millis() - ultimoOled >= 500) {
    ultimoOled = millis();
    actualizarOled();
  }
}
