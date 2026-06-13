from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from exactextract import exact_extract

from county_temp_map.config import CENSUS_COUNTY_ZIP_URL, INCLUDED_STATE_FIPS, STATE_ABBRS
from county_temp_map.download import download_file
from county_temp_map.palette import NO_DATA_COLOR, build_dynamic_temperature_bins, color_for_temp_f, temp_c_to_f
from county_temp_map.rtma import RtmaProduct


def ensure_county_boundaries(cache_dir: Path, *, overwrite: bool = False) -> Path:
    return download_file(CENSUS_COUNTY_ZIP_URL, cache_dir / "census" / "tl_2025_us_county.zip", overwrite=overwrite)


def load_counties(county_zip: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(f"zip://{county_zip}")
    gdf = gdf[gdf["STATEFP"].isin(INCLUDED_STATE_FIPS)].copy()
    gdf["geoid"] = gdf["GEOID"].astype(str).str.zfill(5)
    gdf["state"] = gdf["STATEFP"].map(STATE_ABBRS)
    gdf["name"] = gdf["NAME"].astype(str)
    return gdf[["geoid", "name", "state", "STATEFP", "geometry"]]


def _raster_values_to_celsius(values: np.ndarray, tags: dict[str, str]) -> np.ndarray:
    data = values.astype("float64", copy=True)
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return data
    units = " ".join(str(value).lower() for key, value in tags.items() if "unit" in key.lower() or "grib" in key.lower())
    median = float(np.nanmedian(finite))
    if "k" in units and median > 150:
        return data - 273.15
    if median > 150:
        return data - 273.15
    return data


def _write_celsius_geotiff(product: RtmaProduct, cache_dir: Path, *, overwrite: bool = False) -> Path:
    target = cache_dir / "rtma" / product.valid_time.strftime("%Y%m%d_%HZ") / product.region.name / "tmp2m_celsius.tif"
    if target.exists() and target.stat().st_size > 0 and not overwrite:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(product.grib_path) as src:
        values = src.read(1, masked=True)
        filled = values.filled(np.nan)
        celsius = _raster_values_to_celsius(filled, src.tags(1) | src.tags())
        profile = src.profile.copy()
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
        profile.update(driver="GTiff", count=1, dtype="float32", nodata=np.nan, compress="deflate")
        with rasterio.open(target, "w", **profile) as dst:
            dst.write(celsius.astype("float32"), 1)
    return target


def _region_counties(counties: gpd.GeoDataFrame, product: RtmaProduct) -> gpd.GeoDataFrame:
    state_fips = product.region.state_fips
    return counties[counties["STATEFP"].isin(state_fips)].copy()


def _normalize_exact_result(result: object) -> tuple[float | None, float | None]:
    if isinstance(result, dict):
        properties = result.get("properties") if isinstance(result.get("properties"), dict) else result
        mean = properties.get("mean")
        coverage = properties.get("coverage")
        if coverage is None:
            coverage = properties.get("coverage_fraction")
        return _clean_float(mean), _clean_coverage(coverage)
    if isinstance(result, (list, tuple)):
        if len(result) >= 2:
            return _clean_float(result[0]), _clean_float(result[1])
        if len(result) == 1:
            return _clean_float(result[0]), None
    return _clean_float(result), None


def _clean_coverage(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, np.ndarray)):
        arr = np.asarray(value, dtype="float64")
        if arr.size == 0:
            return None
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            return None
        return float(np.nanmean(finite))
    return _clean_float(value)


def _clean_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def zonal_temperature_for_product(
    counties: gpd.GeoDataFrame,
    product: RtmaProduct,
    cache_dir: Path,
    *,
    overwrite: bool = False,
) -> pd.DataFrame:
    raster_path = _write_celsius_geotiff(product, cache_dir, overwrite=overwrite)
    subset = _region_counties(counties, product)
    if subset.empty:
        return pd.DataFrame()
    with rasterio.open(raster_path) as src:
        subset_projected = subset.to_crs(src.crs)

    stats = exact_extract(str(raster_path), subset_projected, ["mean", "coverage"])
    rows = []
    valid_time = product.valid_time.strftime("%Y-%m-%dT%H:00:00Z")
    for (_, county), result in zip(subset_projected.iterrows(), stats, strict=True):
        temp_c, coverage = _normalize_exact_result(result)
        temp_f = temp_c_to_f(temp_c) if temp_c is not None else None
        status = "ok" if temp_f is not None else "no_data"
        rows.append(
            {
                "geoid": county["geoid"],
                "name": county["name"],
                "state": county["state"],
                "rtma_region": product.region.label,
                "valid_time_utc": valid_time,
                "temp_c": round(temp_c, 3) if temp_c is not None else None,
                "temp_f": round(temp_f, 3) if temp_f is not None else None,
                "coverage_fraction": round(coverage, 6) if coverage is not None else None,
                "status": status,
            }
        )
    return pd.DataFrame(rows)


def aggregate_county_temperatures(
    counties: gpd.GeoDataFrame,
    products: list[RtmaProduct],
    cache_dir: Path,
    *,
    overwrite: bool = False,
) -> pd.DataFrame:
    frames = [zonal_temperature_for_product(counties, product, cache_dir, overwrite=overwrite) for product in products]
    combined = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True)
    all_counties = counties[["geoid", "name", "state"]].copy()
    merged = all_counties.merge(combined, on=["geoid", "name", "state"], how="left")
    merged["rtma_region"] = merged["rtma_region"].fillna("None")
    if not products:
        valid_time = ""
    else:
        valid_time = products[0].valid_time.strftime("%Y-%m-%dT%H:00:00Z")
    merged["valid_time_utc"] = merged["valid_time_utc"].fillna(valid_time)
    merged["status"] = merged["status"].fillna("no_data")
    bins = build_dynamic_temperature_bins(merged.loc[merged["status"] == "ok", "temp_f"])
    merged["color_hex"] = merged["temp_f"].apply(lambda value: color_for_temp_f(value, bins))
    merged.loc[merged["status"] != "ok", "color_hex"] = NO_DATA_COLOR
    return merged[
        [
            "geoid",
            "name",
            "state",
            "rtma_region",
            "valid_time_utc",
            "temp_c",
            "temp_f",
            "coverage_fraction",
            "color_hex",
            "status",
        ]
    ].sort_values("geoid")
