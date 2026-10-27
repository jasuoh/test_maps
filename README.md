# Shade routing Heilbronn – data pipeline

Green City Hackathon Heilbronn, 27–29 Oct 2026. For every edge of Heilbronn's walking network, this computes the share of the edge that lies in shade at each hour from 08:00 to 20:00 on a reference summer day (15 July). The routing API and frontend consume the results.

Background on data quality: [docs/interim_report_data.md](docs/interim_report_data.md).

## Quick start

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements.txt
.venv/bin/python -m pipeline.run_all        # downloads + computes everything (~6 min)
.venv/bin/python -m pipeline.maps           # PNG maps at 10, 14, 18 h
.venv/bin/python -m pipeline.route_demo     # Hbf -> Marktplatz at 15 h
.venv/bin/python -m pipeline.validate       # plausibility checks
.venv/bin/python -m pytest -q tests         # unit tests (cube, L-shape, gable roof, …)
```

Options for `run_all`:
- `--buildings osm` uses OSM buildings only (for comparison).
- `--radius 3000` limits the run to 3 km around the Marktplatz.
- `--out DIR` writes the results to another directory.

## Outputs (`output/`, all in EPSG:25832)

| File | Content |
|---|---|
| `edges_shade.gpkg` | layer `edges`: `u, v, key, length, highway, shade_08 … shade_20` (0–1), geometry |
| `walk_shade.graphml` | the same graph for OSMnx/networkx (`ox.load_graphml`), with `shade_HH` on every edge |
| `shadows.gpkg` | one layer per hour, `shadow_08 … shadow_20`, each holding a single MultiPolygon (for the map view) |
| `buildings_heights.gpkg` | buildings with `height`, `height_source` (`lod2` / `height` / `levels` / `default`), `kind`, `roof_type`, `ground_z` |
| `trees.gpkg` | all trees used: `source` (kataster/osm), `crown_d`, `crown_src`, `height` |
| `stats.csv`, `sun_positions.csv` | mean shade per hour, sun elevation and azimuth |
| `maps/shade_10.png …`, `maps/route_demo.png`, `route_demo.json` | check maps and the routing demo |

The frontend needs WGS84: `ogr2ogr -t_srs EPSG:4326 shadows_4326.gpkg output/shadows.gpkg`.
The graph is bidirectional, so every street appears as both u→v and v→u with identical shade values.

## Data sources

- **OpenStreetMap**: Geofabrik extract Regierungsbezirk Stuttgart (PBF), clipped with pyosmium to the city boundary (relation 62751). We took this route because Overpass was overloaded when we tested. The walking network uses exactly the OSMnx `network_type="walk"` filter (`pipeline/extract_osm.py`).
- **LGL Baden-Württemberg LoD2** (dl-de/by-2.0): 2 × 2 km CityGML tiles from `opengeodata.lgl-bw.de/data/lod2/`, downloaded automatically.
- **Baumkataster Heilbronn**, status 01.01.2026 (dl-de/by-2.0), `opendata.heilbronn.de`.
- Attribution: "© OpenStreetMap contributors (ODbL); Datenquelle: LGL, www.lgl-bw.de, dl-de/by-2.0; Stadt Heilbronn, dl-de/by-2.0".

## Method and assumptions

**Sun:** pvlib, Europe/Berlin (CEST), 15 July 2026, hourly 08–20, at the Marktplatz (49.143 N, 9.219 E). Below 3° elevation every edge counts as fully shaded. At 20:00 the sun is still at 11°.

**Buildings (default `--buildings lod2`):**
- The LoD2 model is the main source. Each building body or building part is a set of 3D faces. Its shadow is the union of the parallel projections of all faces onto the building's own ground level (z = min z of its GroundSurface). This is exact for any roof shape: a gable roof casts a shorter shadow at the eaves than at the ridge.
- An OSM building is kept only if its representative point lies outside every LoD2 footprint. That covers 5,620 buildings, mostly sheds and allotment huts.

**Buildings (OSM fallback):** a prism on flat ground. The shadow is the union of the footprint, its copy shifted by L = h / tan(elevation) away from the sun, and the parallelogram of every ring edge with its shifted copy (Minkowski sum, courtyards handled). Height is taken in this order:
1. `height`.
2. `building:levels` × 3 m + `roof:height`, or + 1.5 m if there is no `roof:height`.
3. A default by building type: garage 3 m, house/detached/semidetached 7 m, residential/apartments 12 m, commercial/retail 10 m, otherwise 8 m.

The bottom of the building is `min_height`, otherwise `building:min_level` × 3 m, otherwise 0. `roof:levels` is ignored, as specified.

**Trees:**
- The tree register has priority. OSM `natural=tree` trees are added only if no register tree lies within 3 m. `tree_row` lines are sampled every 8 m.
- Crown: `KRONE_DM`. If it is ≤ 2 m (the register's placeholder for non-city trees) or missing, it is estimated from the trunk as crown = 20 × girth / π, limited to 2–15 m, and the larger value wins. OSM trees use `diameter_crown`, otherwise 6 m.
- Height: the register has no tree heights, so H = clip(1.4 × crown + 2, 3, 30) m. OSM trees use `height` if it is tagged.
- Shadow: a circle with radius crown/2, shifted by (0.7 × H) / tan(elevation) away from the sun. The crown spans the upper 60 % of the tree, so its centre is at 0.7 H. Trunks are ignored.

**Edge shade:**
- Points are sampled every 2 m along each edge, including both end points.
- For streets (any `highway` other than footway/path/pedestrian/steps), two parallel lines are also sampled, one on each side, offset by `width`/2 or else 5 m. The edge value is the maximum of the three lines, because a pedestrian can choose the shady side.
- Point test: an STRtree over all shadow pieces. This gives the same result as testing against the dissolved union, but is faster. The union is computed separately per 500 m tile for `shadows.gpkg`.

**Simplifications in Phase 1:**
- Flat terrain: each building's shadow falls onto its own ground level, and slopes are ignored.
- No transmission through crowns: tree shadow counts as full shade.
- Bridges and other structures in LoD2 count as buildings.
- Shadows of buildings outside the city boundary are not included.

## Runtime

Measured on the development laptop (Apple Silicon) for the whole city: 100 km², 51,684 directed edges, 3,325 km, about 4.4 M sample points.

| Step | OSM only | LoD2 |
|---|---:|---:|
| First run: PBF/LoD2 download + extract | ~1 min + download | + ~1 min (43 tiles, 160 MB) |
| Buildings, trees, graph, sampling | 15 s | 15 s |
| Shadows + edge shade, 13 hours | 185 s | ~300 s |
| **Total (cached data)** | **~3.5 min** | **~5.5 min** |

## Routing demo

`pipeline/route_demo.py`:
- Edge weight = length × (1 + f × (1 − shade_15)), starting with f = 2.
- If the shadiest route is more than 25 % longer than the shortest one, f is lowered in steps of 0.25.
- The script prints the length and shade share of both routes.

## Bike network + ATRAI sensor data

`run_all` computes shade for two networks in the same pass over the shadow geometry:

| Network | Graph | Shade sampling |
|---|---|---|
| `walk` | OSMnx `walk` filter, bidirectional | centre line, plus both sides of streets; the edge gets the maximum (pedestrians pick the shady side) |
| `bike` | OSMnx `bike` filter, one-way streets respected | paths and cycleways: centre line. Streets: only the **right-hand side in the direction of travel**, offset max(width/2 − 1 m, 1.5 m), or 3 m without `width` |

The **ATRAI** data come from sensor bikes, campaign Heilbronn, Dec 2025 – Oct 2026. They are read from `https://api.atrai.bike/collections/<id>/items`; no token is needed. The pipeline caches them in `data/raw/atrai/` and attaches them to the bike edges (`pipeline/atrai.py`):

| Edge column | Source | Mapping |
|---|---|---|
| `atrai_overtaking` | `overtaking_distance_heilbronn`, mean overtaking distance in cm | segment points every 5 m, snapped to the nearest edge within 8 m, then averaged |
| `atrai_danger_risk`, `_n` | `danger_zones_heilbronn`, Risk Index Overtaking | points snapped to the nearest edge within 15 m, mean and count |
| `atrai_pm25`, `_n` | `osem_bike_data`, raw points in the Heilbronn bbox (PM2.5, readings with humidity > 75 % dropped) | median per edge, within 15 m |
| `atrai_roughness` | `bumpy_roads_heilbronn`, Normalized Roughness 0–100 | as for overtaking |
| `atrai_speed`, `atrai_flow` | `speed_map_heilbronn`, `traffic_flow_heilbronn` | as for overtaking |

**Criteria** `crit_*` run from 0 to 1, where 1 means bad:
- `crit_danger`: the mean of two parts:
  - clip((150 − overtaking cm) / 100, 0, 1). 150 cm is the legal minimum passing distance in built-up areas.
  - the percentile rank of the risk index.
- `crit_pm`: the percentile rank of PM2.5, using only edges with at least 3 readings.
- `crit_rough`: clip(roughness / 40, 0, 1).

We use ranks because ATRAI's indices are relative by design (median risk index 0.86) and PM2.5 is low in absolute terms (median 3.2 µg/m³, below the WHO guideline of 5). The ranks say where conditions are *relatively* worse. Edges without measurements get the median and `has_* = false`.

**Coverage** (share of bike edges with at least one measurement):

| Criterion | Coverage |
|---|---:|
| speed | 34 % |
| roughness | 30 % |
| PM2.5 | 18 % |
| danger | 7 % |

Coverage is concentrated on the routes the sensor bikes actually rode.

**Cost per edge** (`pipeline/bike.py`):
`t × (1 + w_heat·(1 − shade_HH) + w_danger·crit_danger + w_pm·crit_pm + w_rough·crit_rough)`
- t is the travel time, using the measured ATRAI speed (5–35 km/h), otherwise 15 km/h.
- Default weights: heat 1.0, danger 1.5, PM 0.5, roughness 0.5. They are meant to become sliders in the app.

`python -m pipeline.bike` compares *fastest*, *coolest* and *combined* for Hbf → Pfühlpark at 15:00:

| Profile | Length | Time | Shade | Danger | PM | Roughness |
|---|---:|---:|---:|---:|---:|---:|
| fastest | 3,466 m | 13.4 min | 33 % | 0.51 | 0.50 | 0.31 |
| coolest | 3,489 m | 13.8 min | 42 % | 0.50 | 0.52 | 0.28 |
| combined | 3,336 m | 13.8 min | 44 % | 0.47 | 0.50 | 0.30 |

On short trips with few alternatives the profiles hardly differ. Hbf → Bildungscampus, for example, is tied to a single Neckar bridge.

## Web export for the frontend (`web/`, in the repo)

`python -m pipeline.export_web` writes GeoJSON in WGS84 (RFC 7946):
- `shadows/shadow_HH.geojson`: shadows simplified by 0.3 m.
- `edges_walk.geojson` and `edges_bike.geojson`, including `crit_*`, `has_*` and `atrai_*`.
- `buildings.geojson` and `trees.geojson`.
- `meta.json` with the sun positions, statistics and attribution.

`output/shadows.gpkg` (~210 MB) and the GraphML files are too large for GitHub. They are in `.gitignore` and can be regenerated with `run_all`.

## Possible Valhalla integration (optional)

Valhalla cannot use custom edge weights such as `shade_HH`. Options for the frontend:
- Request alternatives with `"alternates": 2` and score them with our edge shade values.
- Use Valhalla only for turn-by-turn instructions, passing our shady route as waypoints to `/route` or `/trace_route`.

The shade routing itself runs on our own graph.

## Phase 2 (not started, needs approval)

- nDOM = DOM1 − DGM1 from the LGL. Tree heights and missing vegetation (private gardens, parks), plus terrain.
- Arbitrary date and time: precompute shadows for a grid of sun positions and use the nearest one at query time.
