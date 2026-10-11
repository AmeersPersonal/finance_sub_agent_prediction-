"""Data sources outside yfinance: Yahoo Finance RSS headlines and BLS macro data.

The BLS's keyless API allows 25 requests a day per IP, so its response is cached
on disk for the day (backend/data/cache/, gitignored). Macro data is monthly,
so a day-old answer is never stale in practice.
"""

from __future__ import annotations

import html
import json
import re
import urllib.request
from dataclasses import dataclass
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
CACHE_KEEP_DAYS = 7  # older daily BLS files are deleted; only today's is ever read
TIMEOUT_SECONDS = 15
_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str | None = None
    published: str | None = None  # as the feed gives it
    summary: str | None = None
    source: str | None = None


def _get(url: str, body: bytes | None = None) -> bytes:
    request = urllib.request.Request(
        url, data=body, headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def _text(raw: str | None) -> str | None:
    cleaned = html.unescape(_TAG.sub("", raw or "")).strip()
    return cleaned or None


def parse_rss_items(xml: bytes, limit: int = 10) -> list[NewsItem]:
    items = []
    for item in ElementTree.fromstring(xml).iter("item"):
        title = _text(item.findtext("title"))
        if title:
            items.append(
                NewsItem(
                    title=title,
                    link=_text(item.findtext("link")),
                    published=_text(item.findtext("pubDate")),
                    summary=_text(item.findtext("description")),
                    source="Yahoo Finance",
                )
            )
    return items[:limit]


def parse_rss_titles(xml: bytes, limit: int = 10) -> list[str]:
    return [item.title for item in parse_rss_items(xml, limit)]


def fetch_news(ticker: str, limit: int = 10) -> list[NewsItem]:
    return parse_rss_items(_get(YAHOO_RSS.format(ticker=quote(ticker))), limit)


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
    today = today or date.today()
    cache = cache_dir / f"bls_{today.isoformat()}.json"
    if cache.exists():
        return parse_bls(json.loads(cache.read_text(encoding="utf-8")))
    body = json.dumps({"seriesid": list(BLS_SERIES.values())}).encode()
    payload = json.loads(_get(BLS_URL, body))
    series = parse_bls(payload)  # raises before caching a failed response
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload), encoding="utf-8")
    prune_cache(cache_dir, today)
    return series


def prune_cache(cache_dir: Path, today: date, keep_days: int = CACHE_KEEP_DAYS) -> None:
    """Delete daily BLS cache files older than `keep_days`. Only bls_<date>.json files
    are touched; the prediction log is never pruned (it's the scoring record)."""
    for path in cache_dir.glob("bls_*.json"):
        try:
            day = date.fromisoformat(path.stem.removeprefix("bls_"))
        except ValueError:
            continue
        if (today - day).days > keep_days:
            path.unlink(missing_ok=True)
