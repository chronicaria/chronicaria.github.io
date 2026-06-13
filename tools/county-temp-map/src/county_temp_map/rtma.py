from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from county_temp_map.config import RTMA_BUCKET_BASE, RTMA_REGIONS, RegionSpec
from county_temp_map.download import download_byte_range, download_file, fetch_text, head_content_length


@dataclass(frozen=True)
class GribIndexRecord:
    number: int
    offset: int
    description: str


@dataclass(frozen=True)
class GribByteRange:
    start: int
    end_inclusive: int | None


@dataclass(frozen=True)
class RtmaProduct:
    region: RegionSpec
    valid_time: datetime
    grib_url: str
    idx_url: str
    idx_path: Path
    grib_path: Path
    byte_range: GribByteRange


def parse_idx(text: str) -> list[GribIndexRecord]:
    records: list[GribIndexRecord] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"Malformed GRIB index line: {raw_line!r}")
        number_text, offset_text, description = parts
        records.append(GribIndexRecord(int(number_text), int(offset_text), description))
    return records


def tmp_byte_range(records: list[GribIndexRecord], total_size: int | None = None) -> GribByteRange:
    for index, record in enumerate(records):
        if "TMP:2 m above ground" not in record.description:
            continue
        if index + 1 < len(records):
            return GribByteRange(record.offset, records[index + 1].offset - 1)
        if total_size is not None:
            return GribByteRange(record.offset, total_size - 1)
        return GribByteRange(record.offset, None)
    raise ValueError("Could not find TMP:2 m above ground in GRIB index")


def utc_hour(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware")
    return dt.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def parse_valid_time(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    return utc_hour(parsed)


def key_url(key: str) -> str:
    return f"{RTMA_BUCKET_BASE}/{key}"


def products_available(valid_time: datetime, *, session: requests.Session | None = None) -> bool:
    yyyymmdd = valid_time.strftime("%Y%m%d")
    hour = valid_time.hour
    for region in RTMA_REGIONS:
        key = region.grib_key(yyyymmdd, hour)
        idx_url = key_url(f"{key}.idx")
        try:
            fetch_text(idx_url, session=session, timeout=20)
        except Exception:
            return False
    return True


def find_latest_common_time(
    *,
    session: requests.Session | None = None,
    now: datetime | None = None,
    lookback_hours: int = 36,
) -> datetime:
    start = utc_hour(now or datetime.now(UTC))
    for age in range(lookback_hours + 1):
        candidate = start - timedelta(hours=age)
        if products_available(candidate, session=session):
            return candidate
    raise RuntimeError(f"No common RTMA hour found in the last {lookback_hours} hours")


def download_rtma_temperature_products(
    valid_time: datetime,
    cache_dir: Path,
    *,
    session: requests.Session | None = None,
    overwrite: bool = False,
) -> list[RtmaProduct]:
    yyyymmdd = valid_time.strftime("%Y%m%d")
    hour = valid_time.hour
    products: list[RtmaProduct] = []
    for region in RTMA_REGIONS:
        key = region.grib_key(yyyymmdd, hour)
        grib_url = key_url(key)
        idx_url = key_url(f"{key}.idx")
        region_dir = cache_dir / "rtma" / valid_time.strftime("%Y%m%d_%HZ") / region.name
        idx_path = download_file(idx_url, region_dir / f"{Path(key).name}.idx", session=session, overwrite=overwrite)
        idx_text = idx_path.read_text()
        total_size = head_content_length(grib_url, session=session)
        byte_range = tmp_byte_range(parse_idx(idx_text), total_size=total_size)
        grib_path = download_byte_range(
            grib_url,
            region_dir / f"{Path(key).name}.tmp2m.grb2",
            byte_range.start,
            byte_range.end_inclusive,
            session=session,
            overwrite=overwrite,
        )
        products.append(
            RtmaProduct(
                region=region,
                valid_time=valid_time,
                grib_url=grib_url,
                idx_url=idx_url,
                idx_path=idx_path,
                grib_path=grib_path,
                byte_range=byte_range,
            )
        )
    return products
