"""LGL Baden-Württemberg 3D-Gebäudemodell LoD2 (CityGML 1.0, dl-de/by-2.0).

Kacheln 2×2 km: https://opengeodata.lgl-bw.de/data/lod2/LoD2_32_<E>_<N>_2_bw.zip
(E ungerade km, N gerade km; jede ZIP enthält vier 1-km-GML-Dateien).

Wir lesen jedes bldg:Building / bldg:BuildingPart mit eigenen Flächen (boundedBy):
  * footprint  = GroundSurface (2D)
  * ground_z   = min. Z der GroundSurface, height = max. Z − ground_z
  * faces      = alle Wand-/Dach-/Boden-/Abschlussflächen als 3D-Polygone
Der Schatten eines geschlossenen Körpers ist die Vereinigung der Parallelprojektionen
seiner Flächen auf die Bodenebene z = ground_z (siehe shadows.face_shadow_pieces).
"""
import io
import zipfile
from concurrent.futures import ProcessPoolExecutor

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from lxml import etree

from . import config as C
from .download import _get

URL = "https://opengeodata.lgl-bw.de/data/lod2/LoD2_32_{e}_{n}_2_bw.zip"
DIR = C.RAW / "lod2"
NS = {"bldg": "http://www.opengis.net/citygml/building/1.0",
      "gml": "http://www.opengis.net/gml",
      "core": "http://www.opengis.net/citygml/1.0"}
SURF = ("WallSurface", "RoofSurface", "GroundSurface", "ClosureSurface")


def tiles_for(area):
    minx, miny, maxx, maxy = (np.array(area.bounds) / 1000).tolist()
    e0 = int(np.floor(minx)) - (int(np.floor(minx)) % 2 == 0)  # ungerade
    n0 = int(np.floor(miny)) - (int(np.floor(miny)) % 2)  # gerade
    out = []
    for e in range(e0, int(np.ceil(maxx)) + 1, 2):
        for n in range(n0, int(np.ceil(maxy)) + 1, 2):
            if shapely.box(e * 1000, n * 1000, (e + 2) * 1000, (n + 2) * 1000).intersects(area):
                out.append((e, n))
    return out


def download(area):
    paths = []
    for e, n in tiles_for(area):
        p = DIR / f"LoD2_32_{e}_{n}_2_bw.zip"
        try:
            _get(URL.format(e=e, n=n), p)
            paths.append(p)
        except Exception as ex:  # leere Randkacheln gibt es nicht immer
            print(f"  LoD2 {e}_{n}: {ex}")
    return paths


def _rings(el):
    for pl in el.iterfind(".//gml:exterior//gml:posList", NS):
        a = np.array(pl.text.split(), float)
        if len(a) >= 12:
            yield a.reshape(-1, 3)


def _parse_gml(data: bytes):
    root = etree.fromstring(data)
    rows, faces, owners = [], [], []
    for b in root.iter(f"{{{NS['bldg']}}}Building", f"{{{NS['bldg']}}}BuildingPart"):
        bounded = b.findall("bldg:boundedBy", NS)
        if not bounded:
            continue
        gid = b.get(f"{{{NS['gml']}}}id")
        ground, fc = [], []
        for bb in bounded:
            for s in bb:
                kind = etree.QName(s).localname
                if kind not in SURF:
                    continue
                for r in _rings(s):
                    fc.append(r)
                    if kind == "GroundSurface":
                        ground.append(r)
        if not ground or not fc:
            continue
        gz = min(r[:, 2].min() for r in ground)
        top = max(r[:, 2].max() for r in fc)
        fp = shapely.union_all([shapely.make_valid(shapely.Polygon(r[:, :2])) for r in ground])
        mh = b.findtext("bldg:measuredHeight", namespaces=NS)
        rows.append({"lod2_id": gid, "part": etree.QName(b).localname == "BuildingPart",
                     "ground_z": gz, "height": top - gz,
                     "measured_height": float(mh) if mh else np.nan,
                     "roof_type": b.findtext("bldg:roofType", namespaces=NS),
                     "function": b.findtext("bldg:function", namespaces=NS),
                     "geometry": fp})
        idx = len(rows) - 1
        faces.extend(fc)
        owners.extend([idx] * len(fc))
    return rows, faces, owners


def _parse_zip(path):
    rows, faces, owners = [], [], []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.lower().endswith(".gml"):
                r, f, o = _parse_gml(z.read(name))
                off = len(rows)
                rows += r
                faces += f
                owners += [i + off for i in o]
    return rows, faces, owners


def load(area):
    """Gebäude (2D-Grundriss + Höhe) und 3D-Flächen; gecacht als GeoParquet."""
    bp, fpth = C.INTERIM / "lod2_buildings.parquet", C.INTERIM / "lod2_faces.parquet"
    if bp.exists() and fpth.exists():
        return gpd.read_parquet(bp), gpd.read_parquet(fpth)
    paths = download(area)
    rows, faces, owners = [], [], []
    with ProcessPoolExecutor() as ex:
        for r, f, o in ex.map(_parse_zip, paths):
            off = len(rows)
            rows += r
            faces += f
            owners += [i + off for i in o]
    b = gpd.GeoDataFrame(rows, geometry="geometry", crs=C.CRS)
    # Kachelgrenzen: Gebäude können doppelt vorkommen
    b["bid"] = np.arange(len(b))
    dup = b.duplicated("lod2_id").to_numpy()
    ring_idx = np.repeat(np.arange(len(faces)), [len(r) for r in faces])
    polys = shapely.polygons(shapely.linearrings(np.concatenate(faces), indices=ring_idx))
    f = gpd.GeoDataFrame({"bid": owners}, geometry=polys, crs=C.CRS)
    f = f[~dup[f.bid.to_numpy()]]
    b = b[~dup]
    keep = b.intersects(area.buffer(200)).to_numpy()
    b = b[keep]
    f = f[f.bid.isin(b.bid)]
    b.to_parquet(bp)
    f.to_parquet(fpth)
    return b, f


def merge_with_osm(lod2_b, osm_b):
    """OSM-Gebäude nur behalten, wo LoD2 nichts hat (Repräsentativpunkt nicht in LoD2-Grundriss)."""
    tree = shapely.STRtree(lod2_b.geometry.values)
    rp = shapely.point_on_surface(osm_b.geometry.values)
    hit = np.unique(tree.query(rp, predicate="within")[0])
    rest = osm_b.drop(osm_b.index[hit])
    lb = pd.DataFrame({"osmid": None, "kind": np.where(lod2_b.part, "lod2_part", "lod2"),
                       "btype": lod2_b["function"], "height": lod2_b.height.round(2), "min_h": 0.0,
                       "height_source": "lod2", "lod2_id": lod2_b.lod2_id, "bid": lod2_b.bid,
                       "roof_type": lod2_b.roof_type, "ground_z": lod2_b.ground_z.round(2),
                       "geometry": lod2_b.geometry.values})
    out = pd.concat([lb, rest.assign(bid=-1)], ignore_index=True)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=C.CRS), len(hit)
