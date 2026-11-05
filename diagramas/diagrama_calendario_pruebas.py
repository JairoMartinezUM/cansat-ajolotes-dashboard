"""
Calendarizacion de las pruebas de software de la estacion terrena (diapositiva 30, punto 27).

Las ventanas se alinean con el diagrama de Gantt del PDR (diapositiva 31): integracion
a mediados de octubre, pruebas integradas a principios de noviembre y lanzamiento en la
ultima semana de noviembre. Las fechas son una propuesta por confirmar con el equipo.

Uso:  python diagrama_calendario_pruebas.py
Salida: diagrama_calendario_pruebas.png / .svg / .pdf en esta misma carpeta.
"""

from datetime import date, timedelta
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle

OUT = Path(__file__).resolve().parent

INK = "#1b2a41"
PRIO = {1: ("#c0392b", "Prioridad 1 (alta)"), 2: ("#e0a030", "Prioridad 2 (media)"), 3: ("#3d8f6a", "Prioridad 3 (baja)")}

HOY = date(2026, 10, 5)
# (prioridad, prueba, inicio, fin, etapa del Gantt)
PRUEBAS = [
    (1, "Recepción con hardware real\n(SX1278 → ESP32 → laptop)", date(2026, 10, 12), date(2026, 10, 23), "Integración"),
    (1, "Alcance del enlace de radio\n(hasta 450 m, línea de vista)", date(2026, 11, 2), date(2026, 11, 6), "Pruebas integradas"),
    (1, "Distancia y rumbo a la carga\nsecundaria (contra medición real)", date(2026, 11, 3), date(2026, 11, 7), "Pruebas integradas"),
    (2, "Operación continua\n(más de 1 h con batería)", date(2026, 10, 19), date(2026, 10, 25), "Integración"),
    (2, "Ensayo general de misión\n(cronometrado, con el operador)", date(2026, 11, 9), date(2026, 11, 13), "Pruebas integradas"),
    (3, "Interfaz en campo\n(lectura con luz solar)", date(2026, 11, 14), date(2026, 11, 16), "Pruebas integradas"),
]
HECHO = ("Pruebas de software con simulador\n(10 de 10 aprobadas)", date(2026, 9, 28), HOY)
CONGELA = date(2026, 11, 17)
LANZ = (date(2026, 11, 19), date(2026, 11, 30))

fig, ax = plt.subplots(figsize=(16, 6.8))
filas = [("hecho",) + HECHO] + [("p",) + p for p in PRUEBAS]
n = len(filas)

x0, x1 = date(2026, 9, 28), date(2026, 12, 1)
ax.set_xlim(mdates.date2num(x0), mdates.date2num(x1))
ax.set_ylim(n - 0.4, -1.1)

# semanas
d = x0
while d <= x1:
    ax.axvline(mdates.date2num(d), color="#d5dbe6", lw=0.8, zorder=0)
    d += timedelta(days=7)

# lanzamiento y congelamiento
ax.add_patch(Rectangle((mdates.date2num(LANZ[0]), -1.1), (LANZ[1] - LANZ[0]).days + 1, n + 0.7,
                       fc="#f3dede", ec="none", zorder=0))
ax.text(mdates.date2num(LANZ[0]) + 5.5, -0.75, "LANZAMIENTO\n(según Gantt)", ha="center", va="center",
        fontsize=9, weight="bold", color="#9b2d2d")
ax.axvline(mdates.date2num(CONGELA), color=INK, ls="--", lw=1.4, zorder=1)
ax.text(mdates.date2num(CONGELA) - 0.6, -0.75, "Congelar el\nsoftware (17 nov)", ha="right", va="center", fontsize=8.8, color=INK)
ax.axvline(mdates.date2num(HOY), color="#5b2a86", lw=1.6, zorder=1)
ax.text(mdates.date2num(HOY) + 0.6, -0.75, "Hoy (5 oct)", ha="left", va="center", fontsize=8.8, color="#5b2a86", weight="bold")

for i, f in enumerate(filas):
    if f[0] == "hecho":
        _, nombre, a, b = f
        ax.barh(i, (b - a).days, left=mdates.date2num(a), height=0.52, color="#9aa7bb", ec=INK, lw=1.2, zorder=3)
        ax.text(mdates.date2num(b) + 1, i, "Terminada", va="center", ha="left", fontsize=8.8, color=INK, style="italic")
        etiqueta = nombre
    else:
        _, p, nombre, a, b, etapa = f
        ax.barh(i, (b - a).days + 1, left=mdates.date2num(a), height=0.52, color=PRIO[p][0], ec=INK, lw=1.2, zorder=3)
        ax.text(mdates.date2num(b) + 2, i, f"{a.day} {['', 'ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'][a.month]}"
                f" – {b.day} {['', 'ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'][b.month]}",
                va="center", ha="left", fontsize=8.8, color=INK, weight="bold",
                bbox=dict(fc="white", ec="none", pad=1.0), zorder=5)
        etiqueta = nombre

ax.set_yticks(range(n))
ax.set_yticklabels([f[1] if f[0] == "hecho" else f"{f[2]}\nEtapa: {f[5]}" for f in filas], fontsize=9.0, color=INK)
ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
ax.tick_params(axis="x", labelsize=8.8, colors=INK)
ax.xaxis.tick_top()
ax.tick_params(axis="y", length=0)
for s in ("right", "bottom", "left"):
    ax.spines[s].set_visible(False)
ax.spines["top"].set_color("#9db3d3")

ax.legend(handles=[Patch(fc=PRIO[k][0], ec=INK, label=PRIO[k][1]) for k in (1, 2, 3)] +
          [Patch(fc="#9aa7bb", ec=INK, label="Realizada")],
          loc="lower center", bbox_to_anchor=(0.5, -0.09), ncol=4, frameon=False, fontsize=9.2)
fig.suptitle("Calendarización de las pruebas de software (ordenadas por prioridad)", fontsize=14, weight="bold",
             color=INK, y=0.985)
fig.tight_layout(rect=(0, 0.02, 1, 0.96))
for ext in ("png", "svg", "pdf"):
    fig.savefig(OUT / f"diagrama_calendario_pruebas.{ext}", dpi=200, facecolor="white")
print("Generado en", OUT)
