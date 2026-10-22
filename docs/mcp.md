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

`start` / `end` accept `lat,lon` or a place name. `length_km` means +-10 %; `min_km`/`max_km` give an explicit range. `settings` takes the `/api/plan` model and routing keys (`weights`, `blend_with`, `blend`, `p_<cause>`, `guard`, `turn_weight`, `diversity` (0..1, default 0.7: skip routes overlapping an already ranked one by more than this; 0 = off), `scales`, `lane_bonus`, `turn_cost`, `lane_exit_cost`, `cycleway_base`, `lanes_variant`, `router`, `refresh`); unknown keys are rejected with a message. Errors (BRouter down, bad input, no route, unknown id, bad out_dir) come back as readable text starting with `Error:`, never tracebacks.

Route ids: `<variant>@<heading>.<set>/alt<k>` for loops and out-and-backs (for example `flow_hi@150.2/alt0`; `<set>` is the 0-based index of the via-point set, so two sets at the same heading stay distinct), `<variant>/alt<k>` for one-way. They are unique within a plan; the session keeps the last 50 routes, and an id from a later plan replaces the same id from an earlier one. `/api/plan` (and the web UI) use the same ids; `duplicate_of` refers to them too.

## GPX to Garmin

Garmin Connect (web): Training & Planning > Courses > Import, choose the `.gpx`, save the course, then send it to the device (Garmin Connect app or sync). The file is one track with elevations (no turn-by-turn cues).

## Limits

- BRouter must be running (the tools say so and suggest `start_brouter`).
- Loops and out-and-backs make 20-50 BRouter calls: about 10-60 s per plan; the tool call blocks until done (no progress events). Repeat plans with the same inputs are served from the cache.
- Climb and flat objectives need DEM tiles (`data/dem`); coverage is shown by `status()`. Without coverage they fall back to evenly spaced headings. The current tile covers lon -7..-6, lat 53..54.
- One-way ignores the length arguments (the route follows the start/end pair); a loop ignores `end`.
- Ireland only (bounding box lon -10.7..-5.4, lat 51.3..55.5); place names are geocoded in Ireland.
- Nominatim usage: one request per second, descriptive User-Agent; only used when a place name is given.

Tests: `uv run pytest tests/test_mcp.py` (tools called in-process with a fake BRouter; a stdio smoke test starts the server with the mcp client; `RUN_NETWORK_TESTS=1` enables the geocode test).

## Planning modes evaluation (41w.9, 2026-10-22)

`uv run scripts/plan_eval.py` runs 12 scenarios from `data/samples/plan_eval_scenarios.csv` sequentially through `PlannerService.plan` (n=4, bearings=8, max_calls=48, default settings, real BRouter and the DEM tile) and writes `data/samples/plan_eval.csv`. `in_range` = candidates kept after dedupe/length filtering; the table shows the top-ranked route. The Clontarf scenario asks for `return=free`; the rest use `same`. The Sandymount flat loop was not included (the Rathfarnham flat loops cover flat loops).

| name | candidates_total | in_range | calls | wall_s | top_id | top_km | ascent_m | climb_score | hardest_climb | expected_stops | turns | longest_straight_km | cycle_km | length_hit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| loop_rath_40_50_flow | 23 | 23 | 36 | 14.9 | flow_hi@270.6/alt0 | 48.0 | 505 | 257 | 2.0km/140m/6.8% | 27.43 | 61 | 2.6 | 22.9 | yes |
| loop_rath_40_50_climb | 31 | 30 | 41 | 11.9 | fastbike@210.6/alt0 | 48.2 | 755 | 424 | 2.0km/140m/6.8% | 36.74 | 52 | 2.1 | 7.0 | yes |
| loop_rath_40_50_flat | 26 | 26 | 39 | 17.0 | fastbike@15.1/alt0 | 40.6 | 146 | 0 | - | 69.56 | 35 | 1.4 | 18.3 | yes |
| loop_rath_70_85_flow | 28 | 28 | 41 | 31.6 | flow_hi@180.4/alt0 | 80.0 | 625 | 284 | 5.6km/314m/5.6% | 30.09 | 81 | 7.6 | 34.9 | yes |
| loop_rath_70_85_climb | 23 | 23 | 43 | 23.4 | flow@165.0/alt0 | 78.7 | 1344 | 856 | 2.8km/297m/10.7% | 29.42 | 76 | 5.1 | 18.4 | yes |
| loop_rath_70_85_flat | 31 | 31 | 40 | 29.7 | fastbike@15.4/alt0 | 73.8 | 291 | 0 | - | 117.28 | 54 | 1.7 | 26.9 | yes |
| oab_rath_sallygap_flow | 4 | 4 | 4 | 0.8 | flow_hi@185.294.0/alt0 | 46.0 | 792 | 437 | 5.6km/314m/5.6% | 6.7 | 19 | 13.8 | 4.7 | no |
| oab_rath_sallygap_climb | 4 | 4 | 4 | 0.8 | flow_lo@185.294.0/alt0 | 43.8 | 802 | 454 | 4.7km/288m/6.2% | 10.1 | 19 | 13.8 | 4.0 | no |
| oab_clontarf_30_40_flat | 21 | 21 | 48 | 10.1 | fastbike@90.1/alt0 | 32.5 | 14 | 0 | - | 15.77 | 7 | 6.4 | 5.7 | yes |
| oneway_lucan_dalkey_flow | 4 | 3 | 4 | 1.6 | flow/alt0 | 31.6 | 91 | 0 | - | 13.47 | 39 | 5.5 | 19.7 | n/a |
| oneway_lucan_dalkey_flat | 4 | 3 | 4 | 1.7 | flow/alt0 | 31.6 | 91 | 0 | - | 13.47 | 39 | 5.5 | 19.7 | n/a |
| loop_enniskerry_50_60_climb | 28 | 17 | 40 | 7.5 | flow_hi@240.3/alt0 | 55.6 | 1728 | 1574 | 2.6km/416m/16.2% | 2.39 | 31 | 6.4 | 1.1 | yes |

- Length-hit rate: 8/10 judged scenarios (loops 6/6, Clontarf out-and-back 1/1, Sally Gap out-and-back 0/2; one-way n/a). Mean wall time per mode: loop 19.4 s, out-and-back 3.9 s (Clontarf 10.1 s, Sally Gap 0.8 s), one-way 1.6 s. No scenario errored or returned zero routes.
- Loops close and land in range every time, but only after BRouter rescaling: many candidates are dropped ("length X km outside range", or "after 3 iterations" for the 50-60 km Enniskerry climb loop: 28 total, 17 kept), and the loops use 36-43 of the 48 calls. The longest loops (70-85 km) are slowest (23-32 s).
- Climb mode does find more ascent than flow for the same range: 755 vs 505 m (40-50 km) and 1344 vs 625 m (70-85 km), climb scores 424/856 vs 257/284, at the price of more expected stops (36.7 vs 27.4 on the short loop). Flat mode gives near-zero ascent (146 and 291 m) but the most stops (69.6 and 117.3), because the winners are fastbike urban routes. The Enniskerry climb loop reports 1728 m in 55.6 km, including a 16 % climb (km 20.6-23.2, 2.6 km / 416 m), but that result is not trustworthy as a road-bike route: the climb is real terrain per the DEM (420 m gain; 27-29 % sustained over 500 m) but runs on highway=path ways tagged surface=ground, foot=yes, some bicycle=no and smoothness=impassable, i.e. the flow_hi profile routed a road-bike loop over a footpath. This is a routing defect (follow-up bead bike-mapper-41w.13), and the row's 1.1 km on cycle infrastructure and 2.39 expected stops reflect that. BRouter's whole-route ascent (1728 m) and the DEM's (2433 m) also disagree by about 700 m on that route (follow-up bead bike-mapper-41w.14), so climb scores computed on BRouter elevations are indicative only.
- Out-and-back with an explicit turnaround (Sally Gap) cannot honour the length range: the route is what it is (43.8-46.0 km), the range is only noted, and the climb objective is ignored (flow and climb picked different variants, flow_hi 46.0 km vs flow_lo 43.8 km, with similar ascent, 792 vs 802 m). With no turnaround (Clontarf), `return=free` almost always fell back to `same` (most free attempts rejected for overlapping the out leg by 82-100 %, wrong length or no route), so a truly different return path is rare in this corridor, and the call budget (48) was exhausted.
- One-way is cheap (1.6 s, 4 calls) but ignores objective and length: flow and flat gave the identical route (31.6 km, 91 m ascent). The DEM tile covers only lon -7..-6, lat 53..54, so 3-12 of 72 grid points had no elevation in the Enniskerry and Clontarf plans.
