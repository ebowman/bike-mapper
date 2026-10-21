# OSM road network: tag coverage (Ireland island vs Balearics)

## Question

How complete is OpenStreetMap tagging on the roads a road cyclist actually uses (surface, smoothness, maxspeed, lanes, width, lighting, cycle infrastructure, access, names)? This decides whether OSM alone can be the routing graph and the surface/traffic layer of the planner, or whether other sources must fill gaps.

## Sources evaluated

| name | URL | license | access method | coverage | resolution/granularity | cost |
|------|-----|---------|---------------|----------|------------------------|------|
| Geofabrik Ireland and Northern Ireland extract | https://download.geofabrik.de/europe/ireland-and-northern-ireland-latest.osm.pbf | ODbL 1.0 (OSM data, (c) OpenStreetMap contributors). Share-alike: a derived *database* (e.g. our enriched road graph, derived surface/climb tables) must be offered under ODbL if publicly used; a produced work (rendered map, route output) needs attribution only; keep OSM-derived data separable from proprietary layers to avoid contaminating them | HTTP download (PBF), parsed with pyosmium | Whole island of Ireland (ROI + NI) | Per way/node, tags as mapped | Free (416 MB, downloaded 2026-10-20) |
| Geofabrik Spain / Islas Baleares extract (spot check) | https://download.geofabrik.de/europe/spain/islas-baleares-latest.osm.pbf | ODbL 1.0 (same obligations) | HTTP download | Balearic Islands | Per way/node | Free (47 MB, downloaded 2026-10-20) |

## Hands-on check

Files in `data/osm/` (gitignored): `ireland.osm.pbf` (416,108,834 bytes), `baleares.osm.pbf` (46,797,713 bytes), both fetched 2026-10-20 with `curl -L --retry 3`.

Reproduce (script: `scripts/osm_tag_coverage.py`, pyosmium `SimpleHandler`, `locations=True`, haversine length per way, % is length-weighted, only ways whose `highway` is in the 12 requested classes):

```
uv run scripts/osm_tag_coverage.py data/osm/ireland.osm.pbf
uv run scripts/osm_tag_coverage.py data/osm/baleares.osm.pbf
```

Wall time on a macOS arm64 laptop: Ireland 136 s (well under the 10 min target), Baleares 19 s. Raw output saved in `data/samples/osm_tag_coverage_ireland.md` and `..._baleares.md`.

Limitations: relations are ignored (tags carried only by route/cycle-network relations, e.g. smoothness on a relation, or cycle route membership, are not counted). `cycleway*` means any key starting with `cycleway` (cycleway, cycleway:left, ...). `bicycle` coverage counts any value (yes/no/designated...). Implicit knowledge (e.g. Irish default speed limits, most tertiary being asphalt) is not credited as coverage. Ways are counted whole even if only partly in the extract.

### Ireland: tag coverage (% of length) by class

| class | ways | km | surface | smoothness | maxspeed | lanes | width | lit | cycleway* | bicycle | traffic_calming | oneway | name |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| motorway | 1951 | 2225 | 100.0 | 77.8 | 100.0 | 100.0 | 0.0 | 42.4 | 1.2 | 19.0 | 0.0 | 100.0 | 75.2 |
| trunk | 10827 | 3449 | 100.0 | 0.3 | 99.5 | 100.0 | 0.2 | 26.4 | 11.6 | 42.5 | 0.0 | 41.8 | 65.1 |
| primary | 11816 | 3885 | 98.3 | 1.3 | 92.1 | 98.0 | 0.1 | 20.3 | 27.0 | 0.9 | 0.0 | 15.1 | 45.8 |
| secondary | 46886 | 16451 | 71.0 | 1.3 | 74.1 | 71.5 | 0.4 | 15.3 | 18.6 | 0.6 | 0.0 | 8.9 | 37.0 |
| tertiary | 52081 | 24011 | 47.9 | 0.4 | 53.2 | 44.3 | 1.6 | 8.6 | 8.3 | 0.9 | 0.0 | 8.1 | 32.1 |
| unclassified | 121382 | 70281 | 24.5 | 0.3 | 27.8 | 23.0 | 1.6 | 5.7 | 4.7 | 0.5 | 0.0 | 4.0 | 20.0 |
| residential | 141105 | 16533 | 45.9 | 0.9 | 42.4 | 32.7 | 0.6 | 15.9 | 9.8 | 0.4 | 0.0 | 5.1 | 71.8 |
| living_street | 638 | 36 | 62.2 | 1.6 | 29.7 | 13.4 | 0.9 | 7.2 | 3.8 | 1.4 | 0.0 | 9.2 | 73.6 |
| cycleway | 14982 | 2562 | 83.0 | 7.7 | 0.6 | 1.4 | 10.4 | 21.1 | 9.6 | 67.3 | 0.0 | 50.5 | 40.3 |
| track | 163720 | 46044 | 9.7 | 0.8 | 0.2 | 0.2 | 0.8 | 0.3 | 0.0 | 1.9 | 0.0 | 0.3 | 1.6 |
| path | 39153 | 8142 | 38.1 | 3.6 | 0.0 | 0.0 | 5.3 | 2.4 | 0.2 | 11.6 | 0.0 | 0.2 | 12.6 |
| service | 743865 | 62085 | 10.3 | 0.2 | 1.5 | 1.2 | 0.1 | 0.8 | 0.1 | 0.3 | 0.0 | 2.9 | 1.5 |
| ALL | 1348406 | 255705 | 28.8 | 1.3 | 24.2 | 21.2 | 1.1 | 6.0 | 4.6 | 2.5 | 0.0 | 5.7 | 19.3 |

### Ireland: surface on tertiary + unclassified (top 10)

| surface | km | % |
|---|---|---|
| (missing) | 65563 | 69.5 |
| asphalt | 27420 | 29.1 |
| paved | 860 | 0.9 |
| unpaved | 133 | 0.1 |
| gravel | 108 | 0.1 |
| concrete | 83 | 0.1 |
| compacted | 42 | 0.0 |
| ground | 18 | 0.0 |
| dirt | 17 | 0.0 |
| tarmac | 12 | 0.0 |

### Ireland: smoothness on tertiary + unclassified (all values)

| smoothness | km | % |
|---|---|---|
| (missing) | 94001.5 | 99.69 |
| good | 164.1 | 0.17 |
| excellent | 53.8 | 0.06 |
| intermediate | 50.2 | 0.05 |
| bad | 11.9 | 0.01 |
| very_bad | 10.5 | 0.01 |
| medium | 0.0 | 0.00 |

### Ireland: restricted ways (count of ways) by class

| class | bicycle=no | access=no | access=private |
|---|---|---|---|
| motorway | 532 | 0 | 1 |
| trunk | 114 | 0 | 0 |
| primary | 0 | 0 | 0 |
| secondary | 8 | 14 | 0 |
| tertiary | 8 | 12 | 8 |
| unclassified | 9 | 74 | 380 |
| residential | 9 | 39 | 1349 |
| living_street | 0 | 0 | 11 |
| cycleway | 3 | 117 | 34 |
| track | 1000 | 1384 | 23592 |
| path | 1652 | 392 | 1005 |
| service | 345 | 800 | 159224 |

Note the many `access=private` service/track ways (farm and driveway access); bicycle=no is dominated by motorways (532) and a few hundred paths/service ways. On the 3 classes cyclists favour (secondary, tertiary, unclassified) restrictions are negligible (about 510 ways in total, mostly unclassified `access=private`).

### Spot check: Balearics (same tables)

| class | ways | km | surface | smoothness | maxspeed | lanes | width | lit | cycleway* | bicycle | traffic_calming | oneway | name |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| motorway | 486 | 186 | 100.0 | 45.7 | 97.6 | 100.0 | 0.0 | 92.2 | 0.0 | 8.1 | 0.0 | 100.0 | 52.2 |
| trunk | 639 | 176 | 100.0 | 8.1 | 93.1 | 98.5 | 0.1 | 22.6 | 12.0 | 5.4 | 0.0 | 95.7 | 15.4 |
| primary | 4236 | 741 | 99.9 | 30.5 | 66.3 | 91.4 | 0.3 | 36.0 | 54.1 | 2.7 | 0.0 | 19.6 | 37.3 |
| secondary | 3997 | 773 | 97.3 | 21.8 | 50.8 | 83.8 | 0.9 | 34.5 | 45.5 | 2.0 | 0.0 | 23.2 | 48.5 |
| tertiary | 5349 | 1474 | 96.5 | 17.6 | 39.5 | 60.5 | 3.2 | 23.3 | 31.0 | 3.2 | 0.3 | 20.5 | 59.9 |
| unclassified | 5764 | 3478 | 57.4 | 6.3 | 10.6 | 7.3 | 5.0 | 4.8 | 9.7 | 5.3 | 0.0 | 6.9 | 68.8 |
| residential | 24581 | 4208 | 52.8 | 4.8 | 16.3 | 11.6 | 2.5 | 19.2 | 11.0 | 1.9 | 0.0 | 37.1 | 85.0 |
| living_street | 862 | 77 | 73.6 | 6.8 | 23.5 | 8.4 | 6.5 | 43.0 | 5.7 | 8.8 | 0.0 | 48.0 | 90.3 |
| cycleway | 870 | 285 | 82.1 | 22.1 | 0.0 | 6.8 | 17.2 | 40.1 | 11.3 | 32.0 | 0.0 | 24.9 | 11.1 |
| track | 27861 | 9154 | 16.1 | 1.7 | 0.4 | 0.1 | 2.1 | 1.1 | 0.1 | 6.7 | 0.0 | 0.2 | 13.7 |
| path | 16481 | 4312 | 26.6 | 1.9 | 0.0 | 0.0 | 3.8 | 2.7 | 0.2 | 6.0 | 0.0 | 0.1 | 12.0 |
| service | 35955 | 4107 | 26.0 | 2.1 | 1.2 | 0.9 | 1.0 | 1.9 | 0.2 | 4.0 | 0.0 | 7.1 | 8.0 |
| ALL | 127081 | 28971 | 39.6 | 5.4 | 10.2 | 11.7 | 2.7 | 8.7 | 7.2 | 5.2 | 0.0 | 11.0 | 33.9 |

Balearics tertiary+unclassified surface: asphalt 62.6%, missing 31.0% (Ireland: 29.1% / 69.5%). Smoothness present on 9.6% of length (Ireland 0.31%).

### Comparison, Ireland vs Balearics (ALL classes / tertiary+unclassified)

Tertiary and unclassified values are length-weighted combinations.

- surface: ALL 28.8% vs 39.6%; tertiary 47.9% vs 96.5%; unclassified 24.5% vs 57.4%. Ireland roughly half as complete on minor roads.
- smoothness: ALL 1.3% vs 5.4%; tertiary 0.4% vs 17.6%; unclassified 0.3% vs 6.3%. Poor in both, effectively absent in Ireland.
- maxspeed: ALL 24.2% vs 10.2%; tertiary 53.2% vs 39.5%; unclassified 27.8% vs 10.6%. Ireland better (but Irish defaults are legally implicit by road type/area, so absence is less harmful).
- lanes: ALL 21.2% vs 11.7%; tertiary 44.3% vs 60.5%; unclassified 23.0% vs 7.3%.
- width: ALL 1.1% vs 2.7%; tertiary 1.6% vs 3.2%. Negligible in both.
- lit: ALL 6.0% vs 8.7%; tertiary 8.6% vs 23.3%.
- cycleway*: ALL 4.6% vs 7.2%; tertiary 8.3% vs 31.0%; primary 27.0% vs 54.1%.
- bicycle: ALL 2.5% vs 5.2%; mostly access exceptions, low on minor roads in both.
- traffic_calming: 0.0% vs 0.0% (ALL; 0.3% on Balearic tertiary). It is mostly mapped as nodes, not on ways, so the way-level number is not meaningful; node-level check belongs to the stop-features bead.
- oneway: ALL 5.7% vs 11.0% (reflects urban share, not quality).
- name: ALL 19.3% vs 33.9%; unclassified 20.0% vs 68.8% (many unnamed rural lanes in Ireland).

## Verdict

Partial / usable with caveats. (a) Routing graph: YES. The Irish network is dense (about 1.35 million ways, 256,000 km across the 12 classes, including 24,000 km tertiary and 70,000 km unclassified), the classes cyclists use are all present, access restrictions are rare on public road classes, and `oneway` is explicit where it matters (motorway/trunk); connectivity and geometry are sufficient to build a graph, subject to a later routability test. (b) Surface awareness: PARTIAL, leaning NO. Surface is on 47.9% of tertiary and 24.5% of unclassified length (30.5% of tertiary+unclassified combined, 69.5% missing; 29.1% asphalt, under 2% anything non-asphalt/non-paved), so absence cannot be read as "good road" or "bad road"; smoothness is on only 0.31% of tertiary+unclassified length (about 290 km of 94,292 km) and on under 2% of any class except motorway (77.8%, 2,225 km), cycleway (7.7%) and path (3.6%), so there is no usable road-quality signal in OSM; a surface-quality layer must come from elsewhere (imagery, Mapillary, PSCI, ride data), with OSM `surface` as a prior (asphalt) and `track`/`path` as the non-road-bike classes. Ireland is clearly worse than the Balearic spot check (30.5% vs 69.0% surface on tertiary+unclassified, smoothness 0.31% vs 9.6%). (c) Traffic awareness: NO. OSM carries no traffic volumes; the proxies are `highway` class (good, fully populated), `maxspeed` (only 34% of tertiary+unclassified length, 92-100% of primary and above) and `lanes` (similar), and cycle infrastructure (`cycleway*` 8.3% tertiary, 27% primary). Class plus Irish default speed rules give a coarse traffic proxy, but real AADT (TII, DfT) is needed for actual traffic awareness.

## Open questions for Eric

- Is a coarse class-based traffic proxy (primary/secondary penalised, unclassified favoured) acceptable for v1, or must AADT data be mandatory?
- Is it acceptable to treat missing `surface` on tertiary/unclassified as "probably asphalt" (about 99% of tagged length is paved), accepting occasional gravel surprises?
- Are you OK with ODbL share-alike on any published derived road database, or must the app keep the OSM-derived layer separable?
- Should relation-carried tags (cycle routes, Eurovelo/NCN) be measured in a follow-up? This note ignores relations.
