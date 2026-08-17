"""Docs feature — relationship-map edge computation. Stage 5 of the
DocApp-in-LabTool plan (see Documentation/planning).

Matches DocApp's own doc-map-graph.js edge logic: wiki-link references,
shared identical headings, and shared "significant" keywords (6+ char
words, frequency > 1 within a doc, simple TF, stop-word filtered) — no
embeddings/NLP, same as source. Computed server-side (cheap string/set work
against content the DB already holds) rather than shipping every doc's
full content to the browser to compute client-side, consistent with this
feature's "keep LabTool's search/computation server-side" design.
"""
from __future__ import annotations

import re
from collections import Counter

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_WORD_RE = re.compile(r"[a-zA-Z]{6,}")

_STOPWORDS = {
    "should", "would", "could", "because", "before", "during", "between",
    "through", "above", "below", "under", "again", "further", "which",
    "their", "there", "where", "when", "what", "will", "been", "being",
    "into", "than", "then", "some", "such", "only", "other", "these",
    "those", "while", "after", "about", "still", "also", "just", "very",
    "most", "each", "both", "once", "here", "however", "without", "within",
}


def _significant_words(content: str) -> set[str]:
    counts = Counter(w.lower() for w in _WORD_RE.findall(content))
    return {w for w, c in counts.items() if c > 1 and w not in _STOPWORDS}


def compute_map(docs: list[dict]) -> dict:
    """docs: list of {"id", "name", "shelf_id", "shelf_name", "content"}.
    Returns {"nodes": [...], "edges": [...]} — edges deduplicated per
    (pair, type), a pair can have more than one edge if related more than
    one way (e.g. both a wiki-link and shared keywords)."""
    nodes = [
        {
            "id": d["id"], "name": d["name"], "shelf_id": d["shelf_id"],
            "shelf_name": d["shelf_name"], "word_count": len(d["content"].split()),
        }
        for d in docs
    ]

    name_to_id: dict[str, str] = {}
    for d in docs:
        name_to_id.setdefault(d["name"].strip().lower(), d["id"])

    headings_by_doc: dict[str, set[str]] = {}
    keywords_by_doc: dict[str, set[str]] = {}
    wiki_targets_by_doc: dict[str, set[str]] = {}

    for d in docs:
        content = d["content"]
        headings_by_doc[d["id"]] = {h.strip().lower() for h in _HEADING_RE.findall(content)}
        keywords_by_doc[d["id"]] = _significant_words(content)
        wiki_targets_by_doc[d["id"]] = {m.strip().lower() for m in _WIKILINK_RE.findall(content)}

    edges: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def add_edge(a: str, b: str, edge_type: str) -> None:
        if a == b:
            return
        pair = tuple(sorted((a, b)))
        key = (pair[0], pair[1], edge_type)
        if key in seen:
            return
        seen.add(key)
        edges.append({"source": pair[0], "target": pair[1], "type": edge_type})

    # Wiki-link edges — directional in source, but the map treats them as
    # an undirected relationship (matches source's rendering: a link either
    # way just draws one connecting edge).
    for doc_id, targets in wiki_targets_by_doc.items():
        for target_name in targets:
            target_id = name_to_id.get(target_name)
            if target_id:
                add_edge(doc_id, target_id, "wiki")

    # Shared-heading and shared-keyword edges — pairwise comparison, fine
    # at the scale a personal doc library actually reaches.
    ids = [d["id"] for d in docs]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            if headings_by_doc[a] & headings_by_doc[b]:
                add_edge(a, b, "heading")
            if len(keywords_by_doc[a] & keywords_by_doc[b]) >= 3:
                add_edge(a, b, "keyword")

    return {"nodes": nodes, "edges": edges}
