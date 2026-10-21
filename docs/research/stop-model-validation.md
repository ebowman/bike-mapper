# Stop-model validation: do OSM stop-cause features predict where Eric actually stops?

## Question

Do the OSM stop-cause features from dhy.10 (signals, signalled crossings, stop/give_way signs, roundabout entries, inferred yields) predict the stop probability observed on Eric's rides (dhy.6, dhy.15)? The answer is a per-class stop-probability table, an honest "explained fraction", and a concrete relative cost-weight table for the BRouter `flow` profile (dhy.8). It decides whether the planner's stop cost can come from OSM alone.

## Sources evaluated

| name | URL | license | access method | coverage | resolution/granularity | cost |
|------|-----|---------|---------------|----------|------------------------|------|
| Eric's observed stops, Ireland (`data/samples/observed_stops_eric.csv`) | local (Garmin Connect export, dhy.12) | personal data, not redistributable beyond the aggregated CSV | CSV, per OSM node | 31 rides / 1,128 km, 15,176 nodes (>= 1 pass), 41,038 node passes; auto-pause OFF, stops = slow-speed runs | per node, one stop per ride per node | free |
| Eric's observed stops, Berlin (`data/samples/observed_stops_eric_berlin.csv`) | local (same export) | personal data | CSV, per OSM node | 32 rides / 1,490 km, 9,622 nodes with >= 2 passes (nodes with < 2 passes dropped upstream), 29,780 passes; auto-pause ON, stops = timer gaps | per node | free |
| OSM stop-cause events (`data/osm/events_ireland.csv`, `events_berlin.csv`) | https://download.geofabrik.de/europe/ireland-and-northern-ireland-latest.osm.pbf and https://download.geofabrik.de/europe/germany/brandenburg-latest.osm.pbf | ODbL 1.0 | `scripts/osm_stop_features.py --causes-csv` (dhy.10 rules incl. approach attribution, yield inference) | Ireland (bbox widened to cover all rides), Berlin | per (way, direction, junction node, cause) | free |
| OSM PBF tags near units (level crossings, amenities, ways) | same two extracts | ODbL 1.0 | pyosmium pass in `scripts/validate_stop_model.py` | same | node/way tags | free |

## Hands-on check

**Reproduce** (about 5 min the first time, dominated by the PBF passes; about 30 s afterwards, the event-node coordinates and unexplained-unit evidence are cached in git-ignored `data/osm/`):
```
uv run scripts/osm_stop_features.py data/osm/ireland.osm.pbf --bbox=-8.9,53.1,-6.0,54.8 \
  --csv /tmp/s.csv --full-csv /tmp/f.csv --signals /tmp/sig.csv \
  --causes-csv data/osm/events_ireland.csv --report /tmp/r.md        # ~2 min, widened events
uv run scripts/validate_stop_model.py                                 # 5 min cold, 30 s warm
```
One run writes the headline and the sensitivity variants. Outputs (all < 1 MB): `data/samples/stop_model_validation_{ireland,berlin,combined}.csv` (per-class rows, >= 5-pass and all-unit tables), `stop_model_sensitivity_{classes,summary}.csv` (all four clustering variants, with weights), `stop_model_unexplained_{ireland,berlin}.csv`, and `stop_units_{ireland,berlin}.csv` (headline units for the map viewer: unit_id, lat, lon, passes, stops, p, class, n_nodes, diameter_m, member_node_ids pipe-separated; all units kept, Ireland 434 KB, Berlin 278 KB; lat/lon = the member node with most passes).

**Coverage check (Ireland).** The existing `events_dublin_wicklow.csv` (bbox -6.6,52.95,-6.0,53.4) covered only 8,914 of the 15,176 observed Irish nodes (rides reach Co. Louth/Meath and west to -8.78). Events were regenerated with bbox -8.9,53.1,-6.0,54.8, which covers 100 % of observed nodes (470 k event rows; `data/osm/events_ireland.csv`; the old file is untouched). Berlin used the existing `events_berlin.csv` (bbox 12.908..13.76, 52.297..52.746), which contains all 9,622 Berlin nodes.

**Method (revised after review).**
1. *Units: bounded-diameter clustering is the headline.* Observed nodes (per region, projected CRS) are grouped by leader clustering with r = 25 m (seeds in descending passes order; every unit has diameter <= 50 m). Unit passes = max member passes (ride passes are NOT recounted from the tracks; the tracks are not in the repository output and a recount would need the 6-minute stop_events run, so this is a stated simplification); unit stops = sum of member stops capped at unit passes. Single-linkage 20 m (as first briefed) is kept as an **upper bound**, not the headline: it chains along roads into units up to 560 m long, where stops from distinct rides along the chain are summed but passes are a max over one node, which inflates p(stop) (review: p(signal) 0.14 for compact units, 0.22 for 40-100 m, 0.46 for > 100 m). Leader r = 20 and 30 m are the other sensitivity variants.
2. *Class by proximity.* A unit takes the first matching class (signals > stop > give_way > roundabout entry > level crossing > signalled crossing > inferred yield > equal-class > mid-way) from the OSM stop-cause events (dhy.10) lying **within 20 m of any member node**, not only on member nodes (event-node coordinates read from the PBF; level crossings = PBF `railway=level_crossing`). This is needed because Eric often rides a parallel cycle track whose nodes are not the junction's event node. Consequences: (a) classes are mutually exclusive by precedence, so a signalled crossing within 20 m of a signal is counted as signals and the "signalled crossing" class now means only crossing signals with no junction signal nearby (it can no longer be compared with signals; see weights); (b) generous catchment: effective reach of a unit is up to about 45 m from its seed. **Direction limitation:** observed stops are not directional, so presence of a cause in either travel direction classifies the unit.
3. Wilson 95 % intervals, implemented directly. Headline table: units with >= 5 passes; all-unit tables in the CSVs. Classes with < 30 passes are marked under-powered, not dropped.

**Nodes to units (headline leader r = 25 m).** Stops are already capped at one per ride per node upstream.

| region | nodes | units | units with > 1 node | largest unit (nodes / diameter) | p99 diameter | stops raw to capped at unit level | level-crossing units (PBF has) |
|---|---|---|---|---|---|---|---|
| Ireland | 15,176 | 5,705 | 3,375 | 25 / 50 m | 45 m | 308 to 302 | 6 (1,735) |
| Berlin (>= 2 passes) | 9,622 | 3,619 | 2,220 | 24 / 48 m | 45 m | 427 to 427 | 13 (4,267) |
| combined | 24,798 | 9,324 | 5,595 | | | 735 to 729 | 19 |

(Single linkage 20 m: 7,326 units, largest 559 m Ireland / 367 m Berlin, 735 to 676 stops.)

**Headline table: combined Ireland + Berlin, units with >= 5 passes (1,629 units).**

| class | units | passes | stops | p(stop) | 95 % Wilson CI | mean stop s | stop-s per pass | note |
|---|---|---|---|---|---|---|---|---|
| traffic_signals | 227 | 1660 | 262 | 0.158 | 0.141 - 0.176 | 27.9 | 4.41 |  |
| stop sign | 77 | 866 | 18 | 0.021 | 0.013 - 0.033 | 41.1 | 0.85 |  |
| give_way sign | 64 | 513 | 21 | 0.041 | 0.027 - 0.062 | 28.9 | 1.18 |  |
| roundabout entry | 4 | 22 | 0 | 0.000 | 0.000 - 0.149 | n/a | 0.00 | under-powered (< 30 passes) |
| level crossing | 2 | 23 | 1 | 0.043 | 0.008 - 0.210 | 74.0 | 3.22 | under-powered (< 30 passes) |
| signalled crossing (no signal within 20 m) | 13 | 105 | 2 | 0.019 | 0.005 - 0.067 | 34.5 | 0.66 |  |
| inferred yield | 242 | 2118 | 34 | 0.016 | 0.011 - 0.022 | 36.0 | 0.58 |  |
| equal-class uncontrolled | 31 | 238 | 5 | 0.021 | 0.009 - 0.048 | 13.0 | 0.27 |  |
| mid-way (no event within 20 m) | 969 | 8421 | 24 | 0.003 | 0.002 - 0.004 | 57.4 | 0.16 |  |

All-unit table (combined):

| class | units | passes | stops | p(stop) | 95 % Wilson CI | mean stop s | stop-s per pass | note |
|---|---|---|---|---|---|---|---|---|
| traffic_signals | 1042 | 3484 | 530 | 0.152 | 0.141 - 0.164 | 28.6 | 4.34 |  |
| stop sign | 236 | 1119 | 25 | 0.022 | 0.015 - 0.033 | 44.2 | 0.99 |  |
| give_way sign | 358 | 1118 | 31 | 0.028 | 0.020 - 0.039 | 33.3 | 0.92 |  |
| roundabout entry | 39 | 83 | 1 | 0.012 | 0.002 - 0.065 | 18.0 | 0.22 |  |
| level crossing | 19 | 55 | 5 | 0.091 | 0.040 - 0.196 | 56.6 | 5.15 |  |
| signalled crossing (no signal within 20 m) | 62 | 210 | 4 | 0.019 | 0.007 - 0.048 | 24.2 | 0.46 |  |
| inferred yield | 1219 | 3948 | 49 | 0.012 | 0.009 - 0.016 | 41.7 | 0.52 |  |
| equal-class uncontrolled | 235 | 640 | 11 | 0.017 | 0.010 - 0.030 | 16.6 | 0.29 |  |
| mid-way (no event within 20 m) | 6114 | 16684 | 73 | 0.004 | 0.004 - 0.005 | 51.4 | 0.22 |  |

Per region (>= 5 passes; u = units, p = passes, s = stops): Ireland: traffic_signals 67u/610p/63s p=0.103 ; stop sign 72u/832p/13s p=0.016 ; give_way sign 25u/257p/11s p=0.043 ; roundabout entry 4u/22p/0s p=0.000 ; level crossing 2u/23p/1s p=0.043 ; signalled crossing 4u/42p/2s p=0.048 ; inferred yield 149u/1507p/25s p=0.017 ; equal-class uncontrolled 11u/79p/4s p=0.051 ; mid-way 594u/5863p/19s p=0.003. Berlin: traffic_signals 160u/1050p/199s p=0.190 ; stop sign 5u/34p/5s p=0.147 ; give_way sign 39u/256p/10s p=0.039 ; signalled crossing 9u/63p/0s p=0.000 ; inferred yield 93u/611p/9s p=0.015 ; equal-class uncontrolled 20u/159p/1s p=0.006 ; mid-way 375u/2558p/5s p=0.002.

**Cross-region caveat.** Ireland rides have auto-pause OFF, so a stop is a slow-speed run (< 1 m/s for >= 3 s) that misses brief rolling stops and is long when it happens (mean 34 s at signals); Berlin has auto-pause ON, so a stop is a Garmin timer gap, shorter (26 s at signals, 12 s at give_way/stop signs). Signal p(stop) is 0.10 (Ireland) vs 0.19 (Berlin); the weights below are therefore instrument-dependent (give_way: Ireland 152-217 vs Berlin 17-23 on the 300 scale). Combined numbers pool both.

**Explained fraction and precision/recall (headline).** Explained = share of all stop events (units with >= 1 pass; Berlin units with >= 2 passes, since lower-pass nodes were dropped upstream) at units whose class is not mid-way / equal-class. Precision/recall: rule "an OSM stop-cause class (signals ... inferred yield) is present within 20 m implies p(stop) >= 0.5", units with >= 5 passes.

| region | stops | explained stops | **explained fraction** | predicted positive | actual positive (p >= 0.5) | true positive | **precision** | **recall** | precision / recall at p >= 0.25 |
|---|---|---|---|---|---|---|---|---|---|
| Ireland | 302 | 243 | **80.5 %** | 323 | 8 | 8 | **2.5 %** | **100 %** | 4.9 % / 88.9 % |
| Berlin | 427 | 402 | **94.1 %** | 306 | 25 | 25 | **8.2 %** | **100 %** | 16.3 % / 100 % |
| combined | 729 | 645 | **88.5 %** | 629 | 33 | 33 | **5.2 %** | **100 %** | 10.5 % / 97.1 % |

Reading: with a 20 m reach nearly every junction-like unit has some cause within range (629 of 1,629 units predicted positive), so recall is trivially 100 % while precision is 5 %; the binary rule is useless, and the explained fraction is correspondingly generous. The informative numbers are the per-class probabilities, not the yes/no rule. The 88.5 % is an upper-end figure: classifying by member nodes only (`--event-m 1`) gives 62.7 % (Ireland 64.9, Berlin 61.1; signal p 0.18, signalled crossing 0.27); proximity at 20 m gives 80-94 %.

**Sensitivity to the grouping (combined, units with >= 5 passes; weights on the signals = 300 scale, net of the mid-way background).**

| variant | units | explained IE / B / all | precision / recall (all) | p(signal) | give_way w | stop w | yield_infer w | equal-class w | level crossing w |
|---|---|---|---|---|---|---|---|---|---|
| leader r = 20 m | 10,885 | 78.6 / 93.2 / 87.1 % | 4.5 / 100 % | 0.134 | 82 | 79 | 33 | 35 | 212 |
| **leader r = 25 m (headline)** | 9,324 | 80.5 / 94.2 / 88.5 % | 5.2 / 100 % | 0.158 | 72 | 49 | 29 | 8 | 216 |
| leader r = 30 m | 8,138 | 81.0 / 94.8 / 89.1 % | 6.3 / 100 % | 0.174 | 68 | 49 | 26 | 9 | 193 |
| single linkage 20 m (upper bound) | 7,326 | 81.8 / 94.0 / 88.8 % | 9.0 / 100 % | 0.253 | 84 | 65 | 32 | 11 | 175 |

Signalled-crossing weight: 0-35 in all four variants because the class is a residual after the signal precedence (signals-vs-crossings cannot be separated by proximity classification; with member-node classification the crossing class gets p 0.27 vs 0.18 for signals, weight 390). Roundabout entries: 0 stops in 22 passes in every variant.

**Unexplained stops (top 15 by stop count among mid-way / equal-class units, per region).** Headline unexplained stops: 59 of 302 in Ireland (19.5 %) and 25 of 427 in Berlin (5.9 %); the top 15 cover 21 and 16 of them (most units have a single stop, so the "top" list is thin). Labels are manual, from the OSM evidence within 40 m and mean stop duration (no Mapillary/Street View). **Label set: the bead's five (missing OSM tag, traffic queue, café/photo/regroup, descent hairpin, data noise) + other, plus one added category, "model gap: OSM feature present nearby but not attached"** (a tagged OSM feature within ~40 m that is not a modelled cause or was beyond the 20 m reach).

| region | rep. node | lat, lon | class | passes | stops | mean s | label | evidence |
|---|---|---|---|---|---|---|---|---|
| IE | 658732 | 53.37165, -6.08746 | midway | 20 | 3 | 100 | café/photo/regroup | Carrickbrack Rd, no junction tags, 100 s: scenic stop |
| IE | 253242243 | 53.37835, -6.06212 | yield_equal | 5 | 2 | 16 | missing OSM tag | Greys Lane residential junction, only inferred equal-class, 16 s, no sign |
| IE | 659995687 | 53.45430, -6.17059 | midway | 5 | 2 | 63 | model gap | traffic_calming=hump on the node + bollard 8 m (not a modelled cause), 63 s |
| IE | 4136049853 | 53.46454, -6.19083 | midway | 2 | 2 | 102 | café/photo/regroup | Hutchinsons Strand seafront, gate + slipway, 102 s |
| IE | 187666504 | 53.36716, -6.14894 | midway | 2 | 2 | 36 | other | unclassified road meeting a path, nothing tagged within 40 m, 36 s |
| IE | 1727098423 | 53.37090, -6.08681 | midway | 22 | 1 | 69 | café/photo/regroup | Carrickbrack Rd informal crossing + stile to Bog of Frogs Loop, 69 s |
| IE | 3009484963 | 53.37820, -6.05662 | midway | 21 | 1 | 25 | model gap | bus stop + stop_position 15 m, gate, service accesses, 25 s (bus stops are not modelled) |
| IE | 662369070 | 53.38793, -6.06501 | midway | 15 | 1 | 7 | traffic queue | Howth Abbey St pedestrians/shops, 7 s, no junction tags |
| IE | 686825610 | 53.38781, -6.06829 | midway | 13 | 1 | 33 | café/photo/regroup | Howth Harbour Rd benches/bins/milestone, 33 s |
| IE | 219167289 | 53.37088, -6.05536 | midway | 12 | 1 | 87 | café/photo/regroup | Howth Summit car park: benches, bins, tourism=viewpoint 28 m, 87 s |
| IE | 6725253387 | 53.38007, -6.10257 | midway | 11 | 1 | 16 | model gap | Sutton Strand bus stop_position on the node, 16 s |
| IE | 219167494 | 53.37067, -6.05505 | midway | 10 | 1 | 63 | café/photo/regroup | Howth Summit: bicycle parking, benches, viewpoint, 63 s |
| IE | 3647682703 | 53.43220, -6.12484 | midway | 7 | 1 | 7 | traffic queue | Strand Rd, parking/parking_space 5-10 m, 7 s: parking manoeuvres |
| IE | 5630463604 | 53.37745, -6.06414 | yield_equal | 7 | 1 | 10 | missing OSM tag | Balkill Rd/Windgate Rd residential junction, 10 s, no tags |
| IE | 302333152 | 53.39831, -6.12645 | midway | 7 | 1 | 73 | café/photo/regroup | Strand Rd promenade bench 12 m, unmarked crossing 14 m, 73 s |
| B | 247327311 | 52.42888, 13.12259 | yield_equal | 2 | 2 | 10 | traffic queue | Pfaueninselchaussee ferry access: tourism=information, bins, 10 s |
| B | 21487185 | 52.52342, 13.40720 | yield_equal | 9 | 1 | 10 | model gap | Rochstr: two unmarked crossings 6-7 m + bollards (pedestrian crossings are not modelled), 10 s |
| B | 413278860 | 52.46888, 13.19734 | midway | 8 | 1 | 73 | café/photo/regroup | Havelchaussee tourism=information 32 m, 73 s: viewpoint |
| B | 8026011923 | 52.44123, 13.20022 | midway | 8 | 1 | 38 | café/photo/regroup | Havelchaussee tourism=information 14 m, 38 s: viewpoint |
| B | 3413071801 | 52.51517, 13.34926 | midway | 8 | 1 | 57 | café/photo/regroup | Grosser Stern (Siegessaeule) bench/street lamps, 57 s: landmark stop |
| B | 8995300528 | 52.51418, 13.34730 | midway | 7 | 1 | 105 | café/photo/regroup | Str. des 17. Juni tourism=information 18 m, 105 s |
| B | 13311134869 | 52.51666, 13.38128 | midway | 5 | 1 | 13 | other | Unter den Linden tram stop 8 m, bins; 13 s, cause unclear |
| B | 12645611885 | 52.50017, 13.22136 | midway | 4 | 1 | 8 | missing OSM tag | path meeting tertiary Am Postfenn, 8 s, nothing tagged |
| B | 30133333 | 52.41824, 13.10921 | midway | 4 | 1 | 135 | café/photo/regroup | Nikolskoer Weg gate 18 m, 135 s: Nikolskoe viewpoint |
| B | 4160071854 | 52.57829, 13.39841 | midway | 3 | 1 | 30 | other | Grabbeallee service access onto primary, only street lamps within 25 m, 30 s |
| B | 10617298999 | 52.53287, 13.41421 | midway | 3 | 1 | 25 | other | Kollwitzstr service/residential, bicycle parking 11 m, 25 s |
| B | 11414645634 | 52.58519, 13.40259 | midway | 3 | 1 | 39 | model gap | traffic_signals 22 m + signalled crossing 24 m, beyond the 20 m reach of this unit, 39 s |
| B | 10617306940 | 52.53445, 13.41596 | midway | 3 | 1 | 4 | data noise | 4 s, close to detection floor; bicycle parking only |
| B | 7710514833 | 52.40924, 13.05834 | yield_equal | 3 | 1 | 26 | model gap | railway=tram_level_crossing 1 m (only railway=level_crossing is modelled), 26 s |
| B | 2260518688 | 52.41545, 13.12561 | midway | 3 | 1 | 47 | model gap | bus stop 17 m + stop_position 19 m, platform Schaeferberg, 47 s |

Label counts (30 units): café/photo/regroup 12, model gap 7, other 4, missing OSM tag 3, traffic queue 3, data noise 1 (no descent hairpin, no start/end proximity; start/end stops are filtered upstream). **Share labelled "missing OSM tag": 3 of 30 (10 %)**; so the OSM completeness gap seen from the saddle is small in this sample (the model gap adds another 23 %). About 40 % of the top units are viewpoint/café stops that no map can predict.

**Re-check of the earlier top-30.** Of the 30 units that were "unexplained" under the first (member-node, single-linkage) analysis, 19 now fall into a cause class under the headline proximity classification, including all 13 that had been diagnosed as "signals on a cycleway/footway": every one of them has a `highway=traffic_signals` (or signalled crossing) node with `on_road_way=1` within 6-19 m (the review's finding; the earlier diagnosis that the signals were attached only to cycleway nodes was wrong for those, and 5 of the 13 have no `on_road_way=0` signal within 20 m at all). They were missed because the riders' nodes (a parallel cycle track or the footway side) were not the junction's event node, not because OSM lacked the tag. The other 11 stay mid-way/equal-class; the table above is the new headline top 15. Attaching signals mapped on cycleway nodes to road junctions is therefore not the main driver of the gap; proximity classification, as done here, is the fix. (The previous "+6 pt / 81 %" estimate is withdrawn.)

## Verdict

**Yes-with-empirical-correction.** A stop-cost model built from OSM features alone can optimise for flow credibly for the dominant causes, but only as a probability-weighted cost, not a flat penalty per feature, and the individual numbers are sensitive to how rides are grouped into junctions. Proximity classification (OSM cause within 20 m of the ridden nodes) explains 88.5 % of observed stops (Ireland 80.5, Berlin 94.1; member-node-only classification 62.7 %, and 87-89 % across the four groupings), but the binary rule "cause present means stop" is worthless (precision 5 %, recall 100 %): p(stop) at a signal is only 0.16 combined (0.11-0.25 across groupings; Ireland 0.10, Berlin 0.19), at give_way signs 0.04, stop signs 0.02, inferred yields 0.016, equal-class junctions 0.02, mid-way 0.003. **Signals carry the weight**: 262 of 367 stops (71 %) at units with >= 5 passes are at signal-class units (the signalled-crossing class is absorbed into it); inferred yields add 9 %, give_way 6 % and stop signs 5 %, mid-way background 7 %. Stop signs stop *less* than give_way signs in all four variants (2 vs 4 % combined, and Ireland 1.6 vs 4.3 %), so the untuned `flow.brf` ordering (stop 150 > give_way 80) is inverted relative to Eric's behaviour. Roundabout entries (0 stops in 22 passes) and level crossings (1 stop in 23 passes; 5 in 55 all-unit) are under-powered: do not tune them from this data.

**Recommended relative weights for `profiles/flow.brf`** (not edited here). Weight = 300 x (p(stop) x mean stop seconds per pass for the class, minus the mid-way background) / (same for signals). Headline = leader r = 25 m; range = across leader 20/25/30 and single-linkage 20 m (combined); regional range (Ireland / Berlin) in brackets where they differ a lot:

| class | measured p(stop) headline (range over variants) | headline weight | range over the four variants | current flow.brf | recommendation |
|---|---|---|---|---|---|
| traffic_signals | 0.158 (0.134-0.253) | 300 | 300 (definition) | 300 | keep as the anchor |
| signal crossing (`crossing=traffic_signals`) | not separable (class absorbed by signals; member-node view 0.27 vs 0.18, weight 390) | 35 as a residual | 0-35 (proximity); 390 (member nodes) | 150 | treat as signals, 300 (up to 390); the current halving is not supported |
| give_way | 0.041 (0.037-0.067) | 72 | 68-84 [Ireland 152-217, Berlin 17-23] | 80 | keep about 80 |
| stop sign | 0.021 (0.021-0.044) | 49 | 49-79 [Ireland 56-105, Berlin 99-142, 5 units] | 150 | lower to about 60 |
| inferred yield (minor meets major) | 0.016 (0.014-0.018) | 29 | 26-33 | not representable | about 30 (needs preprocessing; BRouter cannot infer) |
| equal-class uncontrolled | 0.021 (0.021-0.041) | 8 | 8-35 [Ireland 46-152, 79 passes only] | not representable | at most about 10-35, comparable to or below an inferred yield, not zero as first thought; 238 passes and 5 stops only, wide CI (0.009-0.048) |
| roundabout entry / mini-roundabout | 0 stops in 22 passes (upper CI 0.149) | 0 | 0 | 80 / 150 | under-powered, leave unchanged |
| level crossing | 0.043 (0.036-0.056) | 216 | 175-216 | not in profile | under-powered (23 passes at >= 5), leave out |

The scale is 300 / 4.25 net stop-seconds per signal pass (4.41 minus the 0.16 background), i.e. about 70 cost units per net stop-second; whether that matches the profile's cost units (and whether `flow.brf` expresses node cost in the same unit as per-metre cost) is not verified here. Measured durations exclude deceleration and re-acceleration, a roughly constant addition per stop, which would lift high-p classes slightly relative to low-p ones. Regional spread in the table is mostly the instrument: Ireland slow-run stops last about 35-50 s at signs, Berlin timer gaps about 12 s.

**Caveats.** One rider (81 rides, 63 snapped); both stop instruments are imperfect; passes are the max over member nodes rather than recounted from tracks; the proximity reach (20 m around nodes of a 25 m unit) is generous and pools signalled crossings into signals; every p(stop) is dependent on the grouping (signals 0.11-0.25); single-class confidence intervals are wide (give_way 0.027-0.062); about 40 % of the top unexplained units are viewpoint/café stops that no router model can predict.

## Open questions for Eric

- Do you roll through stop signs and give-way signs rather than stopping, and is that deliberate (the data suggests ~2 % and ~4 %)? If you ride with others the numbers may differ.
- Should the planner treat a "stop" as the Garmin auto-pause definition (Berlin) or a slow-speed run (Ireland)? They give different signal p(stop) (about 0.10 in Ireland vs 0.19 in Berlin) and different mid-way rates.
- Is it worth wiring in Mapillary/Street View to check the unexplained units (7 of 30 look like a model gap, 3 of 30 like a missing tag, 12 of 30 like a viewpoint/café stop), or is that detail beyond the study?
- Can friends contribute rides (consented Garmin/Strava exports) to power the roundabout, level-crossing and stop-sign classes (all under 30 passes at >= 5 passes)?
