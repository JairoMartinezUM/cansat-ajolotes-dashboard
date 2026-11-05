"""
Diagrama de dispositivos y componentes de la estacion terrena (incluye operadores).

Configuracion actual (fase de simulacion): la estacion terrena es una sola laptop que
ejecuta el software de este proyecto (dashboard.py / dashboard.html) y recibe la
telemetria del simulador flight_sim.py por UDP local. Un unico operador.
El receptor LoRa + antena se muestra como fase posterior (aun no incluido).

Uso:  python diagrama_estacion_terrena.py
Salida: diagrama_estacion_terrena.png / .svg / .pdf en esta misma carpeta.
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle, Wedge, Rectangle

OUT = Path(__file__).resolve().parent

INK = "#1b2a41"
BLUE = "#d9e6f7"
AMBER = "#fdf1d6"
GREEN = "#e3f3e9"
GREY = "#f1f1f1"
PURPLE = "#5b2a86"
LAPTOP_BG = "#f6f9fd"

fig, ax = plt.subplots(figsize=(16, 7.6))
ax.set_xlim(0, 35.0)
ax.set_ylim(0, 16.0)
ax.set_aspect("equal")
ax.axis("off")


def box(x, y, w, h, title, lines=(), fc="white", ls="-", ec=INK, tsize=9.6, lsize=8.5):
    """Caja centrada en (x, y) con titulo en negrita y lineas de detalle."""
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                 boxstyle="round,pad=0,rounding_size=0.35", fc=fc, ec=ec, lw=1.6, ls=ls, zorder=3))
    n = len(lines)
    top = y + 0.33 * n
    ax.text(x, top, title, fontsize=tsize, weight="bold", color=ec, ha="center", va="center", zorder=4,
            linespacing=1.2)
    for i, line in enumerate(lines):
        ax.text(x, top - 0.95 - 0.6 * i, line, fontsize=lsize, color=ec, ha="center", va="center", zorder=4)


def label(xy, text, color=INK, bg="white", size=8.5):
    ax.text(*xy, text, fontsize=size, color=color, ha="center", va="center", zorder=6,
            bbox=dict(fc=bg, ec="none", pad=1.2), linespacing=1.15)


def arrow(a, b, color=INK, ls="-"):
    ax.annotate("", xy=b, xytext=a, zorder=2,
                arrowprops=dict(arrowstyle="-|>", color=color, lw=1.7, ls=ls,
                                shrinkA=0, shrinkB=0, mutation_scale=15))


def poly(points, color=INK, ls="-"):
    """Polilinea con punta de flecha en el ultimo tramo."""
    for a, b in zip(points[:-2], points[1:-1]):
        ax.plot([a[0], b[0]], [a[1], b[1]], color=color, lw=1.7, ls=ls, zorder=2)
    arrow(points[-2], points[-1], color=color, ls=ls)


def person(x, y, name, role):
    ax.add_patch(Circle((x, y + 0.75), 0.48, fc=PURPLE, ec=PURPLE, zorder=5))
    ax.add_patch(Wedge((x, y - 0.35), 1.0, 0, 180, fc=PURPLE, ec=PURPLE, zorder=5))
    ax.text(x, y - 1.25, name, fontsize=9.4, weight="bold", color=INK, ha="center", va="center", zorder=5)
    ax.text(x, y - 2.15, role, fontsize=8.5, color=INK, ha="center", va="center", zorder=5, linespacing=1.25)


# ---------- titulo ----------
ax.text(17.5, 15.35, "Estación terrena: dispositivos, componentes y operadores", fontsize=14,
        weight="bold", color=INK, ha="center", va="center")
ax.text(17.5, 14.5, "Configuración actual (fase de simulación)", fontsize=10, color="#5a6b85",
        ha="center", va="center")

# ---------- origen de los datos ----------
box(4.4, 9.2, 6.8, 4.2, "CANSAT SIMULADO", ["flight_sim.py (Python)", "Vuelo completo: ascenso,", "caída libre, autogiro y aterrizaje",
    "1 paquete por segundo"], fc=AMBER)

# fase posterior (no incluida)
box(4.4, 5.0, 6.8, 3.0, "RECEPTOR LoRa + ANTENA", ["Fase posterior: con el", "hardware real (aún no incluido)"],
    fc="white", ls="--", ec="#7f8da3", lsize=8.3)

# ---------- laptop ----------
ax.add_patch(Rectangle((16.2, 0.4), 18.3, 13.3, fc=LAPTOP_BG, ec="#9db3d3", lw=1.4, zorder=0))
ax.text(25.35, 13.15, "LAPTOP DEL OPERADOR  (estación terrena)", fontsize=10.5, weight="bold",
        color=INK, ha="center", va="center")

# enlaces desde el simulador / receptor futuro
poly([(7.8, 9.2), (15.0, 9.2), (15.0, 10.4), (17.0, 10.4)])
label((11.4, 9.95), "UDP local\n127.0.0.1 : 5005")
poly([(7.8, 5.0), (15.0, 5.0), (15.0, 9.2)], color="#7f8da3", ls="--")
label((11.4, 5.7), "(en el futuro)", color="#7f8da3")

# fila 1: recepcion
box(19.6, 10.4, 4.6, 3.4, "RECEPTOR UDP", ["Hilo que escucha", "el puerto 5005"], fc=BLUE)
box(25.4, 10.4, 4.6, 3.4, "DECODIFICADOR", ["Valida 17 campos", "y convierte tipos"], fc=BLUE)
box(31.2, 10.4, 4.6, 3.4, "REGISTRO", ["Lista en memoria", "y archivo CSV"], fc=BLUE)
arrow((21.9, 10.4), (23.1, 10.4))
arrow((27.7, 10.4), (28.9, 10.4))

# fila 2: presentacion
box(31.2, 6.5, 4.6, 3.0, "SERVIDOR WEB", ["dashboard.py", "localhost : 8000"], fc=GREEN)
box(25.4, 6.5, 4.6, 3.0, "DASHBOARD", ["Navegador web", "dashboard.html"], fc=GREEN)
box(19.6, 6.5, 4.6, 3.0, "PANTALLA", ["Tarjetas, gráficas,", "radar y orientación"], fc=GREEN)
arrow((31.2, 8.7), (31.2, 8.0))
arrow((28.9, 6.5), (27.7, 6.5))
arrow((23.1, 6.5), (21.9, 6.5))

# alimentacion
box(31.2, 2.3, 4.6, 2.0, "ALIMENTACIÓN", ["Batería y cargador"], fc=GREY, lsize=8.4)

# operador
person(22.4, 3.3, "OPERADOR ÚNICO", "Monitorea el dashboard, controla la simulación\ny exporta los datos (CSV)")
poly([(22.4, 4.6), (22.4, 5.0)], color=PURPLE, ls="--")

# total de operadores
ax.add_patch(FancyBboxPatch((0.9, 0.4), 6.9, 1.7, boxstyle="round,pad=0,rounding_size=0.35",
                            fc="white", ec=PURPLE, lw=1.8, zorder=3))
ax.text(4.35, 1.25, "Personal necesario: 1 operador", fontsize=10.2, weight="bold", color=PURPLE,
        ha="center", va="center", zorder=4)

fig.tight_layout(pad=0.3)
for ext in ("png", "svg", "pdf"):
    fig.savefig(OUT / f"diagrama_estacion_terrena.{ext}", dpi=200, facecolor="white")
print("Generado en", OUT)
