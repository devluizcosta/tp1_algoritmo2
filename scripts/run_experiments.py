"""Script de avaliação experimental e geração de gráficos de desempenho do sistema.

Executa consultas reais sobre a base de estabelecimentos de Belo Horizonte (`bares.csv.gz`)
e a malha viária do OpenStreetMap, medindo tempos de resposta (runtime) da Trie Compacta,
da filtragem geométrica Haversine e de uma busca exaustiva linear O(N) de referência.
"""

import json
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List

import matplotlib.pyplot as plt

from src.data_loader import load_or_build_restaurants, load_or_build_road_network
from src.geometry import estimate_eta_minutes, haversine_km
from src.models import CourierMatch
from src.simulator import FleetSimulator
from src.spatial_engine import SpatialSearchEngine

DOCS_IMAGES_DIR = Path(__file__).resolve().parent.parent / "docs" / "images"
RESULTS_JSON_PATH = Path(__file__).resolve().parent.parent / "docs" / "benchmark_results.json"


def _exhaustive_linear_query(
    couriers, rest_lat: float, rest_lon: float, radius_km: float
) -> List[CourierMatch]:
    matched: List[CourierMatch] = []
    for c in couriers:
        dist_km = haversine_km(rest_lat, rest_lon, c.latitude, c.longitude)
        if dist_km <= radius_km:
            matched.append(
                CourierMatch(
                    courier=c,
                    distance_km=dist_km,
                    eta_minutes=estimate_eta_minutes(dist_km),
                    within_radius=True,
                    in_candidate_cells=True,
                )
            )
    matched.sort(key=lambda item: item.distance_km)
    return matched


def run_all_experiments() -> Dict[str, Any]:
    DOCS_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    road_index = load_or_build_road_network()
    restaurants = load_or_build_restaurants(road_index)
    simulator = FleetSimulator(restaurants=restaurants, road_index=road_index)
    engine = SpatialSearchEngine(index_precision=7)

    # Seleciona restaurantes representativos em diferentes regiões de Belo Horizonte
    sample_queries = []
    target_keywords = [
        ("SAVASSI", "DONA DEJA"),
        ("CENTRO", "TERMINAL LANCHES"),
        ("SERRA", "TALENTO DE MINAS"),
        ("CRUZEIRO", "NECTAR DA SERRA"),
        ("JARDIM ATLANTICO", "BAR E CAFE DONATELO"),
    ]
    for bairro_kw, name_kw in target_keywords:
        for r in restaurants:
            if bairro_kw in r.neighborhood.upper() and name_kw in r.display_name.upper():
                sample_queries.append(r)
                break

    # Experimento 1: Escalabilidade em função do tamanho da frota N (Raio = 0.6 km, nível p=6)
    fleet_sizes = [100, 250, 500, 1000, 2500, 5000]
    scaling_records: List[Dict[str, Any]] = []

    for n_couriers in fleet_sizes:
        t_sim0 = time.perf_counter()
        couriers = simulator.generate_couriers(num_couriers=n_couriers, seed=42)
        sim_ms = (time.perf_counter() - t_sim0) * 1000.0

        t_idx0 = time.perf_counter()
        engine.rebuild_index(couriers)
        index_ms = (time.perf_counter() - t_idx0) * 1000.0

        _, total_nodes, max_depth = engine.trie.stats()

        trie_times_ms = []
        hybrid_total_ms = []
        linear_times_ms = []
        candidates_counts = []
        matched_counts = []

        # Avalia sobre 50 restaurantes distribuídos pela cidade
        eval_restaurants = restaurants[:: max(1, len(restaurants) // 50)][:50]
        for rest in eval_restaurants:
            res = engine.query_by_restaurant(
                rest, radius_km=0.6, include_outside_discarded=False
            )
            trie_times_ms.append(res.trie_lookup_ms)
            hybrid_total_ms.append(res.total_query_ms)
            candidates_counts.append(res.trie_candidates_count)
            matched_counts.append(len(res.matched_couriers))

            t_lin0 = time.perf_counter()
            _exhaustive_linear_query(
                couriers, rest.latitude, rest.longitude, radius_km=0.6
            )
            linear_times_ms.append((time.perf_counter() - t_lin0) * 1000.0)

        scaling_records.append(
            {
                "fleet_size": n_couriers,
                "simulation_ms": round(sim_ms, 2),
                "trie_build_ms": round(index_ms, 2),
                "trie_nodes": total_nodes,
                "trie_max_depth": max_depth,
                "avg_trie_lookup_ms": round(statistics.mean(trie_times_ms), 4),
                "avg_hybrid_query_ms": round(statistics.mean(hybrid_total_ms), 4),
                "avg_linear_scan_ms": round(statistics.mean(linear_times_ms), 4),
                "speedup_factor": round(
                    statistics.mean(linear_times_ms)
                    / max(1e-6, statistics.mean(hybrid_total_ms)),
                    2,
                ),
                "avg_candidates": round(statistics.mean(candidates_counts), 1),
                "avg_matched": round(statistics.mean(matched_counts), 1),
            }
        )

    # Experimento 2: Consultas detalhadas em restaurantes reais (Frota N = 500 entregadores)
    couriers_500 = simulator.generate_couriers(num_couriers=500, seed=42)
    engine.rebuild_index(couriers_500)

    case_studies: List[Dict[str, Any]] = []
    radii_to_test = [1.0, 2.0, 3.0]
    for rest in sample_queries:
        for r_km in radii_to_test:
            res = engine.query_by_restaurant(rest, radius_km=r_km)
            nearest_dist = (
                round(res.matched_couriers[0].distance_km, 3)
                if res.matched_couriers
                else None
            )
            nearest_eta = (
                round(res.matched_couriers[0].eta_minutes, 1)
                if res.matched_couriers
                else None
            )
            case_studies.append(
                {
                    "record_id": rest.record_id,
                    "restaurant_name": rest.display_name,
                    "neighborhood": rest.neighborhood,
                    "address": rest.formatted_address,
                    "geohash": rest.geohash,
                    "radius_km": r_km,
                    "query_prefix": res.query_prefix,
                    "prefix_precision": res.prefix_precision,
                    "trie_candidates": res.trie_candidates_count,
                    "matched_couriers": len(res.matched_couriers),
                    "nearest_km": nearest_dist,
                    "nearest_eta_min": nearest_eta,
                    "trie_lookup_ms": round(res.trie_lookup_ms, 4),
                    "geometric_filter_ms": round(res.geometric_filter_ms, 4),
                    "total_query_ms": round(res.total_query_ms, 4),
                }
            )

    # Gera gráfico comparativo de tempo de consulta e poda espacial
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.8), dpi=160)

    xs = [row["fleet_size"] for row in scaling_records]
    y_linear = [row["avg_linear_scan_ms"] for row in scaling_records]
    y_hybrid = [row["avg_hybrid_query_ms"] for row in scaling_records]
    y_trie = [row["avg_trie_lookup_ms"] for row in scaling_records]

    ax1.plot(
        xs,
        y_linear,
        marker="o",
        linewidth=2,
        color="#64748b",
        label="Varredura Linear Exaustiva O(N)",
    )
    ax1.plot(
        xs,
        y_hybrid,
        marker="s",
        linewidth=2.2,
        color="#dc2626",
        label="Busca Híbrida (Trie 9 Células + Haversine)",
    )
    ax1.plot(
        xs,
        y_trie,
        marker="^",
        linewidth=1.8,
        linestyle="--",
        color="#1d4ed8",
        label="Apenas Recuperação na Trie O(m + k)",
    )
    ax1.set_title("Tempo Médio de Consulta vs. Tamanho da Frota (Nível p=6)", fontsize=11, fontweight="bold")
    ax1.set_xlabel("Quantidade de Entregadores na Frota (N)")
    ax1.set_ylabel("Tempo de Resposta (ms)")
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(frameon=True, fontsize=9)

    y_nodes = [row["trie_nodes"] for row in scaling_records]
    ax2.plot(
        xs,
        y_nodes,
        marker="D",
        linewidth=2.2,
        color="#0284c7",
        label="Nós na Trie Compacta (Radix Tree)",
    )
    ax2.plot(
        xs,
        xs,
        marker="o",
        linewidth=1.6,
        linestyle=":",
        color="#475569",
        label="Entregadores Indexados (N)",
    )
    ax2.set_title("Crescimento Estrutural da Trie Compacta (Precisão Geohash = 7)", fontsize=11, fontweight="bold")
    ax2.set_xlabel("Quantidade de Entregadores na Frota (N)")
    ax2.set_ylabel("Quantidade de Nós / Entregadores")
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(frameon=True, fontsize=9)

    plt.tight_layout()
    chart_path = DOCS_IMAGES_DIR / "experimental_runtime_chart.png"
    plt.savefig(chart_path)
    plt.close(fig)

    summary = {
        "total_restaurants_bh": len(restaurants),
        "total_osm_road_points": len(road_index.nodes),
        "scaling_experiments": scaling_records,
        "case_studies_n500": case_studies,
    }
    with open(RESULTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary


if __name__ == "__main__":
    results = run_all_experiments()
    print(json.dumps(results, indent=2, ensure_ascii=False))

