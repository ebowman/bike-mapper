# OSM stop-cause features and a first expected-stops-per-km estimate

## Question

Which OSM features force a road cyclist to stop or yield, how completely are they mapped on the island of Ireland, and what does an OSM-only "expected stops per km" per way look like (Wicklow bbox)? This decides whether the flow-optimising planner can get its stop costs from OSM alone before empirical validation (dhy.11).

## Sources evaluated

| name | URL | license | access method | coverage | resolution/granularity | cost |
|------|-----|---------|---------------|----------|------------------------|------|
| Geofabrik Ireland and Northern Ireland extract (re-used from dhy.2) | https://download.geofabrik.de/europe/ireland-and-northern-ireland-latest.osm.pbf | ODbL 1.0 (share-alike on derived databases; attribution for produced works) | local PBF, pyosmium | Island of Ireland | per node/way tags | Free, 416 MB |
| Dublin City Council "Traffic Signal Sites Junctions DCC" (SCATS site list, file `dcc-traffic-signal-sites_151025.geojson`, 850 sites, Junction/Pedestrian/Pelican/Luas types, WGS84) | https://data.smartdublin.ie/dataset/traffic-signal-sites-juctions-dcc (resource https://data.smartdublin.ie/dataset/d8dce4cf-1bb4-4c71-8afb-bc85a1fe63a4/resource/eb4aee9f-7cc0-4fb8-af61-279c087f35f8/download/dcc-traffic-signal-sites_151025.geojson) | CC-BY 4.0 (attribution: Dublin City Council) | CKAN API `package_search?q=SCATS` on data.smartdublin.ie, direct download | Dublin City Council area only | point per signal site | Free, 172 KB |
| Older DCC release "Traffic signals and SCATS sites locations DCC" (825 points, 2022-11-30) | https://data.smartdublin.ie/dataset/traffic-signals-and-scats-sites-locations-dcc | CC-BY | same | Dublin City | point | Free (downloaded, not used; the 2025 list is newer) |

Search terms tried: `SCATS` on data.smartdublin.ie CKAN (found both datasets), `traffic signals` / `SCATS` on data.gov.ie CKAN (same datasets harvested).

## Hands-on check

Scripts (all outputs reproducible; raw inputs under gitignored `data/osm/`, `data/traffic/`):

```
uv run scripts/osm_stop_features.py data/osm/ireland.osm.pbf --report data/samples/osm_stop_features_ireland.md
curl -sL -o data/traffic/sites_2025.geojson 'https://data.smartdublin.ie/dataset/d8dce4cf-1bb4-4c71-8afb-bc85a1fe63a4/resource/eb4aee9f-7cc0-4fb8-af61-279c087f35f8/download/dcc-traffic-signal-sites_151025.geojson'
uv run scripts/scats_recall.py data/traffic/sites_2025.geojson data/osm/signals_ireland.csv > data/samples/scats_recall_dublin.md
```

Wall time (macOS arm64, 12 cores): `osm_stop_features.py` on Ireland 84 s total in the final run (earlier runs 72-131 s; node pass ~24-31 s, way pass ~50-77 s, in-memory junction + attribution + inference ~20-25 s) against a 10 min budget. Outputs: `data/samples/osm_stop_features_ireland.md` (tables below), `data/samples/stops_per_km_wicklow.csv` (8,797 ways, 0.52 MB; `service` ways and ways < 50 m dropped from the sample only, all statistics use all 20,976 bbox ways; the unfiltered CSV is `data/osm/stops_per_km_wicklow_full.csv`, gitignored), `data/samples/scats_recall_dublin.md`, a 172 KB copy of the DCC site file at `data/samples/dcc_traffic_signal_sites_151025.geojson` (CC-BY 4.0, attribution required), and `data/osm/signals_ireland.csv` (gitignored).

Method notes. Road-cycling ways = `highway` in {trunk, primary, secondary, tertiary, unclassified, residential, living_street, service}; motorway is excluded, `*_link` ways (trunk/primary/secondary/tertiary) are included as junction participants with their parent's class (primary_link = primary), and `highway=service` only if the `service` tag is absent (so driveways, parking aisles and alleys do not create junctions). A junction is a node shared by >= 2 distinct such ways; for the density tables, plain splits (exactly 2 ways of the same class, the node an end vertex of both, i.e. a way merely cut in two) are excluded (both figures are given). Lengths are haversine. Node/way phases are pyosmium `FileProcessor` passes (tagged nodes first, then ways with node locations); junction membership is computed in memory with numpy. Wicklow ways are selected by their mid-vertex being inside lon -6.5..-6.1, lat 53.0..53.3. Direction 'fwd' means along the OSM way order; one-way ways (`oneway=yes|-1`, roundabouts, unless `oneway:bicycle=no`) only get their legal direction (the other column is blank); contraflow cycling is not modelled.

### Yield-inference rule (per way, per direction of travel, at each node)

Class hierarchy (highest priority first): **trunk > primary > secondary > tertiary > unclassified > residential > living_street > service**. A cyclist "approaches" a node when travelling towards it: the last vertex of a way is approached in the forward direction, the first vertex in the backward direction, an interior vertex in both. Rules are applied in order; the first that fires decides the event for that (way, direction, node):

1. **Explicit node tag applying to this direction**: `highway=traffic_signals` counts 1 signal; `highway=stop` counts 1 stop; `highway=give_way` counts 1 give-way; `highway=crossing` with `crossing=traffic_signals` counts 1 signal-crossing; `highway=mini_roundabout` counts 1 roundabout entry. A qualifier (`direction`, `stop:direction`, `traffic_signals:direction`, `give_way:direction`) of `forward`/`backward` restricts it to that travel direction relative to the way; `both`, missing, or any other value (compass, `in`...) applies to both directions (flagged assumption; on one-way ways the single legal direction gets it once). If the qualifier excludes this direction the node falls through to rule 2. An explicit tag on the junction node itself suppresses inference at that node for that direction. Most signs are not on the junction node but one or more vertices before it (on the approach), so see rule 1b.
1b. **Approach-node attribution** (pre-step before the ordered rules). Applies to every `highway=traffic_signals|stop|give_way` node that is on a road way but is NOT itself a junction node ("approach node"). For each direction of travel the node applies to (qualifier and oneway as in rule 1): walk along the way in that direction for at most 60 m (haversine) to the next junction node. A walk that reaches the end vertex of a way at a plain-split continuation node (exactly two ways, same class, end vertex of both) crosses onto the continuing way and keeps walking within the same 60 m budget. The (junction, way, direction) reached is marked explicitly controlled and rules 2-6 (including roundabout-entry, priority and class terms) are skipped there. If no junction is reached within 60 m (or the way ends first) the sign is "standalone": it counts once on its own way and suppresses nothing. There is no "behind" fallback. Unqualified `stop`/`give_way` nodes on two-way ways are walked in both directions but attributed only toward the nearer junction, and their event is counted only for that direction (if neither direction reaches a junction they are standalone and counted in both directions, the old assumption); unqualified `traffic_signals` on two-way ways are attributed and counted in both directions (flagged assumption), and any node with a `forward`/`backward`/`both`/other qualifier uses the directions that qualifier gives. `crossing=traffic_signals` mid-block nodes and mini-roundabouts are not attributed (a pedestrian signal is not a junction control). Residual error, measured over the 64,709 Ireland approach events: 95.6% of events end up with their junction approach actually suppressed (99.3% of those events that have a junction within reach); 3.7% are standalone (no junction within 60 m, of which 243 reach a dead end or a non-road way first), and 0.7% (426) name a junction approach that is then not suppressed, 418 of them because the junction node itself carries a second explicit sign for that direction (two mapped signs, both counted) and 8 because the walk entered a one-way against its direction. Raising the cap to 80 / 100 m would lift the share to 96.4% / 96.9% but would increasingly attach mid-block signs to unrelated junctions, so it is kept at 60 m. Two residuals remain: (i) in 966 narrowed unqualified stop/give_way cases a junction lies within 60 m on both sides, so the "nearer junction" choice can pick the wrong side; (ii) the walk crosses only same-class continuation nodes, so 23 signs whose road changes class before the junction leave that junction unsuppressed (0.04% of events, measured independently by the reviewer).
2. **Not a junction** (fewer than 2 distinct ways at the node): no event.
3. **Roundabout**: if this way has `junction=roundabout|circular`, circulating traffic has priority: 0. Otherwise, if any way at the node is a roundabout, this is an entry: counts 1 roundabout entry (always yields).
4. **Continuation**: exactly two ways meet and both only touch the node at an end vertex (the road merely continues or changes class/name): 0.
5. **priority_road**: if this way has `priority_road=designated|yes` and no other way at the node does, 0. If another way has it and this one does not, 1 inferred yield.
6. **Class comparison** (also when both or neither carry `priority_road`): let H be the best (highest) class among the other ways at the node. This way strictly lower than H (e.g. unclassified meeting tertiary, any class meeting trunk): 1 inferred yield. Strictly higher than all others: 0. Equal to H: 0.5 expected stop ("equal class without tags").
7. There are no other cases: every combination of the eight classes falls under rule 6 or an earlier rule.

Expected stops for a way and direction = signals + stops + give-ways + inferred yields (1.0 each) + equal-class 0.5s + roundabout entries + signal-crossings, divided by way length. Pedestrian crossings without signals, `railway=level_crossing`, `traffic_calming` and `barrier` are counted but NOT in the estimate. Signal nodes only on footway/cycleway/path (not on any road-cycling way) never reach any road way. A signal node at a junction is counted for every road way approaching it (once per approach direction).

Limitations: the 0.5 equal-class rule is the brief's choice and is the largest single contributor (see cause breakdown): it fires for every side street meeting a through street of the same class, on the through way as well as on the side street, because the rule does not use geometry (a through way versus a way ending at a T). A signal on a junction node is counted for every road approaching it. Attribution of approach signs is geometric (<= 60 m) and can wrongly attach a mid-block pedestrian `highway=traffic_signals` node to a nearby junction, suppressing a real yield there. Stretch statistics average the two travel directions because chains are not oriented.

### Node feature counts (whole extract; 'on road way' = node is on a road-cycling way)

| feature | all nodes | on road way | on road %  |
|---|---|---|---|
| highway=traffic_signals | 12118 | 11734 | 97 |
| highway=stop | 29816 | 28604 | 96 |
| highway=give_way | 29727 | 26127 | 88 |
| highway=crossing | 92719 | 44527 | 48 |
| highway=mini_roundabout | 1455 | 1426 | 98 |
| highway=turning_circle | 44309 | 42095 | 95 |
| railway=level_crossing | 1735 | 868 | 50 |
| traffic_calming=* | 33558 | 32450 | 97 |
| barrier=* | 118348 | 37365 | 32 |

Ways with junction=roundabout|circular (all highway classes in scope): 7907 ({'roundabout': 7688, 'circular': 219}), 285 km.

### Crossing nodes by crossing=* value

| crossing value | nodes |
|---|---|
| (no crossing tag) [off road] | 39298 |
| unmarked [on road] | 16725 |
| (no crossing tag) [on road] | 9449 |
| traffic_signals [on road] | 8622 |
| uncontrolled [on road] | 7247 |
| unmarked [off road] | 6214 |
| marked [on road] | 1922 |
| uncontrolled [off road] | 1875 |
| marked [off road] | 452 |
| zebra [on road] | 388 |
| traffic_signals [off road] | 226 |
| informal [on road] | 154 |
| zebra [off road] | 88 |
| informal [off road] | 36 |

### Direction qualifiers on stop-cause nodes

| node type | nodes | with any qualifier | % | direction=* | <type>:direction | forward | backward | both | other |
|---|---|---|---|---|---|---|---|---|---|
| traffic_signals | 12118 | 11130 | 91.8 | 93 | 11046 | 6954 | 3890 | 252 | 34 |
| stop | 29816 | 25477 | 85.4 | 25475 | 2 | 12252 | 13206 | 5 | 14 |
| give_way | 29727 | 29233 | 98.3 | 29233 | 0 | 15526 | 13701 | 3 | 3 |

Signal nodes on road ways with no direction qualifier (counted for both directions on two-way ways, flagged assumption): 960.

### Approach-node attribution of explicit signal/stop/give_way nodes

Mode: enabled. Explicit signal/stop/give_way nodes on road ways: on a junction node 1840; on an approach (non-junction) node 64625. Approach events (node x travel direction it is counted for): 64709.

| attribution outcome | events |
|---|---|
| attributed ahead (walk <= 60 m to the next junction on the same way) | 61248 |
| attributed via continuation (walk crossed >= 1 plain-split node onto the continuing way) | 1057 |
| standalone (no junction ahead within 60 m; nothing suppressed) | 2404 |
| ... standalone because the walk reached a way end with no junction (dead end, or only non-road ways beyond) | 243 |
| ... standalone because the 60 m cap was reached first | 2161 |
| walk ended on a continuation node (should be 0) | 0 |
| behind-fallback keys that never match (fallback removed) | 0 |
| unqualified stop/give_way nodes narrowed to the nearer junction/direction | 4320 |
| distinct (junction, way, dir) keys suppressed (matched a real junction approach) | 61488 |
| ... of which controlled by unqualified stop/give_way nodes | 4586 |
| events whose attributed key matched a real approach (actually suppressed) | 61879 |
| events with a key that matched no approach (residual double counting) | 426 |
| ... unmatched: junction node carries its own explicit sign for that direction (two signs, both counted) | 418 |
| ... unmatched: walk entered a one-way way against its direction | 8 |

**Suppressed share** = events whose junction approach is actually suppressed / all approach events = 61879/64709 = 95.6% (standalone events are 3.7% of events and unmatched keys 0.7%).

traffic_calming on road ways (top 8): hump=14043, table=7754, bump=5737, cushion=2392, rumble_strip=1292, island=743, choker=291, yes=102

barrier on road ways (top 8): gate=32711, lift_gate=1720, bollard=946, height_restrictor=569, cattle_grid=392, block=282, yes=212, swing_gate=144

### Junction nodes and density by highway class

Junction = node shared by >= 2 distinct road-cycling ways. 'Present' = junctions where the class meets; density = present / km of that class (km = sum of way lengths).

| class | km | ways | junctions present | per km | as highest | as lowest |
|---|---|---|---|---|---|---|
| trunk | 3660 | 12587 | 15844 | 4.33 | 15844 | 3197 |
| primary | 3896 | 12005 | 19591 | 5.03 | 19208 | 2159 |
| secondary | 16488 | 47592 | 72481 | 4.40 | 70428 | 9210 |
| tertiary | 24029 | 52480 | 84055 | 3.50 | 74724 | 15979 |
| unclassified | 70281 | 121382 | 162438 | 2.31 | 119001 | 80152 |
| residential | 16533 | 141105 | 154218 | 9.33 | 111617 | 137303 |
| living_street | 36 | 638 | 688 | 19.26 | 175 | 639 |
| service | 35857 | 249591 | 239899 | 6.69 | 77541 | 239899 |
| ALL | 170779 | 637380 | 488538 | 2.86 | | |

Junction nodes: 649296 shared by >= 2 ways, of which 160758 are plain splits (exactly 2 ways of the same class, end vertex of both) and are excluded from the table above, leaving 488538. Density of ALL nodes shared by >= 2 ways (splits kept): 3.80/km. Way classes include `*_link` ways under their parent's class.


#### Junction nodes by (highest class, lowest class) meeting

| highest \ lowest | trunk | primary | secondary | tertiary | unclassified | residential | living_street | service |
|---|---|---|---|---|---|---|---|---|
| trunk | 3197 | 353 | 1067 | 1307 | 2828 | 1599 | 3 | 5490 |
| primary | 0 | 1806 | 838 | 1350 | 4112 | 3085 | 13 | 8004 |
| secondary | 0 | 0 | 7305 | 6004 | 15645 | 12717 | 15 | 28742 |
| tertiary | 0 | 0 | 0 | 7318 | 19988 | 14569 | 10 | 32839 |
| unclassified | 0 | 0 | 0 | 0 | 37579 | 10050 | 28 | 71344 |
| residential | 0 | 0 | 0 | 0 | 0 | 95283 | 435 | 15899 |
| living_street | 0 | 0 | 0 | 0 | 0 | 0 | 135 | 40 |
| service | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 77541 |

### Expected stops/km per way, Wicklow bbox (lon -6.5..-6.1, lat 53.0..53.3)

20976 ways (selected by mid-vertex in bbox); sample CSV `data/samples/stops_per_km_wicklow.csv` has 8797 ways (service ways and ways < 50 m dropped; the full set is `data/osm/stops_per_km_wicklow_full.csv`, gitignored). All tables below use all 20976 ways. Statistics over (way, travel direction) samples for ways >= 0.1 km; 'pooled' = sum stops / sum km over all ways of the class.

| class | ways | km | median stops/km | p90 stops/km | pooled stops/km | share of ways with 0 stops |
|---|---|---|---|---|---|---|
| trunk | 458 | 78 | 1.57 | 7.13 | 4.33 | 32% |
| primary | 142 | 21 | 2.23 | 19.13 | 3.32 | 44% |
| secondary | 2490 | 345 | 1.02 | 10.14 | 3.58 | 45% |
| tertiary | 1807 | 308 | 0.94 | 8.68 | 3.32 | 44% |
| unclassified | 1115 | 324 | 0.48 | 5.35 | 1.41 | 46% |
| residential | 7929 | 956 | 4.35 | 9.68 | 5.53 | 17% |
| living_street | 12 | 1 | 10.66 | 10.66 | 8.94 | 0% |
| service | 7023 | 604 | 3.37 | 9.76 | 6.03 | 28% |

Breakdown of expected stops by cause in bbox (sum over travel directions; per-direction km pooled):

| cause | events | per km |
|---|---|---|
| signal | 1688 | 0.335 |
| stop | 1380 | 0.274 |
| give_way | 776 | 0.154 |
| yield_infer | 4239 | 0.841 |
| yield_equal | 12397 | 2.460 |
| rb_entry | 815 | 0.162 |
| xing_signal | 1785 | 0.354 |

Pedestrian crossing nodes (no signals) on bbox road ways, not in estimate: 2591.

### 20 longest stretches with < 0.2 expected stops/km (Wicklow bbox)

Stretch = connected chain of ways with the same `name` (or `ref` when unnamed) joined at way end-vertices (unnamed ways are single-way stretches). Rate = direction-averaged expected stops / total length (a stretch is not oriented, so fwd/bwd are averaged per way).

| # | name | main class | length km | ways | exp. stops | stops/km | first way id |
|---|---|---|---|---|---|---|---|
| 1 | Military Road | secondary | 22.9 | 19 | 2.2 | 0.10 | 23051141 |
| 2 | R756 | secondary | 10.3 | 8 | 1.5 | 0.15 | 4629662 |
| 3 | Shankill Road | unclassified | 9.8 | 12 | 1.2 | 0.13 | 25103496 |
| 4 | R759 | secondary | 9.3 | 14 | 1.0 | 0.11 | 8908167 |
| 5 | Military Road | secondary | 9.1 | 17 | 1.8 | 0.19 | 23051140 |
| 6 | R763 | secondary | 8.0 | 4 | 0.5 | 0.06 | 31115925 |
| 7 | L1059 | tertiary | 5.6 | 2 | 0.5 | 0.09 | 65072937 |
| 8 | L1013 | tertiary | 5.5 | 13 | 0.5 | 0.09 | 20482143 |
| 9 | Ashford Road | secondary | 5.1 | 7 | 1.0 | 0.20 | 28615844 |
| 10 | L4371 | tertiary | 4.9 | 1 | 0.8 | 0.15 | 19753505 |
| 11 | R759 | secondary | 4.6 | 2 | 0.5 | 0.11 | 71247437 |
| 12 | Lake Drive | tertiary | 4.5 | 8 | 0.0 | 0.00 | 175307556 |
| 13 | Roundwood Road | secondary | 4.3 | 2 | 0.8 | 0.18 | 101353143 |
| 14 | Laragh Road | secondary | 3.2 | 2 | 0.0 | 0.00 | 137884207 |
| 15 | L4377 | tertiary | 2.9 | 3 | 0.0 | 0.00 | 86402431 |
| 16 | (unnamed) | service | 2.7 | 1 | 0.5 | 0.18 | 767749173 |
| 17 | L1013 | tertiary | 2.7 | 4 | 0.0 | 0.00 | 20482146 |
| 18 | (unnamed) | unclassified | 2.7 | 1 | 0.0 | 0.00 | 475897194 |
| 19 | (unnamed) | unclassified | 2.6 | 1 | 0.5 | 0.19 | 53658725 |
| 20 | Glencree Road | tertiary | 2.5 | 3 | 0.0 | 0.00 | 200003222 |

### Effect of approach-node attribution (before = double counting; after = attribution on)

Before: the same script with `--no-attribute` (all other behaviour identical). Per-class figures over (way, direction) samples for ways >= 0.1 km, Wicklow bbox.

Before (explicit tag only suppresses inference when it sits on the junction node itself):

| class | ways | km | median stops/km | p90 stops/km | pooled stops/km | share of ways with 0 stops |
|---|---|---|---|---|---|---|
| trunk | 458 | 78 | 1.57 | 7.13 | 4.75 | 32% |
| primary | 142 | 21 | 2.23 | 21.32 | 3.73 | 44% |
| secondary | 2490 | 345 | 1.04 | 10.82 | 3.88 | 45% |
| tertiary | 1807 | 308 | 0.95 | 9.14 | 3.68 | 44% |
| unclassified | 1115 | 324 | 0.50 | 6.36 | 1.65 | 46% |
| residential | 7929 | 956 | 4.42 | 11.57 | 6.07 | 17% |
| living_street | 12 | 1 | 10.66 | 10.66 | 8.94 | 0% |
| service | 7023 | 604 | 3.38 | 10.00 | 6.36 | 28% |

| cause | events | per km |
|---|---|---|
| signal | 1688 | 0.335 |
| stop | 1462 | 0.290 |
| give_way | 781 | 0.155 |
| yield_infer | 5383 | 1.068 |
| yield_equal | 13097 | 2.599 |
| rb_entry | 906 | 0.180 |
| xing_signal | 1785 | 0.354 |

After (the tables above): tertiary median 0.95 -> 0.94, p90 9.14 -> 8.68; unclassified median 0.50 -> 0.48, p90 6.36 -> 5.35; residential p90 11.57 -> 9.68; pooled stops/km tertiary 3.68 -> 3.32, unclassified 1.65 -> 1.41, residential 6.07 -> 5.53. In the bbox the correction removes 1,144 inferred 1.0-yields, 700 equal-class events, 91 roundabout entries, and (via the unqualified stop/give_way direction narrowing, which counts those signs once instead of in both directions) 82 stop and 5 give-way events. The correction is real but modest in aggregate: most signed approaches are on a minor road whose inferred term would only have been 0.5 or 0.

### Dublin SCATS completeness (OSM recall)

DCC site list, 850 sites, projected WGS84 to EPSG:2157 (ITM), STRtree nearest-neighbour against OSM nodes, hit if <= radius. 'signals + crossing=traffic_signals' uses one definition throughout (`highway=traffic_signals` OR `highway=crossing`+`crossing=traffic_signals`), the same as the estimate.

| OSM set | OSM nodes | radius m | sites | matched | recall % | median nearest m |
|---|---|---|---|---|---|---|
| highway=traffic_signals (all) | 12118 | 30 | 850 | 767 | 90.2 | 11 |
| highway=traffic_signals (all) | 12118 | 50 | 850 | 802 | 94.4 | 11 |
| highway=traffic_signals (all) | 12118 | 100 | 850 | 812 | 95.5 | 11 |
| highway=traffic_signals (on road ways) | 11734 | 30 | 850 | 766 | 90.1 | 11 |
| highway=traffic_signals (on road ways) | 11734 | 50 | 850 | 801 | 94.2 | 11 |
| highway=traffic_signals (on road ways) | 11734 | 100 | 850 | 811 | 95.4 | 11 |
| signals + crossing=traffic_signals | 20966 | 30 | 850 | 777 | 91.4 | 9 |
| signals + crossing=traffic_signals | 20966 | 50 | 850 | 804 | 94.6 | 9 |
| signals + crossing=traffic_signals | 20966 | 100 | 850 | 815 | 95.9 | 9 |

By DCC site Type (signals + crossing=traffic_signals, 30 m):

| DCC type | sites | matched | recall % |
|---|---|---|---|
| Junction | 452 | 429 | 94.9 |
| Pedestrian | 324 | 278 | 85.8 |
| Junction (Luas) | 50 | 49 | 98.0 |
| Pedestrian (Luas) | 10 | 8 | 80.0 |
| Nested Pelican | 7 | 7 | 100.0 |
| Pelican | 7 | 6 | 85.7 |

By DCC site Type (highway=traffic_signals only, 30 m):

| DCC type | sites | matched | recall % |
|---|---|---|---|
| Junction | 452 | 422 | 93.4 |
| Pedestrian | 324 | 275 | 84.9 |
| Junction (Luas) | 50 | 49 | 98.0 |
| Pedestrian (Luas) | 10 | 8 | 80.0 |
| Nested Pelican | 7 | 7 | 100.0 |
| Pelican | 7 | 6 | 85.7 |

Caveat: a match only says an OSM signal node lies within the radius, not that it is the same junction (dense city centre). Pedestrian crossings are the weakest class and matter less for a road cyclist. Dublin is the best-mapped area, so recall there is an upper bound for rural Wicklow (where signals are few); nothing here measures precision (OSM signals that no longer exist) because the DCC list is the only reference.

## Verdict

Usable with caveats. OSM captures signals very well (about 90% of DCC signal sites have a `highway=traffic_signals` node within 30 m, 91% when `crossing=traffic_signals` nodes are included, 94-95% for junction-type sites; 12,118 signal nodes island-wide, 92% of them direction-qualified), and `stop`/`give_way` signs (about 30k nodes each, 85-98% with a `direction`) and roundabouts (7.9k roundabout ways, 1.4k mini-roundabouts) are plentifully and directionally mapped, so these four causes can be used as hard stop costs. What OSM misses or only partly gives: approach-level priority at the great majority of unsigned junctions (only about 60k explicit stop/give-way nodes against 649k junction nodes, 489k of them excluding plain way splits), so most yields have to be inferred from road class; pedestrian crossings are mapped (about 44k on road ways) but cannot say whether traffic actually stops; level crossings, signal phase timing, queueing and traffic-dependent stops are absent; and the inference ignores sight-lines, visibility and actual traffic. The resulting estimate is dominated by inferred yields (mostly the 0.5 equal-class term on residential/service streets; about 3.3 of 4.6 stops/km pooled over the bbox after the double-counting fix), whereas the explicit signal/stop/give-way/roundabout/signal-crossing part (about 1.3 stops/km) is the credible one. An OSM-only estimate is good enough to rank routes coarsely (arterial/rural stretches near 0 stops/km versus built-up areas of 5-6 stops/km) and to generate candidate routes, but the inferred-yield part should not be treated as ground truth for routing until dhy.11 has checked per-feature stop probabilities against observed rides, especially the 0.5 equal-class weight and the "yield = stop" assumption for cyclists, who often only slow down.

## Open questions for Eric

- Should "yield" and "give_way" be treated as a full stop for a road cyclist, or as a speed penalty? The estimate counts each as 1 stop; dhy.11 data should set the real probability.
- The brief fixes equal class without tags at 0.5, which also penalises the through way at a T. Do you want a geometric tiebreak (a way that continues through the node has priority over ways that end there) before we validate? It would cut the 2.6 stops/km equal-class term in the bbox sharply.
- `*_link` ways are now junction participants with their parent's class; `highway=service` with a `service` tag and motorway are still not. Confirm that is what you want.
- Signals on two-way roads without a direction qualifier (960 on road ways) are counted for both directions; acceptable?
- The sample CSV drops `service` ways and ways < 50 m (0.52 MB); the full CSV is only under gitignored `data/osm/`. Fine?
