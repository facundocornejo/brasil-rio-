# Lecciones aprendidas — Bot pasajes Río

## 08/07/2026 — Outage silencioso de 3.5 semanas

**Qué pasó**: `fast-flights>=2.2` sin techo de major. El 13/06 salió la v3.0
(API incompatible) y desde el 14/06 cada run instalaba la versión rota. El engine
traga errores de adapters (correcto para fallos parciales) y no había guard de
volumen, así que 47 runs consecutivos terminaron "success" con 0 precios.

**Reglas**:
1. Dependencias de terceros (sobre todo scrapers/APIs no oficiales) SIEMPRE con
   techo de major: `>=X.Y,<X+1`.
2. Todo pipeline de datos necesita un guard de volumen mínimo: "0 resultados" es
   un estado de error que debe romper el run Y notificar, nunca un run verde.
3. Al diagnosticar "no anda" en un cron: mirar primero la FECHA del último run
   sano en los logs y qué versión de cada dependencia instaló ese run vs el roto
   (`pip install` logs). El diff de versiones canta la causa.
