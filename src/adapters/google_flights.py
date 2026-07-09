"""Google Flights price adapter via fast-flights library.

Usa la librería fast-flights (v3) para scrapear Google Flights. Cubre TODAS
las aerolíneas en cualquier ruta. Funciona decodificando parámetros
Protobuf de las URLs de Google Flights y parseando los datos JS de la página.

Install: pip install "fast-flights>=3.0.2,<4"
Docs: https://github.com/AWeirdDev/flights
"""

import asyncio
import logging
import multiprocessing
import re
from datetime import date, timedelta

from src.adapters.base import BaseAdapter
from src.adapters.scan_dates import DEFAULT_DAYS_BETWEEN_SCANS, build_scan_dates
from src.models import AppSettings, PriceResult, RouteConfig

logger = logging.getLogger(__name__)

# Timeout por request en segundos (evita que se cuelgue indefinidamente)
# Usa multiprocessing para poder matar el proceso de verdad
REQUEST_TIMEOUT_SECONDS = 45

# Moneda e idioma que le pedimos a Google explícitamente (v3 lo soporta).
# Así los precios llegan siempre en USD y no hay que adivinar la moneda.
QUERY_CURRENCY = "USD"
QUERY_LANGUAGE = "en-US"


def _parse_price(price_str: str | None) -> float | None:
    """Parse price string to float.

    Fallback por si un precio llega como string tipo "$1,234", "ARS 500,000",
    "€ 450", etc. (fast-flights v3 ya devuelve int). Este parser extrae el número.

    Ejemplos:
        "$1,234" → 1234.0
        "ARS 500,000" → 500000.0
        "€450" → 450.0
        None → None
    """
    if not price_str:
        return None

    # Remover todo excepto dígitos, puntos y comas
    cleaned = re.sub(r"[^\d.,]", "", str(price_str))

    if not cleaned:
        return None

    # Manejar formato con coma como separador de miles (1,234 o 500,000)
    # y punto como separador decimal (1,234.56)
    if "," in cleaned and "." in cleaned:
        # Tiene ambos: 1,234.56 → quitar comas
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # Solo comas: podría ser 1,234 (miles) o 1,50 (decimal europeo)
        parts = cleaned.split(",")
        if len(parts[-1]) == 3:
            # Separador de miles: 1,234 o 500,000
            cleaned = cleaned.replace(",", "")
        else:
            # Separador decimal europeo: 1,50
            cleaned = cleaned.replace(",", ".")

    try:
        return float(cleaned)
    except ValueError:
        logger.warning("No se pudo parsear precio: '%s' → '%s'", price_str, cleaned)
        return None


def _detect_currency(price_str: str | None) -> str:
    """Detect currency from price string.

    Fallback para precios que llegan como string (v3 devuelve int y la moneda
    la pedimos explícita con QUERY_CURRENCY). Detecta según símbolo o prefijo.
    """
    if not price_str:
        return QUERY_CURRENCY

    price_upper = str(price_str).upper()
    if "ARS" in price_upper or "AR$" in price_upper:
        return "ARS"
    if "€" in price_upper or "EUR" in price_upper:
        return "EUR"
    # USD es el default para Google Flights en rutas internacionales
    return QUERY_CURRENCY


def _serialize_flights(result: list, airline_names: dict[str, str]) -> list[dict]:
    """Serialize fast-flights v3 Flights objects to plain dicts.

    Convierte objetos Flights de la v3 a dicts simples para poder pasarlos
    entre procesos (multiprocessing.Queue no banca objetos complejos).
    Duck-typed a propósito: no importa fast_flights, así es testeable.
    """
    flights_data: list[dict] = []
    for f in result:
        # airlines viene como lista de códigos IATA; mapear a nombres si se puede
        codes = list(f.airlines or [])
        names = [airline_names.get(c, c) for c in codes]
        # Escalas = segmentos del itinerario mostrado menos 1
        segments = list(f.flights or [])
        flights_data.append({
            "name": ", ".join(names) if names else None,
            "price": f.price,
            "stops": max(len(segments) - 1, 0),
        })
    return flights_data


def _fetch_in_subprocess(
    origin: str,
    destination: str,
    scan_date_iso: str,
    return_date_iso: str | None,
    trip: str,
    result_queue: multiprocessing.Queue,
) -> None:
    """Run get_flights in a separate process.

    Se ejecuta en un proceso hijo para poder matarlo de verdad si se cuelga.
    Los threads de Python no se pueden matar, pero los procesos sí.

    Pone en la queue una tupla (status, data):
    - ("ok", list[dict])   → precios encontrados
    - ("empty", [])        → respuesta válida pero sin vuelos (no es error)
    - ("error", str)       → falló la consulta
    """
    try:
        from fast_flights import (
            FlightQuery,
            FlightsNotFound,
            Passengers,
            create_query,
            get_flights,
        )

        flight_queries = [
            FlightQuery(
                date=scan_date_iso,
                from_airport=origin,
                to_airport=destination,
            ),
        ]
        if return_date_iso:
            flight_queries.append(
                FlightQuery(
                    date=return_date_iso,
                    from_airport=destination,
                    to_airport=origin,
                ),
            )

        query = create_query(
            flights=flight_queries,
            trip=trip,
            seat="economy",
            passengers=Passengers(adults=1),
            currency=QUERY_CURRENCY,
            language=QUERY_LANGUAGE,
        )

        try:
            result = get_flights(query)
        except FlightsNotFound:
            # Google respondió bien pero no hay vuelos para esa fecha:
            # es una respuesta válida, no un error de scraping.
            result_queue.put(("empty", []))
            return

        # Mapeo código de aerolínea → nombre (viene en la metadata del resultado)
        airline_names: dict[str, str] = {}
        metadata = getattr(result, "metadata", None)
        if metadata is not None:
            airline_names = {a.code: a.name for a in metadata.airlines}

        flights_data = _serialize_flights(result, airline_names)
        result_queue.put(("ok", flights_data) if flights_data else ("empty", []))
    except Exception as e:
        result_queue.put(("error", str(e)))


class GoogleFlightsAdapter(BaseAdapter):
    """Adapter for Google Flights via fast-flights library."""

    def __init__(self, settings: AppSettings) -> None:
        super().__init__(settings)
        self._available = True  # Se pone en False si fast-flights no está instalado
        self._consecutive_failures = 0
        # Máximo de fallos consecutivos antes de abortar esta ruta
        self._max_consecutive_failures = 5

    @property
    def source_name(self) -> str:
        return "google_flights"

    async def _fetch_single_date(
        self,
        route: RouteConfig,
        scan_date: date,
        return_days: int,
        is_round_trip: bool,
    ) -> tuple[str, list[dict]]:
        """Fetch flights for a single date using a subprocess with hard timeout.

        Usa multiprocessing en vez de threads para poder matar el proceso
        si se cuelga (los threads de Python no se pueden matar).

        Devuelve (status, data): status es "ok", "empty" o "error".
        """
        trip = "round-trip" if is_round_trip else "one-way"
        return_date_iso = None
        if is_round_trip:
            return_date_iso = (scan_date + timedelta(days=return_days)).isoformat()

        result_queue: multiprocessing.Queue = multiprocessing.Queue()
        proc = multiprocessing.Process(
            target=_fetch_in_subprocess,
            args=(
                route.origin,
                route.destination,
                scan_date.isoformat(),
                return_date_iso,
                trip,
                result_queue,
            ),
        )
        proc.start()

        # Esperar resultado con timeout real (mata el proceso si se cuelga)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(result_queue.get, timeout=REQUEST_TIMEOUT_SECONDS),
                timeout=REQUEST_TIMEOUT_SECONDS + 5,
            )
        except (asyncio.TimeoutError, Exception):
            # Matar el proceso de verdad
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=5)
            logger.warning(
                "Google Flights: timeout (%ds) en %s→%s fecha %s, salteando...",
                REQUEST_TIMEOUT_SECONDS, route.origin, route.destination, scan_date,
            )
            return ("error", [])
        finally:
            # Asegurar que el proceso hijo no quede zombie
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=5)

        status, data = result
        if status == "error":
            logger.warning(
                "Google Flights: error en %s→%s fecha %s: %s",
                route.origin, route.destination, scan_date, data,
            )
            return ("error", [])

        return (status, data)

    @staticmethod
    def _build_scan_dates(route: RouteConfig, today: date) -> list[date]:
        """Build the list of departure dates to scan (delegado al helper compartido)."""
        return build_scan_dates(route, today, DEFAULT_DAYS_BETWEEN_SCANS)

    async def fetch_prices(self, route: RouteConfig) -> list[PriceResult]:
        """Fetch prices from Google Flights for specific dates.

        Escanea fechas durante months_ahead meses. Para round-trip, usa la
        duración configurada en settings (trip_duration_min/max_days).
        """
        # Intentar importar fast_flights (verificar que está instalado)
        try:
            import fast_flights  # noqa: F401
        except ImportError:
            if self._available:
                logger.error(
                    "fast-flights no está instalado. "
                    'Ejecutá: pip install "fast-flights>=3.0.2,<4"'
                )
                self._available = False
            return []

        results: list[PriceResult] = []
        today = date.today()

        # Generar fechas a escanear. Si la ruta define una ventana explícita
        # (depart_from/depart_to), se escanea día-por-día dentro de ese rango.
        # Si no, se usa el modo clásico: months_ahead + active_months.
        dates_to_scan: list[date] = self._build_scan_dates(route, today)

        # Determinar tipo de viaje y duraciones a escanear
        is_round_trip = route.trip_type == "round_trip"

        if is_round_trip:
            # Escanear cada duración entera en [min, max] días (ej: 8, 9, 10).
            # Así no nos perdemos un precio bueno por un día más o menos de estadía.
            durations = list(range(
                self.settings.trip_duration_min_days,
                self.settings.trip_duration_max_days + 1,
            ))
        else:
            durations = [0]  # one-way: la duración no aplica

        # Construir lista de consultas (fecha_salida, duración). Cada combinación
        # es un request independiente a Google Flights.
        jobs: list[tuple[date, int]] = [
            (scan_date, dur) for scan_date in dates_to_scan for dur in durations
        ]

        logger.info(
            "Google Flights: escaneando %s → %s (%d fechas × %d duración%s = %d consultas%s)",
            route.origin, route.destination,
            len(dates_to_scan), len(durations),
            "es" if len(durations) != 1 else "",
            len(jobs),
            f", vuelta {durations[0]}-{durations[-1]} días" if is_round_trip else "",
        )

        self._consecutive_failures = 0

        for scan_date, return_days in jobs:
            # Si hay muchos fallos consecutivos, abortar esta ruta
            if self._consecutive_failures >= self._max_consecutive_failures:
                logger.warning(
                    "Google Flights: %d fallos consecutivos en %s→%s, abortando ruta.",
                    self._consecutive_failures, route.origin, route.destination,
                )
                break

            try:
                status, flights_data = await self._fetch_single_date(
                    route, scan_date, return_days, is_round_trip,
                )

                # Solo los errores reales suman al contador de fallos.
                # "empty" (sin vuelos para la fecha) es una respuesta sana.
                if status == "error":
                    self._consecutive_failures += 1
                else:
                    self._consecutive_failures = 0

                # Parsear cada vuelo encontrado
                for flight in flights_data:
                    raw_price = flight.get("price")
                    if isinstance(raw_price, (int, float)):
                        # v3 devuelve el precio como número, en QUERY_CURRENCY
                        price: float | None = float(raw_price)
                        currency = QUERY_CURRENCY
                    else:
                        # Fallback defensivo por si llega como string
                        price = _parse_price(raw_price)
                        currency = _detect_currency(raw_price)
                    if price is None:
                        continue

                    # Formatear fecha con duración del viaje
                    date_display = scan_date.isoformat()
                    if is_round_trip:
                        return_date = scan_date + timedelta(days=return_days)
                        date_display = f"{scan_date.isoformat()} → {return_date.isoformat()}"

                    results.append(
                        PriceResult(
                            source=self.source_name,
                            airline=flight.get("name") or "Unknown",
                            origin=route.origin,
                            destination=route.destination,
                            date=date_display,
                            price=price,
                            currency=currency,
                            stops=int(flight.get("stops") or 0),
                        )
                    )

            except Exception as e:
                self._consecutive_failures += 1
                logger.warning(
                    "Google Flights: error al consultar %s→%s fecha %s: %s",
                    route.origin, route.destination, scan_date, e,
                )

            # Delay entre requests para evitar rate limiting de Google
            await asyncio.sleep(self.settings.delay_between_requests_seconds)

        logger.info(
            "Google Flights: encontrados %d precios para %s → %s",
            len(results), route.origin, route.destination,
        )
        return results
