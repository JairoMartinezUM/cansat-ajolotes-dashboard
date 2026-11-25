"""
Estacion terrena con interfaz web.

Igual que ground_station.py, escucha paquetes de telemetria por UDP y los
guarda en un CSV, pero en vez de una ventana de matplotlib sirve un dashboard
en http://localhost:8000 (ver dashboard.html). Desde el dashboard tambien se
puede iniciar/detener el simulador de vuelo y exportar el CSV.

Solo usa la libreria estandar de Python.
"""

import argparse
import csv
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from lora_bridge import LoraBridge, STATES
from telemetry_format import decode, FIELDS, CSV_FIELDS

BASE_DIR = Path(__file__).resolve().parent
# Carpeta de los CSV. En Docker se monta como volumen (CANSAT_LOG_DIR=/data).
LOG_DIR = Path(os.environ.get("CANSAT_LOG_DIR", BASE_DIR))

lock = threading.Lock()
packets = []
epoch = 0                 # cambia cada vez que se reinicia la mision
log_path = None
sim_process = None
udp_port = 5005

# Modo LoRa: el dashboard se alimenta del receptor por puerto serie (--serial COMx).
# `lora` es None en modo simulador.
bridge = LoraBridge()
lora = None
EXTRA_FIELDS = ["RSSI", "SNR"]   # columnas extra del CSV, solo en modo LoRa (calidad del enlace)


def csv_header():
    return CSV_FIELDS + (EXTRA_FIELDS if lora else [])


def new_log():
    """Empieza una mision nueva: limpia paquetes y abre un CSV nuevo."""
    global log_path, epoch
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"telemetry_log_{stamp}.csv"
    n = 1
    while log_path.exists():  # no sobrescribir si hay dos misiones en el mismo segundo
        log_path = LOG_DIR / f"telemetry_log_{stamp}_{n}.csv"
        n += 1
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(csv_header())
    packets.clear()
    bridge.reset()
    epoch += 1


def _store(packet):
    """Guarda un paquete en memoria y en el CSV. Llamar con `lock` tomado."""
    packets.append(packet)
    row = [packet[field] for field in CSV_FIELDS]
    if lora:
        row += [packet.get(field) for field in EXTRA_FIELDS]
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)


def listener_thread(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    print(f"Escuchando telemetria UDP en {host}:{port}")

    while True:
        data, _ = sock.recvfrom(4096)
        try:
            packet = decode(data.decode("utf-8"))
        except ValueError as e:
            print(f"Paquete invalido, descartado: {e}")
            continue

        with lock:
            _store(packet)


def on_lora_line(line):
    """Una linea del receptor LoRa: JSON de telemetria o mensaje de diagnostico (#...)."""
    line = line.strip()
    if not line:
        return
    if not line.startswith("{"):
        print(f"[receptor] {line}")
        return

    with lock:
        try:
            packet = bridge.handle_line(line)
        except ValueError as e:
            lora["errors"] += 1
            print(f"Paquete LoRa invalido, descartado: {e}")
            return
        _store(packet)
        lora["packets"] += 1
        lora["last_rx"] = time.time()
        lora["rssi"] = packet["RSSI"]
        lora["snr"] = packet["SNR"]


def on_lora_status(connected, message):
    with lock:
        if connected != lora["connected"]:
            print(f"Receptor {lora['port']}: " +
                  ("conectado" if connected else f"desconectado ({message}); reintentando..."))
        lora["connected"] = connected
        lora["error"] = message


def sim_running():
    return sim_process is not None and sim_process.poll() is None


def start_sim(speed):
    global sim_process
    stop_sim()
    with lock:
        new_log()
    sim_process = subprocess.Popen(
        [sys.executable, str(BASE_DIR / "flight_sim.py"),
         "--speed", str(speed), "--port", str(udp_port)],
        cwd=BASE_DIR,
    )


def stop_sim():
    global sim_process
    if sim_running():
        sim_process.terminate()
        sim_process.wait(timeout=5)
    sim_process = None


METRICS = [  # (nombre, campo del paquete, ayuda)
    ("cansat_altitude_meters", "ALTITUDE", "Altitud sobre el punto de lanzamiento"),
    ("cansat_velocity_mps", "VELOCITY", "Velocidad (positiva = descendiendo)"),
    ("cansat_temperature_celsius", "TEMPERATURE", "Temperatura"),
    ("cansat_pressure_kpa", "PRESSURE", "Presion"),
    ("cansat_voltage_volts", "VOLTAGE", "Voltaje de la bateria (-1 = sin medicion)"),
    ("cansat_accel_x_ms2", "ACCEL_X", "Aceleracion en X"),
    ("cansat_accel_y_ms2", "ACCEL_Y", "Aceleracion en Y"),
    ("cansat_accel_z_ms2", "ACCEL_Z", "Aceleracion en Z"),
]


def build_metrics():
    """Metricas en formato de texto de Prometheus (sin librerias externas)."""
    with lock:
        total = len(packets)
        last = packets[-1] if packets else None
        running = sim_running()
        current_epoch = epoch
        rssi = lora["rssi"] if lora else None

    out = []

    def gauge(name, help_text, value, labels=""):
        out.append(f"# HELP {name} {help_text}")
        out.append(f"# TYPE {name} gauge")
        out.append(f"{name}{labels} {value}")

    gauge("cansat_packets_received", "Paquetes recibidos en la mision actual", total)
    gauge("cansat_mission_epoch", "Se incrementa cada vez que se reinicia la mision", current_epoch)
    gauge("cansat_sim_running", "1 si el simulador de vuelo esta corriendo", int(running))
    if rssi is not None:
        gauge("cansat_lora_rssi_dbm", "RSSI del ultimo paquete LoRa", rssi)
    if last:
        for name, field, help_text in METRICS:
            gauge(name, help_text, last[field])
        out.append("# HELP cansat_flight_state Fase de vuelo actual (1 = activa)")
        out.append("# TYPE cansat_flight_state gauge")
        for st in STATES:
            out.append(f'cansat_flight_state{{state="{st}"}} {int(last["STATE"] == st)}')
    return "\n".join(out) + "\n"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # sin ruido en la consola

    def _send(self, code, body, content_type="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)

        if url.path in ("/", "/index.html"):
            html = (BASE_DIR / "dashboard.html").read_text(encoding="utf-8")
            self._send(200, html, "text/html; charset=utf-8")

        elif url.path == "/logo.png":
            self._send(200, (BASE_DIR / "Logo Ajolotes.png").read_bytes(), "image/png",
                       {"Cache-Control": "max-age=3600"})

        elif url.path.startswith("/fonts/"):
            font = (BASE_DIR / "fonts" / Path(url.path).name)
            if not font.is_file():
                return self._send(404, {"error": "no encontrado"})
            self._send(200, font.read_bytes(), "font/ttf",
                       {"Cache-Control": "max-age=86400"})

        elif url.path == "/api/state":
            since = int(parse_qs(url.query).get("since", ["0"])[0])
            client_epoch = int(parse_qs(url.query).get("epoch", ["-1"])[0])
            with lock:
                if client_epoch != epoch:
                    since = 0
                new = packets[since:]
                body = {
                    "epoch": epoch,
                    "total": len(packets),
                    "packets": new,
                    "sim_running": sim_running(),
                    "log": log_path.name,
                    "mode": "lora" if lora else "sim",
                    "lora": None if not lora else {
                        **lora,
                        "age": None if lora["last_rx"] is None else time.time() - lora["last_rx"],
                    },
                }
            self._send(200, body)

        elif url.path == "/metrics":
            self._send(200, build_metrics(), "text/plain; version=0.0.4; charset=utf-8")

        elif url.path == "/api/export":
            with lock:
                data = log_path.read_bytes()
            self._send(200, data, "text/csv", {
                "Content-Disposition": f'attachment; filename="{log_path.name}"'})

        else:
            self._send(404, {"error": "no encontrado"})

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "JSON invalido"})

        if lora and url.path.startswith("/api/sim/"):
            return self._send(409, {"error": "modo LoRa: el simulador esta deshabilitado"})

        if url.path == "/api/sim/start":
            speed = float(body.get("speed", 1))
            if not 0.1 <= speed <= 100:
                return self._send(400, {"error": "speed fuera de rango"})
            start_sim(speed)
            self._send(200, {"ok": True})

        elif url.path == "/api/sim/stop":
            stop_sim()
            self._send(200, {"ok": True})

        elif url.path == "/api/reset":
            stop_sim()
            with lock:
                new_log()
            self._send(200, {"ok": True})

        else:
            self._send(404, {"error": "no encontrado"})


def _ips_locales():
    """Direcciones IPv4 de esta computadora en sus redes (no se envia ningun paquete).

    Pueden salir varias (WiFi, Ethernet, VPN...): el celular debe usar la de su misma red."""
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith(("127.", "169.254.")) and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips


def main():
    global udp_port, lora

    parser = argparse.ArgumentParser(description="Dashboard web de la estacion terrena del CanSat")
    parser.add_argument("--host", default=None,
                        help="IP donde escuchar UDP y servir HTTP (por defecto: la pagina se sirve "
                             "en toda la red local y la telemetria UDP solo en 127.0.0.1)")
    parser.add_argument("--local", action="store_true",
                        help="Sirve el dashboard solo en esta computadora (sin acceso desde el celular)")
    parser.add_argument("--lan", action="store_true", help=argparse.SUPPRESS)   # antiguo: ya es el valor por defecto
    parser.add_argument("--port", type=int, default=5005, help="Puerto UDP de telemetria")
    parser.add_argument("--http-port", type=int, default=8000, help="Puerto del dashboard web")
    parser.add_argument("--serial", metavar="COMx",
                        help="Puerto serie del receptor LoRa (ej. COM7). Activa el modo LoRa")
    parser.add_argument("--baud", type=int, default=115200, help="Baudios del receptor LoRa")
    parser.add_argument("--list-ports", action="store_true", help="Lista los puertos serie y sale")
    args = parser.parse_args()
    udp_port = args.port
    # La pagina se abre a la red local por defecto (para verla desde el celular); --local lo evita.
    http_host = args.host or ("127.0.0.1" if args.local else "0.0.0.0")
    udp_host = args.host or "127.0.0.1"

    if args.list_ports:
        from lora_bridge import list_ports
        for device, desc in list_ports():
            print(f"{device}  {desc}")
        return

    if args.serial:   # `lora` antes de new_log(): el CSV lleva columnas extra en modo LoRa
        lora = {"port": args.serial, "baud": args.baud, "connected": False, "error": "",
                "packets": 0, "errors": 0, "last_rx": None, "rssi": None, "snr": None}
    new_log()

    if args.serial:
        from lora_bridge import serial_reader
        threading.Thread(
            target=serial_reader,
            args=(args.serial, args.baud, on_lora_line, on_lora_status, threading.Event()),
            daemon=True,
        ).start()
        print(f"Modo LoRa: leyendo el receptor en {args.serial} a {args.baud} baudios "
              "(cierra el Monitor Serie del Arduino IDE, usa el mismo puerto)")
    else:
        threading.Thread(target=listener_thread, args=(udp_host, args.port), daemon=True).start()

    server = ThreadingHTTPServer((http_host, args.http_port), Handler)
    if http_host == "0.0.0.0":
        print(f"Dashboard en esta computadora: http://localhost:{args.http_port}")
        print("Desde el celular (mismo WiFi), usa la direccion de tu red WiFi:")
        for ip in _ips_locales():
            print(f"   http://{ip}:{args.http_port}")
        print("AVISO: cualquiera en esa red puede ver el dashboard y usar Reiniciar / Exportar.")
    else:
        print(f"Dashboard en http://{http_host}:{args.http_port}")
        if http_host in ("127.0.0.1", "localhost"):
            print("Solo accesible desde esta computadora (quita --local para verlo desde el celular)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_sim()
        print(f"Log guardado en {log_path}")


if __name__ == "__main__":
    main()
