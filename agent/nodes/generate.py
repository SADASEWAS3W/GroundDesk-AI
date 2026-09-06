"""Grounded answer generation from a bounded evidence set."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Protocol


class GenerationProviderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    answer: str
    citation_document_ids: list[str]


class AnswerGenerator(Protocol):
    async def generate(
        self,
        query: str,
        documents: list[dict[str, Any]],
    ) -> GeneratedAnswer: ...


class ExtractiveAnswerGenerator:
    """Deterministic no-provider implementation used by unit tests."""

    async def generate(
        self,
        query: str,
        documents: list[dict[str, Any]],
    ) -> GeneratedAnswer:
        answer_parts = []
        document_ids = []
        for index, document in enumerate(documents, 1):
            excerpt = " ".join(document["content"].split())[:280]
            answer_parts.append(f"{excerpt} [{index}]")
            document_ids.append(document["document_id"])
        return GeneratedAnswer(
            answer="\n\n".join(answer_parts),
            citation_document_ids=document_ids,
        )


class LLMAnswerGenerator:
    """Generate a natural answer while reporting the exact evidence IDs used."""

    def __init__(
        self,
        model_client,
        *,
        model: str | None = None,
        timeout_seconds: float = 20.0,
        max_document_chars: int = 2000,
        max_output_tokens: int = 800,
    ) -> None:
        if max_document_chars < 1:
            raise ValueError("max_document_chars must be positive")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        self._client = model_client
        self._model = model or os.environ.get("QWEN_CHAT_MODEL", "qwen-plus")
        self._timeout_seconds = timeout_seconds
        self._max_document_chars = max_document_chars
        self._max_output_tokens = max_output_tokens

    async def generate(
        self,
        query: str,
        documents: list[dict[str, Any]],
    ) -> GeneratedAnswer:
        bounded_documents = documents[:3]
        evidence = "\n\n".join(
            f"[{index}] document_id={document['document_id']}\n"
            f"title={document['title']}\n"
            f"content={document['content'][:self._max_document_chars]}"
            for index, document in enumerate(bounded_documents, 1)
        )
        prompt = (
            "Answer the customer using only the evidence below. Every factual claim "
            "must cite one or more evidence numbers such as [1]. Do not invent facts. "
            "Return one JSON object with keys answer and citation_document_ids. "
            "citation_document_ids must list the exact document_id values used, in "
            "first-citation order.\n\n"
            f"Customer question:\n{query}\n\nEvidence:\n{evidence}"
        )
        try:
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a grounded SaaS customer-support writer.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0,
                    max_tokens=self._max_output_tokens,
                    response_format={"type": "json_object"},
                ),
                timeout=self._timeout_seconds,
            )
            content = response.choices[0].message.content or ""
            payload = json.loads(content)
            answer = payload["answer"].strip()
            document_ids = payload["citation_document_ids"]
        except Exception as exc:
            raise GenerationProviderError("answer generation provider failed") from exc
        if not answer or not isinstance(document_ids, list) or not all(
            isinstance(document_id, str) for document_id in document_ids
        ):
            raise GenerationProviderError("answer generation returned an invalid payload")
        return GeneratedAnswer(answer=answer, citation_document_ids=document_ids)
