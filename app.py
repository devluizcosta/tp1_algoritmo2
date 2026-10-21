"""Aplicação web interativa (Dash + dash-leaflet) para busca e monitoramento
geoespacial híbrido de entregadores em Belo Horizonte (DCC207 - UFMG).
"""

import time
from typing import Any, Dict, List, Optional, Tuple

import dash
import dash_leaflet as dl
from dash import Input, Output, State, callback_context, dash_table, dcc, html

from src.data_loader import (
    BH_CENTER_LAT,
    BH_CENTER_LON,
    load_or_build_restaurants,
    load_or_build_road_network,
    normalize_text,
)
from src.geohash import decode_bbox
from src.models import Courier, QueryResult, Restaurant
from src.simulator import FleetSimulator
from src.spatial_engine import SpatialSearchEngine

INITIAL_COURIER_COUNT = 250
INITIAL_RADIUS_KM = 2.0
INITIAL_SEED = 42
MAX_DROPDOWN_OPTIONS = 80


class ApplicationRuntime:
    """Mantém as estruturas em memória para resposta instantânea da interface."""

    def __init__(self) -> None:
        self.road_index = load_or_build_road_network()
        self.restaurants = load_or_build_restaurants(self.road_index)
        self.restaurant_by_id: Dict[int, Restaurant] = {
            r.record_id: r for r in self.restaurants
        }
        self.simulator = FleetSimulator(
            restaurants=self.restaurants, road_index=self.road_index
        )
        self.engine = SpatialSearchEngine(index_precision=7)
        self.generation_counter = 0
        self.last_generation_ms = 0.0
        self.regenerate_fleet(INITIAL_COURIER_COUNT, seed=INITIAL_SEED)

    def regenerate_fleet(
        self, count: int, seed: Optional[int] = None
    ) -> List[Courier]:
        t0 = time.perf_counter()
        self.generation_counter += 1
        effective_seed = (
            seed if seed is not None else (INITIAL_SEED + self.generation_counter * 97)
        )
        couriers = self.simulator.generate_couriers(
            num_couriers=count, seed=effective_seed
        )
        self.engine.rebuild_index(couriers)
        self.last_generation_ms = (time.perf_counter() - t0) * 1000.0
        return couriers

    def search_restaurants(self, query_text: str) -> List[Dict[str, Any]]:
        norm_q = normalize_text(query_text)
        matched: List[Restaurant] = []
        if not norm_q:
            # Exibe amostra inicial representativa de bairros centrais e tradicionais
            matched = self.restaurants[:MAX_DROPDOWN_OPTIONS]
        else:
            tokens = norm_q.split()
            for r in self.restaurants:
                haystack = normalize_text(
                    f"{r.display_name} {r.legal_name} {r.street_type} "
                    f"{r.street_name} {r.street_number} {r.neighborhood}"
                )
                if all(tok in haystack for tok in tokens):
                    matched.append(r)
                    if len(matched) >= MAX_DROPDOWN_OPTIONS:
                        break

        return [
            {"label": r.search_label, "value": r.record_id} for r in matched
        ]


RUNTIME = ApplicationRuntime()
DEFAULT_RESTAURANT_ID = RUNTIME.restaurants[0].record_id


def _build_geohash_cell_rectangles(
    query_prefix: str, search_prefixes: List[str]
) -> List[Any]:
    """Constrói os polígonos retangulares da célula Geohash central e de suas 8 adjacentes."""
    rectangles: List[Any] = []
    for prefix in search_prefixes:
        bbox = decode_bbox(prefix)
        is_center = prefix == query_prefix
        bounds = [[bbox.min_lat, bbox.min_lon], [bbox.max_lat, bbox.max_lon]]
        rectangles.append(
            dl.Rectangle(
                bounds=bounds,
                color="#0369a1" if is_center else "#0284c7",
                weight=2 if is_center else 1,
                dashArray="3, 3" if is_center else "6, 6",
                fillColor="#0284c7",
                fillOpacity=0.09 if is_center else 0.03,
                children=[
                    dl.Tooltip(
                        f"Célula Geohash {'Central' if is_center else 'Adjacente'}: {prefix}"
                    )
                ],
            )
        )
    return rectangles


def _build_map_overlays(
    result: QueryResult, show_geohash_cells: bool = True
) -> Tuple[List[Any], List[float]]:
    """Constrói os elementos visuais do mapa interativo (células Geohash, círculo de raio,
    pino do restaurante, pinos vermelhos em destaque e pinos cinzas descartados).
    """
    overlays: List[Any] = []
    rest = result.restaurant

    if show_geohash_cells:
        overlays.extend(
            _build_geohash_cell_rectangles(
                result.query_prefix, result.search_prefixes
            )
        )

    # Círculo do raio de atendimento configurado pelo usuário
    overlays.append(
        dl.Circle(
            center=[rest.latitude, rest.longitude],
            radius=result.radius_km * 1000.0,
            color="#dc2626",
            weight=2,
            fillColor="#dc2626",
            fillOpacity=0.07,
        )
    )

    # Entregadores descartados (fora do raio): plotados sem destaque (pino cinza)
    for item in result.discarded_couriers:
        c = item.courier
        overlays.append(
            dl.CircleMarker(
                center=[c.latitude, c.longitude],
                radius=5,
                color="#475569",
                weight=1,
                fillColor="#94a3b8",
                fillOpacity=0.65,
                children=[
                    dl.Tooltip(
                        f"{c.courier_id} | Fora do raio ({item.distance_km:.2f} km)"
                    ),
                    dl.Popup(
                        html.Div(
                            [
                                html.Strong(f"{c.courier_id} (Descartado)"),
                                html.Br(),
                                html.Span(f"Via projetada: {c.snapped_street}"),
                                html.Br(),
                                html.Span(f"Geohash: {c.geohash}"),
                                html.Br(),
                                html.Span(f"Distância: {item.distance_km:.3f} km"),
                                html.Br(),
                                html.Span(f"ETA estimado: {item.eta_minutes:.1f} min"),
                            ]
                        )
                    ),
                ],
            )
        )

    # Entregadores filtrados dentro do raio: plotados em destaque (pino vermelho)
    for rank, item in enumerate(result.matched_couriers, start=1):
        c = item.courier
        overlays.append(
            dl.CircleMarker(
                center=[c.latitude, c.longitude],
                radius=8,
                color="#ffffff",
                weight=2,
                fillColor="#dc2626",
                fillOpacity=0.95,
                children=[
                    dl.Tooltip(
                        f"#{rank} {c.courier_id} | {item.distance_km:.2f} km | {item.eta_minutes:.1f} min"
                    ),
                    dl.Popup(
                        html.Div(
                            [
                                html.Strong(
                                    f"#{rank} - {c.courier_id} (Selecionado)"
                                ),
                                html.Br(),
                                html.Span(f"Via projetada: {c.snapped_street}"),
                                html.Br(),
                                html.Span(f"Geohash: {c.geohash}"),
                                html.Br(),
                                html.Span(f"Distância: {item.distance_km:.3f} km"),
                                html.Br(),
                                html.Span(f"ETA estimado: {item.eta_minutes:.1f} min"),
                            ]
                        )
                    ),
                ],
            )
        )

    # Pino do restaurante consultado (destaque azul)
    overlays.append(
        dl.CircleMarker(
            center=[rest.latitude, rest.longitude],
            radius=10,
            color="#ffffff",
            weight=3,
            fillColor="#1d4ed8",
            fillOpacity=1.0,
            children=[
                dl.Tooltip(
                    f"Restaurante: {rest.display_name} ({rest.formatted_address})"
                ),
                dl.Popup(
                    html.Div(
                        [
                            html.Strong(rest.display_name),
                            html.Br(),
                            html.Span(rest.formatted_address),
                            html.Br(),
                            html.Span(f"CNAE: {rest.cnae_description}"),
                            html.Br(),
                            html.Span(f"Geohash: {rest.geohash}"),
                        ]
                    )
                ),
            ],
        )
    )

    return overlays, [rest.latitude, rest.longitude]


def create_dash_app() -> dash.Dash:
    app = dash.Dash(
        __name__,
        title="Monitoramento Geoespacial Híbrido - DCC207 UFMG",
        update_title=None,
    )

    initial_options = RUNTIME.search_restaurants("")

    app.layout = html.Div(
        [
            # Cabeçalho Institucional e Técnico
            html.Header(
                className="app-header",
                children=[
                    html.Div(
                        className="header-title-group",
                        children=[
                            html.H1(
                                "Motor de Busca e Monitoramento Geoespacial Híbrido — Belo Horizonte",
                                className="header-title",
                            ),
                            html.P(
                                "DCC207 Algoritmos 2 (UFMG) • Indexação por Prefixo Geohash (Base32) em Trie Compacta + Filtragem Geométrica Viária",
                                className="header-subtitle",
                            ),
                        ],
                    ),
                    html.Div(
                        className="header-badges",
                        children=[
                            html.Span(
                                f"Base PBH: {len(RUNTIME.restaurants):,} estabelecimentos",
                                className="tech-badge",
                            ),
                            html.Span(
                                f"Malha OSM: {len(RUNTIME.road_index.nodes):,} pontos viários",
                                className="tech-badge",
                            ),
                        ],
                    ),
                ],
            ),
            # Área Principal
            html.Main(
                className="main-workspace",
                children=[
                    # Coluna Esquerda: Controles de Consulta, Simulador e Diagnóstico da Trie
                    html.Aside(
                        className="sidebar-panel",
                        children=[
                            # Card 1: Busca de Restaurante e Parâmetros de Filtragem
                            html.Div(
                                className="control-card",
                                children=[
                                    html.H2(
                                        "1. Consulta de Restaurante e Raio",
                                        className="section-header",
                                    ),
                                    html.Div(
                                        className="field-group",
                                        children=[
                                            html.Label(
                                                "Filtrar por nome, logradouro ou bairro:",
                                                htmlFor="search-text-input",
                                                className="field-label",
                                            ),
                                            dcc.Input(
                                                id="search-text-input",
                                                type="text",
                                                placeholder="Ex.: Savassi, Afonso Pena, Pampa, Lourdes...",
                                                value="",
                                                debounce=False,
                                                className="text-input",
                                            ),
                                            html.Span(
                                                "Digite parte do nome fantasia, razão social, rua ou bairro.",
                                                className="field-hint",
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        className="field-group",
                                        children=[
                                            html.Label(
                                                "Estabelecimento selecionado:",
                                                htmlFor="restaurant-dropdown",
                                                className="field-label",
                                            ),
                                            dcc.Dropdown(
                                                id="restaurant-dropdown",
                                                options=initial_options,
                                                value=DEFAULT_RESTAURANT_ID,
                                                clearable=False,
                                                searchable=True,
                                                placeholder="Selecione um restaurante...",
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        className="field-group",
                                        children=[
                                            html.Label(
                                                id="radius-label-display",
                                                children=f"Raio máximo de atendimento: {INITIAL_RADIUS_KM:.1f} km",
                                                className="field-label",
                                            ),
                                            dcc.Slider(
                                                id="radius-slider",
                                                min=0.5,
                                                max=6.0,
                                                step=0.25,
                                                value=INITIAL_RADIUS_KM,
                                                marks={
                                                    0.5: "0.5km",
                                                    2.0: "2km",
                                                    3.5: "3.5km",
                                                    5.0: "5km",
                                                    6.0: "6km",
                                                },
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        className="field-group",
                                        children=[
                                            dcc.Checklist(
                                                id="show-cells-toggle",
                                                options=[
                                                    {
                                                        "label": " Exibir grade das 9 células Geohash consultadas",
                                                        "value": "show",
                                                    }
                                                ],
                                                value=["show"],
                                                style={"fontSize": "12px"},
                                            )
                                        ],
                                    ),
                                ],
                            ),
                            # Card 2: Simulador de Geração de Entregadores
                            html.Div(
                                className="control-card",
                                children=[
                                    html.H2(
                                        "2. Simulador da Frota de Entregadores",
                                        className="section-header",
                                    ),
                                    html.Div(
                                        className="field-group",
                                        children=[
                                            html.Label(
                                                "Quantidade de entregadores (N):",
                                                htmlFor="courier-count-input",
                                                className="field-label",
                                            ),
                                            dcc.Input(
                                                id="courier-count-input",
                                                type="number",
                                                min=10,
                                                max=5000,
                                                step=10,
                                                value=INITIAL_COURIER_COUNT,
                                                className="number-input",
                                            ),
                                            html.Span(
                                                "Distribuição normal centrada nos restaurantes + projeção viária OSM.",
                                                className="field-hint",
                                            ),
                                        ],
                                    ),
                                    html.Button(
                                        "Gerar Entregadores",
                                        id="generate-couriers-btn",
                                        n_clicks=0,
                                        className="action-button",
                                    ),
                                ],
                            ),
                            # Card 3: Detalhes do Restaurante e Diagnóstico da Trie
                            html.Div(
                                className="control-card",
                                children=[
                                    html.H2(
                                        "3. Diagnóstico Geohash & Trie Compacta",
                                        className="section-header",
                                    ),
                                    html.Div(
                                        id="restaurant-diagnostics-panel",
                                        className="restaurant-detail-box",
                                    ),
                                ],
                            ),
                        ],
                    ),
                    # Coluna Direita: KPIs, Mapa Interativo e Tabela de Entregadores
                    html.Section(
                        className="content-panel",
                        children=[
                            # Barra de Métricas Resumo
                            html.Div(
                                id="kpi-summary-bar",
                                className="kpi-grid",
                            ),
                            # Card do Mapa Interativo
                            html.Div(
                                className="map-card",
                                children=[
                                    html.Div(
                                        className="map-toolbar",
                                        children=[
                                            html.Span(
                                                "Mapa Operacional de Belo Horizonte (OpenStreetMap)",
                                                className="map-toolbar-title",
                                            ),
                                            html.Div(
                                                className="legend-group",
                                                children=[
                                                    html.Span(
                                                        [
                                                            html.Span(
                                                                className="legend-dot restaurant"
                                                            ),
                                                            "Restaurante Consultado",
                                                        ],
                                                        className="legend-item",
                                                    ),
                                                    html.Span(
                                                        [
                                                            html.Span(
                                                                className="legend-dot matched"
                                                            ),
                                                            "Entregador no Raio (Destaque)",
                                                        ],
                                                        className="legend-item",
                                                    ),
                                                    html.Span(
                                                        [
                                                            html.Span(
                                                                className="legend-dot discarded"
                                                            ),
                                                            "Entregador Descartado",
                                                        ],
                                                        className="legend-item",
                                                    ),
                                                    html.Span(
                                                        [
                                                            html.Span(
                                                                className="legend-circle"
                                                            ),
                                                            "Raio de Filtragem",
                                                        ],
                                                        className="legend-item",
                                                    ),
                                                    html.Span(
                                                        [
                                                            html.Span(
                                                                className="legend-box"
                                                            ),
                                                            "Célula Geohash + 8 Adjacentes",
                                                        ],
                                                        className="legend-item",
                                                    ),
                                                ],
                                            ),
                                        ],
                                    ),
                                    dl.Map(
                                        id="bh-leaflet-map",
                                        center=[BH_CENTER_LAT, BH_CENTER_LON],
                                        zoom=14,
                                        style={
                                            "width": "100%",
                                            "height": "520px",
                                        },
                                        children=[
                                            dl.TileLayer(
                                                url="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                                                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                                            ),
                                            dl.LayerGroup(id="map-overlays-layer"),
                                        ],
                                    ),
                                ],
                            ),
                            # Card da Tabela Descritiva
                            html.Div(
                                className="table-card",
                                children=[
                                    html.Div(
                                        className="table-header-bar",
                                        children=[
                                            html.H3(
                                                "Entregadores Habilitados Dentro do Raio de Atendimento",
                                                className="table-title",
                                            ),
                                            html.Span(
                                                id="table-subtitle-meta",
                                                className="table-meta",
                                            ),
                                        ],
                                    ),
                                    dash_table.DataTable(
                                        id="couriers-table",
                                        columns=[
                                            {"name": "Ordem", "id": "rank"},
                                            {"name": "ID Entregador", "id": "courier_id"},
                                            {"name": "Distância (km)", "id": "distance_km"},
                                            {"name": "Tempo Estimado (ETA)", "id": "eta_label"},
                                            {"name": "Geohash (Base32)", "id": "geohash"},
                                            {"name": "Via Projetada (OSM)", "id": "snapped_street"},
                                            {"name": "Coordenadas (Lat, Lon)", "id": "coords"},
                                        ],
                                        data=[],
                                        page_size=10,
                                        sort_action="native",
                                        style_table={"overflowX": "auto"},
                                        style_header={
                                            "backgroundColor": "#f1f5f9",
                                            "color": "#1e293b",
                                            "fontWeight": "700",
                                            "fontSize": "12px",
                                            "border": "1px solid #cbd5e1",
                                            "textAlign": "left",
                                            "padding": "8px 10px",
                                        },
                                        style_cell={
                                            "fontFamily": "Inter, sans-serif",
                                            "fontSize": "12.5px",
                                            "color": "#0f172a",
                                            "padding": "7px 10px",
                                            "border": "1px solid #e2e8f0",
                                            "textAlign": "left",
                                        },
                                        style_data_conditional=[
                                            {
                                                "if": {"row_index": "odd"},
                                                "backgroundColor": "#f8fafc",
                                            },
                                            {
                                                "if": {"column_id": "geohash"},
                                                "fontFamily": "JetBrains Mono, monospace",
                                            },
                                            {
                                                "if": {"column_id": "courier_id"},
                                                "fontWeight": "600",
                                                "color": "#dc2626",
                                            },
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ]
    )

    @app.callback(
        Output("restaurant-dropdown", "options"),
        Output("restaurant-dropdown", "value"),
        Input("search-text-input", "value"),
        State("restaurant-dropdown", "value"),
    )
    def update_restaurant_options(
        search_text: Optional[str], current_value: Optional[int]
    ) -> Tuple[List[Dict[str, Any]], int]:
        options = RUNTIME.search_restaurants(search_text or "")
        if not options:
            fallback = RUNTIME.restaurant_by_id.get(
                current_value or DEFAULT_RESTAURANT_ID, RUNTIME.restaurants[0]
            )
            return [{"label": fallback.search_label, "value": fallback.record_id}], fallback.record_id

        option_values = {opt["value"] for opt in options}
        if current_value in option_values and not search_text:
            return options, current_value
        return options, options[0]["value"]

    @app.callback(
        Output("map-overlays-layer", "children"),
        Output("bh-leaflet-map", "center"),
        Output("couriers-table", "data"),
        Output("kpi-summary-bar", "children"),
        Output("restaurant-diagnostics-panel", "children"),
        Output("radius-label-display", "children"),
        Output("table-subtitle-meta", "children"),
        Input("restaurant-dropdown", "value"),
        Input("radius-slider", "value"),
        Input("generate-couriers-btn", "n_clicks"),
        Input("show-cells-toggle", "value"),
        State("courier-count-input", "value"),
    )
    def update_spatial_view(
        restaurant_id: Optional[int],
        radius_km: Optional[float],
        generate_clicks: Optional[int],
        show_cells_values: Optional[List[str]],
        requested_courier_count: Optional[int],
    ):
        ctx = callback_context
        triggered_id = (
            ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""
        )

        if triggered_id == "generate-couriers-btn":
            count = max(1, min(5000, int(requested_courier_count or INITIAL_COURIER_COUNT)))
            RUNTIME.regenerate_fleet(count)

        effective_radius = float(radius_km or INITIAL_RADIUS_KM)
        rest = RUNTIME.restaurant_by_id.get(
            int(restaurant_id or DEFAULT_RESTAURANT_ID), RUNTIME.restaurants[0]
        )

        result = RUNTIME.engine.query_by_restaurant(
            rest, radius_km=effective_radius
        )
        show_cells = bool(show_cells_values and "show" in show_cells_values)
        overlays, map_center = _build_map_overlays(
            result, show_geohash_cells=show_cells
        )

        # Popula dados da tabela descritiva
        table_rows = []
        for idx, match in enumerate(result.matched_couriers, start=1):
            c = match.courier
            table_rows.append(
                {
                    "rank": idx,
                    "courier_id": c.courier_id,
                    "distance_km": f"{match.distance_km:.3f} km",
                    "eta_label": f"{match.eta_minutes:.1f} min",
                    "geohash": c.geohash,
                    "snapped_street": c.snapped_street,
                    "coords": f"({c.latitude:.5f}, {c.longitude:.5f})",
                }
            )

        total_fleet = len(RUNTIME.engine.couriers)
        matched_count = len(result.matched_couriers)
        if matched_count > 0:
            min_dist_str = f"{result.matched_couriers[0].distance_km:.2f} km"
            min_eta_str = f"ETA: {result.matched_couriers[0].eta_minutes:.1f} min"
            avg_eta_val = sum(m.eta_minutes for m in result.matched_couriers) / matched_count
            avg_eta_str = f"{avg_eta_val:.1f} min"
        else:
            min_dist_str = "N/A"
            min_eta_str = "Sem cobertura no raio"
            avg_eta_str = "N/A"

        _, trie_nodes, trie_depth = RUNTIME.engine.trie.stats()

        kpi_cards = [
            html.Div(
                className="kpi-card",
                children=[
                    html.Div("Frota Ativa (N)", className="kpi-label"),
                    html.Div(f"{total_fleet}", className="kpi-value"),
                    html.Div(
                        f"Gerada em {RUNTIME.last_generation_ms:.1f} ms",
                        className="kpi-sub",
                    ),
                ],
            ),
            html.Div(
                className="kpi-card",
                children=[
                    html.Div("Candidatos Trie (9 células)", className="kpi-label"),
                    html.Div(
                        f"{result.trie_candidates_count}",
                        className="kpi-value highlight-blue",
                    ),
                    html.Div(
                        f"Prefixo p={result.prefix_precision} ({result.query_prefix})",
                        className="kpi-sub",
                    ),
                ],
            ),
            html.Div(
                className="kpi-card",
                children=[
                    html.Div("Filtrados no Raio", className="kpi-label"),
                    html.Div(
                        f"{matched_count}",
                        className="kpi-value highlight-red",
                    ),
                    html.Div(
                        f"Descartados: {len(result.discarded_couriers)}",
                        className="kpi-sub",
                    ),
                ],
            ),
            html.Div(
                className="kpi-card",
                children=[
                    html.Div("Entregador Mais Próximo", className="kpi-label"),
                    html.Div(min_dist_str, className="kpi-value"),
                    html.Div(min_eta_str, className="kpi-sub"),
                ],
            ),
            html.Div(
                className="kpi-card",
                children=[
                    html.Div("ETA Médio no Raio", className="kpi-label"),
                    html.Div(avg_eta_str, className="kpi-value"),
                    html.Div("Velocidade média: 25 km/h", className="kpi-sub"),
                ],
            ),
            html.Div(
                className="kpi-card",
                children=[
                    html.Div("Tempo de Resposta", className="kpi-label"),
                    html.Div(
                        f"{result.total_query_ms:.3f} ms",
                        className="kpi-value",
                    ),
                    html.Div(
                        f"Trie: {result.trie_lookup_ms:.3f} ms | Geom: {result.geometric_filter_ms:.3f} ms",
                        className="kpi-sub",
                    ),
                ],
            ),
        ]

        diagnostics_children = [
            html.Div(
                [
                    html.Span("Estabelecimento:", className="detail-key"),
                    html.Span(rest.display_name, className="detail-val"),
                ],
                className="detail-row",
            ),
            html.Div(
                [
                    html.Span("Endereço:", className="detail-key"),
                    html.Span(rest.formatted_address, className="detail-val"),
                ],
                className="detail-row",
            ),
            html.Div(
                [
                    html.Span("Coordenadas:", className="detail-key"),
                    html.Span(
                        f"{rest.latitude:.5f}, {rest.longitude:.5f}",
                        className="detail-val mono-code",
                    ),
                ],
                className="detail-row",
            ),
            html.Div(
                [
                    html.Span("Geohash (p=7):", className="detail-key"),
                    html.Span(rest.geohash, className="detail-val mono-code"),
                ],
                className="detail-row",
            ),
            html.Div(
                [
                    html.Span("Prefixo de Busca:", className="detail-key"),
                    html.Span(
                        f"{result.query_prefix} (nível {result.prefix_precision})",
                        className="detail-val mono-code",
                    ),
                ],
                className="detail-row",
            ),
            html.Div(
                [
                    html.Span("Células Consultadas (9):", className="detail-key"),
                    html.Span(
                        ", ".join(result.search_prefixes),
                        className="detail-val mono-code",
                    ),
                ],
                className="detail-row",
            ),
            html.Div(
                [
                    html.Span("Nós na Trie Compacta:", className="detail-key"),
                    html.Span(
                        f"{trie_nodes} nós (altura máx. {trie_depth})",
                        className="detail-val",
                    ),
                ],
                className="detail-row",
            ),
        ]

        radius_label = f"Raio máximo de atendimento: {effective_radius:.2f} km"
        table_subtitle = (
            f"Exibindo {matched_count} entregador(es) a até {effective_radius:.2f} km de "
            f"{rest.display_name} ({rest.neighborhood}) — ordenados por distância."
        )

        return (
            overlays,
            map_center,
            table_rows,
            kpi_cards,
            diagnostics_children,
            radius_label,
            table_subtitle,
        )

    return app


if __name__ == "__main__":
    application = create_dash_app()
    application.run(host="0.0.0.0", port=8050, debug=False)

