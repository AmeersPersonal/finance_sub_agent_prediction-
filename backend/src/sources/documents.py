"""Collect feed evidence, Hacker News discussion and optional official SEC text.

Every document carries a role: company_info (the company's own filings and press
releases), public_opinion (news coverage and forum posts) or product_event
(launches, announcements and rumors). Retrieval mixes the roles per strategy.

Publisher links are retained as citations, never followed to scrape articles.
Feed summaries are explicitly excerpts, not full articles or public-opinion polls.
Google News RSS gives headlines only; its feed terms allow personal,
non-commercial reading, which fits this learning prototype and nothing more.
SEC downloading is opt-in through SEC_USER_AGENT (application + contact email).
Hacker News discussion comes from the keyless Algolia HN Search API (stories)
and the official HN Firebase API (top-level comments in HN's ranking order).
All fetched URLs and redirects stay on a fixed HTTPS provider allowlist.
"""

from __future__ import annotations

import json
import ipaddress
import os
import re
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import quote, urlencode, urlsplit
from xml.etree import ElementTree

YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
HN_SEARCH = "https://hn.algolia.com/api/v1/search?{params}"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
ALLOWED_HOSTS = frozenset({
    "feeds.finance.yahoo.com", "news.google.com", "www.sec.gov", "data.sec.gov", "sec.gov",
    "hn.algolia.com", "hacker-news.firebaseio.com",
})
PRODUCT_TERMS = re.compile(
    r"\b(launch\w*|announc\w*|unveil\w*|introduc\w*|product\w*|rumou?r\w*|leak\w*)\b", re.I)
UNCONFIRMED_TERMS = re.compile(r"\b(rumou?r\w*|leak\w*|reportedly|speculat\w*|unconfirmed)\b", re.I)
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 15
_sec_lock = threading.Lock()
_sec_last_request = 0.0


@dataclass(frozen=True)
class SourceDocument:
    source_url: str
    title: str
    content_text: str
    document_type: str
    content_kind: str
    source_name: str
    published_at: datetime | None
    first_seen_at: datetime
    classification: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass
class DocumentCollection:
    documents: list[SourceDocument] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_fetch_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Online fetch URL must use an approved HTTPS provider")
    return url


class _ProviderRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_fetch_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url: str, user_agent: str = "FinanceLearningPrototype/1.0") -> bytes:
    """Bound request size/time, forbid off-provider redirects; no publisher scraping."""
    global _sec_last_request
    validate_fetch_url(url)
    if urlsplit(url).hostname in {"www.sec.gov", "sec.gov", "data.sec.gov"}:
        # One process stays well below SEC's 10 requests/second fair-access ceiling.
        with _sec_lock:
            delay = 0.15 - (time.monotonic() - _sec_last_request)
            if delay > 0:
                time.sleep(delay)
            _sec_last_request = time.monotonic()
    request = urllib.request.Request(url, headers={
        "User-Agent": user_agent,
        "Accept": "application/json, application/rss+xml, text/html, text/plain",
    })
    opener = urllib.request.build_opener(_ProviderRedirectHandler())
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("Provider response exceeds the document size limit")
    return data


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "ix:hidden"}:
            self.suppressed += 1
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "ix:hidden"} and self.suppressed:
            self.suppressed -= 1
        if tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.suppressed:
            self.parts.append(data)


def text_from_html(value: str) -> str:
    parser = _TextParser()
    parser.feed(value)
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    # A timezone-free date is not a reliable publication timestamp.
    if result.tzinfo is None:
        return None
    return result.astimezone(timezone.utc)


def _citation_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if host.lower() == "localhost" or host.lower().endswith(".localhost"):
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            pass
        return (parsed.scheme in {"https", "http"} and bool(parsed.hostname)
                and not parsed.username and not parsed.password)
    except ValueError:
        return False


def _norm(value: str) -> str:
    return re.sub(r"\W+", "", value.lower())


def _adds_text(summary: str, title: str, source_name: str) -> bool:
    """Whether a feed description says more than the headline and publisher name.

    Google News descriptions only repeat the linked headline and publisher.
    """
    rest = _norm(summary).replace(_norm(title), "", 1)
    if source_name:
        rest = rest.replace(_norm(source_name), "")
    return bool(rest)


def classify(text: str, default_role: str | None = None) -> dict:
    """Keyword role for news-like text; a query-chosen role wins when given."""
    if default_role:
        role, method = default_role, "query"
    else:
        role = "product_event" if PRODUCT_TERMS.search(text) else "public_opinion"
        method = "keyword"
    return {"role": role, "method": method, "unconfirmed": bool(UNCONFIRMED_TERMS.search(text))}


def mentions(ticker: str, company: str = ""):
    """Pattern for text naming the stock: the ticker as written ($NVDA, NVDA) or the company.

    The ticker is case-sensitive so one-letter tickers don't match ordinary words.
    """
    pattern = r"(?<![\w$])\$?" + re.escape(ticker.upper()) + r"\b"
    if company:
        pattern += r"|(?i:\b" + re.escape(company) + r"\b)"
    return re.compile(pattern)


def parse_news_rss(xml: bytes, ticker: str, limit: int = 10,
                   seen_at: datetime | None = None, *, provider: str = "yahoo_rss",
                   default_source: str = "Yahoo Finance RSS",
                   role: str | None = None, company: str = "") -> list[SourceDocument]:
    """Feed items as documents. With `company`, items naming neither it nor the
    ticker are dropped: Yahoo's per-ticker feed mixes in general market stories."""
    if limit <= 0:
        return []
    # ElementTree does not fetch external entities; reject DTD input explicitly.
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ValueError("Provider feed cannot contain a DTD or entity declarations")
    seen_at = seen_at or datetime.now(timezone.utc)
    about = mentions(ticker, company) if company else None
    root = ElementTree.fromstring(xml)
    documents = []
    seen_links = set()
    for item in root.iter("item"):
        title = text_from_html(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        if not title or not _citation_url(link) or link in seen_links:
            continue
        source_node = item.find("source")
        source_name = (source_node.text or "").strip() if source_node is not None else ""
        if source_name and title.endswith(f" - {source_name}"):
            title = title[: -len(source_name) - 3].strip()  # Google News appends the publisher
        # content:encoded, when supplied, can still be a teaser. Never call it full text.
        body = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
        summary = text_from_html(body or item.findtext("description") or "")
        if summary and not _adds_text(summary, title, source_name):
            summary = ""
        published = _parse_date(item.findtext("pubDate"))
        if published is not None and published > seen_at:
            continue
        if about is not None and not about.search(title + " " + summary):
            continue
        documents.append(SourceDocument(
            source_url=link, title=title, content_text=summary or title,
            document_type="news", content_kind="excerpt" if summary else "headline",
            source_name=source_name or default_source, published_at=published,
            first_seen_at=seen_at, classification=classify(title + " " + summary, role),
            metadata={"ticker": ticker.upper(), "provider": provider, "text_origin": "feed_body" if summary else "feed_title",
                      "publication_time_known": published is not None,
                      "coverage": "Publisher-supplied feed excerpt; not a population sentiment measure"},
        ))
        seen_links.add(link)
        if len(documents) >= limit:
            break
    return documents


def company_query_name(company_name: str) -> str:
    """'Apple Inc.' -> 'Apple': legal suffixes make news searches miss."""
    name = re.sub(r'["()]', " ", company_name).strip()
    suffix = re.compile(r"[,.]?\s+(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|"
                        r"holdings|group|n\.?v|s\.?a|ag|se|class\s+[a-z])\.?$", re.I)
    while (shorter := suffix.sub("", name)) != name:
        name = shorter.strip()
    return re.sub(r"\s+", " ", name)


def fetch_google_news(ticker: str, company_name: str = "", limit: int = 8,
                      seen_at: datetime | None = None) -> DocumentCollection:
    """Two Google News searches: ticker news, and product launches/rumors.

    Items are headlines linked through news.google.com; links are never followed.
    """
    result = DocumentCollection()
    company = company_query_name(company_name) or ticker
    searches = (
        ("news", f'"{ticker}" stock when:7d', None),
        ("product", f'"{company}" (launch OR unveil OR announces OR product OR rumor OR leak) when:30d',
         "product_event"),
    )
    for label, query, role in searches:
        try:
            xml = _get(GOOGLE_NEWS_RSS.format(query=quote(query, safe="")))
            documents = parse_news_rss(xml, ticker, limit, seen_at, provider="google_news_rss",
                                       default_source="Google News", role=role)
            for document in documents:
                document.metadata["search"] = label
            result.documents.extend(documents)
        except Exception as exc:
            result.warnings.append(f"Google News {label} evidence unavailable ({type(exc).__name__})")
    return result


class _IndexTableParser(HTMLParser):
    """Rows of an EDGAR filing index table: cell texts plus the row's links."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[list[str], list[str]]] = []
        self._cells: list[str] | None = None
        self._links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._cells, self._links = [], []
        elif tag == "td" and self._cells is not None:
            self._cells.append("")
        elif tag == "a" and self._cells is not None:
            href = dict(attrs).get("href")
            if href:
                self._links.append(href)

    def handle_endtag(self, tag):
        if tag == "tr" and self._cells is not None:
            self.rows.append(([c.strip() for c in self._cells], self._links))
            self._cells = None

    def handle_data(self, data):
        if self._cells:
            self._cells[-1] += data


def exhibit_991_url(index_html: str, cik: int, accession: str) -> str | None:
    """The EX-99.1 document in an 8-K filing index, if it is a plain document in that filing."""
    parser = _IndexTableParser()
    parser.feed(index_html)
    folder = f"/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
    for cells, links in parser.rows:
        if not any(cell.upper() == "EX-99.1" for cell in cells):
            continue
        for href in links:
            href = href.removeprefix("/ix?doc=")
            name = href.removeprefix(folder)
            if href.startswith(folder) and re.fullmatch(r"[A-Za-z0-9_.-]+\.(?:htm|html|txt)", name, re.I):
                return "https://www.sec.gov" + href
    return None


def _press_releases(cik: int, recent: dict, ticker: str, company: str, user_agent: str,
                    limit: int, result: DocumentCollection) -> None:
    """Exhibit 99.1 press releases attached to the latest 8-Ks."""
    found = 0
    for i, form in enumerate(recent.get("form", [])):
        if form != "8-K" or found >= limit:
            continue
        accession = recent["accessionNumber"][i]
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
            continue
        all_items = recent.get("items") or []
        items = (all_items[i] if i < len(all_items) else "") or ""
        try:
            index_url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                         f"{accession.replace('-', '')}/{accession}-index.htm")
            url = exhibit_991_url(_get(index_url, user_agent).decode("utf-8", errors="replace"), cik, accession)
            if url is None:
                continue  # many 8-Ks carry no press release
            raw = _get(url, user_agent).decode("utf-8", errors="replace")
            text = text_from_html(raw) if url.lower().endswith((".htm", ".html")) else raw.strip()
            if not text:
                raise ValueError("Document contains no usable text")
            found += 1
            accepted = recent.get("acceptanceDateTime", [])
            published = _parse_date(accepted[i]) if i < len(accepted) else None
            # Item 2.02 is results of operations: an earnings release is company info.
            if "2.02" in items:
                classification = {"role": "company_info", "method": "8k_item", "unconfirmed": False}
            elif PRODUCT_TERMS.search(text[:1500]):
                classification = {"role": "product_event", "method": "keyword", "unconfirmed": False}
            else:
                classification = {"role": "company_info", "method": "source_type", "unconfirmed": False}
            result.documents.append(SourceDocument(
                source_url=url, title=f"{company} press release, 8-K Exhibit 99.1 ({recent['filingDate'][i]})",
                content_text=text, document_type="announcement", content_kind="full_text",
                source_name="SEC EDGAR", published_at=published, first_seen_at=datetime.now(timezone.utc),
                classification=classification,
                metadata={"ticker": ticker.upper(), "provider": "sec_edgar", "form": "8-K EX-99.1",
                          "items": items, "accession_number": accession,
                          "filing_date": recent["filingDate"][i],
                          "publication_time_known": published is not None,
                          "coverage": "Company press release furnished with an 8-K; the company's own wording"},
            ))
        except Exception as exc:
            result.warnings.append(f"SEC 8-K press release unavailable ({type(exc).__name__})")


def fetch_sec_filings(ticker: str, company_name: str, user_agent: str,
                      limit: int = 3, press_release_limit: int = 2) -> DocumentCollection:
    """Latest 10-K, 10-Q and 8-K primary documents, plus recent 8-K EX-99.1 press releases."""
    result = DocumentCollection()
    if "@" not in user_agent or "\n" in user_agent or "\r" in user_agent:
        result.warnings.append("SEC filings skipped: SEC_USER_AGENT must identify the application and a contact email")
        return result
    try:
        companies = json.loads(_get(SEC_TICKERS, user_agent))
        entry = next((row for row in companies.values()
                      if str(row.get("ticker", "")).upper() == ticker.upper()), None)
        if entry is None:
            result.warnings.append("SEC filings unavailable: ticker has no CIK mapping")
            return result
        cik = int(entry["cik_str"])
        data = json.loads(_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", user_agent))
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        selected = set()
        for i, form in enumerate(forms):
            if form not in {"10-K", "10-Q", "8-K"} or form in selected:
                continue
            selected.add(form)
            accession = recent["accessionNumber"][i]
            filename = recent["primaryDocument"][i]
            if (not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession)
                    or not re.fullmatch(r"[A-Za-z0-9_.-]+\.(?:htm|html|txt)", filename, re.I)):
                result.warnings.append(f"SEC {form} skipped: unsupported document path")
                continue
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{filename}"
            try:
                raw = _get(url, user_agent).decode("utf-8", errors="replace")
                text = text_from_html(raw) if filename.lower().endswith((".htm", ".html")) else raw.strip()
                if not text:
                    raise ValueError("Document contains no usable text")
                accepted = recent.get("acceptanceDateTime", [])
                published = _parse_date(accepted[i]) if i < len(accepted) else None
                result.documents.append(SourceDocument(
                    source_url=url, title=f"{company_name or entry.get('title') or ticker} {form} ({recent['filingDate'][i]})",
                    content_text=text, document_type="filing", content_kind="full_text", source_name="SEC EDGAR",
                    published_at=published, first_seen_at=datetime.now(timezone.utc),
                    classification={"role": "company_info", "method": "source_type"},
                    metadata={"ticker": ticker.upper(), "provider": "sec_edgar", "form": form,
                              "accession_number": accession, "filing_date": recent["filingDate"][i],
                              "publication_time_known": published is not None,
                              "coverage": "Primary filing text only; press releases are stored separately"},
                ))
            except Exception as exc:
                result.warnings.append(f"SEC {form} text unavailable ({type(exc).__name__})")
            if len(selected) >= limit:
                break
        if press_release_limit > 0:
            company = company_name or entry.get("title") or ticker
            _press_releases(cik, recent, ticker, company, user_agent, press_release_limit, result)
    except Exception as exc:
        result.warnings.append(f"SEC filings unavailable ({type(exc).__name__})")
    return result


def fetch_hacker_news(ticker: str, company_name: str = "", story_limit: int = 3,
                      comments_per_story: int = 4,
                      seen_at: datetime | None = None) -> DocumentCollection:
    """Well-voted Hacker News stories from the past 30 days naming the company, with top comments.

    One document per story. Hacker News skews heavily to tech, so most non-tech
    tickers return nothing. Comment authors are not stored.
    """
    result = DocumentCollection()
    seen_at = seen_at or datetime.now(timezone.utc)
    company = company_query_name(company_name)
    since = int((seen_at - timedelta(days=30)).timestamp())
    try:
        stories = json.loads(_get(HN_SEARCH.format(params=urlencode({
            "query": company or ticker, "tags": "story",
            "numericFilters": f"created_at_i>{since},points>=20", "hitsPerPage": "10",
        })))).get("hits", [])
    except Exception as exc:
        result.warnings.append(f"Hacker News evidence unavailable ({type(exc).__name__})")
        return result
    # Search matches story text and URLs too; require the stock in the title.
    mention = re.compile(r"(?<![\w$])\$?" + re.escape(ticker) + r"\b"
                         + (r"|\b" + re.escape(company) + r"\b" if company else ""), re.I)
    for story in stories:
        story_id = str(story.get("objectID", ""))
        title = (story.get("title") or "").strip()
        try:
            published = datetime.fromtimestamp(int(story["created_at_i"]), timezone.utc)
        except (KeyError, TypeError, ValueError):
            published = None
        if (not story_id.isdigit() or not title or not mention.search(title)
                or (published is not None and published > seen_at)):
            continue
        comments = []
        try:
            # `kids` lists top-level replies in HN's ranking order; nested replies
            # mostly argue with each other, so they are skipped.
            kids = json.loads(_get(HN_ITEM.format(id=story_id)) or b"{}").get("kids") or []
            for kid in kids[: comments_per_story * 2]:
                if len(comments) >= comments_per_story:
                    break
                if not str(kid).isdigit():
                    continue
                item = json.loads(_get(HN_ITEM.format(id=kid)) or b"{}") or {}
                if item.get("type") != "comment" or item.get("deleted") or item.get("dead"):
                    continue
                text = text_from_html(item.get("text") or "").replace("\n", " ")
                if text:
                    comments.append(text if len(text) <= 400 else text[:400].rstrip() + "...")
        except Exception as exc:
            result.warnings.append(f"Hacker News comments unavailable ({type(exc).__name__})")
        body = text_from_html(story.get("story_text") or "")
        parts = [title] + ([body[:1000]] if body else [])
        if comments:
            parts.append("Top-level comments:\n" + "\n".join(f"- {c}" for c in comments))
        text = "\n".join(parts)
        result.documents.append(SourceDocument(
            source_url=f"https://news.ycombinator.com/item?id={story_id}", title=title,
            content_text=text, document_type="forum",
            content_kind="excerpt" if body or comments else "headline",
            source_name="Hacker News", published_at=published, first_seen_at=seen_at,
            classification={"role": "public_opinion", "method": "source_type",
                            "unconfirmed": bool(UNCONFIRMED_TERMS.search(text))},
            metadata={"ticker": ticker.upper(), "provider": "hn_algolia",
                      "points": story.get("points"), "num_comments": story.get("num_comments"),
                      "comments_included": len(comments),
                      "linked_url": story.get("url") if _citation_url(story.get("url") or "") else None,
                      "publication_time_known": published is not None,
                      "coverage": "Tech-community discussion: the top few top-level comments of one thread; "
                                  "skews to tech topics, not a representative opinion sample"},
        ))
        if len(result.documents) >= story_limit:
            break
    return result


def _dedupe(documents: list[SourceDocument]) -> list[SourceDocument]:
    """One copy per link and per news headline (Yahoo and Google often carry the same story)."""
    links, headlines, kept = set(), set(), []
    for document in documents:
        key = _norm(document.title) if document.document_type == "news" else None
        if document.source_url in links or (key and key in headlines):
            continue
        links.add(document.source_url)
        if key:
            headlines.add(key)
        kept.append(document)
    return kept


def fetch_documents(ticker: str, company_name: str = "") -> DocumentCollection:
    """Fetch a small current evidence set; failures preserve successful sources.

    Called on demand by the backend. The caller stores immutable versions and
    chunks, applies forecast cutoffs and constructs per-strategy evidence packets.
    """
    ticker = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=-]{0,19}", ticker):
        raise ValueError("Invalid ticker for evidence collection")
    result = DocumentCollection()
    try:
        xml = _get(YAHOO_RSS.format(ticker=quote(ticker, safe="")))
        result.documents.extend(parse_news_rss(xml, ticker, company=company_query_name(company_name)))
        if not result.documents:
            result.warnings.append("Yahoo feed returned no source-linked evidence")
    except Exception as exc:
        result.warnings.append(f"Yahoo news evidence unavailable ({type(exc).__name__})")
    for extra in (fetch_google_news(ticker, company_name), fetch_hacker_news(ticker, company_name)):
        result.documents.extend(extra.documents)
        result.warnings.extend(extra.warnings)
    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if user_agent:
        filings = fetch_sec_filings(ticker, company_name, user_agent)
        result.documents.extend(filings.documents)
        result.warnings.extend(filings.warnings)
    else:
        result.warnings.append("SEC filings disabled: configure SEC_USER_AGENT to enable official filing text")
    result.documents = _dedupe(result.documents)
    return result
