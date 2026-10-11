-- Index existing and future titles without rewriting immutable source evidence.
-- Retrieval uses the same expression in its title candidate lookup, alongside
-- the existing document_chunks_search_idx for passage body keywords.
CREATE INDEX documents_title_search_idx ON documents
    USING GIN (to_tsvector('english', title));
