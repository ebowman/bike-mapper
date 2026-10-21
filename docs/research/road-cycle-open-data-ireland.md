# Open road and cycle data for Ireland beyond OSM (Overture vs OSM for Dublin, NTA/DCC/DLR/SDCC layers, TII, Tailte, MapRoad, Mapillary)

## Question

The planner routes on OSM through BRouter and draws cycle infrastructure from OSM tags
(`scripts/build_cycle_overlay.py`: `highway=cycleway`, and `cycleway*=lane|track|...` on roads).
Does any other open source add (a) cycle-lane/track coverage, (b) surface quality, or (c) road/traffic
class for Dublin and Wicklow, under a licence that an ODbL-derived planner can use? In particular, does
Overture Maps (Linux Foundation; TomTom, Meta, Amazon, Microsoft) carry better cycle-lane data than OSM
for Dublin? Checked hands-on on 2026-10-21; bbox for all Dublin counts is `-6.45,53.25,-6.05,53.45`.

## Sources evaluated

| name | URL | license | access method | coverage | resolution/granularity | cost |
|------|-----|---------|---------------|----------|------------------------|------|
| Overture Maps transportation theme, `segment` type, release 2026-10-21.0 | https://docs.overturemaps.org/guides/transportation/ ; CLI `uvx overturemaps download` reads the public S3/Azure parquet | **ODbL** for the transportation theme (https://docs.overturemaps.org/attribution/: sources OpenStreetMap + TomTom; CDLA-Permissive-2.0 applies only to Places/Microsoft/Meta) | CLI, 37 s, no account; 160 MB GeoJSON for the bbox | 148,638 segments in the Dublin bbox | per segment: `class`, `subclass`, `road_surface`, `speed_limits`, `access_restrictions`, `road_flags`, `width_rules`, `routes`; **no `lanes` property in the current schema and none in the data** | free |
| OSM (Geofabrik `ireland-and-northern-ireland`, replication 2026-10-19T20:21:11Z) | https://download.geofabrik.de/europe/ireland-and-northern-ireland.html | ODbL | `data/osm/ireland.osm.pbf` (416 MB), pyosmium | same bbox: 97,739 road ways / 6,929 km | full tag set (`cycleway*`, `surface`, `smoothness`, `lanes`, `maxspeed`, `lit`, `width`) | free |
| NTA **Dublin Metropolitan Area Cycle Infrastructure 2025** (`nta-protected-cycle-infrastructure-2025` on Smart Dublin = `nta-active-travel-cycle-network-dublin` on data.gov.ie) | https://data.smartdublin.ie/dataset/nta-protected-cycle-infrastructure-2025 | CC-BY 4.0 | GeoJSON 2.36 MB (also CSV, KMZ, SHP) | Dublin Metropolitan Area, "as of February 2025", modified 2025-09-17; 4,410 features, 975.7 km **per side** | fields `BIKE` (BIKE_LANE, SEPARATE_TRAIL, BIKE_FRIENDLY_PEDESTRIAN_PATH, NON_TRAFFIC_TRAIL, SHARED_ROAD) and `DIR` (Forward/Bi-Directional/Reverse) only; no width, surface, name or road ref | free |
| NTA Existing Protected Cycle Infrastructure 2023 | https://data.smartdublin.ie/dataset/dublin-metropolitan-area-existing-protected-cycle-infrastructure | CC-BY 4.0 | GeoJSON 1.6 MB | 1,944 features / 467.7 km, protected only (painted lanes and bus lanes removed) | `cdo` (SegregatedCycleLane...), `twoway`, `bollardpro` | free |
| NTA Greater Dublin Area Cycle Infrastructure 2021 ("BikeLife", Compass/Jacobs for NTA) | https://data.smartdublin.ie/dataset/greater-dublin-area-cycle-infrastructure-nta | CC-BY 4.0 | shapefile in 1.8 MB zip (ITM), also CSV/KML/WMS | GDA; 5,636 polylines / 665 km | `classifica` (cyclelane 2,221, surfacechange 924, buslane 567, trafficfree 519, shareduse 378, segregatedcyclelane 250...), `width`, `mandatory`, `bollardpro`, `buslane`, `oneside`/`twoway`, `datasource` (4,880 of 5,636 re-categorised from the 2013 survey) | free |
| NTA GDA Cycle Network Survey 2013 (`cycle-network-survey`) | https://data.smartdublin.ie/dataset/cycle-network-survey | CC-BY 4.0 | `cycnet.zip` 5.0 MB, 9 shapefiles | GDA, surveyed 2011-2012; `CycleNetwork_GDA.shp` 7,234 polylines + plan layers (base network, primary/secondary/greenway, feeder, rural routes, LA proposals) | **per direction** (`WD_`/`AD_`): facility `Char` (C1/C2/C3 track-track-lane, B1 bus lane, G1 greenway, S1/S2 shared), `PvmtQua` 1-5, `Width` 1-5, `NumConf`, `JuncDel` 1/3/5, `Comfort` 1-5, `Gradien`, `QoS` A+..D; `Navteq_ID` link | free |
| NTA Projected Cycle Lanes (April 2021) | https://data.smartdublin.ie/dataset/projected-cycle-lanes | CC-BY 4.0 | CSV 22 KB (scheme centroids) + KML | GDA schemes with status (Feasibility/Detailed Design/...) and `METRES` | scheme level, not segments | free |
| NTA CycleConnects / GDA Cycle Network Plan 2022 | https://www.nationaltransport.ie/... (CycleConnects and GDA CNP pages) | n/a | **not verifiable today**: nationaltransport.ie and transportforireland.ie both returned HTTP 503 "Website Temporarily Offline" maintenance pages; no GIS layer on data.gov.ie or Smart Dublin; the only CycleConnects feature service on ArcGIS Online is Cork City Council's `Cork_MA_Routes_CycleConnects_2024` | GDA / national | plan maps are PDF as far as could be checked; the 2013 plan GIS is in `cycnet.zip` above | free |
| DCC Strategic Cycle Network | https://data.smartdublin.ie/dataset/dublin-city-strategic-cycle-network | CC-BY 4.0 | **DWG only** (2007 CAD, Irish Grid) | DCC | n/a | free |
| DLR Cycle Lanes (`cycle-lanes-dlr`) | https://data.smartdublin.ie/dataset/cycle-lanes-dlr | CC-BY 4.0 | GeoJSON 1.16 MB | 695 features / 250.1 km | `Status` Red/Orange/Green Existing = busy / low-traffic / pedestrian-cycle **route suitability** (active school travel), not facility type | free |
| SDCC Cycleways (`cycleways-sdcc3`) | https://data-sdublincoco.opendata.arcgis.com/datasets/sdublincoco::cycleways-sdcc | CC-BY 4.0 | GeoJSON 0.62 MB (EPSG:2157) | 1,020 features / 211.9 km | CAD `Layer`: C1 Cycle Track Separated 63.9 km, C2 Track Immediately Adjacent 50.6 km, C3 Cycle Lane even within Bus Lane 65.0 km, S2 Shared 16.8 km, G1 Greenway 15.6 km | free |
| Fingal CC cycle layers | https://data.fingal.ie (`cycle-lanes-protected-rivervalley-hartstown-fcc`, `baldoyle-howth-cycleway`, `protected-greenway-cycling-lanes`) | CC-BY 4.0 | ArcGIS Hub GeoJSON | scheme-specific only, no county-wide layer | n/a | free |
| TII National Road Network 2013; Sinuosity Index 2016 | https://data.gov.ie/dataset/national-road-network-2013 (zip 8.97 MB at data.tii.ie); https://data.gov.ie/dataset/national-road-network-sinuosity-index | CC-BY 4.0 | KML/SHP, direct | national roads only; sinuosity for ~5,500 1-km sections | geometry (2013) and a bendiness ratio; **no cycle-facility dataset** (ArcGIS Online TII items: low-height bridges only); counters covered in motor-traffic-flow.md | free |
| Tailte Éireann High Value Dataset **Ways** | https://data.gov.ie/dataset/high-value-dataset-ways1 (service `services-eu1.arcgis.com/FH5XCsx8rYXqnjF5/.../Ways/FeatureServer/9`) | CC BY 4.0 (item `licenseInfo`) | ArcGIS REST, 2,000 records per page; GeoJSON/CSV/FGDB bulk exports | 618,183 **polygons** nationally (carriageway footprints "Motorway to Fifth Class") | fields `GUID`, `OBJECTID`, `Shape__Area`, `Shape__Length` only: **no class, name, surface or line geometry** exposed | free |
| Tailte Éireann Roads, National 250k Map | https://data.gov.ie/dataset/roads-national-250k-map-of-ireland | CC BY 4.0 | ArcGIS REST / GeoJSON | 5,188 polylines, generalised | `FCsubtype`, `RTT` (route-type code), `LEN` | free |
| Road Management Office (MapRoad) Regional and Local Road Network | https://data.gov.ie/dataset/regional-road ; https://data.gov.ie/dataset/local-roads (feature services `services-eu1.arcgis.com/1WMHEXUiEEVyii3S/.../Regional Road Schedule Open data`, `Local Road Schedule Open data`; shapefiles 6.9 MB / 40.6 MB) | CC-BY 4.0 on data.gov.ie; item text is an accuracy disclaimer | ArcGIS REST / shapefile | 934 regional routes, 68,726 local routes, 31 LAs | `LA`, `RoadNumber`, `RoadClass` only; **no PSCI or any condition field** | free |
| MapRoad PSCI (Pavement Surface Condition Index) | RMO/LASNTG presentations, e.g. https://lasntg.ie/wp-content/uploads/2026/05/2018-to-2024-Regional-Road-Network-Survey-Analysis.pdf (3.7 MB) | n/a | **not open**: segment ratings live in MapRoad (LA login); publications give network-level shares only | regional network 13,300 centreline km / 700 routes surveyed 2024 (IRI, SCRIM, texture, PSCI, width) | network shares only (2024 IRI: c. 67 % smooth or better at the speed limit, 80 % fair or better); 0 hits for "PSCI" on data.gov.ie and Smart Dublin | n/a |
| SDCC Road Schedule | https://data-sdublincoco.opendata.arcgis.com/datasets/sdublincoco::road-schedule-sdcc | CC-BY 4.0 | CSV 1.1 MB | 4,183 segments (LS 3,280 / 624 km, R 333 / 114 km, LP 275 / 135 km, LT 195 / 33 km, NP 74, NS 26) | `RoadClass`, `RoadType`, `MinWidth`/`MaxWidth` (mostly 0), no condition | free |
| Mapillary | https://www.mapillary.com/developer/api-documentation ; terms https://www.mapillary.com/terms | images CC BY-SA 4.0 (terms §3(b)); registration and client token required; "data mining ... not approved by Mapillary" prohibited (§5) | **token required for every request**: `tiles.mapillary.com/maps/vtp/mly1_public/2/14/7906/5195.mvt` without a token returns 404, `graph.mapillary.com/images?bbox=...` returns 500 "Invalid OAuth 2.0 Access Token"; not registered, coverage not measured | n/a | n/a | free with account |
| Microsoft Road Detections (Bing Maps) | https://github.com/microsoft/RoadDetections | ODbL | `Northern_Europe.zip` 985 MB (drop 2025-04-28; Ireland is in Northern Europe), TSV rows of Alpha-3 + GeoJSON LineString with `WidthMeters` | 2,380k km Northern Europe | ML-detected centreline geometry + width; **no class, name, surface or cycle attributes**; not downloaded | free |
| Meta Daylight Map Distribution | https://daylightmap.org/ | ODbL (OSM-derived) | sunset announced 2024-05-03; final release v1.58 on 2024-11-12 (80.6 GB planet PBF) | planet | validated OSM + ML roads/buildings; discontinued in favour of Overture | n/a |

## Hands-on check

Everything is reproducible from the repo root; raw downloads are in `data/opendata/<source>/` (gitignored),
three small outputs are in `data/samples/`, and the two counting scripts are kept in `scripts/`.

```
# Overture (37 s wall, 148,638 rows, 160 MB; state file records release 2026-10-21.0)
uvx overturemaps download --bbox=-6.45,53.25,-6.05,53.45 -f geojson --type=segment -o data/opendata/overture/dublin_segments.geojson
python3 -I scripts/overture_segment_counts.py data/opendata/overture/dublin_segments.geojson   # -> data/samples/overture_dublin_segments_summary.json
# OSM, same bbox (116 s): highway=cycleway ways, lane/track roads per build_cycle_overlay.classify, tag coverage
uv run scripts/osm_cycle_counts_bbox.py data/osm/ireland.osm.pbf -6.45,53.25,-6.05,53.45          # -> data/samples/osm_dublin_cycle_counts.json
# Overture schema (no `lanes` anywhere in segment.yaml; road_flags enum is bridge/link/tunnel/under_construction/abandoned/covered/indoor)
curl -sL https://raw.githubusercontent.com/OvertureMaps/schema/main/schema/transportation/segment.yaml | grep -n -i lane
# Dublin layers (CKAN package_show gives the resource URLs quoted in the table)
curl -sL -o data/opendata/nta_cycle_2025/nta_cycle_network_2025.geojson https://data.smartdublin.ie/dataset/48b6d5da-c868-41f1-9216-a5e14ceb9d62/resource/955f4c0a-a6dd-47b6-88f5-9d5541a3a6c4/download/nta-active-travel-cycle-network-geojson.json
curl -sL -o data/opendata/nta_cycnet_2013/cycnet.zip https://data.smartdublin.ie/dataset/b1af94ed-0e3f-4639-aefc-b0a743c4bcc2/resource/a9aca3ff-cf86-44af-8e11-b4ce13acf6ae/download/cycnet.zip
# Tailte HVD Ways and RMO regional roads via ArcGIS REST (fields, counts, bbox samples)
curl -s "https://services-eu1.arcgis.com/FH5XCsx8rYXqnjF5/arcgis/rest/services/Ways/FeatureServer/9?f=json"
curl -s "https://services-eu1.arcgis.com/1WMHEXUiEEVyii3S/arcgis/rest/services/Regional%20Road%20Schedule%20Open%20data/FeatureServer/0?f=json"
```

**1. Overture vs OSM for Dublin.** Overture's Dublin segments are OpenStreetMap, re-cut and re-attributed,
with a thin TomTom sprinkle: of 181,911 `sources` entries, 181,133 are `OpenStreetMap` (licence field
`ODbL-1.0`, OSM snapshot version `2026-10-10`) and 778 are `TomTom`, 777 of which sit on `class=unknown`
(the one other is a residential segment). No Esri, Microsoft or Meta source appears in the theme. An
OSM mapping slip survives verbatim: one secondary segment is named `George's Street cycleway:left=no`.
The release is nine days staler than the Geofabrik extract (2026-10-10 vs 2026-10-19).

Cycle information in Overture is limited to three things: `class=cycleway` (2,902 segments, 484 km, of
which 198 carry `subclass=cycle_crossing`), `access_restrictions` with `mode=bicycle` (allowed 2,271,
designated 1,917, denied 990 entries) and route/name strings. There is **no property for an on-road cycle
lane or track**: the current segment schema has no `lanes` property at all, `road_flags` is restricted to
`is_bridge/is_link/is_tunnel/is_under_construction/is_abandoned/is_covered/is_indoor`, and the only
cycle-related enum values are the `cycleway` class and the `cycle_crossing` subclass. The 2,864 `lane`,
1,348 `track`, 1,175 `separate` and 542 `share_busway` values OSM carries on Dublin roads are dropped.
OSM `smoothness`, `lanes`, `lit`, `width` (apart from 1,346 `width_rules` segments) and all `cycleway:*`
sub-tags (surface, width, segregated, oneway) are dropped too; `road_surface` keeps a coarse
paved/unpaved/gravel/paving_stones/dirt/metal set on 69,889 segments. Overture km below are whole-segment
lengths for segments intersecting the bbox; OSM km are clipped to the bbox, OSM ways are counted if any
vertex is inside.

| item (Dublin bbox) | OSM (2026-10-19) | Overture 2026-10-21.0 |
|---|---|---|
| dedicated cycleways (`highway=cycleway` / `class=cycleway`) | 5,117 ways, 473.7 km (742 ways `segregated=yes` 130.8 km; 3,262 shared with foot 334.4 km) | 2,902 segments, 484.0 km (ways merged into longer segments; 198 `cycle_crossing`) |
| on-road **cycle lanes** (`cycleway*=lane/shared_lane/share_busway`) | 3,020 ways, 248.8 km (secondary 168.0, tertiary 46.8, unclassified 9.8, trunk 8.0, residential 6.9) | **none: no property exists** |
| on-road **cycle tracks** (`cycleway*=track/separate`) | 2,399 ways, 238.8 km (secondary 98.7, tertiary 71.9, unclassified 23.3, residential 18.6, trunk 15.7) | **none** |
| any `cycleway*` key on a road | 12,358 ways, 1,310.5 km (7,432 values are `no`) | n/a |
| bicycle access | `bicycle=*` on 9,797 ways | `access_restrictions` mode `bicycle` on 5,178 rule entries |
| surface | `surface` on 46,300 road ways (68 % of road km), 3,900 cycleway ways (73 % of cycleway km) | `road_surface` on 69,889 segments, coarse classes only |
| smoothness | 2,903 road ways (5 % of km), 253 cycleway ways | none |
| lane count / maxspeed | `lanes` 27,819 ways (48 % of km); `maxspeed` 35,055 ways (60 % of km) | no lane count; `speed_limits` on 42,338 segments |
| road classes | residential 19,877 ways / 2,437 km; secondary 6,387 / 581; tertiary 3,832 / 480; unclassified 2,201 / 316 | residential 30,383 / 2,448 km; secondary 5,423 / 611; tertiary 4,517 / 495; unclassified 2,061 / 333; `unknown` 819 / 51 |
| non-OSM content | - | 778 TomTom-sourced segments, 777 of them `class=unknown` |
| licence | ODbL | ODbL (transportation theme) |

**2. Dublin council / NTA cycle layers.** The NTA 2025 layer is the only current, metro-wide one:
975.7 km drawn per side (DIR Forward 764 km, Bi-Directional 211 km) in five classes: footway-level or shared
footpath 335.9 km, painted lane 316.2 km, segregated track 180.4 km, traffic-free trail 121.7 km, signed
quietway 21.5 km. It has no attribute beyond class and direction. Numerical cross-check in
Rathmines-Ranelagh (bbox `-6.275,53.315,-6.245,53.335`, `data/samples/nta_cycle_network_2025_rathmines_ranelagh.geojson`):
NTA has 12.5 km of BIKE_LANE sides and 2.8 km of SEPARATE_TRAIL sides; the planner's OSM overlay has 5.4 km
of ways with lanes on both sides (10.8 side-km) plus 1.3 left and 0.2 right (12.3 side-km of lanes) and
1.0 side-km of track plus 1.8 km of `highway=cycleway` (2.8 km). The two agree to within 2 %; OSM is not
behind the council data here. The 2013 survey shapefile is the richest file found: per direction it rates
pavement quality, width, number of conflicts, junction delay, comfort and gradient and gives a QoS grade,
on a Navteq-linked network, but it is 14 years old. SDCC's layer uses the same C1/C2/C3 taxonomy
(63.9 / 50.6 / 65.0 km); DLR's layer is a route-suitability colouring, not infrastructure; DCC publishes a
2007 DWG; Fingal only scheme polygons.

**3. NTA plans.** The CycleConnects and GDA Cycle Network Plan 2022 pages could not be read: both NTA
domains served HTTP 503 maintenance pages on 2026-10-21. No GIS version of either plan is on data.gov.ie or
Smart Dublin; the 2013 plan's GIS (`cycnet.zip`) is. Flagged below.

**4. TII.** Open, CC-BY, but geometry/bendiness/counters only (national roads, 2013 network); no
cycle-facility layer. OSM already has the geometry; not downloaded.

**5. Tailte Éireann.** The HVD "Ways" layer is genuinely open (CC BY 4.0) and national, but the service
exposes 618,183 carriageway **polygons** with no attributes but a GUID; a 1,284-polygon sample for
Rathmines-Ranelagh is in `data/opendata/tailte_ways/` (2.2 MB). Its one potential use is carriageway width
per OSM way. The 250k roads layer has `RTT`/`FCsubtype` codes on 5,188 generalised lines. No PRIME2 line
network with class/name/surface is open (that is the licensed MapGenie product).

**6. MapRoad / PSCI.** The RMO road schedules are open (934 regional and 68,726 local routes, CC-BY) with
`LA`, `RoadNumber`, `RoadClass` only; a 110-route Dublin regional sample is in `data/opendata/rmo_roads/`.
PSCI ratings are not published as data anywhere found; the 2024 regional survey is reported as network
shares in a LASNTG slide deck.

**7. Mapillary.** Every tile and Graph API request needs a token; without one the coverage tile is a 404
and the API answers "Invalid OAuth 2.0 Access Token". Per the rule of this note no account was created, so
Dublin/Wicklow coverage was not measured. Images are CC BY-SA 4.0; bulk extraction outside the published
interfaces is forbidden by the terms.

**8. Microsoft Road Detections / Daylight.** Road Detections (ODbL) adds ML-detected centrelines with a
`WidthMeters` property, no classes or cycle attributes; for Ireland it can only flag roads missing from
OSM, which the Dublin counts above make irrelevant. Daylight was an OSM mirror with validation and ML
additions; it was sunset in 2024 (final v1.58, 2024-11-12) and its pipeline now feeds Overture.

**Verdict table.** (a) cycle infrastructure, (b) surface quality, (c) traffic/road class, (d) licence
compatibility with an ODbL-derived planner.

| source | (a) cycle infrastructure | (b) surface quality | (c) traffic / road class | (d) licence |
|---|---|---|---|---|
| OSM | lanes, tracks, cycleways, sub-tags; 249 km lanes + 239 km tracks + 474 km cycleways in the bbox | `surface` 68 % of road km, `smoothness` 5 % | highway class, `maxspeed`, `lanes` 48 % | ODbL (baseline) |
| Overture 2026-10-21.0 | **worse**: cycleways only, no lane/track property | worse: coarse `road_surface`, no smoothness | same classes, plus `unknown`; speed limits | ODbL, compatible, nothing gained |
| NTA 2025 cycle infrastructure | independent council-sourced classes per side, 976 side-km; matches OSM within 2 % in a test area; useful as a **QA diff**, not a replacement | none | none | CC-BY 4.0, compatible with attribution |
| NTA 2013 survey (`CycleNetwork_GDA.shp`) | per-direction facility type | **pavement quality 1-5 per direction** (2012) | junction delay, conflicts, comfort, QoS grade | CC-BY 4.0 |
| NTA 2021 BikeLife / 2023 protected | classes, `width`, `mandatory`, `bollardpro`, bus-lane flag | surface-change flag only | none | CC-BY 4.0 |
| SDCC / DLR / Fingal / DCC | SDCC C1/C2/C3 212 km; DLR route colours; Fingal schemes; DCC DWG | none | none | CC-BY 4.0 |
| TII | none | none (sinuosity only) | national-road geometry, counters | CC-BY 4.0 |
| Tailte HVD Ways / 250k | none | none; carriageway **width** derivable from polygons | 250k route-type code only | CC BY 4.0 |
| RMO MapRoad schedules | none | none open (PSCI closed) | R / L road numbers and class for all 31 LAs | CC-BY 4.0 |
| Mapillary | imagery-derived, token-gated | imagery | none | CC BY-SA 4.0 images, terms restrict mining |
| MS Road Detections | none | none (width) | none | ODbL |
| Daylight | discontinued | - | - | ODbL |

## Verdict

**Overture: not usable as an improvement.** For Dublin it is an ODbL OpenStreetMap mirror nine days stale,
with 778 TomTom stubs of class `unknown`, and it strips exactly the tags the planner needs: there is no
representation of on-road cycle lanes or tracks (OSM has 249 km of lanes and 239 km of tracks in the bbox),
no smoothness, no lane counts, no `cycleway:*` sub-tags. Same licence, strictly less content. **Council /
NTA layers: usable with caveats.** The NTA 2025 layer is the only current independent record of Dublin
cycle infrastructure and is CC-BY; in a test area it agrees with OSM within 2 %, so its value is as a
diff to find OSM omissions, not as a routing input. The 2013 survey is the only open file with per-segment
pavement quality and junction delay for Dublin, but it is 2012 vintage. **Surface quality remains closed**:
PSCI is not published, Tailte exposes no attributes, and Mapillary needs an account. **Road class**: nothing
beyond what OSM already has, except RMO's authoritative R/L numbering for all counties.

## Open questions for Eric

- NTA sites were down on 2026-10-21: when they are back, is the GDA Cycle Network Plan 2022 or CycleConnects available as a web map (ArcGIS Experience) whose feature service could be read, as Cork City Council did for its CycleConnects routes?
- Is a Mapillary account acceptable (free, CC BY-SA imagery, client token) to measure Dublin/Wicklow coverage and, later, to spot-check surface or lane presence? This note stayed token-free by rule.
- Is a 2012-vintage pavement-quality grade (NTA 2013 survey, per direction, 7,234 links) worth matching to OSM ways as a weak surface prior where OSM `smoothness` is missing (95 % of Dublin road km), or is it too old to trust?
- Should the planner's cycle overlay carry an NTA-vs-OSM disagreement layer (OSM says no lane where NTA says BIKE_LANE, and the reverse) so that fixes can be pushed upstream to OSM?
