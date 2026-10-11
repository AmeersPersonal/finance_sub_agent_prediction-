import json
from datetime import date

import pandas as pd
import pytest

import ai.feeds as feeds
from ai.feeds import BLS_SERIES, fetch_bls, parse_bls, parse_rss_items, parse_rss_titles

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Yahoo! Finance: AAPL News</title>
<item><title>Apple &amp; partners raise guidance</title>
<link>https://finance.yahoo.com/news/apple-guidance</link>
<pubDate>Thu, 08 Oct 2026 20:00:00 +0000</pubDate>
<description>&lt;p&gt;Apple lifted its outlook.&lt;/p&gt;</description></item>
<item><title>   </title></item>
<item><title>iPhone demand softens</title></item>
</channel></rss>"""


def bls_payload(status="REQUEST_SUCCEEDED"):
    def series(name, values):
        data = [{"year": y, "period": p, "value": v} for y, p, v in values]
        return {"seriesID": BLS_SERIES[name], "data": data}

    return {
        "status": status,
        "message": [] if status == "REQUEST_SUCCEEDED" else ["limit reached"],
        "Results": {
            "series": [
                series("cpi", [("2026", "M09", "335.1"), ("2026", "M08", "334.9"),
                               ("2025", "M13", "320.0"), ("2025", "M10", "-")]),
                series("unemployment_rate", [("2026", "M09", "4.2")]),
                series("payrolls_thousands", [("2026", "M09", "159044")]),
            ]
        },
    }


def test_parse_rss_titles_skips_blank_items():
    assert parse_rss_titles(RSS) == ["Apple & partners raise guidance", "iPhone demand softens"]


def test_parse_rss_items_keep_links_and_strip_markup():
    first, second = parse_rss_items(RSS)
    assert first.link == "https://finance.yahoo.com/news/apple-guidance"
    assert first.published == "Thu, 08 Oct 2026 20:00:00 +0000"
    assert first.summary == "Apple lifted its outlook."
    assert second.link is None and second.summary is None


def test_old_bls_cache_files_are_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr(feeds, "_get", lambda url, body=None: json.dumps(bls_payload()).encode())
    (tmp_path / "bls_2026-09-01.json").write_text("{}")  # 38 days old
    (tmp_path / "bls_2026-10-05.json").write_text("{}")  # 4 days old, kept
    (tmp_path / "notes.json").write_text("{}")  # not a cache file, never touched
    fetch_bls(date(2026, 10, 9), cache_dir=tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "bls_2026-10-05.json", "bls_2026-10-09.json", "notes.json"
    ]


def test_parse_bls_skips_annual_averages_and_unpublished_months():
    series = parse_bls(bls_payload())
    cpi = series["cpi"]
    assert list(cpi.index) == [pd.Timestamp("2026-08-01"), pd.Timestamp("2026-09-01")]
    assert cpi.iloc[-1] == 335.1
    assert series["unemployment_rate"].iloc[0] == 4.2


def test_parse_bls_raises_on_failed_request():
    with pytest.raises(ValueError, match="limit reached"):
        parse_bls(bls_payload(status="REQUEST_NOT_PROCESSED"))


def test_fetch_bls_caches_for_the_day(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, body=None):
        calls.append(url)
        return json.dumps(bls_payload()).encode()

    monkeypatch.setattr(feeds, "_get", fake_get)
    first = fetch_bls(date(2026, 10, 9), cache_dir=tmp_path)
    second = fetch_bls(date(2026, 10, 9), cache_dir=tmp_path)
    assert len(calls) == 1
    pd.testing.assert_series_equal(first["cpi"], second["cpi"])
    fetch_bls(date(2026, 10, 10), cache_dir=tmp_path)  # a new day fetches again
    assert len(calls) == 2


def test_fetch_bls_does_not_cache_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(feeds, "_get", lambda url, body=None: json.dumps(bls_payload("X")).encode())
    with pytest.raises(ValueError):
        fetch_bls(date(2026, 10, 9), cache_dir=tmp_path)
    assert not list(tmp_path.iterdir())
