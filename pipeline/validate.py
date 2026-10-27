"""Plausibilitätsprüfungen nach dem Lauf:  python -m pipeline.validate [--out output]

1. Schattenrichtung: für 300 zufällige LoD2-Gebäude Schwerpunkt(Schatten) − Schwerpunkt(Grundriss)
   -> morgens West, mittags Nord, abends Ost.
2. Mittlerer Schattenanteil aller Kanten ist um die Mittagszeit minimal.
"""
import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from . import config as C
from .shadows import face_shadow_pieces, sun_positions


def compass(dx, dy):
    a = (np.degrees(np.arctan2(dx, dy)) + 360) % 360
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((a + 22.5) // 45) % 8], a


def main(out=C.OUT):
    out = Path(out)
    ok = True
    lb = gpd.read_parquet(C.INTERIM / "lod2_buildings.parquet")
    faces = gpd.read_parquet(C.INTERIM / "lod2_faces.parquet")
    sample = lb[lb.height > 5].sample(300, random_state=1)
    f = faces[faces.bid.isin(sample.bid)].merge(sample[["bid", "ground_z"]], on="bid")
    sun = sun_positions()
    print("1) Schattenrichtung (Schwerpunkt Schatten − Grundriss, 300 LoD2-Gebäude)")
    expect = {8: "W", 13: "N", 18: "E"}
    for h, exp in expect.items():
        r = sun[sun.hour == h].iloc[0]
        d = []
        for (bid, g), fb in zip(sample[["bid", "geometry"]].itertuples(index=False),
                                (f[f.bid == b] for b in sample.bid)):
            s = shapely.union_all(face_shadow_pieces(fb.geometry.values, fb.ground_z.values,
                                                     r.elevation, r.azimuth))
            if not s.is_empty:
                d.append(np.array(s.centroid.coords[0]) - np.array(g.centroid.coords[0]))
        dx, dy = np.mean(d, axis=0)
        name, ang = compass(dx, dy)
        good = exp in name
        ok &= good
        print(f"   {h:02d} Uhr: Sonne Azimut {r.azimuth:5.1f}° -> Schatten nach {name} ({ang:5.1f}°)"
              f"  erwartet {exp}: {'OK' if good else 'FEHLER'}")
    st = pd.read_csv(out / "stats.csv")
    hmin = int(st.loc[st.mean_shade.idxmin(), "hour"])
    good = 12 <= hmin <= 14
    ok &= good
    print(f"2) Minimum des mittleren Schattenanteils um {hmin} Uhr "
          f"({st.mean_shade.min():.3f}; Sonnenhöchststand ~13:30 MESZ): {'OK' if good else 'FEHLER'}")
    print(st[["hour", "elevation", "azimuth", "mean_shade", "mean_shade_length_weighted"]].to_string(index=False))
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(C.OUT))
    raise SystemExit(0 if main(ap.parse_args().out) else 1)
