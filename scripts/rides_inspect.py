#!/usr/bin/env python3
"""Inspect the downloaded ride files in data/rides/.

Per file: number of record messages, median/mean record interval, share of
intervals > 2 s (Garmin "smart recording" thins points when speed is steady),
whether speed and position fields are present, and the recording device.

Prints a summary table plus the aggregate used in
docs/research/ride-data-acquisition.md.

Usage:  uv run scripts/rides_inspect.py [--rides-dir data/rides] [--sample N] [--seed S]
        --sample N  : only inspect N random files (the 3-file sanity check)
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import fitdecode

# Garmin product ids seen in file_id / device_info (garmin_product field)
# fitdecode already resolves most of these to names via the SDK profile.


def inspect_fit(path: Path) -> dict:
    ts: list[datetime] = []
    n_speed = n_pos = 0
    device = None
    product = None
    manufacturer = None
    sport = None
    with fitdecode.FitReader(path) as fr:
        for frame in fr:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            if frame.name == "record":
                t = frame.get_value("timestamp", fallback=None)
                if t is not None:
                    ts.append(t)
                if frame.has_field("speed") or frame.has_field("enhanced_speed"):
                    if (frame.get_value("speed", fallback=None) is not None
                            or frame.get_value("enhanced_speed", fallback=None) is not None):
                        n_speed += 1
                if frame.get_value("position_lat", fallback=None) is not None:
                    n_pos += 1
            elif frame.name == "file_id":
                manufacturer = frame.get_value("manufacturer", fallback=None)
                product = frame.get_value("garmin_product", fallback=None) or frame.get_value("product", fallback=None)
            elif frame.name == "device_info" and device is None:
                di = frame.get_value("device_index", fallback=None)
                if di in (0, "creator"):
                    device = (frame.get_value("manufacturer", fallback=None),
                              frame.get_value("garmin_product", fallback=None)
                              or frame.get_value("product_name", fallback=None)
                              or frame.get_value("product", fallback=None))
            elif frame.name == "sport":
                sport = (frame.get_value("sport", fallback=None), frame.get_value("sub_sport", fallback=None))
    ts.sort()
    gaps = [(b - a).total_seconds() for a, b in zip(ts, ts[1:])]
    gaps = [g for g in gaps if g > 0]
    med = statistics.median(gaps) if gaps else None
    mean = statistics.fmean(gaps) if gaps else None
    over2 = sum(1 for g in gaps if g > 2) / len(gaps) if gaps else None
    return {
        "file": path.name,
        "records": len(ts),
        "start": ts[0].isoformat() if ts else None,
        "median_dt": med,
        "mean_dt": mean,
        "share_gt2s": over2,
        "speed": n_speed,
        "position": n_pos,
        "manufacturer": str(manufacturer),
        "product": str(product),
        "creator": str(device),
        "sport": str(sport),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rides-dir", default="data/rides", type=Path)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--json", type=Path, help="also write per-file rows here")
    args = ap.parse_args()

    files = sorted(args.rides_dir.glob("*.fit"))
    if not files:
        print(f"no .fit files in {args.rides_dir}", file=sys.stderr)
        return 1
    if args.sample:
        files = random.Random(args.seed).sample(files, min(args.sample, len(files)))

    rows = []
    for f in files:
        try:
            rows.append(inspect_fit(f))
        except Exception as e:  # noqa: BLE001 - report and continue
            rows.append({"file": f.name, "error": repr(e)})

    hdr = f"{'file':<18}{'recs':>7}{'med_dt':>8}{'mean_dt':>9}{'>2s':>7}{'speed':>7}{'pos':>7}  product / creator"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        if "error" in r:
            print(f"{r['file']:<18}  ERROR {r['error']}")
            continue
        print(f"{r['file']:<18}{r['records']:>7}{(r['median_dt'] or 0):>8.1f}{(r['mean_dt'] or 0):>9.2f}"
              f"{(r['share_gt2s'] or 0)*100:>6.0f}%{r['speed']:>7}{r['position']:>7}  {r['product']} / {r['creator']}")

    ok = [r for r in rows if "error" not in r and r["records"] > 1]
    empty = [r for r in rows if "error" not in r and r["records"] <= 1]
    errors = [r for r in rows if "error" in r]
    one_sec = [r for r in ok if r["median_dt"] is not None and r["median_dt"] <= 2]
    smart = [r for r in ok if r["median_dt"] is not None and r["median_dt"] > 2]
    print()
    print(f"files: {len(rows)}  with records: {len(ok)}  empty (no record msgs): {len(empty)}  parse errors: {len(errors)}")
    if empty:
        print("  empty files:", ", ".join(r["file"] for r in empty))
    print(f"median record interval <= 2 s (1 s / 'every second' recording): {len(one_sec)}")
    print(f"median record interval  > 2 s (smart recording):                 {len(smart)}")
    if smart:
        print("  smart-recording files:", ", ".join(r["file"] for r in smart))
    print(f"records with speed: {sum(r['speed'] for r in ok)} / {sum(r['records'] for r in ok)}; "
          f"with position: {sum(r['position'] for r in ok)}")
    print("products:", Counter(f"{r['manufacturer']}/{r['product']}" for r in ok).most_common())
    print("mean share of gaps > 2 s across files: "
          f"{statistics.fmean(r['share_gt2s'] for r in ok if r['share_gt2s'] is not None)*100:.1f}%")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
