import asyncio
import os
import re
import shutil
import sys
from pathlib import Path

import flow_mcp
import gpxpy
import pytest
from flowplan.scoring import FLOW_DIR
from flowplan.terrain import Dem

from tests.test_plan_api import Hilly

needs_index = pytest.mark.skipif(not (FLOW_DIR / "ireland.index.csv").exists(), reason="flow index missing")
START = "53.2990,-6.2825"
END = "53.2210,-6.2150"


@pytest.fixture(scope="module")
def svc():
    return flow_mcp.build_service(Hilly(), Dem(paths=[]))


@pytest.fixture(autouse=True)
def inject(svc):
    flow_mcp.set_service(svc)
    svc.cache = type(svc.cache)()
    yield
    flow_mcp.set_service(None)


def ids(text):
    return re.findall(r"^\| \d+ \| (\S+) \|", text, re.MULTILINE)


@needs_index
def test_plan_one_way_table_with_ids():
    out = flow_mcp.plan_route("one_way", START, end=END, n=3)
    assert "| rank | id |" in out and "start: 53.2990,-6.2825" in out
    got = ids(out)
    assert got and len(got) == len(set(got))
    assert not out.startswith("Error")


@needs_index
def test_plan_loop_in_range_and_details_and_gpx(tmp_path):
    out = flow_mcp.plan_route("loop", START, length_km=45, bearings=4, objective="climb", n=3)
    got = ids(out)
    assert got and all("@" in i for i in got)
    kms = [float(r.split("|")[5]) for r in out.splitlines() if re.match(r"\| \d+ \|", r)]
    assert kms and all(40.5 <= k <= 49.5 for k in kms)
    d = flow_mcp.route_details(got[0])
    assert "km by road class" in d and "turns" in d and "climb score" in d
    w = flow_mcp.export_gpx(got[0], out_dir=str(tmp_path))
    assert "Garmin Connect" in w
    f = next(tmp_path.glob("*.gpx"))
    g = gpxpy.parse(f.read_text())
    pts = g.tracks[0].segments[0].points
    assert len(pts) > 2 and all(p.elevation is not None for p in pts)


@needs_index
def test_unknown_id_and_bad_inputs(tmp_path):
    assert flow_mcp.route_details("nope/alt9").startswith("Error: unknown route id")
    assert flow_mcp.export_gpx("nope/alt9", out_dir=str(tmp_path)).startswith("Error")
    assert flow_mcp.plan_route("loop", START).startswith("Error: 'length_km'")
    assert flow_mcp.plan_route("one_way", START, end=END, settings={"bogus": 1}).startswith("Error: unknown setting")
    assert flow_mcp.plan_route("loop", "48.1,11.5", length_km=40).startswith("Error")


@needs_index
def test_export_dir_validation(tmp_path):
    got = ids(flow_mcp.plan_route("one_way", START, end=END, n=1))
    assert "does not exist" in flow_mcp.export_gpx(got[0], out_dir=str(tmp_path / "missing"))
    assert "absolute or start with ~" in flow_mcp.export_gpx(got[0], out_dir="relative/dir")
    a = flow_mcp.export_gpx(got[0], out_dir=str(tmp_path))
    b = flow_mcp.export_gpx(got[0], out_dir=str(tmp_path))
    assert a != b and len(list(tmp_path.glob("*.gpx"))) == 2


def test_place_name_geocoded(monkeypatch):
    monkeypatch.setattr(flow_mcp, "_geocode", lambda q, n=5: [{"name": "Rathfarnham, Dublin", "lat": 53.299,
                                                               "lon": -6.2825, "type": "suburb"}])
    p, d = flow_mcp._resolve_point("Rathfarnham", "start")
    assert p == "53.299,-6.2825" and "Rathfarnham, Dublin" in d


def test_list_presets_shape():
    import json
    p = json.loads(flow_mcp.list_presets())
    assert [x["name"] for x in p] == ["straight & lanes", "plain flow", "quiet roads", "climb", "flat"]
    assert p[0]["settings"]["turn_cost"] == 400 and p[1]["settings"]["lane_exit_cost"] == 0
    assert next(x for x in p if x["name"] == "quiet roads")["settings"]["main_road_penalty"] == 2.5
    assert {x["objective"] for x in p} == {"flow", "climb", "flat"}


def test_status_and_start_brouter_idempotent():
    assert "BRouter: reachable" in flow_mcp.status()
    assert flow_mcp.start_brouter() == "already running"


@pytest.mark.skipif(os.environ.get("RUN_NETWORK_TESTS") != "1", reason="network test; set RUN_NETWORK_TESTS=1")
def test_geocode_network():
    out = flow_mcp.geocode("Rathfarnham", 3)
    assert "Rathfarnham" in out and "->" in out


def test_stdio_smoke():
    mcp_client = pytest.importorskip("mcp.client.stdio")
    from mcp import ClientSession, StdioServerParameters
    if shutil.which("uv") is None:
        pytest.skip("uv not available")
    root = Path(__file__).resolve().parents[1]

    async def run():
        params = StdioServerParameters(command="uv", args=["run", "scripts/flow_mcp.py"], cwd=str(root))
        async with mcp_client.stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            return sorted(t.name for t in (await s.list_tools()).tools)

    names = asyncio.run(asyncio.wait_for(run(), 90))
    assert names == sorted(["status", "pick_points", "start_brouter", "geocode", "plan_route", "route_details",
                            "export_gpx", "list_presets"])
    assert sys.platform  # server stdout carried only MCP frames or initialize would have failed


@needs_index
def test_route_details_resolves_same_heading_routes(monkeypatch):
    from tests.test_plan_api import _two_same_heading
    _two_same_heading(monkeypatch)
    out = flow_mcp.plan_route("loop", START, length_km=45, bearings=4, objective="climb", n=6)
    rows = [r.split("|") for r in out.splitlines() if re.match(r"\| \d+ \|", r)]
    byid = {r[2].strip(): float(r[5]) for r in rows}
    same = [i for i in byid if "@90." in i]
    assert len(same) >= 2 and len(byid) == len(rows)
    for i in same:
        d = flow_mcp.route_details(i)
        assert d.startswith(f"Route {i}: {byid[i]:.1f} km")
    assert len({byid[i] for i in same}) == len(same)


@needs_index
def test_plan_route_passes_main_road_penalty_to_brouter():
    seen = []

    class Rec(Hilly):
        def route(self, points, profile="fastbike", alternativeidx=0, params=None):
            seen.append(dict(params or {}))
            return super().route(points, profile, alternativeidx, params)

    flow_mcp.set_service(flow_mcp.build_service(Rec(), Dem(paths=[])))
    out = flow_mcp.plan_route("one_way", START, end=END, n=1, settings={"main_road_penalty": 2.5})
    assert not out.startswith("Error") and "main-road km" in out
    assert any(p.get("main_road_penalty") == 2.5 for p in seen if p.get("flow_scale"))
    assert all(p.get("main_road_penalty") == 1.0 for p in seen if p.get("flow_scale") == 0)  # baseline fixed
