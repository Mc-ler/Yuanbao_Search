"""Near-duplicate detection for search passages.

Reposts are not independent evidence. Five-character shingles plus Jaccard
similarity over normalized passages, then connected components. Every
cluster counts as one vote in the judge, no matter how many domains carry it.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

from ..contracts import Cluster, SearchPage

_TAG_RE = re.compile(r"<[^>]+>")
_PUNCT_RE = re.compile(r"[\s\u3000-\u303f\uff00-\uffef!-/:-@\[-`{-~]+")


def normalize_text(value: str) -> str:
    text = _TAG_RE.sub(" ", value or "")
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    return _PUNCT_RE.sub("", text)


def shingles(text: str, n: int = 5) -> set[str]:
    normalized = normalize_text(text)
    if not normalized:
        return set()
    if len(normalized) <= n:
        return {normalized}
    return {normalized[i : i + n] for i in range(len(normalized) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class DedupResult:
    unique_pages: list[SearchPage]
    clusters: list[Cluster]
    page_cluster: dict[str, str] = field(default_factory=dict)

    def cluster_for(self, page: SearchPage, index: int = 0) -> str:
        return self.page_cluster.get(page_key(page, index), "")


def page_key(page: SearchPage, index: int = 0) -> str:
    return page.url or f"{page.title}|{index}"


def _unique_pages(pages: Iterable[SearchPage]) -> list[SearchPage]:
    by_key: dict[str, SearchPage] = {}
    for index, page in enumerate(pages):
        key = page_key(page, index)
        current = by_key.get(key)
        if current is None:
            by_key[key] = page
        elif (page.score or 0) > (current.score or 0):
            by_key[key] = page
    return [by_key[key] for key in sorted(by_key)]


def cluster_pages(pages: Iterable[SearchPage], threshold: float = 0.65) -> DedupResult:
    unique = _unique_pages(pages)
    shingle_sets = [shingles(page.text()) for page in unique]
    parent = list(range(len(unique)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if ra < rb:
            parent[rb] = ra
        else:
            parent[ra] = rb

    for i in range(len(unique)):
        if not shingle_sets[i]:
            continue
        for j in range(i + 1, len(unique)):
            if not shingle_sets[j]:
                continue
            if jaccard(shingle_sets[i], shingle_sets[j]) >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for index in range(len(unique)):
        groups.setdefault(find(index), []).append(index)

    clusters: list[Cluster] = []
    page_cluster: dict[str, str] = {}
    for members in groups.values():
        members = sorted(members, key=lambda i: page_key(unique[i], i))
        urls = sorted(page_key(unique[i], i) for i in members)
        cluster_id = "c-" + hashlib.sha1("|".join(urls).encode("utf-8")).hexdigest()[:6]
        domains = sorted({unique[i].domain for i in members if unique[i].domain})
        representative = unique[members[0]].url
        cluster = Cluster(
            cluster_id=cluster_id,
            member_ids=[page_key(unique[i], i) for i in members],
            domains=domains,
            size=len(members),
            representative_url=representative,
        )
        clusters.append(cluster)
        for i in members:
            page_cluster[page_key(unique[i], i)] = cluster_id

    clusters.sort(key=lambda item: item.cluster_id)
    return DedupResult(unique_pages=unique, clusters=clusters, page_cluster=page_cluster)
