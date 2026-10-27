"""Schattengeometrie (Vektor, ebener Grund).

Gebäude als Prisma von min_h bis h: Schatten = Minkowski-Summe des Grundrisses mit dem
Segment [d(min_h), d(h)], d(z) = z / tan(Sonnenhöhe) entgegen dem Azimut. Umgesetzt wie
gefordert als Vereinigung aus (verschobenem) Grundriss, verschobener Kopie und den
konvexen Hüllen jeder Ringkante mit ihrer verschobenen Kopie (= Parallelogramme).
Innenhöfe (Innenringe) werden mitgeführt, dadurch ist das Ergebnis exakt.
"""
import numpy as np
import pandas as pd
import pvlib
import shapely

from . import config as C


def sun_positions(date=C.REF_DATE, hours=C.HOURS, lonlat=C.MARKTPLATZ_LONLAT):
    times = pd.DatetimeIndex([pd.Timestamp(f"{date} {h:02d}:00", tz=C.TZ) for h in hours])
    sp = pvlib.solarposition.get_solarposition(times, lonlat[1], lonlat[0])
    return pd.DataFrame({"hour": hours, "elevation": sp["apparent_elevation"].to_numpy(),
                         "azimuth": sp["azimuth"].to_numpy()})


def shadow_vector(elev_deg, azim_deg):
    """Verschiebung pro Meter Höhe (dx, dy) – zeigt von der Sonne weg."""
    k = 1.0 / np.tan(np.radians(elev_deg))
    a = np.radians(azim_deg)
    return -np.sin(a) * k, -np.cos(a) * k


def building_shadow_pieces(geoms, h, min_h, elev, azim):
    """Alle Einzelteile (Polygone) der Gebäudeschatten; Vereinigung = Schatten.

    geoms: Array von (Multi)Polygonen, h/min_h: Arrays in m.
    Rückgabe: (pieces, owner) – owner = Index des Gebäudes je Teil.
    """
    ux, uy = shadow_vector(elev, azim)
    geoms = np.asarray(geoms)
    h = np.asarray(h, float)
    min_h = np.asarray(min_h, float)

    # Ringe mit zugehörigem Gebäude
    parts, part_idx = shapely.get_parts(geoms, return_index=True)
    rings, ring_idx = shapely.get_rings(parts, return_index=True)
    owner_ring = part_idx[ring_idx]
    xy, ci = shapely.get_coordinates(rings, return_index=True)
    # Kanten: aufeinanderfolgende Punkte desselben Rings
    same = ci[:-1] == ci[1:]
    p1, p2 = xy[:-1][same], xy[1:][same]
    own = owner_ring[ci[:-1][same]]
    d0 = np.c_[ux * min_h[own], uy * min_h[own]]
    d1 = np.c_[ux * h[own], uy * h[own]]
    a, b, c, d = p1 + d0, p2 + d0, p2 + d1, p1 + d1
    cross = np.abs((b[:, 0] - a[:, 0]) * (d[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (d[:, 0] - a[:, 0]))
    ok = cross > 1e-6
    quads = shapely.polygons(np.stack([a, b, c, d, a], axis=1)[ok])

    hi = _translate(geoms, ux * h, uy * h)
    lo = _translate(geoms, ux * min_h, uy * min_h)
    pieces = np.concatenate([lo, hi, quads])
    owner = np.concatenate([np.arange(len(geoms)), np.arange(len(geoms)), own[ok]])
    return pieces, owner


def _translate(geoms, dx, dy):
    """Vektorisierte Verschiebung mit individuellem (dx, dy) je Geometrie."""
    _, idx = shapely.get_coordinates(geoms, return_index=True)
    off = np.c_[np.broadcast_to(dx, len(geoms))[idx], np.broadcast_to(dy, len(geoms))[idx]]
    return shapely.transform(geoms, lambda c: c + off)


def tree_shadow_pieces(points, crown_d, height, elev, azim):
    """Krone als Kreis (Radius KD/2), verschoben um Kronenmittelhöhe (0,7·H) / tan(Höhe)."""
    ux, uy = shadow_vector(elev, azim)
    hc = 0.7 * np.asarray(height, float)
    centers = _translate(np.asarray(points), ux * hc, uy * hc)
    return shapely.buffer(centers, np.asarray(crown_d, float) / 2.0, quad_segs=4)


def face_shadow_pieces(faces3d, ground_z, elev, azim):
    """LoD2: jede 3D-Fläche entlang der Sonnenstrahlen auf z = ground_z ihres Gebäudes projizieren.

    Der Schatten eines geschlossenen Körpers ist die Vereinigung dieser Projektionen. Dächer
    werfen so ihre echte Form (Satteldach -> kürzerer Schatten an der Traufe als am First).
    """
    ux, uy = shadow_vector(elev, azim)
    faces3d = np.asarray(faces3d)
    _, idx = shapely.get_coordinates(faces3d, include_z=True, return_index=True)
    gz = np.asarray(ground_z, float)[idx]

    def proj(c):
        dz = np.clip(c[:, 2] - gz, 0, None)
        return np.c_[c[:, 0] + ux * dz, c[:, 1] + uy * dz, np.zeros(len(c))]

    p = shapely.force_2d(shapely.transform(faces3d, proj, include_z=True))
    p = p[shapely.area(p) > 1e-4]  # sonnenparallele Flächen fallen zu Linien zusammen
    bad = ~shapely.is_valid(p)
    if bad.any():
        p[bad] = shapely.make_valid(p[bad])
    return p
