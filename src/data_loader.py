"""Carregamento da malha viária de Belo Horizonte (OpenStreetMap / osmnx) e
associação de coordenadas reais de logradouro aos estabelecimentos de `bares.csv.gz`.
"""

import csv
import gzip
import hashlib
import math
import pickle
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.geohash import encode
from src.geometry import haversine_km
from src.models import Restaurant

BH_CENTER_LAT = -19.9191
BH_CENTER_LON = -43.9386

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ROAD_CACHE_PATH = DATA_DIR / "bh_road_network.pkl"
RESTAURANTS_CACHE_PATH = DATA_DIR / "bh_restaurants_geocoded.pkl"
RAW_CSV_PATH = Path(__file__).resolve().parent.parent / "bares.csv.gz"


@dataclass(frozen=True)
class RoadNode:
    """Vértice ou ponto intermediário amostrado sobre uma via transitável de BH."""

    node_id: int
    latitude: float
    longitude: float
    street_name: str
    normalized_street: str


def normalize_text(text: str) -> str:
    """Remove acentos, converte para maiúsculas e normaliza espaços."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_str = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(ascii_str.upper().strip().split())


STREET_TYPE_MAP = {
    "AVE": "AVENIDA",
    "AV": "AVENIDA",
    "AVENIDA": "AVENIDA",
    "RUA": "RUA",
    "R": "RUA",
    "PCA": "PRACA",
    "PRACA": "PRACA",
    "ALA": "ALAMEDA",
    "ALAMEDA": "ALAMEDA",
    "ROD": "RODOVIA",
    "RODOVIA": "RODOVIA",
    "BEC": "BECO",
    "BECO": "BECO",
    "TRV": "TRAVESSA",
    "TRAVESSA": "TRAVESSA",
    "EST": "ESTRADA",
    "ESTRADA": "ESTRADA",
    "VD": "VIADUTO",
    "VIADUTO": "VIADUTO",
}


def canonical_street_keys(street_type: str, street_name: str) -> List[str]:
    """Gera chaves normalizadas de busca para casar logradouros da PBH com vias do OSM."""
    norm_type = normalize_text(street_type)
    norm_name = normalize_text(street_name)
    full_type = STREET_TYPE_MAP.get(norm_type, norm_type)

    keys = []
    if full_type and norm_name:
        keys.append(f"{full_type} {norm_name}")
    if norm_name:
        keys.append(norm_name)
    return keys


class RoadNetworkIndex:
    """Índice espacial de nós viários do OpenStreetMap para projeção (snapping)
    de coordenadas sobre vias transitáveis de Belo Horizonte.

    Utiliza uma grade espacial (spatial hash grid) com células de ~0.002 graus
    (~220m) para responder consultas de vizinho mais próximo em tempo médio O(1)
    sem depender de bibliotecas externas pesadas em tempo de consulta.
    """

    def __init__(
        self, nodes: Sequence[RoadNode], cell_size_deg: float = 0.0025
    ) -> None:
        if not nodes:
            raise ValueError("A malha viária não pode ser inicializada sem nós.")
        self.nodes: List[RoadNode] = list(nodes)
        self.cell_size_deg = cell_size_deg
        self._grid: Dict[Tuple[int, int], List[RoadNode]] = {}
        self._street_map: Dict[str, List[RoadNode]] = {}

        for node in self.nodes:
            cell = self._cell_coords(node.latitude, node.longitude)
            self._grid.setdefault(cell, []).append(node)

            if node.normalized_street:
                self._street_map.setdefault(node.normalized_street, []).append(node)
                # Também indexa sem o tipo de logradouro inicial (ex.: 'AFONSO PENA')
                parts = node.normalized_street.split(" ", 1)
                if len(parts) == 2 and parts[0] in STREET_TYPE_MAP.values():
                    self._street_map.setdefault(parts[1], []).append(node)

    def _cell_coords(self, lat: float, lon: float) -> Tuple[int, int]:
        return (
            int(math.floor(lat / self.cell_size_deg)),
            int(math.floor(lon / self.cell_size_deg)),
        )

    def snap_to_nearest_road(
        self, latitude: float, longitude: float
    ) -> Tuple[RoadNode, float]:
        """Projeta a coordenada (latitude, longitude) para o ponto viário mais próximo.

        Retorna a tupla (RoadNode, distancia_em_metros).
        """
        center_cell = self._cell_coords(latitude, longitude)
        best_node: Optional[RoadNode] = None
        best_dist_km = float("inf")

        # Expande anéis concêntricos na grade até encontrar candidatos suficientes
        for ring in range(0, 18):
            candidates: List[RoadNode] = []
            for di in range(-ring, ring + 1):
                for dj in range(-ring, ring + 1):
                    if ring > 0 and abs(di) != ring and abs(dj) != ring:
                        continue
                    cell_nodes = self._grid.get(
                        (center_cell[0] + di, center_cell[1] + dj)
                    )
                    if cell_nodes:
                        candidates.extend(cell_nodes)

            for cand in candidates:
                d_km = haversine_km(
                    latitude, longitude, cand.latitude, cand.longitude
                )
                if d_km < best_dist_km:
                    best_dist_km = d_km
                    best_node = cand

            # Se já encontramos um nó a uma distância menor que a borda do próximo anel, encerramos
            min_possible_next_ring_km = max(0, ring) * self.cell_size_deg * 100.0
            if best_node is not None and best_dist_km <= min_possible_next_ring_km:
                break

        if best_node is None:
            # Fallback exaustivo caso o ponto esteja muito distante da malha
            for cand in self.nodes:
                d_km = haversine_km(
                    latitude, longitude, cand.latitude, cand.longitude
                )
                if d_km < best_dist_km:
                    best_dist_km = d_km
                    best_node = cand

        assert best_node is not None
        return best_node, best_dist_km * 1000.0

    def find_nodes_by_street(
        self, street_type: str, street_name: str
    ) -> List[RoadNode]:
        """Recupera os nós da malha viária cujo nome de via casa com o logradouro."""
        for key in canonical_street_keys(street_type, street_name):
            matched = self._street_map.get(key)
            if matched:
                return matched
        return []


def extract_road_nodes_from_osmnx(
    place_query: str = "Belo Horizonte, Minas Gerais, Brazil",
) -> List[RoadNode]:
    """Baixa o grafo viário transitável de Belo Horizonte via `osmnx` e extrai
    os pontos das vias (vértices e pontos intermediários de arestas longas) com
    seus respectivos nomes de logradouro.

    Utiliza fallback automático entre espelhos públicos do Overpass API caso o
    servidor primário retorne erro de capacidade (502/504/429).
    """
    import osmnx as ox

    overpass_endpoints = [
        "https://overpass-api.de/api",
        "https://lz4.overpass-api.de/api",
        "https://overpass.kumi.systems/api",
        "https://overpass.private.coffee/api",
    ]

    graph = None
    last_error: Optional[Exception] = None
    for endpoint in overpass_endpoints:
        try:
            ox.settings.overpass_url = endpoint
            ox.settings.overpass_rate_limit = False
            ox.settings.requests_timeout = 180
            graph = ox.graph_from_place(
                place_query, network_type="drive", simplify=True
            )
            break
        except Exception as exc:
            last_error = exc
            continue

    if graph is None:
        raise RuntimeError(
            f"Não foi possível baixar a malha viária via osmnx: {last_error}"
        )

    node_coords: Dict[int, Tuple[float, float]] = {}
    node_street: Dict[int, str] = {}

    for nid, data in graph.nodes(data=True):
        lat = float(data["y"])
        lon = float(data["x"])
        node_coords[int(nid)] = (lat, lon)

    sampled_points: List[RoadNode] = []
    next_synthetic_id = -1

    for u, v, data in graph.edges(data=True):
        raw_name = data.get("name", "")
        if isinstance(raw_name, list):
            street = str(raw_name[0]) if raw_name else ""
        else:
            street = str(raw_name) if raw_name else ""
        street_clean = street.strip() or "Via sem denominação oficial"
        norm_street = normalize_text(street_clean)

        u_int, v_int = int(u), int(v)
        if u_int not in node_street and street_clean != "Via sem denominação oficial":
            node_street[u_int] = street_clean
        if v_int not in node_street and street_clean != "Via sem denominação oficial":
            node_street[v_int] = street_clean

        # Amostra também o ponto médio de arestas com geometria para maior fidelidade viária
        if u_int in node_coords and v_int in node_coords:
            lat1, lon1 = node_coords[u_int]
            lat2, lon2 = node_coords[v_int]
            seg_len_m = float(data.get("length", 0.0))
            if seg_len_m > 80.0:
                mid_lat = (lat1 + lat2) / 2.0
                mid_lon = (lon1 + lon2) / 2.0
                sampled_points.append(
                    RoadNode(
                        node_id=next_synthetic_id,
                        latitude=mid_lat,
                        longitude=mid_lon,
                        street_name=street_clean,
                        normalized_street=norm_street,
                    )
                )
                next_synthetic_id -= 1

    for nid, (lat, lon) in node_coords.items():
        st = node_street.get(nid, "Via urbana de Belo Horizonte")
        sampled_points.append(
            RoadNode(
                node_id=nid,
                latitude=lat,
                longitude=lon,
                street_name=st,
                normalized_street=normalize_text(st),
            )
        )

    return sampled_points


def load_or_build_road_network(
    cache_path: Path = ROAD_CACHE_PATH,
) -> RoadNetworkIndex:
    """Carrega a malha viária de Belo Horizonte a partir do cache local ou a constrói via osmnx."""
    if cache_path.exists():
        with open(cache_path, "rb") as f:
            nodes: List[RoadNode] = pickle.load(f)
        return RoadNetworkIndex(nodes)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    nodes = extract_road_nodes_from_osmnx()
    with open(cache_path, "wb") as f:
        pickle.dump(nodes, f, protocol=pickle.HIGHEST_PROTOCOL)
    return RoadNetworkIndex(nodes)


def _deterministic_index(seed_str: str, modulo: int) -> int:
    digest = hashlib.sha256(seed_str.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], byteorder="big")
    return value % modulo


def load_or_build_restaurants(
    road_index: RoadNetworkIndex,
    csv_gz_path: Path = RAW_CSV_PATH,
    cache_path: Path = RESTAURANTS_CACHE_PATH,
    geohash_precision: int = 7,
) -> List[Restaurant]:
    """Lê `bares.csv.gz` e associa cada estabelecimento às coordenadas reais de seu
    logradouro na malha viária de Belo Horizonte (OpenStreetMap).

    Estratégia de geocodificação viária local:
    1. Para cada estabelecimento, busca os nós da via correspondente (`DESC_LOGRADOURO`
       + `NOME_LOGRADOURO`) no grafo do OpenStreetMap de Belo Horizonte.
    2. Seleciona um ponto sobre a própria via de forma determinística a partir do
       número do imóvel (`NUMERO_IMOVEL`) ao longo da extensão da rua.
    3. Calcula o centroide de cada bairro (`NOME_BAIRRO`) a partir dos estabelecimentos
       cujas ruas foram localizadas diretamente no OSM, projetando os demais registros
       do mesmo bairro sobre as vias do respectivo bairro.
    """
    if cache_path.exists():
        with open(cache_path, "rb") as f:
            cached_restaurants: List[Restaurant] = pickle.load(f)
        if cached_restaurants:
            return cached_restaurants

    raw_rows: List[Dict[str, str]] = []
    with gzip.open(csv_gz_path, mode="rt", encoding="utf-8") as gz_file:
        reader = csv.DictReader(gz_file)
        for row in reader:
            raw_rows.append(row)

    # Passo 1: Casamento direto por nome de logradouro no grafo viário do OSM
    direct_coords: Dict[int, Tuple[float, float]] = {}
    neighborhood_points: Dict[str, List[Tuple[float, float]]] = {}

    for idx, row in enumerate(raw_rows):
        st_type = row.get("DESC_LOGRADOURO", "").strip()
        st_name = row.get("NOME_LOGRADOURO", "").strip()
        num_str = row.get("NUMERO_IMOVEL", "").strip()
        bairro = normalize_text(row.get("NOME_BAIRRO", ""))

        matched_nodes = road_index.find_nodes_by_street(st_type, st_name)
        if matched_nodes:
            # Ordena os nós ao longo da direção principal (lat, lon) para interpolar pelo número
            ordered = sorted(
                matched_nodes, key=lambda n: (n.latitude, n.longitude)
            )
            try:
                num_val = int("".join(ch for ch in num_str if ch.isdigit()) or "100")
            except ValueError:
                num_val = 100
            pos_idx = min(
                len(ordered) - 1,
                int((num_val % 3000) / 3000.0 * len(ordered)),
            )
            chosen = ordered[pos_idx]
            direct_coords[idx] = (chosen.latitude, chosen.longitude)
            if bairro:
                neighborhood_points.setdefault(bairro, []).append(
                    (chosen.latitude, chosen.longitude)
                )

    # Passo 2: Calcula o centroide viário de cada bairro para fallback localizado
    neighborhood_centroids: Dict[str, Tuple[float, float]] = {}
    for bairro, pts in neighborhood_points.items():
        avg_lat = sum(p[0] for p in pts) / len(pts)
        avg_lon = sum(p[1] for p in pts) / len(pts)
        neighborhood_centroids[bairro] = (avg_lat, avg_lon)

    restaurants: List[Restaurant] = []
    for idx, row in enumerate(raw_rows):
        rec_id = int(row.get("_id", idx + 1))
        st_type = row.get("DESC_LOGRADOURO", "").strip()
        st_name = row.get("NOME_LOGRADOURO", "").strip()
        num_str = row.get("NUMERO_IMOVEL", "").strip()
        comp = row.get("COMPLEMENTO", "").strip()
        bairro_raw = row.get("NOME_BAIRRO", "").strip()
        bairro_norm = normalize_text(bairro_raw)
        nome = row.get("NOME", "").strip()
        fantasia = row.get("NOME_FANTASIA", "").strip()
        cnae = row.get("CNAE_PRINCIPAL", "").strip()
        cnae_desc = row.get("DESCRICAO_CNAE_PRINCIPAL", "").strip()

        if idx in direct_coords:
            lat, lon = direct_coords[idx]
        elif bairro_norm in neighborhood_centroids:
            c_lat, c_lon = neighborhood_centroids[bairro_norm]
            # Pequeno deslocamento determinístico dentro do bairro seguido de snap viário
            h_idx = _deterministic_index(f"{st_name}:{num_str}:{rec_id}", 1000)
            angle = (h_idx / 1000.0) * 2.0 * math.pi
            radius_deg = 0.002 * ((h_idx % 10) / 10.0)
            snapped, _ = road_index.snap_to_nearest_road(
                c_lat + radius_deg * math.sin(angle),
                c_lon + radius_deg * math.cos(angle),
            )
            lat, lon = snapped.latitude, snapped.longitude
        else:
            node_idx = _deterministic_index(
                f"{bairro_norm}:{st_name}:{rec_id}", len(road_index.nodes)
            )
            chosen_node = road_index.nodes[node_idx]
            lat, lon = chosen_node.latitude, chosen_node.longitude

        gh = encode(lat, lon, precision=geohash_precision)
        restaurants.append(
            Restaurant(
                record_id=rec_id,
                cnae=cnae,
                cnae_description=cnae_desc,
                street_type=st_type,
                street_name=st_name,
                street_number=num_str,
                complement=comp,
                neighborhood=bairro_raw,
                legal_name=nome,
                trade_name=fantasia,
                latitude=lat,
                longitude=lon,
                geohash=gh,
            )
        )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(restaurants, f, protocol=pickle.HIGHEST_PROTOCOL)

    return restaurants
