import numpy as np
import shapely
import shapely.affinity
from shapely.geometry import box

from pipeline.shadows import building_shadow_pieces, shadow_vector, tree_shadow_pieces


def union(*args):
    pieces, _ = building_shadow_pieces(*args)
    return shapely.union_all(pieces)


def test_cube_45deg_south_sun():
    cube = box(0, 0, 10, 10)
    s = union([cube], [10.0], [0.0], 45.0, 180.0)
    assert abs(s.area - 200.0) < 1e-6
    minx, miny, maxx, maxy = s.bounds
    assert abs(maxy - 20.0) < 1e-9 and abs(miny) < 1e-9  # 10 m nach Norden
    assert abs(minx) < 1e-9 and abs(maxx - 10.0) < 1e-9


def test_directions():
    # morgens Sonne im Osten -> Schatten nach Westen, abends umgekehrt
    assert shadow_vector(30, 90)[0] < 0
    assert shadow_vector(30, 270)[0] > 0
    assert shadow_vector(30, 180)[1] > 0


def test_concave_and_courtyard():
    # L-Form, schräge Sonne: Vergleich mit Brute-Force-Minkowski-Summe (viele Verschiebungen)
    L = shapely.Polygon([(0, 0), (20, 0), (20, 10), (10, 10), (10, 20), (0, 20)])
    s = union([L], [10.0], [0.0], 30.0, 135.0)
    ux, uy = shadow_vector(30.0, 135.0)
    ref = shapely.union_all([shapely.affinity.translate(L, ux * z, uy * z) for z in np.linspace(0, 10, 2001)])
    assert abs(s.area - ref.area) / ref.area < 1e-3
    # Innenhof wird teilweise beschattet
    ring = box(0, 0, 30, 30).difference(box(10, 10, 20, 20))
    s = union([ring], [5.0], [0.0], 45.0, 180.0)
    assert s.intersection(box(10, 10, 20, 15)).area > 49.0


def test_floating_part():
    s = union([box(0, 0, 10, 10)], [10.0], [5.0], 45.0, 180.0)
    assert abs(s.area - 150.0) < 1e-6 and abs(s.bounds[1] - 5.0) < 1e-9


def test_tree():
    c = tree_shadow_pieces([shapely.Point(0, 0)], [6.0], [10.0], 45.0, 180.0)[0]
    assert abs(c.centroid.y - 7.0) < 1e-6


def _cube_faces(s=10.0, h=10.0):
    P = shapely.Polygon
    return [
        P([(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0)]),          # Boden
        P([(0, 0, h), (s, 0, h), (s, s, h), (0, s, h)]),          # Dach
        P([(0, 0, 0), (s, 0, 0), (s, 0, h), (0, 0, h)]),          # Südwand
        P([(0, s, 0), (s, s, 0), (s, s, h), (0, s, h)]),          # Nordwand
        P([(0, 0, 0), (0, s, 0), (0, s, h), (0, 0, h)]),          # Westwand
        P([(s, 0, 0), (s, s, 0), (s, s, h), (s, 0, h)]),          # Ostwand
    ]


def test_lod2_cube_matches_prism():
    from pipeline.shadows import face_shadow_pieces
    s = shapely.union_all(face_shadow_pieces(_cube_faces(), np.zeros(6), 45.0, 180.0))
    assert abs(s.area - 200.0) < 1e-6 and abs(s.bounds[3] - 20.0) < 1e-9


def test_lod2_gable_roof_shorter_than_prism():
    from pipeline.shadows import face_shadow_pieces
    P = shapely.Polygon
    # Satteldach, First in Ost-West-Richtung bei y=5, Traufe 6 m, First 10 m
    f = [P([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]),
         P([(0, 0, 6), (10, 0, 6), (10, 5, 10), (0, 5, 10)]),
         P([(0, 10, 6), (10, 10, 6), (10, 5, 10), (0, 5, 10)])]
    s = shapely.union_all(face_shadow_pieces(f, np.zeros(3), 45.0, 180.0))
    assert abs(s.bounds[3] - 16.0) < 1e-9  # Nordtraufe 10 + 6 m (First: 5 + 10 = 15)
