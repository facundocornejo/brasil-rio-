"""Tests for the Google Flights adapter (fast-flights v3).

Tests del mapeo de resultados de la v3 a dicts serializables, de los
parsers de fallback, y del armado de fechas a escanear.
No pega a Google: usa objetos fake con la misma forma que fast-flights v3.
"""

from dataclasses import dataclass, field
from datetime import date

from src.adapters.google_flights import (
    _detect_currency,
    _parse_price,
    _serialize_flights,
)
from src.adapters.scan_dates import build_scan_dates
from src.models import RouteConfig


# === Fakes con la forma de fast_flights v3 (Flights / SingleFlight) ===

@dataclass
class FakeSegment:
    plane_type: str = "Boeing 737"


@dataclass
class FakeFlights:
    price: int = 500
    airlines: list[str] = field(default_factory=lambda: ["G3"])
    flights: list[FakeSegment] = field(default_factory=lambda: [FakeSegment()])


def test_serialize_flights_maps_fields():
    """price/airlines/stops se serializan a dicts simples."""
    result = [
        FakeFlights(price=350, airlines=["G3"], flights=[FakeSegment(), FakeSegment()]),
        FakeFlights(price=410, airlines=["LA", "JJ"], flights=[FakeSegment()]),
    ]
    names = {"G3": "GOL", "LA": "LATAM"}

    data = _serialize_flights(result, names)

    assert data[0] == {"name": "GOL", "price": 350, "stops": 1}
    # Código sin nombre conocido queda como código
    assert data[1] == {"name": "LATAM, JJ", "price": 410, "stops": 0}


def test_serialize_flights_empty_segments():
    """Itinerario sin segmentos no rompe (stops = 0)."""
    data = _serialize_flights([FakeFlights(flights=[])], {})
    assert data[0]["stops"] == 0


def test_parse_price_fallback_formats():
    """El parser de fallback sigue bancando strings de la v2."""
    assert _parse_price("$1,234") == 1234.0
    assert _parse_price("ARS 500,000") == 500000.0
    assert _parse_price("€450") == 450.0
    assert _parse_price(None) is None
    assert _parse_price("1,50") == 1.5


def test_detect_currency_fallback():
    assert _detect_currency("ARS 500,000") == "ARS"
    assert _detect_currency("€450") == "EUR"
    assert _detect_currency("$1,234") == "USD"
    assert _detect_currency(None) == "USD"


def test_build_scan_dates_explicit_window():
    """Ventana explícita: escanea día por día dentro del rango."""
    route = RouteConfig(
        origin="EZE", destination="GIG", sources=["google_flights"],
        depart_from="2099-12-01", depart_to="2099-12-03", scan_step_days=1,
    )
    dates = build_scan_dates(route, today=date(2099, 11, 1))
    assert dates == [date(2099, 12, 1), date(2099, 12, 2), date(2099, 12, 3)]


def test_build_scan_dates_window_clipped_to_future():
    """La ventana nunca incluye fechas pasadas ni hoy."""
    route = RouteConfig(
        origin="EZE", destination="GIG", sources=["google_flights"],
        depart_from="2099-12-01", depart_to="2099-12-03", scan_step_days=1,
    )
    dates = build_scan_dates(route, today=date(2099, 12, 2))
    assert dates == [date(2099, 12, 3)]
