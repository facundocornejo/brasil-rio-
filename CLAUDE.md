# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Estado actual (09/07/2026)

Bot **reparado y verificado en producción** tras 3.5 semanas de outage silencioso
(fast-flights 3.0 rompió la API; detalle completo en `AUDITORIA.md`). Migrado a
fast-flights v3, deps pinneadas con techo, y guard anti-fallo-silencioso: 0 precios
→ alerta Telegram + exit 1. Run verificado: 178 precios, 12 alertas reales.

- **Siguiente paso**: activar Amadeus como 2ª fuente — el adapter ya está hecho
  (`src/adapters/amadeus.py`), falta que Facu se registre en developers.amadeus.com
  y cargue `AMADEUS_CLIENT_ID`/`AMADEUS_CLIENT_SECRET` como secrets de GitHub
  (no hay credenciales previas en ningún .env de B:). Pasos en `AUDITORIA.md`.
- Pendientes menores en `tasks/todo.md` (scripts sueltos rotos, dashboard).

## Model usage (Opus 4.6 / Sonnet 4.6 solamente)
- Default: **Sonnet 4.6** (`claude-sonnet-4-6`) — edits de código, tests, scripts, refactors chicos, ejecutar comandos, lectura/grep de código.
- Escalar a **Opus 4.6** (`/model claude-opus-4-6`) solo para: planning no-trivial, diseño arquitectónico, debugging no-obvio, decisiones de diseño.
- **No usar ningún otro modelo** — en particular NO usar Opus 4.7 (`opus`) ni Haiku. Si Claude Code arranca con otro default, cambiar con `/model claude-sonnet-4-6`.

## Project
Automated Telegram bot that checks flight prices and sends alerts when prices drop below configurable thresholds. Runs on GitHub Actions cron, costs $0.

**Este repo es un clon enfocado en un viaje específico a Río de Janeiro (GIG)** con amigos: orígenes EZE/AEP/ROS/COR, ida 1-3 dic 2026 y vuelta ~7-9 dic 2026 (config en `config/routes-rio.json`). Es un fork del bot original (viaje a Recife); comparten el código de `src/` pero cada uno tiene su propia config, workflow y repositorio de GitHub.

## Conventions
- Python 3.11+, type hints required on all public functions
- Code, variables, functions, class names, docstrings: **English**
- Inline comments and explanations: **Spanish**
- Linter: ruff (`ruff check src/`)
- Tests: pytest (`pytest tests/ -v`)
- Async: use `httpx` (async) for HTTP calls, `asyncio` for orchestration

## Key Commands
```bash
python -m src.main              # Run the bot (requires .env with Telegram tokens)
python -m src.main --dry-run    # Run without sending Telegram alerts (prints to console)
ruff check src/                 # Linting
pytest tests/ -v                # Run tests
```

## Architecture
Adapter pattern: each data source has its own module in `src/adapters/` returning standardized `PriceResult` objects. The engine orchestrates adapters, the checker compares against thresholds, and the notifier sends Telegram alerts. A state manager prevents duplicate alerts within a configurable cooldown period.

## Environment Variables (.env)
- `TELEGRAM_BOT_TOKEN` — Bot token from @BotFather
- `TELEGRAM_CHAT_ID` — Your chat ID for receiving alerts
- `DRY_RUN` — Set to "true" for testing without sending messages

## Data Sources
1. **Level Airlines** — GET, no auth, returns USD prices for Europe routes
2. **Sky Airline** — POST, public API key (Azure APIM), returns ARS prices for regional routes
3. **Google Flights** — via `fast-flights` library, covers all airlines worldwide

## Testing a Single Adapter
```bash
pytest tests/test_level_adapter.py -v    # Test Level adapter only
pytest tests/test_sky_adapter.py -v      # Test Sky adapter only
pytest tests/test_checker.py -v          # Test price threshold logic
pytest tests/test_checker.py::test_cross_currency_usd_to_ars -v  # Single test
```

## Adding a New Adapter
1. Create `src/adapters/<airline>.py` implementing `BaseAdapter` from `src/adapters/base.py`
2. Implement `async fetch_prices(route: RouteConfig) -> list[PriceResult]`
3. Register the adapter in `src/engine.py` (see existing adapter initialization)
4. Add the source name to routes in `config/routes.json`

## Configuration
Routes and thresholds are in `config/routes.json`. The `manual_usd_to_ars` setting controls cross-currency threshold comparison. Alert state is persisted in `data/alert_state.json` (auto-generated, cached by GitHub Actions).
