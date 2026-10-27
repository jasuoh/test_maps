"""Zentrale Konfiguration der Schatten-Pipeline (alle Annahmen an einem Ort)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
OUT = ROOT / "output"

CRS = "EPSG:25832"
TZ = "Europe/Berlin"

# Untersuchungsgebiet: Stadtkreis Heilbronn (OSM-Relation 62751, admin_level 6)
BOUNDARY_OSM_ID = "R62751"
# Fallback-Modus: nur Radius um den Marktplatz (None = ganze Stadt)
MARKTPLATZ_LONLAT = (9.2186, 49.1427)
HBF_LONLAT = (9.2067, 49.1428)

# Quellen
GEOFABRIK_PBF = "https://download.geofabrik.de/europe/germany/baden-wuerttemberg/stuttgart-regbez-latest.osm.pbf"
BAUMKATASTER_ZIP = "https://opendata.heilbronn.de/sites/default/files/SHAPE_BKA_HN20260101_EPSG25832.zip"
PBF_PATH = RAW / "osm" / "stuttgart-regbez-latest.osm.pbf"
BKA_DIR = RAW / "baumkataster"
BKA_SHP = BKA_DIR / "SHN_Baumkataster_open_UTM32N_EPSG25832.shp"

# Sonnenstand
REF_DATE = "2026-07-15"
HOURS = list(range(8, 21))  # 08..20 Uhr Ortszeit (MESZ)
MIN_SUN_ELEV = 3.0  # Grad; darunter gilt alles als Schatten

# Gebäudehöhen
LEVEL_HEIGHT = 3.0
DEFAULT_ROOF = 1.5
DEFAULT_HEIGHT_BY_TYPE = {
    "garage": 3.0, "garages": 3.0,
    "house": 7.0, "detached": 7.0, "semidetached_house": 7.0,
    "residential": 12.0, "apartments": 12.0,
    "commercial": 10.0, "retail": 10.0,
}
DEFAULT_HEIGHT = 8.0

# Bäume
TREE_DEDUP_DIST = 3.0  # m; OSM-Baum nur, wenn kein Katasterbaum näher liegt
OSM_TREE_DEFAULT_CROWN = 6.0  # m Kronendurchmesser, falls OSM nichts angibt
TREE_ROW_SPACING = 8.0  # m; Baumreihen werden in Einzelbäume zerlegt
KATASTER_STD_CROWN = 2.0  # "Standardkronendurchmesser" fremder Bäume (siehe readme)

# Kanten
SAMPLE_STEP = 2.0  # m
STREET_DEFAULT_OFFSET = 5.0  # m, falls width fehlt
FOOT_HIGHWAYS = {"footway", "path", "pedestrian", "steps"}
BIKE_CENTER_HIGHWAYS = {"cycleway", "path", "track", "pedestrian", "footway", "bridleway"}
BIKE_DEFAULT_OFFSET = 3.0  # m rechts der Mittellinie, falls width fehlt
NETWORKS = ("walk", "bike")

# Routing-Demo
DEMO_HOUR = 15
SHADE_FACTOR = 2.0
MAX_DETOUR = 0.25
