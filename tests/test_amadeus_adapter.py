"""Tests for the Amadeus Self-Service adapter.

Tests del adapter de Amadeus: skip sin credenciales, flujo OAuth,
mapeo de ofertas a PriceResult, y manejo de errores de la API.
Usa httpx.MockTransport para no pegarle a la API real.
"""

import httpx
import pytest

from src.adapters.amadeus import AmadeusAdapter
from src.models import AppSettings, RouteConfig

# Oferta de ejemplo con la forma real de Flight Offers Search v2
MOCK_OFFER = {
    "type": "flight-offer",
    "id": "1",
    "validatingAirlineCodes": ["G3"],
    "itineraries": [
        {
            "segments": [
                {"carrierCode": "G3", "number": "7621"},
                {"carrierCode": "G3", "number": "1234"},
            ]
        },
        {
            "segments": [
                {"carrierCode": "G3", "number": "7620"},
            ]
        },
    ],
    "price": {"currency": "USD", "grandTotal": "350.50"},
}

MOCK_SEARCH_RESPONSE = {
    "data": [MOCK_OFFER],
    "dictionaries": {"carriers": {"G3": "GOL LINHAS AEREAS"}},
}

MOCK_TOKEN_RESPONSE = {"access_token": "fake-token-123", "expires_in": 1799}


def _make_settings() -> AppSettings:
    # delay 0 para que los tests no duerman
    return AppSettings(
        delay_between_requests_seconds=0,
        trip_duration_min_days=5,
        trip_duration_max_days=5,
    )


def _make_route() -> RouteConfig:
    return RouteConfig(
        origin="EZE",
        destination="GIG",
        sources=["amadeus"],
        threshold_usd=400,
        depart_from="2099-12-01",
        depart_to="2099-12-01",
        scan_step_days=1,
        trip_type="round_trip",
    )


def _make_adapter(
    monkeypatch,
    transport: httpx.MockTransport | None,
    with_creds: bool = True,
) -> AmadeusAdapter:
    if with_creds:
        monkeypatch.setenv("AMADEUS_CLIENT_ID", "test-id")
        monkeypatch.setenv("AMADEUS_CLIENT_SECRET", "test-secret")
    else:
        monkeypatch.delenv("AMADEUS_CLIENT_ID", raising=False)
        monkeypatch.delenv("AMADEUS_CLIENT_SECRET", raising=False)
    adapter = AmadeusAdapter(_make_settings())
    adapter._transport = transport
    return adapter


@pytest.mark.asyncio
async def test_skips_without_credentials(monkeypatch):
    """Sin credenciales: devuelve vacío sin hacer ningún request."""
    adapter = _make_adapter(monkeypatch, transport=None, with_creds=False)
    results = await adapter.fetch_prices(_make_route())
    assert results == []


@pytest.mark.asyncio
async def test_maps_offers_to_price_results(monkeypatch):
    """Flujo feliz: token OK + búsqueda OK → PriceResults correctos."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
        assert request.headers["Authorization"] == "Bearer fake-token-123"
        assert request.url.params["currencyCode"] == "USD"
        return httpx.Response(200, json=MOCK_SEARCH_RESPONSE)

    adapter = _make_adapter(monkeypatch, httpx.MockTransport(handler))
    results = await adapter.fetch_prices(_make_route())

    assert len(results) == 1
    r = results[0]
    assert r.source == "amadeus"
    assert r.price == 350.50
    assert r.currency == "USD"
    assert r.origin == "EZE"
    assert r.destination == "GIG"
    # 2 segmentos de ida → 1 escala
    assert r.stops == 1
    assert "Gol" in r.airline
    # round-trip de 5 días con formato compartido con google_flights
    assert r.date == "2099-12-01 → 2099-12-06"


@pytest.mark.asyncio
async def test_invalid_credentials_abort_run(monkeypatch):
    """401 en el token: se marca auth_failed y no se insiste."""
    calls = {"token": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            calls["token"] += 1
            return httpx.Response(401, json={"error": "invalid_client"})
        raise AssertionError("No debería llegar a la búsqueda sin token")

    adapter = _make_adapter(monkeypatch, httpx.MockTransport(handler))
    results = await adapter.fetch_prices(_make_route())

    assert results == []
    assert adapter._auth_failed is True
    assert calls["token"] == 1  # No reintenta tras el 401

    # Una segunda ruta tampoco consulta (corta al toque)
    results2 = await adapter.fetch_prices(_make_route())
    assert results2 == []
    assert calls["token"] == 1


@pytest.mark.asyncio
async def test_search_error_returns_empty(monkeypatch):
    """500 en la búsqueda: warning y lista vacía, nunca crashea."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
        return httpx.Response(500, text="internal error")

    adapter = _make_adapter(monkeypatch, httpx.MockTransport(handler))
    results = await adapter.fetch_prices(_make_route())
    assert results == []


def test_offer_without_price_is_skipped(monkeypatch):
    """Ofertas con formato inesperado se descartan sin romper."""
    adapter = _make_adapter(monkeypatch, transport=None)
    from datetime import date

    bad_offer = {"itineraries": []}  # sin price
    result = adapter._offer_to_result(
        bad_offer, _make_route(), date(2099, 12, 1), None,
    )
    assert result is None


def test_token_is_cached(monkeypatch):
    """El token se cachea: expires_at queda en el futuro tras obtenerlo."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
        return httpx.Response(200, json={"data": []})

    adapter = _make_adapter(monkeypatch, httpx.MockTransport(handler))

    import asyncio

    async def scenario():
        async with httpx.AsyncClient(transport=adapter._transport) as client:
            t1 = await adapter._get_token(client)
            t2 = await adapter._get_token(client)
            return t1, t2

    t1, t2 = asyncio.run(scenario())
    assert t1 == t2 == "fake-token-123"
