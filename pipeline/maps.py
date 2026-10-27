"""Kontrollkarten rund um Marktplatz/Kiliansplatz:  python -m pipeline.maps [--out output] [--hours 10 14 18]"""
import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from . import config as C  # noqa: E402

# Sequenzielle Blau-Rampe (hell = sonnig, dunkel = schattig)
SHADE_CMAP = LinearSegmentedColormap.from_list(
    "shade", ["#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"])
INK, MUTED, SHADOW, BUILDING, TREE = "#2b2b2b", "#6b6b6b", "#c9c7c1", "#8f8d87", "#3f8f4f"


def center_box(half=350):
    # Mitte zwischen Marktplatz und Kiliansplatz
    p = gpd.GeoSeries(gpd.points_from_xy([C.MARKTPLATZ_LONLAT[0] + 0.0006], [C.MARKTPLATZ_LONLAT[1]]),
                      crs=4326).to_crs(C.CRS).iloc[0]
    return p.buffer(half, cap_style="square")


def main(out=C.OUT, hours=(10, 14, 18)):
    out = Path(out)
    box = center_box()
    bld = gpd.read_file(out / "buildings_heights.gpkg", bbox=box.bounds)
    ed = gpd.read_file(out / "edges_shade.gpkg", bbox=box.bounds)
    tr = gpd.read_file(out / "trees.gpkg", bbox=box.bounds)
    sun = gpd.pd.read_csv(out / "sun_positions.csv").set_index("hour")
    (out / "maps").mkdir(exist_ok=True)
    for h in hours:
        sh = gpd.read_file(out / "shadows.gpkg", layer=f"shadow_{h:02d}", bbox=box.bounds).clip(box)
        fig, ax = plt.subplots(figsize=(8, 8.6), dpi=150)
        sh.plot(ax=ax, color=SHADOW, linewidth=0)
        bld.clip(box).plot(ax=ax, color=BUILDING, linewidth=0)
        tr.clip(box).plot(ax=ax, color=TREE, markersize=4, alpha=0.8)
        e = ed.clip(box)
        e.plot(ax=ax, column=f"shade_{h:02d}", cmap=SHADE_CMAP, vmin=0, vmax=1, linewidth=2.2)
        ax.set_xlim(box.bounds[0], box.bounds[2])
        ax.set_ylim(box.bounds[1], box.bounds[3])
        ax.set_axis_off()
        r = sun.loc[h]
        ax.set_title(f"Shade at {h:02d}:00, 15 July  ·  sun {r.elevation:.0f}° high, azimuth {r.azimuth:.0f}°",
                     loc="left", color=INK, fontsize=11)
        sm = plt.cm.ScalarMappable(cmap=SHADE_CMAP, norm=plt.Normalize(0, 1))
        cb = fig.colorbar(sm, ax=ax, orientation="horizontal", fraction=0.035, pad=0.02)
        cb.set_label("Edge shade share (0 = full sun, 1 = full shade)", color=MUTED, fontsize=9)
        cb.outline.set_visible(False)
        cb.ax.tick_params(colors=MUTED, labelsize=8)
        ax.text(0.0, -0.005, "Grey fill = shadow · dark grey = buildings · green = trees · 700 × 700 m, north up",
                transform=ax.transAxes, va="top", fontsize=8, color=MUTED)
        fig.savefig(out / "maps" / f"shade_{h:02d}.png", bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"  {out / 'maps' / f'shade_{h:02d}.png'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(C.OUT))
    ap.add_argument("--hours", type=int, nargs="+", default=[10, 14, 18])
    a = ap.parse_args()
    main(a.out, a.hours)
