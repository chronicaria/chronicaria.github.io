#!/usr/bin/env python3
"""Build data/weather-hourly.json — per-county 2 m temperatures for the last N
RTMA hours, so the Temperature page can scrub hour-by-hour client-side.

Reuses the vendored county-temp-map generator (geometry + zonal stats). The
county SVG already carries id="c<FIPS>" per county, so the page recolours those
paths from this file; we only need {geoid: temp_f} per hour here.

Output (oldest -> newest):
  {
    "generated": "<iso>",
    "hours": [
      {"valid_utc": "...", "min_f": .., "max_f": .., "mean_f": ..,
       "temps": {"01069": 84.3, ...}},
      ...
    ]
  }

Usage: uv run --project tools/county-temp-map python scripts/update_weather_hourly.py [N]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "county-temp-map"
sys.path.insert(0, str(TOOL / "src"))

from county_temp_map.download import ensure_dir, make_session  # noqa: E402
from county_temp_map.geometry import (  # noqa: E402
    aggregate_county_temperatures,
    ensure_county_boundaries,
    load_counties,
)
from county_temp_map.rtma import (  # noqa: E402
    download_rtma_temperature_products,
    find_latest_common_time,
    utc_hour,
)

CACHE = TOOL / "work"
OUT = REPO / "data" / "weather-hourly.json"


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    session = make_session()
    ensure_dir(CACHE)
    county_zip = ensure_county_boundaries(CACHE)
    counties = load_counties(county_zip)

    latest = utc_hour(find_latest_common_time(session=session))
    print(f"Latest common RTMA hour: {latest:%Y-%m-%dT%H:00:00Z}; collecting {n} hours back")

    hours = []
    for k in range(n - 1, -1, -1):  # oldest -> newest
        vt = latest - timedelta(hours=k)
        try:
            products = download_rtma_temperature_products(vt, CACHE, session=session)
            data = aggregate_county_temperatures(counties, products, CACHE)
        except Exception as e:  # a missing hour just thins the slider
            print(f"  skip {vt:%Y-%m-%d %HZ}: {type(e).__name__}: {e}")
            continue
        ok = data[data["status"] == "ok"]
        temps = {str(g).zfill(5): round(float(t), 1) for g, t in zip(ok["geoid"], ok["temp_f"])}
        vals = list(temps.values())
        if not vals:
            print(f"  skip {vt:%Y-%m-%d %HZ}: no ok counties")
            continue
        hours.append({
            "valid_utc": vt.strftime("%Y-%m-%dT%H:00:00Z"),
            "min_f": round(min(vals), 1),
            "max_f": round(max(vals), 1),
            "mean_f": round(sum(vals) / len(vals), 1),
            "temps": temps,
        })
        print(f"  {vt:%Y-%m-%d %HZ}: {len(temps)} counties, {min(vals)}..{max(vals)}F")

    if not hours:
        raise SystemExit("No hours collected — aborting (keeping existing file).")

    names = {
        str(g).zfill(5): f"{nm}, {st}"
        for g, nm, st in zip(counties["geoid"], counties["name"], counties["state"])
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "names": names,
        "hours": hours,
    }
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    size_mb = OUT.stat().st_size / 1e6
    print(f"wrote {OUT.name}: {len(hours)} hours, {size_mb:.2f} MB")


if __name__ == "__main__":
    main()
