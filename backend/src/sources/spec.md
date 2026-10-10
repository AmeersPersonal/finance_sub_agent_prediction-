# spec: backend/src/sources/

## Purpose

`fetch_documents(ticker, company_name="")` returns `DocumentCollection` with
`documents` and `warnings`. Each `SourceDocument` has text, title, original URL,
provider, publication timestamp when known, first-seen timestamp, content kind,
classification and metadata. Missing sources do not discard successful sources.

## Sources available now

- Yahoo Finance RSS: linked headlines and publisher-provided descriptions.
  Descriptions are **excerpts**, not full articles. Article links are saved as
  citations but are not followed or scraped. A news story is not representative
  evidence of population-wide public opinion.
- SEC EDGAR: opt-in latest 10-K, 10-Q and 8-K primary filing text (one per form,
  at most three). Set `SEC_USER_AGENT` to your application name plus a real contact
  email. Public reading requires no SEC API key. Exhibits, PDFs and older filing
  history are not collected. Downloaded HTML is converted to plain text; the
  entire primary text is retained rather than passing it all to Gemini.

`product_event` is a keyword-based routing hint, not confirmation that a rumor
or launch is real. SEC filings are routed as `company_info`; other news as
`public_opinion`. Retrieval should preserve these limitations in explanations.

## Boundaries

This package only fetches public evidence. The database layer stores immutable
versions and chunks; retrieval selects source-linked passages for each strategy.
Publication timestamps and first-seen timestamps must both precede a forecast's
cutoff. Unknown publication timestamps remain null, not invented dates.

Network calls are restricted to a fixed HTTPS provider allowlist, redirects are
rechecked, responses are bounded at 8 MiB, and timeouts are 15 seconds. SEC calls
are paced within this process. Tests mock all requests and never use live sources.

There is no Reddit/forum collector, arbitrary publisher full-text scraper,
dedicated company-product announcement connector, or embedding/vector provider.

SEC source documentation:

- [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [Developer resources](https://www.sec.gov/about/developer-resources)
