# Simulador CanSat

Simulador de vuelo + estacion terrena, para desarrollar y probar el software
de telemetria antes de tener el hardware/firmware real.

## Como funciona

- `telemetry_format.py` define el formato del paquete de telemetria (CSV) y
  las funciones para codificarlo/decodificarlo. Este es el formato que el
  firmware real debera producir cuando este listo.
- `flight_sim.py` simula un vuelo completo (ascenso, caida libre, autogiro,
  aterrizaje) y envia paquetes de telemetria por UDP, como si fuera el radio
  del CanSat.
- `ground_station.py` recibe esos paquetes por UDP, los guarda en un CSV con
  timestamp y los grafica en tiempo real (altitud, velocidad, temperatura,
  presion, estado de vuelo, bateria).

Cuando el firmware real este listo, `ground_station.py` no cambia: solo hay
que hacer que el firmware transmita lineas con el mismo formato de
`telemetry_format.py` (por radio en vez de UDP), o adaptar el listener para
leer del puerto serial/radio real en vez de un socket UDP.

## Uso

Instalar dependencias (una sola vez):

```bash
pip install -r requirements.txt
```

Terminal 1 (estacion terrena, se abre una ventana con las graficas):

```bash
python ground_station.py
```

Terminal 2 (simulador de vuelo):

```bash
python flight_sim.py --speed 10
```

`--speed 10` corre el vuelo 10 veces mas rapido que en tiempo real, util para
probar rapido. Sin esa opcion, el vuelo dura lo mismo que uno real (varios
minutos, dominado por el ascenso).

Cada corrida de la estacion terrena genera un archivo
`telemetry_log_YYYYMMDD_HHMMSS.csv` con todos los paquetes recibidos.

## Dashboard web (interfaz recomendada)

```bash
python dashboard.py
```

Abrir http://localhost:8000. Desde ahi se puede iniciar/detener el simulador
(con la velocidad elegida), reiniciar la mision y exportar el CSV. Muestra
fase de vuelo, tarjetas de estado, orientacion 3D, aceleraciones, y
las graficas de altitud, velocidad, temperatura y presion.
No necesita dependencias extra. `ground_station.py` sigue funcionando igual.

El dashboard funciona sin internet: las fuentes (Michroma y Exo 2, licencia
OFL) estan en `fonts/` y el logo es `Logo Ajolotes.png`.

## Modo LoRa (datos reales)

El dashboard puede alimentarse del receptor LoRa (`Pruebas/CanSat_Receptor`) en vez
del simulador. El receptor manda por USB una linea JSON por paquete; `lora_bridge.py`
la convierte al formato de `telemetry_format.py`, asi que graficas y CSV no cambian.

```bash
python dashboard.py --list-ports          # ver los puertos disponibles
python dashboard.py --serial COM7         # modo LoRa (cerrar antes el Monitor Serie del IDE)
```

En este modo se ocultan los botones del simulador y aparece la tarjeta "Enlace LoRa"
(RSSI/SNR). El puerto se reabre solo si se desconecta la placa.

Formato JSON (claves cortas para caber en un paquete LoRa):

| Clave | Campo del dashboard | Unidad |
|---|---|---|
| `id` | TEAM_ID | |
| `n` | PACKET_COUNT | |
| `t` | MISSION_TIME (relativo al primer paquete) | ms desde el arranque |
| `alt` | ALTITUDE (relativa al arranque) | m |
| `p` | PRESSURE | kPa |
| `T` | TEMPERATURE | C |
| `ax` `ay` `az` | ACCEL_X/Y/Z | m/s^2 |
| `r` `pi` `y` | GYRO_ROLL/PITCH/YAW | grados |
| `v` | VELOCITY (positiva = descendiendo) | m/s |
| `rssi` `snr` | (los agrega el receptor) | dBm / dB |

Limitaciones actuales: la fase de vuelo (STATE) se estima en `lora_bridge.py` a partir
de altitud y velocidad; no hay medicion de bateria (VOLTAGE se muestra como `--`) ni
deteccion de carga secundaria; el yaw se integra del giroscopio y deriva con el tiempo
(el MPU6050 no tiene magnetometro).

## Pruebas automaticas

Modo LoRa (sin hardware: conversion del JSON, fases de vuelo, dashboard con lineas
del receptor simuladas):

```bash
python tests/test_lora_bridge.py
```

Modo simulador:

```bash
python tests/test_sistema.py
```

Levanta el dashboard en puertos de prueba (UDP 5105, HTTP 8010) y verifica formato,
vuelo completo, CSV, paquetes invalidos, API, funcionamiento sin internet, retardo y
rafaga de paquetes. Los resultados redactados para el PDR estan en `docs/pruebas_software.md`.
