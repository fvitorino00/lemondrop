# LemonDrop — client guide

> This document describes the **API surface only**. It is for an external client
> or tester who calls the HTTP API and does not administer the infrastructure
> behind it. Deployment, operations, rollback and teardown are **not** described
> here and are out of scope for a client — see §9.

Everything below was read from the running service, its source, or captured
evidence. Any value that could not be verified has been omitted or marked
`[TO BE CONFIRMED]` rather than guessed.

---

## 1. What LemonDrop does

LemonDrop is a **two-stage document-retrieval API**. You hand it text and a
collection name; it hands back the documents from that collection that are most
relevant to your text.

The two stages are:

1. **Embedding.** Text is turned into a 384-dimensional numeric vector by a
   model (`bge-small-en-v1.5`). Two pieces of text that mean similar things end
   up with vectors that sit close together.
2. **Retrieval and reranking.** For a search, the API:

   1. turns your **query** into a vector;
   2. asks the database for the nearest stored document vectors **within the
      collection you named** (this is stage 1, scored by vector `distance`);
   3. sends those candidates through a second model (`bge-reranker-base`) that
      scores each one against your query (this is stage 2, scored by
      `relevance_score`);
   4. returns the best few, best first.

Documents are added to the store with `POST /documents`; the API embeds them at
ingestion time and keeps the vector. You never send a vector yourself.

The API is the single point of access. It is the only reachable component.

---

## 2. How a client accesses it

**Base URL:**

```
<BASE_URL>
```

`<BASE_URL>` stands for the scheme-and-host prefix of the service — the prefix
you put in front of every path in §3. **The actual base URL, and the
authorization to reach it, are provided separately by the service owner and are
not printed in this document.** To get started, contact the service owner: the
owner supplies the base URL and adds your source address to the network
allow-list (§2). Set it once in your shell and use it for every request; the
examples below use `$BASE_URL` for the same value.

The deployment that was observed while this document was written was reached
over **plain HTTP on port 80** (not HTTPS). Use the exact scheme and host the
owner gives you, since that is what decides whether TLS applies.

**The API enforces no application-level authentication.** It does not require a
token, an API key, a header or a credential of any kind, and nothing about your
identity is checked at the application layer. This was verified in the service's
source: there is no authentication dependency, middleware, header check or API
key anywhere in the application.

Because there is no application-level authentication, access is restricted
instead at the **network layer**, by an **allow-list of source addresses**. This
has two consequences you must know before you conclude that the service is down:

- If your source address **is** on the allow-list, requests work as described
  here.
- If your source address **is not** on the allow-list, your request **fails at
  the connection level, with no HTTP response at all**. It will **not** return
  an HTTP status code or an error body, because it never reaches the API. A
  `curl` command that sits and then fails with a connection or timeout error,
  rather than printing an HTTP response, is the signature of an address that is
  not allow-listed — not of a broken API.

**If your requests hang or are refused at the connection level, contact the
owner of this service and ask for your source address to be added to the
allow-list.** The allow-listed address itself is deliberately not printed in
this document.

---

## 3. Supported endpoints and HTTP methods

These are the **complete** set of **application** routes the API serves. There
are exactly seven. Anything not in this table is not an application route of
the API. FastAPI additionally serves the standard documentation endpoints
`/openapi.json`, `/docs` and `/redoc` (the default FastAPI constructor in
`api/app/main.py`); `api/tests/test_search.py` asserts `/openapi.json` is
reachable. Those three are framework-served, not application routes, and are not
listed in this table.

| Method | Path | Purpose | Body fields |
|---|---|---|---|
| `GET` | `/health` | Are the two inference models ready? | none |
| `GET` | `/health/live` | Is the process alive? | none |
| `GET` | `/health/ready` | Can the API serve a request right now (models **and** database)? | none |
| `POST` | `/embed` | Turn one piece of text into one vector. | **required:** `text` |
| `POST` | `/rerank` | Score and rank a list of documents against a query. | **required:** `query`, `documents`; **optional:** `top_n` |
| `POST` | `/documents` | Embed one document and store it (a **write**). | **required:** `document_id`, `collection`, `content`; **optional:** `metadata` |
| `POST` | `/search` | Retrieve and rerank the best documents in one collection. | **required:** `collection`, `query`; **optional:** `candidates`, `top_k` |

Field rules, all enforced by the service:

- `text`, `query`, `document_id`, `collection` and `content` must be non-blank.
  Leading and trailing whitespace is **stripped first**, then an empty result is
  rejected — so `"   "` is invalid, and a request carrying it returns **422**.
- `documents` must be a list with **at least one** entry. An empty list returns
  **422**.
- `metadata` must be a **JSON object** (for example `{"source": "runbook-v3"}`),
  never an array, string or number. It defaults to `{}` when omitted. A
  non-object returns **422**.
- `candidates` and `top_k` must each be **≥ 1** if supplied. `0` or a negative
  value returns **422**. Values **larger** than the service is configured to
  compute are **not** an error: they are silently **clamped down** to the
  configured maximum. `top_k` is additionally capped at the number of
  candidates considered (see §6).
- `top_n` on `/rerank` must be **≥ 1** if supplied. When omitted, the API does
  not send it to the worker at all, and the worker applies its own default.

- Worker-bound text fields — `text` on `POST /embed`, `query` on `POST /search`,
  and each document entry on `POST /rerank` — are limited to **2048 characters**.
  A longer value is refused at the API edge with **422** naming the field and the
  limit, instead of being forwarded to a worker that would answer with a permanent
  502. The 2048-character figure is a CHARACTER proxy for the worker's 512-token
  ceiling (512 tokens × ~4 chars/token of realistic BPE prose) and cannot be
  exact: tokenisation is not a function of character count alone, so pathological
  low-density input (long unbroken character runs) can still exceed the worker's
  token limit below 2048 characters and produce a non-retryable 502. That is a
  KNOWN residual (see §5).

- Identifiers (`document_id`, `collection`) have **no length limit**. They are
  never forwarded to an inference worker, so the worker's token ceiling does not
  apply to them; only non-blankness is required.

- `POST /rerank` document **entries**: an entry that is whitespace-only is
  rejected (422). A non-blank entry is accepted and passed through **unchanged**
  — entries are NOT stripped or rewritten. Padding such as `"  padded  "` is kept
  verbatim.

- `POST /rerank`'s 512-token worker limit applies to the (query, passage)
  **PAIR**, not to either field in isolation. Two values that are each
  individually in limit can still be refused by the worker because their combined
  length exceeds the ceiling. That is a known, accepted residual and is stated
  honestly here rather than concealed behind the per-field limit.

---

## 4. Headers, request bodies, and example `curl` commands

Send `Content-Type: application/json` on every `POST`. The GET routes take no
body.

In the examples below, set the base URL once in your shell, to the value the
service owner gave you:

```
BASE_URL="<BASE_URL>"
```

(The examples use `-sS -i`: `-sS` shows errors instead of hiding them, and `-i` includes the response status line and headers — useful for diagnosing what the client actually received.)

### `GET /health`

```
curl -sS -i "$BASE_URL/health"
```

### `GET /health/live`

```
curl -sS -i "$BASE_URL/health/live"
```

### `GET /health/ready`

```
curl -sS -i "$BASE_URL/health/ready"
```

### `POST /embed`

```
curl -sS -i "$BASE_URL/embed" \
  -H "Content-Type: application/json" \
  -d '{"text":"how do I reset my password"}'
```

### `POST /rerank`

```
curl -sS -i "$BASE_URL/rerank" \
  -H "Content-Type: application/json" \
  -d '{
        "query": "how do I reset my password",
        "documents": [
          "To reset your password click Forgot Password.",
          "The weather in Paris is mild.",
          "MySQL index tuning guide"
        ]
      }'
```

### `POST /documents` — **this is a write; it persists data**

> The example below **stores a document**. Re-POSTing the same `document_id`
> later **updates** the existing row in place (it is an upsert — see §6); it does
> not create a duplicate and does not error. Treat this route as a mutation, not
> a query. The example uses an illustrative collection name; the deployed corpus
> uses `it-support` and `infrastructure`.

```
curl -sS -i "$BASE_URL/documents" \
  -H "Content-Type: application/json" \
  -d '{
        "document_id": "runbook-reset-password",
        "collection": "runbooks",
        "content": "To reset your password click Forgot Password.",
        "metadata": {"source": "runbook-v3"}
      }'
```

### `POST /search`

```
curl -sS -i "$BASE_URL/search" \
  -H "Content-Type: application/json" \
  -d '{
        "collection": "it-support",
        "query": "how do I recover files a user deleted from the Recycle Bin on their workstation"
      }'
```

`candidates` and `top_k` may be added to narrow the result; for example
`"candidates": 10, "top_k": 5`. Omitting them uses the service's configured
defaults.

---

## 5. Example successful responses and error responses

The bodies below match the implemented response models. The specific numbers
shown are examples of the shape and magnitude the service returns; they are not
guarantees and are not reproducible figures. The one run this document records
as an actual observation is described separately in §6. An embedding vector is
elided below because it is 384 floats long.

### `GET /health` — 200

```json
{"status":"ok","embedder":"ok","reranker":"ok"}
```

`status` is `ok` only when **both** models answered. When one is not ready,
`status` is `degraded` and the failing field carries a short reason instead of
`ok` (for example `unreachable: ConnectError`, `unhealthy: HTTP 503`, or
`timeout after 5.0s`), and the HTTP status is **503** at the same time.

### `GET /health/live` — 200

```json
{"status":"ok"}
```

This route always returns 200 and checks nothing.

### `GET /health/ready` — 200

```json
{"status":"ok","embedder":"ok","reranker":"ok","database":"ok"}
```

Same shape and same 200/503 semantics as `/health`, plus a `database` verdict.
When any of the three dependencies is unavailable the status is **503** and
`status` is `degraded`.

### `POST /embed` — 200

```json
{
  "embedding": [-0.02694462426006794, -0.020908871665596962, 0.03651421144604683, "... 381 more floats ..."],
  "dimensions": 384,
  "model": "bge-small-en-v1.5"
}
```

`dimensions` is the width actually returned, and `model` echoes the model alias.
The real `embedding` array contains 384 numbers.

### `POST /rerank` — 200

```json
{
  "results": [
    {"index": 0, "relevance_score": 2.732536792755127},
    {"index": 2, "relevance_score": -7.271678924560547},
    {"index": 1, "relevance_score": -10.19521713256836}
  ],
  "model": "bge-reranker-base"
}
```

`index` is the position the document occupied **in the array you sent** — not
its rank. The list is sorted best-first, so the example's order `0, 2, 1` means
your first document scored best, your third second, and your second last.
`relevance_score` is higher-is-better and is comparable **only within this one
response**.

### `POST /documents` — **201 Created**

```json
{
  "document_id": "runbook-reset-password",
  "collection": "runbooks",
  "dimensions": 384,
  "outcome": "inserted"
}
```

This route returns **201**, not 200. `outcome` is `"inserted"` for a new row or
`"updated"` when the `document_id` already existed. `dimensions` is the width
the database actually stored.

### `POST /search` — 200

```json
{
  "results": [
    {
      "document_id": "support-recycle-bin-file-recovery",
      "collection": "it-support",
      "content": "Purpose: recover a file a user deleted by mistake ...",
      "metadata": {"tags": ["file-recovery", "recycle-bin", "data-loss", "workstation"],
                   "owner": "it-support", "title": "Recover a deleted file from the Recycle Bin",
                   "severity": "high", "updated_at": "2026-04-30"},
      "relevance_score": 8.900704383850098,
      "distance": 0.1570872664451599
    }
  ],
  "collection": "it-support",
  "candidates_considered": 10,
  "model": "bge-reranker-base"
}
```

### Error responses

**422 — validation error.** Returned when a request body is malformed — a blank
required string, an empty `documents` list, a `metadata` that is not an object,
or a `candidates`/`top_k` below 1. FastAPI's standard `detail` shape is used:

```json
{"detail":[{"type":"string_too_short","loc":["body","text"],
            "msg":"String should have at least 1 character",
            "input":"   ","ctx":{"min_length":1}}]}
```

and for an empty document list:

```json
{"detail":[{"type":"too_short","loc":["body","documents"],
            "msg":"List should have at least 1 item after validation, not 0",
            "input":[],"ctx":{"field_type":"List","min_length":1,"actual_length":0}}]}
```

**502 — bad gateway.** The API itself is reachable; one of its inference workers
failed while serving this request. This covers a worker that is unreachable,
that answered a non-2xx status, or that returned a body that was not JSON.

A 502 is **either transient or permanent**:

- **Transient (retryable):** the worker is unreachable, answered a non-2xx
  status, or returned a non-JSON body. A request that returns 502 for one of
  these reasons may be retried, optionally with backoff.
- **Permanent (not retryable):** the input the API forwarded is one the worker
  refuses — for example pathological low-density text whose character count is
  below the 2048-character edge limit but still exceeds the worker's 512-token
  ceiling. Oversized input is caught at the edge with a 422 naming the field
  and the limit (§3), but the character proxy cannot be exact, so this residual
  remains: do not retry a permanent 502, because retrying will fail the same way
  every time.

The body is a short sentence naming the worker and the HTTP status, for example:

```json
{"detail":"embedder returned HTTP 500"}
```

The full upstream worker detail is logged server-side only and is NOT echoed
into the client-facing response.

**503 — service unavailable.** The **database** is unavailable or erroring while
serving `POST /documents` or `POST /search`; the body is:

```json
{"detail":"the database is not available"}
```

503 is also what `/health` and `/health/ready` return when a dependency is down.
This is the same claim: the API cannot serve the request right now.

Two related cases, stated so their status codes are not a surprise: if the
database fails **while** `POST /search` is running, that is also **503**, with
the body `{"detail":"the document store could not be searched"}`. If storage
fails **while** `POST /documents` is running, that is **502**
(`{"detail":"the document could not be stored"}`) — the API itself is fine, the
write did not complete.

**504 — gateway timeout.** An inference worker did not answer within the API's
120-second per-call budget — usually a large reranking request on a CPU-only
machine. The body is:

```json
{"detail":"reranker timed out after 120s"}
```

**Empty results are not an error.** `POST /search` against a collection that
holds no documents returns **200** with `"results": []` and
`"candidates_considered": 0` — **not 404**. See §6.

---

## 6. How to test document search and verify results

The intended flow is: **ingest → search → verify**.

### Step 1 — ingest a document (`POST /documents`)

POST a document with a `document_id` you choose. The response is **201**, and
`outcome` tells you what happened:

- `"inserted"` — a new row was created;
- `"updated"` — a row with that `document_id` already existed and was **replaced
  in place**: its content, metadata, embedding **and collection** were
  overwritten.

**`document_id` is a GLOBAL key.** Re-posting the same `document_id` under a
**different** `collection` does not create a second row: it **moves** the
document — it is removed from its original collection and stored under the new
one. The move is **silent**: there is no 409 "already exists" and no response
flag tells you the document left another collection.

Ingestion is idempotent by id, but **only** for a loader that always uses the
same id→collection mapping: re-posting the same id under the same collection is
safe (it replaces the row in place). A single POST with the wrong collection can
irreversibly remove a document from its collection — there is **no delete
endpoint** and **no undo through the API**. A stored document cannot be removed
through the API at all. (You can restore it by re-ingesting the same content
under the original collection, if you still have the content.)

### Step 2 — search (`POST /search`)

POST `collection` and `query`. Optional `candidates` (stage-1 shortlist size) and
`top_k` (stage-2 results returned) may narrow the request; you can ask for
**fewer** than the configured maximum but never **more**. If you omit them, the
service's configured funnel applies — 10 candidates considered, 5 results
returned in the deployed configuration.

### Step 3 — verify the result

Check the following on every response:

- **Every result is in the collection you searched.** Each result carries its own
  `collection`, and the top-level `collection` echoes what you asked for. In a
  correct response, every `results[*].collection` equals it. This is the
  collection-isolation property, and it is what a scoped search must hold.
- **`candidates_considered` explains emptiness.** `0` means stage 1 found no
  documents at all in that collection (or that the name matched nothing).
  `0` with an empty `results` list is the fact "nothing was searched". A
  `candidates_considered` above zero with fewer results means the funnel cut the
  list — the reranker kept the best `top_k` of what stage 1 returned.
- **Both scores are present, and both are comparable only within one response.**
  `relevance_score` is stage 2 (the reranker's opinion; **higher is better**).
  `distance` is stage 1 (the vector distance that put the document into the
  candidate set at all; **lower is better**). Neither number is a percentage or
  a probability, and neither is comparable across models or model versions — only
  against the other scores in the **same** response.
- **There is no index-join step.** Unlike `POST /rerank`, where you must join
  each `index` back onto your own array, `/search` results carry `document_id`
  directly. There is nothing to re-map.

### Illustrative example (not a recorded run)

The request below is representative of a scoped search. The response that
follows is a **representative shape** — it shows the fields a caller receives and
the order in which they arrive. **It is illustrative: it is not a recorded run,
and its values are not reproducible figures.**

```
POST /search
{"collection": "it-support",
 "query": "how do I recover files a user deleted from the Recycle Bin on their workstation"}
```

```json
{
  "results": [
    {"document_id": "support-recycle-bin-file-recovery", "collection": "it-support",
     "relevance_score": 8.900704383850098, "distance": 0.1570872664451599},
    {"document_id": "support-laptop-wipe-reimage", "collection": "it-support",
     "relevance_score": 2.4003798961639404, "distance": 0.2964167418231509},
    {"document_id": "support-workstation-backup-and-restore", "collection": "it-support",
     "relevance_score": 1.3970743417739868, "distance": 0.2801554799079895},
    {"document_id": "support-mfa-reset-locked-out-user", "collection": "it-support",
     "relevance_score": -0.10599058866500854, "distance": 0.425998330116272},
    {"document_id": "support-departing-employee-access-removal", "collection": "it-support",
     "relevance_score": -1.7708392143249512, "distance": 0.4359403588807359}
  ],
  "collection": "it-support",
  "candidates_considered": 10,
  "model": "bge-reranker-base"
}
```

Content and metadata are present on each result and are elided above for
brevity. Note the shape of the check: every result's `collection` is `it-support`
(matching the request), `candidates_considered` is 10, and both `relevance_score`
and `distance` are present on every row.

### Historical observation (recorded once)

A single search scoped to `it-support` was observed, **once**, against the
deployed service. On that one run it returned:

- **HTTP 200**, in **15.234854 s**;
- with **10 candidates considered** and **5 results returned**;
- the document `support-recycle-bin-file-recovery` ranked first.

The exact query string used for that recorded run was **not captured**, so it is
not shown next to the numbers and must not be paired with them. These figures are
a single historical observation of one run against one deployment: they are not a
guarantee, a specification, or a figure any other request should be expected to
reproduce.

---

## 7. Known limitations and currently verified functionality

### Verified

Verified means observed against the deployed service:

- **All seven routes in §3 were observed responding at runtime** —
  `GET /health`, `GET /health/live`, `GET /health/ready` (with
  `"database":"ok"`), `POST /embed` (384 dimensions, `bge-small-en-v1.5`),
  `POST /rerank` (result order `0, 2, 1`) and `POST /search` (200, 10 candidates
  → 5 results) — verified against the deployed service; and `POST /documents`
  was exercised at runtime during Milestone 3, with 40/40 documents ingested
  through it (see `docs/verification-milestone-3.md` §5.2 and §12.5).
- **`POST /search` works against the deployed service** — HTTP 200 in
  15.234854 s, 10 candidates, 5 results, the correct document ranked first
  (`support-recycle-bin-file-recovery` in `it-support`). This was verified
  against the deployed service.
- **Validation rejects bad input** — blank text returns **422**; an empty
  `documents` list returns **422**. This was verified against the deployed
  service.
- **An empty collection returns 200 with an empty result set**, not 404 —
  `"candidates_considered": 0`. This was verified against the deployed service.
- **Semantic search, reranking, collection isolation and `/health/ready`
  returning 200** were verified earlier against the database-backed service.

### Limitations

- **No application-level authentication.** Anyone who can reach the service and
  is on the source-address allow-list can call every route, including the write
  route. Identity is not checked by the API.
- **Source-address allow-list.** Access is restricted at the network layer by
  source address (§2). From an address that is not on the list, requests fail at
  the connection level with no HTTP response. The allow-listed addresses are not
  published here.
- **Entry-point idle timeout versus worst case.** The network entry point in
  front of the API is configured with an idle timeout of **60 s** (a configured
  default in the infrastructure configuration, not a value observed on the
  running deployment), while the API's own worst-case `/search` can reach
  **~240 s** (two sequential 120 s inference
  budgets — one for the query embedding, one for the reranking). A sufficiently
  slow search can therefore be cut off by the entry point before the API itself
  would have timed out. The one observed search took **15.23 s**, well inside the
  timeout, so this gap is documented but was not exercised by that observation.
- **CPU-only.** Inference runs on CPU. Reranking time scales with the number of
  candidates; there is no GPU acceleration.
- **Scores are not comparable across model versions.** `relevance_score` and
  `distance` are meaningful only within a single response; a model change
  silently changes what the numbers mean.
- **The corpus is synthetic.** The documents currently deployed were generated
  for testing. No result should be read as a statement about real-world
  documentation quality.
- **`POST /documents` is the only writing route.** There is no other route that
  mutates stored data.
- **No bulk ingestion endpoint.** Documents are ingested one per request.
- **No pagination.** `/search` returns at most `top_k` results; there is no
  "next page".
- **No delete endpoint.** A stored document cannot be removed through the API.
- **No search across multiple collections.** Each `/search` targets exactly one
  collection.

---

## 8. How to report bugs, failed requests or unexpected results

When you report a problem, include the following so it can be diagnosed without
a round trip:

1. **The exact command you ran** — the full `curl` (or equivalent) including the
   method, the URL and the body.
2. **The UTC time** of the request, as precisely as you can.
3. **The full HTTP status line and the full response body**, verbatim.
4. **The base URL you used**, exactly as you typed it.

Two things to be aware of when reporting:

- **A request that hangs or fails at the connection level, with no HTTP status
  or body, is almost always the source-address allow-list (§2), not an API
  fault.** Say so in your report if that is what you saw; it routes the problem
  correctly.
- **The network entry point's access logs are OFF.** There is no server-side
  access log to fall back on. **Your own captured output is therefore the primary
  evidence** — please keep it and attach it to the report rather than
  paraphrasing it.

Report to: the project owner, through the existing private communication channel.

---

## 9. Scope note: this is an API-client document

This document is for **API clients**. It covers the HTTP surface: the routes,
the request and response shapes, the status codes, how authentication works
(there is no application-level authentication; access is restricted by a
network-level source-address allow-list), and how to verify a search result.

It deliberately does **not** cover **infrastructure administration**. Deployment,
the cloud topology, the database, the inference workers, scaling, operations,
rollback, teardown and credential management are all **out of scope** here and
are documented elsewhere for the operators who need them. As a client you do not
administer any of it; you call the base URL in §2 and read the responses.
