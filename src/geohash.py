"""Codificação, decodificação e vizinhança Geohash em Base32."""

from dataclasses import dataclass
from typing import Dict, List, Tuple

BASE32_ALPHABET = "0123456789bcdefghjkmnpqrstuvwxyz"
BASE32_DECODE_MAP: Dict[str, int] = {
    char: idx for idx, char in enumerate(BASE32_ALPHABET)
}

LAT_RANGE: Tuple[float, float] = (-90.0, 90.0)
LON_RANGE: Tuple[float, float] = (-180.0, 180.0)


@dataclass(frozen=True)
class BoundingBox:
    """Caixa delimitadora geográfica de uma célula Geohash."""

    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    @property
    def center(self) -> Tuple[float, float]:
        return (
            (self.min_lat + self.max_lat) / 2.0,
            (self.min_lon + self.max_lon) / 2.0,
        )

    @property
    def lat_span(self) -> float:
        return self.max_lat - self.min_lat

    @property
    def lon_span(self) -> float:
        return self.max_lon - self.min_lon


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if not (LAT_RANGE[0] <= latitude <= LAT_RANGE[1]):
        raise ValueError(f"Latitude fora do intervalo [-90, 90]: {latitude}")
    if not (LON_RANGE[0] <= longitude <= LON_RANGE[1]):
        raise ValueError(f"Longitude fora do intervalo [-180, 180]: {longitude}")


def encode(latitude: float, longitude: float, precision: int = 7) -> str:
    """Converte (latitude, longitude) em string Geohash Base32 por intercalação binária.

    Bits de índice par (0, 2, 4, ...) subdividem a longitude [-180, 180].
    Bits de índice ímpar (1, 3, 5, ...) subdividem a latitude [-90, 90].
    Cada grupo de 5 bits intercalados é mapeado para um caractere Base32.
    """
    _validate_coordinates(latitude, longitude)
    if precision <= 0:
        raise ValueError("A precisão do Geohash deve ser um inteiro positivo.")

    lat_min, lat_max = LAT_RANGE
    lon_min, lon_max = LON_RANGE

    is_even_bit = True
    bit_position = 0
    current_char_index = 0
    geohash_chars: List[str] = []

    while len(geohash_chars) < precision:
        if is_even_bit:
            mid = (lon_min + lon_max) / 2.0
            if longitude >= mid:
                current_char_index = (current_char_index << 1) | 1
                lon_min = mid
            else:
                current_char_index = current_char_index << 1
                lon_max = mid
        else:
            mid = (lat_min + lat_max) / 2.0
            if latitude >= mid:
                current_char_index = (current_char_index << 1) | 1
                lat_min = mid
            else:
                current_char_index = current_char_index << 1
                lat_max = mid

        is_even_bit = not is_even_bit
        bit_position += 1

        if bit_position == 5:
            geohash_chars.append(BASE32_ALPHABET[current_char_index])
            bit_position = 0
            current_char_index = 0

    return "".join(geohash_chars)


def decode_bbox(geohash_str: str) -> BoundingBox:
    """Recupera o BoundingBox exato associado a uma string Geohash."""
    if not geohash_str:
        raise ValueError("A string Geohash não pode ser vazia.")

    lat_min, lat_max = LAT_RANGE
    lon_min, lon_max = LON_RANGE
    is_even_bit = True

    for char in geohash_str.lower():
        if char not in BASE32_DECODE_MAP:
            raise ValueError(f"Caractere inválido no Geohash: '{char}'")
        char_value = BASE32_DECODE_MAP[char]

        for mask in (16, 8, 4, 2, 1):
            bit_is_one = bool(char_value & mask)
            if is_even_bit:
                mid = (lon_min + lon_max) / 2.0
                if bit_is_one:
                    lon_min = mid
                else:
                    lon_max = mid
            else:
                mid = (lat_min + lat_max) / 2.0
                if bit_is_one:
                    lat_min = mid
                else:
                    lat_max = mid
            is_even_bit = not is_even_bit

    return BoundingBox(
        min_lat=lat_min,
        max_lat=lat_max,
        min_lon=lon_min,
        max_lon=lon_max,
    )


def decode(geohash_str: str) -> Tuple[float, float]:
    """Retorna o ponto central (latitude, longitude) de uma célula Geohash."""
    return decode_bbox(geohash_str).center


def _wrap_longitude(lon: float) -> float:
    """Normaliza longitude para o intervalo [-180, 180]."""
    if lon > 180.0:
        return lon - 360.0
    if lon < -180.0:
        return lon + 360.0
    return lon


def _clamp_latitude(lat: float) -> float:
    """Restringe latitude ao intervalo [-90, 90]."""
    return max(LAT_RANGE[0], min(LAT_RANGE[1], lat))


def adjacent(geohash_str: str, direction: str) -> str:
    """Calcula a célula Geohash adjacente na direção especificada.

    Direções suportadas: 'n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'.
    Obtém a caixa delimitadora da célula atual e desloca o ponto central
    em uma unidade de altura/largura da célula na direção solicitada.
    """
    bbox = decode_bbox(geohash_str)
    center_lat, center_lon = bbox.center
    d_lat = bbox.lat_span
    d_lon = bbox.lon_span
    precision = len(geohash_str)

    offsets = {
        "n": (d_lat, 0.0),
        "s": (-d_lat, 0.0),
        "e": (0.0, d_lon),
        "w": (0.0, -d_lon),
        "ne": (d_lat, d_lon),
        "nw": (d_lat, -d_lon),
        "se": (-d_lat, d_lon),
        "sw": (-d_lat, -d_lon),
    }

    direction_key = direction.lower()
    if direction_key not in offsets:
        raise ValueError(f"Direção inválida: '{direction}'")

    lat_offset, lon_offset = offsets[direction_key]
    target_lat = _clamp_latitude(center_lat + lat_offset)
    target_lon = _wrap_longitude(center_lon + lon_offset)

    return encode(target_lat, target_lon, precision=precision)


def neighbors(geohash_str: str) -> Dict[str, str]:
    """Retorna as 8 células adjacentes à célula Geohash informada."""
    directions = ("n", "ne", "e", "se", "s", "sw", "w", "nw")
    return {d: adjacent(geohash_str, d) for d in directions}


def covering_prefixes_for_radius(
    latitude: float,
    longitude: float,
    radius_km: float,
    index_precision: int = 7,
) -> Tuple[str, List[str], int]:
    """Determina o prefixo central, a precisão de busca e os 9 prefixos (célula + 8 vizinhos)
    que cobrem completamente o círculo de raio `radius_km` ao redor do ponto.

    Para eliminar o problema de borda sem subestimar o raio configurado pelo usuário,
    seleciona-se o maior comprimento de prefixo p <= index_precision tal que a menor
    dimensão linear da célula Geohash de nível p seja maior ou igual a `radius_km`.
    Assim, a união da célula central com suas 8 adjacentes garante cobertura integral
    de qualquer ponto a até `radius_km` de distância do restaurante.
    """
    from src.geometry import haversine_km

    center_full_hash = encode(latitude, longitude, precision=index_precision)

    selected_precision = 1
    for p in range(index_precision, 0, -1):
        prefix = center_full_hash[:p]
        bbox = decode_bbox(prefix)
        cell_height_km = haversine_km(
            bbox.min_lat, longitude, bbox.max_lat, longitude
        )
        cell_width_km = haversine_km(
            latitude, bbox.min_lon, latitude, bbox.max_lon
        )
        if min(cell_height_km, cell_width_km) >= radius_km:
            selected_precision = p
            break

    query_prefix = center_full_hash[:selected_precision]
    adj_map = neighbors(query_prefix)

    # Preserva a ordem determinística sem duplicatas (centro seguido dos 8 vizinhos)
    search_prefixes: List[str] = [query_prefix]
    for neighbor_prefix in adj_map.values():
        if neighbor_prefix not in search_prefixes:
            search_prefixes.append(neighbor_prefix)

    return query_prefix, search_prefixes, selected_precision

