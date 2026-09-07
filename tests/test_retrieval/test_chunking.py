"""Regression checks for boundaries, provenance, and multilingual source coverage."""

import pytest

from agent.retrieval.chunking import split_document


def test_short_article_keeps_complete_content():
    content = "# Password\n\nReset with your email."
    chunks = split_document(content)
    assert len(chunks) == 1
    assert chunks[0].content == content
    assert (chunks[0].start, chunks[0].end) == (0, len(content))


@pytest.mark.parametrize("text", ["", " \n\t "])
def test_blank_source_has_no_chunks(text):
    assert split_document(text) == []


@pytest.mark.parametrize("content", [
    "界" * 501, "reset password. " * 60,
    "# Account\r\n\r\n第一段包含密码说明。\r\n\r\n" * 35,
    "```python\nprint('sample')\n```\n\n" * 30,
])
def test_bounds_overlap_and_lossless_reconstruction(content):
    chunks = split_document(content, chunk_size=80, overlap=10)
    rebuilt = chunks[0].content
    for previous, chunk in zip(chunks, chunks[1:]):
        assert chunk.start == previous.end - 10
        assert chunk.end > previous.end
        rebuilt += chunk.content[previous.end - chunk.start:]
    assert rebuilt == content
    assert all(chunk.content == content[chunk.start:chunk.end] for chunk in chunks)
    assert all(len(chunk.content) <= 80 for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_paragraph_boundary_is_preferred():
    content = "a" * 55 + "\n\n" + "b" * 90
    chunks = split_document(content, chunk_size=80, overlap=10)
    assert chunks[0].end == 57


@pytest.mark.parametrize("size,overlap", [(True, 0), (1, 0), (80, -1), (80, 40), (80, True)])
def test_invalid_parameters(size, overlap):
    with pytest.raises(ValueError):
        split_document("text", chunk_size=size, overlap=overlap)
