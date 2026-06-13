from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from county_temp_map.config import RTMA_REGIONS
from county_temp_map.geometry import zonal_temperature_for_product
from county_temp_map.rtma import GribByteRange, RtmaProduct


def test_area_weighted_mean_from_tiny_raster(tmp_path: Path) -> None:
    raster_path = tmp_path / "source.tif"
    transform = from_origin(0, 2, 1, 1)
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=transform,
        nodata=np.nan,
    ) as dst:
        dst.write(np.array([[10, 20], [30, 40]], dtype="float32"), 1)

    counties = gpd.GeoDataFrame(
        [{"geoid": "01001", "name": "Test", "state": "AL", "STATEFP": "01"}],
        geometry=[box(0, 0, 2, 2)],
        crs="EPSG:3857",
    )
    product = RtmaProduct(
        region=RTMA_REGIONS[0],
        valid_time=__import__("datetime").datetime(2026, 6, 12, 20, tzinfo=__import__("datetime").UTC),
        grib_url="",
        idx_url="",
        idx_path=tmp_path / "fake.idx",
        grib_path=raster_path,
        byte_range=GribByteRange(0, None),
    )

    result = zonal_temperature_for_product(counties, product, tmp_path, overwrite=True)
    assert result.loc[0, "temp_c"] == 25.0
    assert result.loc[0, "temp_f"] == 77.0
