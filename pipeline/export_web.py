"""Web-Export fürs Frontend (WGS84, GeoJSON, < 100 MB je Datei für GitHub):  python -m pipeline.export_web

web/shadows/shadow_HH.geojson   Schatten je Stunde, um 0,3 m vereinfacht
web/edges_walk.geojson          Fußkanten mit shade_HH
web/edges_bike.geojson          Radkanten mit shade_HH, crit_*, has_*, atrai_*
web/buildings.geojson           Gebäude mit height, height_source
web/trees.geojson               Bäume
web/meta.json                   Stunden, Sonnenstände, Statistik, Quellen/Lizenzen
"""
import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import shapely

from . import config as C

ATTRIBUTION = ("© OpenStreetMap contributors (ODbL); 3D-Gebäudemodell LoD2: LGL, www.lgl-bw.de, dl-de/by-2.0; "
               "Baumkataster: Stadt Heilbronn, dl-de/by-2.0; Radsensordaten: ATRAI (data.atrai.bike)")


def _write(gdf, path, precision=6):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    pyogrio.write_dataframe(gdf.to_crs(4326), path, driver="GeoJSON",
                            layer_options={"COORDINATE_PRECISION": precision, "RFC7946": "YES"})
    mb = path.stat().st_size / 1e6
    print(f"  {path.relative_to(path.parents[1])}: {mb:.1f} MB")
    if mb > 95:
        raise SystemExit(f"{path} ist zu groß für GitHub ({mb:.0f} MB)")


def main(out=C.OUT, web=C.ROOT / "web"):
    out, web = Path(out), Path(web)
    for h in C.HOURS:
        s = gpd.read_file(out / "shadows.gpkg", layer=f"shadow_{h:02d}")
        s["geometry"] = shapely.make_valid(shapely.simplify(s.geometry.values, 0.3))
        _write(s, web / "shadows" / f"shadow_{h:02d}.geojson")
    for net, f in (("walk", "edges_shade.gpkg"), ("bike", "edges_bike.gpkg")):
        if (out / f).exists():
            e = gpd.read_file(out / f)
            e["length"] = e["length"].round(1)
            _write(e, web / f"edges_{net}.geojson")
    b = gpd.read_file(out / "buildings_heights.gpkg")
    b = b[["height", "height_source", "geometry"]].assign(height=lambda d: d.height.round(1))
    b["geometry"] = shapely.simplify(b.geometry.values, 0.2)
    _write(b, web / "buildings.geojson")
    t = gpd.read_file(out / "trees.gpkg")[["source", "crown_d", "height", "geometry"]].round(1)
    _write(t, web / "trees.geojson")
    meta = {
        "reference_date": C.REF_DATE, "hours": C.HOURS, "timezone": C.TZ,
        "sun": pd.read_csv(out / "sun_positions.csv").round(2).to_dict("records"),
        "stats": pd.read_csv(out / "stats.csv").to_dict("records"),
        "shade_semantics": "shade_HH = share of the edge in shadow at HH:00 (0 = full sun, 1 = full shade)",
        "crit_semantics": "crit_* in 0..1, 1 = bad; edges without measurement carry the median (has_* = false)",
        "attribution": ATTRIBUTION,
    }
    (web / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print("  web/meta.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(C.OUT))
    main(ap.parse_args().out)
