# Flow planner MCP server

`scripts/flow_mcp.py` exposes the route planner to Claude Code (or any MCP client) over stdio. It uses the same in-process logic as the web planner (`flowplan/service.py`: settings, loop / out-and-back / one-way planning, ranking, climbs), not HTTP, so the web server does not need to run.

## Setup

1. `make setup` (`uv sync`; installs `mcp<2`, the FastMCP API of the 1.x line) and, once, `make planner-setup` (BRouter tiles + flow index).
2. BRouter must be running: `make brouter` in a terminal, or call the `start_brouter` tool (spawns `scripts/run_brouter.sh serve`, log in `$TMPDIR/flow-brouter.log`, waits up to 60 s).
3. Registration is the project-scoped `.mcp.json` at the repo root:

```json
{"mcpServers": {"flow-planner": {"type": "stdio", "command": "uv", "args": ["run", "scripts/flow_mcp.py"]}}}
```

Claude Code reads `.mcp.json` when started in this repo and asks once to approve the project server; `claude mcp list` then shows `flow-planner`. (`claude mcp add -s project flow-planner -- uv run scripts/flow_mcp.py` writes the same file.) Claude Code starts the command in the project directory; the script itself resolves everything relative to the repo root, so another cwd also works if you give the script path as an absolute path. All logging goes to stderr; stdout carries only MCP frames.

## Example prompts

- "Plan a 60 km climbing loop from Rathfarnham" -> `plan_route(mode='loop', start='Rathfarnham', length_km=60, objective='climb')`
- "Out and back to Sally Gap 55-65 km" -> `plan_route(mode='out_and_back', start=<where you are>, min_km=55, max_km=65, objective='climb')`
- "One way from Lucan to Dalkey, flattest" -> `plan_route(mode='one_way', start='Lucan', end='Dalkey', objective='flat')`
- "Export the best one for my Garmin" -> `export_gpx(<id of rank 1>)`

## Tools

| tool | returns |
|---|---|
| `status()` | BRouter reachable or not, region, stop-model weight set, flow-index rows, DEM coverage, routes in session |
| `start_brouter()` | `already running`, or the pid after the server is healthy (error text on failure / timeout) |
| `geocode(query, limit=5)` | numbered Nominatim candidates (`countrycodes=ie`, at most 1 request/s, User-Agent `bike-mapper-flow-planner/0.1 (local MCP)`) with `lat,lon` |
| `plan_route(mode, start, end=None, length_km=None, min_km=None, max_km=None, objective='flow', n=4, bearings=8, return_mode='same', settings=None)` | echo of the resolved start/end (place name -> geocoded first hit, so you can correct it), a plan line, a markdown table (rank, id, variant, mode/heading, km, ascent m, expected stops, turns, longest straight km, climb score, hardest climb `len/gain/grade`, km on cycle infrastructure) and the plan notes |
| `route_details(route_id)` | km by road class, cycle-infrastructure km (track/lane/path), stop events by cause with expected stops, turns, climbs list, ascent/descent |
| `export_gpx(route_id, name=None, out_dir='~/Downloads')` | path and size of the written GPX 1.1 (with elevation) and the Garmin import hint |
| `list_presets()` | JSON list of presets: `straight & lanes`, `plain flow`, `climb`, `flat`; each has `settings` (pass as `settings`) and `objective` |
| `pick_points(n=1, timeout_s=300)` | opens the planner page in pick mode, waits for `n` map clicks (or search picks) and returns them as `lat,lon` lines to use as start/end in `plan_route`; errors if the planner web server is not running or the timeout passes |

`start` / `end` accept `lat,lon` or a place name. `length_km` means +-10 %; `min_km`/`max_km` give an explicit range. `settings` takes the `/api/plan` model and routing keys (`weights`, `blend_with`, `blend`, `p_<cause>`, `guard`, `turn_weight`, `diversity` (0..1, default 0.7: skip routes overlapping an already ranked one by more than this; 0 = off), `scales`, `lane_bonus`, `turn_cost`, `lane_exit_cost`, `cycleway_base`, `lanes_variant`, `router`, `refresh`, `elevation_source` (auto|brouter|dem, default auto: DEM-sampled elevations for climb stats and the GPX when the DEM covers >= 95 % of the route, else BRouter's; see 'Elevation source comparison')); unknown keys are rejected with a message. Errors (BRouter down, bad input, no route, unknown id, bad out_dir) come back as readable text starting with `Error:`, never tracebacks.

Route ids: `<variant>@<heading>.<set>/alt<k>` for loops and out-and-backs (for example `flow_hi@150.2/alt0`; `<set>` is the 0-based index of the via-point set, so two sets at the same heading stay distinct), `<variant>/alt<k>` for one-way. They are unique within a plan; the session keeps the last 50 routes, and an id from a later plan replaces the same id from an earlier one. `/api/plan` (and the web UI) use the same ids; `duplicate_of` refers to them too.

## GPX to Garmin

Garmin Connect (web): Training & Planning > Courses > Import, choose the `.gpx`, save the course, then send it to the device (Garmin Connect app or sync). The file is one track with elevations (no turn-by-turn cues). The elevations are the profile the route's climb stats used (`stats.elevation_source`: DEM samples by default where the DEM covers the route, else BRouter's), so the GPX ascent matches the table.

## Limits

- BRouter must be running (the tools say so and suggest `start_brouter`).
- Loops and out-and-backs make 20-50 BRouter calls: about 10-60 s per plan; the tool call blocks until done (no progress events). Repeat plans with the same inputs are served from the cache.
- Climb and flat objectives need DEM tiles (`data/dem`); coverage is shown by `status()`. Without coverage they fall back to evenly spaced headings. The current tile covers lon -7..-6, lat 53..54.
- One-way ignores the length arguments (the route follows the start/end pair); a loop ignores `end`.
- Ireland only (bounding box lon -10.7..-5.4, lat 51.3..55.5); place names are geocoded in Ireland.
- Nominatim usage: one request per second, descriptive User-Agent; only used when a place name is given.

Tests: `uv run pytest tests/test_mcp.py` (tools called in-process with a fake BRouter; a stdio smoke test starts the server with the mcp client; `RUN_NETWORK_TESTS=1` enables the geocode test).

## Picking points on the map (pick_points)

`pick_points(n=1, timeout_s=300)` lets the user choose 1 or 2 locations by clicking instead of typing coordinates. It needs the planner web server (`make planner`, default http://localhost:8081; override with env `FLOW_PLANNER_URL`); if that is not running it returns `Error: planner web server not running (make planner)`.

1. The tool makes a random token and opens `http://localhost:8081/#pick=<token>&n=<n>` in the default browser.
2. The user sees a yellow banner "Pick N point(s) for the assistant" with a Cancel button. The next N map clicks (or search selections) drop the usual start/end markers and are POSTed to `/api/pick/<token>`; the banner then says "Sent". The rest of the planner stays usable, and pick mode never starts a plan by itself.
3. The tool polls `GET /api/pick/<token>` every 2 s and returns the points as `lat,lon` strings (first = start, second = end) with a hint to pass them to `plan_route`.
4. If nothing arrives within `timeout_s` (default 300 s) it returns a timeout error. The server keeps picks in memory for 10 minutes only; tokens must match `[A-Za-z0-9_-]{8,64}`, at most 2 points per token.

## Elevation source comparison (41w.14, 2026-10-22)

Question: climb stats (ascent, climbs, climb score) came from BRouter's per-node elevations; do they match the DEM (`flowplan.terrain.Dem`, GLO-30) sampled along the same geometry? `uv run scripts/compare_elevation_sources.py` re-plans the 12 eval scenarios (ranking on BRouter elevations, so these are the pre-change top routes) and writes `data/samples/elevation_source_comparison.csv` (more columns: raw-node variants, DEM coverage, every cell). DEM coverage was 100 % on all 12 routes.

| name | km | BRouter asc (3 m) | DEM asc (25 m grid, 3 m) | DEM/BRouter | BRouter asc (10 m) | DEM asc (25 m grid, 10 m) | hardest climb gain BRouter / DEM |
|---|---|---|---|---|---|---|---|
| loop_rath_40_50_flow | 47.9 | 406 | 561 | 1.38 | 356 | 405 | 193 / 153 |
| loop_rath_40_50_climb | 45.2 | 778 | 888 | 1.14 | 642 | 662 | 139 / 154 |
| loop_rath_40_50_flat | 41.1 | 156 | 303 | 1.94 | 82 | 130 | 0 / 0 |
| loop_rath_70_85_flow | 83.8 | 862 | 1076 | 1.25 | 665 | 681 | 151 / 153 |
| loop_rath_70_85_climb | 80.7 | 1298 | 1602 | 1.23 | 1055 | 1114 | 183 / 182 |
| loop_rath_70_85_flat | 75.2 | 264 | 450 | 1.7 | 158 | 178 | 0 / 0 |
| oab_rath_sallygap_flow | 46.0 | 792 | 957 | 1.21 | 759 | 751 | 312 / 175 |
| oab_rath_sallygap_climb | 43.8 | 802 | 848 | 1.06 | 759 | 747 | 288 / 347 |
| oab_clontarf_30_40_flat | 36.0 | 19 | 81 | 4.26 | 0 | 13 | 0 / 0 |
| oneway_lucan_dalkey_flow | 30.5 | 95 | 386 | 4.06 | 44 | 117 | 0 / 0 |
| oneway_lucan_dalkey_flat | 30.5 | 95 | 386 | 4.06 | 44 | 117 | 0 / 0 |
| loop_enniskerry_50_60_climb | 56.2 | 1166 | 1469 | 1.26 | 1017 | 1089 | 244 / 242 |

Findings:
- With a 3 m hysteresis the DEM reports 1.06-1.4x BRouter's ascent on hilly routes and 1.7-4.3x on flat ones (Lucan-Dalkey 386 vs 87 m, Clontarf 81 vs 19 m, Rathfarnham flat loops 303 vs 151 and 450 vs 247 m). Sampling the DEM at every route node (dense, nearest-cell) is worse still (Lucan-Dalkey 525 m), so the 25 m resample matters. This is DEM noise (30 m cells, surface model, nearest-cell sampling) plus BRouter's smoother profile, not extra real climbing.
- With a 10 m hysteresis the two sources agree: DEM(10 m) is within 0-18 % of BRouter(3 m) on every hilly route (e.g. Enniskerry 1089 vs 1139, Rathfarnham 70-85 climb 1114 vs 1237, Sally Gap 747 vs 796, 40-50 climb 662 vs 739), while flat routes stay near zero (Clontarf 13 m, Lucan-Dalkey 117 m).
- Single big climbs agree where the profile is clean (Enniskerry 244 vs 242 m, Rathfarnham 70-85 climb 183 vs 182 m, 70-85 flow 151 vs 153 m); they differ where the DEM splits or merges a climb differently (Sally Gap flow 312 vs 175 m, 40-50 flow 193 vs 153 m, Sally Gap climb 288 vs 347 m), so hardest-climb gain is source-dependent by up to ~40 %.

Decision: `elevation_source` = `auto` by default: use the DEM when it covers >= 95 % of the route points (it is gap-filled by linear interpolation over distance), else BRouter's elevations. The DEM profile replaces the candidate's elevations for climb stats (ascent, descent, climbs, climb score, hardest climb, the `flat` ranking) and for the GPX export, and `stats.elevation_source` says which was used per route. Ascent/descent hysteresis: 3 m for BRouter elevations (unchanged), 10 m for DEM elevations (`climbs.DEM_HYST`), because the table shows 3 m inflates DEM ascent 1.5-4x on flat terrain while 10 m lands on the BRouter(3 m) scale. Climb detection already resamples to 25 m. `brouter` and `dem` force a source (`dem` falls back to BRouter only when no route point has a DEM value). The setting only changes ranking, not the BRouter candidates, so it is not part of the cache key.

Effect on the eval (re-run below): top-route ascent changed on all 12 rows, mostly down: 70-85 flow 862 -> 726 m, Enniskerry 1166 -> 1004 (a different route), 70-85 flat 264 -> 197, 70-85 climb 1298 -> 1231, 40-50 climb 778 -> 721, 40-50 flat 156 -> 120, Sally Gap climb 802 -> 735, Clontarf 19 -> 0, up on Lucan-Dalkey flow 95 -> 124 and 40-50 flow 406 -> 409; climb scores moved up 3-85 points (the DEM resolves more distinct climbs). Six top routes changed because the flat/climb rankings now use the DEM stats (loop_rath_40_50_flat, loop_rath_70_85_flat, oab_rath_sallygap_climb, oab_clontarf_30_40_flat, oneway_lucan_dalkey_flat, loop_enniskerry_50_60_climb). Length hit unchanged at 8/10.

## Planning modes evaluation (41w.9, 2026-10-22)

`uv run scripts/plan_eval.py` runs 12 scenarios from `data/samples/plan_eval_scenarios.csv` sequentially through `PlannerService.plan` (n=4, bearings=8, max_calls=48, default settings, real BRouter and the DEM tile) and writes `data/samples/plan_eval.csv`. `in_range` = candidates kept after dedupe/length filtering; the table shows the top-ranked route. The Clontarf scenario asks for `return=free`; the rest use `same`. The Sandymount flat loop was not included (the Rathfarnham flat loops cover flat loops).

| name | candidates_total | in_range | calls | wall_s | top_id | top_km | ascent_m | climb_score | hardest_climb | expected_stops | turns | longest_straight_km | cycle_km | length_hit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| loop_rath_40_50_flow | 26 | 26 | 39 | 12.6 | flow_hi@180.4/alt0 | 47.9 | 409 | 229 | 1.6km/153m/9.6% | 29.69 | 65 | 4.5 | 17.0 | yes |
| loop_rath_40_50_climb | 31 | 27 | 41 | 11.0 | fastbike@150.0/alt0 | 45.2 | 721 | 564 | 2.3km/154m/6.6% | 29.81 | 35 | 7.5 | 16.1 | yes |
| loop_rath_40_50_flat | 30 | 30 | 40 | 11.7 | fastbike@0.4/alt0 | 40.9 | 120 | 0 | - | 77.39 | 33 | 1.0 | 26.8 | yes |
| loop_rath_70_85_flow | 24 | 24 | 43 | 16.3 | flow_hi@315.7/alt0 | 83.8 | 726 | 304 | 2.4km/153m/6.3% | 38.83 | 92 | 10.2 | 29.4 | yes |
| loop_rath_70_85_climb | 16 | 15 | 38 | 10.2 | flow_hi@195.4/alt0 | 80.7 | 1231 | 602 | 2.5km/182m/7.4% | 25.6 | 56 | 7.4 | 15.2 | yes |
| loop_rath_70_85_flat | 21 | 21 | 36 | 14.8 | flow_lo@15.4/alt0 | 78.7 | 197 | 0 | - | 97.71 | 83 | 5.4 | 42.3 | yes |
| oab_rath_sallygap_flow | 4 | 4 | 4 | 0.6 | flow@185.294.0/alt0 | 46.0 | 779 | 441 | 2.2km/175m/7.8% | 7.34 | 19 | 13.8 | 4.7 | no |
| oab_rath_sallygap_climb | 4 | 4 | 4 | 0.6 | fastbike@185.294.0/alt0 | 43.8 | 735 | 468 | 6.0km/347m/5.8% | 10.35 | 15 | 13.8 | 4.0 | no |
| oab_clontarf_30_40_flat | 22 | 22 | 48 | 5.9 | flow_hi@135.4/alt0 | 38.3 | 0 | 0 | - | 17.08 | 91 | 1.3 | 16.0 | yes |
| oneway_lucan_dalkey_flow | 4 | 3 | 4 | 0.8 | flow/alt0 | 30.5 | 124 | 0 | - | 18.97 | 39 | 7.0 | 10.3 | n/a |
| oneway_lucan_dalkey_flat | 4 | 3 | 4 | 0.8 | fastbike/alt0 | 29.0 | 90 | 0 | - | 39.83 | 16 | 1.8 | 11.2 | n/a |
| loop_enniskerry_50_60_climb | 20 | 10 | 38 | 3.6 | flow@225.1/alt0 | 52.5 | 1004 | 767 | 3.5km/242m/7.0% | 1.53 | 19 | 16.1 | 0.0 | yes |

- Re-run for 41w.15 (the Fastest baseline is now the flow profile with flow_scale 0 instead of stock fastbike; the old table is the 41w.13 run). Length hit unchanged at 8/10 judged scenarios (loops 6/6, Clontarf 1/1, Sally Gap out-and-back 0/2). Top routes: 9 of 12 identical; changed: loop_rath_40_50_climb (flow 45.5 km / 769 m / 25.85 stops -> fastbike baseline 45.2 km / 778 m / 29.81 stops), loop_rath_40_50_flat (42.3 -> 41.1 km, 74.9 -> 77.1 stops) and loop_rath_70_85_flat (75.3 -> 75.2 km, 119.2 -> 113.7 stops). Candidate counts rose (e.g. 40-50 flat 23 -> 30 total) because the baseline now yields more usable routes. Baseline candidates with ride warnings across all kept candidates: 0 (asserted by the script, column `baseline_warned`). The 'dropped stock-fastbike' note and null `delta_vs_fastest` no longer occur.
- Re-run after the rideability fix (41w.13; the first run of this table, before it, had a 55.6 km / 1728 m Enniskerry row). 11 of 12 top routes changed (only the Sally Gap climb out-and-back is identical), because the profile now forbids a lot of off-road and `bicycle=no` ways and the stock fastbike candidates that used them are dropped from plan results; the length-hit rate is unchanged at 8/10 judged scenarios (loops 6/6, Clontarf out-and-back 1/1, Sally Gap out-and-back 0/2; one-way n/a). Mean wall time per mode: loop 13.1 s, out-and-back 5.0 s (Clontarf 13.3 s, Sally Gap 0.8 s), one-way 1.5 s. No scenario errored or returned zero routes.
- Loops still close and land in range every time, but only after BRouter rescaling: fewer candidates survive than before (e.g. Enniskerry 16 total / 8 kept, was 28 / 17; Rathfarnham 70-85 climb 14 / 14, was 23 / 23) and the loops use 36-43 of the 48 calls.
- Climb mode still finds more ascent than flow for the same range: 769 vs 406 m (40-50 km) and 1298 vs 862 m (70-85 km), climb scores 478/553 vs 198/300, with fewer expected stops than before on the short loop (25.9 vs 29.7). Flat mode gives near-zero ascent (155 and 266 m) but the most stops (74.9 and 119.2), because the winners are fastbike urban routes. The Enniskerry climb loop is now on rideable ways: 56.2 km, 1166 m ascent, climb score 734 (was 1574), hardest climb 3.5 km / 244 m / 6.9 % (was 2.6 km / 416 m / 16.2 %, on `highway=path` ways with `surface=ground`, `bicycle=no`, `smoothness=impassable`), 19 turns, 1.99 expected stops, no km on cycle infrastructure. Debug segments of every top route in the 12 scenarios show no `bicycle=no|dismount|private|use_sidepath`, no impassable/very_horrible/horrible/very_bad smoothness, no ground/mud/sand/grass/dirt/earth surfaces and no `highway=track`; the only path/footway segments left are footways explicitly tagged `bicycle=yes` on a paved surface (at most 0.1 km per route). BRouter's whole-route ascent and the DEM's still disagree on that kind of route (follow-up bead bike-mapper-41w.14), so climb scores computed on BRouter elevations were indicative only; 41w.14 resolved this (DEM elevations by default, see above). The table below is the 41w.14 re-run with `elevation_source=auto`.
- Out-and-back with an explicit turnaround (Sally Gap) cannot honour the length range: the route is what it is (43.8-46.0 km), the range is only noted, and the climb objective is ignored (flow and climb picked different variants, flow_hi 46.0 km vs flow_lo 43.8 km, with similar ascent, 792 vs 802 m). With no turnaround (Clontarf), `return=free` almost always fell back to `same` (most free attempts rejected for overlapping the out leg by 82-100 %, wrong length or no route), so a truly different return path is rare in this corridor, and the call budget (48) was exhausted.
- One-way is cheap (1.5 s, 4 calls) but ignores objective and length: flow and flat gave the identical route (30.5 km, 95 m ascent; before the rideability fix 31.6 km / 91 m, 39 turns both times, expected stops 13.5 -> 19.0). The Dublin sample pair (flow GPX) shifted from 19.77 to 19.17 km (flow_lo 18.58 -> 17.95); the Wicklow samples keep their length. The Clontarf flat out-and-back went from fastbike 32.5 km / 7 turns / 15.8 stops to flow_lo 36.0 km / 28 turns / 10.8 stops, because the stock fastbike route used a footway. The DEM tile covers only lon -7..-6, lat 53..54, so 3-12 of 72 grid points had no elevation in the Enniskerry and Clontarf plans.
