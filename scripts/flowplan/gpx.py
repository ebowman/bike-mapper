"""GPX 1.1 writer (Garmin Connect importable): one track, optional elevations and course points."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

MAX_POINTS = 100_000
CREATOR = "bike-mapper flow planner"


def gpx_string(name: str, coords, elevations=None, desc: str | None = None,
               course_points=None, creator: str = CREATOR) -> str:
    """coords: [(lon, lat), ...]; elevations: parallel list of float|None (or None);
    course_points: [(lon, lat, name), ...] written as <rte>/<rtept> (omitted when empty/None)."""
    coords = list(coords)
    n = len(coords)
    if n < 2:
        raise ValueError(f"GPX needs at least 2 points, got {n}")
    if n > MAX_POINTS:
        raise ValueError(f"GPX has {n} points; the limit is {MAX_POINTS}")
    if elevations is not None and len(elevations) != n:
        raise ValueError(f"elevations length {len(elevations)} != coords length {n}")
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    root = (f'<gpx version="1.1" creator={quoteattr(creator)} '
            'xmlns="http://www.topografix.com/GPX/1/1" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://www.topografix.com/GPX/1/1 '
            'http://www.topografix.com/GPX/1/1/gpx.xsd">')
    out = ['<?xml version="1.0" encoding="UTF-8"?>', root,
           "<metadata>", f"<name>{escape(name)}</name>"]
    if desc:
        out.append(f"<desc>{escape(desc)}</desc>")
    out += [f"<time>{now}</time>", "</metadata>"]
    if course_points:
        out.append(f"<rte><name>{escape(name)}</name>")
        for p in course_points:
            out.append(f'<rtept lat="{p[1]:.6f}" lon="{p[0]:.6f}"><name>{escape(str(p[2]))}</name></rtept>')
        out.append("</rte>")
    out += [f"<trk><name>{escape(name)}</name><trkseg>"]
    for i, c in enumerate(coords):
        e = elevations[i] if elevations is not None else None
        ele = f"<ele>{e:.1f}</ele>" if e is not None else ""
        out.append(f'<trkpt lat="{c[1]:.6f}" lon="{c[0]:.6f}">{ele}</trkpt>')
    out += ["</trkseg></trk>", "</gpx>", ""]
    return "\n".join(out)


def write_gpx(path, name: str, coords, elevations=None, desc: str | None = None,
              course_points=None, creator: str = CREATOR) -> Path:
    path = Path(path)
    text = gpx_string(name, coords, elevations, desc, course_points, creator)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
