// DIAGNOSTICO: ¿la transmision LoRa perturba la lectura del barometro (BMP280)?
//
// Imita al transmisor real (mismo bus I2C, mismo BMP280 con FILTER_X16, misma radio
// SF10 / CR 4/8 / preambulo 12, paquetes de 112 B cada 2727 ms, OLED a 2 Hz) y alterna
// fases de FASE_MS cada una:
//   0 = SIN TX          (radio en recepcion)
//   1 = TX a 2 dBm
//   2 = TX a 20 dBm
//   3 = SIN TX          (para ver si la lectura vuelve a su valor)
// Imprime por Serial a 115200, 10 veces por segundo:
//   D,<ms>,<fase>,<tx 0/1>,<oled 0/1>,<presion Pa>,<temperatura C>
// tx = el SX1276 esta transmitiendo en ese instante; oled = hubo un redibujo de la OLED
// desde la lectura anterior. Las lineas "# ..." son comentarios.
//
// NO es el firmware de vuelo: despues hay que volver a subir CanSat_Transmisor.

#include <SPI.h>
#include <Wire.h>
#include <LoRa.h>
#include <U8g2lib.h>
#include <Adafruit_BMP280.h>

#define FASE_MS     20000
#define PERIODO_TX  2727      // igual que el transmisor real en SF10
#define PAQUETE_B   112

#define LORA_SCK 5
#define LORA_MISO 19
#define LORA_MOSI 27
#define LORA_SS 18
#define LORA_RST 14
#define LORA_DIO0 26
#define I2C_SDA 4
#define I2C_SCL 15
#define OLED_RST 16

U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, OLED_RST, I2C_SCL, I2C_SDA);
Adafruit_BMP280 bmp(&Wire);

const int N_FASES = 4;
const int POTENCIA[N_FASES] = {0, 20, 20, 0};        // 0 = sin transmitir
const char* NOMBRE[N_FASES] = {"SIN TX", "TX 20dBm", "TX 20dBm", "SIN TX"};

int fase = 0;
unsigned long tFase = 0, ultimoBaro = 0, ultimoTx = 0, ultimoOled = 0, ciclo = 0;
bool oledDibujado = false;
volatile bool txTerminado = false;      // la pone el callback cuando el SX1276 termina de transmitir
bool txActivo = false;                  // true desde endPacket(true) hasta el fin de la transmision
void alTerminarTx() { txTerminado = true; }

void dibujar() {
  char b[32];
  oled.clearBuffer();
  oled.setFont(u8g2_font_7x13B_tr);
  oled.drawStr(0, 14, "DIAGNOSTICO");
  oled.setFont(u8g2_font_6x10_tf);
  snprintf(b, sizeof(b), "Fase %d: %s", fase, NOMBRE[fase]);
  oled.drawStr(0, 32, b);
  snprintf(b, sizeof(b), "Ciclo %lu", ciclo);
  oled.drawStr(0, 46, b);
  oled.drawStr(0, 60, "No mover la placa");
  oled.sendBuffer();
}

void iniciarFase() {
  tFase = millis();
  if (POTENCIA[fase] > 0) LoRa.setTxPower(POTENCIA[fase], PA_OUTPUT_PA_BOOST_PIN);
  Serial.printf("# FASE %d %s (ciclo %lu) t=%lu\n", fase, NOMBRE[fase], ciclo, millis());
  dibujar();
  oledDibujado = true;
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("# == DIAGNOSTICO baro vs TX ==");

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);
  oled.begin();

  bool ok = bmp.begin(0x76, 0x58) || bmp.begin(0x77, 0x58) ||
            bmp.begin(0x76, 0x60) || bmp.begin(0x77, 0x60);
  if (!ok) { Serial.println("# ERROR: BMP280 no encontrado"); while (true) delay(1000); }
  bmp.setSampling(Adafruit_BMP280::MODE_NORMAL, Adafruit_BMP280::SAMPLING_X2,
                  Adafruit_BMP280::SAMPLING_X16, Adafruit_BMP280::FILTER_OFF,   // sin IIR
                  Adafruit_BMP280::STANDBY_MS_1);

  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_SS);
  LoRa.setPins(LORA_SS, LORA_RST, LORA_DIO0);
  if (!LoRa.begin(915E6)) { Serial.println("# ERROR: LoRa no inicia"); while (true) delay(1000); }
  LoRa.setSpreadingFactor(10);
  LoRa.setSignalBandwidth(125E3);
  LoRa.setCodingRate4(8);
  LoRa.setPreambleLength(12);
  LoRa.setSyncWord(0x12);
  LoRa.enableCrc();
  LoRa.onTxDone(alTerminarTx);
  LoRa.receive();

  Serial.println("# columnas: D,ms,fase,tx,oled,presion_Pa,temp_C");
  delay(3000);                       // dejar que el sensor se asiente antes de la fase 0
  iniciarFase();
}

void loop() {
  unsigned long ahora = millis();

  if (ahora - tFase >= FASE_MS) {
    fase = (fase + 1) % N_FASES;
    if (fase == 0) ciclo++;
    iniciarFase();
  }

  if (txTerminado) {                    // como el transmisor real: al terminar, volver a escuchar
    txTerminado = false;
    txActivo = false;
    LoRa.receive();
  }

  if (POTENCIA[fase] > 0 && !txActivo && ahora - ultimoTx >= PERIODO_TX) {
    ultimoTx = ahora;
    uint8_t buf[PAQUETE_B];
    memset(buf, 'x', sizeof(buf));
    if (LoRa.beginPacket()) {
      LoRa.write(buf, sizeof(buf));
      txActivo = true;
      LoRa.endPacket(true);                               // asincrono, como el real
    }
  }

  if (ahora - ultimoBaro >= 50) {                         // 20 Hz
    ultimoBaro = ahora;
    float t = bmp.readTemperature();
    float p = bmp.readPressure();
    Serial.printf("D,%lu,%d,%d,%d,%.1f,%.2f\n", ahora, fase, txActivo ? 1 : 0,
                  oledDibujado ? 1 : 0, p, t);
    oledDibujado = false;
  }

  if (ahora - ultimoOled >= 500) {
    ultimoOled = ahora;
    dibujar();
    oledDibujado = true;
  }
}
