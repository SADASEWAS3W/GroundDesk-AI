"""Redis-backed decorator for the unified retrieval boundary."""

from __future__ import annotations

import hashlib
from dataclasses import asdict

from agent.cache import TTL_KB_SEARCH, get_cached, set_cached
from agent.retrieval.models import RetrievedDocument, RetrievalDiagnostics, RetrievalResult


class CachedRetrievalService:
    def __init__(self, service, redis_client, *, ttl: int = TTL_KB_SEARCH) -> None:
        self._service = service
        self._redis = redis_client
        self._ttl = ttl

    async def retrieve(self, query: str, *, strategy="hybrid_rerank", top_k: int = 3):
        normalized = " ".join(query.strip().casefold().split())
        digest = hashlib.sha256(
            f"v1|{strategy}|{top_k}|{normalized}".encode("utf-8")
        ).hexdigest()
        key = f"retrieval:{digest}"
        cached = await get_cached(self._redis, key)
        if cached is not None:
            documents = [
                RetrievedDocument(
                    **{**item, "source_retrievers": tuple(item["source_retrievers"])}
                )
                for item in cached["documents"]
            ]
            diagnostics = RetrievalDiagnostics(**cached["diagnostics"])
            diagnostics.attributes["cache_hit"] = True
            return RetrievalResult(
                query=cached["query"],
                documents=documents,
                strategy=cached["strategy"],
                low_confidence=cached["low_confidence"],
                confidence_reasons=cached["confidence_reasons"],
                diagnostics=diagnostics,
            )
        result = await self._service.retrieve(query, strategy=strategy, top_k=top_k)
        await set_cached(self._redis, key, asdict(result), self._ttl)
        return result
