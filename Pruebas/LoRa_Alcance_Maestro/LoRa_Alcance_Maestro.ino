// LoRa - PRUEBA DE ALCANCE (ESP32 + SX1276, clon Heltec WiFi LoRa 32 V2)
//
// Dos placas: MAESTRO y REMOTO (mismo codigo, solo cambia ROL_MAESTRO).
//   MAESTRO: manda un "ping" cada cierto tiempo y espera el "pong".
//   REMOTO : recibe el ping, responde con el pong y cuenta los que se perdieron.
//
// Con esto se mide cada sentido por separado:
//   UP = el REMOTO oyo al MAESTRO (el ping)   DN = el MAESTRO oyo al REMOTO (el pong)
// Los resultados salen en la OLED de AMBAS placas (no hace falta laptop) y por Serial.
//
// Para ganar alcance a costa de velocidad se usa: potencia 20 dBm, BW 125 kHz,
// codificacion 4/8, preambulo largo y un Spreading Factor alto (SF10 por defecto).
// El boton PRG (GPIO0) cambia de perfil SF7 -> SF9 -> SF10 -> SF12. Hay que pulsarlo
// en AMBAS placas (con las dos cerca) para que usen el mismo perfil.
//
// Los tiempos (periodo del ping, espera del pong) se calculan solos segun el SF.
//
// Libreria: LoRa (Sandeep Mistry) y U8g2.

#include <SPI.h>
#include <LoRa.h>
#include <U8g2lib.h>

#define ROL_MAESTRO true      // true = MAESTRO, false = REMOTO

#define FRECUENCIA     915E6
#define POTENCIA_DBM   20     // maximo del SX1276 en PA_BOOST (17 es el valor por defecto)
#define ANCHO_BANDA    125E3
#define CODIF_CR       8      // 4/8 (mas robusto que 4/5)
#define PREAMBULO      12

const uint8_t PERFILES_SF[] = {7, 9, 10, 12};
const int N_PERFILES = sizeof(PERFILES_SF);
int perfil = 2;               // SF10 al arrancar

// Pines SX1276
#define LORA_SCK   5
#define LORA_MISO  19
#define LORA_MOSI  27
#define LORA_SS    18
#define LORA_RST   14
#define LORA_DIO0  26

// OLED SSD1306 (I2C)
#define OLED_SDA   4
#define OLED_SCL   15
#define OLED_RST   16

#define PIN_BOTON  0          // PRG

U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, OLED_RST, OLED_SCL, OLED_SDA);

#if ROL_MAESTRO
const char* ROL = "MAESTRO";
#else
const char* ROL = "REMOTO";
#endif

volatile bool rxPendiente = false;
void alRecibir(int size) { rxPendiente = true; }

unsigned long periodoMs = 2000;     // cada cuanto manda el MAESTRO
unsigned long timeoutMs = 2000;     // cuanto espera el MAESTRO el pong
unsigned long ultimoOled = 0, ultimoBoton = 0;

// ------------------------------------------------------------------
// Tiempo en el aire de un paquete (formula del datasheet del SX1276)
// ------------------------------------------------------------------
float tiempoAireMs(int bytes, int sf) {
  float ts = pow(2, sf) / ANCHO_BANDA * 1000.0;
  bool ldro = (sf >= 11 && ANCHO_BANDA <= 125E3);
  float num = 8.0 * bytes - 4.0 * sf + 28 + 16;          // CRC activado, cabecera explicita
  float den = 4.0 * (sf - (ldro ? 2 : 0));
  float simbolos = 8 + fmaxf(ceilf(num / den) * CODIF_CR, 0.0f);
  return (PREAMBULO + 4.25) * ts + simbolos * ts;
}

// ------------------------------------------------------------------
// Pantalla
// ------------------------------------------------------------------
void pantalla(const char* l1, const char* l2 = "", const char* l3 = "", const char* l4 = "") {
  char der[16];
  snprintf(der, sizeof(der), "SF%d %ddBm", PERFILES_SF[perfil], POTENCIA_DBM);

  oled.clearBuffer();
  oled.setDrawColor(1);
  oled.drawBox(0, 0, 128, 15);
  oled.setDrawColor(0);
  oled.setFont(u8g2_font_7x13B_tr);
  oled.drawStr(3, 12, ROL);
  oled.setFont(u8g2_font_6x10_tf);
  oled.drawStr(128 - 6 * strlen(der) - 2, 11, der);
  oled.setDrawColor(1);
  oled.drawStr(0, 27, l1);
  oled.drawStr(0, 38, l2);
  oled.drawStr(0, 49, l3);
  oled.drawStr(0, 60, l4);
  oled.sendBuffer();
}

// ------------------------------------------------------------------
// Estado de la prueba
// ------------------------------------------------------------------
#if ROL_MAESTRO
unsigned long seq = 0, enviados = 0, okPong = 0;
unsigned long tPing = 0, tUltimoPing = 0;
bool esperando = false;
int estado = 0;                     // 0 nada, 1 esperando, 2 OK, 3 sin respuesta
int upRssi = 0, dnRssi = 0;
float upSnr = 0, dnSnr = 0;
bool hayDatos = false;
#else
unsigned long ultimoSeq = 0, recibidos = 0, perdidos = 0;
unsigned long okA = 0, enviadosA = 0;     // lo que el MAESTRO dice haber recibido de mis pongs
unsigned long ultimoRx = 0;
int rssi = 0;
float snr = 0;
bool hayDatos = false;
#endif

void reiniciarEstadisticas() {
#if ROL_MAESTRO
  seq = enviados = okPong = 0;
  esperando = false;
  estado = 0;
  hayDatos = false;
  tUltimoPing = millis();
#else
  ultimoSeq = recibidos = perdidos = okA = enviadosA = 0;
  hayDatos = false;
  ultimoRx = millis();
#endif
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

  // Paquetes de ~24 bytes. Periodo = ida + vuelta + margen.
  float aire = tiempoAireMs(24, sf);
  periodoMs = max(1500.0f, 2 * aire + 700);
  timeoutMs = aire + 150 + 600;       // 150 ms = pausa del REMOTO antes de responder

  reiniciarEstadisticas();
  Serial.printf("# Perfil SF%d | %d dBm | BW %.0f kHz | CR 4/%d | aire(24B)=%.0f ms | periodo=%lu ms\n",
                sf, POTENCIA_DBM, ANCHO_BANDA / 1000, CODIF_CR, aire, periodoMs);
}

// ------------------------------------------------------------------
// MAESTRO
// ------------------------------------------------------------------
#if ROL_MAESTRO
void actualizarOled() {
  char b1[32], b2[32], b3[32], b4[32];
  const char* txt = estado == 1 ? "..." : estado == 2 ? "OK" : estado == 3 ? "SIN RESP" : "";
  snprintf(b1, sizeof(b1), "Ping #%lu %s", seq, txt);
  if (hayDatos) {
    snprintf(b2, sizeof(b2), "UP:%d DN:%d dBm", upRssi, dnRssi);
    snprintf(b3, sizeof(b3), "SNR UP:%.1f DN:%.1f", upSnr, dnSnr);
  } else {
    snprintf(b2, sizeof(b2), "UP:-- DN:-- dBm");
    snprintf(b3, sizeof(b3), "Sin respuesta aun");
  }
  unsigned long pct = enviados ? (okPong * 100 / enviados) : 0;
  snprintf(b4, sizeof(b4), "OK %lu/%lu (%lu%%)", okPong, enviados, pct);
  pantalla(b1, b2, b3, b4);
}

void enviarPing() {
  char buf[32];
  seq++;
  snprintf(buf, sizeof(buf), "P,%lu,%lu,%lu", seq, okPong, enviados);   // incluye mis estadisticas
  LoRa.beginPacket();
  LoRa.print(buf);
  LoRa.endPacket();                  // bloqueante: es corto
  LoRa.receive();
  enviados++;
  esperando = true;
  estado = 1;
  tPing = tUltimoPing = millis();
  actualizarOled();
}

void procesarRx() {
  String s = "";
  while (LoRa.available()) s += (char)LoRa.read();
  int r = LoRa.packetRssi();
  float n = LoRa.packetSnr();

  unsigned long sq; int upR, upN;
  if (sscanf(s.c_str(), "R,%lu,%d,%d", &sq, &upR, &upN) == 3 && esperando && sq == seq) {
    esperando = false;
    estado = 2;
    okPong++;
    hayDatos = true;
    upRssi = upR;  upSnr = upN / 10.0;
    dnRssi = r;    dnSnr = n;
    Serial.printf("%lu,OK,%d,%.1f,%d,%.1f\n", seq, upRssi, upSnr, dnRssi, dnSnr);
    actualizarOled();
  }
}

void bucle() {
  unsigned long ahora = millis();
  if (!esperando && ahora - tUltimoPing >= periodoMs) enviarPing();
  if (rxPendiente) { rxPendiente = false; procesarRx(); }
  if (esperando && ahora - tPing > timeoutMs) {
    esperando = false;
    estado = 3;
    Serial.printf("%lu,PERDIDO\n", seq);
    actualizarOled();
  }
}

// ------------------------------------------------------------------
// REMOTO
// ------------------------------------------------------------------
#else
void actualizarOled() {
  char b1[32], b2[32], b3[32], b4[32];
  unsigned long edad = (millis() - ultimoRx) / 1000;
  bool sinSenal = (millis() - ultimoRx) > (3 * periodoMs + 2000);

  if (!hayDatos) {
    pantalla("Esperando ping...", "", "", sinSenal ? "Revisa el perfil SF" : "");
    return;
  }
  snprintf(b1, sizeof(b1), "Rx #%lu RSSI:%d", ultimoSeq, rssi);
  snprintf(b2, sizeof(b2), "SNR:%.1f Perd:%lu", snr, perdidos);
  snprintf(b3, sizeof(b3), "Maestro oye:%lu/%lu", okA, enviadosA);
  unsigned long total = recibidos + perdidos;
  unsigned long pct = total ? (recibidos * 100 / total) : 0;
  if (sinSenal) snprintf(b4, sizeof(b4), "SIN SENAL %lus", edad);
  else          snprintf(b4, sizeof(b4), "Hace %lus  %lu%% ok", edad, pct);
  pantalla(b1, b2, b3, b4);
}

void procesarRx() {
  String s = "";
  while (LoRa.available()) s += (char)LoRa.read();
  int r = LoRa.packetRssi();
  float n = LoRa.packetSnr();

  unsigned long sq, ok, env;
  if (sscanf(s.c_str(), "P,%lu,%lu,%lu", &sq, &ok, &env) != 3) return;

  if (!hayDatos || sq <= ultimoSeq) {        // primer ping, o el maestro reinicio la cuenta
    recibidos = perdidos = 0;
  } else {
    perdidos += sq - ultimoSeq - 1;          // huecos en la secuencia = pings perdidos
  }
  recibidos++;
  ultimoSeq = sq;
  rssi = r;  snr = n;
  okA = ok;  enviadosA = env;
  ultimoRx = millis();
  hayDatos = true;

  // Responder con el pong, que lleva como oi el ping
  delay(150);
  char buf[32];
  snprintf(buf, sizeof(buf), "R,%lu,%d,%d", sq, r, (int)lroundf(n * 10));
  LoRa.beginPacket();
  LoRa.print(buf);
  LoRa.endPacket();
  LoRa.receive();

  Serial.printf("%lu,RX,%d,%.1f,perdidos=%lu\n", sq, r, n, perdidos);
  actualizarOled();
}

void bucle() {
  if (rxPendiente) { rxPendiente = false; procesarRx(); }
}
#endif

// ------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("# == LoRa ALCANCE: %s ==\n", ROL);
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
  pantalla("LoRa OK", "PRG = cambiar SF");
  delay(1500);
  actualizarOled();
}

void loop() {
  // Boton PRG: siguiente perfil (pulsar en AMBAS placas)
  if (digitalRead(PIN_BOTON) == LOW && millis() - ultimoBoton > 400) {
    ultimoBoton = millis();
    perfil = (perfil + 1) % N_PERFILES;
    aplicarPerfil();
    actualizarOled();
  }

  bucle();

  if (millis() - ultimoOled >= 500) {
    ultimoOled = millis();
    actualizarOled();
  }
}
