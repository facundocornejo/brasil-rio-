"""Shared departure-date scanning logic for flight adapters.

Genera la lista de fechas de salida a escanear para una ruta. Lo usan
los adapters que barren un rango de fechas (Google Flights, Amadeus).
"""

import logging
from datetime import date, timedelta

from src.models import RouteConfig

logger = logging.getLogger(__name__)

# Escanear cada N días por default (compromiso entre cobertura y velocidad)
DEFAULT_DAYS_BETWEEN_SCANS = 7


def build_scan_dates(
    route: RouteConfig,
    today: date,
    default_step_days: int = DEFAULT_DAYS_BETWEEN_SCANS,
) -> list[date]:
    """Build the list of departure dates to scan for a route.

    Dos modos:
    - Ventana explícita: si la ruta tiene depart_from/depart_to, escanea
      dentro de ese rango con el paso configurado (route.scan_step_days,
      default default_step_days), recortando al futuro (nunca antes de mañana).
    - Clásico: months_ahead hacia adelante, filtrando por active_months.
    """
    dates: list[date] = []
    start_floor = today + timedelta(days=1)  # Nunca escanear el pasado ni hoy
    step = route.scan_step_days or default_step_days  # Paso entre fechas

    # === Modo ventana explícita ===
    if route.depart_from or route.depart_to:
        try:
            win_start = (
                date.fromisoformat(route.depart_from)
                if route.depart_from
                else start_floor
            )
            win_end = (
                date.fromisoformat(route.depart_to)
                if route.depart_to
                else win_start + timedelta(days=route.months_ahead * 30)
            )
        except ValueError:
            logger.warning(
                "Ventana de fechas inválida en %s→%s (depart_from=%s, depart_to=%s), "
                "usando modo clásico.",
                route.origin, route.destination, route.depart_from, route.depart_to,
            )
        else:
            current = max(win_start, start_floor)
            while current <= win_end:
                dates.append(current)
                current += timedelta(days=step)
            return dates

    # === Modo clásico: months_ahead + active_months ===
    total_days = route.months_ahead * 30
    current = start_floor
    while (current - today).days <= total_days:
        if not route.active_months or current.month in route.active_months:
            dates.append(current)
        current += timedelta(days=step)
    return dates
