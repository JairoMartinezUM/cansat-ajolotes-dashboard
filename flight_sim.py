"""
Simulador de vuelo del CanSat.

Genera un flujo de paquetes de telemetria que sigue el perfil de la mision
(ver CanSat.docx): ascenso a 50 m enganchado al dron, caida libre hasta
35 m, despliegue del autogiro y descenso controlado a 8-12 m/s, aterrizaje
y 15 s de transmision post-aterrizaje con deteccion de la carga secundaria.

Envia cada paquete por UDP a la estacion terrena (ground_station.py), igual
que lo haria un enlace de radio real. Cuando el firmware este listo, esta
misma logica de generacion de datos se puede reemplazar por lecturas reales
de sensores sin tocar el resto del sistema (el formato de paquete y el
receptor de la estacion terrena no cambian).
"""

import argparse
import random
import socket
import time

from telemetry_format import encode, TEAM_ID

# --- Parametros de la mision (ver limites de diseno en CanSat.docx) ---
LAUNCH_ALTITUDE = 50.0        # m
AUTOGYRO_ALTITUDE = 35.0      # m
ASCENT_RATE = 2.5             # m/s, velocidad de ascenso con el dron
FREEFALL_TERMINAL_V = 35.0    # m/s
AUTOGYRO_V_MIN = 8.0          # m/s
AUTOGYRO_V_MAX = 12.0         # m/s
POST_LANDING_TIME = 15.0      # s (el requisito minimo son 10 s)

SEA_LEVEL_PRESSURE = 101.325  # kPa
GROUND_TEMPERATURE = 25.0     # C
LAPSE_RATE = 6.5 / 1000       # C por metro

PACKET_RATE_HZ = 1.0


class FlightSimulator:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.state = "LAUNCH_PAD"
        self.altitude = 0.0
        self.velocity = 0.0
        self.packet_count = 0
        self.mission_time = 0.0
        self.state_entered_at = 0.0
        self.voltage = 9.0
        self.autogyro_target_v = self.rng.uniform(AUTOGYRO_V_MIN, AUTOGYRO_V_MAX)
        self.yaw = 0.0
        self.landed_at = None
        self.secondary_dist = round(self.rng.uniform(5.0, 80.0), 1)
        self.secondary_dir = round(self.rng.uniform(0.0, 360.0), 1)

    def _set_state(self, new_state):
        self.state = new_state
        self.state_entered_at = self.mission_time

    def step(self, dt):
        self.mission_time += dt

        if self.state == "LAUNCH_PAD":
            if self.mission_time > 2.0:
                self._set_state("ASCENT")

        elif self.state == "ASCENT":
            self.velocity = -ASCENT_RATE
            self.altitude += ASCENT_RATE * dt
            if self.altitude >= LAUNCH_ALTITUDE:
                self.altitude = LAUNCH_ALTITUDE
                self._set_state("FREEFALL")

        elif self.state == "FREEFALL":
            tau = 2.0
            self.velocity += (FREEFALL_TERMINAL_V - self.velocity) / tau * dt
            self.altitude -= self.velocity * dt
            if self.altitude <= AUTOGYRO_ALTITUDE:
                self.altitude = AUTOGYRO_ALTITUDE
                self._set_state("AUTOGYRO_DESCENT")

        elif self.state == "AUTOGYRO_DESCENT":
            tau = 1.5
            self.velocity += (self.autogyro_target_v - self.velocity) / tau * dt
            self.altitude -= self.velocity * dt
            self.yaw = (self.yaw + 320 * dt) % 360
            if self.altitude <= 0:
                self.altitude = 0.0
                self.velocity = 0.0
                self._set_state("LANDED")
                self.landed_at = self.mission_time

        elif self.state == "LANDED":
            pass

        self.voltage = max(6.5, self.voltage - self.rng.uniform(0.0, 0.0005))

    def is_done(self):
        return self.state == "LANDED" and (self.mission_time - self.landed_at) >= POST_LANDING_TIME

    def build_packet(self):
        self.packet_count += 1

        pressure = SEA_LEVEL_PRESSURE * (1 - 2.25577e-5 * self.altitude) ** 5.25588
        pressure += self.rng.gauss(0, 0.02)

        temperature = GROUND_TEMPERATURE - LAPSE_RATE * self.altitude
        temperature += self.rng.gauss(0, 0.15)

        time_in_state = self.mission_time - self.state_entered_at
        accel_z = 9.81 + self.rng.gauss(0, 0.05)
        if self.state == "FREEFALL":
            accel_z = self.rng.gauss(0.5, 0.3)
        elif self.state == "AUTOGYRO_DESCENT" and time_in_state < 0.5:
            accel_z = self.rng.gauss(15.0, 2.0)  # tiron mecanico al desplegar

        roll = self.rng.gauss(0, 2.0)
        pitch = self.rng.gauss(0, 2.0)

        t = self.mission_time
        mission_time_str = f"{int(t // 3600):02d}:{int((t % 3600) // 60):02d}:{int(t % 60):02d}"

        in_landed = self.state == "LANDED"
        secondary_dist = self.secondary_dist if in_landed else -1.0
        secondary_dir = self.secondary_dir if in_landed else -1.0

        return {
            "TEAM_ID": TEAM_ID,
            "MISSION_TIME": mission_time_str,
            "PACKET_COUNT": self.packet_count,
            "STATE": self.state,
            "ALTITUDE": self.altitude,
            "PRESSURE": pressure,
            "TEMPERATURE": temperature,
            "VOLTAGE": self.voltage,
            "ACCEL_X": self.rng.gauss(0, 0.1),
            "ACCEL_Y": self.rng.gauss(0, 0.1),
            "ACCEL_Z": accel_z,
            "GYRO_ROLL": roll,
            "GYRO_PITCH": pitch,
            "GYRO_YAW": self.yaw,
            "VELOCITY": self.velocity,
            "SECONDARY_DIST": secondary_dist,
            "SECONDARY_DIR": secondary_dir,
        }


def main():
    parser = argparse.ArgumentParser(description="Simulador de vuelo del CanSat")
    parser.add_argument("--host", default="127.0.0.1", help="IP de la estacion terrena")
    parser.add_argument("--port", type=int, default=5005, help="Puerto UDP de la estacion terrena")
    parser.add_argument("--rate", type=float, default=PACKET_RATE_HZ, help="Paquetes por segundo")
    parser.add_argument("--speed", type=float, default=1.0, help="Multiplicador de velocidad (10 = 10x mas rapido que un vuelo real)")
    parser.add_argument("--seed", type=int, default=None, help="Semilla aleatoria, para vuelos repetibles")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sim = FlightSimulator(seed=args.seed)

    dt = 1.0 / args.rate
    print(f"Simulando vuelo -> {args.host}:{args.port}  (rate={args.rate} Hz, speed={args.speed}x)")

    while not sim.is_done():
        sim.step(dt)
        packet = sim.build_packet()
        line = encode(packet)
        sock.sendto(line.encode("utf-8"), (args.host, args.port))
        print(line)
        time.sleep(dt / args.speed)

    print("Vuelo terminado.")


if __name__ == "__main__":
    main()
