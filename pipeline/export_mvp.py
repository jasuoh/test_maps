"""Kompakter Radgraph für das Browser-MVP:  python -m pipeline.export_mvp

web/mvp/bike_graph.json
  hours:  [8, …, 20]
  nodes:  [[lon, lat], …]
  edges:  [[u, v, length_m, time_s, danger, pm, rough, flags, [shade_08…shade_20], [[lon, lat], …]], …]
          flags: Bit 0 has_danger, 1 has_pm, 2 has_rough, 3 has_speed
"""
import json

import geopandas as gpd
import numpy as np
import shapely

from . import config as C
from .bike import DEFAULT_SPEED


def main(out=C.OUT, web=C.ROOT / "web" / "mvp"):
    e = gpd.read_file(out / "edges_bike.gpkg").to_crs(4326)
    shade_cols = [f"shade_{h:02d}" for h in C.HOURS]
    node_ids = np.unique(np.r_[e.u.to_numpy(), e.v.to_numpy()])
    idx = {n: i for i, n in enumerate(node_ids)}
    # Knotenkoordinaten aus Kantenenden
    xy = {}
    for u, v, g in zip(e.u, e.v, e.geometry):
        c = g.coords
        xy.setdefault(u, c[0])
        xy.setdefault(v, c[-1])
    nodes = [[round(xy[n][0], 6), round(xy[n][1], 6)] for n in node_ids]

    def flag(col):
        return e[col].astype(str).eq("True").to_numpy() if col in e else np.zeros(len(e), bool)

    flags = flag("has_danger") * 1 + flag("has_pm") * 2 + flag("has_rough") * 4 + flag("has_speed") * 8
    v = e["atrai_speed"].to_numpy(float)
    speed = np.where((v >= 5) & (v <= 35), v, DEFAULT_SPEED)
    time_s = e["length"].to_numpy(float) / (speed / 3.6)
    geoms = shapely.simplify(e.geometry.values, 0.00001)
    edges = []
    for i, r in enumerate(e.itertuples(index=False)):
        coords = [[round(x, 6), round(y, 6)] for x, y in geoms[i].coords]
        edges.append([idx[r.u], idx[r.v], round(r.length, 1), round(float(time_s[i]), 1),
                      round(float(r.crit_danger), 3), round(float(r.crit_pm), 3),
                      round(float(r.crit_rough), 3), int(flags[i]),
                      [round(float(getattr(r, c)), 2) for c in shade_cols], coords])
    web.mkdir(parents=True, exist_ok=True)
    p = web / "bike_graph.json"
    p.write_text(json.dumps({"hours": C.HOURS, "nodes": nodes, "edges": edges}, separators=(",", ":")))
    print(f"  {p.relative_to(C.ROOT)}: {len(nodes)} Knoten, {len(edges)} Kanten, {p.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
