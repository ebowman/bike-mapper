<!-- data/osm/ireland.osm.pbf: node pass 24s, way pass 59s, inference 25s, total 108s; 637380 road-cycling ways, 359648 tagged nodes, 649296 junction nodes -->

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

Mode: enabled. Explicit signal/stop/give_way nodes on road ways: on a junction node 1840; on an approach (non-junction) node 64625. Approach events (node x travel direction): attributed by walking <= 60 m along the way in the direction of travel to the next junction: 64021; attributed to the nearest junction within 60 m behind (no junction ahead within the cap): 4480; standalone (no junction within 60 m): 528. Junction approaches whose inferred yield / equal-class term was suppressed: 63432.

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
| trunk | 458 | 78 | 1.57 | 7.13 | 4.37 | 32% |
| primary | 142 | 21 | 2.23 | 19.13 | 3.32 | 44% |
| secondary | 2490 | 345 | 1.02 | 10.14 | 3.63 | 45% |
| tertiary | 1807 | 308 | 0.94 | 8.68 | 3.35 | 44% |
| unclassified | 1115 | 324 | 0.48 | 5.35 | 1.41 | 46% |
| residential | 7929 | 956 | 4.36 | 9.70 | 5.56 | 17% |
| living_street | 12 | 1 | 10.66 | 10.66 | 8.94 | 0% |
| service | 7023 | 604 | 3.38 | 9.76 | 6.05 | 28% |

Breakdown of expected stops by cause in bbox (sum over travel directions; per-direction km pooled):

| cause | events | per km |
|---|---|---|
| signal | 1688 | 0.335 |
| stop | 1462 | 0.290 |
| give_way | 781 | 0.155 |
| yield_infer | 4259 | 0.845 |
| yield_equal | 12418 | 2.464 |
| rb_entry | 824 | 0.164 |
| xing_signal | 1785 | 0.354 |

Pedestrian crossing nodes (no signals) on bbox road ways, not in estimate: 2591.

### 20 longest stretches with < 0.2 expected stops/km (Wicklow bbox)

Stretch = connected chain of ways with the same `name` (or `ref` when unnamed) joined at way end-vertices (unnamed ways are single-way stretches). Rate = direction-averaged expected stops / total length (a stretch is not oriented, so fwd/bwd are averaged per way).

| # | name | main class | length km | ways | exp. stops | stops/km | first way id |
|---|---|---|---|---|---|---|---|
| 1 | Military Road | secondary | 22.9 | 19 | 2.5 | 0.11 | 23051141 |
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
