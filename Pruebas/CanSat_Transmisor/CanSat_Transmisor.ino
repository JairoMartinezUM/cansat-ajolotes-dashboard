// CanSat - TRANSMISOR
// ESP32 + SX1276 (clon Heltec WiFi LoRa 32 V2) + MPU6050 + BMP280
//
// Lee los sensores y transmite un paquete JSON por LoRa.
// El receptor responde con "ACK:<n>" para saber si el paquete llego.
//
// Radio configurado para MAXIMO ALCANCE (a costa de velocidad): 20 dBm, BW 125 kHz,
// codificacion 4/8, preambulo 12 y SF alto (SF10 por defecto). El periodo de envio y
// la espera del ACK se calculan solos segun el SF (un paquete en SF10 dura ~1.7 s).
// El boton PRG (GPIO0) cambia el SF: 7 -> 8 -> 9 -> 10. Pulsarlo en AMBAS placas
// (con las dos cerca) para que usen el mismo perfil. Debe coincidir con el receptor.
//
// Librerias (Administrador de bibliotecas):
//   - LoRa                (Sandeep Mistry)
//   - U8g2                (oliver)
//   - Adafruit BMP280 Library  (instala tambien Adafruit BusIO y Adafruit Unified Sensor)
//   (el MPU6050 se lee directo por registros I2C: no necesita libreria y funciona
//    tambien con modulos clon que no pasan la verificacion de identidad de Adafruit)
//
// BAROMETRO: el TX de 20 dBm desplaza ~11 Pa (~1 m) la lectura del BMP280 mientras el
// amplificador esta encendido (medido con Diag_Baro_TX). Por eso: (1) el BMP280 va SIN
// filtro IIR, asi el efecto es un escalon limpio; (2) solo se aceptan lecturas fuera de la
// transmision (y GUARDA_TX_MS despues); (3) la velocidad se calcula por regresion con las
// marcas de tiempo reales de esas lecturas; (4) en tierra el cero de altitud se reajusta
// solo (con la placa quieta y a menos de ZERO_BANDA_M del cero) para absorber la deriva
// termica; deja de ajustarse en cuanto despega. Un capacitor de 100 uF + 0.1 uF en el VCC
// del BMP280 ayuda tambien.
//
// Conexion de sensores (bus I2C compartido con la OLED, pines 4 y 15):
//   MPU6050 y BMP280:  VCC -> 3V3 | GND -> GND | SDA -> GPIO4 | SCL -> GPIO15
//   (MPU6050 AD0 a GND -> 0x68. BMP280 SDO a GND -> 0x76 o a 3V3 -> 0x77)
//
// Paquete JSON (claves cortas para que quepa en un paquete LoRa; sin "id" para ahorrar
// tiempo en el aire: el dashboard usa el TEAM_ID de telemetry_format.py):
//   n # paquete | t ms desde el arranque | alt m (relativa al arranque)
//   p presion kPa | T temperatura C | ax ay az m/s^2 | r pi y roll/pitch/yaw grados
//   v velocidad vertical m/s (positiva = descendiendo)

#include <SPI.h>
#include <Wire.h>
#include <LoRa.h>
#include <U8g2lib.h>
#include <Adafruit_BMP280.h>

#define FRECUENCIA     915E6

// ---- Radio: maximo alcance ----
#define POTENCIA_DBM   20          // maximo del SX1276 en PA_BOOST (17 es el valor por defecto)
#define ANCHO_BANDA    125E3
#define CODIF_CR       8           // 4/8 (mas robusto que 4/5)
#define PREAMBULO      12
#define PIN_BOTON      0           // PRG
#define JSON_BYTES_MAX 125         // tamano maximo esperado del JSON (para calcular tiempos)
#define ACK_BYTES      10          // "ACK:12345"
#define PAUSA_ACK_MS   30          // pausa del receptor antes de responder el ACK

const uint8_t PERFILES_SF[] = {7, 8, 9, 10};
const int N_PERFILES = sizeof(PERFILES_SF);
int perfil = 3;                    // SF10 al arrancar

#define PERIODO_TX_MIN_MS   1000   // periodo minimo entre paquetes (el real depende del SF)
#define PERIODO_SENSORES_MS 20     // lectura del MPU6050 (50 Hz) para el filtro
#define PERIODO_BARO_MS     50     // lectura del BMP280 (20 Hz; las lecturas durante el TX se descartan)
#define PERIODO_OLED_MS     500

unsigned long periodoTxMs = PERIODO_TX_MIN_MS;
unsigned long timeoutAckMs = 800;

// Pines SX1276
#define LORA_SCK   5
#define LORA_MISO  19
#define LORA_MOSI  27
#define LORA_SS    18
#define LORA_RST   14
#define LORA_DIO0  26

// Bus I2C (OLED + sensores)
#define I2C_SDA    4
#define I2C_SCL    15
#define OLED_RST   16

U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, OLED_RST, I2C_SCL, I2C_SDA);
Adafruit_BMP280 bmp(&Wire);

// ---- MPU6050 por registros I2C ----
#define MPU_ADDR 0x68
#define MPU_REMAPEAR 1           // 1 = remapear ejes (modulo de canto), 0 = ejes tal cual del chip
#define MPU_ACCEL_LSB_G 4096.0f   // rango +-8 g
#define MPU_GYRO_LSB_DPS 65.5f    // rango +-500 grados/s

struct MpuCrudo { float ax, ay, az, gx, gy, gz; };   // m/s^2 y grados/s

bool mpuEscribir(uint8_t reg, uint8_t valor) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(valor);
  return Wire.endTransmission() == 0;
}

bool mpuLeer(MpuCrudo& m) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);                                  // ACCEL_XOUT_H
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)14) != 14) return false;
  int16_t v[7];                                      // ax ay az temp gx gy gz
  for (int i = 0; i < 7; i++) {
    uint8_t hi = Wire.read();
    uint8_t lo = Wire.read();
    v[i] = (int16_t)((hi << 8) | lo);
  }
  m.ax = v[0] / MPU_ACCEL_LSB_G * 9.80665f;
  m.ay = v[1] / MPU_ACCEL_LSB_G * 9.80665f;
  m.az = v[2] / MPU_ACCEL_LSB_G * 9.80665f;
  m.gx = v[4] / MPU_GYRO_LSB_DPS;
  m.gy = v[5] / MPU_GYRO_LSB_DPS;
  m.gz = v[6] / MPU_GYRO_LSB_DPS;

#if MPU_REMAPEAR
  // Remapeo de ejes: el modulo esta montado de canto (la gravedad cae en su eje X).
  // Se reasignan los ejes para que el eje Z "del CanSat" apunte hacia arriba y en
  // reposo az = +9.8, que es lo que espera el dashboard.
  // (x', y', z') = (-z, y, x): giro de 90 grados, conserva el sentido de los ejes.
  float t;
  t = m.ax; m.ax = -m.az; m.az = t;
  t = m.gx; m.gx = -m.gz; m.gz = t;
#endif
  return true;
}

bool mpuIniciar() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x75);                                  // WHO_AM_I
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)1) != 1) return false;
  uint8_t quien = Wire.read();
  Serial.print("MPU WHO_AM_I: 0x");
  Serial.println(quien, HEX);                        // 0x68 original; los clones dan otros valores

  bool ok = mpuEscribir(0x6B, 0x00);                 // salir de sleep
  delay(100);
  ok &= mpuEscribir(0x6B, 0x01);                     // reloj: PLL del giroscopio X
  ok &= mpuEscribir(0x1A, 0x03);                     // filtro pasa-bajas ~44 Hz
  ok &= mpuEscribir(0x1B, 0x08);                     // giroscopio +-500 grados/s
  ok &= mpuEscribir(0x1C, 0x10);                     // acelerometro +-8 g
  delay(50);
  return ok;
}

// ---- Estado de los sensores ----
float presionBase = 101325.0;          // Pa, referencia de altitud 0 (se mide al arrancar)
float gyroBiasX = 0, gyroBiasY = 0, gyroBiasZ = 0;   // deg/s
float roll = 0, pitch = 0, yaw = 0;    // grados
float ax = 0, ay = 0, az = 0;          // m/s^2
float temperatura = 0, presionPa = 0;
float altitud = 0, velocidad = 0;

// Barometro (ver nota arriba)
#define GUARDA_TX_MS    100       // tras terminar un TX, descartar lecturas este tiempo
#define ALT_SUAVIZADO   0.3f      // por muestra valida (0..1, menor = mas suave)
#define PRES_SUAVIZADO  0.3f
#define VEL_SUAVIZADO   0.6f      // peso de la velocidad nueva en cada paquete
#define VEL_VENTANA_S   4.0f      // regresion de altitud sobre los ultimos 4 s de lecturas validas
#define N_HIST          64
#define ZERO_BANDA_M    1.5f      // cero autoajustable solo si |altitud| < esto...
#define ZERO_VEL_MAX    0.2f      // ...y |velocidad| < esto (m/s)
#define ZERO_ALFA       0.01f     // ~20 s de constante de tiempo
struct MuestraAlt { unsigned long t; float alt; };
MuestraAlt histAlt[N_HIST];
int histN = 0, histIdx = 0;
float altSuave = 0, pSuave = 0;
unsigned long tPrevFiltro = 0, tPrevBaro = 0;

// ---- Enlace LoRa ----
volatile bool txTerminado = false;
volatile bool rxPendiente = false;
bool txActivo = false;                 // true desde que empieza hasta que termina una transmision
unsigned long tFinTx = 0;              // millis() en que termino la ultima transmision
unsigned long contador = 0;
unsigned long ultimoTx = 0, ultimoOled = 0, ultimoSensor = 0;
bool esperandoAck = false;
bool ackOk = false;
unsigned long tEnvio = 0;
long ackEsperado = -1;
int ackRssi = 0;
unsigned long ackOkTotal = 0, enviados = 0;

void alTerminarTx()      { txTerminado = true; }
void alRecibir(int size) { rxPendiente = true; }

// ---- Pantalla ----
void pantalla(const char* l1, const char* l2 = "", const char* l3 = "", const char* l4 = "") {
  oled.clearBuffer();
  oled.setDrawColor(1);
  oled.drawBox(0, 0, 128, 15);
  oled.setDrawColor(0);
  oled.setFont(u8g2_font_7x13B_tr);
  oled.drawStr(3, 12, "TRANSMISOR");
  oled.setFont(u8g2_font_6x10_tf);
  char der[16];
  snprintf(der, sizeof(der), "SF%d %ddBm", PERFILES_SF[perfil], POTENCIA_DBM);
  oled.drawStr(128 - 6 * strlen(der) - 2, 11, der);
  oled.setDrawColor(1);
  oled.drawStr(0, 27, l1);
  oled.drawStr(0, 38, l2);
  oled.drawStr(0, 49, l3);
  oled.drawStr(0, 60, l4);
  oled.sendBuffer();
}

void detener(const char* l1, const char* l2 = "") {
  Serial.println(l1);
  pantalla(l1, l2);
  while (true) delay(1000);
}

void escanearI2C() {
  Serial.print("Dispositivos I2C:");
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.print(" 0x");
      Serial.print(a, HEX);
    }
  }
  Serial.println();
}

// ---- Sensores ----
float altitudDesdePresion(float pPa) {
  return 44330.0 * (1.0 - pow(pPa / presionBase, 0.1903));
}

void leerMpu(float dt) {
  MpuCrudo m;
  if (!mpuLeer(m)) return;               // lectura fallida: conservar el ultimo valor
  ax = m.ax;
  ay = m.ay;
  az = m.az;
  float gx = m.gx - gyroBiasX;
  float gy = m.gy - gyroBiasY;
  float gz = m.gz - gyroBiasZ;

  // Filtro complementario: gyro (rapido) + acelerometro (referencia de gravedad)
  float rollAcc  = atan2(ay, az) * RAD_TO_DEG;
  float pitchAcc = atan2(-ax, sqrt(ay * ay + az * az)) * RAD_TO_DEG;
  roll  = 0.98 * (roll  + gx * dt) + 0.02 * rollAcc;
  pitch = 0.98 * (pitch + gy * dt) + 0.02 * pitchAcc;
  yaw  += gz * dt;                         // sin magnetometro: deriva con el tiempo
  if (yaw > 360) yaw -= 360;
  if (yaw < 0)   yaw += 360;
}

void leerBaro() {
  // Lectura contaminada por el TX (el amplificador desplaza la presion): descartar
  if (txActivo || millis() - tFinTx < GUARDA_TX_MS) return;

  float p = bmp.readPressure();
  if (isnan(p) || p < 30000 || p > 110000) return;     // lectura invalida del sensor
  temperatura = bmp.readTemperature();
  presionPa = p;
  pSuave = (pSuave == 0) ? p : pSuave + PRES_SUAVIZADO * (p - pSuave);
  altitud = altitudDesdePresion(p);
  altSuave += ALT_SUAVIZADO * (altitud - altSuave);

  histAlt[histIdx] = { millis(), altitud };            // historial para la velocidad
  histIdx = (histIdx + 1) % N_HIST;
  if (histN < N_HIST) histN++;

  // Cero autoajustable: en tierra y quieto, la referencia sigue a la presion (absorbe la
  // deriva termica). Fuera de la banda o con velocidad, queda congelada (vuelo).
  if (fabsf(altSuave) < ZERO_BANDA_M && fabsf(velocidad) < ZERO_VEL_MAX)
    presionBase += ZERO_ALFA * (pSuave - presionBase);
}

// Velocidad vertical = pendiente de la altitud (regresion lineal) sobre las lecturas
// validas de los ultimos VEL_VENTANA_S segundos, con sus marcas de tiempo reales.
// Positiva = descendiendo. Se calcula al armar cada paquete.
float calcularVelocidad() {
  unsigned long ahora = millis();
  double n = 0, sx = 0, sy = 0, sxx = 0, sxy = 0, xmin = 1e9, xmax = -1e9;
  for (int i = 0; i < histN; i++) {
    double x = -(double)(ahora - histAlt[i].t) / 1000.0;           // segundos respecto a ahora
    if (x < -VEL_VENTANA_S) continue;
    double y = histAlt[i].alt;
    n++; sx += x; sy += y; sxx += x * x; sxy += x * y;
    if (x < xmin) xmin = x;
    if (x > xmax) xmax = x;
  }
  double den = n * sxx - sx * sx;
  if (n < 6 || (xmax - xmin) < 1.5 || den < 1e-6) return velocidad;   // pocas lecturas: conservar
  double pendiente = (n * sxy - sx * sy) / den;                       // m/s, positiva = subiendo
  return velocidad + VEL_SUAVIZADO * ((float)(-pendiente) - velocidad);
}

void calibrar() {
  pantalla("Calibrando...", "No mover el CanSat");
  Serial.println("Calibrando gyro y presion (no mover)...");

  float sx = 0, sy = 0, sz = 0, sp = 0;
  const int N = 200;
  for (int i = 0; i < N; i++) {
    MpuCrudo m;
    if (!mpuLeer(m)) detener("MPU6050 sin lectura", "Revisa SDA/SCL");
    sx += m.gx;
    sy += m.gy;
    sz += m.gz;
    if (i == N - 1) {
      roll  = atan2(m.ay, m.az) * RAD_TO_DEG;
      pitch = atan2(-m.ax, sqrt(m.ay * m.ay + m.az * m.az)) * RAD_TO_DEG;
    }
    delay(5);
  }
  gyroBiasX = sx / N; gyroBiasY = sy / N; gyroBiasZ = sz / N;

  for (int i = 0; i < 20; i++) {
    sp += bmp.readPressure();
    delay(50);
  }
  presionBase = sp / 20.0;
  pSuave = presionBase;
  yaw = 0;
  altitud = altSuave = 0;
  velocidad = 0;
  histN = histIdx = 0;
  Serial.print("Presion base: ");
  Serial.print(presionBase / 1000.0, 3);
  Serial.println(" kPa (altitud 0)");
}

// ---- Radio ----
// Tiempo en el aire de un paquete (formula del datasheet del SX1276)
float tiempoAireMs(int bytes, int sf) {
  float ts = pow(2, sf) / ANCHO_BANDA * 1000.0;
  bool ldro = (sf >= 11 && ANCHO_BANDA <= 125E3);
  float num = 8.0 * bytes - 4.0 * sf + 28 + 16;          // CRC activado, cabecera explicita
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
  LoRa.enableCrc();                 // descarta paquetes corruptos
  LoRa.receive();

  // paquete + pausa del receptor + ACK; el periodo deja ademas margen entre envios
  float aireJson = tiempoAireMs(JSON_BYTES_MAX, sf);
  float aireAck = tiempoAireMs(ACK_BYTES, sf);
  timeoutAckMs = aireJson + PAUSA_ACK_MS + aireAck + 600;     // cuenta desde que empieza el envio
  periodoTxMs = max((float)PERIODO_TX_MIN_MS, aireJson + PAUSA_ACK_MS + aireAck + 400);

  esperandoAck = false;
  ackOk = false;
  enviados = ackOkTotal = 0;
  Serial.printf("Perfil SF%d | %d dBm | CR 4/%d | aire JSON=%.0f ms | periodo=%lu ms | espera ACK=%lu ms\n",
                sf, POTENCIA_DBM, CODIF_CR, aireJson, periodoTxMs, timeoutAckMs);
}

// ---- Transmision ----
void enviarPaquete() {
  char json[256];
  velocidad = calcularVelocidad();        // con las lecturas validas (fuera del TX) mas recientes
  int len = snprintf(json, sizeof(json),
    "{\"n\":%lu,\"t\":%lu,\"alt\":%.2f,\"p\":%.3f,\"T\":%.2f,"
    "\"ax\":%.1f,\"ay\":%.1f,\"az\":%.1f,\"r\":%.1f,\"pi\":%.1f,\"y\":%.1f,\"v\":%.2f}",
    contador + 1, millis(), altSuave, pSuave / 1000.0, temperatura,
    ax, ay, az, roll, pitch, yaw, velocidad);

  if (LoRa.beginPacket() == 0) return;    // todavia transmitiendo el anterior
  contador++;
  LoRa.write((const uint8_t*)json, len);
  txActivo = true;                        // desde aqui las lecturas del baro se descartan
  LoRa.endPacket(true);                   // asincrono: no bloquea las lecturas

  enviados++;
  esperandoAck = true;
  ackOk = false;
  ackEsperado = contador;
  tEnvio = millis();

  Serial.print("TX ");
  Serial.print(len);
  Serial.print("B: ");
  Serial.println(json);
}

void revisarRecepcion() {
  if (txTerminado) {            // al terminar de transmitir, volver a escuchar el ACK
    txTerminado = false;
    txActivo = false;
    tFinTx = millis();
    LoRa.receive();
  }
  if (rxPendiente) {
    rxPendiente = false;
    String r = "";
    while (LoRa.available()) r += (char)LoRa.read();
    if (esperandoAck && r == "ACK:" + String(ackEsperado)) {
      esperandoAck = false;
      ackOk = true;
      ackOkTotal++;
      ackRssi = LoRa.packetRssi();
    }
  }
  if (esperandoAck && millis() - tEnvio > timeoutAckMs) {
    esperandoAck = false;
    ackOk = false;
    Serial.println("Sin ACK");
  }
}

void actualizarOled() {
  char b1[32], b2[32], b3[32], b4[32];
  snprintf(b1, sizeof(b1), "Alt:%.1fm T:%.1fC", altitud, temperatura);
  snprintf(b2, sizeof(b2), "P:%.2fkPa V:%.1f", pSuave / 1000.0, velocidad);
  snprintf(b3, sizeof(b3), "R%.0f P%.0f Y%.0f", roll, pitch, yaw);
  if (enviados == 0)      snprintf(b4, sizeof(b4), "TX #0");
  else if (esperandoAck)  snprintf(b4, sizeof(b4), "TX #%lu ACK..", contador);
  else if (ackOk)         snprintf(b4, sizeof(b4), "#%lu ACK %ddBm", contador, ackRssi);
  else                    snprintf(b4, sizeof(b4), "#%lu SIN ACK", contador);
  pantalla(b1, b2, b3, b4);
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("== CanSat TRANSMISOR ==");

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);
  oled.begin();
  pantalla("Iniciando...");

  escanearI2C();

  // BMP280 (0x76 o 0x77). Algunos modulos son BME280 (id 0x60): tambien sirven.
  bool bmpOk = bmp.begin(0x76, 0x58) || bmp.begin(0x77, 0x58) ||
               bmp.begin(0x76, 0x60) || bmp.begin(0x77, 0x60);
  if (!bmpOk) detener("BMP280 no encontrado", "Revisa SDA/SCL");
  bmp.setSampling(Adafruit_BMP280::MODE_NORMAL,
                  Adafruit_BMP280::SAMPLING_X2,     // temperatura
                  Adafruit_BMP280::SAMPLING_X16,    // presion
                  Adafruit_BMP280::FILTER_OFF,      // sin IIR: el efecto del TX es un escalon limpio
                  Adafruit_BMP280::STANDBY_MS_1);

  if (!mpuIniciar()) detener("MPU6050 no responde", "Revisa SDA/SCL");

  calibrar();

  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_SS);
  LoRa.setPins(LORA_SS, LORA_RST, LORA_DIO0);
  if (!LoRa.begin(FRECUENCIA)) detener("ERROR LoRa", "Revisa pines/antena");
  LoRa.onTxDone(alTerminarTx);
  LoRa.onReceive(alRecibir);
  aplicarPerfil();                  // potencia, SF, CR, preambulo, CRC y modo recepcion
  pinMode(PIN_BOTON, INPUT_PULLUP);

  Serial.println("Listo. Transmitiendo...");
  pantalla("Listo", "Transmitiendo...");
  tPrevFiltro = tPrevBaro = micros();
  ultimoTx = ultimoOled = ultimoSensor = millis();
}

void loop() {
  unsigned long ahora = millis();

  if (ahora - ultimoSensor >= PERIODO_SENSORES_MS) {
    unsigned long us = micros();
    leerMpu((us - tPrevFiltro) / 1e6);
    tPrevFiltro = us;
    ultimoSensor = ahora;
  }

  if (micros() - tPrevBaro >= PERIODO_BARO_MS * 1000UL) {
    tPrevBaro = micros();
    leerBaro();
  }

  // Boton PRG: siguiente perfil (pulsar tambien en el receptor)
  static unsigned long ultimoBoton = 0;
  if (digitalRead(PIN_BOTON) == LOW && ahora - ultimoBoton > 400) {
    ultimoBoton = ahora;
    perfil = (perfil + 1) % N_PERFILES;
    aplicarPerfil();
  }

  revisarRecepcion();

  if (ahora - ultimoTx >= periodoTxMs) {
    ultimoTx = ahora;
    enviarPaquete();
  }

  if (ahora - ultimoOled >= PERIODO_OLED_MS) {
    ultimoOled = ahora;
    actualizarOled();
  }
}
