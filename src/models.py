"""Modelos de domínio para restaurantes, entregadores e resultados de busca."""

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Restaurant:
    """Estabelecimento comercial (bar ou restaurante) de Belo Horizonte."""

    record_id: int
    cnae: str
    cnae_description: str
    street_type: str
    street_name: str
    street_number: str
    complement: str
    neighborhood: str
    legal_name: str
    trade_name: str
    latitude: float
    longitude: float
    geohash: str

    @property
    def display_name(self) -> str:
        base = self.trade_name.strip() if self.trade_name.strip() else self.legal_name.strip()
        return base

    @property
    def formatted_address(self) -> str:
        num = f", {self.street_number}" if self.street_number else ""
        bairro = f" - {self.neighborhood}" if self.neighborhood else ""
        return f"{self.street_type} {self.street_name}{num}{bairro}"

    @property
    def search_label(self) -> str:
        return f"{self.display_name} ({self.formatted_address})"


@dataclass(frozen=True)
class Courier:
    """Entregador da frota com posição corrigida para a malha viária."""

    courier_id: str
    latitude: float
    longitude: float
    geohash: str
    raw_latitude: float
    raw_longitude: float
    snapped_street: str
    source_restaurant_id: int
    snap_distance_m: float


@dataclass(frozen=True)
class CourierMatch:
    """Entregador avaliado em relação ao restaurante consultado."""

    courier: Courier
    distance_km: float
    eta_minutes: float
    within_radius: bool
    in_candidate_cells: bool


@dataclass(frozen=True)
class QueryResult:
    """Resultado consolidado de uma consulta espacial híbrida."""

    restaurant: Restaurant
    radius_km: float
    query_prefix: str
    search_prefixes: List[str]
    prefix_precision: int
    trie_candidates_count: int
    matched_couriers: List[CourierMatch] = field(default_factory=list)
    discarded_couriers: List[CourierMatch] = field(default_factory=list)
    trie_lookup_ms: float = 0.0
    geometric_filter_ms: float = 0.0
    total_query_ms: float = 0.0

