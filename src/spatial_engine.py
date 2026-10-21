"""Motor de busca geoespacial híbrido: Geohash + Trie Compacta + Filtragem Geométrica."""

import time
from typing import Iterable, List

from src.geohash import covering_prefixes_for_radius, encode
from src.geometry import DEFAULT_COURIER_SPEED_KMH, estimate_eta_minutes, haversine_km
from src.models import Courier, CourierMatch, QueryResult, Restaurant
from src.trie import CompactTrie

DEFAULT_INDEX_PRECISION = 7


class SpatialSearchEngine:
    """Indexa a frota de entregadores em uma Trie compacta por Geohash e executa
    consultas híbridas (recuperação por prefixo com vizinhança + filtragem Haversine).
    """

    def __init__(
        self,
        index_precision: int = DEFAULT_INDEX_PRECISION,
        courier_speed_kmh: float = DEFAULT_COURIER_SPEED_KMH,
    ) -> None:
        self.index_precision = index_precision
        self.courier_speed_kmh = courier_speed_kmh
        self.trie: CompactTrie[Courier] = CompactTrie()
        self._couriers: List[Courier] = []

    @property
    def couriers(self) -> List[Courier]:
        return list(self._couriers)

    def rebuild_index(self, couriers: Iterable[Courier]) -> None:
        """Descarta o índice anterior e reinsere todos os entregadores na Trie compacta."""
        self.trie.clear()
        self._couriers = list(couriers)
        for courier in self._couriers:
            geohash_key = (
                courier.geohash
                if len(courier.geohash) == self.index_precision
                else encode(
                    courier.latitude,
                    courier.longitude,
                    precision=self.index_precision,
                )
            )
            self.trie.insert(geohash_key, courier)

    def query_by_restaurant(
        self,
        restaurant: Restaurant,
        radius_km: float,
        include_outside_discarded: bool = True,
    ) -> QueryResult:
        """Executa a busca em duas etapas:
        1. Recuperação de candidatos na Trie compacta para a célula central e as
           8 células adjacentes que cobrem o raio `radius_km` em tempo O(m + k).
        2. Filtragem geométrica exata por distância de Haversine <= `radius_km`,
           classificando entregadores selecionados (destaque) e descartados.
        """
        if radius_km <= 0:
            raise ValueError("O raio de busca deve ser maior que zero.")

        t0 = time.perf_counter()

        query_prefix, search_prefixes, prefix_precision = (
            covering_prefixes_for_radius(
                restaurant.latitude,
                restaurant.longitude,
                radius_km=radius_km,
                index_precision=self.index_precision,
            )
        )

        candidates = self.trie.search_prefixes(search_prefixes)
        t_trie = time.perf_counter()

        candidate_ids = {c.courier_id for c in candidates}
        matched: List[CourierMatch] = []
        discarded: List[CourierMatch] = []

        # Filtra geometricamente apenas os k candidatos retornados pela Trie
        for courier in candidates:
            dist_km = haversine_km(
                restaurant.latitude,
                restaurant.longitude,
                courier.latitude,
                courier.longitude,
            )
            eta_min = estimate_eta_minutes(dist_km, self.courier_speed_kmh)
            within = dist_km <= radius_km
            match_item = CourierMatch(
                courier=courier,
                distance_km=dist_km,
                eta_minutes=eta_min,
                within_radius=within,
                in_candidate_cells=True,
            )
            if within:
                matched.append(match_item)
            else:
                discarded.append(match_item)

        matched.sort(key=lambda item: item.distance_km)
        t_geom = time.perf_counter()

        if include_outside_discarded:
            for courier in self._couriers:
                if courier.courier_id in candidate_ids:
                    continue
                dist_km = haversine_km(
                    restaurant.latitude,
                    restaurant.longitude,
                    courier.latitude,
                    courier.longitude,
                )
                eta_min = estimate_eta_minutes(dist_km, self.courier_speed_kmh)
                discarded.append(
                    CourierMatch(
                        courier=courier,
                        distance_km=dist_km,
                        eta_minutes=eta_min,
                        within_radius=False,
                        in_candidate_cells=False,
                    )
                )
            discarded.sort(key=lambda item: item.distance_km)

        trie_ms = (t_trie - t0) * 1000.0
        geom_ms = (t_geom - t_trie) * 1000.0
        total_ms = trie_ms + geom_ms

        return QueryResult(
            restaurant=restaurant,
            radius_km=radius_km,
            query_prefix=query_prefix,
            search_prefixes=search_prefixes,
            prefix_precision=prefix_precision,
            trie_candidates_count=len(candidates),
            matched_couriers=matched,
            discarded_couriers=discarded,
            trie_lookup_ms=trie_ms,
            geometric_filter_ms=geom_ms,
            total_query_ms=total_ms,
        )

