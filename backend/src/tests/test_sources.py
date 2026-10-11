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


def test_rss_with_company_keeps_only_items_naming_the_stock():
    xml = b'''<rss><channel>
    <item><title>Why CrowdStrike Holdings Stock Crushed it on Friday</title><link>https://example.com/1</link></item>
    <item><title>Chip stocks rally</title><link>https://example.com/2</link>
    <description>Nvidia led the semiconductor index higher.</description></item>
    <item><title>$NVDA options volume jumps</title><link>https://example.com/3</link></item>
    <item><title>nvda lowercase is not the ticker</title><link>https://example.com/4</link></item>
    </channel></rss>'''
    docs = sources.parse_news_rss(xml, "NVDA", seen_at=NOW, company="NVIDIA")
    assert [d.source_url for d in docs] == ["https://example.com/2", "https://example.com/3"]
    assert len(sources.parse_news_rss(xml, "NVDA", seen_at=NOW)) == 4  # no company: unfiltered


def test_one_letter_ticker_does_not_match_ordinary_words():
    about = sources.mentions("F", "Ford Motor")
    assert about.search("Ford Motor recalls trucks") and about.search("F shares slip")
    assert not about.search("a look at f-strings") and not about.search("half of fords")


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
        return b'{"hits": []}' if "hn.algolia.com" in url else RSS

    monkeypatch.setattr(sources, "_get", fake_get)
    result = sources.fetch_documents("NVDA")
    # Yahoo, Google News for news and for product/rumor coverage, then Hacker News
    # story search; no publisher pages.
    assert len(calls) == 4
    assert "feeds.finance.yahoo.com" in calls[0]
    assert all("news.google.com/rss/search" in url for url in calls[1:3])
    assert calls[3].startswith("https://hn.algolia.com/api/v1/search?")
    assert result.documents
    # The same story from several feeds is kept once.
    assert len({d.source_url for d in result.documents}) == len(result.documents)
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


GOOGLE_RSS = b"""<rss><channel>
<item><title>Example Chips stock slides after guidance - Market Daily</title>
<link>https://news.google.com/rss/articles/abc?oc=5</link>
<pubDate>Fri, 09 Oct 2026 15:00:00 GMT</pubDate>
<description>&lt;a href="https://news.google.com/rss/articles/abc?oc=5"&gt;Example Chips stock slides after guidance - Market Daily&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font color="#6f6f6f"&gt;Market Daily&lt;/font&gt;</description>
<source url="https://marketdaily.example">Market Daily</source></item>
<item><title>Example Chips reportedly readies new AI accelerator - Tech Wire</title>
<link>https://news.google.com/rss/articles/def?oc=5</link>
<pubDate>Thu, 08 Oct 2026 15:00:00 GMT</pubDate>
<source url="https://techwire.example">Tech Wire</source></item>
</channel></rss>"""


def test_google_news_items_are_headlines_with_publisher_and_query_role(monkeypatch):
    calls = []

    def fake_get(url, user_agent=""):
        calls.append(url)
        return GOOGLE_RSS

    monkeypatch.setattr(sources, "_get", fake_get)
    result = sources.fetch_google_news("NVDA", "Example Chips Corporation", seen_at=NOW)
    assert result.warnings == []
    assert len(calls) == 2
    assert "%22NVDA%22" in calls[0] and "%22Example%20Chips%22" in calls[1]  # legal suffix dropped
    news = [d for d in result.documents if d.metadata["search"] == "news"]
    product = [d for d in result.documents if d.metadata["search"] == "product"]
    first = news[0]
    assert first.title == "Example Chips stock slides after guidance"
    assert first.source_name == "Market Daily"
    # The description only repeats the headline, so it is not an excerpt.
    assert first.content_kind == "headline"
    assert first.content_text == first.title
    assert first.metadata["provider"] == "google_news_rss"
    assert first.classification == {"role": "public_opinion", "method": "keyword", "unconfirmed": False}
    # Keyword roles are coarse: "readies" is not a product keyword, but the rumor wording is flagged.
    assert news[1].classification == {"role": "public_opinion", "method": "keyword", "unconfirmed": True}
    assert all(d.classification["role"] == "product_event" and d.classification["method"] == "query"
               for d in product)
    assert product[1].classification["unconfirmed"] is True


def test_google_news_failure_is_a_warning(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    result = sources.fetch_google_news("NVDA")
    assert result.documents == []
    assert [w.split(" evidence")[0] for w in result.warnings] == ["Google News news", "Google News product"]


@pytest.mark.parametrize("name, expected", [
    ("Apple Inc.", "Apple"), ("NVIDIA Corporation", "NVIDIA"), ("Alphabet Inc. Class A", "Alphabet"),
    ('Odd "Name" Holdings, Ltd.', "Odd Name"), ("", ""),
])
def test_company_query_name_drops_legal_suffixes(name, expected):
    assert sources.company_query_name(name) == expected


INDEX_HTML = """<table class="tableFile">
<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th></tr>
<tr><td>1</td><td>8-K</td><td><a href="/ix?doc=/Archives/edgar/data/1234/000000123426000009/form8k.htm">form8k.htm</a></td><td>8-K</td></tr>
<tr><td>2</td><td>PRESS RELEASE</td><td><a href="/Archives/edgar/data/1234/000000123426000009/ex991.htm">ex991.htm</a></td><td>EX-99.1</td></tr>
</table>"""


def test_exhibit_991_is_found_only_inside_its_filing():
    accession = "0000001234-26-000009"
    assert sources.exhibit_991_url(INDEX_HTML, 1234, accession) == \
        "https://www.sec.gov/Archives/edgar/data/1234/000000123426000009/ex991.htm"
    elsewhere = INDEX_HTML.replace("/1234/000000123426000009/ex991", "/9999/000000999926000001/ex991")
    assert sources.exhibit_991_url(elsewhere, 1234, accession) is None
    assert sources.exhibit_991_url(INDEX_HTML.replace("EX-99.1", "EX-10.1"), 1234, accession) is None


def test_sec_fetches_8k_press_releases_with_roles(monkeypatch):
    companies = {"0": {"cik_str": 1234, "ticker": "NVDA", "title": "Example Chips"}}
    submissions = {"filings": {"recent": {
        "form": ["8-K", "8-K", "8-K", "8-K"],
        "accessionNumber": ["0000001234-26-000009", "0000001234-26-000008",
                            "0000001234-26-000007", "0000001234-26-000006"],
        "primaryDocument": ["form8k.htm"] * 4,
        "items": ["2.02,9.01", "5.02", "8.01,9.01", "7.01"],
        "filingDate": ["2026-10-08", "2026-09-20", "2026-09-01", "2026-08-01"],
        "acceptanceDateTime": ["2026-10-08T20:00:00Z"] * 4,
    }}}
    calls = []

    def fake_get(url, user_agent=""):
        calls.append(url)
        if url == sources.SEC_TICKERS:
            return json.dumps(companies).encode()
        if "submissions" in url:
            return json.dumps(submissions).encode()
        if url.endswith("-index.htm"):
            folder = url.split("/")[-2]
            if folder == "000000123426000008":  # an officer change with no press release
                return b"<table><tr><td>8-K</td></tr></table>"
            return INDEX_HTML.replace("000000123426000009", folder).encode()
        if url.endswith("ex991.htm"):
            if "000000123426000009" in url:
                return b"<p>Example Chips reports third-quarter revenue of $10 billion.</p>"
            return b"<p>Example Chips unveils its next-generation accelerator.</p>"
        return b"<p>Cover page.</p>"

    monkeypatch.setattr(sources, "_get", fake_get)
    result = sources.fetch_sec_filings("NVDA", "Example Chips", "FinancePrototype developer@example.com")
    assert result.warnings == []
    releases = [d for d in result.documents if d.document_type == "announcement"]
    assert len(releases) == 2  # press_release_limit; the 7.01 filing is never requested
    assert not any("000000123426000006" in url for url in calls)
    earnings, product = releases
    assert earnings.classification["role"] == "company_info"
    assert earnings.classification["method"] == "8k_item"
    assert earnings.metadata["form"] == "8-K EX-99.1"
    assert earnings.metadata["ticker"] == "NVDA"
    assert earnings.content_kind == "full_text"
    assert earnings.source_url.endswith("/000000123426000009/ex991.htm")
    assert product.classification["role"] == "product_event"
    assert "unveils" in product.content_text


def test_forum_hosts_other_than_hacker_news_are_not_allowlisted():
    sources.validate_fetch_url("https://news.google.com/rss/search?q=x")
    sources.validate_fetch_url("https://hn.algolia.com/api/v1/search?query=x")
    for url in ("https://www.reddit.com/r/stocks.json", "https://oauth.reddit.com/r/stocks/search?q=x"):
        with pytest.raises(ValueError):
            sources.validate_fetch_url(url)


HN_STORIES = {"hits": [
    {"objectID": "101", "title": "Example Chips ships new GPU", "points": 300, "num_comments": 80,
     "created_at_i": 1791500000, "url": "https://publisher.example/gpu", "author": "poster"},
    {"objectID": "102", "title": "Unrelated story that only links to examplechips.com", "points": 50,
     "created_at_i": 1791500000},
    {"objectID": "103", "title": "Ask HN: Is $NVDA overvalued?", "story_text": "<p>Thoughts?</p>",
     "points": 40, "num_comments": 0, "created_at_i": 1791500000},
    {"objectID": "104", "title": "Example Chips from the future", "created_at_i": 1891900000},
    {"objectID": "../x", "title": "Example Chips bad id", "created_at_i": 1791500000},
]}
HN_ITEMS = {
    "101": {"type": "story", "kids": [201, 202, 203, 204]},
    "201": {"type": "comment", "parent": 101, "text": "Rumor says yields are poor.<p>Second paragraph", "by": "alice"},
    "202": {"type": "comment", "deleted": True},
    "203": {"type": "comment", "dead": True, "text": "flagged"},
    "204": {"type": "comment", "text": "x" * 500},
    "103": {"type": "story"},
}


def _hn_get(calls):
    def fake_get(url, user_agent=""):
        calls.append(url)
        if url.startswith("https://hn.algolia.com/"):
            return json.dumps(HN_STORIES).encode()
        item = url.rsplit("/", 1)[-1].removesuffix(".json")
        return json.dumps(HN_ITEMS.get(item)).encode()
    return fake_get


def test_hacker_news_stories_carry_ranked_top_level_comments(monkeypatch):
    calls = []
    monkeypatch.setattr(sources, "_get", _hn_get(calls))
    result = sources.fetch_hacker_news("NVDA", "Example Chips Corp", seen_at=NOW)
    assert result.warnings == []
    assert "query=Example+Chips" in calls[0] and "points%3E%3D20" in calls[0]
    # Only titles naming the company or ticker, from the past, with numeric ids.
    assert [d.source_url for d in result.documents] == [
        "https://news.ycombinator.com/item?id=101", "https://news.ycombinator.com/item?id=103"]
    story, ask = result.documents
    assert story.content_text.splitlines()[:3] == [
        "Example Chips ships new GPU", "Top-level comments:", "- Rumor says yields are poor. Second paragraph"]
    assert story.content_text.endswith("x" * 400 + "...")  # long comments are trimmed
    assert story.metadata["comments_included"] == 2  # deleted and dead comments skipped
    assert story.metadata["linked_url"] == "https://publisher.example/gpu"
    assert story.classification == {"role": "public_opinion", "method": "source_type", "unconfirmed": True}
    assert story.document_type == "forum" and story.content_kind == "excerpt"
    assert story.published_at == datetime(2026, 10, 8, 22, 53, 20, tzinfo=timezone.utc)
    assert "alice" not in story.content_text and "poster" not in json.dumps(story.metadata)
    assert ask.content_text == "Ask HN: Is $NVDA overvalued?\nThoughts?"
    # Every request stays on the two HN API hosts.
    assert all(url.startswith(("https://hn.algolia.com/", "https://hacker-news.firebaseio.com/"))
               for url in calls)


def test_hacker_news_comment_failure_keeps_the_story(monkeypatch):
    def fake_get(url, user_agent=""):
        if url.startswith("https://hn.algolia.com/"):
            return json.dumps(HN_STORIES).encode()
        raise TimeoutError()

    monkeypatch.setattr(sources, "_get", fake_get)
    result = sources.fetch_hacker_news("NVDA", "Example Chips", story_limit=1, seen_at=NOW)
    assert [d.content_kind for d in result.documents] == ["headline"]
    assert result.warnings == ["Hacker News comments unavailable (TimeoutError)"]


def test_hacker_news_search_failure_is_a_warning(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda *a, **k: (_ for _ in ()).throw(ValueError()))
    result = sources.fetch_hacker_news("NVDA")
    assert result.documents == []
    assert result.warnings == ["Hacker News evidence unavailable (ValueError)"]
