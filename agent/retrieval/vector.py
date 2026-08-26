"""PostgreSQL/pgvector semantic retriever."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from agent.retrieval.models import RetrievedDocument, validate_top_k

DEFAULT_EMBEDDING_MODEL = "text-embedding-v4"
EMBEDDING_DIMENSIONS = 1536
DEFAULT_IVFFLAT_PROBES = 10


class VectorRetrievalError(RuntimeError):
    """Raised when the embedding provider or vector database is unavailable."""


class PgVectorRetriever:
    """Retrieve ranked knowledge-base documents using cosine similarity.

    The model client and database pool are injected by the service composition
    root. By default no similarity threshold is applied: confidence thresholds
    must be calibrated by Retrieval Eval rather than copied from the legacy
    Function Tool. A threshold can be supplied explicitly for baseline
    comparison.
    """

    def __init__(
        self,
        *,
        model_client: Any,
        db_pool: Any,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        embedding_dimensions: int = EMBEDDING_DIMENSIONS,
        similarity_threshold: float | None = None,
        ivfflat_probes: int = DEFAULT_IVFFLAT_PROBES,
    ) -> None:
        if embedding_dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"embedding_dimensions must be {EMBEDDING_DIMENSIONS} "
                "for the current database schema"
            )
        if not embedding_model.strip():
            raise ValueError("embedding_model must not be empty")
        if similarity_threshold is not None and (
            not math.isfinite(similarity_threshold)
            or not -1.0 <= similarity_threshold <= 1.0
        ):
            raise ValueError("similarity_threshold must be between -1 and 1")
        if (
            isinstance(ivfflat_probes, bool)
            or not isinstance(ivfflat_probes, int)
            or ivfflat_probes < 1
        ):
            raise ValueError("ivfflat_probes must be a positive integer")

        self._model_client = model_client
        self._db_pool = db_pool
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions
        self._similarity_threshold = similarity_threshold
        self._ivfflat_probes = ivfflat_probes

    async def search(self, query: str, *, top_k: int = 10) -> list[RetrievedDocument]:
        """Return one-based ranked vector candidates for a non-empty query."""
        checked_top_k = validate_top_k(top_k)
        normalized_query = " ".join(query.strip().split())
        if not normalized_query:
            return []

        query_embedding = await self._create_embedding(normalized_query)
        rows = await self._search_database(query_embedding, checked_top_k)

        documents: list[RetrievedDocument] = []
        for rank, row in enumerate(rows, start=1):
            distance = float(row["distance"])
            similarity = float(row["similarity"])
            documents.append(
                RetrievedDocument(
                    document_id=str(row["id"]),
                    title=row["title"],
                    content=row["content"],
                    category=row["category"],
                    metadata={
                        "source": "knowledge_base",
                        "vector_distance": distance,
                    },
                    source_retrievers=("vector",),
                    vector_score=similarity,
                    vector_rank=rank,
                )
            )
        return documents

    async def _create_embedding(self, query: str) -> list[float]:
        try:
            response = await self._model_client.embeddings.create(
                input=query,
                model=self._embedding_model,
                dimensions=self._embedding_dimensions,
                encoding_format="float",
            )
            embedding = response.data[0].embedding
            return self._validate_embedding(embedding)
        except VectorRetrievalError:
            raise
        except Exception as exc:
            raise VectorRetrievalError("query embedding failed") from exc

    def _validate_embedding(self, embedding: Sequence[float]) -> list[float]:
        if len(embedding) != self._embedding_dimensions:
            raise VectorRetrievalError(
                "embedding dimension mismatch: "
                f"expected {self._embedding_dimensions}, received {len(embedding)}"
            )

        values = [float(value) for value in embedding]
        if not all(math.isfinite(value) for value in values):
            raise VectorRetrievalError("embedding contains a non-finite value")
        return values

    async def _search_database(
        self,
        query_embedding: list[float],
        top_k: int,
    ) -> Sequence[Any]:
        distance_expression = "embedding <=> $1::vector"
        where_clause = "embedding IS NOT NULL"
        parameters: tuple[Any, ...]

        if self._similarity_threshold is None:
            limit_placeholder = "$2"
            parameters = (query_embedding, top_k)
        else:
            where_clause += f" AND 1 - ({distance_expression}) >= $2"
            limit_placeholder = "$3"
            parameters = (query_embedding, self._similarity_threshold, top_k)

        sql = (
            "SELECT id, title, content, category, "
            f"{distance_expression} AS distance, "
            f"1 - ({distance_expression}) AS similarity "
            "FROM knowledge_base "
            f"WHERE {where_clause} "
            f"ORDER BY {distance_expression} "
            f"LIMIT {limit_placeholder}"
        )

        try:
            async with self._db_pool.acquire() as connection:
                async with connection.transaction():
                    await connection.execute(
                        "SELECT set_config('ivfflat.probes', $1, true)",
                        str(self._ivfflat_probes),
                    )
                    return await connection.fetch(sql, *parameters)
        except Exception as exc:
            raise VectorRetrievalError("pgvector query failed") from exc
