"""
Formato del paquete de telemetria del CanSat.

Sigue el estilo estandar usado en competencias CanSat (linea CSV de texto plano),
para que sea facil de leer por humanos y de parsear tanto en el simulador como
en el firmware real cuando este listo.

Fases de vuelo (STATE), segun el CONOPS de la mision:
  LAUNCH_PAD        - en tierra, antes del ascenso
  ASCENT            - subiendo enganchado al dron (0 -> 450 m)
  FREEFALL          - caida libre tras el desacople (450 -> 200 m)
  AUTOGYRO_DESCENT  - autogiro desplegado, descenso controlado (200 -> 0 m)
  LANDED            - en tierra, transmitiendo y buscando la carga secundaria
"""

FIELDS = [
    "TEAM_ID",
    "MISSION_TIME",     # HH:MM:SS
    "PACKET_COUNT",
    "STATE",
    "ALTITUDE",         # m sobre el punto de lanzamiento
    "PRESSURE",         # kPa
    "TEMPERATURE",      # C
    "VOLTAGE",          # V (bateria 9V)
    "ACCEL_X",          # m/s^2
    "ACCEL_Y",
    "ACCEL_Z",
    "GYRO_ROLL",        # deg
    "GYRO_PITCH",       # deg
    "GYRO_YAW",         # deg (gira rapido durante AUTOGYRO_DESCENT)
    "VELOCITY",         # m/s, positivo = descendiendo
    "SECONDARY_DIST",   # m, distancia a la carga secundaria (solo valido en LANDED)
    "SECONDARY_DIR",    # deg, rumbo a la carga secundaria (solo valido en LANDED)
]

TEAM_ID = "FIT2026"


def encode(packet: dict) -> str:
    """Convierte un dict de telemetria a una linea CSV lista para transmitir."""
    values = []
    for field in FIELDS:
        value = packet.get(field, "")
        if isinstance(value, float):
            values.append(f"{value:.2f}")
        else:
            values.append(str(value))
    return ",".join(values)


def decode(line: str) -> dict:
    """Convierte una linea CSV recibida de vuelta a un dict de telemetria."""
    parts = line.strip().split(",")
    if len(parts) != len(FIELDS):
        raise ValueError(f"Se esperaban {len(FIELDS)} campos, llegaron {len(parts)}: {line!r}")

    packet = dict(zip(FIELDS, parts))

    packet["PACKET_COUNT"] = int(packet["PACKET_COUNT"])
    for field in (
        "ALTITUDE", "PRESSURE", "TEMPERATURE", "VOLTAGE",
        "ACCEL_X", "ACCEL_Y", "ACCEL_Z",
        "GYRO_ROLL", "GYRO_PITCH", "GYRO_YAW",
        "VELOCITY", "SECONDARY_DIST", "SECONDARY_DIR",
    ):
        packet[field] = float(packet[field])

    return packet
