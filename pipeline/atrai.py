"""ATRAI-Datenplattform (Sensorfahrräder, Kampagne Heilbronn): laden, cachen, auf Kanten mappen.

API (OGC API Features, ohne Token lesbar): https://api.atrai.bike/collections/<id>/items
  overtaking_distance_heilbronn  Segmente: Ø Überholabstand (cm)
  danger_zones_heilbronn         Punkte:   Risk Index Overtaking (0–1)
  bumpy_roads_heilbronn          Segmente: Normalized Roughness (0–100)
  speed_map_heilbronn            Segmente: Ø Radtempo (km/h)
  traffic_flow_heilbronn         Segmente: avg_traffic_flow (0–1)
  osem_bike_data                 Rohpunkte aller Kampagnen weltweit -> wir behalten Heilbronn;
                                 daraus PM2.5 (Messungen mit rel. Feuchte > 75 % verworfen, wie ATRAI)
"""
import json
import urllib.request

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from . import config as C

API = "https://api.atrai.bike/collections/{c}/items?limit={n}&offset={o}"
DIR = C.RAW / "atrai"
SEGMENTS = {
    "overtaking": ("overtaking_distance_heilbronn", "Average Overtaking Distance cm"),
    "roughness": ("bumpy_roads_heilbronn", "Normalized Roughness"),
    "speed": ("speed_map_heilbronn", "avg_speed[km/h]"),
    "flow": ("traffic_flow_heilbronn", "avg_traffic_flow"),
}
HN_BBOX = (9.04, 49.08, 9.31, 49.22)


def _fetch(coll, page=10000, keep=None):
    feats, off = [], 0
    while True:
        req = urllib.request.Request(API.format(c=coll, n=page, o=off),
                                     headers={"User-Agent": "GreenCityHackathon-Heilbronn/0.1"})
        with urllib.request.urlopen(req, timeout=180) as r:
            fs = json.load(r)["features"]
        feats += [f for f in fs if keep is None or keep(f)]
        off += page
        if len(fs) < page:
            return feats


def _to_gdf(feats):
    return gpd.GeoDataFrame.from_features(feats, crs=4326).to_crs(C.CRS)


def load():
    """Alle benötigten Collections als GeoDataFrames (gecacht als GeoParquet in data/raw/atrai)."""
    DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for key, (coll, _) in SEGMENTS.items():
        p = DIR / f"{coll}.parquet"
        if not p.exists():
            _to_gdf(_fetch(coll)).to_parquet(p)
        out[key] = gpd.read_parquet(p)
    p = DIR / "danger_zones_heilbronn.parquet"
    if not p.exists():
        _to_gdf(_fetch("danger_zones_heilbronn")).to_parquet(p)
    out["danger"] = gpd.read_parquet(p)
    p = DIR / "osem_bike_data_heilbronn.parquet"
    if not p.exists():
        x0, y0, x1, y1 = HN_BBOX

        def hn(f):
            x, y = f["geometry"]["coordinates"][:2]
            return x0 <= x <= x1 and y0 <= y <= y1
        _to_gdf(_fetch("osem_bike_data", keep=hn)).to_parquet(p)
    out["raw"] = gpd.read_parquet(p)
    for k, v in out.items():
        print(f"  ATRAI {k}: {len(v)}")
    return out


# --- Zuordnung auf Kanten ---------------------------------------------------------------

def _snap(edges, pts, max_dist):
    """Nächste Kante je Punkt (innerhalb max_dist), sonst -1."""
    tree = shapely.STRtree(edges.geometry.values)
    pi, ei = tree.query_nearest(pts, max_distance=max_dist, all_matches=False)
    idx = np.full(len(pts), -1)
    idx[pi] = ei
    return idx


def _segments_to_edges(edges, seg, col, step=5.0, max_dist=8.0):
    """Segmentwerte über Stützpunkte alle 5 m auf die nächste Kante übertragen; je Kante Mittelwert."""
    seg = seg[seg[col].notna()]
    geoms = seg.geometry.values
    L = shapely.length(geoms)
    n = np.maximum(np.ceil(L / step).astype(int), 1) + 1
    gid = np.repeat(np.arange(len(geoms)), n)
    start = np.repeat(np.cumsum(n) - n, n)
    frac = (np.arange(n.sum()) - start) / np.repeat(n - 1, n)
    pts = shapely.line_interpolate_point(geoms[gid], frac, normalized=True)
    e = _snap(edges, pts, max_dist)
    ok = e >= 0
    df = pd.DataFrame({"e": e[ok], "v": seg[col].astype(float).to_numpy()[gid[ok]]})
    return df.groupby("e").v.mean()


def _points_to_edges(edges, pts, values, max_dist=15.0, agg="mean"):
    e = _snap(edges, pts.geometry.values, max_dist)
    ok = e >= 0
    df = pd.DataFrame({"e": e[ok], "v": np.asarray(values, float)[ok]}).dropna()
    g = df.groupby("e").v
    return g.agg(agg), g.size()


def attach(edges, data):
    """Hängt Rohwerte (atrai_*) und normierte Kriterien 0–1 (crit_*) an die Kanten.

    Normierung (1 = schlecht). Die ATRAI-Indizes sind laut Doku relativ (Median Risk Index 0,86)
    und PM2.5 ist absolut niedrig (Median 3 µg/m³), daher Rangwerte innerhalb der gemessenen Kanten:
      danger    Mittel aus clip((150 − Überholabstand_cm) / 100, 0, 1)  [150 cm = gesetzl. Mindestabstand
                innerorts, ≤ 50 cm -> 1]  und Perzentilrang des Risk Index Overtaking
      pm        Perzentilrang des PM2.5-Medians (nur Kanten mit ≥ 3 Messpunkten)
      rough     clip(Normalized Roughness / 40, 0, 1)
    Tempo geht nicht als Kriterium, sondern als Fahrzeit ein (siehe bike.py).
    Kanten ohne Messung bekommen den Median der gemessenen Kanten (neutral) und has_* = False.
    """
    e = edges.copy()
    n = len(e)

    def put(name, s):
        a = np.full(n, np.nan)
        a[s.index.to_numpy()] = s.to_numpy()
        e[name] = a

    for key, (_, col) in SEGMENTS.items():
        put(f"atrai_{key}", _segments_to_edges(e, data[key], col))
    risk, cnt = _points_to_edges(e, data["danger"], data["danger"]["Risk Index Overtaking"])
    put("atrai_danger_risk", risk)
    put("atrai_danger_n", cnt)
    raw = data["raw"]
    pm = pd.to_numeric(raw["Finedust PM2.5"], errors="coerce")
    hum = pd.to_numeric(raw["Rel. Humidity"], errors="coerce")
    pm = pm.where(~(hum > 75))
    pm = pm.where(pm.between(0, 500))
    m = pm.notna().to_numpy()
    pmv, pmn = _points_to_edges(e, raw[m], pm[m], max_dist=15.0, agg="median")
    put("atrai_pm25", pmv)
    put("atrai_pm25_n", pmn)

    d1 = np.clip((150 - e["atrai_overtaking"]) / 100, 0, 1)
    d2 = e["atrai_danger_risk"].rank(pct=True)
    danger = pd.concat([d1, d2], axis=1).mean(axis=1, skipna=True)
    pm = e["atrai_pm25"].where(e["atrai_pm25_n"] >= 3)
    crits = {
        "danger": danger,
        "pm": pm.rank(pct=True),
        "rough": np.clip(e["atrai_roughness"] / 40, 0, 1),
    }
    for k, v in crits.items():
        v = pd.Series(np.asarray(v, float), index=e.index)
        e[f"has_{k}"] = v.notna()
        e[f"crit_{k}"] = v.fillna(v.median()).round(3)
    e["has_speed"] = e["atrai_speed"].notna()
    return e
