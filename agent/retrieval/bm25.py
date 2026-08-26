"""In-process BM25 retrieval and PostgreSQL knowledge loading."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from rank_bm25 import BM25Okapi

from agent.retrieval.models import RetrievedDocument, validate_top_k
from agent.retrieval.tokenizer import BilingualTokenizer


class BM25IndexNotBuiltError(RuntimeError):
    """Raised when keyword search is attempted before the first build."""


@dataclass(frozen=True, slots=True)
class BM25IndexStatus:
    built: bool
    document_count: int


class InMemoryBM25Retriever:
    """Atomically rebuildable BM25 index for a single application process."""

    def __init__(self, *, tokenizer: BilingualTokenizer | None = None) -> None:
        self._tokenizer = tokenizer or BilingualTokenizer()
        self._documents: tuple[RetrievedDocument, ...] = ()
        self._document_token_sets: tuple[frozenset[str], ...] = ()
        self._index: BM25Okapi | None = None
        self._built = False

    @property
    def status(self) -> BM25IndexStatus:
        return BM25IndexStatus(
            built=self._built,
            document_count=len(self._documents),
        )

    def build(self, documents: Sequence[RetrievedDocument]) -> BM25IndexStatus:
        """Build a fresh index and replace the active snapshot atomically."""
        copied_documents = tuple(
            replace(document, metadata=dict(document.metadata))
            for document in documents
        )
        document_ids = [document.document_id for document in copied_documents]
        if len(set(document_ids)) != len(document_ids):
            raise ValueError("BM25 documents must have unique document_id values")

        corpus = [
            self._tokenizer.tokenize(f"{document.title} {document.content}")
            for document in copied_documents
        ]
        token_sets = tuple(frozenset(tokens) for tokens in corpus)
        index = BM25Okapi(corpus) if corpus and any(corpus) else None

        self._documents = copied_documents
        self._document_token_sets = token_sets
        self._index = index
        self._built = True
        return self.status

    def rebuild(self, documents: Sequence[RetrievedDocument]) -> BM25IndexStatus:
        """Rebuild the complete in-memory snapshot."""
        return self.build(documents)

    async def search(self, query: str, *, top_k: int) -> list[RetrievedDocument]:
        checked_top_k = validate_top_k(top_k)
        if not self._built:
            raise BM25IndexNotBuiltError("BM25 index has not been built")
        if self._index is None:
            return []

        query_tokens = self._tokenizer.tokenize(query)
        if not query_tokens:
            return []

        query_token_set = frozenset(query_tokens)
        scores = self._index.get_scores(query_tokens)
        candidates = [
            (index, float(score))
            for index, score in enumerate(scores)
            if query_token_set.intersection(self._document_token_sets[index])
        ]
        candidates.sort(
            key=lambda item: (
                -item[1],
                self._documents[item[0]].document_id,
            )
        )

        results: list[RetrievedDocument] = []
        for rank, (index, score) in enumerate(candidates[:checked_top_k], start=1):
            document = self._documents[index]
            sources = tuple(dict.fromkeys((*document.source_retrievers, "bm25")))
            results.append(
                replace(
                    document,
                    metadata=dict(document.metadata),
                    source_retrievers=sources,
                    bm25_score=score,
                    bm25_rank=rank,
                )
            )
        return results


async def load_knowledge_documents(db_pool: Any) -> list[RetrievedDocument]:
    """Load the complete searchable corpus for an in-process BM25 snapshot."""
    async with db_pool.acquire() as connection:
        rows = await connection.fetch(
            "SELECT id, title, content, category "
            "FROM knowledge_base ORDER BY id"
        )
    return [
        RetrievedDocument(
            document_id=str(row["id"]),
            title=row["title"],
            content=row["content"],
            category=row["category"],
            metadata={"source": "knowledge_base"},
        )
        for row in rows
    ]
