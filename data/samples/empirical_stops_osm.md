### Source B (OSM public traces)

Pages loaded: 60; trackpoints 300000, with <time> 300000 (100.0 %); trkseg 293, with time 293 (100.0 %); distinct timestamped traces (merged across pages by URL, >= 5 pts) 231
Traces analysed 231; excluded: median speed > 12.0 m/s: 54; > 50 % of snapped points on motorway/trunk: 4 ; median speed < 0.0 m/s (walking pace, only if flag set): 0 -> excluded share 25.1 % of traces; trackpoint share 39.9 %; km before exclusion 1846
Kept traces with median speed < 2.5 m/s (walking pace, not excluded): 107
Trace length: median 424 points, median sample interval 4.0 s
Traces/rides in node statistics: 173; data-gap counters: datagap_moved=1154, datagap_unbracketed=2326, discarded_end_margin=566
CSV observed_stops_osm.csv: 7963 of 26082 nodes written (min passes 2); size 328250 bytes

| stop kind | events | total stopped time (h) | mean (s) |
|---|---|---|---|
| pause | 0 | 0.00 | - |
| gap | 0 | 0.00 | - |
| slow | 3126 | 33.01 | 38 |
| rest | 113 | 27.54 | 877 |
| **all** | 3239 | 60.55 | 70 |

| metric | value |
|---|---|
| km ridden (haversine) | 1140 |
| trackpoint snap rate (<= 20 m) | 92.5 % of 176618 |
| stop-event snap rate (excl. rest) | 87.7 % of 3126 |
| distinct nodes with >= 1 pass | 26082 |
| nodes with >= 5 passes | 1329 |
| ... of which with >= 1 stop | 410 |
| nodes with >= 5 passes that are junctions (>= 3 segments) or tagged signals/stop/give_way/crossing | 99 |
| nodes with >= 10 passes | 13 |
| stop events attached to a node (<= 30 m) | 2442 |
| extra same-ride same-node stops dropped by the one-stop-per-ride-per-node cap | 183 |

Top 20 nodes by stop count (>= 5 passes):

| node | lat,lon | passes | stops | p(stop) | mean stop s | what is there (OSM) |
|---|---|---|---|---|---|---|
| 4300127696 | 53.00414,-6.39448 | 7 | 5 | 0.71 | 118 | nothing tagged (mid-way / bend) |
| 1563577432 | 53.24405,-6.24151 | 5 | 5 | 1.00 | 50 | nothing tagged (mid-way / bend) |
| 5343217693 | 53.00366,-6.31350 | 9 | 4 | 0.44 | 18 | nothing tagged (mid-way / bend) |
| 2473036819 | 53.00639,-6.38729 | 8 | 4 | 0.50 | 44 | nothing tagged (mid-way / bend) |
| 2473036832 | 53.00658,-6.38396 | 8 | 4 | 0.50 | 69 | nothing tagged (mid-way / bend) |
| 392347313 | 53.00625,-6.38057 | 8 | 4 | 0.50 | 24 | nothing tagged (mid-way / bend) |
| 564806176 | 53.00528,-6.31472 | 8 | 4 | 0.50 | 14 | nothing tagged (mid-way / bend) |
| 392347281 | 53.00651,-6.38579 | 7 | 4 | 0.57 | 27 | nothing tagged (mid-way / bend) |
| 392346855 | 53.00028,-6.37356 | 6 | 4 | 0.67 | 99 | nothing tagged (mid-way / bend) |
| 564806057 | 53.00572,-6.31985 | 6 | 4 | 0.67 | 26 | nothing tagged (mid-way / bend) |
| 9895135759 | 53.00125,-6.34790 | 5 | 4 | 0.80 | 15 | nothing tagged (mid-way / bend) |
| 302901691 | 53.24991,-6.23994 | 5 | 4 | 0.80 | 30 | nothing tagged (mid-way / bend) |
| 1839668668 | 53.25115,-6.24029 | 5 | 4 | 0.80 | 42 | nothing tagged (mid-way / bend) |
| 531324920 | 53.24542,-6.24042 | 5 | 4 | 0.80 | 15 | junction of path ways |
| 3214274195 | 53.00608,-6.36638 | 8 | 3 | 0.38 | 35 | nothing tagged (mid-way / bend) |
| 392347286 | 53.00669,-6.38506 | 8 | 3 | 0.38 | 20 | nothing tagged (mid-way / bend) |
| 297347964 | 53.24795,-6.23839 | 8 | 3 | 0.38 | 93 | nothing tagged (mid-way / bend) |
| 392347094 | 53.00430,-6.39469 | 7 | 3 | 0.43 | 28 | nothing tagged (mid-way / bend) |
| 392347096 | 53.00465,-6.39557 | 7 | 3 | 0.43 | 22 | nothing tagged (mid-way / bend) |
| 392347100 | 53.00593,-6.39743 | 7 | 3 | 0.43 | 21 | nothing tagged (mid-way / bend) |
