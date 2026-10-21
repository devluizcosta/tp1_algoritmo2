"""Testes unitários para o módulo de codificação e vizinhança Geohash."""

import math
import pytest

from src.geohash import (
    BASE32_ALPHABET,
    adjacent,
    covering_prefixes_for_radius,
    decode,
    decode_bbox,
    encode,
    neighbors,
)
from src.geometry import haversine_km, meters_to_degree_offsets


def test_encode_known_geohashes() -> None:
    """Verifica a intercalação binária contra valores de referência do Geohash."""
    # Ezs42: exemplo clássico da especificação Geohash (42.6, -5.6)
    assert encode(42.6, -5.6, precision=5) == "ezs42"
    # Praça Sete de Setembro, Belo Horizonte (-19.9191, -43.9386) -> 7h2y8ju
    gh_bh = encode(-19.9191, -43.9386, precision=7)
    assert len(gh_bh) == 7
    assert all(ch in BASE32_ALPHABET for ch in gh_bh)
    assert gh_bh == "7h2y8ju"


def test_encode_decode_roundtrip() -> None:
    """Verifica que o ponto codificado pertence à caixa delimitadora decodificada."""
    lat, lon = -19.93215, -43.93802
    for precision in range(1, 10):
        gh = encode(lat, lon, precision=precision)
        bbox = decode_bbox(gh)
        assert bbox.min_lat <= lat <= bbox.max_lat
        assert bbox.min_lon <= lon <= bbox.max_lon

        center_lat, center_lon = decode(gh)
        assert abs(center_lat - lat) <= bbox.lat_span / 2.0 + 1e-12
        assert abs(center_lon - lon) <= bbox.lon_span / 2.0 + 1e-12


def test_neighbors_symmetry_and_distinctness() -> None:
    """Verifica que uma célula possui 8 vizinhos distintos e simétricos."""
    center = encode(-19.9191, -43.9386, precision=6)
    adj = neighbors(center)
    assert len(adj) == 8
    assert len(set(adj.values())) == 8
    assert center not in adj.values()

    assert adjacent(adj["n"], "s") == center
    assert adjacent(adj["s"], "n") == center
    assert adjacent(adj["e"], "w") == center
    assert adjacent(adj["w"], "e") == center
    assert adjacent(adj["ne"], "sw") == center
    assert adjacent(adj["nw"], "se") == center


def test_covering_prefixes_eliminates_boundary_problem() -> None:
    """Pontos próximos separados pela fronteira de uma célula Geohash devem ser
    cobertos pelos 9 prefixos (célula central + 8 adjacentes).
    """
    base_gh = encode(-19.9191, -43.9386, precision=6)
    bbox = decode_bbox(base_gh)

    # Posiciona o restaurante a apenas 5 metros da borda norte/leste da célula
    rest_lat = bbox.max_lat - 1e-5
    rest_lon = bbox.max_lon - 1e-5

    # Posiciona um entregador logo do outro lado da borda nordeste (~20 metros)
    dlat, dlon = meters_to_degree_offsets(rest_lat, 25.0, 25.0)
    courier_lat = rest_lat + dlat
    courier_lon = rest_lon + dlon

    dist_km = haversine_km(rest_lat, rest_lon, courier_lat, courier_lon)
    assert dist_km < 0.05  # menos de 50 metros

    radius_km = 2.0
    query_prefix, search_prefixes, precision = covering_prefixes_for_radius(
        rest_lat, rest_lon, radius_km=radius_km, index_precision=7
    )

    courier_gh = encode(courier_lat, courier_lon, precision=7)
    assert any(courier_gh.startswith(p) for p in search_prefixes)
    assert len(search_prefixes) == 9


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        encode(-95.0, -43.9, precision=5)
    with pytest.raises(ValueError):
        encode(-19.9, 185.0, precision=5)
    with pytest.raises(ValueError):
        encode(-19.9, -43.9, precision=0)
    with pytest.raises(ValueError):
        decode_bbox("")
    with pytest.raises(ValueError):
        decode_bbox("6gkz!invalid")
    with pytest.raises(ValueError):
        adjacent("6gkzq", "invalid_dir")
