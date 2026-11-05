"""
Estacion terrena.

Escucha paquetes de telemetria por UDP (enviados por flight_sim.py, o mas
adelante por el radio real del CanSat), los guarda en un CSV con timestamp
y los grafica en tiempo real: altitud, velocidad, temperatura y presion.
"""

import argparse
import csv
import socket
import threading
import time
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.animation as animation

from telemetry_format import decode, FIELDS

packets = []
packets_lock = threading.Lock()
log_path = None


def listener_thread(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    print(f"Estacion terrena escuchando en {host}:{port}")

    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)
        while True:
            data, _ = sock.recvfrom(4096)
            line = data.decode("utf-8")
            try:
                packet = decode(line)
            except ValueError as e:
                print(f"Paquete invalido, descartado: {e}")
                continue

            with packets_lock:
                packets.append(packet)

            writer.writerow([packet[field] for field in FIELDS])
            f.flush()


def make_plot():
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    fig.suptitle("CanSat - Estacion Terrena (simulador)")
    ax_alt, ax_vel, ax_temp, ax_pres = axes.flatten()

    ax_alt.set_ylabel("Altitud (m)")
    ax_vel.set_ylabel("Velocidad (m/s)")
    ax_temp.set_ylabel("Temperatura (C)")
    ax_pres.set_ylabel("Presion (kPa)")
    for ax in axes.flatten():
        ax.set_xlabel("Tiempo de mision (s)")
        ax.grid(True, alpha=0.3)

    status_text = fig.text(0.5, 0.955, "", ha="center", va="top", fontsize=10)

    def update(_frame):
        with packets_lock:
            snapshot = list(packets)

        if not snapshot:
            return

        t = [i for i in range(len(snapshot))]
        alt = [p["ALTITUDE"] for p in snapshot]
        vel = [p["VELOCITY"] for p in snapshot]
        temp = [p["TEMPERATURE"] for p in snapshot]
        pres = [p["PRESSURE"] for p in snapshot]

        for ax in axes.flatten():
            ax.cla()
            ax.grid(True, alpha=0.3)
            ax.set_xlabel("Paquete #")

        ax_alt.plot(t, alt, color="tab:blue")
        ax_alt.set_ylabel("Altitud (m)")
        ax_vel.plot(t, vel, color="tab:orange")
        ax_vel.set_ylabel("Velocidad (m/s)")
        ax_temp.plot(t, temp, color="tab:red")
        ax_temp.set_ylabel("Temperatura (C)")
        ax_pres.plot(t, pres, color="tab:green")
        ax_pres.set_ylabel("Presion (kPa)")

        last = snapshot[-1]
        status = (
            f"Estado: {last['STATE']}   |   Tiempo: {last['MISSION_TIME']}   |   "
            f"Paquete #{last['PACKET_COUNT']}   |   Bateria: {last['VOLTAGE']:.2f} V"
        )
        if last["STATE"] == "LANDED":
            status += (
                f"   |   Carga secundaria: {last['SECONDARY_DIST']:.1f} m "
                f"a {last['SECONDARY_DIR']:.0f} grados"
            )
        status_text.set_text(status)

    return fig, update


def main():
    global log_path

    parser = argparse.ArgumentParser(description="Estacion terrena del CanSat")
    parser.add_argument("--host", default="127.0.0.1", help="IP donde escuchar")
    parser.add_argument("--port", type=int, default=5005, help="Puerto UDP donde escuchar")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = f"telemetry_log_{timestamp}.csv"

    t = threading.Thread(target=listener_thread, args=(args.host, args.port), daemon=True)
    t.start()

    fig, update = make_plot()
    ani = animation.FuncAnimation(fig, update, interval=500, cache_frame_data=False)
    plt.tight_layout(rect=(0, 0, 1, 0.95))
    plt.show()

    print(f"Log guardado en {log_path}")


if __name__ == "__main__":
    main()
