import json
from datetime import datetime, timezone

import pytest

from sources import documents as sources

NOW = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
RSS = b'''<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Example chip launch</title><link>https://publisher.example/launch</link>
<pubDate>Fri, 09 Oct 2026 14:00:00 -0400</pubDate>
<description>&lt;p&gt;The company unveiled a new chip.&lt;/p&gt;</description>
<source>Example News</source></item>
<item><title>Market update</title><link>https://publisher.example/market</link></item>
<item><title>Duplicate</title><link>https://publisher.example/market</link></item>
<item><title>Unsafe link</title><link>file:///private/file</link></item>
<item><title>Future report</title><link>https://publisher.example/future</link>
<pubDate>Sat, 10 Oct 2026 14:00:00 -0400</pubDate></item>
</channel></rss>'''


def test_rss_preserves_links_dates_and_truthful_content_kind():
    docs = sources.parse_news_rss(RSS, "NVDA", seen_at=NOW)
    assert len(docs) == 2
    assert docs[0].content_text == "The company unveiled a new chip."
    assert docs[0].content_kind == "excerpt"
    assert docs[0].classification["role"] == "product_event"
    assert docs[0].source_name == "Example News"
    assert docs[0].source_url == "https://publisher.example/launch"
    assert docs[0].published_at == datetime(2026, 10, 9, 18, tzinfo=timezone.utc)
    assert docs[0].first_seen_at == NOW
    assert docs[1].content_kind == "headline"
    assert docs[1].content_text == "Market update"
    assert docs[1].published_at is None


def test_encoded_feed_body_is_still_marked_excerpt():
    xml = b'''<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item>
    <title>Results</title><link>https://example.com/results</link>
    <description>Short summary</description><content:encoded>&lt;p&gt;Longer text&lt;/p&gt;</content:encoded>
    </item></channel></rss>'''
    doc = sources.parse_news_rss(xml, "NVDA")[0]
    assert doc.content_text == "Longer text"
    assert doc.content_kind == "excerpt"


def test_entity_declarations_are_rejected():
    with pytest.raises(ValueError, match="DTD"):
        sources.parse_news_rss(b'<!DOCTYPE rss [<!ENTITY x "bad">]><rss/>', "NVDA")


@pytest.mark.parametrize("url", [
    "http://www.sec.gov/a", "https://127.0.0.1/a", "https://www.sec.gov.evil.example/a",
    "https://user:pass@www.sec.gov/a", "https://www.sec.gov:444/a",
    "https://publisher.example/article", "file:///tmp/file",
])
def test_fetch_allowlist_blocks_unaudited_urls(url):
    with pytest.raises(ValueError):
        sources.validate_fetch_url(url)


def test_redirect_revalidates_destination():
    handler = sources._ProviderRedirectHandler()
    request = sources.urllib.request.Request("https://www.sec.gov/a")
    with pytest.raises(ValueError):
        handler.redirect_request(request, None, 302, "Found", {}, "https://127.0.0.1/private")


def test_document_size_limit_rejects_instead_of_truncating(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return b"x" * size

    class Opener:
        def open(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(sources, "MAX_RESPONSE_BYTES", 100)
    monkeypatch.setattr(sources.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(ValueError, match="size limit"):
        sources._get("https://feeds.finance.yahoo.com/rss")


@pytest.mark.parametrize("url", ["https://127.0.0.1/a", "http://localhost/a", "http://[::1]/a"])
def test_private_citation_links_are_discarded(url):
    assert not sources._citation_url(url)


def test_html_extraction_removes_scripts_styles_and_hidden_xbrl():
    text = sources.text_from_html("<style>style</style><script>bad()</script><ix:hidden>hidden</ix:hidden><p>Revenue grew.</p><p>Risks remain.</p>")
    assert text == "Revenue grew.\nRisks remain."


def test_fetch_news_does_not_follow_publisher_links(monkeypatch):
    calls = []
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)

    def fake_get(url, user_agent=""):
        calls.append(url)
        return RSS

    monkeypatch.setattr(sources, "_get", fake_get)
    result = sources.fetch_documents("NVDA")
    assert len(calls) == 1
    assert "feeds.finance.yahoo.com" in calls[0]
    assert result.documents
    assert any("SEC filings disabled" in warning for warning in result.warnings)


def test_provider_failure_is_a_warning_not_crash(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)

    def fail(*args):
        raise TimeoutError("private diagnostics should not be exposed")

    monkeypatch.setattr(sources, "_get", fail)
    result = sources.fetch_documents("NVDA")
    assert result.documents == []
    assert any("TimeoutError" in warning for warning in result.warnings)
    assert not any("private diagnostics" in warning for warning in result.warnings)


def test_sec_fetches_official_primary_filing_text(monkeypatch):
    calls = []
    companies = {"0": {"cik_str": 1234, "ticker": "NVDA", "title": "Example Chips"}}
    submissions = {"filings": {"recent": {
        "form": ["10-Q", "10-Q", "4"],
        "accessionNumber": ["0000001234-26-000001", "0000001234-26-000002", "0000001234-26-000003"],
        "primaryDocument": ["report.htm", "older.htm", "form4.xml"],
        "filingDate": ["2026-10-08", "2026-07-08", "2026-10-01"],
        "acceptanceDateTime": ["2026-10-08T20:00:00Z", "2026-07-08T20:00:00Z", "2026-10-01T20:00:00Z"],
    }}}

    def fake_get(url, user_agent=""):
        calls.append(url)
        if url == sources.SEC_TICKERS:
            return json.dumps(companies).encode()
        if "submissions" in url:
            return json.dumps(submissions).encode()
        return b"<html><p>Revenue increased.</p><p>Competition remains a risk.</p></html>"

    monkeypatch.setattr(sources, "_get", fake_get)
    result = sources.fetch_sec_filings("NVDA", "", "FinancePrototype developer@example.com")
    assert len(calls) == 3
    assert result.warnings == []
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.content_kind == "full_text"
    assert doc.content_text == "Revenue increased.\nCompetition remains a risk."
    assert doc.classification["role"] == "company_info"
    assert doc.published_at == datetime(2026, 10, 8, 20, tzinfo=timezone.utc)
    assert doc.source_url == "https://www.sec.gov/Archives/edgar/data/1234/000000123426000001/report.htm"


def test_sec_requires_identifying_contact_before_requests(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda *args: pytest.fail("Should not fetch"))
    result = sources.fetch_sec_filings("NVDA", "", "anonymous")
    assert not result.documents
    assert result.warnings


def test_sec_rejects_unsafe_document_path(monkeypatch):
    companies = {"0": {"cik_str": 1234, "ticker": "NVDA"}}
    submissions = {"filings": {"recent": {
        "form": ["10-Q"], "accessionNumber": ["0000001234-26-000001"],
        "primaryDocument": ["../../private.htm"], "filingDate": ["2026-10-08"],
    }}}
    calls = []

    def fake_get(url, user_agent=""):
        calls.append(url)
        return json.dumps(companies if url == sources.SEC_TICKERS else submissions).encode()

    monkeypatch.setattr(sources, "_get", fake_get)
    result = sources.fetch_sec_filings("NVDA", "", "FinancePrototype developer@example.com")
    assert len(calls) == 2
    assert not result.documents
    assert "unsupported document path" in result.warnings[0]
