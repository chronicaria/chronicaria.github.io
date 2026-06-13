# Current US County Temperature Map Generator

Generate a static county-level temperature map for the 50 states and DC using NOAA RTMA 2 m temperature analyses.

The CLI downloads the latest common RTMA hour for CONUS, Alaska, and Hawaii, computes county area-weighted mean temperatures, paints the Wikimedia county SVG by FIPS id, and writes SVG, PNG, and CSV outputs.

County colors are scaled dynamically for each generated map: the coldest county uses the deepest Wikipedia Democratic blue, the hottest county uses the deepest Wikipedia Republican red, and intermediate bins use only the exact colors from those Wikipedia ramps.

## Quick Start

```bash
uv run county-temp-map generate --latest --out-dir outputs
```

Generate a specific UTC hour:

```bash
uv run county-temp-map generate --time 2026-06-12T20:00Z --out-dir outputs
```

Use a custom cache:

```bash
uv run county-temp-map generate --latest --cache-dir work/cache --out-dir outputs
```

## Outputs

For a valid time like `20260612_20Z`, the generator writes:

- `outputs/county_temperature_20260612_20Z.svg`
- `outputs/county_temperature_20260612_20Z.png`
- `outputs/county_temperature_20260612_20Z.csv`

The CSV includes:

`geoid,name,state,rtma_region,valid_time_utc,temp_c,temp_f,coverage_fraction,color_hex,status`

## Data Sources

- NOAA RTMA data from the public `noaa-rtma-pds` S3 bucket.
- County boundaries from the official Census 2025 TIGER/Line county shapefile.
- SVG base map from Wikimedia Commons, `Usa_counties_large.svg`.
- Color ramps from the 2023 Wikipedia US election legend color proposal.

NOAA data is public; NOAA requests attribution and does not endorse derived products. The Wikimedia SVG is public domain as a US Census Bureau derivative.
