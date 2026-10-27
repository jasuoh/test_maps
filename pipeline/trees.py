"""Schritt 3: Bäume (Kataster vorrangig, OSM ergänzend).

Das Kataster enthält KRONE_DM (Kronendurchmesser) und ST_UMFANG (Stammumfang), aber
KEINE Baumhöhe. Annahmen:
  * Krone: KRONE_DM. Ist er <= 2 m (Standardwert für fremde Bäume laut readme) oder fehlt,
    wird er aus dem Stamm geschätzt: KD = 20 × BHD, BHD = ST_UMFANG / π (Baumgruppen: wie
    Einzelbaum, da Umfang = Summe) und auf [2, 15] m begrenzt; der größere Wert gewinnt.
  * Höhe:  H = clip(1.4 × KD + 2, 3, 30) m  (grobe Allometrie für Stadt-Laubbäume)
  * Kronenmittelhöhe: Hc = H − 0,3 × H = 0,7 × H (Krone nimmt obere 60 % ein)
OSM-Bäume: height bzw. diameter_crown, falls vorhanden, sonst KD = 6 m.
natural=tree_row wird alle 8 m in Einzelbäume zerlegt.
"""
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from . import config as C
from .heights import col


def crown_from_stem(umfang):
    return np.clip(20.0 * umfang / np.pi, 2.0, 15.0)


def height_from_crown(kd):
    return np.clip(1.4 * kd + 2.0, 3.0, 30.0)


def load_kataster():
    t = gpd.read_file(C.BKA_SHP).to_crs(C.CRS)
    kd = t["KRONE_DM"].fillna(0.0).to_numpy()
    stem = crown_from_stem(t["ST_UMFANG"].fillna(0.0).to_numpy())
    std = kd <= C.KATASTER_STD_CROWN
    t["crown_d"] = np.where(std, np.maximum(kd, stem), kd)
    t["crown_src"] = np.where(std, "stamm", "kataster")
    t["height"] = height_from_crown(t["crown_d"])
    t["source"] = "kataster"
    return t[["source", "crown_d", "crown_src", "height", "geometry"]]


def load_osm(feat):
    nat = feat.get("natural")
    pts = feat[(nat == "tree") & (feat.geom_type == "Point")]
    rows = feat[(nat == "tree_row") & feat.geom_type.isin(["LineString", "MultiLineString"])]
    # Baumreihen in Punkte zerlegen
    rp = []
    for g in rows.geometry:
        n = max(int(g.length // C.TREE_ROW_SPACING) + 1, 2)
        rp.extend(shapely.line_interpolate_point(g, np.linspace(0, g.length, n)))
    o = pd.concat([pts[["geometry"]].assign(h=col(pts, "height"), d=col(pts, "diameter_crown")),
                   gpd.GeoDataFrame({"h": np.full(len(rp), np.nan), "d": np.full(len(rp), np.nan)},
                                    geometry=rp, crs=C.CRS)],
                  ignore_index=True)
    o = gpd.GeoDataFrame(o, geometry="geometry", crs=C.CRS)
    kd = o["d"].where(o["d"].between(1, 40), C.OSM_TREE_DEFAULT_CROWN)
    h = o["h"].where(o["h"].between(2, 50), height_from_crown(kd))
    o["crown_d"], o["height"], o["crown_src"], o["source"] = kd, h, "osm", "osm"
    return o[["source", "crown_d", "crown_src", "height", "geometry"]]


def all_trees(feat):
    k = load_kataster()
    o = load_osm(feat)
    tree = shapely.STRtree(k.geometry.values)
    near = tree.query(o.geometry.values, predicate="dwithin", distance=C.TREE_DEDUP_DIST)
    drop = np.unique(near[0])
    o = o.drop(o.index[drop])
    t = pd.concat([k, o], ignore_index=True)
    print(f"  Bäume: {len(k)} Kataster + {len(o)} OSM (ergänzt, {len(drop)} Dubletten verworfen)")
    return gpd.GeoDataFrame(t, geometry="geometry", crs=C.CRS)
