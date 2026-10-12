"""Integration tests for the LemonDrop API.

These are INTEGRATION tests, not unit tests. They make real HTTP calls against a
running stack -- there is no mocking and no in-process test client.

The stack must already be running before pytest is invoked. From the repository
root:

    cp .env.example .env
    ./scripts/fetch-models.sh
    docker compose up -d --build

Then run the suite from the repository root with the project virtual
environment active:

    python -m pytest api/tests/test_integration.py -v

If the API is not running, every test in this file fails. That is correct
behaviour, not a broken test: a connection error means the stack is down, and
the assertions here have no meaning without a live service behind them.

What this suite protects: the 384-dimension embedding contract (both the
declared ``dimensions`` field and the length of the vector actually returned),
validation of blank input, correct best-first reranking, and preservation of
the caller's original document indices through the rerank results.
"""

import os
import requests

#Read from the environment so the suite can point at  a different host
#without editing this file. The default is where compose publishes the API
BASE_URL = os.environ.get("API_URL", "http://localhost:8000")


def test_health_reports_all_dependencies_ok():
    """The API should report itself healthy with both workers reachable."""
    response = requests.get(f"{BASE_URL}/health")

    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["embedder"] == "ok"
    assert body["reranker"] == "ok"


def test_embed_returns_384_dimensions():
    """The embedding route returns a 384-dimension vector, as declared and as sent."""
    response = requests.post(
        f"{BASE_URL}/embed",
        json={"text": "how do I reset my password"},
    )

    assert response.status_code == 200

    body = response.json()
    # Both are asserted on purpose. "dimensions" is what the API *claims* it
    # produced; len(embedding) is what the data actually *is*. Asserting only
    # the claim would let a bug through where the API reports 384 while
    # returning some other number of floats, and every downstream consumer
    # that trusts the declared field would break at a distance.
    assert body["dimensions"] == 384
    assert len(body["embedding"]) == 384


def test_embed_rejects_blank_text():
    """The embed route rejects whitespace-only text, not just an empty string."""
    # Whitespace on purpose, not "". An empty string is the easy case and every
    # naive `if not text` guard already catches it. But "   " is truthy in
    # Python, so a guard written as `if not text` lets it straight through and
    # the worker gets called on nothing. This is the case that actually bites.
    response = requests.post(f"{BASE_URL}/embed", json={"text": "   "})

    assert response.status_code == 422


def test_rerank_ranks_the_relevant_document_first():
    """The reranker puts the genuinely relevant document at the top of the results."""
    response = requests.post(
        f"{BASE_URL}/rerank",
        json={
            "query": "how do I reset my password",
            "documents": [
                "To reset your password click Forgot Password.",
                "The weather in Paris is mild.",
                "MySQL index tuning guide",
            ],
        },
    )

    assert response.status_code == 200

    body = response.json()
    # Document 0 is the password doc, so a working reranker must rank it first.
    assert body["results"][0]["index"] == 0

    # Walking consecutive pairs checks the WHOLE list is sorted best-first,
    # not just that the winner landed in slot 0. That is the stronger claim: a
    # worker that returns results in the caller's original order but scores
    # them correctly would pass a first-element-only check, and every caller
    # that reads results[0] as "best match" would silently get the wrong doc.
    scores = [result["relevance_score"] for result in body["results"]]
    for earlier, later in zip(scores, scores[1:]):
        assert earlier >= later


def test_rerank_rejects_empty_documents():
    """The rerank route refuses a request that carries no documents to score."""
    response = requests.post(
        f"{BASE_URL}/rerank",
        json={"query": "anything", "documents": []},
    )

    assert response.status_code == 422


def test_rerank_preserves_original_document_indices():
    """Each result carries the index the caller originally sent, not its rank."""
    response = requests.post(
        f"{BASE_URL}/rerank",
        json={
            "query": "how do I reset my password",
            "documents": [
                "To reset your password click Forgot Password.",
                "The weather in Paris is mild.",
                "MySQL index tuning guide",
            ],
        },
    )

    assert response.status_code == 200

    body = response.json()
    indices = [result["index"] for result in body["results"]]

    # Results come back sorted best-first, so the order we should see is:
    # the password doc (sent at position 0) first, the MySQL doc (sent at
    # position 2) second, and the weather doc (sent at position 1) last --
    # hence [0, 2, 1] rather than [0, 1, 2].
    #
    # This locks in that "index" is the caller's ORIGINAL array position and not
    # the rank. If the API ever renumbered index by result position, every
    # caller would map each score onto the wrong document, and nothing would
    # raise: the request succeeds, the scores look fine, and the wrong snippets
    # get shown to users. This test is the only thing standing between that bug
    # and production.
    #
    # Asserting the exact list rather than just "0 came first" is safe because
    # the ranking of these three fixed documents is deterministic and repeats
    # exactly, so the full sequence is stable.
    assert indices == [0, 2, 1]
