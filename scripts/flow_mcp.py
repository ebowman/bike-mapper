"""Flow route planner as an MCP server (stdio). Run: uv run scripts/flow_mcp.py
Tools: status, pick_points, start_brouter, geocode, plan_route, route_details, export_gpx, list_presets.
Everything is logged to stderr; stdout carries only MCP frames. See docs/mcp.md."""
from __future__ import annotations

import functools
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from collections import OrderedDict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

import requests
from flowplan.brouter import DEFAULT_URL
from flowplan.gpx import write_gpx
from flowplan.service import STRAIGHT_DEFAULTS, PlannerService, ServiceError
from mcp.server.fastmcp import FastMCP

log = logging.getLogger("flow_mcp")
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "bike-mapper-flow-planner/0.1 (local MCP)"
SESSION_SIZE = 50
BROUTER_WAIT_S = 60
PICK_POLL_S = 2.0
GARMIN_HINT = "Garmin Connect: Training & Planning > Courses > Import, then send to device"
LATLON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
# settings accepted by plan_route(settings=...): the /api/plan model/routing/ranking parameters
SETTING_KEYS = {"weights", "blend_with", "blend", "guard", "turn_weight", "diversity", "scales", "router", "refresh",
                "elevation_source",
                "lanes_variant", "lane_bonus", "turn_cost", "lane_exit_cost", "cycleway_base", "main_road_penalty",
                *(f"p_{c}" for c in ("signal", "stop", "give_way", "rb_entry", "xing_signal",
                                     "yield_infer", "yield_equal"))}
PRESETS = [
    {"name": "straight & lanes", "objective": "flow",
     "description": "Default: penalise turns, stay on cycle lanes/paths (fewest turns, long straights).",
     "settings": dict(STRAIGHT_DEFAULTS)},
    {"name": "plain flow", "objective": "flow",
     "description": "Pre-emq.27 behaviour: avoid stops only, no lane preference.",
     "settings": {"turn_cost": 150, "lane_exit_cost": 0, "lane_bonus": 1.0}},
    {"name": "quiet roads", "objective": "flow",
     "description": "Penalise primary/secondary roads 2.5x; otherwise the default straight & lanes behaviour",
     "settings": {"main_road_penalty": 2.5, "lane_bonus": 0.7, "turn_cost": 400.0, "lane_exit_cost": 150.0}},
    {"name": "climb", "objective": "climb",
     "description": "Rank by climb score (points per the climbs spec); pass objective='climb'.",
     "settings": {}},
    {"name": "flat", "objective": "flat",
     "description": "Rank by least total ascent; pass objective='flat'.",
     "settings": {}},
]

mcp = FastMCP("flow-planner", instructions=(
    "Plans road-cycling routes around Dublin/Wicklow (Ireland) that minimise expected stops, with climb "
    "seeking or flat options and GPX export for Garmin. Typical flow: plan_route -> route_details -> "
    "export_gpx. BRouter must be running (status / start_brouter). Route ids refer to the most recent plan "
    "that produced them."))

_state: dict = {"service": None, "sessions": OrderedDict(), "brouter_proc": None, "last_geocode": 0.0}
_lock = threading.Lock()


def build_service(client=None, dem=None) -> PlannerService:
    """Shared planner service; tests inject a FakeClient and Dem(paths=[])."""
    return PlannerService.create("ireland", DEFAULT_URL, client=client, dem=dem)


def set_service(svc: PlannerService | None) -> None:
    _state["service"] = svc
    _state["sessions"].clear()


def service() -> PlannerService:
    with _lock:
        if _state["service"] is None:
            _state["service"] = build_service()
        return _state["service"]


def tool(fn):
    """Register fn as an MCP tool; errors come back as readable text, never tracebacks."""
    @functools.wraps(fn)
    def wrapped(*a, **k):
        try:
            return fn(*a, **k)
        except ServiceError as e:
            return f"Error: {e.detail}" + (" (start it with the start_brouter tool)" if e.status == 503 else "")
        except Exception as e:
            log.exception("tool %s failed", fn.__name__)
            return f"Error: {type(e).__name__}: {e}"
    return mcp.tool()(wrapped)


# ---- geocoding ----
def _geocode(query: str, limit: int = 5) -> list[dict]:
    """Nominatim (Ireland only), at most 1 request/second. -> [{name, lat, lon, type}]."""
    with _lock:
        wait = 1.05 - (time.monotonic() - _state["last_geocode"])
        if wait > 0:
            time.sleep(wait)
        _state["last_geocode"] = time.monotonic()
    r = requests.get(NOMINATIM, params={"q": query, "format": "jsonv2", "countrycodes": "ie",
                                        "limit": max(1, min(10, limit))},
                     headers={"User-Agent": USER_AGENT}, timeout=15)
    r.raise_for_status()
    return [{"name": x.get("display_name", ""), "lat": float(x["lat"]), "lon": float(x["lon"]),
             "type": x.get("type", "")} for x in r.json()]


def _resolve_point(text: str, label: str) -> tuple[str, str]:
    """'lat,lon' or a place name -> ('lat,lon', description for the echo)."""
    m = LATLON.match(text)
    if m:
        return f"{float(m.group(1))},{float(m.group(2))}", f"{label}: {m.group(1)},{m.group(2)}"
    hits = _geocode(text, 1)
    if not hits:
        raise ServiceError(400, f"could not find a place called {text!r} in Ireland; "
                                "try geocode or give 'lat,lon'")
    h = hits[0]
    return f"{h['lat']},{h['lon']}", f"{label}: {text!r} -> {h['name']} ({h['lat']:.5f},{h['lon']:.5f})"


# ---- formatting ----
def _climb_str(c) -> str:
    return "-" if not c else f"{c['length_m'] / 1000:.1f}km/{c['gain_m']:.0f}m/{c['avg_grade_pct']:.1f}%"


def _fmt(v, spec="{:.1f}") -> str:
    return "-" if v is None else spec.format(v)


def _cyc(ck: dict) -> float:
    """Km on cycle infrastructure (path + lane + track); cycle_km['total_km'] is the whole route."""
    return ck["path"] + ck["lane"] + ck["track"]


def _table(resp: dict) -> str:
    rows = [("| rank | id | variant | mode/heading | km | ascent m | exp. stops | turns | longest straight km "
            "| climb score | hardest climb (len/gain/grade) | km on cycle infra | main-road km | warnings |"),
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in resp["routes"]:
        s, p = r["stats"], r.get("plan") or {}
        mh = p.get("mode", "?") + (f" {p['heading_deg']:g} deg" if p.get("heading_deg") is not None else "")
        rows.append(f"| {r['rank']} | {r['id']} | {r['variant']} | {mh} | {s['distance_km']:.1f} "
                    f"| {_fmt(s['ascent_m'], '{:.0f}')} | {s['expected_stops']:.2f} | {s['turns']} "
                    f"| {s['longest_straight_km']:.1f} | {s['climb_score']:.0f} | {_climb_str(s['hardest_climb'])} "
                    f"| {_cyc(s['cycle_km']):.1f} | {s.get('main_road_km', 0.0):.1f} | {'; '.join(r.get('warnings') or []) or '-'} |")
    return "\n".join(rows)


def _remember(top) -> None:
    ss = _state["sessions"]
    for s in top:
        ss[s.cand.route_id] = s
        ss.move_to_end(s.cand.route_id)
    while len(ss) > SESSION_SIZE:
        ss.popitem(last=False)


def _settings_qp(settings: dict | None) -> dict:
    out = {}
    for k, v in (settings or {}).items():
        if k not in SETTING_KEYS:
            raise ServiceError(400, f"unknown setting {k!r}; allowed: {', '.join(sorted(SETTING_KEYS))} "
                                    "(see list_presets)")
        out[k] = ("1" if v else "0") if isinstance(v, bool) else (
            ",".join(str(x) for x in v) if isinstance(v, (list, tuple)) else str(v))
    return out


# ---- tools ----
@tool
def status() -> str:
    """BRouter reachability, region, stop-model weight set, flow index size and DEM coverage."""
    svc = service()
    h = svc.health()
    cov = svc.dem.coverage()
    cov_s = "none (no DEM tiles: climb/flat objectives fall back to even headings)" if cov is None else (
        f"lon {cov[0]:.2f}..{cov[2]:.2f}, lat {cov[1]:.2f}..{cov[3]:.2f}")
    return "\n".join([
        f"BRouter: {'reachable' if h['brouter'] else 'NOT reachable (use start_brouter)'}",
        f"Region: {h['region']}", f"Weight set: {h['weight_set']}", f"Flow index rows: {h['index_rows']}",
        f"DEM coverage: {cov_s}", f"Routes in session: {len(_state['sessions'])}"])


@tool
def start_brouter() -> str:
    """Start the local BRouter server (scripts/run_brouter.sh serve) if it is not reachable; waits up to 60 s."""
    client = service().client
    if client.health():
        return "already running"
    logf = Path(tempfile.gettempdir()) / "flow-brouter.log"
    with open(logf, "ab") as out:
        proc = subprocess.Popen([str(REPO / "scripts" / "run_brouter.sh"), "serve"], cwd=REPO,
                                stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    _state["brouter_proc"] = proc
    deadline = time.monotonic() + BROUTER_WAIT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return f"Error: BRouter exited with code {proc.returncode}; see {logf} (run `make planner-setup`?)"
        if client.health():
            return f"started BRouter, pid {proc.pid} (log {logf})"
        time.sleep(1.0)
    return f"Error: BRouter (pid {proc.pid}) did not become healthy within {BROUTER_WAIT_S} s; see {logf}"


@tool
def geocode(query: str, limit: int = 5) -> str:
    """Look up an Irish place name (Nominatim). Returns candidates with name and lat,lon."""
    hits = _geocode(query, limit)
    if not hits:
        return f"No results for {query!r} in Ireland."
    return "\n".join(f"{i}. {h['name']} -> {h['lat']:.5f},{h['lon']:.5f} ({h['type']})"
                     for i, h in enumerate(hits, 1))


@tool
def plan_route(mode: str, start: str, end: str | None = None, length_km: float | None = None,
               min_km: float | None = None, max_km: float | None = None, objective: str = "flow",
               n: int = 4, bearings: int = 8, return_mode: str = "same",
               settings: dict | None = None) -> str:
    """Plan routes. mode: loop | out_and_back | one_way. start/end: 'lat,lon' or a place name (geocoded; the
    resolved place is echoed). Loops and out-and-backs need length_km (+-10%) or min_km and max_km; one_way
    needs end and ignores length. objective: flow (fewest stops/turns) | climb | flat. return_mode: same | free.
    settings: optional dict from list_presets (e.g. turn_cost, lane_bonus, weights;
    main_road_penalty 1..5 multiplies the cost of primary/secondary/trunk roads, 2.5 = 'quiet roads' preset). Loops take 30-60 s.
    Returns a markdown table of ranked routes (use the ids with route_details / export_gpx) plus plan notes."""
    svc = service()
    echo = []
    s_ll, d = _resolve_point(start, "start")
    echo.append(d)
    qp = {"mode": mode, "from": s_ll, "objective": objective, "n": str(n), "bearings": str(bearings),
          "return": return_mode, **_settings_qp(settings)}
    if end:
        e_ll, d = _resolve_point(end, "end")
        qp["to"] = e_ll
        echo.append(d)
    for k, v in (("length_km", length_km), ("min_km", min_km), ("max_km", max_km)):
        if v is not None:
            qp[k] = str(v)
    resp, top = svc.plan_scored(qp)
    _remember(top)
    p = resp["plan"]
    lr = f", length {p['length_range'][0]:g}-{p['length_range'][1]:g} km" if p["length_range"] else ""
    out = [*echo, (f"Plan: {p['mode']}, objective {p['objective']}{lr}, {p['calls']} BRouter calls, "
                  f"{resp['timings_ms']['total'] / 1000:.1f} s{' (cached)' if resp['cached'] else ''}"),
           "", _table(resp)]
    if p["notes"]:
        out += ["", "Notes:", *(f"- {x}" for x in p["notes"])]
    if resp["skipped"]:
        out.append(f"\n{len(resp['skipped'])} BRouter request(s) were skipped (errors).")
    return "\n".join(out)


def _lookup(route_id: str):
    s = _state["sessions"].get(route_id.strip())
    if s is None:
        raise ServiceError(404, f"unknown route id {route_id!r}; ids come from plan_route "
                                f"(known: {', '.join(list(_state['sessions'])[-8:]) or 'none yet'})")
    return s


@tool
def route_details(route_id: str) -> str:
    """Explain a planned route: km by road class, cycle-infrastructure km, stop events, climbs, turns."""
    d = service().explain(_lookup(route_id))
    cyc = d["cycle_km"]
    lines = [(f"Route {d['id']}: {d['distance_km']:.1f} km, ascent {_fmt(d['ascent_m'], '{:.0f}')} m, "
             f"descent {_fmt(d['descent_m'], '{:.0f}')} m"),
             "km by road class: " + ", ".join(f"{k} {v:.1f}" for k, v in d["km_by_highway"].items()),
             (f"km on cycle infrastructure: {_cyc(cyc):.1f} of {cyc['total_km']:.1f} km (track {cyc['track']:.1f}, "
             f"lane {cyc['lane']:.1f}, path {cyc['path']:.1f})"),
             f"expected stops {d['expected_stops']:.2f} from {d['stop_events']} stop events; by cause: "
             + (", ".join(f"{k} {v['events']} ev/{v['expected']:.2f} exp"
                          for k, v in d["expected_stops_by_class"].items() if v["events"]) or "none"),
             f"turns {d['turns']} (sharp {d['sharp_turns']}), longest straight {d['longest_straight_km']:.1f} km",
             f"climb score {d['climb_score']:.0f}, {len(d['climbs'])} climb(s)"]
    for c in d["climbs"]:
        lines.append(f"- km {c['start_km']:.1f}-{c['end_km']:.1f}: {c['length_m'] / 1000:.1f} km, "
                     f"+{c['gain_m']:.0f} m, avg {c['avg_grade_pct']:.1f}%, max500 "
                     f"{c['max_500m_grade_pct']:.1f}%, {c['points']:.0f} pts ({c['category']})")
    return "\n".join(lines)


def _out_dir(out_dir: str) -> Path:
    raw = str(out_dir).strip()
    if not (raw.startswith("~") or Path(raw).is_absolute()):
        raise ServiceError(400, f"out_dir {out_dir!r} must be absolute or start with ~")
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        raise ServiceError(400, f"out_dir {str(p)!r} does not exist or is not a directory")
    return p


@tool
def export_gpx(route_id: str, name: str | None = None, out_dir: str = "~/Downloads") -> str:
    """Write a planned route as GPX 1.1 (with elevation) into out_dir (must exist; absolute or ~)."""
    s = _lookup(route_id)
    folder = _out_dir(out_dir)
    c, x = s.cand, s.extra
    p = c.plan or {}
    name = name or f"Flow {p.get('mode', 'route')} {c.length_m / 1000:.0f} km ({c.route_id})"
    ele = c.elevations if c.elevations and any(e is not None for e in c.elevations) else None
    desc = (f"{c.length_m / 1000:.1f} km, ascent {_fmt(x['ascent_m'], '{:.0f}')} m, "
            f"{s.expected_stops:.2f} expected stops, {s.score.turns} turns (bike-mapper flow planner)")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "route"
    path, i = folder / f"{stem}.gpx", 1
    while path.exists():
        path, i = folder / f"{stem}-{i}.gpx", i + 1
    write_gpx(path, name, c.geometry, ele, desc)
    return f"Wrote {path} ({path.stat().st_size} bytes, {len(c.geometry)} points" \
           f"{', with ' + x.get('elevation_source', 'brouter') + ' elevation' if ele else ', no elevation data'}).\n{GARMIN_HINT}"


@tool
def list_presets() -> str:
    """Settings presets (straight & lanes, plain flow, climb, flat) as dicts: pass `settings` to plan_route
    and `objective` as plan_route's objective argument."""
    return json.dumps(PRESETS, indent=2)


def _planner_url() -> str:
    return os.environ.get("FLOW_PLANNER_URL", "http://localhost:8081").rstrip("/")


def _fetch_pick(token: str) -> dict | None:
    """GET /api/pick/{token} -> payload, or None while nothing was sent (404). Raises on a dead server."""
    r = requests.get(f"{_planner_url()}/api/pick/{token}", timeout=5)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


@tool
def pick_points(n: int = 1, timeout_s: float = 300) -> str:
    """Ask the user to click 1 or 2 points on the planner map (opens the browser at the planner web page, which
    needs `make planner` running) and wait for them. Returns 'lat,lon' strings to use as start / end in plan_route."""
    if n not in (1, 2):
        return "Error: n must be 1 or 2"
    token = secrets.token_urlsafe(12)
    try:
        _fetch_pick(token)   # reachability check before bothering the user
    except requests.RequestException:
        return "Error: planner web server not running (make planner)"
    url = f"{_planner_url()}/#pick={token}&n={n}"
    try:
        opened = webbrowser.open(url)
    except Exception:  # noqa: BLE001
        opened = False
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while True:
        try:
            got = _fetch_pick(token)
        except requests.RequestException:
            return "Error: planner web server not running (make planner)"
        if got and got.get("points"):
            pts = got["points"][:n]
            lines = [f"{i}. {p['lat']:.6f},{p['lon']:.6f}" + (f" ({p['label']})" if p.get("label") else "")
                     for i, p in enumerate(pts, 1)]
            hint = ("Use the first as start" + (" and the second as end" if len(pts) > 1 else "")
                    + " in plan_route, e.g. start='" + f"{pts[0]['lat']:.6f},{pts[0]['lon']:.6f}'.")
            return "Picked " + f"{len(pts)} point(s):\n" + "\n".join(lines) + "\n" + hint
        if time.monotonic() >= deadline:
            return (f"Error: timed out after {timeout_s:g} s waiting for {n} point(s) in the browser"
                    + ("" if opened else f"; the browser could not be opened, visit {url}"))
        time.sleep(PICK_POLL_S)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
