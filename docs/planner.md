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

## What it does not use

- Eric's ride files are not read at run time. They were used once, offline, to derive the `combined` and `ireland` sets; the default `prior` set does not depend on them, and the empirical sets are optional.
- Motor traffic volumes, speeds or time of day.

## Known limits

- The default prior is literature-based, not measured in Ireland.
- The empirical sets come from one rider (81 rides); absolute levels differ 2.5-4x from the prior, which `flow_scale` absorbs.
- No motor traffic in the model.
- Roundabout entries are untuned (0 stops in 22 observed passes).
- `node_snap` (matching a route to index nodes) assumes the geometry is BRouter's, i.e. points sit on OSM node positions.
- Latency is 4.5-8 s per request, dominated by the 16 BRouter calls.
- `/api/health` calls BRouter live on every request.
- Ireland only (bbox lon -10.7..-5.4, lat 51.3..55.5); the BRouter tiles are W10_N50 and W10_N55.
- Address search uses public Nominatim from the browser (1 request/s throttle); it can return 429.

## API

`GET /api/health` -> `{brouter: bool, region, index_rows, weight_set, bbox{lon_min,lon_max,lat_min,lat_max}}`.

`GET /api/route?from=lat,lon&to=lat,lon&n=4` (n clamped to 1-6) -> 
- `query` (from, to, n), `weight_set`
- `routes[]`: `rank`, `id`, `variant` (fastbike, flow_lo, flow, flow_hi), `profile`, `alt`, `geometry` (GeoJSON LineString, [lon, lat]), `stats` {`distance_km`, `ascent_m`, `brouter_time_s`, `expected_stops`, `stops_per_km`, `expected_stop_s`, `by_class`}, `delta_vs_fastest` {`stops`, `km`} or null, `hits[]` {`lat`, `lon`, `cause`, `p`}
- `candidates_total`, `candidates_deduped`, `skipped[]` (BRouter requests that failed, with error), `timings_ms` {`brouter`, `score`, `total`}

Errors: 400 bad or out-of-region coordinates, 404 no route, 503 BRouter unreachable.

Example: `curl 'http://localhost:8081/api/route?from=53.2990,-6.2825&to=53.2210,-6.2150'`

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
