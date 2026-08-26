"""Tests for bilingual BM25 tokenization."""

from agent.retrieval import BilingualTokenizer


def test_english_is_casefolded_and_punctuation_is_removed():
    tokenizer = BilingualTokenizer()

    assert tokenizer.tokenize(" Reset PASSWORD, error-code API_v2! ") == [
        "reset",
        "password",
        "error-code",
        "api_v2",
    ]


def test_chinese_uses_word_segmentation():
    tokenizer = BilingualTokenizer()

    tokens = tokenizer.tokenize("如何重置密码？")

    assert "重置" in tokens
    assert "密码" in tokens


def test_mixed_query_uses_the_same_normalization_pipeline():
    tokenizer = BilingualTokenizer(chinese_tokenizer=lambda text: ["重置", "密码"])

    assert tokenizer.tokenize("API 重置密码 v2") == ["api", "重置", "密码", "v2"]


def test_blank_text_has_no_tokens():
    assert BilingualTokenizer().tokenize(" \t\n ") == []
