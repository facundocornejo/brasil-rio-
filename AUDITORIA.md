# Auditoría del bot de pasajes a Río — 08/07/2026

## Resumen ejecutivo

**El bot estuvo roto en silencio desde el 14/06/2026** (3.5 semanas): cero precios
encontrados en cada corrida, pero todos los runs de GitHub Actions en verde. Esta
auditoría encontró la causa raíz, la corrigió, y agregó defensas para que un fallo
así nunca más pase desapercibido. Además se sumó Amadeus como segunda fuente de
datos (pendiente de credenciales).

## Causa raíz (corregida)

- `requirements.txt` decía `fast-flights>=2.2` **sin techo de versión**.
- El **13/06/2026** salió `fast-flights 3.0` en PyPI: una reescritura incompatible
  (el import `FlightData` dejó de existir).
- Desde el run del 14/06, pip instalaba la v3 y las 36 consultas por corrida
  fallaban con `cannot import name 'FlightData'`.
- El engine traga errores de adapters por diseño (correcto para fallos parciales),
  y no había ningún guard de "0 precios totales" → exit 0 → run verde.

**Evidencia**: logs de Actions. Último run sano: 13/06 16:07 UTC (fast-flights 2.2,
~1000 precios/ruta, 26 alertas). Primer run roto: 14/06 07:15 UTC (fast-flights 3.0,
0 precios).

## Qué se corrigió hoy

1. **Migración a fast-flights v3** (`src/adapters/google_flights.py`): API nueva
   (`create_query`/`FlightQuery`/`get_flights`), moneda pedida explícita en USD
   (antes se adivinaba de un string), precio numérico nativo. Se eliminó el
   helper `_parse_stops` (parseaba strings "1 stop" que la v3 ya no devuelve);
   `_parse_price`/`_detect_currency` quedan como fallback defensivo.
2. **Pin de dependencias** (`requirements.txt`): `fast-flights>=3.0.2,<4` y techos
   de major en todo. La causa raíz fue exactamente esto.
3. **Guard anti-fallo-silencioso** (`src/engine.py` + `src/main.py`): si una corrida
   junta 0 precios con rutas configuradas → alerta de error por Telegram + exit 1
   (run rojo en Actions + mail de GitHub).
4. **"Sin vuelos" ya no cuenta como fallo**: la v3 distingue `FlightsNotFound`
   (respuesta sana sin vuelos) de un error real. Antes, 5 fechas sin vuelos
   abortaban la ruta entera.
5. **Nueva fuente: Amadeus** (`src/adapters/amadeus.py`) — ver sección más abajo.
6. **Split de dependencias**: `requirements-dev.txt` (ruff/pytest) separado del
   runtime que instala Actions.
7. **Docs actualizados**: README, setup-guide, architecture y dashboard ahora
   reflejan la realidad (cada 12h, `routes-rio.json`, link correcto al repo).
8. **Tests nuevos**: `tests/test_google_flights_adapter.py` (serialización v3,
   parsers, ventana de fechas) y `tests/test_amadeus_adapter.py` (OAuth, mapeo
   de ofertas, manejo de errores). 26 tests en verde.

## Verificación realizada

- Dry-run real local con fast-flights 3.0.2: precios reales para las 4 rutas,
  incluidas alertas bajo el umbral (ej: **COR→GIG USD 340 JetSMART, 1-7 dic**).
- Guard de 0 precios: probado con config sin resultados → error + exit 1. ✔
- `pytest` 26/26 y `ruff check` limpios. ✔
- Pendiente al pushear: run real de Actions (`workflow_dispatch`) en verde con
  precios > 0.

## Hallazgos restantes (no corregidos, por decisión o alcance)

| # | Severidad | Hallazgo | Sugerencia |
|---|-----------|----------|------------|
| 1 | P2 | Scripts sueltos rotos en la raíz: `find_cheap.py` y `show_cheapest.py` apuntan a `config/routes.json` (no existe); `send_top4.py` tiene vuelos hardcodeados de abril/SSA de otro viaje y usa divisor 1400 vs 1500 de config | Borrarlos o arreglarlos (decisión de Facu; hoy se optó por no borrar código) |
| 2 | P2 | Adapters Level y Sky sin uso en las rutas de Río; Sky además tiene la API key hardcodeada en `src/adapters/sky.py:27` | Dejar como están (sirven si se agregan rutas); si Sky se reactiva, mover la key a env |
| 3 | P2 | **Level está bloqueando**: su API redirige a `sorry.flylevel.com` (anti-bot). Detectado durante esta auditoría | Si algún día se usa Level, va a necesitar otro enfoque |
| 4 | P3 | `config.py` defaultea a `config/routes.json` inexistente: `python -m src.main` sin `--config` falla | Cambiar el default a `routes-rio.json` o documentarlo |
| 5 | P3 | El dashboard (`docs/index.html`) muestra el historial pero no hay señal de "bot roto" (el archivo simplemente deja de actualizarse) | Con el guard nuevo el fallo ya es ruidoso por Telegram/mail; opcional: timestamp de último run en el dashboard |

## Segunda fuente: Amadeus (implementada, falta activarla)

Adapter completo en `src/adapters/amadeus.py`, registrado en el engine y en las
4 rutas. **Hasta que cargues credenciales, se saltea con un log claro y no
molesta.** Para activarlo:

1. Crear cuenta gratis en <https://developers.amadeus.com> → *Create New App* →
   copiás **API Key** (client id) y **API Secret**.
2. En GitHub: repo → Settings → Secrets and variables → Actions → New repository
   secret: `AMADEUS_CLIENT_ID` y `AMADEUS_CLIENT_SECRET`.
3. (Opcional) Variable `AMADEUS_ENV=production` para datos reales. El default es
   `test`: gratis pero con datos de prueba y cuota mensual chica (~2.000 llamadas;
   ojo: el bot hace ~2.160/mes con la config actual — si la cuota muerde, subí
   `scan_step_days` o bajá la frecuencia del cron).
4. Local: agregar las mismas variables al `.env`.

## Otros conectores evaluados (y por qué no)

| Fuente | Veredicto |
|--------|-----------|
| **SerpApi / SearchApi** (Google Flights como servicio) | Free tier ~100 búsquedas/mes vs ~2.160 que necesitamos. Solo útil como fallback puntual; fast-flights v3 trae integración nativa con SearchApi si un día Google bloquea el scraping directo |
| **Travelpayouts / Aviasales Data API** | Gratis, pero devuelve precios cacheados (no tiempo real). Podría servir como señal de tendencia; no como fuente de alertas |
| **Kiwi Tequila** | Cerrado a registros nuevos desde 2024 |
| **Skyscanner** | Solo partners comerciales |
| **Duffel** | Orientado a agencias (venta), overkill para alertas |

## Reglas que deja esta auditoría

- **Nunca `>=` sin techo de major** en dependencias de scraping/APIs de terceros.
- **"0 resultados" es un estado de error**, no un run exitoso: todo pipeline de
  datos necesita un guard de volumen mínimo.
