# TODO — Bot pasajes Río

## Estado actual (10/07/2026)

Bot operativo con **doble fuente**: Google Flights (en vivo) + Travelpayouts/Aviasales
(cache, señal de tendencia). Amadeus muerto (portal cerrado). Ver CLAUDE.md §Estado.

## Pendiente

- [ ] **Verificar el próximo run de Actions de Río** (cron 03:00/15:00 UTC): que salga
      verde y el log muestre `travelpayouts: N precios` (el dispatch manual de Facu
      no llegó a ejecutarse; Recife ya quedó verificado en producción)
- [ ] Decidir qué hacer con los scripts sueltos rotos (`find_cheap.py`,
      `show_cheapest.py`, `send_top4.py`) — ver AUDITORIA.md hallazgo #1
- [ ] Opcional: timestamp de último run en el dashboard (hallazgo #5)

## Hecho (10/07/2026)

- [x] Confirmado cierre de Amadeus self-service (17/07/2026, registros ya pausados)
      → adapter queda como código muerto documentado
- [x] Cuenta de Travelpayouts creada + Drive verificado en el dashboard (snippet
      en docs/index.html, commit b3c9e16)
- [x] Adapter Travelpayouts (`src/adapters/travelpayouts.py`) + 10 tests, commits
      9e893f7 y ab5fbd0. Filtro de duración ESTRICTO acá (decisión de Facu)
- [x] Fix: `travelpayouts` faltaba en VALID_SOURCES (descarte silencioso)
- [x] Fix semántica: el cache filtra por ventana de ruta, no por paso de escaneo
      (`departure_in_window` en scan_dates.py)
- [x] Verificado en vivo: moneda USD OK, EZE→GIG dic tiene ofertas USD 272-286
      pero con vueltas de ~14 días (estricto → 0 resultados hoy, esperado)
- [x] Port completo al bot de Recife (flightbot f782aa7, modo RELAJADO) +
      secret cargado + **verificado en producción**: 567 precios, 13 alertas
      reales a Telegram (incl. AEP→REC USD 330 directo detectado por Travelpayouts)

## Cerrado sin hacer (10/07/2026)

- [x] ~~Amadeus como 2ª fuente~~ — **INVIABLE**: portal self-service decomisionado
      el 17/07/2026, registros pausados desde ~marzo 2026. Ver AUDITORIA.md §Amadeus

## Hecho (08/07/2026)

- [x] Auditoría completa (AUDITORIA.md)
- [x] Causa raíz del outage 14/06→08/07: fast-flights 3.0 rompió la API, pin sin techo
- [x] Migración a fast-flights v3 + pin `>=3.0.2,<4`
- [x] Guard de 0 precios: Telegram + exit 1
- [x] Adapter Amadeus + tests (esperando credenciales)
- [x] requirements-dev.txt separado
- [x] Docs/dashboard actualizados (12h, routes-rio.json, link del repo)
- [x] Verificación real: dry-run con 153 precios, alertas COR→GIG USD 340
- [x] Run de producción verificado (28990559942): verde, 178 precios, 12 alertas
      reales enviadas a Telegram
