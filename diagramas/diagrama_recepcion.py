"""
Genera el diagrama de flujo del algoritmo de recepción de telemetría de la
estación terrena (basado en dashboard.py y dashboard.html, con el simulador
flight_sim.py como fuente de datos).

Uso:  python diagrama_recepcion.py
Salida: diagrama_recepcion.png / .svg / .pdf en esta misma carpeta.
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Polygon, Circle, Rectangle

OUT = Path(__file__).resolve().parent

INK = "#1b2a41"
FILL = {"term": "#d9e6f7", "proc": "#ffffff", "io": "#fdf1d6", "dec": "#e3f3e9", "ext": "#f1f1f1"}

fig, ax = plt.subplots(figsize=(16, 13.4))
ax.set_xlim(-13, 20.2)
ax.set_ylim(-25.2, 1.9)
ax.set_aspect("equal")
ax.axis("off")

FONT = dict(fontsize=9.3, color=INK, ha="center", va="center", linespacing=1.25)


def term(x, y, text, w=4.4, h=1.0):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                 boxstyle=f"round,pad=0,rounding_size={h / 2}",
                 fc=FILL["term"], ec=INK, lw=1.6, zorder=3))
    ax.text(x, y, text, weight="bold", zorder=4, **FONT)


def proc(x, y, text, w=6.0, h=1.2, kind="proc", dashed=False):
    ax.add_patch(Rectangle((x - w / 2, y - h / 2), w, h, fc=FILL[kind], ec=INK, lw=1.4,
                           ls="--" if dashed else "-", zorder=3))
    ax.text(x, y, text, zorder=4, **FONT)


def io(x, y, text, w=6.0, h=1.2, skew=0.5):
    pts = [(x - w / 2 + skew, y + h / 2), (x + w / 2 + skew, y + h / 2),
           (x + w / 2 - skew, y - h / 2), (x - w / 2 - skew, y - h / 2)]
    ax.add_patch(Polygon(pts, fc=FILL["io"], ec=INK, lw=1.4, zorder=3))
    ax.text(x, y, text, zorder=4, **FONT)


def dec(x, y, text, w=6.4, h=2.6):
    pts = [(x, y + h / 2), (x + w / 2, y), (x, y - h / 2), (x - w / 2, y)]
    ax.add_patch(Polygon(pts, fc=FILL["dec"], ec=INK, lw=1.4, zorder=3))
    ax.text(x, y, text, zorder=4, **{**FONT, "fontsize": 8.8})


def junction(x, y):
    ax.add_patch(Circle((x, y), 0.17, fc=INK, ec=INK, zorder=5))


def arrow(points, label=None, label_at=None, dashed=False, color=INK, head=True):
    """Polilínea con punta de flecha en el ultimo tramo."""
    style = "--" if dashed else "-"
    for a, b in zip(points[:-2], points[1:-1]):
        ax.plot([a[0], b[0]], [a[1], b[1]], color=color, lw=1.4, ls=style, zorder=2)
    a, b = points[-2], points[-1]
    ax.annotate("", xy=b, xytext=a, zorder=2,
                arrowprops=dict(arrowstyle="-|>" if head else "-", color=color, lw=1.4,
                                ls=style, shrinkA=0, shrinkB=0, mutation_scale=14))
    if label:
        lx, ly = label_at
        ax.text(lx, ly, label, fontsize=8.8, color=color, ha="center", va="center", zorder=6,
                bbox=dict(fc="white", ec="none", pad=1.2))


# ---------------- carriles ----------------
ax.add_patch(Rectangle((-6.6, -24.6), 16.4, 25.4, fc="#f6f9fd", ec="#9db3d3", lw=1.2, zorder=0))
ax.add_patch(Rectangle((10.0, -24.6), 9.6, 25.4, fc="#f9f7f1", ec="#cbb98c", lw=1.2, zorder=0))
ax.text(1.6, 0.35, "RECEPTOR DE TELEMETRÍA  (hilo UDP · dashboard.py)", fontsize=10.5, weight="bold",
        color=INK, ha="center", va="center", zorder=1)
ax.text(14.8, 0.35, "INTERFAZ WEB  (dashboard.html)", fontsize=10.5, weight="bold",
        color=INK, ha="center", va="center", zorder=1)
ax.text(3.2, 1.5, "Algoritmo de recepción de datos del CanSat en la estación terrena (simulador)",
        fontsize=13, weight="bold", color=INK, ha="center", va="center")

# ---------------- carril A: receptor ----------------
X = 0.0
term(X, -1.4, "INICIO")
proc(X, -3.1, "Leer parámetros:\nIP 127.0.0.1 · puerto UDP 5005")
proc(X, -4.8, "Crear archivo CSV con fecha y hora\ny escribir el encabezado (17 campos)")
proc(X, -6.5, "Crear socket UDP y enlazarlo\n(bind) a IP:puerto")
JY = -7.8
junction(X, JY)
io(X, -9.2, "Esperar paquete\nrecvfrom()  ·  bloqueante")
proc(X, -10.9, "Decodificar bytes a texto (UTF-8)\ny separar la línea por comas")
dec(X, -13.3, "¿Paquete válido?\n17 campos y valores\nnuméricos correctos")
proc(X, -15.7, "Convertir tipos: PACKET_COUNT a entero,\nresto de campos a decimal\n→ diccionario de telemetría", h=1.5)
proc(X, -17.5, "Guardar el paquete en la lista\nen memoria (protegida con lock)")
proc(X, -19.1, "Escribir la fila en el CSV\ny forzar el guardado (flush)")
dec(X, -21.2, "¿Se detuvo\nel servidor?\n(Ctrl+C)", w=5.0, h=2.2)
proc(X, -23.2, "Cerrar el servidor y guardar el log", h=0.9)
term(X, -24.3, "FIN", h=0.8, w=3.0)

# fuente externa
proc(-10.0, JY, "Simulador flight_sim.py\n1 paquete por segundo\n(línea CSV por UDP)", w=4.8, h=1.7, kind="ext", dashed=True)
arrow([(-7.6, JY), (X - 0.2, JY)], dashed=True)

# flujo principal
arrow([(X, -1.9), (X, -2.5)])
arrow([(X, -3.7), (X, -4.2)])
arrow([(X, -5.4), (X, -5.9)])
arrow([(X, -7.1), (X, JY + 0.17)], head=False)
arrow([(X, JY), (X, -8.6)])
arrow([(X, -9.8), (X, -10.3)])
arrow([(X, -11.5), (X, -12.0)])
arrow([(X, -14.6), (X, -14.95)], label="Sí", label_at=(0.45, -14.8))
arrow([(X, -16.45), (X, -16.9)])
arrow([(X, -18.1), (X, -18.5)])
arrow([(X, -19.7), (X, -20.1)])
arrow([(X, -22.3), (X, -22.75)], label="Sí", label_at=(0.45, -22.5))
arrow([(X, -23.65), (X, -23.9)])

# paquete inválido
proc(6.9, -13.3, "Imprimir \"Paquete inválido\"\ny descartarlo", w=4.4, h=1.2)
arrow([(3.2, -13.3), (4.7, -13.3)], label="No", label_at=(3.95, -12.95))
arrow([(6.9, -12.7), (6.9, JY), (X + 0.2, JY)])

# repetir
arrow([(-2.5, -21.2), (-4.9, -21.2), (-4.9, JY), (-0.2, JY)], label="No\n(esperar el\nsiguiente paquete)",
      label_at=(-4.9, -17.8))

# ---------------- carril B: interfaz ----------------
XB = 14.3
WB = 6.8
term(XB, -2.3, "Abrir el dashboard\n(navegador)", w=4.8, h=1.3)
proc(XB, -4.9, "Cada 500 ms pedir al servidor los\npaquetes nuevos: GET /api/state?since=N", w=WB, h=1.3)
dec(XB, -7.6, "¿Hay paquetes\nnuevos?", w=5.0, h=2.2)
proc(XB, -10.0, "Agregar a la lista local y convertir\nMISSION_TIME a segundos", w=WB, h=1.3)
proc(XB, -12.0, "Actualizar tarjetas de estado, fase de\nvuelo, batería y orientación 3D", w=WB, h=1.3)
dec(XB, -14.9, "¿STATE = LANDED y\nSECONDARY_DIST ≥ 0?", w=6.6, h=2.6)
proc(XB, -17.7, "Mostrar la carga secundaria en el\nradar (distancia y rumbo)", w=WB, h=1.3)
proc(XB, -19.9, "Redibujar gráficas: altitud, velocidad,\ntemperatura, presión y aceleración", w=WB, h=1.3)

arrow([(XB, -2.95), (XB, -4.25)])
arrow([(XB, -5.55), (XB, -6.5)])
arrow([(XB, -8.7), (XB, -9.35)], label="Sí", label_at=(XB + 0.45, -9.05))
arrow([(XB, -10.65), (XB, -11.35)])
arrow([(XB, -12.65), (XB, -13.6)])
arrow([(XB, -16.2), (XB, -17.05)], label="Sí", label_at=(XB + 0.45, -16.6))
arrow([(XB, -18.35), (XB, -19.25)])
# no hay paquetes -> esperar
arrow([(XB + 2.5, -7.6), (18.6, -7.6), (18.6, -4.9), (XB + WB / 2, -4.9)],
      label="No", label_at=(16.9, -7.25))
# repetir ciclo
arrow([(XB + WB / 2, -19.9), (18.6, -19.9), (18.6, -7.6)], head=False)
ax.text(18.6, -13.7, "repetir\ncada\n500 ms", fontsize=8.8, color=INK, ha="center", va="center",
        rotation=90, bbox=dict(fc="#f9f7f1", ec="none", pad=1.5), zorder=6)
# no landed -> directo a gráficas
arrow([(XB - 3.3, -14.9), (10.4, -14.9), (10.4, -19.9), (XB - WB / 2, -19.9)],
      label="No", label_at=(11.0, -14.55))

# enlace entre carriles: lista compartida
arrow([(X + 3.0, -17.5), (9.5, -17.5), (9.5, -4.9), (XB - WB / 2, -4.9)], dashed=True, color="#b0562b")
ax.text(9.5, -11.5, "lista de\npaquetes\n(servida por\n/api/state)", fontsize=8.6, color="#b0562b",
        ha="center", va="center", bbox=dict(fc="white", ec="none", pad=1.5), zorder=6)

# leyenda
lx, ly = -12.6, -17.0
ax.text(lx, ly + 1.4, "Símbolos", fontsize=9.5, weight="bold", color=INK, ha="left")
items = [("term", "Inicio / fin"), ("proc", "Proceso"), ("io", "Entrada / salida"),
         ("dec", "Decisión")]
for i, (k, name) in enumerate(items):
    yy = ly + 0.4 - i * 1.0
    if k == "term":
        ax.add_patch(FancyBboxPatch((lx, yy - 0.3), 1.2, 0.6, boxstyle="round,pad=0,rounding_size=0.3",
                                    fc=FILL[k], ec=INK, lw=1.2))
    elif k == "proc":
        ax.add_patch(Rectangle((lx, yy - 0.3), 1.2, 0.6, fc=FILL[k], ec=INK, lw=1.2))
    elif k == "io":
        ax.add_patch(Polygon([(lx + 0.25, yy + 0.3), (lx + 1.35, yy + 0.3), (lx + 0.95, yy - 0.3),
                              (lx - 0.15, yy - 0.3)], fc=FILL[k], ec=INK, lw=1.2))
    else:
        ax.add_patch(Polygon([(lx + 0.6, yy + 0.35), (lx + 1.3, yy), (lx + 0.6, yy - 0.35), (lx - 0.1, yy)],
                             fc=FILL[k], ec=INK, lw=1.2))
    ax.text(lx + 1.7, yy, name, fontsize=8.8, color=INK, ha="left", va="center")

fig.tight_layout(pad=0.4)
for ext in ("png", "svg", "pdf"):
    fig.savefig(OUT / f"diagrama_recepcion.{ext}", dpi=200, facecolor="white")
print("Generado en", OUT)
