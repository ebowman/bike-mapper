# Research notes

Every note in this directory follows [TEMPLATE.md](TEMPLATE.md).

Planned notes:

- osm-road-network.md - OSM tag coverage (surface, smoothness, maxspeed, cycleway...) for the Ireland extract
- osm-stop-features.md - OSM stop-cause features (signals, stop, give-way, roundabouts) and expected stops/km
- empirical-stops.md - empirical stop detection from real ride GPS and public traces
- stop-model-validation.md - validating the OSM-derived stop model against empirical stops
- elevation.md - open DEM comparison and profile accuracy on a known Irish climb
- climbs.md - open climb datasets and a derivation spec from OSM + DEM
- motor-traffic-flow.md - open AADT sources (TII, DfT) and coverage of minor roads
- routing-engines.md - routing engines compared on node-level stop and turn costs, BRouter 'flow' profile
- feasibility-summary.md - go/no-go synthesis: layer verdicts, licence matrix, recommended stack
- ride-data-acquisition.md - acquiring Eric's ride history (FIT/GPX) from Garmin Connect / Strava (bead dhy.12)

## Environment

Python tooling is managed with [uv](https://docs.astral.sh/uv/). Install with `brew install uv` if missing. Run `make setup` (runs `uv sync`).
