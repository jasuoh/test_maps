"""Schritt 2: Gebäude + Höhen.

Höhe in dieser Reihenfolge (height_source):
  "height"  – Tag height (bei building:part ggf. minus min_height ist NICHT abgezogen; height ist absolute Oberkante)
  "levels"  – building:levels × 3 m + Dach (roof:height, sonst 1,5 m)
  "default" – nach Gebäudetyp (config.DEFAULT_HEIGHT_BY_TYPE, sonst 8 m)
Unterkante (min_h): min_height, sonst building:min_level × 3 m, sonst 0.
"""
import re

import geopandas as gpd
import numpy as np
import pandas as pd

from . import config as C

_NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def num(v):
    """'12 m', '12,5', '12;15' -> erste Zahl als float; Fuß ('40\'') wird umgerechnet."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    s = str(v)
    m = _NUM.search(s)
    if not m:
        return np.nan
    x = float(m.group().replace(",", "."))
    if "'" in s or "ft" in s:
        x *= 0.3048
    return x


def col(df, name):
    return df[name].map(num) if name in df else pd.Series(np.nan, index=df.index)


def compute_heights(feat: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    is_part = feat.get("building:part", pd.Series(None, index=feat.index)).notna()
    is_bld = feat.get("building", pd.Series(None, index=feat.index)).notna()
    poly = feat.geom_type.isin(["Polygon", "MultiPolygon"])
    b = feat[(is_bld | is_part) & poly].copy()
    b["kind"] = np.where(b.get("building:part").notna(), "part", "building")
    btype = b["building"].fillna(b.get("building:part")).fillna("yes").astype(str)
    b["btype"] = btype

    h_tag = col(b, "height")
    lv = col(b, "building:levels")
    roof = col(b, "roof:height").fillna(C.DEFAULT_ROOF)
    h_lv = lv * C.LEVEL_HEIGHT + roof
    h_def = btype.map(C.DEFAULT_HEIGHT_BY_TYPE).fillna(C.DEFAULT_HEIGHT)

    valid_tag = h_tag.gt(0) & h_tag.lt(300)
    valid_lv = lv.gt(0) & lv.lt(80)
    b["height"] = np.where(valid_tag, h_tag, np.where(valid_lv, h_lv, h_def))
    b["height_source"] = np.where(valid_tag, "height", np.where(valid_lv, "levels", "default"))

    mh = col(b, "min_height")
    mh = mh.fillna(col(b, "building:min_level") * C.LEVEL_HEIGHT).fillna(0.0)
    b["min_h"] = np.clip(mh, 0, None)
    b.loc[b.min_h >= b.height, "min_h"] = 0.0

    keep = ["kind", "btype", "height", "min_h", "height_source", "geometry"]
    b = b.reset_index()
    b["osmid"] = b["element"].astype(str) + "/" + b["id"].astype(str)
    return b[["osmid"] + keep]


def coverage(feat: gpd.GeoDataFrame) -> pd.DataFrame:
    """Abdeckung der Höhen-Tags für Gebäude (building=*, ohne building:part)."""
    bld = feat[feat.get("building").notna() & feat.geom_type.isin(["Polygon", "MultiPolygon"])]
    n = len(bld)
    rows = []
    h = col(bld, "height").gt(0)
    lv = col(bld, "building:levels").gt(0)
    for name, m in [("height", h), ("building:levels", lv), ("height ODER levels", h | lv),
                    ("roof:height", col(bld, "roof:height").notna()),
                    ("roof:levels", col(bld, "roof:levels").notna()),
                    ("min_height", col(bld, "min_height").notna())]:
        rows.append({"tag": name, "anzahl": int(m.sum()), "prozent": round(100 * m.sum() / n, 1)})
    df = pd.DataFrame(rows)
    df.attrs["n"] = n
    return df
