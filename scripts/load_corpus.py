#!/usr/bin/env python3
"""Load `data/corpus.json` into the running API, one document per request.

This talks HTTP to an already-running API on `API_URL` (default
`http://localhost:8000`). It holds no credentials, reads no DSN and constructs
no database connection of its own: the API owns the database, and a loader that
also wrote directly would be a second, differently-behaving ingestion path whose
bugs would look like API bugs.

Usage, from the repository root:

    .venv/bin/python scripts/load_corpus.py

It is IDEMPOTENT. `POST /documents` upserts by `document_id`, so running this
twice leaves exactly the same rows as running it once — the second run updates
them in place. That is what makes it safe to re-run after a corpus change, and
safe to leave in a runbook.

It exits NON-ZERO if any document failed. A loader that prints a cheerful
summary while having silently dropped a third of the corpus is worse than one
that crashes: the summary would be believed, and the missing documents would
only be noticed when somebody searched for something that should have been
there.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import requests

# The API under test, read from the environment with a localhost default —
# matching the convention in api/tests/test_db.py and api/tests/test_integration.py,
# so the whole project can be pointed at another host without editing a file.
DEFAULT_BASE_URL = os.environ.get("API_URL", "http://localhost:8000")

# The corpus, relative to the repository root. Computed from this file's own
# location rather than from the working directory, so the script runs the same
# whether it is invoked from the root, from `scripts/`, or from an absolute path
# in a cron entry. `parents[1]` is the repository root: this file is
# `<root>/scripts/load_corpus.py`.
CORPUS_PATH = Path(__file__).resolve().parents[1] / "data" / "corpus.json"

# Per-document timeout. Generous, because each request embeds text through a
# CPU-only llama.cpp worker on a t3.micro and 40 of them run back to back — the
# API's own inference budget is 120s (INFERENCE_TIMEOUT_SECONDS), so a timeout
# much below that would fail requests the API was about to serve successfully.
REQUEST_TIMEOUT_SECONDS = 180.0


def load_documents(path: Path) -> list[dict[str, Any]]:
    """Read the corpus file and return its documents.

    Fails loudly on a malformed corpus rather than posting whatever parsed. A
    half-read corpus posted through an idempotent loader looks exactly like a
    successful one, and the difference is only visible in the row counts of a
    collection nobody was watching.
    """
    with path.open(encoding="utf-8") as handle:
        corpus = json.load(handle)

    documents = corpus["documents"]
    if not documents:
        raise SystemExit(f"{path} contains no documents — refusing to load nothing")

    return documents


def post_document(session: requests.Session, base_url: str, document: dict[str, Any]) -> str | None:
    """POST one document. Returns None on success, or a short failure reason.

    ── WHY THE RESPONSE BODY IS NEVER PRINTED ─────────────────────────────────
    This looks like a missing diagnostic and is not. FastAPI's 422 body is
    `[{"loc": [...], "msg": "...", "input": <the offending value>}]` — the
    `input` key echoes the value the caller actually sent. Printing
    `response.text` would therefore put up to a hundred-odd characters of a
    document's own text into terminal scrollback, which is exactly the kind of
    thing that gets pasted into a ticket. A field NAME is what an operator needs
    to fix a bad corpus and cannot carry a document.

    The exception branch likewise reports the exception CLASS, not its message:
    `requests` messages embed the URL and vary between versions.
    """
    payload = {
        "document_id": document["id"],
        "collection": document["collection"],
        "content": document["content"],
        "metadata": document.get("metadata", {}),
    }

    try:
        response = session.post(f"{base_url}/documents", json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return f"{type(exc).__name__}"

    if response.status_code in (200, 201):
        return None

    if response.status_code == 422:
        try:
            fields = sorted({".".join(str(part) for part in error["loc"]) for error in response.json()["detail"]})
        except (ValueError, KeyError, TypeError):
            # The body was not the 422 shape FastAPI produces. Report that fact
            # rather than echoing whatever arrived.
            fields = ["<unparseable detail>"]
        return f"HTTP 422: invalid field(s) {', '.join(fields)}"

    return f"HTTP {response.status_code}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"API base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--corpus", default=str(CORPUS_PATH), type=Path, help="path to corpus.json")
    args = parser.parse_args()

    documents = load_documents(args.corpus)

    print(f"loading {len(documents)} document(s) into {args.base_url}")

    sent_by_collection: Counter[str] = Counter()
    failed_by_collection: Counter[str] = Counter()
    failures: list[tuple[str, str]] = []

    # One session for the whole run so the TCP connection to the API is reused
    # across all 40 requests instead of re-established per document.
    with requests.Session() as session:
        for index, document in enumerate(documents, start=1):
            collection = document["collection"]
            reason = post_document(session, args.base_url, document)

            if reason is None:
                sent_by_collection[collection] += 1
            else:
                failed_by_collection[collection] += 1
                failures.append((document["id"], reason))

            # Progress on one line per document: a loader that is silent for two
            # minutes and then prints a summary gives an operator no way to tell
            # "slow" from "hung".
            status_char = "ok " if reason is None else "FAIL"
            print(f"  [{index:>3}/{len(documents)}] {status_char} {document['id']}")
            if reason is not None:
                print(f"        {reason}")

    # ── The summary, with NUMBERS ──────────────────────────────────────────────
    # Per-collection counts rather than one total, because "40 sent" and "20
    # infrastructure, 20 it-support" answer different questions and only the
    # second one can catch a loader that dropped a whole collection.
    all_collections = sorted(set(sent_by_collection) | set(failed_by_collection))
    print()
    print(f"{'collection':<20} {'sent':>6} {'failed':>7}")
    print(f"{'-' * 20} {'-' * 6} {'-' * 7}")
    for collection in all_collections:
        print(
            f"{collection:<20} {sent_by_collection[collection]:>6} "
            f"{failed_by_collection[collection]:>7}"
        )
    print(f"{'-' * 20} {'-' * 6} {'-' * 7}")
    print(f"{'TOTAL':<20} {sum(sent_by_collection.values()):>6} {sum(failed_by_collection.values()):>7}")

    if failures:
        print()
        print(f"{len(failures)} document(s) FAILED:")
        for document_id, reason in failures:
            print(f"  {document_id}: {reason}")
        print()
        print("Exiting non-zero. The corpus is INCOMPLETE — re-run this script")
        print("(it is idempotent) or check the API logs for the reasons above.")
        return 1

    print()
    print(f"All {len(documents)} document(s) stored. This run was idempotent: re-running it")
    print("updates the same rows rather than creating duplicates.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
