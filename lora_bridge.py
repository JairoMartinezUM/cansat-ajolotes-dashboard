"""
Puente LoRa -> dashboard.

El receptor (CanSat_Receptor.ino) manda por USB una linea JSON por paquete, con
las claves cortas del transmisor mas "rssi" y "snr":

  {"id":"FIT2026","n":12,"t":12345,"alt":1.23,"p":101.325,"T":25.1,
   "ax":0.01,"ay":-0.02,"az":9.81,"r":0.5,"pi":-0.3,"y":12.0,"v":0.05,
   "rssi":-62,"snr":9.5}

Este modulo convierte esa linea al mismo dict que usa el resto del sistema
(telemetry_format.FIELDS), de modo que el dashboard y el CSV no cambian.

Lo que el firmware todavia no entrega se rellena asi:
  - STATE: se estima aqui a partir de altitud y velocidad (ver FlightStateEstimator).
  - VOLTAGE: -1 (el dashboard lo muestra como "--") salvo que el JSON traiga "volt".
  - SECONDARY_DIST / SECONDARY_DIR: -1 (no hay deteccion de carga secundaria aun).
"""

import json
import math

from telemetry_format import TEAM_ID

GRAVEDAD = 9.80665        # m/s^2
ACCEL_CAL_PAQUETES = 10   # paquetes iniciales en LAUNCH_PAD que fijan la escala del acelerometro
ACCEL_ESCALA_MIN, ACCEL_ESCALA_MAX = 0.90, 1.10   # fuera de este rango se ignora (no estaba quieto)

STATES = ["LAUNCH_PAD", "ASCENT", "FREEFALL", "AUTOGYRO_DESCENT", "LANDED"]

REQUIRED = ("n", "t", "alt", "p", "T", "ax", "ay", "az", "r", "pi", "y", "v")


class FlightStateEstimator:
    """Estima la fase de vuelo con reglas simples. Solo avanza, nunca retrocede.

    Velocidad positiva = descendiendo (igual que el resto del sistema).
    """

    RISE_START = -0.5        # m/s: subiendo mas rapido que esto -> ASCENT
    FREEFALL_V = 15.0        # m/s: bajando mas rapido que esto -> FREEFALL
    DESCENT_V = 2.0          # m/s: bajando mas rapido que esto -> esta descendiendo
    DROP_FROM_MAX = 3.0      # m: cuanto debe bajar desde el maximo para contar como descenso
    LANDED_ALT = 3.0         # m sobre el punto de lanzamiento
    LANDED_V = 0.5           # m/s
    LANDED_PACKETS = 3       # paquetes seguidos quietos para dar por aterrizado

    def __init__(self):
        self.state = "LAUNCH_PAD"
        self.max_alt = 0.0
        self.still = 0

    def _advance(self, new_state):
        if STATES.index(new_state) > STATES.index(self.state):
            self.state = new_state

    def update(self, alt, vel):
        self.max_alt = max(self.max_alt, alt)
        descending = vel > self.DESCENT_V and (self.max_alt - alt) > self.DROP_FROM_MAX

        if self.state == "LAUNCH_PAD" and vel < self.RISE_START and alt > 2.0:
            self._advance("ASCENT")

        if self.state in ("LAUNCH_PAD", "ASCENT") and descending:
            self._advance("FREEFALL" if vel > self.FREEFALL_V else "AUTOGYRO_DESCENT")
        elif self.state == "FREEFALL" and self.DESCENT_V < vel <= self.FREEFALL_V:
            self._advance("AUTOGYRO_DESCENT")

        # Aterrizaje: ya habia volado y ahora esta quieto cerca del suelo
        flew = self.state != "LAUNCH_PAD" and self.max_alt > self.LANDED_ALT
        if flew and alt < self.LANDED_ALT and abs(vel) < self.LANDED_V:
            self.still += 1
            if self.still >= self.LANDED_PACKETS:
                self._advance("LANDED")
        else:
            self.still = 0

        return self.state


def _num(raw, key):
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"campo '{key}' no es un numero valido: {value!r}")
    return float(value)


def _hms(seconds):
    s = max(0, int(seconds))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


class LoraBridge:
    """Convierte lineas JSON del receptor en paquetes de telemetria."""

    def __init__(self):
        self.reset()

    def reset(self):
        """Nueva mision: el tiempo de mision vuelve a 0 y la fase a LAUNCH_PAD."""
        self.estimator = FlightStateEstimator()
        self.t_ref = None        # ms del transmisor que corresponden a mission_time = 0
        self.last_t = None
        self.last_mission = 0.0
        self.accel_n = 0         # paquetes usados para calibrar la escala del acelerometro
        self.accel_sum = 0.0     # suma de |a| medida en reposo
        self.accel_scale = 1.0

    def _escala_aceleracion(self, ax, ay, az, state):
        """Escala del acelerometro: en reposo |a| debe ser 1 g.

        Con los primeros paquetes en LAUNCH_PAD (CanSat quieto en el punto de lanzamiento)
        se promedia |a| y se calcula el factor que la lleva a 9.80665 m/s^2. Si el factor
        sale fuera de 0.90-1.10 se ignora (el CanSat no estaba quieto)."""
        if state == "LAUNCH_PAD" and self.accel_n < ACCEL_CAL_PAQUETES:
            self.accel_n += 1
            self.accel_sum += math.sqrt(ax * ax + ay * ay + az * az)
            media = self.accel_sum / self.accel_n
            factor = GRAVEDAD / media if media > 0 else 1.0
            self.accel_scale = factor if ACCEL_ESCALA_MIN <= factor <= ACCEL_ESCALA_MAX else 1.0
        return self.accel_scale

    def convert(self, raw):
        if not isinstance(raw, dict):
            raise ValueError("el JSON no es un objeto")
        missing = [k for k in REQUIRED if k not in raw]
        if missing:
            raise ValueError(f"faltan campos: {', '.join(missing)}")

        t_ms = _num(raw, "t")
        if self.t_ref is None:
            self.t_ref = t_ms
        elif self.last_t is not None and t_ms < self.last_t:
            # El transmisor se reinicio: continuar el tiempo de mision sin saltos
            self.t_ref = t_ms - self.last_mission * 1000.0
        self.last_t = t_ms
        mission = (t_ms - self.t_ref) / 1000.0
        self.last_mission = mission

        alt = _num(raw, "alt")
        vel = _num(raw, "v")
        state = self.estimator.update(alt, vel)
        # En tierra no se registran valores negativos de altitud ni de velocidad (ruido del
        # barometro): se dejan en 0. Se hace despues del estimador porque este usa la
        # velocidad negativa para detectar el ascenso.
        if state in ("LAUNCH_PAD", "LANDED"):
            alt = max(0.0, alt)
            vel = max(0.0, vel)

        ax, ay, az = _num(raw, "ax"), _num(raw, "ay"), _num(raw, "az")
        k = self._escala_aceleracion(ax, ay, az, state)
        ax, ay, az = round(ax * k, 4), round(ay * k, 4), round(az * k, 4)

        team = str(raw.get("id", TEAM_ID)).replace(",", "")[:20] or TEAM_ID
        volt = _num(raw, "volt") if "volt" in raw else -1.0

        packet = {
            "TEAM_ID": team,
            "MISSION_TIME": _hms(mission),
            "PACKET_COUNT": int(_num(raw, "n")),
            "STATE": state,
            "ALTITUDE": alt,
            "PRESSURE": _num(raw, "p"),
            "TEMPERATURE": _num(raw, "T"),
            "VOLTAGE": volt,
            "ACCEL_X": ax,
            "ACCEL_Y": ay,
            "ACCEL_Z": az,
            "GYRO_ROLL": _num(raw, "r"),
            "GYRO_PITCH": _num(raw, "pi"),
            "GYRO_YAW": _num(raw, "y"),
            "VELOCITY": vel,
            "SECONDARY_DIST": -1.0,
            "SECONDARY_DIR": -1.0,
        }
        # Calidad del enlace (no forma parte del CSV, solo se muestra en el dashboard)
        packet["RSSI"] = _num(raw, "rssi") if "rssi" in raw else None
        packet["SNR"] = _num(raw, "snr") if "snr" in raw else None
        return packet

    def handle_line(self, line):
        """Linea de texto -> paquete. Lanza ValueError si no es un paquete valido."""
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON invalido: {e}") from e
        return self.convert(raw)


def list_ports():
    from serial.tools import list_ports as lp
    return [(p.device, p.description) for p in lp.comports()]


def serial_reader(port, baud, on_line, on_status, stop_event):
    """Lee lineas del puerto serie del receptor y reconecta si se desconecta.

    on_line(texto)            se llama por cada linea recibida
    on_status(conectado, msg) se llama al conectar / desconectar
    """
    import serial

    while not stop_event.is_set():
        ser = serial.Serial()
        ser.port, ser.baudrate, ser.timeout = port, baud, 1
        ser.dtr = False   # evita que abrir el puerto reinicie el ESP32
        ser.rts = False
        try:
            ser.open()
            on_status(True, "")
            while not stop_event.is_set():
                raw = ser.readline()
                if raw:
                    on_line(raw.decode("utf-8", "replace"))
        except (serial.SerialException, OSError) as e:
            on_status(False, str(e))
            stop_event.wait(2)
        finally:
            ser.close()
