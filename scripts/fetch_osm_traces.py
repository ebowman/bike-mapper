#!/usr/bin/env python3
"""Page the OSM public trackpoints API for a bbox; save raw GPX to data/gps/osm_trackpoints_pNNN.gpx.

Usage: uv run scripts/fetch_osm_traces.py [--bbox lon0,lat0,lon1,lat1] [--max-pages 60]
Stops at the first empty page (no <trkpt>). >= 1 s between calls, polite User-Agent.
"""
import argparse
import pathlib
import time

import subprocess

UA = "bike-mapper-research/0.1 (ebowman@boboco.ie)"
URL = "https://api.openstreetmap.org/api/0.6/trackpoints"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", default="-6.5,53.0,-6.1,53.3")
    ap.add_argument("--max-pages", type=int, default=60)
    ap.add_argument("--out", default="data/gps")
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for page in range(a.max_pages):
        # NB: requests/urllib3 is answered 429 by the OSM CDN (TLS fingerprint); curl is not.
        for attempt in range(6):
            r = subprocess.run(["curl", "-s", "-A", UA, "-w", "\n%{http_code}", f"{URL}?bbox={a.bbox}&page={page}"],
                               capture_output=True, text=True, timeout=180)
            body, _, code = r.stdout.rpartition("\n")
            if code not in ("429", "503", "000"):
                break
            wait = 30 * (attempt + 1)
            print(f"page {page}: HTTP {code}, back off {wait}s", flush=True)
            time.sleep(wait)
        if code != "200":
            raise SystemExit(f"page {page}: HTTP {code}")
        n = body.count("<trkpt")
        print(f"page {page}: {n} points, {len(body)} bytes", flush=True)
        if n == 0:
            break
        (out / f"osm_trackpoints_p{page:03d}.gpx").write_text(body)
        time.sleep(1.1)


if __name__ == "__main__":
    main()
