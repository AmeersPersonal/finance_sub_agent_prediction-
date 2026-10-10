"""Data sources outside yfinance: Yahoo Finance RSS headlines and BLS macro data.

The BLS's keyless API allows 25 requests a day per IP, so its response is cached
on disk for the day (backend/data/cache/, gitignored). Macro data is monthly,
so a day-old answer is never stale in practice.
"""

from __future__ import annotations

import html
import json
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

import pandas as pd

YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
BLS_SERIES = {
    "cpi": "CUUR0000SA0",  # CPI-U, all items, not seasonally adjusted
    "unemployment_rate": "LNS14000000",
    "payrolls_thousands": "CES0000000001",  # total nonfarm
}
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
TIMEOUT_SECONDS = 15


def _get(url: str, body: bytes | None = None) -> bytes:
    request = urllib.request.Request(
        url, data=body, headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def parse_rss_titles(xml: bytes, limit: int = 10) -> list[str]:
    titles = (item.findtext("title") for item in ElementTree.fromstring(xml).iter("item"))
    return [html.unescape(t).strip() for t in titles if t and t.strip()][:limit]


def fetch_headlines(ticker: str, limit: int = 10) -> list[str]:
    return parse_rss_titles(_get(YAHOO_RSS.format(ticker=quote(ticker))), limit)


def parse_bls(payload: dict) -> dict[str, pd.Series]:
    """Monthly series indexed by month start, oldest first. Months BLS didn't
    publish (shown as "-") are skipped."""
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError(f"BLS request failed: {payload.get('message')}")
    names = {series_id: name for name, series_id in BLS_SERIES.items()}
    result = {}
    for series in payload["Results"]["series"]:
        points = {}
        for point in series["data"]:
            period = point["period"]
            if not period.startswith("M") or period == "M13":  # M13 = annual average
                continue
            try:
                points[pd.Timestamp(int(point["year"]), int(period[1:]), 1)] = float(point["value"])
            except ValueError:
                continue
        result[names[series["seriesID"]]] = pd.Series(points, dtype=float).sort_index()
    return result


def fetch_bls(today: date | None = None, cache_dir: Path = CACHE_DIR) -> dict[str, pd.Series]:
    cache = cache_dir / f"bls_{(today or date.today()).isoformat()}.json"
    if cache.exists():
        return parse_bls(json.loads(cache.read_text(encoding="utf-8")))
    body = json.dumps({"seriesid": list(BLS_SERIES.values())}).encode()
    payload = json.loads(_get(BLS_URL, body))
    series = parse_bls(payload)  # raises before caching a failed response
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload), encoding="utf-8")
    return series
