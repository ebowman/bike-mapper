# Motor-traffic volume (AADT): open sources and their coverage of minor roads

Bead: bike-mapper-dhy.5 (secondary objective; scope unchanged). Script: `scripts/traffic_coverage.py`.

## Question

Is open motor-traffic volume data (AADT or similar) dense enough to classify the minor roads a road cyclist uses (tertiary, unclassified) as quiet vs busy? Why it matters for the planner: busy roads cause yield-stops when joining/crossing and make riding unpleasant; direct AADT would be the cleanest "busy" signal, but only if it reaches minor roads.

## Sources evaluated

"Reuse in an app" = does the licence allow it (attribution assumed to be given).

| name | URL | licence | format / access | update | count points | road classes covered | reuse in an app |
|------|-----|---------|-----------------|--------|--------------|----------------------|-----------------|
| TII Traffic Counter **locations** (data.gov.ie `traffic-counter-locations`) | http://data.tii.ie/Datasets/TrafficCounters/tmu-traffic-counters.geojson (also KML/SHP/TSV) | CC-BY 4.0 | GeoJSON, direct download, no auth | ad hoc (static file) | **308** TMU sites (M 92, N 187, R 15, T 14 by name prefix) | national roads only (motorway, N, a few R) | Yes (CC-BY) |
| TII Traffic Data portal (AADT / monthly / hourly per site) | https://trafficdata.tii.ie/ (`publicmultinodemap.asp`, `dsaadtsummary.asp`, `tfnodemonths.asp`; data.gov.ie `traffic-counter-data`) | CC-BY 4.0 (per data.gov.ie) | per-site XLSX/CSV reports from a web form; **no bulk file, no documented API** | near real time | the same ~300 sites | national roads only | Yes (CC-BY), but only manual per-site download. **Not retrieved here, see Hands-on** |
| TII per-vehicle records (data.gov.ie `national-road-traffic-counts`) | http://data.tii.ie/Datasets/pvrs/ | CC-BY | TSV, ~330 GB, 6.5 bn records at ~300 sites | continuing | ~300 | national roads | Yes, but absurd for AADT: same sites |
| Dublin City Council traffic volumes (data.gov.ie `traffic-volumes`; plus `volume-data-for-dublin-city-from-dublin-city-council-traffic-departments-scats-system`) | https://data.smartdublin.ie/dataset/traffic-volumes | CC-BY 4.0 | CSV + locations CSV/GeoJSON, direct download (18 resources) | yearly cordon counts (Nov: 33 sites; May: ~60 sites); SCATS volume ZIPs for past periods | ~33-60 sites per survey | urban arterials into/around Dublin city centre | Yes (CC-BY); city-centre only, irrelevant to rural tertiary/unclassified |
| Dun Laoghaire-Rathdown SCATS traffic volumes (data.gov.ie `traffic-volumes-from-scats-traffic-management-system-2021/2022/2023`) | https://data.smartdublin.ie (DLR organisation) | CC-BY 4.0 | monthly CSV, direct download | monthly | one detector set per signalised junction in DLR (count not tallied here) | urban signalised junctions, South Dublin | Yes (CC-BY); signalised urban junctions only |
| Cork (Cork City Council / Cork County Council) | data.gov.ie searched `q=traffic counts Cork` | n/a | n/a | n/a | n/a | n/a | No open motor-traffic count dataset found (search terms: "traffic counts Cork"; only `corkcitypedestriancounts`, pedestrian counts, cc-by, Cork City Council, turned up) |
| Kildare (Kildare County Council) | data.gov.ie searched `q=Kildare traffic`, `q=Kildare traffic count` | n/a | n/a | n/a | n/a | n/a | No open motor-traffic count dataset found (search terms: "Kildare traffic", "Kildare traffic count"; results were only TII, DCC, DLR sets). Closest local-authority example elsewhere: Kilkenny County Council "Road Traffic Counts 2016" (CC-BY 4.0, one-off XLSX at https://opendata.kilkennycoco.ie/portal/Kilkenny-Traffic-Counts-2016.xlsx, not downloaded or counted here) shows counties can publish minor-road counts, but one-off |
| NTA (National Transport Authority) | data.gov.ie searched `q=NTA traffic`; NTA Transport Modelling / National Household Travel Survey pages | n/a | n/a | n/a | n/a | n/a | No open NTA road-traffic count/AADT dataset found on data.gov.ie (search term: "NTA traffic"; hits were CSO "NTA" survey tables on collisions, unrelated). NTA modelling outputs (National Transport Model) are not published as open data to our knowledge: not verified |
| Dublin-region cycle counters (DCC, DLR, Fingal; data.smartdublin.ie, search "cycle counter") | https://data.smartdublin.ie | CC-BY 4.0 | CSV/GeoJSON, direct download | monthly/yearly | cycle (not motor) counters in Dublin | cycle infrastructure | Yes (CC-BY), but cycle counts, not motor AADT |
| DfT Road Traffic Statistics, AADF by count point (GB) | https://roadtraffic.dft.gov.uk/downloads (`dft_traffic_counts_aadf.zip`, `count_points.zip`) | OGL v3.0 | CSV in ZIP (150 MB unzipped), direct download | annual (2000-2025 present) | **46,754** count points ever; **35,849** with an AADF record in 2016-2025 (22,334 in 2025 alone); 600,550 point-year rows | all: motorway (TM/PM), A (TA/PA), B (MB), minor C/U (MCU, 3,851 points in 2025) | Yes (OGL, attribution) |
| DfI Northern Ireland traffic counts | https://www.opendatani.gov.uk (search "traffic count") / DfI Traffic Information | OGL v3.0 where on OpenDataNI (to be verified) | not verified: OpenDataNI API returned non-JSON from this machine | n/a | n/a (availability only, as briefed) | n/a | Unverified |
| EU spot-check: France, "Trafic moyen journalier annuel (TMJA) sur le reseau routier national" (DIR/Cerema, data.gouv.fr) | https://www.data.gouv.fr/datasets/trafic-moyen-journalier-annuel-sur-le-reseau-routier-national | fr-lo (Licence Ouverte 1.0, reuse allowed) | CSV (160 KB) + SHP, years to 2024, direct download | annual | national network only (160 KB CSV, i.e. a few thousand segments at most) | national roads (routes nationales/autoroutes non-concedees) | Yes (Licence Ouverte) |
| EU spot-check: France, departmental TMJA (e.g. Sarthe) | https://data.sarthe.fr (via data.gouv.fr `le-trafic-moyen-journalier-annuel-en-sarthe`) | Licence Ouverte v2.0 | CSV/GeoJSON/SHP via OpenDataSoft | annual | one departement; many departements publish, patchy | departmental roads (D), i.e. the French equivalent of regional/local roads | Yes |
| OSM tags (`maxspeed`, `lanes`, `highway`) | ireland.osm.pbf | ODbL 1.0 | PBF | continuous | n/a | see `docs/research/osm-road-network.md`: maxspeed on 34% and lanes on ~28% of tertiary+unclassified km; highway 100% | Yes (ODbL share-alike) |
| OSM direct volume tags (`traffic_volume`, `aadt`, `traffic_count`, `traffic:volume`, `average_traffic`, `traffic_flow`) | same | ODbL | `scripts/traffic_coverage.py tags` (pyosmium KeyFilter, nodes+ways) | n/a | **0 found** in the Ireland extract | n/a | n/a |

## Hands-on check

Reproduce (from repo root, `uv run`):

```
# data (gitignored under data/traffic/)
curl -L -o data/traffic/tii/tmu-traffic-counters.geojson http://data.tii.ie/Datasets/TrafficCounters/tmu-traffic-counters.geojson
B=https://storage.googleapis.com/dft-statistics/road-traffic/downloads/data-gov-uk
curl -L -o /tmp/aadf.zip $B/dft_traffic_counts_aadf.zip && unzip -d data/traffic/dft /tmp/aadf.zip
curl -L -o /tmp/cp.zip $B/count_points.zip && unzip -d data/traffic/dft /tmp/cp.zip
curl -L -o data/osm/devon.osm.pbf https://download.geofabrik.de/europe/united-kingdom/england/devon-latest.osm.pbf
uv run python scripts/traffic_coverage.py ireland   # ~7 min (full-island network parse), cached afterwards
uv run python scripts/traffic_coverage.py devon     # ~35 s
uv run python scripts/traffic_coverage.py tags      # ~15 s
```

Downloaded and row counts: TII TMU locations 308 features (WGS84, all `NRA`, fields: description with road + junction names, site id, lat, lon; **no AADT in this file**). DfT `count_points.csv` 46,754 rows (one per point; `year` = last year with an AADF record: 22,334 for 2025, 10,951 for 2019, the rest older) and `dft_traffic_counts_aadf.csv` 600,550 rows (242,838 Counted, 357,713 Estimated). Outputs are in `data/samples/traffic_coverage_ireland.md`, `data/samples/traffic_coverage_devon.md`; snapped point lists in `data/samples/tii_tmu_snapped.csv`, `data/samples/dft_devon_count_points_snapped.csv`; TII locations sample `data/samples/tii_tmu_traffic_counters.geojson` (157 KB, CC-BY 4.0, TII).

**TII AADT values could not be retrieved.** `trafficdata.tii.ie` is unreachable from this machine: HTTPS fails at the TLS handshake (connection reset) and plain HTTP returns a "Web Site Blocked" page (a local web filter, not a TII refusal). The locations are open and bulk; the AADT numbers sit behind the portal form. Manual route (to be done from an unfiltered network): open https://trafficdata.tii.ie/publicmultinodemap.asp, click a counter on the map, choose "AADT summary" (dsaadtsummary.asp) for a date range, and use the XLSX export; repeat per site (308 times; no bulk endpoint is documented). Not needed for the coverage question, which depends only on where the counters are.

CRS: TII GeoJSON is already WGS84 (CRS84); DfT provides WGS84 `latitude/longitude` (OSGB easting/northing also present, not used). Both sets asserted to lie in the country bbox (Ireland -10.8..-5.3 E, 51.3..55.5 N; Devon -5.3..-2.8, 50.1..51.3). `scripts/snap.py` projects to EPSG:2157 (ITM); for Devon (3.5W) this distorts distances by a fraction of a percent: irrelevant here.

Method: nearest OSM `highway` way segment within 30 m (`snap.py` STRtree); then "km within 2 km" = for each way segment, 100 m sub-pieces whose midpoint lies within 2 km of any count point (exact polygon clipping was >10 minutes at Ireland scale; error at the disc edge is below ~50 m per segment crossing). Totals are way segment lengths in the extract (so tertiary 24,058 km, unclassified 70,420 km, within 1% of the figures in `osm-road-network.md`).

### Table 1. Count points per OSM highway class

Ireland (TII, 308 points; 307 snapped, median snap 6.6 m):

| class | points |
|---|---:|
| motorway (+ motorway_link 19) | 79 (+19) |
| trunk (+ trunk_link 6) | 75 (+6) |
| primary | 76 |
| secondary | 20 |
| tertiary | 3 |
| unclassified | 2 |
| residential | 2 |
| service / track / path / footway / cycleway | 11 / 2 / 2 / 4 / 6 |
| no way within 30 m | 1 |

GB, Devon + Plymouth + Torbay (DfT, 914 points with an AADF record in 2016-2025; 859 physically "Counted" at least once in that window; all snapped, median snap 1.6 m):

| class | all active points | counted in last 10 y |
|---|---:|---:|
| motorway | 6 | 6 |
| trunk (+ links) | 131 (+6) | 120 (+4) |
| primary (+ link) | 179 (+1) | 153 (+0) |
| secondary | 37 | 37 |
| tertiary | 92 | 89 |
| unclassified | 236 | 231 |
| residential | 190 | 187 |
| service / track / path / footway / cycleway / living_street | 6 / 5 / 4 / 12 / 8 / 1 | 5 / 4 / 4 / 11 / 7 / 1 |

DfT road_category x snapped class: of the MCU (minor C/U) points, 234 snap to unclassified, 188 to residential, 88 to tertiary. Points that snapped to footway/cycleway/path/service (about 30 in Devon, ~25 in Ireland incl. service/track) are almost certainly counters on the parallel road where a footway or cycleway sits within the nearest-segment search; this is the plain "nearest way" rule, not corrected.

### Table 2. Share of tertiary / unclassified km within 2 km of any count point

Ireland. The headline row is for the whole island extract (island incl. NI): it includes Northern Ireland, which TII does not cover. NI is about 16,744 km (17.7%) of the 94,478 km of tertiary+unclassified, estimated by testing way-segment midpoints against the Nominatim polygon of the Northern Ireland relation (no TII point falls inside it). **Republic-only: 77,734 km, of which 4,169 km (5.4%) is within 2 km of a TII point (94.6% not).** The table below is island-wide; read the Republic-only 5.4% as the better Irish figure.

| count-point set | class | total km | km within 2 km | % within | % NOT within |
|---|---|---:|---:|---:|---:|
| all 308 TII points | tertiary | 24,058 | 1,464 | 6.1 | 93.9 |
| all 308 TII points | unclassified | 70,420 | 2,763 | 3.9 | 96.1 |
| all 308 TII points | **tertiary+unclassified (island incl. NI)** | 94,478 | 4,227 | **4.5** | **95.5** |
| points on secondary or lower only (38 points) | tertiary+unclassified | 94,478 | 603 | 0.6 | 99.4 |
| all 308 TII points | secondary | 16,485 | 1,089 | 6.6 | 93.4 |
| all 308 TII points | residential | 16,567 | 2,825 | 17.1 | 82.9 |

GB-region: Devon (+Plymouth, Torbay; Geofabrik Devon extract; chosen because the full-GB OSM extract is ~2 GB and Devon is rural, the closest GB analogue to Irish tertiary/unclassified roads):

| count-point set | class | total km | km within 2 km | % within | % NOT within |
|---|---|---:|---:|---:|---:|
| all 914 active DfT points | tertiary | 1,472 | 992 | 67.4 | 32.6 |
| all 914 active DfT points | unclassified | 8,297 | 5,093 | 61.4 | 38.6 |
| all 914 active DfT points | **tertiary+unclassified** | 9,769 | 6,085 | **62.3** | **37.7** |
| 859 points counted (not estimated) in last 10 y | tertiary+unclassified | 9,769 | 6,006 | 61.5 | 38.5 |
| counted-10y points on MCU (minor C/U) roads only | tertiary+unclassified | 9,769 | 5,002 | 51.2 | 48.8 |

Caveats: (1) Devon is clipped at the county boundary, so roads near the edge lose coverage from counters just across it (understates "within"). (2) Count points are placed on dual carriageways on one carriageway only and the 30 m nearest-segment rule may pick the other carriageway or a parallel path; this affects only the class tally, not the 2 km coverage. (3) DfT AADFs are partly estimated (2025 rows: 14,384 Estimated vs 7,950 Counted overall; for minor C/U roads 3,256 of 3,851 are flagged Counted), and a counted AADF is itself derived from a short count scaled to an annual figure (DfT methodology; not checked here). Median 2025 MCU AADF is 1,047 vehicles/day (Devon MCU: median 559, max 11,114), i.e. the values do separate quiet from busy minor roads. (4) A 2 km disc is generous: a count at one point says little about the next lane 1.5 km away.

## Verdict

**Ireland: (c), useless as a direct minor-road layer.** The open TII data is 308 counters on motorways, N-roads and a few R-roads. Only 5 of 308 points sit on tertiary/unclassified roads, and 95.5% of island tertiary+unclassified km (94.6% of Republic-only km, about 73,500 of 77,700) has no counter within 2 km, rising to 99.4% (island incl. NI) if only counters on secondary-or-lower roads are counted. It cannot classify the quiet-road network, and the per-site AADT is not even bulk-downloadable. The nearest it gets to (b) is calibration for national/regional road volumes (an estimator trained on class + context could be checked against N/R-road counts) and, with 20+ secondary points, as a sanity check. I pick (c) rather than (b) because 5 minor-road points are far too few to train on; TII counts would be at most a sanity check for an estimator trained elsewhere (e.g. on DfT data).

**GB: (b), a training/validation signal for an estimator.** DfT lists 46,754 count points (35,849 active since 2016) and AADF for all road classes, including thousands of minor roads, and in Devon 62% of tertiary+unclassified km is within 2 km of an active count point (51% using only counted minor-road points), leaving about 38-49% with no nearby count. About 85% of 2025 minor C/U rows are flagged Counted, so the values are real measurements, but 38-49% of minor-road km still has no count within 2 km, so it cannot be a full layer (a); it is best used as a training/validation signal for a class+context model, with direct lookup as a bonus where a point is within a few hundred metres. Ireland is the planner's primary market, so the planner cannot assume direct AADT; GB shows what a mature scheme looks like and supplies free training labels to learn "what a quiet C/U road looks like in OSM". France (national network only, plus patchy departmental files) looks like Ireland-lite: national roads plus voluntary departmental data.

Stated percentage of cyclist-relevant road km (tertiary+unclassified) with no count within 2 km: **Ireland 94.6% (Republic-only; 95.5% island incl. NI); Devon 37.7%** (48.8% counting only counted minor-road points).

### Link to the flow finding (dhy.11)

In the stop-model validation, busy-road yield-stops are the `yield_infer` class (inferred yield: a minor road meeting a higher-class road without a give_way/stop sign): p(stop) = 0.016 (242 units, 34 stops of 2,118 passes in the combined set; 0.011-0.022 CI), i.e. a low per-pass stop probability (inferred yields account for roughly 9% of observed stops, but because there are many such passes; the rate per pass is what is low) and AADT would not materially sharpen the stop-cause model on current evidence. The mechanism is real (a cyclist crossing or joining a busy road waits longer), but p is so low that the junction type is not what drives stops; an AADT-weighted yield model could at best move p from 0.016 towards a bimodal value (more stops where the crossed road is very busy), which would need many more observed passes than the 34 stops available, and the major road's volume is typically known from class alone. For the planner: AADT would be more plausibly a comfort/safety cost on road segments than a stop-model feature; for the flow objective keep using OSM class + explicit signs.

## Proxy / derived approaches (no implementation, one-line feasibility each)

1. **OSM class + maxspeed + lanes heuristic.** Feasible now, free, complete coverage for class (100%), maxspeed (34% on tertiary+unclassified; Irish defaults inferable from area/class) and lanes; coarse but monotone with traffic; calibrate its bins against TII/DfT counts.
2. **Population / POI gravity model.** Feasible with CSO small-area population or GHSL grids + OSM POIs, assign trips between settlements and route them on the OSM graph (a simple traffic assignment); medium effort, plausible quality on rural roads, validated against the same ~300 TII and DfT points; no licence problem (CSO open, OSM ODbL).
3. **Commercial feeds (TomTom Traffic Stats / Flow, HERE Traffic Analytics).** Technically best (floating-car data on every class), but paid per area or per API call (enterprise pricing, historically hundreds to thousands of EUR per month for production use), licences generally forbid bulk caching and redistribution and tie data to the vendor's map; not open, not a v1 option for a free app.
4. **Mapillary image-based car counts.** Feasible only for a sampling/calibration role: Mapillary (CC-BY-SA imagery) coverage of Irish minor roads is patchy, object-detection of passing vehicles per frame gives density not flow, and counts need many passes per road; high effort, low payoff.
5. **Learn it from GB.** Train a class+context model on DfT's minor-road counts (OSM features -> log AADF), apply to Ireland with TII as the check; reasonable and cheap given OGL data, but needs a transfer-validity test (Irish rural lanes are narrower and busier per class than English ones is a plausible bias).

## Open questions for Eric

- Is a class + maxspeed + settlement-gravity estimate good enough for a v1 busy/quiet label, or must it be calibrated first (needs the TII per-site AADT, i.e. a manual portal pull from an unfiltered network)?
- Should Northern Ireland (DfI) be in v1 scope? Availability was not verified here.
- Is training on DfT England data an acceptable basis for an Irish traffic estimator, or do we want an Irish-only check?
