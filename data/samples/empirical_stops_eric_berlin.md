### Source A (Eric)

Files 86; used 32 inside the extract bbox; dropped 5: 20030508907 (no position records (empty / indoor)); 20070525554 (no position records (empty / indoor)); 20271114668 (smart recording (median dt 3.0s)); 24428644818 (no position records (empty / indoor)); 20271116194 (duplicate of 20030354929)
Outside the extract (stop events counted, not snapped): 49 rides, 2040 km
Unsnapped (outside extract) by country: France: 4 rides, 387 km; Greece: 6 rides, 208 km; Ireland: 31 rides, 1128 km; Netherlands: 2 rides, 10 km; Slovenia: 4 rides, 237 km; UK (GB): 2 rides, 70 km
Traces/rides in node statistics: 32; data-gap counters: datagap_moved=5, discarded_end_margin=42
Stop events on rides outside the extract: gap=43, pause=254, rest=71, slow=347
CSV observed_stops_eric_berlin.csv: 9622 of 38116 nodes written (min passes 2); size 395547 bytes

| stop kind | events | total stopped time (h) | mean (s) |
|---|---|---|---|
| pause | 635 | 5.71 | 32 |
| gap | 4 | 0.02 | 17 |
| slow | 151 | 1.13 | 27 |
| rest | 17 | 2.91 | 616 |
| **all** | 807 | 9.78 | 45 |

| metric | value |
|---|---|
| km ridden (haversine) | 1490 |
| trackpoint snap rate (<= 20 m) | 100.0 % of 224439 |
| stop-event snap rate (excl. rest) | 100.0 % of 790 |
| distinct nodes with >= 1 pass | 38116 |
| nodes with >= 5 passes | 1592 |
| ... of which with >= 1 stop | 99 |
| nodes with >= 5 passes that are junctions (>= 3 segments) or tagged signals/stop/give_way/crossing | 726 |
| nodes with >= 10 passes | 47 |
| stop events attached to a node (<= 30 m) | 781 |
| extra same-ride same-node stops dropped by the one-stop-per-ride-per-node cap | 1 |

Top 20 nodes by stop count (>= 5 passes):

| node | lat,lon | passes | stops | p(stop) | mean stop s | what is there (OSM) |
|---|---|---|---|---|---|---|
| 3832556271 | 52.52390,13.41135 | 7 | 7 | 1.00 | 52 | tagged node: highway=traffic_signals |
| 4911322523 | 52.51186,13.32235 | 9 | 6 | 0.67 | 7 | crossing 8 m away |
| 4911322525 | 52.51174,13.32201 | 8 | 4 | 0.50 | 11 | traffic_signals 2 m away |
| 654381387 | 52.51332,13.32132 | 7 | 4 | 0.57 | 16 | traffic_signals 5 m away |
| 7695908269 | 52.50270,13.44631 | 6 | 4 | 0.67 | 35 | tagged node: highway=traffic_signals |
| 10896082193 | 52.50984,13.28149 | 6 | 4 | 0.67 | 47 | tagged node: highway=traffic_signals |
| 13288280546 | 52.52406,13.41262 | 5 | 4 | 0.80 | 50 | tagged node: highway=traffic_signals |
| 8968763795 | 52.51664,13.38095 | 5 | 4 | 0.80 | 24 | tagged node: highway=traffic_signals |
| 9704988313 | 52.51342,13.33177 | 9 | 3 | 0.33 | 28 | crossing 11 m away |
| 13511691425 | 52.52211,13.37671 | 7 | 3 | 0.43 | 21 | crossing 5 m away |
| 654381281 | 52.51176,13.32195 | 7 | 3 | 0.43 | 18 | traffic_signals 6 m away |
| 10982153275 | 52.51214,13.31725 | 7 | 3 | 0.43 | 23 | crossing 6 m away |
| 10287205930 | 52.51726,13.38895 | 7 | 3 | 0.43 | 25 | crossing 11 m away |
| 3413071793 | 52.51519,13.34889 | 6 | 3 | 0.50 | 29 | traffic_signals 3 m away |
| 10998117512 | 52.52199,13.37637 | 5 | 3 | 0.60 | 19 | crossing 6 m away |
| 4910582854 | 52.51445,13.35175 | 5 | 3 | 0.60 | 4 | traffic_signals 3 m away |
| 9443073374 | 52.52459,13.40793 | 11 | 2 | 0.18 | 11 | tagged node: highway=crossing, crossing=unmarked |
| 779036558 | 52.52319,13.40706 | 10 | 2 | 0.20 | 12 | crossing 21 m away |
| 12889278398 | 52.51300,13.33015 | 9 | 2 | 0.22 | 18 | crossing 8 m away |
| 12862490084 | 52.51110,13.30126 | 8 | 2 | 0.25 | 38 | tagged node: highway=traffic_signals |
