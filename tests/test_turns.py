import math

from flowplan.turns import turn_metrics

LAT0, LON0 = 53.3, -6.26
M_LAT = 111_320.0
M_LON = 111_320.0 * math.cos(math.radians(LAT0))


def geo(*xy):
    """Points in metres east/north of a Dublin origin -> [(lon, lat)]."""
    return [(LON0 + x / M_LON, LAT0 + y / M_LAT) for x, y in xy]


def test_straight_line_has_no_turns():
    m = turn_metrics(geo((0, 0), (100, 0), (300, 0), (1000, 0)))
    assert m["turns"] == 0 and m["sharp_turns"] == 0
    assert abs(m["longest_straight_km"] - 1.0) < 0.02


def test_square_has_four_turns_of_90():
    m = turn_metrics(geo((0, 0), (200, 0), (200, 200), (0, 200), (0, 0), (-1, 0)))
    # the closing vertex at (0,0) is the 4th corner (arrives from the north, leaves west by ~1 m)
    m2 = turn_metrics(geo((0, 0), (200, 0), (200, 200), (0, 200), (0, 0), (-100, 0)))
    assert m2["turns"] == 4 and m2["sharp_turns"] == 4
    assert all(abs(t["angle_deg"] - 90) < 5 for t in m2["turn_points"])
    assert m["turns"] >= 3


def test_s_bend_within_25m_counts_once():
    m = turn_metrics(geo((0, 0), (100, 0), (100, 10), (200, 10)))
    assert m["turns"] == 1


def test_gentle_20_degree_bend_is_not_a_turn():
    a = math.radians(20)
    m = turn_metrics(geo((0, 0), (100, 0), (100 + 100 * math.cos(a), 100 * math.sin(a))))
    assert m["turns"] == 0


def test_longest_straight_with_turn_and_stop_hit():
    g = geo((0, 0), (1000, 0), (1000, 500), (1000, 2000))  # 1 km east, turn, 2 km north
    m = turn_metrics(g)
    assert m["turns"] == 1
    assert abs(m["longest_straight_km"] - 2.0) < 0.02
    assert abs(m["mean_straight_km"] - 1.5) < 0.02
    m2 = turn_metrics(g, stop_hits=[{"p": 0.5, "dist_along_km": 0.5}, {"p": 0.01, "dist_along_km": 1.5}])
    # interruptions at 0.5 (stop) and 1.0 (turn); the p=0.01 hit is ignored: 0.5, 0.5, 2.0
    assert abs(m2["longest_straight_km"] - 2.0) < 0.02
    assert abs(m2["mean_straight_km"] - 1.0) < 0.02


def test_brouter_turn_cost_filters_geometry_bends():
    g = geo((0, 0), (100, 0), (100, 100), (200, 100), (200, 200))
    # the charge sits on the segment LEAVING the junction at g[2]: seg 2 ends at g[3], starts at g[2]
    segs = [{"lon": g[1][0], "lat": g[1][1], "turn_cost": 0.0},
            {"lon": g[2][0], "lat": g[2][1], "turn_cost": 0.0},
            {"lon": g[3][0], "lat": g[3][1], "turn_cost": 400.0},
            {"lon": g[4][0], "lat": g[4][1], "turn_cost": 0.0}]
    assert turn_metrics(g)["turns"] == 3
    assert turn_metrics(g, segs)["turns"] == 1
    small = [dict(sg, turn_cost=10.0) for sg in segs]
    assert turn_metrics(g, small)["turns"] == 3  # below the floor: geometry only
    zero = [{"lon": g[1][0], "lat": g[1][1], "turn_cost": 0.0}]
    assert turn_metrics(g, zero)["turns"] == 3  # no charges at all -> geometry only


def test_charged_segment_longer_than_25m_still_counts():
    g = geo((0, 0), (200, 0), (200, 150))  # 90 deg turn then a 150 m straight segment
    segs = [{"lon": g[1][0], "lat": g[1][1], "turn_cost": 0.0},
            {"lon": g[2][0], "lat": g[2][1], "turn_cost": 400.0, "dist_m": 150.0}]
    assert turn_metrics(g, segs)["turns"] == 1
