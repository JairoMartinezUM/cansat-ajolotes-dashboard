#!/usr/bin/env bash
# Lanza vuelos simulados en bucle para que Grafana siempre tenga datos que mostrar.
# Cada vuelo guarda un CSV: usalo solo mientras pruebas o presentas, no lo dejes dias corriendo.
# Uso: ./scripts/demo_vuelos.sh [URL_DASHBOARD] [VELOCIDAD]
URL="${1:-http://localhost:8000}"
SPEED="${2:-5}"

while true; do
  curl -fsS -X POST -H 'Content-Type: application/json' \
       -d "{\"speed\": ${SPEED}}" "${URL}/api/sim/start" > /dev/null || { sleep 5; continue; }
  sleep 2
  while curl -fsS "${URL}/metrics" | grep -q '^cansat_sim_running 1'; do sleep 2; done
  echo "Vuelo terminado, siguiente en 5 s"
  sleep 5
done
