"""
Pruebas automaticas del software de la estacion terrena (modo simulador).

Levanta dashboard.py en puertos de prueba (UDP 5105, HTTP 8010) para no chocar con
una sesion normal, y verifica el formato de telemetria, la recepcion por UDP, el
descarte de paquetes invalidos, el registro CSV, la API del dashboard y el
funcionamiento sin internet.

Uso:  python tests/test_sistema.py
"""

import csv
import io
import json
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import warnings
import urllib.request
from pathlib import Path

warnings.simplefilter("ignore", ResourceWarning)

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from flight_sim import FlightSimulator  # noqa: E402
from telemetry_format import FIELDS, decode, encode  # noqa: E402

UDP_PORT = 5105
HTTP_PORT = 8010
URL = f"http://127.0.0.1:{HTTP_PORT}"
FLIGHT_ORDER = ["LAUNCH_PAD", "ASCENT", "FREEFALL", "AUTOGYRO_DESCENT", "LANDED"]

server = None
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
logs_before = set()


def http(path, data=None):
    req = urllib.request.Request(URL + path, data=None if data is None else json.dumps(data).encode(),
                                 method="GET" if data is None else "POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read()


def state(since=0, epoch=-1):
    return json.loads(http(f"/api/state?since={since}&epoch={epoch}")[1])


def send(payload):
    sock.sendto(payload if isinstance(payload, bytes) else payload.encode(), ("127.0.0.1", UDP_PORT))


def valid_line(count=1):
    sim = FlightSimulator(seed=1)
    sim.step(1.0)
    packet = sim.build_packet()
    packet["PACKET_COUNT"] = count
    return encode(packet)


def wait_until(cond, timeout=15.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return False


def setUpModule():
    global server, logs_before
    logs_before = {p.name for p in BASE.glob("telemetry_log_*.csv")}
    server = subprocess.Popen(
        [sys.executable, str(BASE / "dashboard.py"), "--port", str(UDP_PORT), "--http-port", str(HTTP_PORT)],
        cwd=BASE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert wait_until(lambda: _up(), timeout=10), "El dashboard no arranco"


def _up():
    try:
        http("/api/state")
        return True
    except Exception:
        return False


def tearDownModule():
    server.terminate()
    server.wait(timeout=5)
    # borra los CSV que generaron las pruebas
    for p in BASE.glob("telemetry_log_*.csv"):
        if p.name not in logs_before:
            p.unlink()


class Pruebas(unittest.TestCase):
    def setUp(self):
        http("/api/reset", {})

    # ---- formato ----
    def test_01_formato_ida_y_vuelta(self):
        """encode -> decode conserva los 17 campos de un paquete."""
        sim = FlightSimulator(seed=7)
        for _ in range(30):
            sim.step(1.0)
            p = sim.build_packet()
            q = decode(encode(p))
            self.assertEqual(len(FIELDS), 17)
            self.assertEqual(list(q.keys()), FIELDS)
            for f in FIELDS:
                if isinstance(p[f], float):
                    self.assertAlmostEqual(p[f], q[f], places=1)
                else:
                    self.assertEqual(str(p[f]), str(q[f]))

    # ---- vuelo completo ----
    def test_02_vuelo_completo_sin_perdidas(self):
        """Un vuelo simulado completo llega sin perdidas ni duplicados y pasa por las 5 fases."""
        http("/api/sim/start", {"speed": 100})
        self.assertTrue(wait_until(lambda: not state()["sim_running"] and state()["total"] > 0, timeout=30))
        s = state()
        pk = s["packets"]
        counts = [p["PACKET_COUNT"] for p in pk]
        self.assertEqual(counts, list(range(1, len(pk) + 1)), "faltan o se repiten paquetes")
        phases = []
        for p in pk:
            if not phases or phases[-1] != p["STATE"]:
                phases.append(p["STATE"])
        self.assertEqual(phases, FLIGHT_ORDER)
        self.assertAlmostEqual(max(p["ALTITUDE"] for p in pk), 450.0, places=1)
        landed = [p for p in pk if p["STATE"] == "LANDED"]
        self.assertGreaterEqual(len(landed), 10, "menos de 10 s de transmision tras aterrizar")
        self.assertTrue(5.0 <= landed[-1]["SECONDARY_DIST"] <= 80.0)
        self.assertTrue(0.0 <= landed[-1]["SECONDARY_DIR"] <= 360.0)
        gyro = [p["VELOCITY"] for p in pk if p["STATE"] == "AUTOGYRO_DESCENT"][-5:]
        self.assertTrue(all(7.5 <= v <= 12.5 for v in gyro), gyro)
        print(f"\n   [vuelo] {len(pk)} paquetes, fases {phases}, aterrizaje con "
              f"{len(landed)} paquetes, carga secundaria a {landed[-1]['SECONDARY_DIST']} m / "
              f"{landed[-1]['SECONDARY_DIR']} grados")

    def test_03_csv_coincide_con_lo_recibido(self):
        """El CSV guardado tiene encabezado de 17 campos y una fila por paquete recibido."""
        http("/api/sim/start", {"speed": 100})
        self.assertTrue(wait_until(lambda: not state()["sim_running"] and state()["total"] > 0, timeout=30))
        s = state()
        rows = list(csv.reader(io.StringIO(http("/api/export")[1].decode())))
        self.assertEqual(rows[0], FIELDS)
        self.assertEqual(len(rows) - 1, s["total"])
        self.assertTrue(all(len(r) == 17 for r in rows))

    # ---- paquetes invalidos ----
    def test_04_descarta_paquetes_invalidos(self):
        """Los paquetes mal formados se descartan y el sistema sigue recibiendo."""
        malos = [b"", b"hola", "FIT2026,00:00:01,1", valid_line() + ",extra",
                 valid_line().replace("LAUNCH_PAD,0.0", "LAUNCH_PAD,abc"), b"\xff\xfe\xfa",
                 valid_line().replace(",1,", ",uno,", 1)]
        for m in malos:
            send(m)
        time.sleep(0.5)
        self.assertEqual(state()["total"], 0, "se acepto un paquete invalido")
        send(valid_line(1))
        self.assertTrue(wait_until(lambda: state()["total"] == 1))
        print(f"\n   [invalidos] {len(malos)} paquetes invalidos descartados; 1 valido posterior recibido")

    # ---- API ----
    def test_05_lectura_incremental(self):
        """La API entrega solo los paquetes nuevos (parametro since)."""
        for i in range(1, 11):
            send(valid_line(i))
        self.assertTrue(wait_until(lambda: state()["total"] == 10))
        e = state()["epoch"]
        self.assertEqual(len(state(0, e)["packets"]), 10)
        self.assertEqual(len(state(5, e)["packets"]), 5)
        self.assertEqual(len(state(10, e)["packets"]), 0)

    def test_06_reinicio_de_mision(self):
        """Reiniciar limpia los paquetes, cambia de epoca y abre un CSV nuevo."""
        send(valid_line(1))
        self.assertTrue(wait_until(lambda: state()["total"] == 1))
        antes = state()
        http("/api/reset", {})
        despues = state()
        self.assertEqual(despues["total"], 0)
        self.assertGreater(despues["epoch"], antes["epoch"])
        self.assertNotEqual(despues["log"], antes["log"])

    def test_07_rechaza_peticiones_incorrectas(self):
        """Velocidad fuera de rango y rutas inexistentes se rechazan; no se sale de /fonts."""
        with self.assertRaises(urllib.error.HTTPError) as c:
            http("/api/sim/start", {"speed": 1000})
        self.assertEqual(c.exception.code, 400)
        for ruta in ("/no-existe", "/fonts/../dashboard.py", "/fonts/no.ttf"):
            with self.assertRaises(urllib.error.HTTPError) as c:
                http(ruta)
            self.assertEqual(c.exception.code, 404, ruta)

    # ---- sin internet ----
    def test_08_funciona_sin_internet(self):
        """La pagina no depende de recursos externos: fuentes y logo se sirven localmente."""
        html = http("/")[1].decode()
        for externo in ("http://", "https://", "//cdn", "googleapis", "gstatic"):
            self.assertNotIn(externo, html)
        for recurso in ("/logo.png", "/fonts/Michroma-400.ttf", "/fonts/Exo2-400.ttf",
                        "/fonts/Exo2-600.ttf", "/fonts/Exo2-700.ttf"):
            status, body = http(recurso)
            self.assertEqual(status, 200)
            self.assertGreater(len(body), 1000)

    # ---- rendimiento ----
    def test_09_latencia(self):
        """Tiempo desde que se envia un paquete UDP hasta que esta disponible en la API."""
        tiempos = []
        for i in range(1, 21):
            t0 = time.perf_counter()
            send(valid_line(i))
            self.assertTrue(wait_until(lambda: state()["total"] == i, step=0.002))
            tiempos.append((time.perf_counter() - t0) * 1000)
        tiempos.sort()
        print(f"\n   [latencia] mediana {tiempos[len(tiempos)//2]:.0f} ms, maxima {tiempos[-1]:.0f} ms (20 paquetes)")
        self.assertLess(tiempos[-1], 1000)

    def test_10_rafaga_sin_perdidas(self):
        """1000 paquetes enviados sin pausa por UDP local llegan completos."""
        n = 1000
        linea = [valid_line(i) for i in range(1, n + 1)]
        t0 = time.perf_counter()
        for l in linea:
            send(l)
            time.sleep(0.0005)
        self.assertTrue(wait_until(lambda: state()["total"] >= n, timeout=30), f"llegaron {state()['total']}")
        dt = time.perf_counter() - t0
        pk = state()["packets"]
        self.assertEqual([p["PACKET_COUNT"] for p in pk], list(range(1, n + 1)))
        print(f"\n   [rafaga] {n} paquetes en {dt:.2f} s ({n/dt:.0f} paquetes/s), 0 perdidos")


if __name__ == "__main__":
    unittest.main(verbosity=2)
