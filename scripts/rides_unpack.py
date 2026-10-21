#!/usr/bin/env python3
"""Turn the JSON batches produced by scripts/garmin_browser_pull.js into
data/rides/<activityId>.fit files plus data/rides/index.json.

Inputs (all gitignored, under data/rides/_batches/):
  list_NNN.json   output of gcPull.listPages()   -> {pages:[{start,count,activities:[...]}], done}
  batch_NNN.json  output of gcPull.downloadBatch -> [{id, ok, status, contentType, bytes, b64}]

Resume-safe: a batch entry whose .fit already exists on disk is skipped, and
index.json is rebuilt from scratch on every run from the list files + disk.

Usage:  uv run scripts/rides_unpack.py [--rides-dir data/rides]
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import zipfile
from pathlib import Path

INDOOR_TYPES = {"indoor_cycling", "virtual_ride"}


def load_activities(batches_dir: Path) -> list[dict]:
    """All raw activity dicts from list_*.json, newest first, de-duplicated by id."""
    seen: dict[int, dict] = {}
    for f in sorted(batches_dir.glob("list_*.json")):
        data = json.loads(f.read_text())
        for page in data["pages"]:
            for a in page["activities"]:
                seen.setdefault(a["activityId"], a)
    return sorted(seen.values(), key=lambda a: a["startTimeGMT"], reverse=True)


def unpack_batches(batches_dir: Path, rides_dir: Path) -> dict[int, dict]:
    """Write .fit files; return {activityId: {file, status, error}}."""
    results: dict[int, dict] = {}
    for f in sorted(batches_dir.glob("batch_*.json")):
        for entry in json.loads(f.read_text()):
            aid = int(entry["id"])
            if not entry.get("ok"):
                results[aid] = {"file": None, "error": f"HTTP {entry.get('status')} {entry.get('error', '')}".strip()}
                continue
            raw = base64.b64decode(entry["b64"])
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    members = zf.namelist()
                    # Original export: one <id>_ACTIVITY.fit (or .tcx/.gpx as uploaded)
                    name = next((m for m in members if m.lower().endswith((".fit", ".tcx", ".gpx"))), None)
                    if name is None:
                        results[aid] = {"file": None, "error": f"zip without ride file: {members}"}
                        continue
                    payload = zf.read(name)
                    ext = Path(name).suffix.lower()
            except zipfile.BadZipFile:
                # Not zipped: trust the magic bytes
                payload = raw
                ext = ".fit" if raw[8:12] == b".FIT" else ".bin"
            target = rides_dir / f"{aid}{ext}"
            if not target.exists():
                target.write_bytes(payload)
            results[aid] = {"file": target.name, "error": None}
    return results


def build_index(activities: list[dict], rides_dir: Path, results: dict[int, dict]) -> list[dict]:
    index = []
    for a in activities:
        aid = a["activityId"]
        type_key = a["activityType"]["typeKey"]
        on_disk = next((p.name for p in rides_dir.glob(f"{aid}.*")), None)
        row = {
            "activityId": aid,
            "activityName": a.get("activityName"),
            "startTimeGMT": a.get("startTimeGMT"),
            "startTimeLocal": a.get("startTimeLocal"),
            "distance_m": a.get("distance"),
            "duration_s": a.get("duration"),
            "typeKey": type_key,
            "deviceId": a.get("deviceId"),
            "manufacturer": a.get("manufacturer"),
            "hasPolyline": a.get("hasPolyline"),
            "downloaded": on_disk is not None,
            "file": on_disk,
        }
        if type_key in INDOOR_TYPES:
            row["reason"] = "indoor"
        elif on_disk is None:
            r = results.get(aid)
            row["reason"] = r["error"] if r and r.get("error") else "not_attempted"
        index.append(row)
    return index


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rides-dir", default="data/rides", type=Path)
    args = ap.parse_args()
    rides_dir: Path = args.rides_dir
    batches_dir = rides_dir / "_batches"
    rides_dir.mkdir(parents=True, exist_ok=True)

    activities = load_activities(batches_dir)
    if not activities:
        print(f"no list_*.json under {batches_dir}", file=sys.stderr)
        return 1
    results = unpack_batches(batches_dir, rides_dir)
    index = build_index(activities, rides_dir, results)
    (rides_dir / "index.json").write_text(json.dumps(index, indent=1))

    n = len(index)
    indoor = sum(1 for r in index if r.get("reason") == "indoor")
    outdoor = n - indoor
    dl = sum(1 for r in index if r["downloaded"])
    failed = [r for r in index if not r["downloaded"] and r.get("reason") != "indoor"]
    print(f"activities: {n}  indoor/virtual (skipped): {indoor}  outdoor: {outdoor}  downloaded: {dl}  failed: {len(failed)}")
    for r in failed:
        print(f"  FAIL {r['activityId']} {r['startTimeGMT']} {r['typeKey']}: {r['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
