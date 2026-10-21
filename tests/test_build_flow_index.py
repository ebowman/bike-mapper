import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("bfi", Path(__file__).parent.parent / "scripts" / "build_flow_index.py")
bfi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bfi)

NODES = [(10, 53.0, -6.0), (11, 53.1, -6.1), (12, 53.2, -6.2)]


def ev(d, idx, nid):
    return {"way_id": "1", "dir": d, "vertex_idx": str(idx), "node_id": str(nid), "cause": "stop", "amount": "1"}


def test_fwd_middle():
    row, st = bfi.build_row(NODES, ev("fwd", 1, 11))
    assert st == "ok" and row["from_node_id"] == 10 and row["lat"] == "53.1000000" and row["from_lon"] == "-6.0000000"


def test_bwd_middle():
    row, st = bfi.build_row(NODES, ev("bwd", 1, 11))
    assert st == "ok" and row["from_node_id"] == 12


def test_fwd_at_first_vertex():
    row, st = bfi.build_row(NODES, ev("fwd", 0, 10))
    assert st == "no_from_vertex" and row["from_lat"] == "" and row["from_node_id"] == "" and row["lat"]


def test_bwd_at_last_vertex():
    row, st = bfi.build_row(NODES, ev("bwd", 2, 12))
    assert st == "no_from_vertex" and row["from_lon"] == ""


def test_node_elsewhere_fallback():
    row, st = bfi.build_row(NODES, ev("fwd", 0, 12))
    assert st == "ok" and row["node_id"] == 12 and row["from_node_id"] == 11


def test_missing_node_dropped():
    row, st = bfi.build_row(NODES, ev("fwd", 0, 99))
    assert row is None and st == "dropped_missing_vertex"
