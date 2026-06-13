#!/usr/bin/env python3
"""Refresh the county temperature map and its summary stats.

Runs the vendored county-temp-map generator (tools/county-temp-map) for the
latest RTMA hour, then publishes:

  - assets/weather/county-temp.svg   (the painted county map)
  - data/weather.json                (hottest/coldest counties + national stats)

Pass --from-outputs DIR to skip generation and harvest an existing outputs
directory instead (uses the newest hour found there).

Stdlib only; the generator itself is invoked as a subprocess.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL_DIR = REPO_ROOT / "tools" / "county-temp-map"
SVG_DEST = REPO_ROOT / "assets" / "weather" / "county-temp.svg"
JSON_DEST = REPO_ROOT / "data" / "weather.json"

STAMP_RE = re.compile(r"county_temperature_(\d{8}_\d{2}Z)\.csv$")


def find_latest_outputs(out_dir: Path) -> tuple[Path, Path, str]:
    """Return (svg_path, csv_path, stamp) for the newest hour in out_dir."""
    stamps = []
    for path in out_dir.glob("county_temperature_*.csv"):
        match = STAMP_RE.search(path.name)
        if match:
            stamps.append(match.group(1))
    if not stamps:
        raise SystemExit(f"No county_temperature_*.csv files found in {out_dir}")
    stamp = max(stamps)
    svg_path = out_dir / f"county_temperature_{stamp}.svg"
    csv_path = out_dir / f"county_temperature_{stamp}.csv"
    if not svg_path.is_file():
        raise SystemExit(f"Missing SVG for stamp {stamp}: {svg_path}")
    return svg_path, csv_path, stamp


def run_generator(out_dir: Path, cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "county_temp_map",
        "generate",
        "--latest",
        "--out-dir",
        str(out_dir),
        "--cache-dir",
        str(cache_dir),
    ]
    env = dict(os.environ)
    src_dir = TOOL_DIR / "src"
    env["PYTHONPATH"] = str(src_dir) + os.pathsep + env.get("PYTHONPATH", "")
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, env=env)


def summarize(csv_path: Path) -> dict:
    rows = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") != "ok":
                continue
            try:
                temp_f = float(row["temp_f"])
            except (KeyError, TypeError, ValueError):
                continue
            rows.append(
                {
                    "name": row.get("name", ""),
                    "state": row.get("state", ""),
                    "temp_f": temp_f,
                    "valid_time_utc": row.get("valid_time_utc", ""),
                }
            )
    if not rows:
        raise SystemExit(f"No status==ok rows in {csv_path}")

    rows_sorted = sorted(rows, key=lambda r: r["temp_f"])
    temps = [r["temp_f"] for r in rows]

    def pick(items):
        return [
            {"name": r["name"], "state": r["state"], "temp_f": round(r["temp_f"], 1)}
            for r in items
        ]

    return {
        "valid_time_utc": rows[0]["valid_time_utc"],
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hottest": pick(reversed(rows_sorted[-3:])),
        "coldest": pick(rows_sorted[:3]),
        "national": {
            "min_f": round(min(temps), 1),
            "max_f": round(max(temps), 1),
            "mean_f": round(sum(temps) / len(temps), 1),
        },
    }


def publish(svg_path: Path, csv_path: Path) -> dict:
    SVG_DEST.parent.mkdir(parents=True, exist_ok=True)
    JSON_DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(svg_path, SVG_DEST)
    summary = summarize(csv_path)
    JSON_DEST.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-outputs",
        metavar="DIR",
        help="Skip generation; harvest the newest hour from an existing outputs dir.",
    )
    args = parser.parse_args()

    if args.from_outputs:
        out_dir = Path(args.from_outputs).expanduser().resolve()
        svg_path, csv_path, stamp = find_latest_outputs(out_dir)
    else:
        cache_dir = Path(
            os.environ.get("TEMP_MAP_CACHE", TOOL_DIR / "work")
        ).expanduser()
        with tempfile.TemporaryDirectory(prefix="county-temp-out-") as tmp:
            out_dir = Path(tmp)
            run_generator(out_dir, cache_dir)
            svg_path, csv_path, stamp = find_latest_outputs(out_dir)
            summary = publish(svg_path, csv_path)
            print(f"Published {stamp}: {SVG_DEST} + {JSON_DEST}")
            print(json.dumps(summary, indent=2))
            return

    summary = publish(svg_path, csv_path)
    print(f"Published {stamp}: {SVG_DEST} + {JSON_DEST}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
