### Source A (Eric)

Files 86; used 31 in Ireland; dropped 5: 20030508907 (no position records (empty / indoor)); 20070525554 (no position records (empty / indoor)); 20271114668 (smart recording (median dt 3.0s)); 24428644818 (no position records (empty / indoor)); 20271116194 (duplicate of 20030354929)
Outside the Ireland extract (stop events counted, not snapped): 50 rides, 2402 km
Traces/rides in node statistics: 31; data-gap counters: datagap_moved=1, discarded_end_margin=69
Stop events on outside-Ireland rides: gap=46, pause=889, rest=71, slow=187
CSV observed_stops_eric.csv: 15176 of 15176 nodes written (min passes 1); size 619963 bytes

| stop kind | events | total stopped time (h) | mean (s) |
|---|---|---|---|
| pause | 0 | 0.00 | - |
| gap | 1 | 0.00 | 7 |
| slow | 311 | 3.35 | 39 |
| rest | 17 | 5.94 | 1259 |
| **all** | 329 | 9.29 | 107 |

| metric | value |
|---|---|
| km ridden (haversine) | 1128 |
| trackpoint snap rate (<= 20 m) | 99.8 % of 202806 |
| stop-event snap rate (excl. rest) | 100.0 % of 312 |
| distinct nodes with >= 1 pass | 15176 |
| nodes with >= 5 passes | 2437 |
| ... of which with >= 1 stop | 90 |
| nodes with >= 5 passes that are junctions (>= 3 segments) or tagged signals/stop/give_way/crossing | 973 |
| nodes with >= 10 passes | 914 |
| stop events attached to a node (<= 30 m) | 311 |

Top 20 nodes by stop count (>= 5 passes):

| node | lat,lon | passes | stops | p(stop) | mean stop s | what is there (OSM) |
|---|---|---|---|---|---|---|
| 219167823 | 53.37104,-6.05575 | 13 | 5 | 0.38 | 54 | nothing tagged (mid-way / bend) |
| 6680343437 | 53.38835,-6.06455 | 7 | 4 | 0.57 | 48 | crossing 2 m away |
| 6649584866 | 53.38934,-6.11001 | 16 | 3 | 0.19 | 9 | tagged node: highway=crossing, crossing=traffic_signals |
| 2469421390 | 53.38878,-6.11739 | 10 | 3 | 0.30 | 28 | crossing 7 m away |
| 2469421307 | 53.36074,-6.18240 | 9 | 3 | 0.33 | 48 | crossing 8 m away |
| 2366009797 | 53.38840,-6.06461 | 8 | 3 | 0.38 | 55 | crossing 7 m away |
| 12193727842 | 53.38878,-6.11735 | 7 | 3 | 0.43 | 20 | crossing 6 m away |
| 255329547 | 53.41758,-6.14296 | 6 | 3 | 0.50 | 30 | traffic_signals 7 m away |
| 686757750 | 53.38933,-6.10999 | 17 | 2 | 0.12 | 50 | crossing 2 m away |
| 6645068947 | 53.37169,-6.08743 | 15 | 2 | 0.13 | 118 | nothing tagged (mid-way / bend) |
| 2469421344 | 53.38878,-6.11751 | 11 | 2 | 0.18 | 144 | traffic_signals 6 m away |
| 11514001162 | 53.36080,-6.18224 | 8 | 2 | 0.25 | 21 | crossing 5 m away |
| 255329546 | 53.41725,-6.14238 | 6 | 2 | 0.33 | 16 | traffic_signals 13 m away |
| 3642841659 | 53.38948,-6.11053 | 6 | 2 | 0.33 | 41 | crossing 7 m away |
| 4090999428 | 53.45404,-6.17112 | 5 | 2 | 0.40 | 16 | nothing tagged (mid-way / bend) |
| 659995687 | 53.45430,-6.17059 | 5 | 2 | 0.40 | 68 | junction footway x tertiary |
| 12382074333 | 53.45212,-6.15379 | 5 | 2 | 0.40 | 10 | tagged node: highway=crossing, crossing=traffic_signals |
| 253242243 | 53.37835,-6.06212 | 5 | 2 | 0.40 | 16 | junction of residential ways |
| 6650776261 | 53.38931,-6.11010 | 5 | 2 | 0.40 | 98 | crossing 7 m away |
| 219156898 | 53.37229,-6.08841 | 23 | 1 | 0.04 | 58 | junction secondary x tertiary |
