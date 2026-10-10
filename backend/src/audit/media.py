"""Source digest with explicit coverage, avoiding invented article summaries."""


def source_digest(sources: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for source in sources:
        if source['document_id'] in seen:
            continue
        seen.add(source['document_id'])
        result.append({'title': source['title'], 'url': source['url'],
                       'coverage': source['content_kind'], 'published_at': source['published_at']})
    return result
