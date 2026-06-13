from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import requests

from county_temp_map.config import USER_AGENT


class DownloadError(RuntimeError):
    pass


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_file(
    url: str,
    dest: Path,
    *,
    session: requests.Session | None = None,
    overwrite: bool = False,
    timeout: int = 120,
) -> Path:
    if dest.exists() and dest.stat().st_size > 0 and not overwrite:
        return dest

    ensure_dir(dest.parent)
    active_session = session or make_session()
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with active_session.get(url, stream=True, timeout=timeout, allow_redirects=True) as response:
        if response.status_code >= 400:
            raise DownloadError(f"Failed to download {url}: HTTP {response.status_code}")
        with tmp.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    tmp.replace(dest)
    return dest


def fetch_text(url: str, *, session: requests.Session | None = None, timeout: int = 60) -> str:
    active_session = session or make_session()
    response = active_session.get(url, timeout=timeout)
    if response.status_code >= 400:
        raise DownloadError(f"Failed to fetch {url}: HTTP {response.status_code}")
    return response.text


def head_content_length(url: str, *, session: requests.Session | None = None, timeout: int = 60) -> int | None:
    active_session = session or make_session()
    response = active_session.head(url, timeout=timeout, allow_redirects=True)
    if response.status_code >= 400:
        return None
    value = response.headers.get("content-length")
    return int(value) if value and value.isdigit() else None


def download_byte_range(
    url: str,
    dest: Path,
    start: int,
    end_inclusive: int | None,
    *,
    session: requests.Session | None = None,
    overwrite: bool = False,
    timeout: int = 120,
) -> Path:
    if dest.exists() and dest.stat().st_size > 0 and not overwrite:
        return dest

    ensure_dir(dest.parent)
    active_session = session or make_session()
    range_value = f"bytes={start}-{end_inclusive if end_inclusive is not None else ''}"
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    response = active_session.get(url, headers={"Range": range_value}, stream=True, timeout=timeout)
    if response.status_code not in (200, 206):
        raise DownloadError(f"Failed to download range {range_value} from {url}: HTTP {response.status_code}")
    with response:
        with tmp.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    tmp.replace(dest)
    return dest


def safe_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    return name or "download"
