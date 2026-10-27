"""Mini-Demo: Hauptbahnhof -> Marktplatz, kürzeste vs. schattigste Route.

Gewicht = length × (1 + f × (1 − shade_HH)), f startet bei 2. Ist die schattige Route mehr als
25 % länger als die kürzeste, wird f in 0,25er-Schritten gesenkt.
    python -m pipeline.route_demo [--hour 15] [--out output]
"""
import argparse
import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox

from . import config as C


def route_stats(G, path, col):
    L = S = 0.0
    for u, v in zip(path[:-1], path[1:]):
        d = min(G[u][v].values(), key=lambda e: e["length"])
        L += d["length"]
        S += d["length"] * d[col]
    return L, S / L


def best_edge_attr(G, u, v, weight):
    return min(d[weight] for d in G[u][v].values())


def main(out=C.OUT, hour=C.DEMO_HOUR):
    out = Path(out)
    G = ox.load_graphml(out / "walk_shade.graphml")
    col = f"shade_{hour:02d}"
    for _, _, d in G.edges(data=True):
        d[col] = float(d[col])
    pts = gpd.GeoSeries(gpd.points_from_xy([C.HBF_LONLAT[0], C.MARKTPLATZ_LONLAT[0]],
                                           [C.HBF_LONLAT[1], C.MARKTPLATZ_LONLAT[1]]), crs=4326).to_crs(C.CRS)
    a, b = ox.distance.nearest_nodes(G, pts.x.tolist(), pts.y.tolist())

    short = nx.shortest_path(G, a, b, weight="length")
    Ls, Ss = route_stats(G, short, col)
    f = C.SHADE_FACTOR
    while True:
        for _, _, d in G.edges(data=True):
            d["w"] = d["length"] * (1 + f * (1 - d[col]))
        shady = nx.shortest_path(G, a, b, weight="w")
        Lh, Sh = route_stats(G, shady, col)
        if Lh <= Ls * (1 + C.MAX_DETOUR) or f <= 0.25:
            break
        f -= 0.25

    res = {"hour": hour, "factor": f,
           "shortest": {"length_m": round(Ls), "shade_share": round(Ss, 3)},
           "shadiest": {"length_m": round(Lh), "shade_share": round(Sh, 3),
                        "detour_pct": round(100 * (Lh / Ls - 1), 1)}}
    print(json.dumps(res, indent=2))
    (out / "route_demo.json").write_text(json.dumps(res, indent=2))

    # Routen als GeoPackage + PNG
    def geom(path):
        return ox.routing.route_to_gdf(G, path, weight="length").geometry.union_all()
    gdf = gpd.GeoDataFrame({"route": ["shortest", "shadiest"]}, geometry=[geom(short), geom(shady)], crs=C.CRS)
    gdf.to_file(out / "route_demo.gpkg", engine="pyogrio")
    _plot(out, gdf, hour, res)
    return res


def _plot(out, gdf, hour, res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    box = gdf.total_bounds
    pad = 150
    bb = (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)
    sh = gpd.read_file(out / "shadows.gpkg", layer=f"shadow_{hour:02d}", bbox=bb)
    bld = gpd.read_file(out / "buildings_heights.gpkg", bbox=bb)
    fig, ax = plt.subplots(figsize=(9, 6.5), dpi=150)
    sh.plot(ax=ax, color="#c9c7c1", linewidth=0)
    bld.plot(ax=ax, color="#8f8d87", linewidth=0)
    s, h = res["shortest"], res["shadiest"]
    gdf[gdf.route == "shortest"].plot(ax=ax, color="#e8762b", linewidth=3,
                                       label=f"Shortest: {s['length_m']} m, {s['shade_share']:.0%} shade")
    gdf[gdf.route == "shadiest"].plot(ax=ax, color="#184f95", linewidth=3,
                                       label=f"Shadiest: {h['length_m']} m, {h['shade_share']:.0%} shade")
    ax.set_xlim(bb[0], bb[2])
    ax.set_ylim(bb[1], bb[3])
    ax.set_axis_off()
    ax.legend(loc="lower left", frameon=False, fontsize=9)
    ax.set_title(f"Hauptbahnhof → Marktplatz at {hour:02d}:00, 15 July", loc="left", fontsize=11, color="#2b2b2b")
    fig.savefig(out / "maps" / "route_demo.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(C.OUT))
    ap.add_argument("--hour", type=int, default=C.DEMO_HOUR)
    a = ap.parse_args()
    main(a.out, a.hour)
