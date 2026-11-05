"""
Pruebas del modo LoRa: conversion del JSON del receptor a paquetes de telemetria,
estimacion de la fase de vuelo, y el dashboard alimentado por el puerto serie.

No necesita hardware: las lineas del receptor se simulan.

Uso:  python tests/test_lora_bridge.py
"""

import csv
import json
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
import warnings
from pathlib import Path

warnings.simplefilter("ignore", ResourceWarning)

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import dashboard  # noqa: E402
from flight_sim import FlightSimulator  # noqa: E402
from lora_bridge import STATES, LoraBridge  # noqa: E402
from telemetry_format import FIELDS  # noqa: E402

HTTP_PORT = 8011


def raw_packet(n=1, t=1000, alt=0.0, v=0.0, **extra):
    """Paquete tal como lo entrega el receptor."""
    raw = {"id": "FIT2026", "n": n, "t": t, "alt": alt, "p": 101.325, "T": 25.0,
           "ax": 0.1, "ay": -0.2, "az": 9.8, "r": 1.5, "pi": -2.5, "y": 30.0, "v": v,
           "rssi": -62, "snr": 9.5}
    raw.update(extra)
    return raw


class TestConversion(unittest.TestCase):
    def test_campos(self):
        p = LoraBridge().handle_line(json.dumps(raw_packet(n=7, t=5000, alt=12.34, v=-1.0)))
        self.assertEqual(p["PACKET_COUNT"], 7)
        self.assertEqual(p["TEAM_ID"], "FIT2026")
        self.assertAlmostEqual(p["ALTITUDE"], 12.34)
        self.assertAlmostEqual(p["PRESSURE"], 101.325)
        self.assertAlmostEqual(p["TEMPERATURE"], 25.0)
        self.assertAlmostEqual(p["ACCEL_Z"], 9.8)
        self.assertAlmostEqual(p["GYRO_ROLL"], 1.5)
        self.assertAlmostEqual(p["GYRO_PITCH"], -2.5)
        self.assertAlmostEqual(p["GYRO_YAW"], 30.0)
        self.assertAlmostEqual(p["VELOCITY"], -1.0)
        self.assertEqual(p["RSSI"], -62)
        self.assertEqual(p["SNR"], 9.5)

    def test_tiene_todos_los_campos_del_csv(self):
        p = LoraBridge().convert(raw_packet())
        for field in FIELDS:
            self.assertIn(field, p)

    def test_sin_voltaje_ni_carga_secundaria(self):
        p = LoraBridge().convert(raw_packet())
        self.assertEqual(p["VOLTAGE"], -1.0)
        self.assertEqual(p["SECONDARY_DIST"], -1.0)
        self.assertEqual(LoraBridge().convert(raw_packet(volt=8.7))["VOLTAGE"], 8.7)

    def test_sin_rssi(self):
        raw = raw_packet()
        del raw["rssi"], raw["snr"]
        p = LoraBridge().convert(raw)
        self.assertIsNone(p["RSSI"])
        self.assertIsNone(p["SNR"])

    def test_invalidos(self):
        b = LoraBridge()
        bad = [
            "no es json",
            "[1, 2, 3]",
            json.dumps({"n": 1}),                                  # faltan campos
            json.dumps(raw_packet(alt="alto")),                    # no numerico
            json.dumps(raw_packet(alt=True)),                      # booleano
            json.dumps(raw_packet()).replace('"alt": 0.0', '"alt": NaN'),
            "",
        ]
        for line in bad:
            with self.subTest(line=line):
                with self.assertRaises(ValueError):
                    b.handle_line(line)

    def test_tiempo_de_mision_relativo(self):
        b = LoraBridge()
        self.assertEqual(b.convert(raw_packet(t=50_000))["MISSION_TIME"], "00:00:00")
        self.assertEqual(b.convert(raw_packet(t=50_000 + 65_000))["MISSION_TIME"], "00:01:05")

    def test_reinicio_del_transmisor_no_regresa_el_tiempo(self):
        b = LoraBridge()
        b.convert(raw_packet(t=1_000))
        b.convert(raw_packet(t=11_000))                         # 10 s de mision
        p = b.convert(raw_packet(t=500))                        # el transmisor se reinicio
        self.assertEqual(p["MISSION_TIME"], "00:00:10")
        p = b.convert(raw_packet(t=3_500))
        self.assertEqual(p["MISSION_TIME"], "00:00:13")

    def test_reset(self):
        b = LoraBridge()
        b.convert(raw_packet(t=1_000))
        b.convert(raw_packet(t=9_000))
        b.reset()
        self.assertEqual(b.convert(raw_packet(t=20_000))["MISSION_TIME"], "00:00:00")


class TestEstadoDeVuelo(unittest.TestCase):
    def test_en_reposo_se_queda_en_plataforma(self):
        import random
        rng = random.Random(3)
        b = LoraBridge()
        for i in range(300):
            p = b.convert(raw_packet(n=i, t=i * 1000, alt=rng.gauss(0, 0.2), v=rng.gauss(0, 0.3)))
            self.assertEqual(p["STATE"], "LAUNCH_PAD")

    def test_vuelo_completo_del_simulador(self):
        """Los paquetes del simulador, pasados como si vinieran por LoRa, recorren las 5 fases."""
        sim = FlightSimulator(seed=1)
        b = LoraBridge()
        seen = []
        while not sim.is_done():
            sim.step(1.0)
            s = sim.build_packet()
            p = b.convert(raw_packet(n=s["PACKET_COUNT"], t=sim.mission_time * 1000,
                                     alt=s["ALTITUDE"], v=s["VELOCITY"]))
            seen.append(p["STATE"])

        order = [STATES.index(s) for s in seen]
        self.assertEqual(order, sorted(order), "las fases no pueden retroceder")
        self.assertEqual(sorted(set(seen), key=STATES.index), STATES)
        self.assertEqual(seen[-1], "LANDED")


class TestDashboardModoLora(unittest.TestCase):
    """El dashboard (en el mismo proceso) alimentado con lineas del receptor."""

    def setUp(self):
        self.logs_before = {p.name for p in BASE.glob("telemetry_log_*.csv")}
        dashboard.lora = {"port": "COMTEST", "baud": 115200, "connected": True, "error": "",
                          "packets": 0, "errors": 0, "last_rx": None, "rssi": None, "snr": None}
        dashboard.new_log()

    def tearDown(self):
        dashboard.lora = None
        for p in BASE.glob("telemetry_log_*.csv"):
            if p.name not in self.logs_before:
                p.unlink()

    def test_lineas_del_receptor(self):
        dashboard.on_lora_line("# LoRa OK, esperando paquetes")        # diagnostico: se ignora
        dashboard.on_lora_line("")
        dashboard.on_lora_line(json.dumps(raw_packet(n=1, t=1000, alt=1.0)))
        dashboard.on_lora_line("{roto")                                 # invalido: se descarta
        dashboard.on_lora_line(json.dumps(raw_packet(n=2, t=2000, alt=2.0)))

        self.assertEqual([p["PACKET_COUNT"] for p in dashboard.packets], [1, 2])
        self.assertEqual(dashboard.lora["packets"], 2)
        self.assertEqual(dashboard.lora["errors"], 1)
        self.assertEqual(dashboard.lora["rssi"], -62)

        with open(dashboard.log_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], FIELDS)
        self.assertEqual(len(rows), 3)                                  # encabezado + 2 paquetes
        self.assertEqual(rows[2][FIELDS.index("PACKET_COUNT")], "2")

    def test_reiniciar_mision_reinicia_el_tiempo(self):
        dashboard.on_lora_line(json.dumps(raw_packet(n=1, t=1000)))
        dashboard.on_lora_line(json.dumps(raw_packet(n=2, t=9000)))
        self.assertEqual(dashboard.packets[-1]["MISSION_TIME"], "00:00:08")
        dashboard.new_log()
        self.assertEqual(dashboard.packets, [])
        dashboard.on_lora_line(json.dumps(raw_packet(n=3, t=20_000)))
        self.assertEqual(dashboard.packets[-1]["MISSION_TIME"], "00:00:00")


class TestServidorModoLora(unittest.TestCase):
    """dashboard.py --serial con un puerto que no existe: sigue vivo y reporta el estado."""

    @classmethod
    def setUpClass(cls):
        cls.logs_before = {p.name for p in BASE.glob("telemetry_log_*.csv")}
        cls.server = subprocess.Popen(
            [sys.executable, str(BASE / "dashboard.py"), "--serial", "COM_NO_EXISTE",
             "--http-port", str(HTTP_PORT)],
            cwd=BASE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        end = time.time() + 15
        while time.time() < end:
            try:
                cls.get("/api/state")
                return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("el dashboard no arranco")

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=5)
        for p in BASE.glob("telemetry_log_*.csv"):
            if p.name not in cls.logs_before:
                p.unlink()

    @staticmethod
    def get(path):
        with urllib.request.urlopen(f"http://127.0.0.1:{HTTP_PORT}{path}", timeout=5) as r:
            return json.loads(r.read())

    def test_estado(self):
        s = self.get("/api/state")
        self.assertEqual(s["mode"], "lora")
        self.assertEqual(s["lora"]["port"], "COM_NO_EXISTE")
        self.assertFalse(s["lora"]["connected"])
        self.assertIsNone(s["lora"]["age"])
        self.assertEqual(s["packets"], [])

    def test_simulador_deshabilitado(self):
        req = urllib.request.Request(f"http://127.0.0.1:{HTTP_PORT}/api/sim/start",
                                     data=b'{"speed": 1}', method="POST",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 409)


if __name__ == "__main__":
    unittest.main(verbosity=2)
