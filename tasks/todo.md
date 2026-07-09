# TODO — Bot pasajes Río

## Estado actual (08/07/2026)

Bot **reparado y verificado**: migrado a fast-flights v3, guard anti-fallo-silencioso,
adapter de Amadeus listo (esperando credenciales). Ver `AUDITORIA.md` para el detalle.

## Pendiente

- [ ] **Facu**: crear cuenta en developers.amadeus.com y cargar secrets
      `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` en GitHub (pasos en AUDITORIA.md §Amadeus).
      Nota 09/07: se buscó en todos los .env de B:\ y NO hay credenciales previas —
      hay que registrarse de cero
- [ ] Decidir qué hacer con los scripts sueltos rotos (`find_cheap.py`,
      `show_cheapest.py`, `send_top4.py`) — ver AUDITORIA.md hallazgo #1
- [ ] Opcional: timestamp de último run en el dashboard (hallazgo #5)

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
