# CanSat Ajolotes — Telemetría LoRa (firmware y pruebas)

Firmware de las placas **ESP32 + SX1276** del CanSat y de la estación terrena, más los firmwares de prueba
(alcance y diagnóstico). El dashboard en Python vive en la carpeta hermana `simulator` (en GitHub es la raíz
del repo y esta carpeta queda como `Pruebas/`).

```
 CanSat (en el aire)                                   Estación terrena (en tierra)
┌────────────────────────┐   LoRa 915 MHz            ┌─────────────────────┐  USB   ┌────────────────────┐
│ CanSat_Transmisor      │ ───── JSON (~118 B) ────► │ CanSat_Receptor     │ ─────► │ simulator/         │
│ ESP32+SX1276           │ ◄──── "ACK:<n>" ───────── │ ESP32+SX1276        │ Serial │ dashboard.py       │
│ MPU6050 + BMP280 + OLED│                           │ OLED                │ 115200 │ (gráficas + CSV)   │
└────────────────────────┘                           └─────────────────────┘        └────────────────────┘
```

## Contenido de la carpeta

| Carpeta | Qué es |
|---|---|
| `CanSat_Transmisor/` | **Firmware de vuelo.** Lee MPU6050 + BMP280 y transmite telemetría. |
| `CanSat_Receptor/` | **Firmware de la estación terrena.** Recibe, valida, responde ACK y reenvía por USB. |
| `LoRa_Alcance_Maestro/`, `LoRa_Alcance_Remoto/` | **Prueba de alcance** (mismo código, solo cambia `ROL_MAESTRO`). |
| `Diag_Baro_TX/` | Diagnóstico: ¿la transmisión perturba el barómetro? (ver §6). |
| `LoRa_Prueba/`, `LoRa_Prueba_Receptor/` | Primeras pruebas de enlace con eco (SF7). Históricas. |
| `prueba_conexion_LoRa/` | Sketch vacío de la primera prueba. |

---

## 1. Hardware

- **Placas:** 2 × "LoRa 32" clon de **Heltec WiFi LoRa 32 V2** (ESP32 + SX1276 + OLED SSD1306 0.96").
  En el IDE: `Heltec WiFi LoRa 32(V2)` (`esp32:esp32:heltec_wifi_lora_32_V2`).
- **Pines** (iguales en todos los sketches):

| Señal | GPIO |
|---|---|
| SX1276 SCK / MISO / MOSI / NSS / RST / DIO0 | 5 / 19 / 27 / 18 / 14 / 26 |
| I2C (OLED + sensores) SDA / SCL | 4 / 15 |
| OLED RST | 16 |
| Botón PRG | 0 |

- **Sensores del transmisor** (comparten el bus I2C con la OLED, VCC a **3V3**, nunca 5 V):

| Sensor | Dirección | Notas |
|---|---|---|
| OLED SSD1306 | 0x3C | |
| MPU6050 | 0x68 | Nuestro módulo es un **clon** (`WHO_AM_I = 0x70`): la librería de Adafruit lo rechaza, por eso se lee **directo por registros**. |
| BMP280 | 0x76 | Con SDO a GND. El código prueba 0x76/0x77 y también el id de BME280. |

- **Montaje del MPU6050:** está montado **de canto** (la gravedad cae en su eje X). `MPU_REMAPEAR 1` aplica
  `(x', y', z') = (−z, y, x)` para que en reposo `az ≈ +9.8`, como espera el dashboard. Si se monta plano, poner `0`.
- **Antena:** conectar **siempre** antes de transmitir (el conector micro IPEX/u.FL se suelta con facilidad).

## 2. Entorno de desarrollo

- **Arduino IDE 2.x** + paquete **esp32 (Espressif) 3.3.12**.
- **Librerías** (Administrador de bibliotecas):

| Librería | Autor | Usada en |
|---|---|---|
| LoRa 0.8.0 | Sandeep Mistry | todos |
| U8g2 | oliver | todos (OLED) |
| Adafruit BMP280 Library (+ BusIO, Unified Sensor) | Adafruit | Transmisor, Diag |
| ArduinoJson **v7** | Benoit Blanchon | Receptor |

- **Driver USB:** CP210x (Silicon Labs). Sin él no aparece el puerto COM (Administrador de dispositivos → error código 28).
- **Importante — dos placas, un solo COM:** ambas placas reportan el mismo número de serie USB (`0001`) y Windows
  normalmente muestra **un solo puerto** (el que se conectó). Para programar o leer una placa, conecta **solo esa**.
- **Un puerto = un programa.** Si el Monitor Serie del IDE está abierto, el dashboard recibe `Acceso denegado` (y viceversa).
- Compilar sin IDE: `arduino-cli compile --fqbn esp32:esp32:heltec_wifi_lora_32_V2 CanSat_Transmisor`
  (el CLI viene dentro de la carpeta de instalación del Arduino IDE).

---

## 3. Radio LoRa

Mismos parámetros en **ambos** extremos o no se oyen:

| Parámetro | Valor | Comentario |
|---|---|---|
| Frecuencia | 915 MHz | Banda ISM de América |
| Potencia | **20 dBm** | `setTxPower(20, PA_OUTPUT_PA_BOOST_PIN)`. El valor por defecto de la librería es 17 |
| Ancho de banda | 125 kHz | |
| Codificación | **4/8** | Más robusta que 4/5 (el defecto), más tiempo en el aire |
| Preámbulo | 12 símbolos | |
| Sync word | 0x12 | |
| CRC | activado | Descarta paquetes corruptos |
| **Spreading Factor** | **SF10 por defecto** | Cambiable con el botón **PRG** (ver abajo) |

**Principio de diseño: sacrificar velocidad para ganar alcance.** Sensibilidad y tiempo en el aire (BW 125 kHz, CR 4/8, preámbulo 12):

| SF | Sensibilidad | Aire JSON (125 B) | Periodo de envío (CanSat) | Paquetes/min | Ganancia vs SF7 @ 17 dBm |
|---|---|---|---|---|---|
| 7 | −123 dBm | 0.33 s | 1.0 s | 60 | +3 dB (solo potencia) |
| 8 | −126 dBm | 0.57 s | 1.1 s | 54 | +6 dB |
| 9 | −129 dBm | 1.02 s | 1.6 s | 36 | +9 dB |
| **10** | **−132 dBm** | **1.90 s** | **2.7 s** | **22** | **+12 dB** |

Cada +6 dB duplica aproximadamente el alcance en espacio libre. Con SF10 **la telemetría baja a ~22 paquetes/min**: si la
misión exige 1 Hz, solo SF7 llega a 1 paquete/s. Elegir el SF es un compromiso alcance ↔ tasa de datos.

**Botón PRG (cambio de perfil sin reflashear):** cada pulsación pasa al siguiente SF. **Hay que pulsarlo en ambas placas**, con las dos
juntas, hasta que muestren el mismo `SFxx` en la esquina superior derecha de la OLED. **Las listas son distintas según la familia:**

| Sketches | Lista de SF | SF al arrancar |
|---|---|---|
| `CanSat_Transmisor` / `CanSat_Receptor` | 7 → 8 → 9 → 10 | 10 |
| `LoRa_Alcance_*` | 7 → 9 → 10 → 12 | 10 |

Los tiempos (periodo de envío, espera del ACK) **se calculan solos** con la fórmula del tiempo en el aire del datasheet del SX1276
(`tiempoAireMs()` en cada sketch), así que cambiar el SF no exige tocar nada más.

## 4. Protocolo de telemetría (CanSat_*)

### 4.1 Paquete del transmisor (JSON, ~112–118 bytes)

```json
{"n":12,"t":34567,"alt":1.23,"p":96.912,"T":26.70,"ax":0.2,"ay":-0.1,"az":10.2,"r":-0.3,"pi":-1.6,"y":0.1,"v":0.02}
```

| Clave | Significado | Unidad |
|---|---|---|
| `n` | número de paquete (empieza en 1 al arrancar) | |
| `t` | tiempo desde el arranque del transmisor | ms |
| `alt` | altitud **relativa** al punto de arranque | m |
| `p` | presión (suavizada) | kPa |
| `T` | temperatura (BMP280) | °C |
| `ax` `ay` `az` | aceleración (ejes ya remapeados) | m/s² |
| `r` `pi` `y` | roll, pitch, yaw | grados |
| `v` | velocidad vertical, **positiva = descendiendo** | m/s |

No lleva `"id"` (ahorra tiempo en el aire); el dashboard usa el `TEAM_ID` de `simulator/telemetry_format.py`.

### 4.2 ACK
El receptor responde `ACK:<n>` (ej. `ACK:12`) unos 30 ms después de recibir el paquete válido. El transmisor lo usa solo para
mostrar en su OLED si el paquete llegó y con qué RSSI; **no hay reenvío automático** si no llega.

### 4.3 Salida del receptor por USB (115200 baudios)
Una línea JSON por paquete, **el mismo JSON + `rssi` (dBm) y `snr` (dB)**. Las líneas que empiezan con `#` son diagnóstico
(perfil activo, errores) y el dashboard las ignora.

---

## 5. Cómo funciona el firmware `CanSat_Transmisor`

### Arranque (`setup`)
1. `Wire.begin(4,15)` a 400 kHz, OLED y escaneo I2C (imprime `Dispositivos I2C: 0x3C 0x68 0x76`; si falta uno, revisar cableado).
2. Inicia BMP280 (muestreo: temp ×2, presión ×16, **sin filtro IIR**, standby 1 ms) y MPU6050 (±8 g, ±500 °/s, filtro ~44 Hz).
3. `calibrar()` — **la placa debe estar quieta ~2 s**: promedia 200 lecturas del giroscopio (sesgo) y 20 de presión (**cero de altitud**), y fija yaw = 0.
4. Inicia el SX1276, registra los callbacks `onTxDone` / `onReceive` y llama `aplicarPerfil()` (potencia, SF, CR, preámbulo, CRC; calcula periodo y timeout).

### Bucle principal (`loop`)
| Tarea | Frecuencia | Detalle |
|---|---|---|
| Lectura MPU6050 + actitud | 50 Hz | **Filtro complementario** 0.98 giroscopio + 0.02 acelerómetro para roll/pitch. El yaw solo integra el giroscopio y **deriva** (no hay magnetómetro). |
| Lectura BMP280 | 20 Hz | Con **descarte de lecturas contaminadas** por el TX (ver abajo). |
| Envío de paquete | cada `periodoTxMs` | `max(1000, aire(JSON) + 30 + aire(ACK) + 400)` ms. Transmisión **asíncrona** (`endPacket(true)`) para no bloquear los sensores. |
| Recepción del ACK | continua | Al terminar el TX se pasa a recepción continua. Espera `aire(JSON) + 30 + aire(ACK) + 600` ms. |
| OLED | 2 Hz | Altitud, T, P, velocidad, actitud y estado del ACK (`ACK -63dBm` / `SIN ACK`). |
| Botón PRG | — | Cambia de SF (antirrebote 400 ms) y reinicia los contadores. |

### Barómetro: altitud y velocidad (lo más delicado del firmware)
**Problema descubierto con `Diag_Baro_TX`:** la transmisión a 20 dBm desplaza la lectura del BMP280 (≈ −11 Pa ≈ +1 m) **mientras el
amplificador está encendido**. Como el paquete se armaba justo al empezar el TX, la altitud salía ~+2 m y la velocidad ~+3 m/s
fijas con la placa quieta. Solución implementada:

1. **BMP280 sin filtro IIR:** el efecto queda como un escalón limpio en lugar de una curva borrosa de ~1 s.
2. **Se descartan las lecturas** mientras `txActivo` y durante `GUARDA_TX_MS = 100 ms` tras terminar el TX. Solo se usan las lecturas de los huecos entre paquetes.
3. **Velocidad por regresión lineal** de la altitud sobre las lecturas válidas de los últimos `VEL_VENTANA_S = 4 s`, con sus marcas de tiempo reales (se calcula al armar cada paquete y se suaviza con `VEL_SUAVIZADO = 0.6`). Latencia aproximada: 1–3 s.
4. **Cero autoajustable en tierra:** la presión de referencia sigue lentamente a la presión medida (constante ~20 s, `ZERO_ALFA`) **solo si** `|altitud| < ZERO_BANDA_M (1.5 m)` y `|velocidad| < ZERO_VEL_MAX (0.2 m/s)`. En cuanto despega o se mueve, queda congelada. Absorbe la deriva térmica acumulada por el TX sostenido.

Resultado en banco (20 dBm, SF10, 2 min, placa quieta): altitud media −0.01 m (desv. 0.12 m), velocidad media 0.00 m/s (desv. 0.02 m/s).

### Constantes que se pueden ajustar (inicio del `.ino`)
| Constante | Efecto |
|---|---|
| `POTENCIA_DBM` | 2–20 dBm. Menos potencia = menos perturbación al baro, menos alcance |
| `perfil` / `PERFILES_SF` | SF inicial y lista del botón PRG |
| `JSON_BYTES_MAX` | Tamaño supuesto del JSON para calcular tiempos (si agregan campos, subirlo) |
| `PERIODO_TX_MIN_MS` | Periodo mínimo entre paquetes (el real depende del SF) |
| `MPU_REMAPEAR` | Remapeo de ejes (módulo de canto o plano) |
| `GUARDA_TX_MS`, `ALT_SUAVIZADO`, `VEL_SUAVIZADO`, `VEL_VENTANA_S`, `ZERO_*` | Afinan altitud, velocidad y cero autoajustable |

**Si agregan campos al JSON:** actualizar `JSON_BYTES_MAX`, el `snprintf` de `enviarPaquete()`, y `REQUIRED`/`convert()` en
`simulator/lora_bridge.py` si el campo es obligatorio.

## 6. Cómo funciona el firmware `CanSat_Receptor`

1. Arranca OLED y SX1276 con el **mismo perfil** que el transmisor; la recepción es **continua** (`onReceive` solo levanta una bandera; el procesamiento ocurre en el `loop`).
2. Por cada paquete (`procesarPaquete`):
   - Parsea el JSON con ArduinoJson. Es **válido** si trae `n` y `alt`; si no, cuenta un error y lo reporta con `#`.
   - **Cuenta pérdidas** por huecos en `n` (`perdidos += n − ultimoN − 1`); se reinicia si llega el primer paquete o `n` retrocede (el transmisor se reinició).
   - Responde `ACK:<n>` tras 30 ms y vuelve a recepción.
   - Agrega `rssi` y `snr` y reenvía el JSON por USB.
3. **OLED (4 líneas):** `Alt/V` · `T/P` · `SNR/Perdidos` · `RSSI/#paquete`. Si pasan más de `2.5 × periodo + 1 s` sin paquetes muestra `SIN SENAL hace Ns`.
4. **Botón PRG:** cambia el SF (mismo comportamiento que en el transmisor).

El receptor **no calcula** altitud ni fases de vuelo; solo reenvía. La fase de vuelo la estima el dashboard (`simulator/lora_bridge.py`).

---

## 7. Prueba de alcance: `LoRa_Alcance_Maestro` y `LoRa_Alcance_Remoto`

**Objetivo:** medir hasta dónde llega el enlace y qué tan bien en **cada sentido por separado**, sin laptop (cada placa con su powerbank).

### Protocolo ping/pong
- **MAESTRO** (fijo): manda `P,<seq>,<pongs_ok>,<pings_enviados>` y espera el pong.
- **REMOTO** (el que se aleja): mide RSSI/SNR del ping, espera 150 ms y responde `R,<seq>,<rssi>,<snr×10>`.
- Con eso el maestro conoce los **dos sentidos**:
  - **UP** = lo que oyó el remoto (el ping) · **DN** = lo que oyó el maestro (el pong).
- El remoto cuenta los pings perdidos por huecos en `seq`, y el maestro le dice (dentro del ping) cuántos pongs ha recibido.
- Periodo del maestro: `max(1500 ms, 2 × aire(24 B) + 700)`; espera del pong: `aire + 150 + 600` ms.

| SF | Sensibilidad | Aire (24 B) | Periodo del ping |
|---|---|---|---|
| 7 | −123 dBm | 0.09 s | 1.5 s |
| 9 | −129 dBm | 0.30 s | 1.5 s |
| **10** | −132 dBm | 0.53 s | 1.8 s |
| 12 | −137 dBm | 2.1 s | 4.9 s |

### Qué muestra la OLED
- **Maestro:** `Ping #N OK|SIN RESP` · `UP:-95 DN:-97 dBm` · `SNR UP:-3.5 DN:-2.0` · `OK 45/50 (90%)`.
- **Remoto:** `Rx #N RSSI:-95` · `SNR:-3.5 Perd:2` · `Maestro oye:45/50` · `Hace 3s  90% ok` (o `SIN SENAL`).
- Por Serial (115200) ambos imprimen CSV: Maestro `seq,OK,upRssi,upSnr,dnRssi,dnSnr` o `seq,PERDIDO`; Remoto `seq,RX,rssi,snr,perdidos=N`.

### Cómo hacer la prueba
1. Sube **Maestro** a una placa y **Remoto** a la otra (en el IDE, abrir cada carpeta).
2. Con las dos **juntas** (antena vertical, lejos de metal), pulsa **PRG en ambas** hasta que muestren el mismo SF.
3. Deja el Maestro fijo y camina con el Remoto. Anota **distancia, RSSI y SNR (UP y DN) y % de aciertos** en cada punto.
4. Al perder el enlace, sube de SF (PRG en ambas) y repite. Si el Remoto muestra "Revisa el perfil SF", están desincronizados.
5. Distancias: mídelas con el mapa del celular (no hay GPS).

### Cómo interpretar
- **UP ≠ DN muy distintos** → una antena es peor que la otra.
- **RSSI a 1 m debería estar por encima de −50 dBm.** Si sigue en −60 o peor, es la antena/conector, no el software.
- Con SNR negativo el RSSI reportado es poco fiable (normal en SF10/SF12 cerca del límite); fíate del **% de paquetes recibidos**.
- Referencia en espacio libre (TX 17 dBm, antenas ~2 dBi): RSSI esperado a 1 m ≈ −11, 2 m ≈ −17, 5 m ≈ −25, 10 m ≈ −31 dBm.

### Antecedente (prueba previa con otro firmware)
Una primera prueba, de un segundo piso a un primer piso exterior (ambas placas con powerbank), **solo llegó a ~100 m**. El RSSI a 1–2 m ya era de −55 a −79 dBm
(40–60 dB por debajo de lo ideal), lo que apunta a **antena o conector** (mal encajado, antena apoyada en metal o en la laptop, banda equivocada)
más que a los parámetros de radio. **La causa no está confirmada.** Antes de repetir: verificar conectores, que las antenas sean de 915 MHz,
y montarlas verticales, lejos de metal y a más de 1 m del suelo.

### Resultados (completar)
| SF | Distancia máx. (m) | ¿Línea de vista? | RSSI UP / DN (dBm) | SNR UP / DN (dB) | % recibido | Notas |
|---|---|---|---|---|---|---|
| 7 | | | | | | |
| 9 | | | | | | |
| 10 | | | | | | |
| 12 | | | | | | |

---

## 8. Diagnóstico del barómetro: `Diag_Baro_TX`

Firmware **solo de diagnóstico** (no es de vuelo). Imita al transmisor (mismo bus, BMP280, radio y OLED) y alterna fases de 20 s:
sin TX → TX a potencia X → TX a potencia Y → sin TX. Imprime a 115200 baudios: `D,<ms>,<fase>,<tx 0/1>,<oled 0/1>,<presión Pa>,<temp °C>`.
Cambia `POTENCIA[]`, `FASE_MS` y el filtro del BMP280 en el `.ino` para otros experimentos. **Después hay que volver a subir `CanSat_Transmisor`.**

Hallazgos (SF10, paquetes de 112 B cada 2.7 s):
- Sin TX: presión estable (desv. ~1 Pa). **Con TX la lectura baja, y más cuanto mayor la potencia** (diferencia entre TX activo y huecos): 2 dBm ≈ 0.3 Pa · 14 dBm ≈ 1.5–1.8 Pa · 17 dBm ≈ 3.1 Pa · 20 dBm ≈ 4.5–5.6 Pa.
- Con filtro IIR ×16, a 20 dBm aparece un **diente de sierra de ~25 Pa (~2 m)** sincronizado con el TX. Sin filtro es un **escalón de ~−11 Pa** que vuelve a 0 al apagar el amplificador.
- **No es la OLED** (su redibujo no cambia la presión) y la temperatura del BMP280 no cambia → causa eléctrica (radio o alimentación), no térmica. No se ha distinguido entre ambas.
- **Pendiente recomendado (hardware):** capacitor de 100 µF + 0.1 µF en el VCC del BMP280, cables cortos y lejos de la antena.

## 9. Dashboard (resumen)

```
cd simulator
python dashboard.py --list-ports        # ver puertos
python dashboard.py --serial COM7       # modo LoRa (cerrar antes el Monitor Serie)
```
Abrir http://localhost:8000. Muestra fase de vuelo, altitud, velocidad, temperatura, presión, orientación 3D, aceleración, **RSSI/SNR del enlace** y
guarda un CSV (`telemetry_log_*.csv`, con columnas extra `RSSI` y `SNR` en modo LoRa). Detalle en `simulator/README.md`.
- La **fase de vuelo se estima** en `lora_bridge.py` a partir de altitud y velocidad (umbrales a ajustar con un vuelo real).
- Alerta "Sin señal" tras 10 s sin paquetes (a SF10 llega un paquete cada ~3 s).
- El botón **Reiniciar** reinicia el tiempo de misión y el CSV, **no** la altitud 0 (esa se reajusta sola en tierra o al reiniciar el transmisor).

## 10. Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| No aparece puerto COM | Falta driver CP210x / cable solo de carga | Instalar driver; usar cable de datos |
| Solo aparece un COM con las dos placas | Mismo número de serie USB | Conectar una placa a la vez |
| `Acceso denegado` al abrir COM7 | Monitor Serie del IDE o dashboard abiertos | Cerrar el otro programa |
| Transmisor dice `BMP280/MPU6050 no encontrado` | Cableado I2C | Mirar la línea `Dispositivos I2C: ...` del arranque |
| Receptor no recibe nada | SF distinto entre placas / antena suelta | Igualar el SF con PRG en ambas; revisar antena |
| `SIN ACK` en el transmisor | El receptor no oyó o el ACK no volvió | Revisar distancia, antenas y que el SF coincida |
| Altitud ≠ 0 en tierra con TX | Perturbación del TX / deriva térmica | Ver §5 (ya mitigado); capacitor en el BMP280 |
| `Failed to connect to ESP32` al subir | Placa no entra en modo de carga | Mantener **BOOT/PRG** pulsado al iniciar la subida |
| Lecturas de aceleración ≈ 10.2 en vez de 9.81 | Error de escala del módulo MPU6050 | Normal en este módulo; no afecta las gráficas |

## 11. Limitaciones y pendientes

- No hay medición de **batería** (el dashboard muestra `--`), **GPS** ni detección de **carga secundaria**.
- El **yaw** deriva con el tiempo (sin magnetómetro).
- Con SF10 la telemetría es de ~22 paquetes/min; la velocidad se calcula sobre ~4 s.
- No se ha probado el cero autoajustable ni la velocidad **en vuelo real** (solo en banco).
- No hay reenvío automático de paquetes perdidos (el ACK es solo informativo).
- Verificar en campo que la radio de control del dron **no use 915 MHz** (ELRS/Crossfire/telemetría) antes de volar el transmisor.
