// CanSat - TRANSMISOR
// ESP32 + SX1276 (clon Heltec WiFi LoRa 32 V2) + MPU6050 + BMP280
//
// Lee los sensores y transmite un paquete JSON por LoRa cada PERIODO_TX_MS.
// El receptor responde con "ACK:<n>" para saber si el paquete llego.
//
// Librerias (Administrador de bibliotecas):
//   - LoRa                (Sandeep Mistry)
//   - U8g2                (oliver)
//   - Adafruit BMP280 Library  (instala tambien Adafruit BusIO y Adafruit Unified Sensor)
//   (el MPU6050 se lee directo por registros I2C: no necesita libreria y funciona
//    tambien con modulos clon que no pasan la verificacion de identidad de Adafruit)
//
// Conexion de sensores (bus I2C compartido con la OLED, pines 4 y 15):
//   MPU6050 y BMP280:  VCC -> 3V3 | GND -> GND | SDA -> GPIO4 | SCL -> GPIO15
//   (MPU6050 AD0 a GND -> 0x68. BMP280 SDO a GND -> 0x76 o a 3V3 -> 0x77)
//
// Paquete JSON (claves cortas para que quepa en un paquete LoRa):
//   id equipo | n # paquete | t ms desde el arranque | alt m (relativa al arranque)
//   p presion kPa | T temperatura C | ax ay az m/s^2 | r pi y roll/pitch/yaw grados
//   v velocidad vertical m/s (positiva = descendiendo)

#include <SPI.h>
#include <Wire.h>
#include <LoRa.h>
#include <U8g2lib.h>
#include <Adafruit_BMP280.h>

#define TEAM_ID        "FIT2026"
#define FRECUENCIA     915E6

#define PERIODO_TX_MS       1000   // cada cuanto se transmite un paquete
#define PERIODO_SENSORES_MS 20     // lectura del MPU6050 (50 Hz) para el filtro
#define PERIODO_BARO_MS     100    // lectura del BMP280 (10 Hz)
#define PERIODO_OLED_MS     500
#define TIMEOUT_ACK_MS      800

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

// Velocidad vertical: se deriva de una altitud suavizada, comparando contra la de
// hace 1 s (10 muestras a 10 Hz). Derivar muestra a muestra amplificaria el ruido
// del barometro (~0.3 m de jitter -> ~3 m/s falsos).
#define VEL_VENTANA     10        // muestras del baro (1 s)
#define ALT_SUAVIZADO   0.3f      // 0..1, menor = mas suave
#define VEL_SUAVIZADO   0.4f      // peso de la medicion nueva en la velocidad
float altSuave = 0;
float histAlt[VEL_VENTANA];
int histIdx = 0;
unsigned long tPrevFiltro = 0, tPrevBaro = 0;

// ---- Enlace LoRa ----
volatile bool txTerminado = false;
volatile bool rxPendiente = false;
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
  oled.drawStr(128 - 6 * 6 - 2, 11, "915MHz");
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
  temperatura = bmp.readTemperature();
  presionPa   = bmp.readPressure();
  altitud     = altitudDesdePresion(presionPa);

  altSuave += ALT_SUAVIZADO * (altitud - altSuave);
  float altHaceUnSegundo = histAlt[histIdx];          // la muestra mas vieja de la ventana
  histAlt[histIdx] = altSuave;
  histIdx = (histIdx + 1) % VEL_VENTANA;

  float ventanaS = VEL_VENTANA * PERIODO_BARO_MS / 1000.0f;
  float vNueva = -(altSuave - altHaceUnSegundo) / ventanaS;   // positiva = descendiendo
  velocidad += VEL_SUAVIZADO * (vNueva - velocidad);
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
  yaw = 0;
  altitud = altSuave = 0;
  velocidad = 0;
  for (int i = 0; i < VEL_VENTANA; i++) histAlt[i] = 0;
  histIdx = 0;
  Serial.print("Presion base: ");
  Serial.print(presionBase / 1000.0, 3);
  Serial.println(" kPa (altitud 0)");
}

// ---- Transmision ----
void enviarPaquete() {
  char json[256];
  contador++;
  int len = snprintf(json, sizeof(json),
    "{\"id\":\"%s\",\"n\":%lu,\"t\":%lu,\"alt\":%.2f,\"p\":%.3f,\"T\":%.2f,"
    "\"ax\":%.2f,\"ay\":%.2f,\"az\":%.2f,\"r\":%.1f,\"pi\":%.1f,\"y\":%.1f,\"v\":%.2f}",
    TEAM_ID, contador, millis(), altitud, presionPa / 1000.0, temperatura,
    ax, ay, az, roll, pitch, yaw, velocidad);

  if (LoRa.beginPacket() == 0) return;    // todavia transmitiendo el anterior
  LoRa.write((const uint8_t*)json, len);
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
  if (esperandoAck && millis() - tEnvio > TIMEOUT_ACK_MS) {
    esperandoAck = false;
    ackOk = false;
    Serial.println("Sin ACK");
  }
}

void actualizarOled() {
  char b1[32], b2[32], b3[32], b4[32];
  snprintf(b1, sizeof(b1), "Alt:%.1fm T:%.1fC", altitud, temperatura);
  snprintf(b2, sizeof(b2), "P:%.2fkPa V:%.1f", presionPa / 1000.0, velocidad);
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
                  Adafruit_BMP280::FILTER_X16,
                  Adafruit_BMP280::STANDBY_MS_1);

  if (!mpuIniciar()) detener("MPU6050 no responde", "Revisa SDA/SCL");

  calibrar();

  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_SS);
  LoRa.setPins(LORA_SS, LORA_RST, LORA_DIO0);
  if (!LoRa.begin(FRECUENCIA)) detener("ERROR LoRa", "Revisa pines/antena");
  LoRa.setSpreadingFactor(7);
  LoRa.setSignalBandwidth(125E3);
  LoRa.setSyncWord(0x12);
  LoRa.enableCrc();                 // descarta paquetes corruptos
  LoRa.onTxDone(alTerminarTx);
  LoRa.onReceive(alRecibir);
  LoRa.receive();

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

  revisarRecepcion();

  if (ahora - ultimoTx >= PERIODO_TX_MS) {
    ultimoTx = ahora;
    enviarPaquete();
  }

  if (ahora - ultimoOled >= PERIODO_OLED_MS) {
    ultimoOled = ahora;
    actualizarOled();
  }
}
