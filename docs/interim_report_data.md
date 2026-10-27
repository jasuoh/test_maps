# Interim report: data sources for shade routing in Heilbronn

Status 27 Oct 2026 · Green City Hackathon Heilbronn · data pipeline (Phase 1)

## TL;DR

- **OSM building heights are poor in Heilbronn.** Only 21 % of the 44,278 OSM buildings carry `height` or `building:levels`. Without other data, 79 % of the buildings (75 % of the footprint area) would get a guessed height.
- **Solution: the LGL Baden-Württemberg LoD2 3D building model** (open data, dl-de/by-2.0). It has measured roof and wall geometry for 60,296 building bodies in the city. It now replaces OSM for buildings, and OSM only fills gaps.
- **Trees:** Baumkataster Heilbronn (43,031 trees, with crown diameter but no height), plus 950 extra trees from OSM.
- **Where data is still missing:** tree height (estimated) and private, park and forest trees. A normalised surface model (nDOM, Phase 2) would cover both.

## Source availability

| Source | Status | What we use |
|---|---|---|
| Overpass API (main server and 3 mirrors) | ❌ overloaded (502/504) during testing | Geofabrik extract Regierungsbezirk Stuttgart (212 MB PBF), clipped locally with pyosmium |
| Nominatim | ✅ | city boundary (OSM relation 62751, 99.8 km²) |
| opendata.heilbronn.de | ✅ | Baumkataster, status 1 Jan 2026, EPSG:25832 |
| opengeodata.lgl-bw.de, LoD2 | ✅ | 2 × 2 km CityGML tiles, `…/data/lod2/LoD2_32_<E>_<N>_2_bw.zip` (E odd, N even, in km) |
| opengeodata.lgl-bw.de, DOM1/DGM1 | ✅ reachable | Phase 2 only |

`python -m pipeline.download` fetches OSM and the tree register. The LoD2 tiles are downloaded automatically on the first run.

## Buildings

### OSM tag coverage (44,278 `building=*`)

| Tag | Count | Share |
|---|---:|---:|
| `height` | 79 | 0.2 % |
| `building:levels` | 9,294 | 21.0 % |
| `height` or `building:levels` | 9,322 | 21.1 % |
| `roof:levels` | 8,875 | 20.0 % |
| `roof:height` | 9 | 0.0 % |
| `min_height` | 1 | 0.0 % |

- About 45 % of all buildings are plain `building=yes` with no type, so they get the 8 m default.
- Within 1 km of the Marktplatz, 45 % have levels. That is better than the city average but still less than half.
- Only 34 % of buildings larger than 200 m² have a real height, and those are the ones that cast the shadows that matter.

### How accurate the OSM heights are (compared with LoD2, 38,700 matched buildings)

| OSM height source | Median error (OSM − LoD2) | Share off by > 5 m |
|---|---:|---:|
| `height` tag | −0.2 m | 20 % |
| `building:levels` × 3 m + 1.5 m | **−3.1 m** (too low) | 19 % |
| type default | −0.2 m | 11 %, worst case −118 m (towers, chimneys) |

The levels rule underestimates heights because LoD2 heights go up to the ridge. The defaults are roughly right on average but miss every tall building.

### LGL LoD2

- **60,296 building bodies** (buildings and building parts) with **680,933 3D faces** (walls, roofs, ground).
- Height = highest roof point minus lowest ground point. It matches the LGL `measuredHeight` to the centimetre (median difference 0.00 m).
- Roof types (ALKIS codes): flat 29 %, gable 25 %, mixed 20 %, mono-pitch 19 %, other 7 %.
- Model status: ALKIS footprints April 2025, data exported Feb 2026.
- **Replaces 39,024 OSM buildings.** 5,620 OSM buildings have no LoD2 counterpart. They are mostly small (median 15.5 m²: sheds, allotment huts, garages) and are kept with the OSM height rule.

**Shadow model with LoD2:** we don't extrude a prism. We project every 3D face along the sun rays onto the building's ground level and union the results. A gable roof then casts a correct, shorter shadow at the eaves than a box at ridge height would.

## Trees

| Source | Count | Height | Crown |
|---|---:|---|---|
| Baumkataster 2026 | 43,031 | ❌ none | `KRONE_DM` (median 5 m) |
| OSM `natural=tree` | 2,006 | 6 tagged | 2 tagged |
| OSM `natural=tree_row` | 42 rows | – | – |

Attributes in the tree register: `BAUM_NR, ORT, STADTTEIL, STRASSE, TYP, DEU_TEXT, WIS_TEXT, ST_UMFANG (trunk girth, m), KRONE_DM (crown diameter, m)`.

**How the tree sources are merged:**
1. The tree register has priority.
   - 8,641 trees have `KRONE_DM` = 2 m, which the register's readme describes as a placeholder for trees not maintained by the city. Another 2,113 have 0 or no value.
   - For these trees the crown is estimated from the trunk: crown = 20 × DBH, with DBH = girth / π, limited to 2–15 m. The larger of the two values is used.
2. OSM trees are added only if no register tree lies within 3 m. That dropped 1,603 duplicates and **added 950 trees**. Tree rows are split into one tree every 8 m.
3. Height: H = clip(1.4 × crown + 2, 3, 30) m. The crown centre is at 0.7 × H.
4. Shadow: a circle with the crown radius, shifted away from the sun by crown-centre height / tan(sun elevation).

**Gaps:** private gardens, parks and forest are only partly covered by either source. LoD2 contains no vegetation.

## Recommendation

1. **Use LoD2 for buildings and the tree register plus OSM for trees.** This is now the pipeline default (`--buildings lod2`). An OSM-only run (`--buildings osm`) is kept for comparison.
2. **Phase 2 (nDOM = DOM1 − DGM1):** the main gain is now on the vegetation side, not buildings. It would give real tree heights and the missing private and park trees, plus terrain on the hillsides (Wartberg).
3. **Pitch angle:** OSM has heights for only 21 % of Heilbronn's buildings, while open state data (LoD2) closes that gap completely. That is a good argument for open data.
