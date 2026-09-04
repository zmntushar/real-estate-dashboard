"""Disk-backed HTTP cache with retry and graceful degradation.

Zillow's national CSVs are megabytes and update monthly, so we persist them
locally as Parquet and only re-download when the copy goes stale. Some public
endpoints (FRED in particular) rate-limit aggressively and drop connections, so
every fetch retries with backoff and falls back to a stale local copy rather
than failing the page.
"""
from __future__ import annotations

import hashlib
import json
import ssl
import time
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import CACHE_DIR, CACHE_TTL_HOURS, REQUEST_TIMEOUT, USER_AGENT

# Corporate TLS-inspecting proxies install their root CA into the OS trust
# store, which certifi's bundle does not know about. truststore makes Python
# use the OS store, matching what curl/browsers already do on this machine.
try:  # pragma: no cover - environment dependent
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 - fall back to certifi if unavailable
    pass


class SourceUnavailable(RuntimeError):
    """Raised when an upstream dataset cannot be retrieved and no copy exists."""


def _slug(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _fresh(path: Path, ttl_hours: float) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < ttl_hours * 3600


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
    retry = Retry(
        total=4,
        backoff_factor=1.5,          # 0s, 1.5s, 3s, 6s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def _request(url: str, *, method: str = "GET", params: dict | None = None,
             payload: dict | None = None, attempts: int = 3) -> requests.Response:
    """Fetch with backoff across connection drops that Retry does not cover."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            s = session()
            if method == "POST":
                resp = s.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            else:
                resp = s.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp
        except (requests.RequestException, ssl.SSLError) as exc:
            last = exc
            if i < attempts - 1:
                time.sleep(1.5 * (2 ** i))
    raise last  # type: ignore[misc]


def cached_csv(
    url: str,
    ttl_hours: float = CACHE_TTL_HOURS,
    *,
    dtype: dict | None = None,
    sep: str = ",",
    label: str | None = None,
    **read_kwargs,
) -> pd.DataFrame:
    """Download a CSV once, then serve it from a local Parquet copy."""
    parquet = CACHE_DIR / f"{_slug(url)}.parquet"
    if _fresh(parquet, ttl_hours):
        try:
            return pd.read_parquet(parquet)
        except Exception:  # noqa: BLE001 - corrupt cache, refetch
            parquet.unlink(missing_ok=True)

    try:
        resp = _request(url)
    except Exception as exc:  # noqa: BLE001
        if parquet.exists():  # a stale copy beats an empty page
            return pd.read_parquet(parquet)
        raise SourceUnavailable(f"Could not download {label or url}: {exc}") from exc

    raw = CACHE_DIR / f"{_slug(url)}.raw"
    raw.write_bytes(resp.content)
    try:
        df = pd.read_csv(raw, dtype=dtype, sep=sep, low_memory=False, **read_kwargs)
    finally:
        raw.unlink(missing_ok=True)

    df.columns = [str(c) for c in df.columns]  # Parquet requires string names
    try:
        df.to_parquet(parquet, index=False)
    except Exception:  # noqa: BLE001 - caching is best-effort
        pass
    return df


def cached_json(url: str, ttl_hours: float = CACHE_TTL_HOURS, *, params: dict | None = None,
                method: str = "GET", payload: dict | None = None, label: str | None = None):
    """Download a JSON document once, then serve it from a local copy."""
    key = url + json.dumps(params or {}, sort_keys=True) + json.dumps(payload or {}, sort_keys=True)
    path = CACHE_DIR / f"{_slug(key)}.json"
    if _fresh(path, ttl_hours):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            path.unlink(missing_ok=True)

    try:
        resp = _request(url, method=method, params=params, payload=payload)
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        raise SourceUnavailable(f"Could not download {label or url}: {exc}") from exc

    try:
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return data


def cached_text(url: str, ttl_hours: float = CACHE_TTL_HOURS, *, label: str | None = None) -> str:
    path = CACHE_DIR / f"{_slug(url)}.txt"
    if _fresh(path, ttl_hours):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            path.unlink(missing_ok=True)
    try:
        resp = _request(url)
    except Exception as exc:  # noqa: BLE001
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
        raise SourceUnavailable(f"Could not download {label or url}: {exc}") from exc
    text = resp.content.decode("utf-8", errors="replace")
    try:
        path.write_text(text, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return text


def cache_stats() -> dict:
    files = [f for f in CACHE_DIR.glob("*") if f.is_file()]
    size = sum(f.stat().st_size for f in files)
    newest = max((f.stat().st_mtime for f in files), default=None)
    return {"files": len(files), "mb": size / 1_048_576, "newest": newest}


def clear_cache() -> int:
    n = 0
    for f in CACHE_DIR.glob("*"):
        if f.is_file():
            f.unlink(missing_ok=True)
            n += 1
    return n
