# Research notes

Every note in this directory follows [TEMPLATE.md](TEMPLATE.md).

Start here: [feasibility-summary.md](feasibility-summary.md) - go/no-go synthesis (flow answer, layer verdicts, licence matrix, recommended stack, next epic, open questions).

Notes:

- feasibility-summary.md - go/no-go synthesis: layer verdicts, licence matrix, recommended stack
- osm-road-network.md - OSM tag coverage (surface, smoothness, maxspeed, cycleway...) for the Ireland extract
- osm-stop-features.md - OSM stop-cause features (signals, stop, give-way, roundabouts) and expected stops/km
- empirical-stops.md - empirical stop detection from real ride GPS and public traces
- stop-model-validation.md - validating the OSM-derived stop model against empirical stops
- elevation.md - open DEM comparison and profile accuracy on a known Irish climb
- climbs.md - open climb datasets and a derivation spec from OSM + DEM
- motor-traffic-flow.md - open AADT sources (TII, DfT) and coverage of minor roads
- routing-engines.md - routing engines compared on node-level stop and turn costs, BRouter 'flow' profile
- stop-priors-open-data.md - open non-ride sources (See.Sense, SCATS, GTFS-R, Strava Metro) and literature for per-class stop priors; structural prior table vs empirical
- ride-data-acquisition.md - acquiring Eric's ride history (FIT/GPX) from Garmin Connect / Strava (bead dhy.12)
- road-cycle-open-data-ireland.md - open road/cycle data beyond OSM: Overture vs OSM counts for Dublin (Overture = OSM mirror, no cycle-lane property), NTA/SDCC/DLR cycle layers, TII, Tailte HVD Ways, MapRoad/PSCI, Mapillary, MS Road Detections, Daylight; verdict table (bead emq.22)

## Environment

Python tooling is managed with [uv](https://docs.astral.sh/uv/). Install with `brew install uv` if missing. Run `make setup` (runs `uv sync`).

## Map viewer

`docs/map/index.html` is a single-file Leaflet map over the study's sample outputs, for Dublin/Wicklow and Berlin (region switcher, top left). Layers: ways coloured by expected stops/km (5-step scale), dhy.11 stop units (circle size ~ log passes, grey-to-red by observed stop probability, faint under 5 passes), BRouter baseline (dashed) vs flow (solid) routes, and the manually labelled unexplained units. Build the data with `make map` (writes `docs/map/data/*.geojson` from `data/samples/` and the OSM PBFs; Ireland ways are filtered to primary/secondary/tertiary/unclassified/residential and at least 0.1 km to stay under 2 MB), then serve with `uv run python -m http.server 8080 --directory docs/map` and open http://localhost:8080. `uv run python scripts/check_map_data.py` is the smoke test. Way geometries are simplified with a Douglas-Peucker tolerance of 1.5e-5 degrees (roughly 1-2 m) before export.

The route planner built on these findings is documented in [../planner.md](../planner.md).
