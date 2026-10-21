"""Simulador de geração sintética de entregadores com:
1. Distribuição normal bidimensional centrada equitativamente nos restaurantes.
2. Projeção (snapping) para a via transitável mais próxima da malha viária real (OSM).
"""

import random
from typing import List, Optional, Sequence

from src.data_loader import RoadNetworkIndex
from src.geohash import encode
from src.geometry import meters_to_degree_offsets
from src.models import Courier, Restaurant

DEFAULT_SIGMA_METERS = 380.0


class FleetSimulator:
    """Gerador de posicionamento sintético da frota de entregadores."""

    def __init__(
        self,
        restaurants: Sequence[Restaurant],
        road_index: RoadNetworkIndex,
        geohash_precision: int = 7,
        sigma_meters: float = DEFAULT_SIGMA_METERS,
    ) -> None:
        if not restaurants:
            raise ValueError("A lista de restaurantes não pode ser vazia.")
        self.restaurants: List[Restaurant] = list(restaurants)
        self.road_index = road_index
        self.geohash_precision = geohash_precision
        self.sigma_meters = sigma_meters

    def generate_couriers(
        self,
        num_couriers: int,
        seed: Optional[int] = None,
        anchor_restaurants: Optional[Sequence[Restaurant]] = None,
    ) -> List[Courier]:
        """Gera `num_couriers` posições do zero, distribuindo-os equitativamente
        entre os centros disponíveis (restaurantes) segundo uma distribuição
        normal N(mu_centro, sigma^2) e projetando cada ponto matemático para a
        via transitável mais próxima da malha viária de Belo Horizonte.
        """
        if num_couriers < 0:
            raise ValueError("A quantidade de entregadores não pode ser negativa.")
        if num_couriers == 0:
            return []

        rng = random.Random(seed)
        centers = list(anchor_restaurants) if anchor_restaurants else list(self.restaurants)
        num_centers = len(centers)

        # Embaralha a ordem dos centros para que, quando N < num_centers ou
        # N não é múltiplo exato de num_centers, a alocação permaneça equitativa
        # (diferença máxima de 1 entregador entre quaisquer dois centros).
        shuffled_indices = list(range(num_centers))
        rng.shuffle(shuffled_indices)

        generated: List[Courier] = []
        for idx in range(num_couriers):
            center_restaurant = centers[shuffled_indices[idx % num_centers]]

            delta_north_m = rng.gauss(0.0, self.sigma_meters)
            delta_east_m = rng.gauss(0.0, self.sigma_meters)

            dlat, dlon = meters_to_degree_offsets(
                center_restaurant.latitude, delta_north_m, delta_east_m
            )
            raw_lat = center_restaurant.latitude + dlat
            raw_lon = center_restaurant.longitude + dlon

            snapped_node, snap_dist_m = self.road_index.snap_to_nearest_road(
                raw_lat, raw_lon
            )

            final_lat = snapped_node.latitude
            final_lon = snapped_node.longitude

            gh = encode(
                final_lat, final_lon, precision=self.geohash_precision
            )

            generated.append(
                Courier(
                    courier_id=f"ENT-{idx + 1:04d}",
                    latitude=final_lat,
                    longitude=final_lon,
                    geohash=gh,
                    raw_latitude=raw_lat,
                    raw_longitude=raw_lon,
                    snapped_street=snapped_node.street_name,
                    source_restaurant_id=center_restaurant.record_id,
                    snap_distance_m=snap_dist_m,
                )
            )

        return generated

