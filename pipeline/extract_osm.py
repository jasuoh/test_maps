"""Schritt 1: Aus dem PBF zwei kleine .osm-Dateien für OSMnx schneiden.

walk.osm      – nur Wege, die den OSMnx-Filter network_type="walk" erfüllen
features.osm  – Gebäude, building:part, natural=tree / tree_row (+ Multipolygon-Relationen)

Gleiche Wegfilter-Logik wie osmnx._overpass._get_network_filter("walk").
"""
import re

import osmium

from . import config as C

WALK_EXCL = re.compile(
    "abandoned|bus_guideway|construction|cycleway|motor|no|planned|platform|"
    "proposed|raceway|razed|rest_area|services"
)


def is_walk(tags):
    hw = tags.get("highway")
    if hw is None or WALK_EXCL.search(hw):
        return False
    if "yes" in tags.get("area", ""):
        return False
    if "private" in tags.get("access", "") or "private" in tags.get("service", ""):
        return False
    if "no" in tags.get("foot", ""):
        return False
    for k in ("sidewalk", "sidewalk:both", "sidewalk:left", "sidewalk:right"):
        if "separate" in tags.get(k, ""):
            return False
    return True


def is_feature_way(tags):
    return "building" in tags or "building:part" in tags or tags.get("natural") == "tree_row"


def extract(bbox, walk_out, feat_out):
    """bbox = (minlon, minlat, maxlon, maxlat)."""
    x0, y0, x1, y1 = bbox

    def inside(lon, lat):
        return x0 <= lon <= x1 and y0 <= lat <= y1

    # Pass 1: Multipolygon-Relationen von Gebäuden -> benötigte Member-Wege
    rel_ways = set()
    for r in osmium.FileProcessor(C.PBF_PATH, osmium.osm.RELATION):
        t = r.tags
        if t.get("type") == "multipolygon" and ("building" in t or "building:part" in t):
            rel_ways.update(m.ref for m in r.members if m.type == "w")

    # Pass 2: Wege mit Koordinaten prüfen
    walk_ways, walk_nodes, feat_ways, feat_nodes = set(), set(), set(), set()
    fp = osmium.FileProcessor(C.PBF_PATH, osmium.osm.NODE | osmium.osm.WAY).with_locations()
    for o in fp:
        if not o.is_way():
            continue
        t = o.tags
        walk = is_walk(t)
        feat = is_feature_way(t) or o.id in rel_ways
        if not (walk or feat):
            continue
        try:
            if not any(inside(n.lon, n.lat) for n in o.nodes):
                continue
        except osmium.InvalidLocationError:
            continue
        ids = [n.ref for n in o.nodes]
        if walk:
            walk_ways.add(o.id)
            walk_nodes.update(ids)
        if feat:
            feat_ways.add(o.id)
            feat_nodes.update(ids)

    # Pass 3: schreiben (PBF ist sortiert: Knoten, Wege, Relationen)
    for p in (walk_out, feat_out):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.unlink(missing_ok=True)
    ww = osmium.SimpleWriter(str(walk_out))
    fw = osmium.SimpleWriter(str(feat_out))
    n_rel = 0
    for o in osmium.FileProcessor(C.PBF_PATH):
        if o.is_node():
            if o.id in walk_nodes:
                ww.add_node(o)
            if o.id in feat_nodes or (o.tags.get("natural") == "tree" and inside(o.lon, o.lat)):
                fw.add_node(o)
        elif o.is_way():
            if o.id in walk_ways:
                ww.add_way(o)
            if o.id in feat_ways:
                fw.add_way(o)
        elif o.is_relation():
            t = o.tags
            if (t.get("type") == "multipolygon" and ("building" in t or "building:part" in t)
                    and any(m.type == "w" and m.ref in feat_ways for m in o.members)):
                fw.add_relation(o)
                n_rel += 1
    ww.close()
    fw.close()
    print(f"  walk: {len(walk_ways)} Wege | features: {len(feat_ways)} Wege, {n_rel} Relationen")


BIKE_EXCL = re.compile(
    "abandoned|bus_guideway|construction|corridor|elevator|escalator|footway|motor|no|planned|"
    "platform|proposed|raceway|razed|rest_area|services|steps"
)


def is_bike(tags):
    """Wie osmnx network_type="bike"."""
    hw = tags.get("highway")
    if hw is None or BIKE_EXCL.search(hw):
        return False
    if "yes" in tags.get("area", ""):
        return False
    if "private" in tags.get("access", "") or "private" in tags.get("service", ""):
        return False
    return "no" not in tags.get("bicycle", "")


def extract_network(bbox, out, pred):
    """Nur Wege eines Netzfilters (z. B. is_bike) samt Knoten in eine .osm-Datei schreiben."""
    x0, y0, x1, y1 = bbox
    ways, nodes = set(), set()
    fp = osmium.FileProcessor(C.PBF_PATH, osmium.osm.NODE | osmium.osm.WAY).with_locations()
    for o in fp:
        if not o.is_way() or not pred(o.tags):
            continue
        try:
            if not any(x0 <= n.lon <= x1 and y0 <= n.lat <= y1 for n in o.nodes):
                continue
        except osmium.InvalidLocationError:
            continue
        ways.add(o.id)
        nodes.update(n.ref for n in o.nodes)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    w = osmium.SimpleWriter(str(out))
    for o in osmium.FileProcessor(C.PBF_PATH, osmium.osm.NODE | osmium.osm.WAY):
        if o.is_node() and o.id in nodes:
            w.add_node(o)
        elif o.is_way() and o.id in ways:
            w.add_way(o)
    w.close()
    print(f"  {out.name}: {len(ways)} Wege")
