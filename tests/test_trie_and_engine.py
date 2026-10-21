"""Testes unitários da Trie Compacta (Radix Tree) e da busca espacial híbrida."""

import random
import pytest

from src.geohash import encode
from src.geometry import haversine_km, meters_to_degree_offsets
from src.models import Courier, Restaurant
from src.spatial_engine import SpatialSearchEngine
from src.trie import CompactTrie, RadixTrieNode


def _assert_radix_invariants(node: RadixTrieNode, is_root: bool = True) -> None:
    """Verifica os invariantes estruturais de uma Trie Compacta:
    1. Apenas a raiz tem `label == ""`.
    2. A chave de `children` coincide sempre com `child.label[0]`.
    3. Nenhum nó interno sem valores armazenados possui exatamente 1 filho
       (caminhos unários devem estar comprimidos em uma única aresta).
    """
    if is_root:
        assert node.label == ""
    else:
        assert len(node.label) >= 1

    if not is_root and not node.values:
        assert len(node.children) >= 2, (
            f"Nó interno com rótulo '{node.label}' não está compactado: "
            f"possui {len(node.children)} filho(s) e nenhum valor."
        )

    for first_char, child in node.children.items():
        assert child.label.startswith(first_char)
        _assert_radix_invariants(child, is_root=False)


def test_compact_trie_compression_and_invariants() -> None:
    """Garante que chaves com prefixos comuns são comprimidas e os invariantes se mantêm."""
    trie: CompactTrie[int] = CompactTrie()
    keys = [
        "6gkzq9b",
        "6gkzq9c",
        "6gkzq8f",
        "6gkzp10",
        "6gkzp10",  # chave duplicada com segundo valor
        "6gkyzzz",
        "7h00000",
    ]
    for idx, k in enumerate(keys):
        trie.insert(k, idx)

    assert len(trie) == len(keys)
    _assert_radix_invariants(trie.root)

    # Verifica busca exata
    assert trie.search_exact("6gkzq9b") == [0]
    assert sorted(trie.search_exact("6gkzp10")) == [3, 4]
    assert trie.search_exact("6gkzq9") == []
    assert trie.search_exact("inexistente") == []

    # Verifica busca por prefixo em diferentes pontos (dentro e no fim de arestas comprimidas)
    assert sorted(trie.search_prefix("6gkzq9")) == [0, 1]
    assert sorted(trie.search_prefix("6gkzq")) == [0, 1, 2]
    assert sorted(trie.search_prefix("6gkz")) == [0, 1, 2, 3, 4]
    assert sorted(trie.search_prefix("6gk")) == [0, 1, 2, 3, 4, 5]
    assert sorted(trie.search_prefix("7")) == [6]
    assert trie.search_prefix("8") == []


def test_spatial_engine_matches_exhaustive_ground_truth() -> None:
    """Compara o resultado da busca híbrida (Trie + 8 vizinhos + Haversine) contra
    uma varredura exaustiva O(N) em múltiplos raios e posições.
    """
    rng = random.Random(42)
    center_lat, center_lon = -19.9227, -43.9451

    couriers = []
    for i in range(400):
        d_north = rng.gauss(0, 2200.0)
        d_east = rng.gauss(0, 2200.0)
        dlat, dlon = meters_to_degree_offsets(center_lat, d_north, d_east)
        lat = center_lat + dlat
        lon = center_lon + dlon
        couriers.append(
            Courier(
                courier_id=f"ENT-{i:04d}",
                latitude=lat,
                longitude=lon,
                geohash=encode(lat, lon, precision=7),
                raw_latitude=lat,
                raw_longitude=lon,
                snapped_street="RUA TESTE",
                source_restaurant_id=1,
                snap_distance_m=0.0,
            )
        )

    engine = SpatialSearchEngine(index_precision=7)
    engine.rebuild_index(couriers)
    _assert_radix_invariants(engine.trie.root)

    restaurant = Restaurant(
        record_id=100,
        cnae="5611201",
        cnae_description="RESTAURANTES E SIMILARES",
        street_type="AVE",
        street_name="AFONSO PENA",
        street_number="1500",
        complement="",
        neighborhood="CENTRO",
        legal_name="RESTAURANTE CENTRAL LTDA",
        trade_name="RESTAURANTE CENTRAL",
        latitude=center_lat,
        longitude=center_lon,
        geohash=encode(center_lat, center_lon, precision=7),
    )

    for radius_km in (0.4, 1.0, 2.0, 3.5, 5.0):
        result = engine.query_by_restaurant(restaurant, radius_km=radius_km)

        expected_ids = {
            c.courier_id
            for c in couriers
            if haversine_km(center_lat, center_lon, c.latitude, c.longitude)
            <= radius_km
        }
        returned_ids = {m.courier.courier_id for m in result.matched_couriers}

        assert returned_ids == expected_ids, (
            f"Divergência no raio {radius_km} km: "
            f"faltaram={expected_ids - returned_ids}, "
            f"extras={returned_ids - expected_ids}"
        )

        # Verifica ordenação crescente por distância
        distances = [m.distance_km for m in result.matched_couriers]
        assert distances == sorted(distances)

        # Verifica que todos os entregadores da frota estão particionados entre
        # selecionados e descartados
        assert len(result.matched_couriers) + len(result.discarded_couriers) == len(
            couriers
        )

