"""Retrieval over the private documents in ai/docs/ (gitignored).

Deliberately simple keyword overlap with no embeddings, so it works offline with
zero setup. Only .md and .txt files are read; convert filings to text first.
Swap in a vector store here if the folder grows past a few dozen files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent / "docs"
TEXT_SUFFIXES = {".md", ".txt"}
_WORD = re.compile(r"[a-z0-9&]{3,}")


@dataclass(frozen=True)
class Snippet:
    source: str  # path relative to the docs folder
    text: str
    document_id: int | None = None
    chunk_id: int | None = None
    url: str | None = None
    title: str | None = None
    content_kind: str | None = None
    role: str | None = None  # company_info / public_opinion / product_event; None for local docs
    unconfirmed: bool = False  # rumor or leak wording

    @property
    def citation_id(self) -> str:
        return f"doc-{self.document_id}-chunk-{self.chunk_id}" if self.document_id is not None else self.source


def _terms(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def retrieve(
    query: str, k: int = 3, max_chars: int = 1500, docs_dir: Path = DOCS_DIR
) -> list[Snippet]:
    """The `k` documents sharing the most terms with `query`, truncated to `max_chars`."""
    if not docs_dir.is_dir():
        return []
    query_terms = _terms(query)
    scored = []
    for path in docs_dir.rglob("*"):
        if path.suffix.lower() not in TEXT_SUFFIXES or "age_profiles" in path.relative_to(docs_dir).parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        score = len(query_terms & _terms(text))
        if score:
            scored.append((score, path, text))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        Snippet(str(path.relative_to(docs_dir)), text[:max_chars])
        for _, path, text in scored[:k]
    ]


def load_age_profile(label: str, docs_dir: Path = DOCS_DIR) -> str | None:
    """A sourced profile for an age band, from age_profiles/<label>.md, if one exists."""
    path = docs_dir / "age_profiles" / f"{label}.md"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else None
