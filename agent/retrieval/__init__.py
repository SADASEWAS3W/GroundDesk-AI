"""Provider-neutral retrieval contracts and services."""

from agent.retrieval.models import (
    MAX_TOP_K,
    RETRIEVAL_STRATEGIES,
    RetrievedDocument,
    RetrievalDiagnostics,
    RetrievalResult,
    RetrievalStrategy,
    validate_strategy,
    validate_top_k,
)
from agent.retrieval.bm25 import (
    BM25IndexNotBuiltError,
    BM25IndexStatus,
    InMemoryBM25Retriever,
    load_knowledge_documents,
)
from agent.retrieval.fusion import ReciprocalRankFusion
from agent.retrieval.protocols import (
    BM25Retriever,
    FusionStrategy,
    Reranker,
    RetrievalService,
    VectorRetriever,
)
from agent.retrieval.reranker import (
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MAX_DOCUMENT_CHARS,
    DEFAULT_MAX_QUERY_CHARS,
    DEFAULT_RERANK_MODEL,
    LLMReranker,
    NoOpReranker,
    RerankerError,
    RerankerProviderError,
    RerankerResponseError,
)
from agent.retrieval.service import (
    FakeRetrievalService,
    HybridRetrievalService,
    RetrievalCapabilityError,
)
from agent.retrieval.tokenizer import BilingualTokenizer
from agent.retrieval.vector import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_IVFFLAT_PROBES,
    EMBEDDING_DIMENSIONS,
    PgVectorRetriever,
    VectorRetrievalError,
)

__all__ = [
    "BM25Retriever",
    "BM25IndexNotBuiltError",
    "BM25IndexStatus",
    "BilingualTokenizer",
    "DEFAULT_MAX_CANDIDATES",
    "DEFAULT_MAX_DOCUMENT_CHARS",
    "DEFAULT_MAX_QUERY_CHARS",
    "DEFAULT_RERANK_MODEL",
    "FakeRetrievalService",
    "FusionStrategy",
    "HybridRetrievalService",
    "InMemoryBM25Retriever",
    "LLMReranker",
    "MAX_TOP_K",
    "NoOpReranker",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_IVFFLAT_PROBES",
    "EMBEDDING_DIMENSIONS",
    "PgVectorRetriever",
    "RETRIEVAL_STRATEGIES",
    "Reranker",
    "RerankerError",
    "RerankerProviderError",
    "RerankerResponseError",
    "ReciprocalRankFusion",
    "RetrievedDocument",
    "RetrievalDiagnostics",
    "RetrievalResult",
    "RetrievalService",
    "RetrievalStrategy",
    "RetrievalCapabilityError",
    "VectorRetriever",
    "VectorRetrievalError",
    "validate_strategy",
    "validate_top_k",
    "load_knowledge_documents",
]
