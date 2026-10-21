#!/usr/bin/env python3
"""Shrink a stops_per_km sample CSV to the ways listed in an observed_ways CSV (the ways actually ridden).

Usage: uv run scripts/filter_ways_csv.py <stops_per_km.csv> <observed_ways.csv> [--min-km 0.0]
Rewrites the first file in place; the unfiltered version stays in the gitignored *_full.csv.
"""
import csv
import sys

src, ridden = sys.argv[1], sys.argv[2]
with open(ridden) as f:
    ids = {r["way_id"] for r in csv.DictReader(f)}
with open(src) as f:
    rows = list(csv.reader(f))
keep = [rows[0]] + [r for r in rows[1:] if r[0] in ids]
with open(src, "w", newline="") as f:
    csv.writer(f).writerows(keep)
print(f"{src}: {len(rows) - 1} -> {len(keep) - 1} ways")
