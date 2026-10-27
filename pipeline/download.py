"""Schritt 0: Rohdaten herunterladen (eigenständig ausführbar: python -m pipeline.download).

- OSM: Geofabrik-Extrakt Regierungsbezirk Stuttgart (~210 MB). Overpass war beim Test
  überlastet (502/504); der PBF-Weg ist reproduzierbar und offline wiederholbar.
- Baumkataster Heilbronn, Stand 01.01.2026, EPSG:25832 (dl-de/by-2.0).
- Stadtgrenze über Nominatim (OSM-Relation 62751).
"""
import urllib.request
import zipfile

from . import config as C

UA = {"User-Agent": "GreenCityHackathon-Heilbronn/0.1"}


def _get(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  vorhanden: {dest.name}")
        return
    print(f"  lade {url}")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


def boundary():
    """Stadtgrenze als GeoDataFrame in EPSG:25832 (gecacht)."""
    import geopandas as gpd
    import osmnx as ox

    path = C.INTERIM / "boundary.gpkg"
    if path.exists():
        return gpd.read_file(path)
    ox.settings.useragent = UA["User-Agent"]
    g = ox.geocode_to_gdf(C.BOUNDARY_OSM_ID, by_osmid=True)[["geometry"]].to_crs(C.CRS)
    path.parent.mkdir(parents=True, exist_ok=True)
    g.to_file(path)
    return g


def main():
    _get(C.GEOFABRIK_PBF, C.PBF_PATH)
    zpath = C.BKA_DIR / "bka2026.zip"
    _get(C.BAUMKATASTER_ZIP, zpath)
    if not C.BKA_SHP.exists():
        zipfile.ZipFile(zpath).extractall(C.BKA_DIR)
    b = boundary()
    print(f"  Stadtgrenze: {b.area.iloc[0] / 1e6:.1f} km²")


if __name__ == "__main__":
    main()
