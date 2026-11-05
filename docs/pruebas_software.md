# Pruebas de software de la estación terrena (borrador para el PDR)

Resultados de `python tests/test_sistema.py` (10 pruebas, todas aprobadas, ~8 s).
Todas se hicieron con el simulador de vuelo (`flight_sim.py`) y UDP local: todavía
no hay enlace de radio ni hardware real.

## Diapositiva 29 — Punto 26: pruebas realizadas hasta el momento

| Nombre de la prueba | Descripción | Sustento y resultados |
|---|---|---|
| Formato de telemetría (codificar y decodificar) | Se generan 30 paquetes con el simulador, se convierten a la línea CSV de 17 campos y se leen de vuelta. | Prueba automática 01. Los 17 campos se conservan en el mismo orden y con los mismos valores (a 2 decimales). |
| Vuelo completo simulado | Un vuelo completo (ascenso a 450 m, caída libre, autogiro desde 200 m, aterrizaje y transmisión posterior) se envía por UDP a la estación terrena. | Prueba 02. Se recibieron ≈225 paquetes numerados sin faltantes ni repetidos; las 5 fases salieron en orden; altitud máxima de 450 m; velocidad en autogiro de 8 a 12 m/s; 16 paquetes tras aterrizar (mínimo exigido: 10 s) con la carga secundaria ubicada (p. ej. 14.9 m a 223.6°). |
| Registro de datos en CSV | Se compara el archivo CSV guardado contra lo recibido al terminar un vuelo. | Prueba 03. Encabezado de 17 campos y una fila por cada paquete recibido, sin filas incompletas. |
| Paquetes inválidos | Se envían 7 paquetes defectuosos (vacío, texto basura, faltan campos, sobran campos, valor no numérico, bytes no UTF-8, contador no numérico) y después uno válido. | Prueba 04. Los 7 se descartaron con aviso, el sistema siguió activo y recibió el paquete válido siguiente. |
| Velocidad de recepción y retardo | Se envían 1000 paquetes sin pausa y se mide el tiempo entre el envío de un paquete y su disponibilidad en el dashboard. | Pruebas 09 y 10. 1000 de 1000 paquetes recibidos en orden (≈880 paquetes/s, contra 1 paquete/s del vuelo real); retardo máximo de 16 ms. |
| Funcionamiento sin internet y dashboard | Se revisa que la página no cargue nada externo (fuentes, logo, librerías) y se prueba el reinicio de misión, la lectura incremental y las peticiones incorrectas. | Pruebas 05 a 08. Todos los recursos se sirven desde la laptop; el reinicio abre un CSV nuevo; las peticiones fuera de rango se rechazan (400/404). Revisión visual en el navegador sin errores en consola (captura en la diapositiva 23). |

Hallazgo corregido: la prueba 06 detectó que dos misiones iniciadas en el mismo segundo
reutilizaban el nombre del CSV y lo sobrescribían. Se corrigió (ahora se agrega un sufijo) y la prueba pasa.

## Diapositiva 30 — Punto 27: plan de pruebas de software (ordenado por prioridad)

Las etapas siguen el diagrama de Gantt (diapositiva 31). Las fechas exactas están por confirmar con el equipo.

| Prioridad | Prueba | Qué se verificará | Etapa propuesta |
|---|---|---|---|
| 1 (Alta) | Recepción con hardware real | Que la estación reciba por LoRa (SX1278 → ESP32 → laptop) paquetes con el firmware real y los 17 campos sin errores. | Integración |
| 1 (Alta) | Alcance del enlace de radio | Recepción sin pérdidas de paquetes hasta los 450 m de altura y en tierra tras el aterrizaje, con línea de vista. | Pruebas integradas |
| 1 (Alta) | Distancia y rumbo a la carga secundaria | Comparar la distancia y el rumbo calculados con los GPS contra una medición real en campo (cinta o mapa). | Pruebas integradas |
| 2 (Media) | Ensayo general de misión | Un vuelo completo (simulado primero, con el hardware después) con el operador y cronometrado. | Pruebas integradas |
| 2 (Media) | Operación continua | Sesión de recepción de más de una hora con la batería de la laptop, sin cierres ni pérdida de datos. | Pruebas de subsistema |
| 3 (Baja) | Interfaz en campo | Que el dashboard se lea con luz solar y en la pantalla de la laptop del operador. | Pruebas integradas |

## Calendarización propuesta (diapositiva 30)

Imagen: `diagramas/diagrama_calendario_pruebas.png`. Las ventanas salen del Gantt (diapositiva 31) y
las fechas son una propuesta por confirmar con el equipo.

| Prioridad | Prueba | Fechas | Etapa (Gantt) |
|---|---|---|---|
| Realizada | Pruebas de software con el simulador (10 de 10 aprobadas) | hasta el 5 oct | — |
| 1 (Alta) | Recepción con hardware real (SX1278 → ESP32 → laptop) | 12 – 23 oct | Integración |
| 1 (Alta) | Alcance del enlace de radio (hasta 450 m, línea de vista) | 2 – 6 nov | Pruebas integradas |
| 1 (Alta) | Distancia y rumbo a la carga secundaria (contra medición real) | 3 – 7 nov | Pruebas integradas |
| 2 (Media) | Operación continua (más de 1 h con batería) | 19 – 25 oct | Integración |
| 2 (Media) | Ensayo general de misión (cronometrado, con el operador) | 9 – 13 nov | Pruebas integradas |
| 3 (Baja) | Interfaz en campo (lectura con luz solar) | 14 – 16 nov | Pruebas integradas |
| — | Congelar el software (sin más cambios) | 17 nov | — |
| — | Lanzamiento (según el Gantt) | 19 – 30 nov | — |
