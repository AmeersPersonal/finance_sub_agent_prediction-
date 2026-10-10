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
- Google News RSS (keyless): two searches per ticker, `"<TICKER>" stock` over
  7 days and `"<Company>" (launch OR unveil OR announces OR product OR rumor OR
  leak)` over 30 days. Items are **headlines** only (the description just
  repeats the headline and publisher), linked through `news.google.com`; links
  are not followed. The feed's terms allow personal, non-commercial reading,
  which suits this learning prototype; review them before any other use.
- SEC EDGAR: opt-in latest 10-K, 10-Q and 8-K primary filing text (one per form,
  at most three), plus Exhibit 99.1 press releases from the two most recent
  8-Ks that have one (found through each filing's `-index.htm`; only documents
  inside that filing's folder are fetched). Set `SEC_USER_AGENT` to your
  application name plus a real contact email. Public reading requires no SEC API
  key. Other exhibits, PDFs and older filing history are not collected.
  Downloaded HTML is converted to plain text; the entire text is retained rather
  than passing it all to Gemini.
- Hacker News (keyless, always on): the Algolia HN Search API finds stories
  from the past 30 days with at least 20 points whose **title** names the
  company or ticker (up to 3). For each, the official HN Firebase API supplies
  the story's top-level comments in HN's own ranking order; the top 4 live
  (not deleted or dead) comments are kept, trimmed to 400 characters. One
  document per story, cited as its `news.ycombinator.com` thread. Authors are
  not stored. HN skews heavily to tech, so most non-tech tickers get nothing.

Same-link duplicates, and news items with the same headline across feeds, are
kept once.

## Roles

Every document's `classification` holds `role`, `method` and `unconfirmed`:

| Role | Sources |
|---|---|
| `company_info` | SEC filings; 8-K press releases for Item 2.02 (results) or without product wording |
| `public_opinion` | News without product keywords; Hacker News threads |
| `product_event` | News with product/launch/rumor keywords; every Google product-search result; press releases with product wording |

`product_event` is a keyword- or query-based routing hint, not confirmation that
a rumor or launch is real. `unconfirmed` is set when text uses rumor, leak,
"reportedly" or speculation wording. Prompts show both, and retrieval mixes the
roles per strategy (see `database/spec.md`).

## Boundaries

This package only fetches public evidence. The database layer stores immutable
versions and chunks; retrieval selects source-linked passages for each strategy.
Publication timestamps and first-seen timestamps must both precede a forecast's
cutoff. Unknown publication timestamps remain null, not invented dates.

Network calls are restricted to a fixed HTTPS provider allowlist, redirects are
rechecked, responses are bounded at 8 MiB, and timeouts are 15 seconds. SEC calls
are paced within this process. Tests mock all requests and never use live sources.

There is no arbitrary publisher full-text scraper, other forum collector, or
embedding/vector provider. Hacker News threads are not a representative opinion
sample.

Reddit is deliberately not collected. Its
[Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)
requires explicit approval before any API access, forbids sharing Reddit data
(our pipeline sends passages to Gemini) or using it to train models, and bars
circumventing access limits, so unofficial scraping is out too.

SEC source documentation:

- [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [Developer resources](https://www.sec.gov/about/developer-resources)
