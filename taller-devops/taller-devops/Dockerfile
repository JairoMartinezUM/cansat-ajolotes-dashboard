FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    CANSAT_LOG_DIR=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY telemetry_format.py flight_sim.py lora_bridge.py dashboard.py dashboard.html ./
COPY ["Logo Ajolotes.png", "./"]
COPY fonts ./fonts

# No correr como root dentro del contenedor
RUN useradd --system --uid 10001 cansat && mkdir /data && chown cansat /data
USER cansat

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/metrics', timeout=3)"

# Modo simulador. El dashboard lanza flight_sim.py como subproceso (boton "Iniciar").
CMD ["python", "dashboard.py", "--host", "0.0.0.0"]
