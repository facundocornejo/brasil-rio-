"""Amadeus Self-Service API price adapter.

**MUERTO — no activable (10/07/2026).** Amadeus decomisionó el portal
self-service el 17/07/2026: las API keys self-service quedaron deshabilitadas
y los registros nuevos estaban pausados desde ~marzo 2026, así que nunca se
pudieron obtener credenciales. Solo sobreviven las Enterprise APIs (contrato
comercial). Se conserva como referencia de implementación de un adapter con
OAuth2 + rate limiting por si aparece una fuente equivalente.

API real de Amadeus (sin scraping): Flight Offers Search. Cubre las
aerolíneas que operan AR→BR (GOL, LATAM, Aerolíneas, JetSmart, Flybondi).

Requería credenciales de https://developers.amadeus.com (ya no disponibles):
- AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET (env vars o GitHub secrets)
- AMADEUS_ENV: "test" (default, entorno de prueba) o "production"

Si no hay credenciales configuradas, el adapter se saltea con un log claro
(no rompe el run — Google Flights sigue siendo la fuente principal).
"""

import asyncio
import logging
import os
import time
from datetime import date, timedelta

import httpx

from src.adapters.base import BaseAdapter
from src.adapters.scan_dates import DEFAULT_DAYS_BETWEEN_SCANS, build_scan_dates
from src.models import AppSettings, PriceResult, RouteConfig

logger = logging.getLogger(__name__)

# Hosts por entorno. El entorno test es gratis pero con datos de prueba
# y cuota mensual limitada; production tiene datos reales.
BASE_URLS = {
    "test": "https://test.api.amadeus.com",
    "production": "https://api.amadeus.com",
}

TOKEN_PATH = "/v1/security/oauth2/token"
SEARCH_PATH = "/v2/shopping/flight-offers"

# Máximo de ofertas por consulta (una consulta = un request contra la cuota)
MAX_OFFERS_PER_QUERY = 20

REQUEST_TIMEOUT_SECONDS = 30

# Margen de seguridad antes de que expire el token OAuth (en segundos)
TOKEN_EXPIRY_MARGIN_SECONDS = 60


class AmadeusAdapter(BaseAdapter):
    """Adapter for the Amadeus Self-Service Flight Offers Search API."""

    def __init__(self, settings: AppSettings) -> None:
        super().__init__(settings)
        self._client_id = os.getenv("AMADEUS_CLIENT_ID", "").strip()
        self._client_secret = os.getenv("AMADEUS_CLIENT_SECRET", "").strip()
        env = os.getenv("AMADEUS_ENV", "test").strip().lower()
        self._base_url = BASE_URLS.get(env, BASE_URLS["test"])
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._warned_no_credentials = False
        self._auth_failed = False
        # Transporte inyectable para tests (httpx.MockTransport)
        self._transport: httpx.AsyncBaseTransport | None = None

    @property
    def source_name(self) -> str:
        return "amadeus"

    def _has_credentials(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def _get_token(self, client: httpx.AsyncClient) -> str | None:
        """Get (or refresh) the OAuth2 access token.

        Amadeus usa client-credentials: el token dura ~30 min, lo cacheamos
        en la instancia y lo renovamos con margen antes de que expire.
        """
        now = time.monotonic()
        if self._token and now < self._token_expires_at:
            return self._token

        try:
            response = await client.post(
                f"{self._base_url}{TOKEN_PATH}",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as e:
            logger.warning("Amadeus: error de red al pedir token: %s", e)
            return None

        if response.status_code == 401:
            # Credenciales inválidas: no insistir en esta corrida
            self._auth_failed = True
            logger.error(
                "Amadeus: credenciales rechazadas (401). Verificá "
                "AMADEUS_CLIENT_ID/AMADEUS_CLIENT_SECRET."
            )
            return None
        if response.status_code != 200:
            logger.warning(
                "Amadeus: token endpoint devolvió %d: %s",
                response.status_code, response.text[:200],
            )
            return None

        payload = response.json()
        self._token = payload.get("access_token")
        expires_in = int(payload.get("expires_in", 1799))
        self._token_expires_at = now + expires_in - TOKEN_EXPIRY_MARGIN_SECONDS
        return self._token

    async def _search_offers(
        self,
        client: httpx.AsyncClient,
        token: str,
        route: RouteConfig,
        depart: date,
        return_date: date | None,
    ) -> list[dict]:
        """Query flight offers for a single date combination.

        Devuelve la lista de ofertas cruda de la API (puede ser vacía).
        Lanza httpx.HTTPError ante errores de red; el caller decide.
        """
        params: dict[str, str | int] = {
            "originLocationCode": route.origin,
            "destinationLocationCode": route.destination,
            "departureDate": depart.isoformat(),
            "adults": 1,
            "currencyCode": "USD",
            "max": MAX_OFFERS_PER_QUERY,
        }
        if return_date is not None:
            params["returnDate"] = return_date.isoformat()

        response = await client.get(
            f"{self._base_url}{SEARCH_PATH}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )

        if response.status_code == 401:
            # Token vencido a mitad de corrida: invalidar para renovar
            self._token = None
            self._token_expires_at = 0.0
            logger.warning("Amadeus: token expirado (401), se renovará.")
            return []
        if response.status_code == 429:
            logger.warning("Amadeus: rate limit (429), salteando consulta.")
            return []
        if response.status_code != 200:
            logger.warning(
                "Amadeus: búsqueda devolvió %d para %s→%s %s: %s",
                response.status_code, route.origin, route.destination,
                depart, response.text[:200],
            )
            return []

        payload = response.json()
        offers = payload.get("data", [])
        # dictionaries.carriers mapea código IATA → nombre de aerolínea
        carriers = (payload.get("dictionaries") or {}).get("carriers", {})
        for offer in offers:
            offer["_carriers"] = carriers
        return offers

    def _offer_to_result(
        self,
        offer: dict,
        route: RouteConfig,
        depart: date,
        return_date: date | None,
    ) -> PriceResult | None:
        """Map a raw Amadeus offer to a standardized PriceResult."""
        try:
            price = float(offer["price"]["grandTotal"])
            currency = offer["price"].get("currency", "USD")
            itineraries = offer.get("itineraries", [])
            segments = itineraries[0].get("segments", []) if itineraries else []
            stops = max(len(segments) - 1, 0)

            carriers: dict[str, str] = offer.get("_carriers", {})
            codes = offer.get("validatingAirlineCodes") or []
            if not codes and segments:
                codes = [segments[0].get("carrierCode", "")]
            airline = ", ".join(
                carriers.get(c, c).title() if carriers.get(c) else c
                for c in codes if c
            ) or "Unknown"
        except (KeyError, IndexError, TypeError, ValueError) as e:
            logger.debug("Amadeus: oferta con formato inesperado, salteada: %s", e)
            return None

        # Mismo formato de fecha que google_flights para que la deduplicación
        # de alertas (route_key) funcione entre fuentes.
        date_display = depart.isoformat()
        if return_date is not None:
            date_display = f"{depart.isoformat()} → {return_date.isoformat()}"

        return PriceResult(
            source=self.source_name,
            airline=airline,
            origin=route.origin,
            destination=route.destination,
            date=date_display,
            price=price,
            currency=currency,
            stops=stops,
        )

    async def fetch_prices(self, route: RouteConfig) -> list[PriceResult]:
        """Fetch prices from Amadeus for the route's scan window."""
        if not self._has_credentials():
            if not self._warned_no_credentials:
                logger.info(
                    "Amadeus: sin credenciales (AMADEUS_CLIENT_ID/SECRET), "
                    "fuente salteada."
                )
                self._warned_no_credentials = True
            return []
        if self._auth_failed:
            return []

        results: list[PriceResult] = []
        today = date.today()
        dates_to_scan = build_scan_dates(route, today, DEFAULT_DAYS_BETWEEN_SCANS)

        is_round_trip = route.trip_type == "round_trip"
        if is_round_trip:
            durations = list(range(
                self.settings.trip_duration_min_days,
                self.settings.trip_duration_max_days + 1,
            ))
        else:
            durations = [0]

        jobs: list[tuple[date, int]] = [
            (scan_date, dur) for scan_date in dates_to_scan for dur in durations
        ]
        logger.info(
            "Amadeus: escaneando %s → %s (%d consultas)",
            route.origin, route.destination, len(jobs),
        )

        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=self._transport,
        ) as client:
            for scan_date, return_days in jobs:
                if self._auth_failed:
                    break

                token = await self._get_token(client)
                if token is None:
                    if self._auth_failed:
                        break
                    continue  # error transitorio de token: probar próxima consulta

                return_date = (
                    scan_date + timedelta(days=return_days) if is_round_trip else None
                )

                try:
                    offers = await self._search_offers(
                        client, token, route, scan_date, return_date,
                    )
                except httpx.HTTPError as e:
                    logger.warning(
                        "Amadeus: error de red en %s→%s %s: %s",
                        route.origin, route.destination, scan_date, e,
                    )
                    offers = []

                for offer in offers:
                    result = self._offer_to_result(offer, route, scan_date, return_date)
                    if result is not None:
                        results.append(result)

                await asyncio.sleep(self.settings.delay_between_requests_seconds)

        logger.info(
            "Amadeus: encontrados %d precios para %s → %s",
            len(results), route.origin, route.destination,
        )
        return results
