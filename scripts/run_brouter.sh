#!/usr/bin/env bash
# Reproduce the BRouter hands-on (dhy.8). Usage: scripts/run_brouter.sh [setup|serve|route|profiles]
# All downloads go under data/brouter/ (gitignored).
#
# Segments: PRE-BUILT rd5 tiles from brouter.de are used instead of a local build from
# data/osm/ireland.osm.pbf (the mapcreator pipeline: pbf -> osmosis -> .rd5 per 5x5 degree tile,
# see https://github.com/abrensch/brouter/blob/master/docs/developers/ and misc/scripts/mapcreation/).
# Ireland: W10_N50.rd5 (lon -10..-5, lat 50..55: Republic + NI south of 55N), W10_N55.rd5 (NI north coast).
# Tile dates/sizes at download (2026-10-20): both Last-Modified 2026-10-20 01:03 GMT;
# W10_N50 43,155,455 B, W10_N55 5,517,791 B. Build time: none (download only, ~10 s). 
# RAM: the server runs with -Xmx1g and 4 threads (~0.65-1.2 GB RSS observed), see docs/research/routing-engines.md.
set -euo pipefail
cd "$(dirname "$0")/.."
VER=1.7.10
B=data/brouter
DIST=$B/dist/brouter-$VER
SEG=$B/segments
PORT=17777
PROFDIR=$PWD/$DIST/profiles2

profiles() {   # sync profiles/flow*.brf into the dir the running BRouter reads (PROFDIR)
  [ -d $DIST/profiles2 ] || { echo "run setup first" >&2; exit 1; }
  cp profiles/flow*.brf $DIST/profiles2/
}

setup() {
  mkdir -p $SEG $B/dl $B/dist data/samples
  for t in W10_N50 W10_N55; do
    [ -f $SEG/$t.rd5 ] || curl -sf -o $SEG/$t.rd5 https://brouter.de/brouter/segments4/$t.rd5
  done
  [ -f $B/dl/brouter.zip ] || curl -sfL -o $B/dl/brouter.zip \
    https://github.com/abrensch/brouter/releases/download/v$VER/brouter-$VER.zip
  [ -d $DIST ] || unzip -q $B/dl/brouter.zip -d $B/dist
  # RouteServer resolves ?profile=NAME as <profiledir>/NAME.brf (the 3rd arg is only for uploaded
  # 'custom_*' profiles), so flow.brf is copied next to the stock profiles and lookups.dat.
  # flow_lo / flow_hi are NOT separate files: RouteServer 1.7.10 accepts per-request overrides of profile
  # variables as '&profile:<var>=<value>' (verified: &profile=flow&profile:flow_scale=0.5 / 2.0 change the route),
  # so one profile + the flow_scale multiplier gives all three variants. Copy every flow*.brf anyway.
  profiles
  mkdir -p $B/customprofiles
}

# Server threads (last RouteServer arg) MUST be >= the client's concurrency: flowplan.candidates.generate()
# and flow_server default to max_workers=4. With 2 server threads and 4 client workers, BRouter's
# thread-priority-watchdog killed queued requests on 20-50 km pairs (10-13 of 16 candidates skipped).
# Measured 4 threads/4 workers: 0 skipped, ~82 s for the 10 eval pairs vs ~144 s for 2/2; RSS 0.65-1.2 GB
# with -Xmx1g (heap cap unchanged: no OOM observed, RSS includes non-heap/mapped segment memory).
THREADS=4

serve() {   # foreground; Ctrl-C or kill to stop
  profiles
  exec java -Xmx1g -cp $DIST/brouter-$VER-all.jar btools.server.RouteServer \
    $SEG $PROFDIR $PWD/$B/customprofiles $PORT $THREADS
}

route() {   # needs server running; optional output dir ($1, default data/samples)
  local out=${1:-data/samples}; mkdir -p "$out"
  local url="http://localhost:$PORT/brouter?alternativeidx=0&format=gpx"
  # 41w.15: the "Fastest" baseline is the flow profile with node costs off (same definition as the planner's
  # fastbike variant: flow_scale 0, lane_bonus 1, lane_exit_cost 0, turn_cost 90), so it obeys the rideability rules
  local base="profile=flow&profile:flow_scale=0&profile:lane_bonus=1&profile:lane_exit_cost=0&profile:turn_cost=90"
  curl -sf "$url&$base&lonlats=-6.2957,53.0112|-6.3088,53.1358|-6.1706,53.1928" -o "$out"/brouter-wicklow-baseline.gpx
  curl -sf "$url&profile=flow&lonlats=-6.2957,53.0112|-6.3088,53.1358|-6.1706,53.1928" -o "$out"/brouter-wicklow-flow.gpx
  curl -sf "$url&$base&lonlats=-6.2825,53.2990|-6.2150,53.2210|-6.2110,53.2560" -o "$out"/brouter-dublin-baseline.gpx
  curl -sf "$url&profile=flow&lonlats=-6.2825,53.2990|-6.2150,53.2210|-6.2110,53.2560" -o "$out"/brouter-dublin-flow.gpx
  # flow_lo / flow_hi: same flow profile with flow_scale overridden per request (0.5 / 2.0; default 1.0)
  local w="lonlats=-6.2957,53.0112|-6.3088,53.1358|-6.1706,53.1928" d="lonlats=-6.2825,53.2990|-6.2150,53.2210|-6.2110,53.2560"
  curl -sf "$url&profile=flow&profile:flow_scale=0.5&$d" -o "$out"/brouter-dublin-flow_lo.gpx
  curl -sf "$url&profile=flow&profile:flow_scale=2.0&$d" -o "$out"/brouter-dublin-flow_hi.gpx
  curl -sf "$url&profile=flow&profile:flow_scale=0.5&$w" -o "$out"/brouter-wicklow-flow_lo.gpx
  curl -sf "$url&profile=flow&profile:flow_scale=2.0&$w" -o "$out"/brouter-wicklow-flow_hi.gpx
}
"${1:-setup}" "${2:-}"
