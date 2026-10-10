"""Public online evidence collection, with provenance and explicit coverage limits."""

from .documents import DocumentCollection, SourceDocument, fetch_documents

__all__ = ["DocumentCollection", "SourceDocument", "fetch_documents"]
