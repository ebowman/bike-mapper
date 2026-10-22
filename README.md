# bike-mapper

A road-cycling route planner for Dublin and Wicklow that ranks routes by how
often you will have to **stop**, not just by how far you ride. It plans loops,
out-and-backs and one-way rides to a target length, can seek out the hardest
climbs or avoid them, keeps you off main roads if you ask, and exports GPX
files that import straight into Garmin Connect. It runs as a local web page
and as an [MCP](https://modelcontextprotocol.io) server, so you can plan a
ride by talking to Claude Code.

Everything is built on open data: OpenStreetMap, the Copernicus GLO-30
elevation model and [BRouter](https://brouter.de). The project started as a
feasibility study (see [Research](#research)) into whether open data can
predict where a cyclist stops; the planner is what came out of it.

## What it does

- **Fewest-stops routing.** Every candidate route is scored against a
  directional index of stop causes derived from OSM (traffic signals, stop and
  give-way signs, roundabout entries, junction priority) and a per-class stop
  model, giving expected stops, stops per km and expected stopped time.
- **Three ride shapes with a length target.** `loop`, `out_and_back` (same
  road back, or a free return) and `one_way`, with `length_km` or an explicit
  `min_km`/`max_km` range. Loops are searched over ring and petal via-point
  shapes so they still close from awkward starts such as the Howth peninsula.
- **Three objectives.** `flow` (fewest stops and turns), `climb` (most and
  hardest climbing, via-points picked from the DEM) and `flat`.
- **Tunable routing.** Lane bonus, turn cost, lane-exit cost, cycleway weight
  and a `main_road_penalty` (1 to 5) that trades distance for quieter roads,
  with presets (`straight & lanes`, `plain flow`, `quiet roads`, `climb`,
  `flat`). Ferries are never used.
- **Route explanation.** Per route: km by road class, km on cycle
  infrastructure, main-road km, stop events by cause, turns, detected climbs
  (length, gain, grade), ascent and descent from DEM-sampled elevations.
- **GPX export** with elevation, ready for Garmin Connect
  (Training & Planning > Courses > Import).
- **Web UI** (Leaflet, single file) with click-to-pick start and end, place
  search, sliders for every setting, route cards and a cycle-infrastructure
  overlay.
- **MCP server** exposing `plan_route`, `route_details`, `export_gpx`,
  `geocode`, `list_presets`, `pick_points`, `status` and `start_brouter`.

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/) (`brew install uv`), Java 17+
(for BRouter), `curl`, and Node (only for the UI syntax check).

```bash
make setup           # uv sync
make planner-setup   # once: downloads BRouter 1.7.10 + Ireland tiles into data/brouter/, builds the flow index
make brouter         # terminal 1: BRouter on http://localhost:17777
make planner         # terminal 2: planner on http://localhost:8081
```

Open <http://localhost:8081>, click a start and an end (or search by name) and
pick a mode. `make planner-check` runs pytest, ruff and the UI syntax check.

### Data you need to provide

The `data/` directory is gitignored apart from small samples and the stop
model. Before `make planner-setup` you need:

| path | what | where from |
|---|---|---|
| `data/osm/ireland.osm.pbf` | OSM extract | [Geofabrik](https://download.geofabrik.de/europe/ireland-and-northern-ireland.html) |
| `data/osm/events_ireland.csv` | stop-cause events | `scripts/osm_stop_features.py` over the PBF, see `docs/planner.md` |
| `data/dem/*.tif` | Copernicus GLO-30 tiles (optional, needed for `climb`/`flat`) | AWS Open Data, see `docs/planner.md` |

BRouter's routing tiles are downloaded by the setup script. The committed stop
model (`data/model/stop_model.json`) defaults to a literature-based prior; the
empirical weight sets were derived offline from one rider's history, which is
not in the repo.

## Use it from Claude Code

The repo ships a project-scoped `.mcp.json` that registers the planner as the
`flow-planner` MCP server (`uv run scripts/flow_mcp.py`). Start Claude Code in
the repo, approve the server, make sure BRouter is running (or ask for
`start_brouter`), then:

> Plan a 60 km climbing loop from Rathfarnham.
>
> Out and back from Howth to Donabate, 50 to 60 km, keep me off the main roads.
>
> Export the best one for my Garmin.

Details, the full tool table and the evaluation results are in
[docs/mcp.md](docs/mcp.md).

## How it works

1. The web page or MCP tool calls `PlannerService` in `scripts/flowplan/`.
2. BRouter is asked for candidates with the custom `profiles/flow.brf` profile:
   four cost variants times four alternatives per leg, plus via-point sets for
   loops and out-and-backs, under a call budget.
3. Near-duplicate candidates are dropped, the rest are matched to the flow
   index (`data/flow/ireland.index.csv`) and scored by the stop model.
4. Routes are ranked by the objective, climbs are detected on a DEM-sampled
   profile, and the top `n` are returned with explanations and GPX.

[docs/planner.md](docs/planner.md) covers the architecture, the stop model,
the BRouter profile, loop geometry, elevation sources and known limits.

## Repository layout

| path | contents |
|---|---|
| `scripts/flowplan/` | planner library: BRouter client, candidates, scoring, ranking, climbs, terrain (DEM), turns, GPX, service |
| `scripts/flow_server.py` | FastAPI web server and `/api/plan`, `/api/route` |
| `scripts/flow_mcp.py` | MCP server (FastMCP, stdio) |
| `scripts/*.py` | data pipeline and research scripts (OSM features, flow index, stop-model validation, evals) |
| `profiles/flow.brf` | the BRouter profile with node costs per stop cause, lane and main-road factors |
| `web/index.html` | the planner page |
| `tests/` | pytest suite (BRouter is mocked; no network needed) |
| `docs/planner.md`, `docs/mcp.md` | planner and MCP documentation, evaluation tables |
| `docs/research/` | the feasibility study, one note per question |
| `docs/map/` | Leaflet viewer over the study's sample outputs |
| `data/samples/`, `data/model/` | small committed data: eval CSVs, sample GPX, the stop model |
| `.beads/` | issue tracker export (see below) |

## Research

The planner rests on a set of research notes in [docs/research/](docs/research/),
each following one template, starting from the
[feasibility summary](docs/research/feasibility-summary.md): OSM tag coverage
in Ireland, OSM stop-cause features, empirical stop detection from ride GPS,
validation of the stop model against observed stops, open elevation models
checked on the Wicklow Gap, open climb datasets, motor-traffic counts, routing
engines compared on node-level costs, and open sources for stop priors.

## Development

- `make planner-check` is the gate: pytest, `ruff check`, and a syntax check of
  the inline UI script.
- Evaluations: `uv run scripts/plan_eval.py` (loop, out-and-back and one-way
  scenarios against a live BRouter) and `uv run scripts/planner_eval.py`
  (one-way pairs). Results are committed under `data/samples/` and discussed
  in the docs.
- Issues are tracked with [beads](https://github.com/gastownhall/beads) (`bd`).
  The versioned export is `.beads/issues.jsonl`; run `bd prime` for the
  workflow. The commit history is one commit per bead, so `git log` reads as
  the project's change log.
- The code was written with Claude Code acting as implementer and reviewer
  under a human orchestrator; `CLAUDE.md` and `AGENTS.md` hold the agent
  instructions.

## Data licences

- Map data (c) [OpenStreetMap](https://www.openstreetmap.org/copyright)
  contributors, ODbL. Derived tables (the flow index, the stop-cause events,
  the committed samples) are derived databases under the ODbL.
- Elevation: Copernicus DEM GLO-30, (c) European Union, Copernicus free licence.
- Routing: [BRouter](https://github.com/abrensch/brouter) (MIT), downloaded at
  setup, not vendored.

## Licence

MIT, see [LICENSE](LICENSE).
