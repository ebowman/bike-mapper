"""Shared OSM road-network snapping helper (EPSG:2157, shapely STRtree over way segments).

    net = load_network("data/osm/ireland.osm.pbf", boxes=[(lon0, lat0, lon1, lat1), ...])
    seg, t, d = net.snap(x, y, max_m=20)    # nearest way segment per point (seg=-1 if none within max_m)
    node, dist = net.node_of(seg, t, x, y)  # nearest endpoint node of the snapped segment

Loaded: every `highway` way with >= 1 vertex in one of the boxes (except steps/proposed/construction/
elevator/corridor). Also keeps tags of tagged nodes (signals, stop, give_way, crossing, ...) for labelling.
The parsed network is pickled to data/cache/ (gitignored) because the Ireland pass takes minutes.
"""
import hashlib
import pickle
import pathlib

import numpy as np
import osmium
import shapely
from pyproj import Transformer
from shapely import STRtree

TR = Transformer.from_crs(4326, 2157, always_xy=True)
SKIP_HW = {"steps", "proposed", "construction", "elevator", "corridor", "razed", "abandoned"}
NODE_KEYS = ("highway", "crossing", "traffic_calming", "railway", "barrier")
NODE_HW = {"traffic_signals", "stop", "give_way", "crossing", "mini_roundabout", "turning_circle"}


def project(lon, lat):
    x, y = TR.transform(np.asarray(lon, float), np.asarray(lat, float))
    return np.asarray(x), np.asarray(y)


class Network:
    def __init__(self, ways, node_xy, node_tag):
        # ways: {way_id: (highway, roundabout, [node ids])}
        self.ways = {w: (hw, rb) for w, (hw, rb, _) in ways.items()}
        wid, na, nb, ax, ay, bx, by, widx = [], [], [], [], [], [], [], []
        self.way_ids = list(ways)
        for k, w in enumerate(self.way_ids):
            ns = ways[w][2]
            for i in range(len(ns) - 1):
                a, b = ns[i], ns[i + 1]
                if a == b:
                    continue
                na.append(a); nb.append(b)
                ax.append(node_xy[a][0]); ay.append(node_xy[a][1])
                bx.append(node_xy[b][0]); by.append(node_xy[b][1])
                widx.append(k)
        self.na = np.array(na, dtype=np.int64); self.nb = np.array(nb, dtype=np.int64)
        self.ax, self.ay, self.bx, self.by = (np.array(v) for v in (ax, ay, bx, by))
        self.way_of_seg = np.array(widx, dtype=np.int64)
        self.node_xy = node_xy
        self.node_tag = node_tag
        self._build()

    def _build(self):
        self.tree = STRtree(shapely.linestrings(np.stack([np.stack([self.ax, self.ay], 1),
                                                          np.stack([self.bx, self.by], 1)], 1)))

    def __getstate__(self):
        d = dict(self.__dict__); d.pop("tree", None); return d

    def __setstate__(self, d):
        self.__dict__.update(d); self._build()

    def hw_of_seg(self, seg):
        return self.ways[self.way_ids[self.way_of_seg[seg]]][0]

    def snap(self, x, y, max_m=20.0):
        """Return (seg index or -1, param t in [0,1] along the segment, distance m) per point."""
        n = len(x)
        seg = np.full(n, -1, dtype=np.int64); t = np.zeros(n); d = np.full(n, np.inf)
        pts = shapely.points(x, y)
        ii, jj = self.tree.query_nearest(pts, max_distance=max_m, all_matches=False)
        if len(ii):
            dx, dy = self.bx[jj] - self.ax[jj], self.by[jj] - self.ay[jj]
            L2 = np.maximum(dx * dx + dy * dy, 1e-9)
            tt = np.clip(((x[ii] - self.ax[jj]) * dx + (y[ii] - self.ay[jj]) * dy) / L2, 0, 1)
            px, py = self.ax[jj] + tt * dx, self.ay[jj] + tt * dy
            seg[ii] = jj; t[ii] = tt; d[ii] = np.hypot(x[ii] - px, y[ii] - py)
        return seg, t, d

    def node_of(self, seg, t, x, y):
        """Nearest endpoint node (id) of each snapped segment and its distance in m (-1/inf if unsnapped)."""
        node = np.full(len(seg), -1, dtype=np.int64); dist = np.full(len(seg), np.inf)
        ok = seg >= 0
        s = seg[ok]
        use_a = t[ok] < 0.5
        node[ok] = np.where(use_a, self.na[s], self.nb[s])
        ex = np.where(use_a, self.ax[s], self.bx[s]); ey = np.where(use_a, self.ay[s], self.by[s])
        dist[ok] = np.hypot(x[ok] - ex, y[ok] - ey)
        return node, dist


def load_network(pbf, boxes=(), points=None, cell=0.02, cache_dir="data/cache"):
    """boxes: [(lon0,lat0,lon1,lat1)]; points: (lon, lat) arrays -> all cells of `cell` degrees touched by a
    point plus the 8 neighbours (cheap union-of-buffers, avoids loading the whole bbox of far-apart rides)."""
    cells = set()
    if points is not None:
        for lo, la in set(zip(np.floor(points[0] / cell).astype(int).tolist(), np.floor(points[1] / cell).astype(int).tolist())):
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    cells.add((lo + di, la + dj))
    key = hashlib.md5((str(pathlib.Path(pbf).resolve()) + str(pathlib.Path(pbf).stat().st_mtime) + repr(sorted(boxes)) + repr(sorted(cells))).encode()).hexdigest()[:10]
    cp = pathlib.Path(cache_dir) / f"network_{key}.pkl"
    if cp.exists():
        return pickle.load(open(cp, "rb"))
    def inside(lon, lat):
        if cells and (int(lon // cell), int(lat // cell)) in cells:
            return True
        return any(b[0] <= lon <= b[2] and b[1] <= lat <= b[3] for b in boxes)
    ways, ll, tags = {}, {}, {}
    fp = osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations()
    for o in fp:
        if o.is_node():
            if len(o.tags) and inside(o.lon, o.lat):
                tg = {k: o.tags[k] for k in NODE_KEYS if k in o.tags}
                if tg:
                    tags[o.id] = tg
            continue
        hw = o.tags.get("highway")
        if hw is None or hw in SKIP_HW:
            continue
        pts, ins = [], False
        for n in o.nodes:
            if not n.location.valid():
                continue
            pts.append((n.ref, n.lon, n.lat))
            ins = ins or inside(n.lon, n.lat)
        if ins and len(pts) >= 2:
            ways[o.id] = (hw, o.tags.get("junction") in ("roundabout", "circular"), [p[0] for p in pts])
            for r, lo, la in pts:
                ll[r] = (lo, la)
    ids = list(ll)
    xs, ys = project([ll[i][0] for i in ids], [ll[i][1] for i in ids])
    node_xy = {i: (float(x), float(y)) for i, x, y in zip(ids, xs, ys)}
    node_ll = ll
    net = Network(ways, node_xy, tags)
    net.node_ll = node_ll
    net.tagged_ll = {}
    cp.parent.mkdir(parents=True, exist_ok=True)
    pickle.dump(net, open(cp, "wb"), protocol=4)
    return net
