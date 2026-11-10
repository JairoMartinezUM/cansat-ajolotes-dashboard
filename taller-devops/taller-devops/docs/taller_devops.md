# Taller 3 de Sistemas Operativos: Git/GitHub + Docker + Grafana

Dashboard del CanSat (modo simulador) desplegado con contenedores en el servidor casero,
monitoreado con Prometheus + Grafana y actualizado desde GitHub Actions.

```
 git push ──> GitHub Actions ──> pruebas ──> imagen en ghcr.io ──> runner en el servidor
                                                                         │ docker compose pull/up
 ┌────────────────────────── servidor (Ubuntu Server) ────────────────────▼─────────┐
 │  dashboard :8000 ──/metrics──> prometheus ──> grafana :3000                       │
 │     └─ flight_sim.py (subproceso)      ▲                                          │
 │  node-exporter (CPU/RAM/disco) ────────┤   cAdvisor (CPU/RAM por contenedor) ─────┘
 └───────────────────────────────────────────────────────────────────────────────────┘
```

## 1. Probar en tu PC (Docker Desktop)

```bash
git switch -c taller-devops
cp .env.example .env
docker compose up -d --build
./scripts/demo_vuelos.sh          # en otra terminal (Git Bash / WSL): vuelos simulados en bucle
```

Dashboard: http://localhost:8000 · Grafana: http://localhost:3000 (admin / la contraseña de `.env`).
En Windows no hay node-exporter ni cAdvisor (necesitan Linux), así que el panel "Servidor" sale vacío.

## 2. Preparar el servidor

```bash
free -h && df -h /                       # RAM y disco disponibles
sudo apt update && sudo apt install -y docker.io docker-compose-v2   # o Docker Engine oficial
sudo systemctl enable --now docker
sudo usermod -aG docker $USER            # cerrar sesión y volver a entrar
docker run --rm hello-world              # prueba también el pull desde la red de la facultad
git clone https://github.com/JairoMartinezUM/cansat-ajolotes-dashboard.git && cd cansat-ajolotes-dashboard
git switch taller-devops
cp .env.example .env && nano .env        # descomentar COMPOSE_PROFILES=server y poner la contraseña
docker compose up -d --build
```

Si la RAM es de 4 GB o menos, quita `cadvisor` o baja los `mem_limit`.
El servidor ya no se apaga solo y la batería de la laptop aguanta más de 1 h, así que un apagón de unos 40 min
no lo interrumpe. Aun así, `restart: unless-stopped` + Docker habilitado en systemd hacen que todo vuelva solo
tras un reinicio (se puede demostrar con `sudo reboot`).

Con el servidor encendido todo el tiempo, usa `scripts/demo_vuelos.sh` solo mientras pruebas o presentas: cada
vuelo guarda un CSV en el volumen `cansat-logs` y, en bucle durante días, llenaría el disco mecánico.

## 3. CI/CD con GitHub Actions

1. Subir la rama: `git push -u origin taller-devops`. En la pestaña **Actions** corren las pruebas y se publica
   la imagen en `ghcr.io/jairomartinezum/cansat-ajolotes-dashboard:taller-devops`.
2. Si el paquete es privado, en el servidor: `docker login ghcr.io` (usuario + token con `read:packages`).
3. Runner en el servidor: repo > Settings > Actions > Runners > New self-hosted runner (Linux x64), con la
   etiqueta `cansat-server`. Instalarlo como servicio (`sudo ./svc.sh install && sudo ./svc.sh start`).
   Guardar la configuración del servidor en `/etc/cansat/.env` (copia de `.env`).
4. Settings > Secrets and variables > Actions > Variables: `DEPLOY_ENABLED = true`.
   Desde ahí cada push actualiza los contenedores en el servidor.
5. Plan B si el firewall bloquea al runner: en el servidor, `git pull && docker compose pull && docker compose up -d`.
   **No usar el runner con pull requests de forks** (si el repo es público, ponerlo privado durante el taller).

## 4. Demos de sistemas operativos

| Tema | Comandos | Qué mostrar |
|---|---|---|
| Procesos y namespaces | `docker top cansat-dashboard-1`, `docker exec cansat-dashboard-1 ps aux`, `sudo lsns -t pid` | Dentro del contenedor el dashboard es el PID 1 y `flight_sim.py` su hijo; afuera tienen otros PID |
| cgroups (CPU y memoria) | Poner `DASHBOARD_CPUS=0.1` y `DASHBOARD_MEM=32m` en `.env`, luego `docker compose up -d`; `docker stats` | El límite aparece en Grafana ("Memoria por contenedor") y el kernel lo aplica |
| Recuperación | `docker kill cansat-dashboard-1` | `restart: unless-stopped` lo levanta; Grafana muestra el hueco |
| Reinicio del servidor | `sudo reboot`, y luego `docker ps` y `uptime` | Docker y los contenedores vuelven solos, sin intervención |
| Servicios | `systemctl status docker`, `journalctl -u docker -n 20`, `docker compose logs -f dashboard` | Docker es un servicio de systemd; arranca solo tras un reinicio |
| Convivencia | Con el servidor de Terraria encendido, mirar CPU/RAM por contenedor | Cómo se reparten los recursos |
| Persistencia | `docker volume ls`, `docker compose down && docker compose up -d` | Los CSV (`cansat-logs`) sobreviven; el contenedor no |

## 5. Evidencia para entregar

- Historial de commits de la rama `taller-devops` y una ejecución verde en Actions.
- Captura de Grafana con un vuelo completo (fases, altitud, CPU/RAM por contenedor).
- Salida de `docker stats` y de `lsns` / `docker top`.
- Captura del límite de memoria aplicado y del reinicio tras `docker kill`.
- Respaldo por si falla la red del campus: `docker save -o imagenes.tar $(docker compose config --images)`
  y en el servidor `docker load -i imagenes.tar`.

## Nota para el día del lanzamiento

El modo LoRa (`python dashboard.py --serial COMx`) sigue corriendo directo con Python en la laptop del
operador (Windows). Docker queda para el taller y el servidor. El `/metrics` funciona en los dos modos.
