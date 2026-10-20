### Source B (OSM public traces)

Pages loaded: 60; trackpoints 300000, with <time> 300000 (100.0 %); trkseg 293, with time 293 (100.0 %); distinct timestamped traces (merged across pages by URL, >= 5 pts) 231
Traces analysed 231; excluded: median speed > 12.0 m/s: 54; > 50 % of snapped points on motorway/trunk: 4 ; median speed < 3.0 m/s (walking pace, only if flag set): 117 -> excluded share 75.8 % of traces; trackpoint share 90.4 %; km before exclusion 1846
Kept traces with median speed < 2.5 m/s (walking pace, not excluded): 0
Trace length: median 130 points, median sample interval 2.0 s
Traces/rides in node statistics: 56; data-gap counters: datagap_moved=1154, datagap_unbracketed=2326, discarded_end_margin=566
CSV observed_stops_osm_cyclingpace.csv: 9367 of 9367 nodes written (min passes 1); size 380823 bytes

| stop kind | events | total stopped time (h) | mean (s) |
|---|---|---|---|
| pause | 0 | 0.00 | - |
| gap | 0 | 0.00 | - |
| slow | 177 | 1.58 | 32 |
| rest | 3 | 0.31 | 377 |
| **all** | 180 | 1.90 | 39 |

| metric | value |
|---|---|
| km ridden (haversine) | 316 |
| trackpoint snap rate (<= 20 m) | 95.6 % of 28294 |
| stop-event snap rate (excl. rest) | 97.2 % of 177 |
| distinct nodes with >= 1 pass | 9367 |
| nodes with >= 5 passes | 18 |
| ... of which with >= 1 stop | 0 |
| nodes with >= 5 passes that are junctions (>= 3 segments) or tagged signals/stop/give_way/crossing | 12 |
| nodes with >= 10 passes | 0 |
| stop events attached to a node (<= 30 m) | 170 |

Top 20 nodes by stop count (>= 5 passes):

| node | lat,lon | passes | stops | p(stop) | mean stop s | what is there (OSM) |
|---|---|---|---|---|---|---|
| 8612020878 | 53.29986,-6.30963 | 9 | 0 | 0.00 | - | tagged node: highway=traffic_signals |
| 1321500978 | 53.29893,-6.30968 | 8 | 0 | 0.00 | - | give_way 11 m away |
| 1321500980 | 53.29824,-6.30962 | 8 | 0 | 0.00 | - | tagged node: highway=crossing, crossing=marked |
| 8253243741 | 53.29652,-6.30936 | 8 | 0 | 0.00 | - | traffic_signals 9 m away |
| 8253243742 | 53.29641,-6.30936 | 8 | 0 | 0.00 | - | crossing 7 m away |
| 27688309 | 53.29619,-6.30926 | 8 | 0 | 0.00 | - | traffic_signals 7 m away |
| 8013965348 | 53.29689,-6.30929 | 7 | 0 | 0.00 | - | nothing tagged (mid-way / bend) |
| 71640133 | 53.29956,-6.30960 | 7 | 0 | 0.00 | - | give_way 6 m away |
| 8612020877 | 53.29919,-6.30969 | 7 | 0 | 0.00 | - | give_way 20 m away |
| 71681140 | 53.29765,-6.30937 | 7 | 0 | 0.00 | - | junction residential x secondary |
| 2484187142 | 53.29902,-6.30969 | 6 | 0 | 0.00 | - | give_way 6 m away |
| 12752847102 | 53.29978,-6.30962 | 6 | 0 | 0.00 | - | tagged node: highway=traffic_signals |
| 4344705731 | 53.23385,-6.23312 | 5 | 0 | 0.00 | - | nothing tagged (mid-way / bend) |
| 81612802 | 53.29825,-6.30944 | 5 | 0 | 0.00 | - | crossing 12 m away |
| 8612706553 | 53.29718,-6.30946 | 5 | 0 | 0.00 | - | junction of footway ways |
| 12285350210 | 53.29920,-6.30966 | 5 | 0 | 0.00 | - | give_way 20 m away |
| 27688311 | 53.29633,-6.30926 | 5 | 0 | 0.00 | - | crossing 9 m away |
| 8612706554 | 53.29808,-6.30955 | 5 | 0 | 0.00 | - | crossing 18 m away |
