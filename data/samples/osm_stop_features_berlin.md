<!-- data/osm/brandenburg.osm.pbf: node pass 40s, way pass 41s, inference 9s, total 89s; 317831 road-cycling ways, 308265 tagged nodes, 313542 junction nodes -->

### Node feature counts (whole extract; 'on road way' = node is on a road-cycling way)

| feature | all nodes | on road way | on road %  |
|---|---|---|---|
| highway=traffic_signals | 12099 | 10284 | 85 |
| highway=stop | 1752 | 1594 | 91 |
| highway=give_way | 10885 | 10003 | 92 |
| highway=crossing | 64351 | 61446 | 95 |
| highway=mini_roundabout | 22 | 16 | 73 |
| highway=turning_circle | 5484 | 4452 | 81 |
| railway=level_crossing | 4267 | 3117 | 73 |
| traffic_calming=* | 5244 | 4799 | 92 |
| barrier=* | 204976 | 16694 | 8 |

Ways with junction=roundabout|circular (all highway classes in scope): 945 ({'circular': 159, 'roundabout': 786}), 57 km.

### Crossing nodes by crossing=* value

| crossing value | nodes |
|---|---|
| unmarked [on road] | 36516 |
| traffic_signals [on road] | 12526 |
| (no crossing tag) [on road] | 6026 |
| uncontrolled [on road] | 4870 |
| (no crossing tag) [off road] | 1316 |
| marked [on road] | 1032 |
| unmarked [off road] | 743 |
| uncontrolled [off road] | 387 |
| informal [on road] | 362 |
| traffic_signals [off road] | 314 |
| marked [off road] | 126 |
| zebra [on road] | 100 |
| zebra [off road] | 13 |
| informal [off road] | 6 |

### Direction qualifiers on stop-cause nodes

| node type | nodes | with any qualifier | % | direction=* | <type>:direction | forward | backward | both | other |
|---|---|---|---|---|---|---|---|---|---|
| traffic_signals | 12099 | 6493 | 53.7 | 78 | 6437 | 3910 | 2503 | 76 | 4 |
| stop | 1752 | 1694 | 96.7 | 1693 | 13 | 873 | 818 | 1 | 2 |
| give_way | 10885 | 10502 | 96.5 | 10502 | 1 | 5270 | 5212 | 0 | 20 |

Signal nodes on road ways with no direction qualifier (counted for both directions on two-way ways, flagged assumption): 4228.

### Approach-node attribution of explicit signal/stop/give_way nodes

Mode: enabled. Explicit signal/stop/give_way nodes on road ways: on a junction node 2774; on an approach (non-junction) node 19107. Approach events (node x travel direction it is counted for): 19596.

| attribution outcome | events |
|---|---|
| attributed ahead (walk <= 60 m to the next junction on the same way) | 16071 |
| attributed via continuation (walk crossed >= 1 plain-split node onto the continuing way) | 2289 |
| standalone (no junction ahead within 60 m; nothing suppressed) | 1236 |
| ... standalone because the walk reached a way end with no junction (dead end, or only non-road ways beyond) | 34 |
| ... standalone because the 60 m cap was reached first | 1202 |
| walk ended on a continuation node (should be 0) | 0 |
| behind-fallback keys that never match (fallback removed) | 0 |
| unqualified stop/give_way nodes narrowed to the nearer junction/direction | 46 |
| distinct (junction, way, dir) keys suppressed (matched a real junction approach) | 17363 |
| ... of which controlled by unqualified stop/give_way nodes | 302 |
| events whose attributed key matched a real approach (actually suppressed) | 18158 |
| events with a key that matched no approach (residual double counting) | 202 |
| ... unmatched: junction node carries its own explicit sign for that direction (two signs, both counted) | 198 |
| ... unmatched: walk entered a one-way way against its direction | 4 |

**Suppressed share** = events whose junction approach is actually suppressed / all approach events = 18158/19596 = 92.7% (standalone events are 6.3% of events and unmatched keys 1.0%).

traffic_calming on road ways (top 8): table=1339, island=1128, choker=961, bump=643, hump=300, chicane=197, cushion=144, no=30

barrier on road ways (top 8): gate=11242, bollard=2118, lift_gate=1820, swing_gate=557, kerb=220, cycle_barrier=174, block=164, yes=70

### Junction nodes and density by highway class

Junction = node shared by >= 2 distinct road-cycling ways. 'Present' = junctions where the class meets; density = present / km of that class (km = sum of way lengths).

| class | km | ways | junctions present | per km | as highest | as lowest |
|---|---|---|---|---|---|---|
| trunk | 430 | 1915 | 770 | 1.79 | 770 | 445 |
| primary | 3068 | 16385 | 10468 | 3.41 | 10353 | 1237 |
| secondary | 6751 | 36188 | 26691 | 3.95 | 25648 | 3692 |
| tertiary | 5193 | 25911 | 22645 | 4.36 | 19913 | 4006 |
| unclassified | 6064 | 15073 | 15965 | 2.63 | 12703 | 4838 |
| residential | 17508 | 123218 | 114698 | 6.55 | 83985 | 78564 |
| living_street | 891 | 8117 | 9037 | 10.15 | 4555 | 7673 |
| service | 10464 | 91024 | 87443 | 8.36 | 29971 | 87443 |
| ALL | 50368 | 317831 | 187898 | 3.73 | | |

Junction nodes: 313542 shared by >= 2 ways, of which 125644 are plain splits (exactly 2 ways of the same class, end vertex of both) and are excluded from the table above, leaving 187898. Density of ALL nodes shared by >= 2 ways (splits kept): 6.23/km. Way classes include `*_link` ways under their parent's class.


#### Junction nodes by (highest class, lowest class) meeting

| highest \ lowest | trunk | primary | secondary | tertiary | unclassified | residential | living_street | service |
|---|---|---|---|---|---|---|---|---|
| trunk | 445 | 72 | 77 | 76 | 25 | 15 | 0 | 60 |
| primary | 0 | 1165 | 781 | 710 | 587 | 3887 | 95 | 3128 |
| secondary | 0 | 0 | 2834 | 1490 | 1276 | 10791 | 385 | 8872 |
| tertiary | 0 | 0 | 0 | 1730 | 1001 | 9933 | 444 | 6805 |
| unclassified | 0 | 0 | 0 | 0 | 1949 | 5165 | 118 | 5471 |
| residential | 0 | 0 | 0 | 0 | 0 | 48773 | 3298 | 31914 |
| living_street | 0 | 0 | 0 | 0 | 0 | 0 | 3333 | 1222 |
| service | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 29971 |

### Expected stops/km per way, Wicklow bbox (lon 12.908..13.76, lat 52.297..52.746)

156133 ways (selected by mid-vertex in bbox); sample CSV `data/samples/stops_per_km_berlin.csv` has 55946 ways (service ways and ways < 50 m dropped; the full set is `data/osm/stops_per_km_berlin_full.csv`, gitignored). All tables below use all 156133 ways. Statistics over (way, travel direction) samples for ways >= 0.1 km; 'pooled' = sum stops / sum km over all ways of the class.

| class | ways | km | median stops/km | p90 stops/km | pooled stops/km | share of ways with 0 stops |
|---|---|---|---|---|---|---|
| trunk | 882 | 176 | 0.00 | 4.06 | 1.60 | 51% |
| primary | 6666 | 546 | 0.00 | 10.72 | 6.78 | 52% |
| secondary | 19829 | 1556 | 0.00 | 7.86 | 5.61 | 56% |
| tertiary | 14413 | 1232 | 0.00 | 4.76 | 4.43 | 52% |
| unclassified | 3395 | 526 | 0.00 | 4.19 | 1.78 | 61% |
| residential | 68321 | 6844 | 2.85 | 6.22 | 4.12 | 26% |
| living_street | 5068 | 499 | 4.37 | 9.67 | 5.58 | 21% |
| service | 37559 | 3366 | 3.61 | 9.44 | 5.85 | 28% |

Breakdown of expected stops by cause in bbox (sum over travel directions; per-direction km pooled):

| cause | events | per km |
|---|---|---|
| signal | 9091 | 0.332 |
| stop | 786 | 0.029 |
| give_way | 6320 | 0.231 |
| yield_infer | 31050 | 1.133 |
| yield_equal | 65348 | 2.384 |
| rb_entry | 638 | 0.023 |
| xing_signal | 15690 | 0.572 |

Pedestrian crossing nodes (no signals) on bbox road ways, not in estimate: 43740.

### 20 longest stretches with < 0.2 expected stops/km (Wicklow bbox)

Stretch = connected chain of ways with the same `name` (or `ref` when unnamed) joined at way end-vertices (unnamed ways are single-way stretches). Rate = direction-averaged expected stops / total length (a stretch is not oriented, so fwd/bwd are averaged per way).

| # | name | main class | length km | ways | exp. stops | stops/km | first way id |
|---|---|---|---|---|---|---|---|
| 1 | L 211 | secondary | 5.4 | 4 | 0.0 | 0.00 | 44804004 |
| 2 | K 6502 | tertiary | 4.2 | 4 | 0.5 | 0.12 | 333896136 |
| 3 | Straße nach Sacrow | unclassified | 3.8 | 7 | 0.8 | 0.20 | 79565568 |
| 4 | K 7241 | tertiary | 3.5 | 4 | 0.5 | 0.14 | 34293113 |
| 5 | Straße zur L76 | unclassified | 3.4 | 3 | 0.5 | 0.14 | 66983506 |
| 6 | L 30 | secondary | 3.4 | 2 | 0.0 | 0.00 | 46618194 |
| 7 | Willmersdorfer Landstraße | secondary | 3.4 | 1 | 0.2 | 0.07 | 522462741 |
| 8 | Schwarzer Weg | service | 3.3 | 6 | 0.0 | 0.00 | 7947348 |
| 9 | Bernauer Damm | tertiary | 3.0 | 2 | 0.5 | 0.16 | 5399931 |
| 10 | LPG-Straße | unclassified | 3.0 | 3 | 0.5 | 0.17 | 337876036 |
| 11 | L 292 | secondary | 2.9 | 3 | 0.2 | 0.09 | 27567574 |
| 12 | Kastanienstraße | tertiary | 2.7 | 1 | 0.2 | 0.09 | 6573860 |
| 13 | Elisenauer Straße | secondary | 2.6 | 8 | 0.5 | 0.19 | 5563314 |
| 14 | Straße zum Müggelhort | residential | 2.6 | 5 | 0.5 | 0.19 | 24205285 |
| 15 | Summter Chaussee | secondary | 2.6 | 3 | 0.5 | 0.19 | 46933221 |
| 16 | L 29 | secondary | 2.6 | 3 | 0.5 | 0.20 | 6573865 |
| 17 | L 200 | secondary | 2.5 | 1 | 0.0 | 0.00 | 722296485 |
| 18 | L 292 | secondary | 2.5 | 1 | 0.0 | 0.00 | 417092738 |
| 19 | L 292 | secondary | 2.4 | 1 | 0.0 | 0.00 | 5399870 |
| 20 | Schwielowseestraße | tertiary | 2.3 | 1 | 0.2 | 0.11 | 39486744 |
