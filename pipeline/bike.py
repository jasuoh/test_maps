"""Radrouting mit kombinierter Kostenfunktion (Hitze, Gefahr, Feinstaub, Rauheit) + Demo.

Kosten je Kante (Sekunden, gewichtet):
    t      = length / v,   v = gemessenes ATRAI-Tempo (5–35 km/h), sonst 15 km/h
    cost_h = t × (1 + w_heat·(1 − shade_h) + w_danger·crit_danger + w_pm·crit_pm + w_rough·crit_rough)
Alle crit_* liegen in 0–1 (1 = schlecht); Kanten ohne Messung tragen den Median (neutral).

    python -m pipeline.bike [--hour 15] [--from LON LAT] [--to LON LAT]
"""
import argparse
import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox

from . import config as C

DEFAULT_SPEED = 15.0
WEIGHTS = {"heat": 1.0, "danger": 1.5, "pm": 0.5, "rough": 0.5}
PROFILES = {
    "fastest": {"heat": 0, "danger": 0, "pm": 0, "rough": 0},
    "coolest": {"heat": 2.0, "danger": 0, "pm": 0, "rough": 0},
    "combined": WEIGHTS,
}
# Hauptbahnhof -> Pfühlpark (Nominatim, geprüft)
DEMO_FROM = C.HBF_LONLAT
DEMO_TO = (9.2422, 49.1413)

NUM = ["length", "atrai_speed", "crit_danger", "crit_pm", "crit_rough"] + [f"shade_{h:02d}" for h in C.HOURS]
FLAGS = ["has_danger", "has_pm", "has_rough", "has_speed"]


def load(out=C.OUT):
    G = ox.load_graphml(Path(out) / "bike_shade.graphml")
    for _, _, d in G.edges(data=True):
        for k in NUM:
            d[k] = float(d.get(k, "nan"))
        for k in FLAGS:
            d[k] = str(d.get(k)) == "True"
        v = d["atrai_speed"]
        d["time_s"] = d["length"] / ((v if 5 <= v <= 35 else DEFAULT_SPEED) / 3.6)
    return G


def set_cost(G, hour, w, name="cost"):
    s = f"shade_{hour:02d}"
    for _, _, d in G.edges(data=True):
        d[name] = d["time_s"] * (1 + w["heat"] * (1 - d[s]) + w["danger"] * d["crit_danger"]
                                 + w["pm"] * d["crit_pm"] + w["rough"] * d["crit_rough"])


def summarize(G, path, hour, weight):
    s = f"shade_{hour:02d}"
    rows = [min(G[u][v].values(), key=lambda e: e[weight]) for u, v in zip(path[:-1], path[1:])]
    L = sum(r["length"] for r in rows)

    def wavg(k):
        return round(sum(r[k] * r["length"] for r in rows) / L, 3)

    def cov(k):
        return round(sum(r["length"] for r in rows if r[k]) / L, 3)

    return {"length_m": round(L), "time_min": round(sum(r["time_s"] for r in rows) / 60, 1),
            "shade": wavg(s), "danger": wavg("crit_danger"), "pm": wavg("crit_pm"),
            "rough": wavg("crit_rough"),
            "measured_share": {"danger": cov("has_danger"), "pm": cov("has_pm"),
                               "rough": cov("has_rough"), "speed": cov("has_speed")}}


def demo(out=C.OUT, hour=C.DEMO_HOUR, a=DEMO_FROM, b=DEMO_TO):
    out = Path(out)
    G = load(out)
    p = gpd.GeoSeries(gpd.points_from_xy([a[0], b[0]], [a[1], b[1]]), crs=4326).to_crs(C.CRS)
    na, nb = ox.distance.nearest_nodes(G, p.x.tolist(), p.y.tolist())
    res, geoms = {"hour": hour, "weights_combined": WEIGHTS}, {}
    for prof, w in PROFILES.items():
        set_cost(G, hour, w, prof)
        path = nx.shortest_path(G, na, nb, weight=prof)
        res[prof] = summarize(G, path, hour, prof)
        geoms[prof] = ox.routing.route_to_gdf(G, path, weight=prof).geometry.union_all()
    print(json.dumps(res, indent=2))
    (out / "bike_route_demo.json").write_text(json.dumps(res, indent=2))
    gdf = gpd.GeoDataFrame({"profile": list(geoms)}, geometry=list(geoms.values()), crs=C.CRS)
    gdf.to_file(out / "bike_route_demo.gpkg", engine="pyogrio")
    _plot(out, gdf, hour, res)
    return res


def _plot(out, gdf, hour, res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    b = gdf.total_bounds
    pad = 200
    bb = (b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad)
    sh = gpd.read_file(out / "shadows.gpkg", layer=f"shadow_{hour:02d}", bbox=bb)
    bld = gpd.read_file(out / "buildings_heights.gpkg", bbox=bb)
    ed = gpd.read_file(out / "edges_bike.gpkg", bbox=bb)
    fig, ax = plt.subplots(figsize=(9, 7.5), dpi=150)
    sh.plot(ax=ax, color="#d9d7d1", linewidth=0)
    bld.plot(ax=ax, color="#a8a6a0", linewidth=0)
    hot = ed[ed.has_danger.astype(str) == "True"]
    hot = hot[hot.crit_danger >= 0.5]
    if len(hot):
        hot.plot(ax=ax, color="#d03b3b", linewidth=5, alpha=0.35)
    colors = {"fastest": "#e8762b", "coolest": "#3987e5", "combined": "#0d366b"}
    for prof, c in colors.items():
        r = res[prof]
        gdf[gdf.profile == prof].plot(
            ax=ax, color=c, linewidth=2.6 if prof != "combined" else 3.2,
            label=f"{prof.capitalize()}: {r['length_m']} m, {r['time_min']} min, "
                  f"shade {r['shade']:.0%}, danger {r['danger']:.2f}")
    ax.plot([], [], color="#d03b3b", alpha=0.35, linewidth=5, label="Measured danger ≥ 0.5 (ATRAI)")
    ax.set_xlim(bb[0], bb[2])
    ax.set_ylim(bb[1], bb[3])
    ax.set_axis_off()
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.01), frameon=False, fontsize=8.5)
    ax.set_title(f"Bike: Hauptbahnhof → Pfühlpark at {hour:02d}:00, 15 July", loc="left",
                 fontsize=11, color="#2b2b2b")
    (out / "maps").mkdir(exist_ok=True)
    fig.savefig(out / "maps" / "bike_route_demo.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(C.OUT))
    ap.add_argument("--hour", type=int, default=C.DEMO_HOUR)
    ap.add_argument("--from", dest="a", type=float, nargs=2, default=DEMO_FROM)
    ap.add_argument("--to", dest="b", type=float, nargs=2, default=DEMO_TO)
    x = ap.parse_args()
    demo(x.out, x.hour, tuple(x.a), tuple(x.b))
