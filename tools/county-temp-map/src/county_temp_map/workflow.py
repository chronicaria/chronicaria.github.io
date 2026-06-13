from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console

from county_temp_map.download import ensure_dir, make_session
from county_temp_map.geometry import aggregate_county_temperatures, ensure_county_boundaries, load_counties
from county_temp_map.rtma import download_rtma_temperature_products, find_latest_common_time, parse_valid_time, utc_hour
from county_temp_map.svg_render import ensure_base_svg, export_png, render_svg


@dataclass(frozen=True)
class GenerationResult:
    valid_time: datetime
    svg_path: Path
    png_path: Path
    csv_path: Path
    png_ok: bool
    painted: int
    no_data: int


def generate_map(
    *,
    latest: bool,
    time_value: str | None,
    out_dir: Path,
    cache_dir: Path,
    overwrite: bool = False,
    console: Console | None = None,
) -> GenerationResult:
    active_console = console or Console()
    session = make_session()
    ensure_dir(out_dir)
    ensure_dir(cache_dir)

    if latest:
        active_console.print("Finding latest common RTMA hour...")
        valid_time = find_latest_common_time(session=session)
    elif time_value:
        valid_time = parse_valid_time(time_value)
    else:
        raise ValueError("Either --latest or --time is required")
    valid_time = utc_hour(valid_time)
    stamp = valid_time.strftime("%Y%m%d_%HZ")
    valid_time_utc = valid_time.strftime("%Y-%m-%dT%H:00:00Z")

    active_console.print(f"Using RTMA valid time {valid_time_utc}")
    active_console.print("Downloading/caching source SVG and Census counties...")
    base_svg = ensure_base_svg(cache_dir, overwrite=overwrite)
    county_zip = ensure_county_boundaries(cache_dir, overwrite=overwrite)
    counties = load_counties(county_zip)

    active_console.print("Downloading RTMA 2 m temperature messages...")
    products = download_rtma_temperature_products(valid_time, cache_dir, session=session, overwrite=overwrite)

    active_console.print("Computing area-weighted county means...")
    data = aggregate_county_temperatures(counties, products, cache_dir, overwrite=overwrite)

    csv_path = out_dir / f"county_temperature_{stamp}.csv"
    svg_path = out_dir / f"county_temperature_{stamp}.svg"
    png_path = out_dir / f"county_temperature_{stamp}.png"
    data.to_csv(csv_path, index=False)

    active_console.print("Painting SVG...")
    paint_stats = render_svg(base_svg, data, svg_path, valid_time_utc=valid_time_utc)
    active_console.print("Exporting PNG...")
    png_ok = export_png(svg_path, png_path)
    if not png_ok:
        active_console.print("[yellow]PNG export failed; SVG and CSV were written successfully.[/yellow]")

    return GenerationResult(
        valid_time=valid_time,
        svg_path=svg_path,
        png_path=png_path,
        csv_path=csv_path,
        png_ok=png_ok,
        painted=paint_stats["painted"],
        no_data=paint_stats["no_data"],
    )
