from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from county_temp_map.config import default_cache_dir
from county_temp_map.workflow import generate_map


@click.group()
def main() -> None:
    """Generate US county temperature maps from NOAA RTMA."""


@main.command()
@click.option("--latest", is_flag=True, help="Use the latest common RTMA hour for CONUS, Alaska, and Hawaii.")
@click.option("--time", "time_value", help="Specific valid UTC time, for example 2026-06-12T20:00Z.")
@click.option("--out-dir", type=click.Path(path_type=Path, file_okay=False), default=Path("outputs"), show_default=True)
@click.option("--cache-dir", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--overwrite-cache", is_flag=True, help="Redownload cached source files and RTMA messages.")
def generate(latest: bool, time_value: str | None, out_dir: Path, cache_dir: Path | None, overwrite_cache: bool) -> None:
    """Download RTMA data, aggregate temperatures, and write SVG/PNG/CSV outputs."""
    if latest == bool(time_value):
        raise click.UsageError("Choose exactly one of --latest or --time.")

    console = Console()
    result = generate_map(
        latest=latest,
        time_value=time_value,
        out_dir=out_dir,
        cache_dir=cache_dir or default_cache_dir(),
        overwrite=overwrite_cache,
        console=console,
    )
    console.print("[green]Done.[/green]")
    console.print(f"SVG: {result.svg_path}")
    console.print(f"CSV: {result.csv_path}")
    if result.png_ok:
        console.print(f"PNG: {result.png_path}")
    else:
        console.print(f"PNG: not written ({result.png_path})")
    console.print(f"Painted counties: {result.painted}; no-data counties: {result.no_data}")
