"""Ein Befehl berechnet alles neu:  python -m pipeline.run_all [--radius 3000]

Ausgaben in output/:
  edges_shade.gpkg, walk_shade.graphml, shadows.gpkg (Layer shadow_HH), buildings_heights.gpkg,
  sun_positions.csv, stats.csv
"""
import argparse
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
import shapely

from . import config as C
from . import atrai, download, edges as E, extract_osm, heights, lod2, shadows, trees

T0 = time.time()


def log(msg):
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def tiled_union(pieces, area, tile=500.0):
    """Vereinigung aller Schattenteile: je 500-m-Kachel vereinigen, zuschneiden, dann zusammenführen."""
    tree = shapely.STRtree(pieces)
    minx, miny, maxx, maxy = area.bounds
    tiles = np.array([shapely.box(x, y, x + tile, y + tile)
                      for x in np.arange(minx, maxx, tile) for y in np.arange(miny, maxy, tile)])
    q = tree.query(tiles, predicate="intersects")
    order = np.argsort(q[0], kind="stable")
    ti, pi = q[0][order], q[1][order]
    bounds = np.searchsorted(ti, np.arange(len(tiles) + 1))
    out = []
    for i in range(len(tiles)):
        sel = pi[bounds[i]:bounds[i + 1]]
        if len(sel):
            out.append(shapely.intersection(shapely.union_all(pieces[sel]), tiles[i]))
    u = shapely.union_all(out)
    return shapely.intersection(u, area)


def as_multipolygon(g):
    polys = [p for p in shapely.get_parts(g) if p.geom_type == "Polygon"]
    return shapely.MultiPolygon(polys)


def flatten_lists(df):
    for c in df.columns:
        if c != "geometry" and df[c].map(lambda v: isinstance(v, list)).any():
            df[c] = df[c].map(lambda v: ";".join(map(str, v)) if isinstance(v, list) else v)
    return df


def main(radius=None, buildings="lod2", out=C.OUT):
    out = Path(out)
    out.mkdir(exist_ok=True)
    log("Rohdaten")
    download.main()
    area = download.boundary().geometry.iloc[0]
    if radius:
        m = gpd.GeoSeries(gpd.points_from_xy(*[[v] for v in C.MARKTPLATZ_LONLAT]), crs=4326).to_crs(C.CRS)
        area = area.intersection(m.iloc[0].buffer(radius))
    area4326 = gpd.GeoSeries([area], crs=C.CRS).to_crs(4326).iloc[0]

    if not (C.INTERIM / "walk.osm").exists() or not (C.INTERIM / "features.osm").exists():
        log("OSM-Extrakt aus PBF")
        bbox = tuple(gpd.GeoSeries([area.buffer(300)], crs=C.CRS).to_crs(4326).total_bounds)
        extract_osm.extract(bbox, C.INTERIM / "walk.osm", C.INTERIM / "features.osm")

    log("Gebäude & Bäume")
    feat = ox.features_from_xml(C.INTERIM / "features.osm", polygon=area4326,
                                tags={"building": True, "building:part": True,
                                      "natural": ["tree", "tree_row"]}).to_crs(C.CRS)
    bld = heights.compute_heights(feat)
    cov = heights.coverage(feat)
    print(cov.to_string(index=False))
    faces = None
    if buildings == "lod2":
        log("LoD2 (LGL)")
        lb, faces = lod2.load(area)
        bld, n_rep = lod2.merge_with_osm(lb, bld)
        faces = faces.merge(lb[["bid", "ground_z"]], on="bid")
        print(f"  {len(lb)} LoD2-Körper, {len(faces)} Flächen; {n_rep} OSM-Gebäude ersetzt, "
              f"{(bld.height_source != 'lod2').sum()} OSM-Gebäude ergänzt")
    print(bld.height_source.value_counts().to_string())
    bld.to_file(out / "buildings_heights.gpkg", layer="buildings", engine="pyogrio")
    tr = trees.all_trees(feat)
    tr = tr[tr.within(area.buffer(50))]
    tr.to_file(out / "trees.gpkg", layer="trees", engine="pyogrio")

    nets = {}
    for net in C.NETWORKS:
        log(f"Netz {net}")
        if not (C.INTERIM / f"{net}.osm").exists():
            bbox = tuple(gpd.GeoSeries([area.buffer(300)], crs=C.CRS).to_crs(4326).total_bounds)
            extract_osm.extract_network(bbox, C.INTERIM / f"{net}.osm", getattr(extract_osm, f"is_{net}"))
        G = E.load_graph(area4326, net)
        ed = ox.graph_to_gdfs(G, nodes=False)
        pts, line_id, edge_row = E.sample_lines(ed, mode=net)
        nets[net] = dict(G=G, ed=ed, pts=pts, line_id=line_id, edge_row=edge_row)
        log(f"  {len(ed)} Kanten, {ed.length.sum() / 1000:.0f} km, {len(pts)} Abtastpunkte")

    sun = shadows.sun_positions()
    sun.to_csv(out / "sun_positions.csv", index=False)
    shadow_path = out / "shadows.gpkg"
    shadow_path.unlink(missing_ok=True)
    stats = []
    for r in sun.itertuples():
        col = f"shade_{r.hour:02d}"
        if r.elevation < C.MIN_SUN_ELEV:
            for n in nets.values():
                n["ed"][col] = 1.0
            union = area
        else:
            ob = bld[bld.height_source != "lod2"]
            pb, _ = shadows.building_shadow_pieces(ob.geometry.values, ob.height.values,
                                                   ob.min_h.values, r.elevation, r.azimuth)
            if faces is not None:
                pf = shadows.face_shadow_pieces(faces.geometry.values, faces.ground_z.values,
                                                r.elevation, r.azimuth)
                pb = np.concatenate([pf, pb])
            pt = shadows.tree_shadow_pieces(tr.geometry.values, tr.crown_d.values,
                                            tr.height.values, r.elevation, r.azimuth)
            pieces = np.concatenate([pb, pt])
            tree = shapely.STRtree(pieces)
            for n in nets.values():
                hit = tree.query(n["pts"], predicate="intersects")[0]
                shaded = np.zeros(len(n["pts"]), bool)
                shaded[hit] = True
                n["ed"][col] = np.round(E.edge_shade(shaded, n["line_id"], n["edge_row"], len(n["ed"])), 3)
            union = tiled_union(pieces, area)
        gpd.GeoDataFrame({"hour": [r.hour], "elevation": [r.elevation], "azimuth": [r.azimuth]},
                         geometry=[as_multipolygon(union)], crs=C.CRS).to_file(
            shadow_path, layer=f"shadow_{r.hour:02d}", engine="pyogrio")
        row = {"hour": r.hour, "elevation": round(r.elevation, 1), "azimuth": round(r.azimuth, 1),
               "shadow_area_km2": round(union.area / 1e6, 2)}
        for net, n in nets.items():
            ed, w = n["ed"], n["ed"].length
            pre = "" if net == "walk" else f"{net}_"
            row[f"{pre}mean_shade"] = round(ed[col].mean(), 4)
            row[f"{pre}mean_shade_length_weighted"] = round(float((ed[col] * w).sum() / w.sum()), 4)
        stats.append(row)
        log(f"  {r.hour:02d} Uhr: Sonne {r.elevation:5.1f}° / {r.azimuth:5.1f}°  mittl. Schatten "
            + "  ".join(f"{net} {n['ed'][col].mean():.3f}" for net, n in nets.items()))
    pd.DataFrame(stats).to_csv(out / "stats.csv", index=False)

    log("Schreiben")
    shade_cols = [f"shade_{h:02d}" for h in C.HOURS]
    extra = {"walk": [], "bike": []}
    if "bike" in nets:
        log("ATRAI-Daten an Radkanten")
        data = atrai.load()
        nets["bike"]["ed"] = atrai.attach(nets["bike"]["ed"], data)
        extra["bike"] = [c for c in nets["bike"]["ed"].columns if c.startswith(("atrai_", "crit_", "has_"))]
        cov = {c: round(float(nets["bike"]["ed"][c].mean()), 3) for c in nets["bike"]["ed"] if c.startswith("has_")}
        print(f"  Abdeckung (Anteil Kanten mit Messung): {cov}")
    for net, n in nets.items():
        G, ed = n["G"], n["ed"]
        cols = ["length", "highway", "name"] + shade_cols + extra[net]
        cols = [c for c in cols if c in ed.columns]
        eo = ed.reset_index()[["u", "v", "key"] + cols + ["geometry"]]
        name = "edges_shade.gpkg" if net == "walk" else f"edges_{net}.gpkg"
        flatten_lists(eo).to_file(out / name, layer="edges", engine="pyogrio")
        attrs = shade_cols + extra[net]
        for (u, v, k), row in ed[attrs].iterrows():
            G.edges[u, v, k].update({a: (bool(x) if isinstance(x, (bool, np.bool_)) else
                                         float(x)) for a, x in row.items()})
        ox.save_graphml(G, out / f"{net}_shade.graphml")
    log("fertig")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--radius", type=float, default=None, help="nur Radius (m) um den Marktplatz")
    ap.add_argument("--buildings", choices=["lod2", "osm"], default="lod2",
                    help="Gebäudequelle: LGL-LoD2 (+ OSM-Ergänzung) oder nur OSM")
    ap.add_argument("--out", default=str(C.OUT))
    a = ap.parse_args()
    main(a.radius, a.buildings, a.out)
