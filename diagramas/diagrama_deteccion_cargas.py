"""
Diagrama de como la carga primaria detecta a la carga secundaria despues del
aterrizaje y calcula la distancia entre ambas (diapositiva 6 del PDR, punto 4).

Basado en los componentes de las diapositivas 10, 12 y 13 (GPS NEO-6M + LoRa en
ambas cargas) y en los campos SECONDARY_DIST / SECONDARY_DIR del formato de
telemetria (telemetry_format.py).

Uso:  python diagrama_deteccion_cargas.py
Salida: diagrama_deteccion_cargas.png / .svg / .pdf en esta misma carpeta.
"""

from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle, Rectangle

OUT = Path(__file__).resolve().parent

INK = "#1b2a41"
BLUE = "#d9e6f7"
AMBER = "#fdf1d6"
GREEN = "#e3f3e9"
RADIO = "#b0562b"

fig, ax = plt.subplots(figsize=(16, 7.2))
ax.set_xlim(0, 32)
ax.set_ylim(0, 14.4)
ax.set_aspect("equal")
ax.axis("off")


def box(x, y, w, h, title, lines=(), fc="white", tsize=9.6, lsize=8.6):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                 boxstyle="round,pad=0,rounding_size=0.35", fc=fc, ec=INK, lw=1.6, zorder=3))
    n = len(lines)
    top = y + 0.33 * n
    ax.text(x, top, title, fontsize=tsize, weight="bold", color=INK, ha="center", va="center", zorder=4)
    for i, line in enumerate(lines):
        ax.text(x, top - 0.8 - 0.55 * i, line, fontsize=lsize, color=INK, ha="center", va="center", zorder=4)


def container(x0, y0, x1, y1, title, fc, ec):
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc=fc, ec=ec, lw=1.3, zorder=0))
    ax.text((x0 + x1) / 2, y1 - 0.5, title, fontsize=10.2, weight="bold", color=INK, ha="center", va="center")


def arrow(a, b, color=INK, ls="-"):
    ax.annotate("", xy=b, xytext=a, zorder=2,
                arrowprops=dict(arrowstyle="-|>", color=color, lw=1.7, ls=ls,
                                shrinkA=0, shrinkB=0, mutation_scale=15))


def label(xy, text, color=INK, bg="white", size=8.6):
    ax.text(*xy, text, fontsize=size, color=color, ha="center", va="center", zorder=6,
            bbox=dict(fc=bg, ec="none", pad=1.2), linespacing=1.4)


def wave(a, b):
    t = np.linspace(0, 1, 200)
    xs = a[0] + (b[0] - a[0]) * t
    ys = a[1] + 0.3 * np.sin(8 * np.pi * t)
    ax.plot(xs[:-8], ys[:-8], color=RADIO, lw=1.8, zorder=2)
    arrow((xs[-8], ys[-8]), (b[0], a[1]), color=RADIO)


# ---------- contenedores ----------
container(0.4, 3.6, 9.8, 13.9, "CARGA SECUNDARIA  (ya en tierra)", "#f6f9fd", "#9db3d3")
container(12.4, 3.6, 21.8, 13.9, "CARGA PRIMARIA  (ya en tierra)", "#fbf8f0", "#cbb98c")
container(24.6, 3.6, 31.6, 13.9, "ESTACIÓN TERRENA", "#f6f9fd", "#9db3d3")

# ---------- carga secundaria ----------
XS, XP = 5.1, 17.1
box(XS, 10.9, 7.6, 2.4, "GPS NEO-6M", ["Obtiene su latitud", "y longitud"], fc=BLUE)
box(XS, 7.7, 7.6, 2.4, "MICROCONTROLADOR", ["ESP32-C3 / Arduino Nano", "Arma el paquete con la posición"], fc=BLUE)
box(XS, 4.9, 7.6, 2.0, "LoRa SX1278 / NRF24L01", ["Transmite la posición"], fc=BLUE)
arrow((XS, 9.7), (XS, 8.9))
arrow((XS, 6.5), (XS, 5.9))

# ---------- carga primaria ----------
box(XP, 10.9, 7.6, 2.4, "GPS NEO-6M propio", ["Posición de referencia", "de la carga primaria"], fc=AMBER)
box(XP, 7.7, 7.6, 2.4, "ESP32 DevKit V1", ["Calcula distancia y rumbo", "hacia la carga secundaria"], fc=AMBER)
box(XP, 4.9, 7.6, 2.0, "LoRa SX1278 (Rx)", ["Recibe la posición"], fc=AMBER)
arrow((XP, 9.7), (XP, 8.9))
arrow((XP, 5.9), (XP, 6.5))

# enlace de radio
wave((8.9, 4.9), (13.3, 4.9))
label((11.1, 6.1), "Enlace LoRa\n433/915 MHz", RADIO)

# ---------- estacion terrena ----------
ax.add_patch(FancyBboxPatch((25.1, 4.6), 6.0, 8.2, boxstyle="round,pad=0,rounding_size=0.35",
                            fc=GREEN, ec=INK, lw=1.6, zorder=3))
ax.text(28.1, 12.0, "DASHBOARD", fontsize=9.6, weight="bold", color=INK, ha="center", va="center", zorder=4)
for i, line in enumerate(["Radar de la carga", "secundaria: distancia", "y rumbo"]):
    ax.text(28.1, 11.1 - 0.55 * i, line, fontsize=8.6, color=INK, ha="center", va="center", zorder=4)
for r in (0.6, 1.2, 1.8):
    ax.add_patch(Circle((28.1, 7.0), r, fc="none", ec=INK, lw=0.9, zorder=4))
ax.add_patch(Circle((28.1, 7.0), 0.14, fc=INK, ec=INK, zorder=5))
ax.add_patch(Circle((28.9, 7.9), 0.2, fc="#e0a030", ec="#e0a030", zorder=5))
ax.plot([28.1, 28.9], [7.0, 7.9], color="#e0a030", lw=1.2, ls="--", zorder=4)
arrow((20.9, 7.7), (25.1, 7.7))
label((23.0, 9.0), "Telemetría\nSECONDARY_DIST (m)\nSECONDARY_DIR (°)", INK, size=8.3)

# ---------- calculo ----------
ax.add_patch(FancyBboxPatch((0.4, 0.3), 31.2, 2.9, boxstyle="round,pad=0,rounding_size=0.35",
                            fc="white", ec=INK, lw=1.4, zorder=3))
ax.text(1.0, 2.55, "Cálculo en la carga primaria (φ = latitud, λ = longitud; 1 = primaria, 2 = secundaria):",
        fontsize=9.2, weight="bold", color=INK, ha="left", va="center", zorder=4)
ax.text(1.0, 1.65, "Distancia (Haversine):   d = 2R · arcsin √( sin²(Δφ/2) + cos φ₁ · cos φ₂ · sin²(Δλ/2) ),   R = 6 371 km",
        fontsize=9.0, color=INK, ha="left", va="center", zorder=4)
ax.text(1.0, 0.85, "Rumbo respecto al norte:   θ = atan2( sin Δλ · cos φ₂ ,  cos φ₁ · sin φ₂ − sin φ₁ · cos φ₂ · cos Δλ )",
        fontsize=9.0, color=INK, ha="left", va="center", zorder=4)
ax.text(31.2, 1.25, "La secundaria transmite 15 s tras\naterrizar (mínimo exigido: 10 s)\nPrecisión típica del GPS: ≈ 2.5 m",
        fontsize=8.2, color=INK, ha="right", va="center", zorder=4, linespacing=1.3)

fig.tight_layout(pad=0.3)
for ext in ("png", "svg", "pdf"):
    fig.savefig(OUT / f"diagrama_deteccion_cargas.{ext}", dpi=200, facecolor="white")
print("Generado en", OUT)
