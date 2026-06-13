from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


RTMA_BUCKET_BASE = "https://noaa-rtma-pds.s3.amazonaws.com"
SVG_REDIRECT_URL = "https://commons.wikimedia.org/wiki/Special:Redirect/file/Usa_counties_large.svg"
CENSUS_COUNTY_ZIP_URL = "https://www2.census.gov/geo/tiger/TIGER2025/COUNTY/tl_2025_us_county.zip"

USER_AGENT = "county-temp-map/0.1 (https://commons.wikimedia.org/wiki/File:Usa_counties_large.svg)"

STATE_ABBRS = {
    "01": "AL",
    "02": "AK",
    "04": "AZ",
    "05": "AR",
    "06": "CA",
    "08": "CO",
    "09": "CT",
    "10": "DE",
    "11": "DC",
    "12": "FL",
    "13": "GA",
    "15": "HI",
    "16": "ID",
    "17": "IL",
    "18": "IN",
    "19": "IA",
    "20": "KS",
    "21": "KY",
    "22": "LA",
    "23": "ME",
    "24": "MD",
    "25": "MA",
    "26": "MI",
    "27": "MN",
    "28": "MS",
    "29": "MO",
    "30": "MT",
    "31": "NE",
    "32": "NV",
    "33": "NH",
    "34": "NJ",
    "35": "NM",
    "36": "NY",
    "37": "NC",
    "38": "ND",
    "39": "OH",
    "40": "OK",
    "41": "OR",
    "42": "PA",
    "44": "RI",
    "45": "SC",
    "46": "SD",
    "47": "TN",
    "48": "TX",
    "49": "UT",
    "50": "VT",
    "51": "VA",
    "53": "WA",
    "54": "WV",
    "55": "WI",
    "56": "WY",
}

INCLUDED_STATE_FIPS = frozenset(STATE_ABBRS)

CONUS_STATE_FIPS = INCLUDED_STATE_FIPS - {"02", "15"}


@dataclass(frozen=True)
class RegionSpec:
    name: str
    label: str
    state_fips: frozenset[str]

    def grib_key(self, yyyymmdd: str, hour: int) -> str:
        hh = f"{hour:02d}"
        if self.name == "conus":
            return f"rtma2p5.{yyyymmdd}/rtma2p5.t{hh}z.2dvaranl_ndfd.grb2_wexp"
        if self.name == "alaska":
            return f"akrtma.{yyyymmdd}/akrtma.t{hh}z.2dvaranl_ndfd_3p0.grb2"
        if self.name == "hawaii":
            return f"hirtma.{yyyymmdd}/hirtma.t{hh}z.2dvaranl_ndfd.grb2"
        raise ValueError(f"Unknown RTMA region: {self.name}")


RTMA_REGIONS = (
    RegionSpec("conus", "CONUS", frozenset(CONUS_STATE_FIPS)),
    RegionSpec("alaska", "Alaska", frozenset({"02"})),
    RegionSpec("hawaii", "Hawaii", frozenset({"15"})),
)


def default_cache_dir(root: Path | None = None) -> Path:
    return (root or Path.cwd()) / "work" / "cache"
