"""Deterministic character-bounded splitting with original-text offsets."""

from __future__ import annotations

import re
from dataclasses import dataclass

CHUNKING_VERSION = "paragraph-char-v1"


@dataclass(frozen=True, slots=True)
class TextChunk:
    index: int
    start: int
    end: int
    content: str


def split_document(content: str, *, chunk_size: int = 1200, overlap: int = 150) -> list[TextChunk]:
    """Prefer paragraphs, then sentence/space boundaries in the window's latter half.

    Offsets refer to the unmodified Python string; end is exclusive. Overlap
    is measured in characters, not tokens. Long unbroken text uses hard cuts.
    """
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 2:
        raise ValueError("chunk_size must be an integer >= 2")
    if isinstance(overlap, bool) or not isinstance(overlap, int) or not 0 <= overlap < chunk_size // 2:
        raise ValueError("overlap must be non-negative and smaller than half chunk_size")
    if not content.strip():
        return []
    chunks = []
    start = 0
    while start < len(content):
        end = min(start + chunk_size, len(content))
        if end < len(content):
            lower = start + chunk_size // 2
            window = content[lower:end]
            for pattern in (r"\n[ \t\r]*\n", r"[。！？!?]|\.(?=\s)", r"\s+"):
                matches = list(re.finditer(pattern, window))
                if matches:
                    end = lower + matches[-1].end()
                    break
        fragment = content[start:end]
        if fragment.strip():
            chunks.append(TextChunk(len(chunks), start, end, fragment))
        if end == len(content):
            break
        start = end - overlap
    return chunks
