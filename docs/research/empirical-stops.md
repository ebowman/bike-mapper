# Empirical stop events: Eric's ride history vs OSM public timestamped traces

## Question

Where do cyclists actually stop? Derive observed stop events from ride GPS, attach them to OSM
nodes/ways, and judge whether the resulting data can validate the OSM-based stop estimate
(dhy.10 -> dhy.11). Two sources are tested: (A) Eric's own Garmin history (dhy.12) and (B) the
public OSM GPS traces that carry timestamps; (C) is documented only.

**Stop event definition** (parameters are CLI flags of `scripts/stop_events.py`, defaults shown):

| kind | rule |
|---|---|
| `slow` | speed < `--speed-thr` 1.0 m/s sustained >= `--min-stop-s` 3 s. Recorded speed if present (FIT), else haversine/dt smoothed over 3 points (GPX/TCX/OSM) |
| `pause` | recording gap > `--gap-s` 2 s bracketed by FIT `event` timer `stop_all`/`stop` ... `start` messages (Edge auto-pause), or a timer stop->start pair > 2 s; duration = the gap |
| `gap` | unbracketed gap in (2 s, `--data-gap-s` 30 s] on a regularly recorded FIT file (not used for OSM traces, where sparse sampling is normal) |
| data gap (not a stop) | unbracketed gap > 30 s, or any gap whose ends are > `--gap-max-disp` 100 m apart (the rider moved while not recording); counted separately |
| `rest` | any event longer than `--max-stop-s` 300 s (cafe, puncture, photo): reported, excluded from node/way stop statistics |

Events < `--merge-s` 10 s apart are merged (kind priority pause > gap > slow); events within
`--end-margin-m` 200 m of ride start/end are discarded. This supersedes the bead's "gap > 30 s =
auto-pause" rule, because the Edge 840 records auto-pause as gaps bracketed by timer events.
**Snapping:** each trackpoint/stop is snapped to the nearest OSM `highway` way segment within
`--snap-m` 20 m (shapely STRtree, EPSG:2157, helper `scripts/snap.py`) and attached to the nearer
end node of that segment. A **pass** of node N = one ride/trace with a point snapped to a segment
whose nearer end is N and within `--node-radius` 30 m of it (counted once per ride, not per
point); a stop is attached to a node by the same rule. p(stop) = stop events at N / passes of N.

## Sources evaluated

| name | URL | license | access method | coverage | resolution/granularity | cost |
|------|-----|---------|---------------|----------|------------------------|------|
| A. Eric's Garmin Connect history | see `docs/research/ride-data-acquisition.md` | own data (acquisition terms discussed there) | original FIT files in `data/rides/` (gitignored) via dhy.12 | 86 outdoor rides, 3 720 km, 2020-11..2026-10; 81 usable after cleaning; only 31 rides / 1 128 km inside the Ireland extract | 1 s records with speed + position (Edge 840) | free |
| B. OSM public GPS traces | https://api.openstreetmap.org/api/0.6/trackpoints?bbox=-6.5,53.0,-6.1,53.3&page=N (docs: https://wiki.openstreetmap.org/wiki/API_v0.6#GPS_traces) | traces stay the uploader's content, shared at the uploader's chosen visibility (https://wiki.openstreetmap.org/wiki/Visibility_of_GPS_traces); they are not ODbL map data. Raw GPX stays in gitignored `data/gps/`; only aggregated per-node counts are committed | `curl` with UA `bike-mapper-research/0.1 (ebowman@boboco.ie)`, 5 000 points/page, >= 1.1 s between calls (python `requests` is answered 429 by the OSM CDN; curl is not) | Wicklow/south Dublin bbox; 60 pages x 5 000 pts = 300 000 pts, **not exhausted** (page cap hit) | 2-6 s sampling typical, timestamps on every returned point | free |
| C1. Strava API v3 streams | https://developers.strava.com/docs/reference/#api-Streams-getActivityStreams (`keys=time,latlng,velocity_smooth,moving`) | Strava API Agreement https://www.strava.com/legal/api : "Strava Data provided by a specific user can only be displayed or disclosed in your Developer Application to that user. Strava Data related to other users, even if such data is publicly viewable on the Strava Platform, may not be displayed or disclosed." plus a ban on competing/replicating applications | OAuth per athlete; usable for one's **own** activities only; rate limits (docs https://developers.strava.com/docs/rate-limits/, quoted from memory, re-check): 200 req/15 min and 2 000/day overall, 100/15 min and 1 000/day for non-upload calls | own activities only; **not usable** for other users' data in a routing product | 1 Hz `velocity_smooth`/`moving` | free |
| C2. Ride with GPS export | https://ridewithgps.com/ (trip page "Export" -> GPX / TCX / FIT, also `/trips/<id>.gpx`) | per-user ToS; public trips are not licensed for reuse (not re-verified) | own trips; per-trip download | own | GPX/TCX track points, timestamps only if recorded rather than planned | free |
| C3. Komoot export | https://www.komoot.com/ (tour page -> "Export GPX") | per-user ToS (not re-verified) | own tours; GPX only | own | GPX; recorded tours carry timestamps | free (some exports need a purchased region/premium) |

## Hands-on check

**Reproduce.**
```
uv run scripts/stop_events.py --selftest                       # synthetic GPX/TCX/auto-pause checks
uv run scripts/stop_events.py --source eric                    # ~3.5 min (FIT parse + cached network)
uv run scripts/fetch_osm_traces.py                             # 60 pages, ~7 min
uv run scripts/stop_events.py --source osm                     # ~5 min first run (network cached in data/cache/)
uv run scripts/stop_events.py --source osm --min-median-speed 3.0 --tag _cyclingpace
```
Outputs: `data/samples/observed_stops_eric.csv`, `observed_ways_eric.csv`, `observed_stops_osm.csv`,
`observed_stops_osm_cyclingpace.csv` (columns node_id, lat, lon, passes, stops, probability,
mean_stop_s; all < 1 MB, no passes filter was needed for Eric, OSM default drops passes < 2),
plus the per-run markdown reports `data/samples/empirical_stops_*.md`.

### Source A: Eric's rides

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

Notes on source A:
- **Geography matters more than the brief assumed.** Of 81 usable rides only 31 (1 128 km, almost
  all Edge 840, Dublin area plus one north-west ride) fall in the Ireland extract; 50 rides (2 402 km: about 30 around Berlin/Brandenburg,
  plus Slovenia, Greece, southern France, Netherlands, UK) cannot be snapped to `ireland.osm.pbf`.
  Their stop events are detected and counted above, not attached to nodes.
- **Auto-pause is on for the Berlin rides and off for the Irish ones**: 889 `pause` events on
  rides outside Ireland versus 0 on Irish rides (Irish stops appear as `slow` runs of near-zero
  speed). Both detection paths therefore matter; neither alone would work for the full history.
- De-duplication (start +-60 s and distance +-2 %) found **no** duplicates: the third-party
  re-uploads start minutes apart. Extension used: time spans overlap > 50 % of the shorter ride and
  distance within 10 % -> dropped 20271116194 (dup of 20030354929). The earlier note's "5 duplicates
  of Edge rides" does not hold: all third-party files are from Slovenia/Greece/Berlin/Netherlands where
  there is no Edge copy. 20030311998 / 20271112561 (Greece, starts 23 min apart, 27 vs 25 km) were
  kept as separate rides.
- Dropped files: 20030508907, 20070525554 (no records), 24428644818 (9-s accidental start, no
  position), 20271114668 (smart recording, median dt 3 s), 20271116194 (duplicate).
- 'Stops at nodes' counts are low in absolute terms: 90 of the 2 437 nodes with >= 5 passes
  have even one stop; the 5-pass nodes are mostly bends/mid-way vertices (only 973 are junctions
  or tagged), because every OSM vertex along a repeated route accumulates passes.

### Source B: OSM public traces (spec filters: exclude median > 12 m/s and motorway/trunk)

Pages loaded: 60; trackpoints 300000, with <time> 300000 (100.0 %); trkseg 293, with time 293 (100.0 %); distinct timestamped traces (merged across pages by URL, >= 5 pts) 231
Traces analysed 231; excluded: median speed > 12.0 m/s: 54; > 50 % of snapped points on motorway/trunk: 4 -> excluded share 25.1 % of traces; trackpoint share 39.9 %; km before exclusion 1846
Kept traces with median speed < 2.5 m/s (walking pace, not excluded): 107
Trace length: median 424 points, median sample interval 4.0 s
Traces/rides in node statistics: 173; data-gap counters: datagap_moved=1154, datagap_unbracketed=2326, discarded_end_margin=566
CSV observed_stops_osm.csv: 7963 of 26082 nodes written (min passes 2); size 328245 bytes

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
| stop events attached to a node (<= 30 m) | 2625 |

Top 20 nodes by stop count (>= 5 passes):

| node | lat,lon | passes | stops | p(stop) | mean stop s | what is there (OSM) |
|---|---|---|---|---|---|---|
| 5343217693 | 53.00366,-6.31350 | 9 | 6 | 0.67 | 16 | nothing tagged (mid-way / bend) |
| 3214273969 | 53.00606,-6.36726 | 8 | 5 | 0.62 | 41 | nothing tagged (mid-way / bend) |
| 392347313 | 53.00625,-6.38057 | 8 | 5 | 0.62 | 23 | nothing tagged (mid-way / bend) |
| 4300127696 | 53.00414,-6.39448 | 7 | 5 | 0.71 | 118 | nothing tagged (mid-way / bend) |
| 9895135759 | 53.00125,-6.34790 | 5 | 5 | 1.00 | 15 | nothing tagged (mid-way / bend) |
| 4226869493 | 53.24584,-6.24007 | 5 | 5 | 1.00 | 9 | nothing tagged (mid-way / bend) |
| 1563577432 | 53.24405,-6.24151 | 5 | 5 | 1.00 | 50 | nothing tagged (mid-way / bend) |
| 1839668668 | 53.25115,-6.24029 | 5 | 5 | 1.00 | 58 | nothing tagged (mid-way / bend) |
| 531324920 | 53.24542,-6.24042 | 5 | 5 | 1.00 | 13 | junction of path ways |
| 2473036819 | 53.00639,-6.38729 | 8 | 4 | 0.50 | 44 | nothing tagged (mid-way / bend) |
| 2473036832 | 53.00658,-6.38396 | 8 | 4 | 0.50 | 69 | nothing tagged (mid-way / bend) |
| 564806176 | 53.00528,-6.31472 | 8 | 4 | 0.50 | 14 | nothing tagged (mid-way / bend) |
| 392347281 | 53.00651,-6.38579 | 7 | 4 | 0.57 | 27 | nothing tagged (mid-way / bend) |
| 3206330666 | 53.00864,-6.33296 | 6 | 4 | 0.67 | 16 | nothing tagged (mid-way / bend) |
| 392346855 | 53.00028,-6.37356 | 6 | 4 | 0.67 | 99 | nothing tagged (mid-way / bend) |
| 564806057 | 53.00572,-6.31985 | 6 | 4 | 0.67 | 26 | nothing tagged (mid-way / bend) |
| 7630354973 | 53.00133,-6.35234 | 5 | 4 | 0.80 | 14 | nothing tagged (mid-way / bend) |
| 302901688 | 53.24941,-6.23946 | 5 | 4 | 0.80 | 14 | nothing tagged (mid-way / bend) |
| 302901691 | 53.24991,-6.23994 | 5 | 4 | 0.80 | 30 | nothing tagged (mid-way / bend) |
| 3214274195 | 53.00608,-6.36638 | 8 | 3 | 0.38 | 35 | nothing tagged (mid-way / bend) |

**Cycling-pace-only variant** (`--min-median-speed 3.0`, i.e. additionally dropping walkers):

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

Notes on source B:
- **Timestamp share is 100 %** (300 000 / 300 000 points, 293 / 293 segments): the
  `trackpoints` endpoint only returned traces that carry `<time>` in these 60 pages (153 distinct
  trace URLs from 25 uploaders; upload dates 2000-07 to 2026-10, 2 399 of the points from 2026-10).
  The page cap (60) was reached, so total supply in the bbox is higher than what is analysed here.
- Contamination: 54 traces with median speed > 12 m/s (cars/trains) and 4 mostly on motorway/trunk
  are excluded (25.1 % of traces, 39.9 % of trackpoints). Of the 173 kept, 107 have median speed
  < 2.5 m/s, i.e. **walkers/hikers** (Wicklow trails) -- the "top stop nodes" in the spec-filtered
  table are hiking-path rest points, not cycling stops (every "nothing tagged" entry). Only 56
  traces (316 km) are at cycling pace.
- Unbracketed gaps > 30 s are frequent (2 326) and gap-moved events 1 154: phone traces drop out often.
- Python `requests` gets HTTP 429 from the OSM CDN even at one request; `curl` works.

### Source C

Documented only (table above); nothing pulled.

## Verdict

**Usable with caveats for validation; not usable as a public substitute.**
(a) *Is Eric's history big enough to validate a stop model?* Only marginally, and only for
Dublin/Wicklow. Total usable history is 81 rides / 3 530 km, but just **31 rides / 1 128 km**
snap to the Ireland extract, giving **2 437 nodes with >= 5 passes** (914 with >= 10; 973 of the
5-pass nodes are junctions or tagged), **312 stop events** (+17 `rest` events) and only **90
nodes with >= 5 passes and >= 1 stop**. That is enough to compare mean stop probability between
broad feature classes (signals vs crossings vs untagged junctions) but too thin for per-node
calibration or for rare causes (stop signs, give-ways). Adding the 2 402 km of Berlin/other
rides would roughly triple km but needs a Berlin-Brandenburg (and other) OSM extract; that is the
cheapest way to enlarge source A.
(b) *Is OSM timestamped trace density enough as a public substitute?* No. All 300 000 returned
points have timestamps, but they are 231 traces / 1 846 km before filtering, 40 % of the points
are cars/trains/motorways, and most of the rest is walking pace; only **56 traces / 316 km**
are cycling-pace, giving **18 nodes with >= 5 passes and zero stops** among them (max 9 passes at
any node). Even spec-filtered (173 traces, 1 140 km) only 99 nodes with >= 5 passes are junctions
or tagged, and the stop statistics there are dominated by walkers. The bbox has ~25 uploaders; a
60-page cap was hit, but the density per km of road is far below what node-level probabilities need.
(c) *Best realistic non-personal source:* none of the public timestamped GPS sources is adequate
on its own. The realistic routes are (1) more personal/consented data (Eric's other regions with
matching OSM extracts; friends' Garmin/Strava account exports via the official bulk export, with
consent), then (2) infrastructure-side signal data (DCC signal sites / SCATS, see `data/samples/scats_recall_dublin.md`) as the prior. Strava API data cannot be used for other users' data per its API
Agreement; Strava Metro / Garmin Connect aggregates were not evaluated here.

## Open questions for Eric

- Do you want the Berlin-Brandenburg (and Slovenia/Greece/France) Geofabrik extracts loaded so the
  other 2 402 km of rides can validate the stop model (the code is region-agnostic via `--pbf`)?
- Did you turn Edge auto-pause off in Ireland on purpose (Irish rides: 0 pause events; Berlin: 889)?
- Are you OK with `rest` (> 5 min) events being excluded from the stop statistics, or should a different
  cut-off be used?
- Can you export rides from a few cycling friends (official Strava/Garmin bulk export, with consent)
  to enlarge the Dublin sample?
