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

Route ids: `<variant>@<heading>/alt<k>` for loops and out-and-backs (for example `flow_hi@150/alt0`), `<variant>/alt<k>` for one-way. They are unique within a plan; the session keeps the last 50 routes, and an id from a later plan replaces the same id from an earlier one. `/api/plan` (and the web UI) use the same ids; `duplicate_of` refers to them too.

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
