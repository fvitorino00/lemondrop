"""Validation-contract tests for the four API request models.

**NO SERVICES. NO STUBS. NO NETWORK.** This module imports `app.main` and asserts
what its Pydantic request models accept and reject. Nothing here starts a server,
opens a socket, constructs a database engine, or replaces a collaborator with a
fake. `app.main` builds its engine only inside `lifespan` and reads its
environment with defaults at import time, so importing it — which is all this
module does — touches neither PostgreSQL nor either inference worker. The whole
file runs with Docker stopped, with no `.env`, and with `DATABASE_URL` and
`API_URL` unset.

**Why the contract is worth a module of its own.** The validation rule for these
bodies is not decoration: FastAPI turns a failed Pydantic validation into a 422
naming the offending field automatically, and that is the ONLY thing standing
between a malformed request and an inference call (or a permanent database row)
built from it. The rule lives in `app.main` — `NonBlankText` strips whitespace
*then* enforces `min_length=1`, so `""` and `"   "` are both rejected;
`NonBlankItem` enforces `min_length=1` with NO stripping. These tests read that
rule from the outside, through the same constructor FastAPI uses, so an accidental
relaxation of it fails here rather than as a 200 with a blank vector in it.

**What this file deliberately does NOT assert.** The status code of a real HTTP
502 from an inference worker (work item A1(d)): producing a genuine worker
502 requires a live inference worker, which this service-free module cannot
provide. That guarantee — the client-facing 502 detail must not contain worker
internals such as "batch size" — is verified by code review on `app.main`
(`_post_upstream` performs a real httpx call and cannot be exercised without a
worker).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.main import (
    DocumentRequest,
    EmbedRequest,
    MAX_INFERENCE_INPUT_CHARS,
    RerankRequest,
    SearchRequest,
    _strip_internal_metadata,
)

# ── EmbedRequest ──────────────────────────────────────────────────────────────
#
# One required field. `NonBlankText` strips first, so both an empty string and a
# whitespace-only string collapse to "" and are rejected by `min_length=1`.


def test_embed_requires_text() -> None:
    """Omitting `text` entirely is a validation error, not a default."""
    with pytest.raises(ValidationError):
        EmbedRequest()


@pytest.mark.parametrize("blank", ["", "   "])
def test_embed_rejects_blank_text(blank: str) -> None:
    """`""` and `"   "` are both invalid; stripping is what makes the second one so."""
    with pytest.raises(ValidationError):
        EmbedRequest(text=blank)


def test_embed_accepts_a_normal_text() -> None:
    """A non-blank string constructs, and survives unchanged."""
    request = EmbedRequest(text="hello")

    assert request.text == "hello"


def test_embed_rejects_oversized_text() -> None:
    """Text above MAX_INFERENCE_INPUT_CHARS is refused with a `string_too_long` error naming `text` and the limit."""
    oversized = "x" * (MAX_INFERENCE_INPUT_CHARS + 1)
    with pytest.raises(ValidationError) as excinfo:
        EmbedRequest(text=oversized)
    errors = excinfo.value.errors()
    assert any(
        e["type"] == "string_too_long"
        and "text" in e["loc"]
        and e.get("ctx", {}).get("max_length") == MAX_INFERENCE_INPUT_CHARS
        for e in errors
    ), errors


def test_embed_accepts_text_at_and_just_under_limit() -> None:
    """Text at and just under the limit is accepted; the limit itself is inclusive."""
    EmbedRequest(text="x" * MAX_INFERENCE_INPUT_CHARS)
    EmbedRequest(text="x" * (MAX_INFERENCE_INPUT_CHARS - 1))


# ── RerankRequest ─────────────────────────────────────────────────────────────
#
# `query` follows the same non-blank rule as EmbedRequest.text. `documents` must
# be a list with at least one entry, and each entry must be non-empty (but is NOT
# stripped — see NonBlankItem). `top_n`, when supplied, must be >= 1.


def test_rerank_requires_query() -> None:
    """`query` is required; `documents` alone is not a valid body."""
    with pytest.raises(ValidationError):
        RerankRequest(documents=["d"])


@pytest.mark.parametrize("blank", ["", "   "])
def test_rerank_rejects_a_blank_query(blank: str) -> None:
    """A query made of whitespace cannot be ranked against anything."""
    with pytest.raises(ValidationError):
        RerankRequest(query=blank, documents=["d"])


def test_rerank_rejects_an_empty_documents_list() -> None:
    """`documents=[]` is rejected by `min_length=1`, not scored as a ranking of nothing."""
    with pytest.raises(ValidationError):
        RerankRequest(query="q", documents=[])


def test_rerank_rejects_a_blank_document_entry() -> None:
    """An empty-string entry is rejected by `NonBlankItem`'s `min_length=1`."""
    with pytest.raises(ValidationError):
        RerankRequest(query="q", documents=[""])


def test_rerank_rejects_documents_that_are_not_a_list() -> None:
    """A bare string is not coerced into a list of characters; it is refused."""
    with pytest.raises(ValidationError):
        RerankRequest(query="q", documents="abc")


@pytest.mark.parametrize("bad_top_n", [0, -1])
def test_rerank_rejects_a_non_positive_top_n(bad_top_n: int) -> None:
    """`ge=1`: a zero or negative `top_n` is a caller mistake, not a no-op."""
    with pytest.raises(ValidationError):
        RerankRequest(query="q", documents=["d"], top_n=bad_top_n)


def test_rerank_accepts_an_explicit_none_top_n() -> None:
    """`top_n=None` is the documented "not sent" value and is accepted."""
    assert RerankRequest(query="q", documents=["d"], top_n=None).top_n is None


def test_rerank_accepts_a_positive_top_n() -> None:
    """A positive `top_n` survives as given."""
    assert RerankRequest(query="q", documents=["d"], top_n=5).top_n == 5


def test_rerank_minimal_request_defaults_top_n_to_none() -> None:
    """The smallest valid body constructs, and `top_n` defaults to `None`, not a number."""
    request = RerankRequest(query="q", documents=["d"])

    assert request.query == "q"
    assert request.documents == ["d"]
    assert request.top_n is None


def test_rerank_rejects_oversized_document_entry() -> None:
    """A document entry above MAX_INFERENCE_INPUT_CHARS is refused before it reaches the reranker."""
    oversized = "x" * (MAX_INFERENCE_INPUT_CHARS + 1)
    with pytest.raises(ValidationError):
        RerankRequest(query="q", documents=[oversized])


def test_rerank_rejects_whitespace_only_document_entry() -> None:
    """A whitespace-only document entry is blank after stripping and is refused."""
    with pytest.raises(ValidationError):
        RerankRequest(query="q", documents=["   "])


def test_rerank_accepts_padded_document_without_rewrite() -> None:
    """A non-blank document entry is accepted verbatim: whitespace is NOT stripped or rewritten."""
    request = RerankRequest(query="q", documents=["  padded  "])
    assert request.documents == ["  padded  "]


# ── DocumentRequest ───────────────────────────────────────────────────────────
#
# Three `NonBlankText` fields (`document_id`, `collection`, `content`) and one
# object field (`metadata`) defaulting to `{}` — never `None`, because the column
# is `JSONB NOT NULL DEFAULT '{}'` and a JSON null is deliberately ruled out.


@pytest.mark.parametrize("omitted", ["document_id", "collection", "content"])
def test_document_requires_each_field(omitted: str) -> None:
    """Each of the three string fields is required; omitting any one is refused."""
    payload = {"document_id": "id", "collection": "c", "content": "t"}
    del payload[omitted]

    with pytest.raises(ValidationError):
        DocumentRequest(**payload)


@pytest.mark.parametrize("field", ["document_id", "collection", "content"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_document_rejects_blank_fields(field: str, blank: str) -> None:
    """Every string field is `NonBlankText`; a blank value is refused by name."""
    payload = {"document_id": "id", "collection": "c", "content": "t"}
    payload[field] = blank

    with pytest.raises(ValidationError):
        DocumentRequest(**payload)


def test_document_metadata_defaults_to_an_empty_dict() -> None:
    """Absent metadata is `{}`, the documented default — and specifically not `None`."""
    request = DocumentRequest(document_id="id", collection="c", content="t")

    assert request.metadata == {}


@pytest.mark.parametrize("bad_metadata", [[1, 2, 3], "a string", 42])
def test_document_rejects_non_object_metadata(bad_metadata: object) -> None:
    """A list, a string or a number is refused at the edge, not at the INSERT."""
    with pytest.raises(ValidationError):
        DocumentRequest(
            document_id="id",
            collection="c",
            content="t",
            metadata=bad_metadata,
        )


def test_document_metadata_round_trips() -> None:
    """A JSON object is accepted and preserved exactly."""
    request = DocumentRequest(
        document_id="id",
        collection="c",
        content="t",
        metadata={"source": "x"},
    )

    assert request.metadata == {"source": "x"}


# REGRESSION: docs/verification-milestone-3.md §5.2 records 40/40 documents
# ingested through POST /documents, and data/corpus.json measures document
# content at 1244–1874 characters (median 1384.5, maximum 1874). The old
# 768-character cap was BELOW the corpus minimum and would have rejected all
# 40 documents with a 422 — a 100% regression on a verified path. A realistic
# 1874-character document must be accepted.
def test_document_accepts_corpus_maximum_length_content() -> None:
    """A realistic 1874-character document (the measured corpus maximum) is accepted.

    Cites data/corpus.json (§5.2's 40/40 record): content of this length must
    not be refused by MAX_INFERENCE_INPUT_CHARS, which is now 2048 chars
    (= 512 tokens x ~4 chars/token at realistic BPE prose density).
    """
    content = "x" * 1874
    request = DocumentRequest(document_id="id", collection="c", content=content)
    assert request.content == content


# Identifiers (document_id, collection) are never forwarded to an inference
# worker, so they carry NO max_length. A 1000-character identifier must be
# accepted — it never reaches a worker and has no token ceiling.
def test_document_accepts_long_identifiers_uncapped() -> None:
    """document_id and collection of 1000 characters are accepted (no max_length)."""
    long_id = "x" * 1000
    long_collection = "y" * 1000
    request = DocumentRequest(
        document_id=long_id,
        collection=long_collection,
        content="t",
    )
    assert request.document_id == long_id
    assert request.collection == long_collection


# ── SearchRequest ─────────────────────────────────────────────────────────────
#
# Two required `NonBlankText` fields (`collection`, `query`) and two optional
# `ge=1` sizes (`candidates`, `top_k`) that default to `None` — "use the server's
# configured funnel" — rather than to a number restated here.


@pytest.mark.parametrize("omitted", ["collection", "query"])
def test_search_requires_each_field(omitted: str) -> None:
    """Both `collection` and `query` are required."""
    payload = {"collection": "c", "query": "q"}
    del payload[omitted]

    with pytest.raises(ValidationError):
        SearchRequest(**payload)


@pytest.mark.parametrize("field", ["collection", "query"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_search_rejects_blank_fields(field: str, blank: str) -> None:
    """Both required fields are `NonBlankText`; a blank value is refused."""
    payload = {"collection": "c", "query": "q"}
    payload[field] = blank

    with pytest.raises(ValidationError):
        SearchRequest(**payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("candidates", 0), ("candidates", -5), ("top_k", 0)],
)
def test_search_rejects_non_positive_sizes(field: str, value: int) -> None:
    """`candidates` and `top_k` are `ge=1`; a zero or negative size is refused."""
    payload = {"collection": "c", "query": "q", field: value}

    with pytest.raises(ValidationError):
        SearchRequest(**payload)


def test_search_optional_sizes_default_to_none() -> None:
    """Omitted `candidates` and `top_k` are both `None` — the server resolves them."""
    request = SearchRequest(collection="c", query="q")

    assert request.candidates is None
    assert request.top_k is None


def test_search_accepts_positive_sizes() -> None:
    """A valid request with both sizes set constructs, and both survive."""
    request = SearchRequest(collection="c", query="q", candidates=10, top_k=3)

    assert request.collection == "c"
    assert request.query == "q"
    assert request.candidates == 10
    assert request.top_k == 3


def test_search_rejects_oversized_query() -> None:
    """A search query above MAX_INFERENCE_INPUT_CHARS is refused before it reaches the embedder."""
    oversized = "x" * (MAX_INFERENCE_INPUT_CHARS + 1)
    with pytest.raises(ValidationError):
        SearchRequest(collection="c", query=oversized)


def test_strip_internal_metadata_removes_canary_preserves_caller_keys() -> None:
    """The response-metadata filter drops `isolation_canary` and preserves ordinary caller keys."""
    metadata = {"source": "x", "isolation_canary": True, "page": 3}
    assert _strip_internal_metadata(metadata) == {"source": "x", "page": 3}
    # The input dict is not mutated.
    assert metadata == {"source": "x", "isolation_canary": True, "page": 3}


def test_strip_internal_metadata_keeps_caller_metadata_intact_without_canary() -> None:
    """Ordinary caller metadata with no internal keys passes through unchanged."""
    metadata = {"source": "x", "page": 3}
    assert _strip_internal_metadata(metadata) == metadata
