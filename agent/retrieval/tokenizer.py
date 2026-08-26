"""Deterministic bilingual tokenization for keyword retrieval."""

from __future__ import annotations

import re
from collections.abc import Callable

import jieba

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[._+#-][a-z0-9]+)*|[\u3400-\u9fff]+")
_HAS_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")


class BilingualTokenizer:
    """Tokenize English, Chinese, and mixed support queries consistently."""

    def __init__(self, *, chinese_tokenizer: Callable[[str], list[str]] | None = None):
        self._chinese_tokenizer = chinese_tokenizer or self._cut_chinese

    def tokenize(self, text: str) -> list[str]:
        """Return normalized tokens while discarding punctuation and blanks."""
        normalized = text.casefold().strip()
        if not normalized:
            return []

        tokens: list[str] = []
        for segment in _TOKEN_PATTERN.findall(normalized):
            if _HAS_CJK_PATTERN.search(segment):
                tokens.extend(
                    token.strip()
                    for token in self._chinese_tokenizer(segment)
                    if token.strip()
                )
            else:
                tokens.append(segment)
        return tokens

    @staticmethod
    def _cut_chinese(text: str) -> list[str]:
        return list(jieba.cut(text, cut_all=False))
