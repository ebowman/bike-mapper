"""Smoke test for docs/map: GeoJSON sanity + node --check of the inline script."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MAP = Path(__file__).resolve().parent.parent / "docs" / "map"
NAMES = ["stops_ireland", "stops_berlin", "ways_ireland", "ways_berlin", "routes",
         "unexplained_ireland", "unexplained_berlin"]


def coords(g):
    if g["type"] == "Point":
        yield g["coordinates"]
    elif g["type"] == "LineString":
        yield from g["coordinates"]
    else:
        raise AssertionError(f"unexpected geometry {g['type']}")


def main():
    total = 0
    for n in NAMES:
        p = MAP / "data" / f"{n}.geojson"
        d = json.loads(p.read_text())
        assert d["type"] == "FeatureCollection" and d["features"], f"{n}: empty"
        for f in d["features"]:
            for lon, lat in coords(f["geometry"]):
                assert -11 <= lon <= 14 and 51 <= lat <= 55, f"{n}: bad coord {lon},{lat}"
        size = p.stat().st_size
        assert size <= 2_000_000, f"{n}: {size} bytes > 2 MB"
        total += size
        print(f"ok {n}: {len(d['features'])} features, {size/1e6:.2f} MB")
    assert total <= 10_000_000
    html = (MAP / "index.html").read_text()
    blocks = [b for b in re.findall(r"<script>(.*?)</script>", html, re.DOTALL) if b.strip()]
    assert blocks, "no inline script"
    if shutil.which("node"):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "inline.js"
            f.write_text("\n".join(blocks))
            subprocess.run(["node", "--check", str(f)], check=True)
        print("ok node --check inline script")
    else:
        print("node not found: inline JS not syntax-checked")


if __name__ == "__main__":
    sys.exit(main())
