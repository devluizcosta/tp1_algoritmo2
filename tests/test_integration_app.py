"""Testes de integração com a base real de Belo Horizonte (bares.csv.gz + OSM) e
fluxo completo da aplicação Dash (consulta, filtro de raio e regeneração da frota).
"""

from app import RUNTIME, create_dash_app
from tests.test_trie_and_engine import _assert_radix_invariants


def test_real_dataset_and_osm_road_network_loaded() -> None:
    """Verifica que a base de bares de BH e a malha viária OSM foram carregadas."""
    assert len(RUNTIME.restaurants) == 20859
    assert len(RUNTIME.road_index.nodes) > 30000

    # Verifica que as coordenadas dos restaurantes estão em Belo Horizonte
    sample = RUNTIME.restaurants[:100]
    for r in sample:
        assert -20.10 <= r.latitude <= -19.70
        assert -44.15 <= r.longitude <= -43.80
        assert len(r.geohash) == 7


def test_fleet_regeneration_discards_previous_and_snaps_to_osm() -> None:
    """Ao regenerar N entregadores, os anteriores devem ser descartados e todos os
    novos devem estar sobre coordenadas válidas da malha viária OSM e indexados na Trie.
    """
    valid_road_coords = {
        (n.latitude, n.longitude) for n in RUNTIME.road_index.nodes
    }

    couriers_120 = RUNTIME.regenerate_fleet(120, seed=101)
    assert len(couriers_120) == 120
    assert len(RUNTIME.engine.trie) == 120
    _assert_radix_invariants(RUNTIME.engine.trie.root)

    for c in couriers_120:
        assert (c.latitude, c.longitude) in valid_road_coords

    # Regenera com novo N=300 e verifica descarte integral da frota anterior
    couriers_300 = RUNTIME.regenerate_fleet(300, seed=202)
    assert len(couriers_300) == 300
    assert len(RUNTIME.engine.trie) == 300
    assert len(RUNTIME.engine.couriers) == 300
    _assert_radix_invariants(RUNTIME.engine.trie.root)


def test_dash_app_layout_and_search_flow() -> None:
    """Valida a construção da interface e a busca textual por nome/endereço."""
    app = create_dash_app()
    assert app.layout is not None

    savassi_options = RUNTIME.search_restaurants("SAVASSI")
    assert len(savassi_options) > 0
    first_id = savassi_options[0]["value"]
    rest = RUNTIME.restaurant_by_id[first_id]
    assert "SAVASSI" in rest.neighborhood.upper() or "SAVASSI" in rest.search_label.upper()

    result = RUNTIME.engine.query_by_restaurant(rest, radius_km=2.5)
    assert result.radius_km == 2.5
    assert len(result.search_prefixes) == 9
    assert result.total_query_ms >= 0.0
    for m in result.matched_couriers:
        assert m.distance_km <= 2.5
        assert m.within_radius is True
    for d in result.discarded_couriers:
        assert d.distance_km > 2.5
        assert d.within_radius is False

