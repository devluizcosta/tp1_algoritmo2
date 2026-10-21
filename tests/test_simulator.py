"""Testes unitários do simulador de geração sintética e projeção viária."""

from collections import Counter

from src.data_loader import RoadNetworkIndex, RoadNode, normalize_text
from src.geohash import encode
from src.models import Restaurant
from src.simulator import FleetSimulator


def _build_fixture_network_and_restaurants():
    road_nodes = [
        RoadNode(1, -19.9191, -43.9386, "Avenida Afonso Pena", normalize_text("Avenida Afonso Pena")),
        RoadNode(2, -19.9205, -43.9370, "Rua da Bahia", normalize_text("Rua da Bahia")),
        RoadNode(3, -19.9320, -43.9355, "Rua Alagoas", normalize_text("Rua Alagoas")),
        RoadNode(4, -19.9365, -43.9320, "Avenida do Contorno", normalize_text("Avenida do Contorno")),
    ]
    road_index = RoadNetworkIndex(road_nodes)

    restaurants = [
        Restaurant(
            record_id=10,
            cnae="5611201",
            cnae_description="RESTAURANTES E SIMILARES",
            street_type="AVE",
            street_name="AFONSO PENA",
            street_number="1000",
            complement="",
            neighborhood="CENTRO",
            legal_name="RESTAURANTE ALFA LTDA",
            trade_name="RESTAURANTE ALFA",
            latitude=-19.9191,
            longitude=-43.9386,
            geohash=encode(-19.9191, -43.9386, precision=7),
        ),
        Restaurant(
            record_id=20,
            cnae="5611201",
            cnae_description="RESTAURANTES E SIMILARES",
            street_type="RUA",
            street_name="ALAGOAS",
            street_number="1314",
            complement="",
            neighborhood="SAVASSI",
            legal_name="RESTAURANTE BETA LTDA",
            trade_name="RESTAURANTE BETA",
            latitude=-19.9320,
            longitude=-43.9355,
            geohash=encode(-19.9320, -43.9355, precision=7),
        ),
        Restaurant(
            record_id=30,
            cnae="5611201",
            cnae_description="RESTAURANTES E SIMILARES",
            street_type="AVE",
            street_name="DO CONTORNO",
            street_number="6000",
            complement="",
            neighborhood="SAVASSI",
            legal_name="RESTAURANTE GAMA LTDA",
            trade_name="RESTAURANTE GAMA",
            latitude=-19.9365,
            longitude=-43.9320,
            geohash=encode(-19.9365, -43.9320, precision=7),
        ),
    ]
    return road_nodes, road_index, restaurants


def test_equitable_distribution_among_centers() -> None:
    """Verifica que os N entregadores são distribuídos equitativamente entre os centros."""
    _, road_index, restaurants = _build_fixture_network_and_restaurants()
    simulator = FleetSimulator(restaurants=restaurants, road_index=road_index)

    couriers = simulator.generate_couriers(num_couriers=30, seed=123)
    assert len(couriers) == 30

    counts = Counter(c.source_restaurant_id for c in couriers)
    assert counts[10] == 10
    assert counts[20] == 10
    assert counts[30] == 10


def test_road_snapping_places_couriers_exclusively_on_roads() -> None:
    """Garante que todas as coordenadas finais pertencem exatamente aos vértices da malha viária."""
    road_nodes, road_index, restaurants = _build_fixture_network_and_restaurants()
    valid_road_coords = {(n.latitude, n.longitude) for n in road_nodes}

    simulator = FleetSimulator(restaurants=restaurants, road_index=road_index)
    couriers = simulator.generate_couriers(num_couriers=25, seed=7)

    for c in couriers:
        assert (c.latitude, c.longitude) in valid_road_coords
        assert len(c.geohash) == 7
        assert c.snap_distance_m >= 0.0

