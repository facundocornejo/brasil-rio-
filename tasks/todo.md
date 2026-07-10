# TODO — Bot pasajes Río

## Estado actual (08/07/2026)

Bot **reparado y verificado**: migrado a fast-flights v3, guard anti-fallo-silencioso,
adapter de Amadeus listo (esperando credenciales). Ver `AUDITORIA.md` para el detalle.

## Pendiente

- [ ] Decidir qué hacer con los scripts sueltos rotos (`find_cheap.py`,
      `show_cheapest.py`, `send_top4.py`) — ver AUDITORIA.md hallazgo #1
- [ ] Opcional: timestamp de último run en el dashboard (hallazgo #5)
- [ ] Verificar adapter Travelpayouts contra la API real (token ya cargado como
      secret; falta run en vivo) y después run de producción en Actions

## Cerrado sin hacer (10/07/2026)

- [x] ~~Amadeus como 2ª fuente~~ — **INVIABLE**: Amadeus decomisiona el portal
      self-service el 17/07/2026 y los registros nuevos estaban pausados desde
      ~marzo 2026; no se puede crear cuenta. El adapter queda como código muerto
      documentado (`src/adapters/amadeus.py`). Ver AUDITORIA.md §Amadeus

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
