"""Fußwegnetz laden und Abtastpunkte je Kante erzeugen."""
import geopandas as gpd
import numpy as np
import osmnx as ox
import shapely

from . import config as C
from .heights import num


def load_graph(boundary_4326, network="walk"):
    """walk: ungerichtet nutzbar (bidirectional); bike: Einbahnstraßen werden respektiert."""
    G = ox.graph_from_xml(C.INTERIM / f"{network}.osm", bidirectional=(network == "walk"), retain_all=True)
    G = ox.truncate.truncate_graph_polygon(G, boundary_4326, truncate_by_edge=True)
    G = ox.truncate.largest_component(G, strongly=False)
    return ox.project_graph(G, to_crs=C.CRS)


def _first(v):
    return v[0] if isinstance(v, list) else v


def sample_lines(edges: gpd.GeoDataFrame, mode="walk"):
    """Abtastlinien je Kante.

    walk: Mitte und – bei Straßen – links/rechts versetzt (Maximum: man wählt die schattige Seite).
    bike: Wege ohne Autoverkehr mittig; Straßen nur rechts in Fahrtrichtung, Versatz
          max(width/2 − 1 m, 1,5 m), sonst 3 m (dort fährt man; Seitenwahl gibt es nicht).

    Rückgabe: Punkte, line_id je Punkt, edge_row je Linie (Kantenindex 0..n-1).
    """
    geoms = edges.geometry.to_numpy()
    hw = edges["highway"].map(_first).astype(str).to_numpy()
    width = edges["width"].map(lambda v: num(_first(v))) if "width" in edges else np.full(len(edges), np.nan)
    width = np.asarray(width, float)
    if mode == "bike":
        street = ~np.isin(hw, list(C.BIKE_CENTER_HIGHWAYS))
        off = np.where(width > 0, np.maximum(width / 2 - 1.0, 1.5), C.BIKE_DEFAULT_OFFSET)
        signs = (-1,)  # negativer Versatz = rechts der Linienrichtung (u -> v)
    else:
        street = ~np.isin(hw, list(C.FOOT_HIGHWAYS))
        off = np.where(width > 0, width / 2, C.STREET_DEFAULT_OFFSET)
        signs = (1, -1)

    si = np.flatnonzero(street)
    keep = np.ones(len(geoms), bool)
    if mode == "bike":
        keep[si] = False  # Straßen: nur die rechte Linie zählt
    lines, edge_row = [geoms[keep]], [np.flatnonzero(keep)]
    for sign in signs:
        oc = shapely.offset_curve(geoms[si], sign * off[si], quad_segs=2, join_style="mitre", mitre_limit=2)
        ok = (shapely.get_type_id(oc) == 1) & (shapely.length(oc) > 0)  # nur saubere LineStrings
        lines.append(oc[ok])
        edge_row.append(si[ok])
        if mode == "bike" and (~ok).any():  # Fallback: Mittellinie
            lines.append(geoms[si[~ok]])
            edge_row.append(si[~ok])
    lines = np.concatenate(lines)
    edge_row = np.concatenate(edge_row)

    length = shapely.length(lines)
    n = np.maximum(np.ceil(length / C.SAMPLE_STEP).astype(int), 1) + 1
    line_id = np.repeat(np.arange(len(lines)), n)
    start = np.repeat(np.cumsum(n) - n, n)
    frac = (np.arange(n.sum()) - start) / np.repeat(n - 1, n)
    pts = shapely.line_interpolate_point(lines[line_id], frac, normalized=True)
    return pts, line_id, edge_row


def edge_shade(shaded, line_id, edge_row, n_edges):
    """Anteil beschatteter Punkte je Linie, dann Maximum über Mitte/links/rechts je Kante."""
    n_lines = len(edge_row)
    cnt = np.bincount(line_id, minlength=n_lines)
    hit = np.bincount(line_id, weights=shaded.astype(float), minlength=n_lines)
    frac = hit / np.maximum(cnt, 1)
    out = np.zeros(n_edges)
    np.maximum.at(out, edge_row, frac)
    return out
