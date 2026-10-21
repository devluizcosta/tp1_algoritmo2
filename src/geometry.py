"""Funções de geometria computacional esférica e estimativa de deslocamento."""

import math
from typing import Tuple

EARTH_RADIUS_KM = 6371.0088
DEFAULT_COURIER_SPEED_KMH = 25.0


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Calcula a distância ortodrômica (Haversine) em quilômetros entre dois pontos."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    sin_dphi = math.sin(delta_phi / 2.0)
    sin_dlambda = math.sin(delta_lambda / 2.0)

    a = (
        sin_dphi * sin_dphi
        + math.cos(phi1) * math.cos(phi2) * sin_dlambda * sin_dlambda
    )
    a = min(1.0, max(0.0, a))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_KM * c


def estimate_eta_minutes(
    distance_km: float, speed_kmh: float = DEFAULT_COURIER_SPEED_KMH
) -> float:
    """Estima o tempo de chegada (em minutos) até o restaurante."""
    if speed_kmh <= 0:
        raise ValueError("A velocidade média deve ser positiva.")
    if distance_km < 0:
        raise ValueError("A distância não pode ser negativa.")
    return (distance_km / speed_kmh) * 60.0


def meters_to_degree_offsets(
    latitude: float, delta_north_m: float, delta_east_m: float
) -> Tuple[float, float]:
    """Converte deslocamentos métricos locais (norte, leste) em variações (dlat, dlon)."""
    meters_per_deg_lat = 111_132.92
    cos_lat = math.cos(math.radians(latitude))
    meters_per_deg_lon = max(1.0, 111_412.84 * cos_lat)
    return delta_north_m / meters_per_deg_lat, delta_east_m / meters_per_deg_lon

