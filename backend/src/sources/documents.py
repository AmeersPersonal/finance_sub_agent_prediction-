"""Collect feed evidence and optional official SEC filing text.

Publisher links are retained as citations, never followed to scrape articles.
Feed summaries are explicitly excerpts, not full articles or public-opinion polls.
SEC downloading is opt-in through SEC_USER_AGENT (application + contact email).
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
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
ALLOWED_HOSTS = frozenset({"feeds.finance.yahoo.com", "www.sec.gov", "data.sec.gov", "sec.gov"})
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


def parse_news_rss(xml: bytes, ticker: str, limit: int = 10,
                   seen_at: datetime | None = None) -> list[SourceDocument]:
    if limit <= 0:
        return []
    # ElementTree does not fetch external entities; reject DTD input explicitly.
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ValueError("Provider feed cannot contain a DTD or entity declarations")
    seen_at = seen_at or datetime.now(timezone.utc)
    root = ElementTree.fromstring(xml)
    documents = []
    seen_links = set()
    for item in root.iter("item"):
        title = text_from_html(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        if not title or not _citation_url(link) or link in seen_links:
            continue
        # content:encoded, when supplied, can still be a teaser. Never call it full text.
        body = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
        summary = text_from_html(body or item.findtext("description") or "")
        published = _parse_date(item.findtext("pubDate"))
        if published is not None and published > seen_at:
            continue
        role = "product_event" if re.search(
            r"\b(launch\w*|announc\w*|unveil\w*|product\w*|rumou?r\w*)\b", title + " " + summary, re.I
        ) else "public_opinion"
        source_node = item.find("source")
        source_name = (source_node.text or "").strip() if source_node is not None else ""
        documents.append(SourceDocument(
            source_url=link, title=title, content_text=summary or title,
            document_type="news", content_kind="excerpt" if summary else "headline",
            source_name=source_name or "Yahoo Finance RSS", published_at=published,
            first_seen_at=seen_at, classification={"role": role, "method": "keyword"},
            metadata={"ticker": ticker.upper(), "provider": "yahoo_rss", "text_origin": "feed_body" if summary else "feed_title",
                      "publication_time_known": published is not None,
                      "coverage": "Publisher-supplied feed excerpt; not a population sentiment measure"},
        ))
        seen_links.add(link)
        if len(documents) >= limit:
            break
    return documents


def fetch_sec_filings(ticker: str, company_name: str, user_agent: str,
                      limit: int = 3) -> DocumentCollection:
    """Latest 10-K, 10-Q and 8-K primary documents; no exhibits or bulk history."""
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
                              "coverage": "Primary filing text only; linked exhibits are not fetched"},
                ))
            except Exception as exc:
                result.warnings.append(f"SEC {form} text unavailable ({type(exc).__name__})")
            if len(selected) >= limit:
                break
    except Exception as exc:
        result.warnings.append(f"SEC filings unavailable ({type(exc).__name__})")
    return result


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
        result.documents.extend(parse_news_rss(xml, ticker))
        if not result.documents:
            result.warnings.append("Yahoo feed returned no source-linked evidence")
    except Exception as exc:
        result.warnings.append(f"Yahoo news evidence unavailable ({type(exc).__name__})")
    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if user_agent:
        filings = fetch_sec_filings(ticker, company_name, user_agent)
        result.documents.extend(filings.documents)
        result.warnings.extend(filings.warnings)
    else:
        result.warnings.append("SEC filings disabled: configure SEC_USER_AGENT to enable official filing text")
    return result
