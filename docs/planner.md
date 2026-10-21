# Flow route planner

## What it does

Pick a start and an end in Ireland (click the map or search by name) and the planner returns a handful of cycling routes ranked by how few times you are expected to stop (traffic signals, give-way and stop signs, junction priorities), with distance, ascent, expected stops and expected stopped time for each, the stop locations on the map, and a GPX download per route.

## Quick start

Two terminals, both from the repo root. Data (`data/osm/ireland.osm.pbf`, `data/osm/events_ireland.csv`) must already be present.

```bash
make planner-setup   # once: downloads BRouter + tiles into data/brouter/, builds data/flow/ireland.index.csv (idempotent)
make brouter         # terminal 1, foreground: BRouter on http://localhost:17777
make planner         # terminal 2, foreground: planner on http://localhost:8081
```

Open http://localhost:8081. Stop each server with Ctrl-C. `make planner-check` runs pytest, ruff and the UI syntax check (`make ui-check`).

## Architecture

1. `web/index.html` (Leaflet, served by the planner at `/`) calls `GET /api/route`.
2. `scripts/flow_server.py` (FastAPI) asks BRouter for candidates: 4 variants x 4 alternatives = 16 requests. Variants: profile `fastbike`, and profile `flow` (`profiles/flow.brf`) at `profile:flow_scale` 0.5 (flow_lo), 1 (flow) and 2 (flow_hi); `alternativeidx` 0-3 for each.
3. Near-duplicates are removed (within 20 m of each other over 90 % of the length).
4. Each surviving candidate is scored outside BRouter: its geometry is matched to the flow index (`data/flow/ireland.index.csv`, directional stop events) and the stop model gives expected stops, stops per km and expected stopped seconds.
5. Ranking: fewest expected stops first (ties: shorter first). Candidates longer than 1.3x the shortest candidate are dropped, unless that would leave fewer than 3, in which case the guard is ignored. The top `n` (1-6, default 4) are returned, each with its delta against the fastbike alternative 0.

## The stop model

`data/model/stop_model.json` holds a per-class stop probability p (applied per arrival at a junction event) and mean stop duration, in three weight sets:

| set | what it is |
|---|---|
| `prior` (default) | literature-based: signals about 0.40 (red share), yield classes from a gap-acceptance model by road class. See `docs/research/stop-priors-open-data.md` |
| `combined` | measured on Eric's Ireland + Berlin rides (`docs/research/stop-model-validation.md`; signals 0.158) |
| `ireland` | measured on the Ireland rides only (signals 0.103) |

The default is `prior`; the verdict is in `docs/research/stop-priors-open-data.md`. Switch with the environment variable, e.g. `FLOW_WEIGHTS=combined make planner`. The active set is shown in the page footer and in `weight_set` of the API responses.

Classes, in precedence order: signal, stop, give_way, rb_entry, xing_signal, yield_infer, yield_equal. When several events fire for the same arrival (same node, way and direction) only the highest-precedence one is kept.

### Router and scorer use the same table

By default (`router=base`) the server derives BRouter's node costs from the BASE weight set only (the `weights=` choice, ignoring `blend_with`/`blend` and `p_<cause>` overrides) with `StopModel.brouter_costs(anchor=300)`: `cost(class) = 300 x (p x mean_stop_s) / (p_signal x mean_stop_s_signal)`, the weight formula of `docs/research/stop-model-validation.md` (without its mid-way background subtraction), clamped to 0..1000 and rounded. Signals are the anchor (always 300). The six values are sent to every flow variant as `profile:cost_signal`, `cost_xing_signal`, `cost_give_way`, `cost_stop`, `cost_mini_rb` and `cost_rb_entry` (`rb_entry` feeds both roundabout variables); the fastbike baseline is untouched. In `profiles/flow.brf` the defaults (300/300/80/60/80/150) reproduce the pre-emq.16 routes byte for byte; node costs are still multiplied by `flow_scale`, `cost_rb_entry` is not. With `router=table` (opt-in; the UI checkbox 'Router follows sliders') the costs come from the effective table instead (after weights, blend and per-class overrides), so router and scorer are fully consistent. Cache implication: the costs are part of the candidate cache key. Under `router=base` blend and slider moves leave the costs unchanged, so they hit the cache and re-rank instantly (scoring still uses the effective model); only a different `weights=` set or different `scales` re-routes (5-8 s). Under `router=table` any change that moves a rounded cost re-routes. The mode and the costs actually sent are echoed in `settings.router` and `settings.brouter_costs`.

## What it does not use

- Eric's ride files are not read at run time. They were used once, offline, to derive the `combined` and `ireland` sets; the default `prior` set does not depend on them, and the empirical sets are optional.
- Motor traffic volumes, speeds or time of day.

## Known limits

- The default prior is literature-based, not measured in Ireland.
- The empirical sets come from one rider (81 rides); absolute levels differ 2.5-4x from the prior, which `flow_scale` absorbs.
- No motor traffic in the model.
- Roundabout entries are untuned (0 stops in 22 observed passes).
- `node_snap` (matching a route to index nodes) assumes the geometry is BRouter's, i.e. points sit on OSM node positions.
- Latency is dominated by the 16 BRouter calls: about 1-3 s for short rural pairs and up to 12-15 s for 30-40 km pairs. Measured over the 10 eval pairs (tv5), total wall time and skipped requests: server 2 threads / 2 client workers 144 s, 0 skipped; server 4 / client 2 156 s, 0 skipped; server 4 / client 4 81-85 s (two runs), 0 skipped (the old combination, server 2 / client 4, skipped 10-13 of 16 on long pairs). BRouter RSS (-Xmx1g) was ~1.0 GB with 2 threads and 0.65-1.2 GB with 4, so the heap cap was kept.
- `/api/health` calls BRouter live on every request.
- Ireland only (bbox lon -10.7..-5.4, lat 51.3..55.5); the BRouter tiles are W10_N50 and W10_N55.
- Address search uses public Nominatim from the browser (1 request/s throttle); it can return 429.

## API

`GET /api/health` -> `{brouter: bool, region, index_rows, weight_set, bbox{lon_min,lon_max,lat_min,lat_max}}`.

`GET /api/route?from=lat,lon&to=lat,lon&n=4` (n clamped to 1-6) -> 
- `query` (from, to, n), `weight_set`
- `routes[]`: `rank`, `id`, `variant` (fastbike, flow_lo, flow, flow_hi, flow_lanes), `profile`, `alt`, `geometry` (GeoJSON LineString, [lon, lat]), `stats` {`distance_km`, `ascent_m`, `brouter_time_s`, `expected_stops`, `stops_per_km`, `expected_stop_s`, `by_class`}, `delta_vs_fastest` {`stops`, `km`} or null, `hits[]` {`lat`, `lon`, `cause`, `p`}
- `stats.cycle_km` {`path`, `lane`, `track`, `total_km`}: km on highway=cycleway, on roads with a lane value and on roads with a track value (from BRouter per-segment way tags; track beats lane, path beats both)
- `candidates_total`, `candidates_deduped`, `skipped[]` (BRouter requests that failed, with error), `timings_ms` {`brouter`, `score`, `total`}

Optional model parameters on `/api/route` (all validated; a bad value gives 400 naming the parameter):
- `weights=prior|ireland|combined` (default: the server's model), `blend_with=<set>&blend=<0..1>` (linear blend of p and mean_stop_s from `weights` toward `blend_with`; the two must be given together), `p_<cause>=<0..1>` for any of the seven causes (applied last, after the blend).
- `guard` (distance guard factor, 0 = off, max 3.0, default 1.3), `scales` (comma-separated `flow_scale` values for the flow variants, default `0.5,1,2`; each must be > 0 and <= 10; fastbike is always included), `n`, `refresh=1` (bypass the candidate cache), `router=base|table` (default `base`; which p-table the router's node costs derive from, see 'Router and scorer use the same table'; any other value gives 400).
- `lane_bonus` (0.5..1.0, default 1.0 = off) and `lanes_variant=1`, see 'Preferring cycle infrastructure'.
- The response echoes `settings` (`weights`, `blend_with`, `blend`, `overrides`, `guard`, `scales`, `n`, `router`, `brouter_costs`, `lane_bonus`, `lanes_variant`) and `model` (effective p per cause), plus `cached` (bool). `weight_set` is the effective name (e.g. `blend(prior,ireland,0.50)+custom`).

Candidate cache: an in-process LRU of 32 entries keyed by start and end (rounded to 5 decimals), the `scales` tuple, the BRouter costs actually sent, `lane_bonus` and `lanes_variant`, holding the generated candidates. A hit skips BRouter (`timings_ms.brouter` = 0, `cached` true); scoring and ranking always run with the request's model. Under the default `router=base` the costs come from the base weight set only, so blend, per-class `p_*`, guard and n re-rank instantly, while changing the weight set (or any slider under `router=table`) changes the costs and re-routes. `refresh=1` bypasses and refills the entry. Requests with no kept candidates are not cached.

`GET /api/model` -> `{default_weight_set, precedence, weight_sets: {name: {cause: {p, p_lo, p_hi, mean_stop_s, note}}}, midway_background_p}` straight from `data/model/stop_model.json`.

Errors: 400 bad or out-of-region coordinates or bad model parameters, 404 no route, 503 BRouter unreachable.

Example: `curl 'http://localhost:8081/api/route?from=53.2990,-6.2825&to=53.2210,-6.2150'`

## Preferring cycle infrastructure

`profiles/flow.brf` has a global `lane_bonus` (default 1.0, per-request `&profile:lane_bonus=<x>`). The base per-metre costfactor of a way is multiplied by `lane_factor` = `lane_bonus` when the way is `highway=cycleway` or `hasbikelane` (any of `cycleway`, `cycleway:left/right/both` = lane, track, shared_lane, share_busway, plus opposite_lane/opposite_track where the lookup table allows), else 1.0. Only the base is scaled; the additive oneway/traffic penalties and all node costs are not. At 1.0 routing is byte-identical to before (all 8 sample GPX identical ignoring time/creator).
costfactor >= 1: BRouter neither rejects nor clamps a costfactor below 1 (verified live with a constant 0.5: `CostPerKm` 500 in the response, route cost halved), so the bonus is applied directly and tertiary roads with a lane really drop to 0.8. The theoretical downside is that a costfactor below 1 makes BRouter's air-distance heuristic optimistic, so a result can in principle be marginally non-optimal; the validated band is 0.5..1.0 and the UI offers 0.7..1.0.
Per-metre caution: the bonus scales with distance, not per crossing. 0.8 over 10 km of eligible road saves about 2000 cost units, roughly 7 traffic signals at the 300 anchor, so a Strong setting (0.7) can trade a few signals for a noticeably longer, lane-following route. The distance guard still applies in the ranking.
Tagging caveat: OSM lanes are tagged on only ~8% of Irish tertiary roads (`docs/research/osm-road-network.md`), so the preference only sees tagged infrastructure and `cycle_km` is a lower bound.
API: `lane_bonus` (default 1.0; applied to every flow variant, not fastbike; part of the cache key; echoed in `settings.lane_bonus`), `lanes_variant=1` adds a fifth variant `flow_lanes` (flow_scale 1.0, lane_bonus = min(0.8, requested lane_bonus); label "Flow+lanes"). UI: Settings 'Prefer cycle infrastructure' slider (Off .. Strong = 0.7, step 0.05, re-routes) and 'Add a lanes-favouring route'; hash keys `lb=`, `lv=1`. Cards show km on cycle paths and on roads with lanes/tracks when non-zero.

## Regenerating the data

Events table (all of Ireland; slow, run once; the command is from the docstring of `scripts/score_route_stops.py` with the Ireland bbox):

```bash
uv run scripts/osm_stop_features.py data/osm/ireland.osm.pbf --bbox=-10.7,51.3,-5.4,55.5 \
  --csv /tmp/s.csv --full-csv /tmp/f.csv --signals /tmp/sig.csv --causes-csv data/osm/events_ireland.csv
make flow-index      # data/osm/events_ireland.csv + ireland.osm.pbf -> data/flow/ireland.index.csv
```

## Troubleshooting

- BRouter down: `/api/route` returns 503 and the footer says BRouter DOWN. Start `make brouter` in another terminal.
- Point outside the BRouter tiles or outside Ireland: 400 from the planner, or a BRouter error such as "datafile ... not found" listed under `skipped` / in a 404 detail.
- Nominatim 429: the search box shows "rate-limited"; wait a moment. Clicking the map or typing `lat,lon` needs no search.
- Port in use: `make planner` fails with "address already in use". Stop the old process (`pgrep -fl flow_server`) or run `uv run scripts/flow_server.py --port 8082`. BRouter listens on 17777.

## Planner evaluation (emq.10, 2026-10-21)

Ten fixed OD pairs (`data/samples/planner_od_pairs.csv`: 4 suburban, 3 Wicklow rural, 3 cross-town), each run through generate -> score -> rank (n=4) by `uv run scripts/planner_eval.py` against a local BRouter. Weight set: `prior` (default). Full rows: `data/samples/planner_eval.csv`. "fastbike" is the fastbike alt-0 candidate (kept whenever its request succeeds; it did for all pairs); "top" is rank 1. Deltas are top vs fastbike, negative = fewer stops.

| pair | fastbike km | fastbike stops | top (variant/alt) | top km | top stops | d stops % | d km % | cands kept/total | wall s |
|---|---|---|---|---|---|---|---|---|---|
| rathfarnham_howth | 21.27 | 36.65 | flow_hi/0 | 24.9 | 6.76 | -81.6 | 17.1 | 16/16 | 11.69 |
| dundrum_phoenixpark | 12.27 | 15.2 | flow_hi/0 | 15.27 | 6.22 | -59.1 | 24.5 | 15/16 | 9.04 |
| blanchardstown_sandymount | 14.95 | 21.83 | flow/0 | 15.54 | 3.46 | -84.2 | 3.9 | 14/16 | 6.98 |
| tallaght_malahide | 27.04 | 40.67 | flow_hi/2 | 32.53 | 15.34 | -62.3 | 20.3 | 14/16 | 14.35 |
| bray_wicklowgap | 41.43 | 5.55 | flow/0 | 42.54 | 1.75 | -68.5 | 2.7 | 9/16 | 4.91 |
| greystones_roundwood | 18.75 | 4.84 | fastbike/3 | 21.71 | 1.65 | -65.9 | 15.8 | 11/16 | 0.8 |
| enniskerry_sallygap | 18.39 | 0.72 | fastbike/2 | 20.28 | 0.33 | -54.2 | 10.3 | 4/16 | 0.98 |
| dunlaoghaire_clontarf | 14.73 | 17.11 | flow_hi/2 | 16.49 | 4.65 | -72.8 | 11.9 | 13/16 | 3.91 |
| lucan_dalkey | 29.41 | 38.68 | flow_hi/3 | 34.02 | 8.57 | -77.8 | 15.7 | 16/16 | 13.28 |
| swords_bray | 35.38 | 41.11 | flow/0 | 42.22 | 19.49 | -52.6 | 19.3 | 15/16 | 14.58 |

- Mean delta stops: -67.9 %, median -67.2 %. Mean delta distance: +14.2 %.
- Pairs where the top route is the fastbike alt-0 route: 0 of 10. (In greystones_roundwood and enniskerry_sallygap the top is fastbike alt 2/3, a different road than alt 0.)
- No pair errors, no skipped BRouter requests. Re-run in tv5 with the final defaults (4 server threads, 4 client workers) after correcting the end points of bray_wicklowgap (now 53.0270,-6.4100, was 53.0120,-6.3990, ~1.8 km off the R756 summit) and enniskerry_sallygap (now 53.1370,-6.3140, was 53.1013,-6.3010, ~4 km south of the R759/R115 crossroads); other coordinates routed as given.
- `combined` weights (`data/samples/planner_eval_combined.csv`): mean delta stops -74.8 %, median -73.4 %, mean delta distance +12.1 %; the rank-1 candidate is the same as under `prior` in 9 of 10 pairs (greystones_roundwood differs), so the ranking is not sensitive to the weight set, only the absolute percentages are.

Interpretation: in the suburbs and cross-town the planner finds large cuts (50-85 % fewer expected stops) for 4-24 % more distance, because fastbike goes straight through signalled junctions that the flow profile detours around. In rural Wicklow the absolute gain is small (fastbike already has 0.03-0.26 stops/km, e.g. 0.72 expected stops over 25 km for enniskerry_sallygap), so the large percentage is a small number of stops and the planner adds little in practice there. These are model-predicted stops from the stop model, not measured rides, and the `prior` percentages depend on its signal probability of 0.40.

Caveat found while evaluating (fixed in tv5): `run_brouter.sh serve` used 2 server threads while the planner requests candidates with 4 client threads; on 20-50 km pairs BRouter's "thread-priority-watchdog" killed queued requests (10-13 of 16 skipped in a first run with 4 workers). The server now runs 4 threads (`THREADS` in `run_brouter.sh`), matching `DEFAULT_WORKERS = 4` in `flowplan/candidates.py` (used by `flow_server.py` and `planner_eval.py`). Keep client workers <= server threads. `flow_server` logs a WARNING for every skipped request.

## Cycle infrastructure overlay

`make cycle-overlay` (`scripts/build_cycle_overlay.py`, ~40 s from `data/osm/ireland.osm.pbf`) writes `web/data/cycle_dublin_wicklow.geojson` (bbox -6.6,52.95,-6.0,53.4, 2.86 MB, committed): 5669 cycleway paths (597.3 km), 3165 road ways with cycle lanes (260.4 km), 2239 with tracks (229.0 km; `track`, `opposite_track`, `separate`).
The Layers control (top right) toggles "Cycle paths" (green) and "Roads with cycle lanes/tracks" (blue, dashed = lane, solid = track); both are off by default, lazy-loaded on first enable, click shows raw OSM tags, toggle state in localStorage. Cycle route relations are not included.
Caveat: OSM lanes are tagged on only ~8% of Irish tertiary roads (`docs/research/osm-road-network.md`), so a missing lane on the map does not mean there is none.
