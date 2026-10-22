# lemondrop

A two-stage document-retrieval stack, running on CPU under Docker Compose.
Two `llama.cpp` workers do the inference — one embeds text into 384-dimension
vectors, the other scores query/document pairs — and a small FastAPI service
stands in front of them as the only reachable endpoint. This milestone delivers
the HTTP surface that calls them, and Milestone 3 added the database, the
ingestion and the retrieval on top of them: documents are ingested into a
PostgreSQL instance with pgvector, and `/search` retrieves and reranks against
it. The verified M3 record — what was checked, on what, and what the result does
*not* establish — is `docs/verification-milestone-3.md`, with §12 as the
authority.

## Contents

- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Verifying](#verifying)
- [API routes](#api-routes)
- [Configuration](#configuration)
- [Design notes](#design-notes)
- [Troubleshooting](#troubleshooting)
- [Project status](#project-status)

## Architecture

This section describes the **local** Compose stack. The **deployed AWS**
topology — the VPC, subnets, the load balancer, the security-group chain and the
request flow — is in `docs/architecture.md`.

Four services are defined in `docker-compose.yml`: three that run by default,
and one development database behind an optional profile.

1. **`embedder`** — `llama.cpp` serving `bge-small-en-v1.5` (Q8_0 GGUF).
   Produces 384-dimension embeddings with CLS pooling. Endpoint `/v1/embeddings`.
   Image `ghcr.io/ggml-org/llama.cpp:server`.
2. **`reranker`** — `llama.cpp` serving `bge-reranker-base` (Q8_0 GGUF).
   Cross-encoder relevance scoring with rank pooling. Endpoint `/v1/rerank`.
   Same image.
3. **`api`** — FastAPI orchestrator, pulled as a digest-pinned GHCR image
   rather than built from `./api`. `docker-compose.yml` has no `build:` key for
   `api`, so `docker compose up --build` no longer builds this service. It
   serves every route in [API routes](#api-routes) — `GET /health`,
   `GET /health/live`, `GET /health/ready`, `POST /embed`, `POST /rerank`,
   `POST /documents` and `POST /search` — and it is the only service with a
   published port.
4. **`postgres`** — PostgreSQL 16 with pgvector, image `pgvector/pgvector:pg16`.
   Holds the `documents` table, whose `embedding` column is `vector(384)`.
   **Development only:** it sits behind the optional `devdb` profile and is not
   started by a plain `docker compose up`. See
   [Two database deployments](#two-database-deployments) below.

```
                        host
                          │
                  :8000   │   the only published port
                          ▼
                  ┌───────────────┐
                  │      api      │   FastAPI, digest-pinned GHCR image
                  └──┬────────┬───┘
                     │        │
       ┌─────────────┴┐       └────────────┴
       ▼              ▼                    ▼
 ┌───────────┐  ┌───────────┐  ┌───────────────────────┐
 │ embedder  │  │ reranker  │  │ postgres  pgvector    │
 │ :8080     │  │ :8080     │  │ profile: devdb         │
 │ llama.cpp │  │ llama.cpp │  │ volume: pgdata        │
 └───────────┘  └───────────┘  └───────────┬───────────┘
       ▲              ▲                    │
       └──────┬───────┘                    │
          ./models:/models                 ▼  psql on this host only
```

What the arrows in that diagram are, in words, since a picture can be read
loosely:

- **`api` → `embedder`, `api` → `reranker`** — plain HTTP over the compose
  network, to `http://embedder:8080` and `http://reranker:8080`. By service
  name, resolved by Docker's embedded DNS. No published port is involved.
- **`api` → `postgres`** — the `postgresql+asyncpg` DSN in `DATABASE_URL`, over
  the compose network, to `postgres:5432`. That service name resolves to the
  devdb container locally; on AWS the same variable is empty and the DSN comes
  from the resolver instead.
- **`./models:/models`** — a bind mount onto both workers, not a connection.
  `./models:/models` is how the two workers get their weights.
- **`postgres` → `127.0.0.1:5432`** — a published port bound to loopback, and
  the only reason it exists is so `psql` on the workstation can attach.

Port topology. `docker-compose.yml` contains two `ports:` keys: one on `api`,
and one on `postgres` bound to loopback.

| Service    | Reachable from the host at   |
|------------|------------------------------|
| `api`      | `localhost:8000` (`${API_HOST_PORT}:${API_INTERNAL_PORT}`) |
| `embedder` | not published — `http://embedder:8080` only, inside the compose network |
| `reranker` | not published — `http://reranker:8080` only, inside the compose network |
| `postgres` | `127.0.0.1:${DEV_DB_HOST_PORT:-5432}` — loopback only, and only when started with `--profile devdb`. Nothing off this host can reach it. |

That the workers have no published port is why `api` is the only reachable
surface, not an oversight: `api` reaches them by service name over the compose
network, through Docker's embedded DNS, and no publishing is involved on that
path. Both workers listen on 8080 inside their own network namespaces — separate
containers, separate namespaces, so the two sockets do not collide. What
distinguishes the services is the name, not the port.

`api` depends on both workers with `condition: service_healthy`, so it starts
only once each worker has passed its healthcheck. `llama.cpp` answers `/health`
with 503 while it is still reading the GGUF off disk, so a plain `depends_on`
would start the API against two unready dependencies. There is deliberately **no
`depends_on` on `postgres`**: it is profile-gated and does not exist on the
production host, where `scripts/boot.sh` runs a bare `docker compose up -d`, so
declaring it there would fail every compose call on a database that host is not
running.

### Two database deployments

These are two different things, and the difference matters when you are reading
this to work out how a running system found its database.

- **Local Compose PostgreSQL** — the `postgres` service, behind the optional
  `devdb` profile. A development convenience, not the default: start it
  explicitly with `docker compose --profile devdb up -d postgres`. The `api`
  container's DSN comes from `DEV_DATABASE_URL` in `.env`, which names the
  `postgres` service on the compose network. Until it is started, the API serves
  and reports degraded on `/health/ready`, which is the honest answer.
- **AWS RDS PostgreSQL** — the deployed target. Reached through the AWS
  credential resolver, not an environment file: `DB_DSN_SOURCE=aws` selects it,
  `AWS_REGION` supplies the region (there is deliberately no default, because
  the AWS SDK does not discover one), host and port come from SSM Parameter
  Store and the credential from Secrets Manager, both through the EC2 instance
  role. The DSN exists only in process memory, for the life of the process.

The selection is explicit and never inferred. `api/app/config.py`'s
`resolve_database_url` returns `DATABASE_URL` whenever it is set and non-blank,
and only otherwise consults `DB_DSN_SOURCE` — so a local `DEV_DATABASE_URL`
short-circuits the AWS path entirely, and it is a production host with an empty
`DATABASE_URL` and `DB_DSN_SOURCE=aws` that reaches RDS. There is no
autodetect: a host that forgot the variable would otherwise silently connect to
production from a laptop.

## Prerequisites

- Docker Desktop on Windows, with **Settings → Resources → WSL Integration**
  enabled for your distribution. Verification: `/mnt/wsl/docker-desktop` exists
  in the WSL filesystem.
- Docker Compose v2 or newer — the `docker compose` subcommand form, not
  `docker-compose`. The stack was built and verified against v5.5.1.
- A checkout of this repository on the WSL filesystem, on native ext4. Model
  weights are loaded from disk on every cold start, and loading from `/mnt/c`
  (9p) is slow enough to matter. Read the path off your shell prompt: one
  beginning `/mnt/` is the 9p-mounted Windows drive, one under `/home/` is
  native ext4.

## Quick start

From a fresh clone:

```
cd <repo>
cp .env.example .env
./scripts/fetch-models.sh
docker compose up -d --build
docker compose ps
```

Step by step:

- `cp .env.example .env` — Compose interpolates `${VAR}` from this file. If it
  is absent, Compose substitutes empty strings and warns.
- `./scripts/fetch-models.sh` — downloads the two GGUF files into `./models`.
  Run this **before** the first `docker compose up`. Re-running is safe: a file
  that is already present and non-empty is skipped. The script is idempotent.
- `docker compose up -d --build` — starts the stack in the background. The
  `api` service is pulled as a digest-pinned GHCR image (`docker-compose.yml`
  has no `build:` key for `api`), so `--build` does not build the API; it is a
  no-op for that service.
- `docker compose ps` — all three services reach `(healthy)`.

If a service does not reach `(healthy)`, read its logs rather than restarting —
see [Troubleshooting](#troubleshooting).

Expect the first start to be slow. The models take roughly 30–60 seconds to load
from disk on CPU. The API reports `health: starting` until both of its
dependencies have passed, which is expected behaviour, not a fault.

## Verifying

Three checks, in increasing order of what they prove.

**1. Readiness.** Confirms the API is up and both workers are reachable:

```
curl -s http://localhost:8000/health
```

```
{"status":"ok","embedder":"ok","reranker":"ok"}
```

**2. Embedding.** Confirms the embedder is loaded and returning vectors. This
command prints only the dimension count and the model alias, not the vector
itself, so the output stays readable:

```
curl -s http://localhost:8000/embed \
  -H "Content-Type: application/json" \
  -d '{"text":"how do I reset my password"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('dims:', d['dimensions']); print('model:', d['model'])"
```

```
dims: 384
model: bge-small-en-v1.5
```

The numbers above show the response shape and magnitude; they are illustrative
and are not reproducible guarantees.

**3. Reranking.** Confirms the reranker is loaded and ordering correctly:

```
curl -s http://localhost:8000/rerank \
  -H "Content-Type: application/json" \
  -d '{"query":"how do I reset my password","documents":["To reset your password click Forgot Password.","The weather in Paris is mild.","MySQL index tuning guide"]}'
```

```
{"results":[{"index":0,"relevance_score":2.747},{"index":2,"relevance_score":-7.242},{"index":1,"relevance_score":-10.195}],"model":"bge-reranker-base"}
```

The relevance scores above show the response shape and magnitude; they are
illustrative and are not reproducible guarantees.

Note the `index` values: **0, 2, 1 — not 0, 1, 2.** This is correct. `index` is
the position the document occupied in the array you sent, not its rank in the
response. The results are sorted best-first, so the best match (the password
document, sent at index 0) is first, and the two irrelevant documents follow in
relevance order. Join each `index` back onto your own array to recover which of
your documents survived; do not read it as a rank.

**4. The integration suite.** The tests make real HTTP calls, so the stack must
be running first. From the repository root:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r api/requirements-dev.txt
python -m pytest api/tests/test_integration.py -v
```

Six tests, all passing against the running stack. These are six of the live-stack
(T3) tests — the six in `api/tests/test_integration.py`, a subset of the 31-test
T3 tier. They require the full stack (API, both llama.cpp workers and the dev
database) to be running, and T3 is NOT executed by CI (CI runs T1+T2 =
177 of 208 tracked tests; the 31 T3 tests are deliberately not run in this
workflow). Test names and count only — pytest's own column layout and timings
are not shown:

```
test_health_reports_all_dependencies_ok          PASSED
test_embed_returns_384_dimensions                PASSED
test_embed_rejects_blank_text                    PASSED
test_rerank_ranks_the_relevant_document_first    PASSED
test_rerank_rejects_empty_documents              PASSED
test_rerank_preserves_original_document_indices  PASSED

6 passed
```

On Ubuntu and Debian, `python3 -m venv .venv` can fail with
`ensurepip is not available`. Fix it with:

```
sudo apt install python3-venv
```

**Shutting down.**

```
docker compose down
docker compose down -v
```

`docker compose down` removes the containers and networks. `docker compose
down -v` also removes named volumes. In this project the models are
bind-mounted from `./models`, not stored in a named volume, so **`down -v` does
not delete the downloaded models.** That is deliberate: the weights survive a
full teardown and are still there after the next `docker compose up`.

## API routes

All seven routes below are the complete set of **application** routes served by
the `api` service on `localhost:8000`. `api/app/main.py` registers no others
beyond those seven; FastAPI additionally serves the standard documentation
endpoints `/openapi.json`, `/docs` and `/redoc`. Three came
from the retrieval-free milestone (`/health`, `/embed`, `/rerank`); the other
four arrived with the database phase. `POST /documents` and `POST /search` are
the two that use the store; their behaviour and cloud evidence are recorded in
`docs/verification-milestone-3.md`.

### `GET /health`

Reports whether the API can do its job, by probing both workers. This is a
readiness check, not a liveness check: it returns 200 only when both
dependencies answered, and 503 when either did not.

Response fields are strings rather than booleans, so a failure reports why:

```json
{"status":"ok","embedder":"ok","reranker":"ok"}
```

On failure, `status` is `degraded`, and the failing dependency carries a short
description instead of `ok` — for example `unhealthy: HTTP 503`,
`unreachable: ConnectError`, or `timeout after 5.0s`. The HTTP status code is
503 at the same time.

### `GET /health/live`

Answers one question: **is this process so broken that restarting it is the only
way forward?** It checks nothing at all and always returns 200:

```json
{"status": "ok"}
```

That is the contract, not an oversight. A dependency cannot break the process,
so a liveness probe that consulted the embedder, the reranker or the database
would report 503 during a transient blip and the orchestrator would kill a
healthy container — turning a five-second blip into a restart loop.

### `GET /health/ready`

Answers the opposite question: **can this process serve a request right now?**
It probes both workers and the database, and returns 503 when any of the three
is unavailable — the correct response, because a load balancer takes the instance
out of rotation and puts it back when it recovers. Both can therefore be true at
once: with the database down, `/health/live` returns 200 and `/health/ready`
returns 503.

```json
{"status": "ok", "embedder": "ok", "reranker": "ok", "database": "ok"}
```

Same shape and same 200/503 semantics as `GET /health`, plus the `database`
verdict — `"ok"`, or a short description of why it could not be reached, such as
`timeout after 2.0s`. That field is credential-free by construction. `GET
/health` is unchanged and remains the workers-only check that compose,
`scripts/boot.sh` and the ALB depend on.

### `POST /embed`

Turns one piece of text into one vector.

Request:

```json
{"text": "how do I reset my password"}
```

`text` is required and must not be blank. Whitespace-only input is stripped and
then rejected, so `"   "` returns 422 rather than forwarding an empty string to
the worker.

Response:

```json
{
  "embedding": [ ... 384 floats ... ],
  "dimensions": 384,
  "model": "bge-small-en-v1.5"
}
```

`dimensions` is the width of the vector actually returned. It is reported
alongside the vector so that a caller can attribute a stored vector to the model
that produced it. `model` echoes the alias.

### `POST /rerank`

Scores every supplied document against the query and returns them best-first.

Request:

```json
{
  "query": "how do I reset my password",
  "documents": [
    "To reset your password click Forgot Password.",
    "The weather in Paris is mild.",
    "MySQL index tuning guide"
  ]
}
```

`query` must not be blank. `documents` must contain at least one non-empty
string; an empty list returns 422. `top_n` is optional — when omitted it is not
sent upstream at all, and the worker applies its own default.

Response:

```json
{
  "results": [
    {"index": 0, "relevance_score": 2.747},
    {"index": 2, "relevance_score": -7.242},
    {"index": 1, "relevance_score": -10.195}
  ],
  "model": "bge-reranker-base"
}
```

`index` is the document's position in the array you sent, **not** its rank —
see [Verifying](#verifying) above. `relevance_score` is a cross-encoder logit;
higher is more relevant, and values are comparable within one response but not
across models or model versions.

This route does not filter and does not truncate. Deciding which candidates are
worth scoring is retrieval's job, and that is `POST /search` below.

### `POST /documents`

Embeds one document and writes it to the `documents` table, returning **201**.
This is the first route that mutates anything.

Request — `document_id`, `collection` and `content` are required and must not be
blank; `metadata` is optional and defaults to `{}`:

```json
{
  "document_id": "runbook-reset-password",
  "collection": "runbooks",
  "content": "To reset your password click Forgot Password.",
  "metadata": {"source": "runbook-v3"}
}
```

Re-posting a `document_id` that already exists **updates** that row rather than
creating a second one — content, metadata, embedding and collection — so
ingestion is idempotent by id and there is no 409. Because `id` is the global
primary key, re-posting under a different `collection` moves the document rather
than copying it.

The embedding is never accepted from the caller: the route embeds `content`
itself, through the `POST /embed` handler, and therefore inherits that route's
behaviour — including the fact that the text goes to the embedder **bare**,
with no query prefix. See [Design notes](#design-notes).

The response reports what the database now holds, not what was asked for:
`document_id` and `collection` as stored, `outcome` as `"inserted"` or
`"updated"`, and `dimensions` as the width PostgreSQL accepted — read back from
the stored vector, not the width the embedder claimed. If the model and the
schema disagree about that width, the request fails with 502 naming both
numbers, rather than producing a write that cannot be retrieved later.

### `POST /search`

Finds the documents most relevant to a query within one collection, and returns
the top few. This is the route that composes both workers and reads the store.

Request — `collection` and `query` are required and must not be blank;
`candidates` and `top_k` are optional:

```json
{
  "collection": "runbooks",
  "query": "how do I reset my password",
  "candidates": 10,
  "top_k": 5
}
```

When `candidates` or `top_k` is omitted, the configured funnel sizes in
[Configuration](#configuration) apply. A caller may ask for **fewer** and never
for more: both numbers are clamped to the configured maximum, and `top_k` is
additionally capped at the resolved candidate count, because the reranker can
only re-order documents stage 1 actually returned.

The stages run in a fixed order: embed the query, filter by collection in SQL
and take the nearest candidates by pgvector distance, then rerank those
candidates and return the best `top_k`. If stage 1 returns nothing, the route
returns 200 with an empty result and **does not call the reranker** at all.

This is the only route that applies `QUERY_PREFIX`, and it applies it to the
query and to nothing else. Stage-1 candidates are not re-embedded — their
vectors were computed at ingestion and are read from the column — so the stored
document vectors stay exactly as they were written.

The response carries `results`, `collection` echoed back from what was asked
for, `candidates_considered` (how many candidates stage 1 actually returned —
the number that distinguishes an empty collection from a funnel that found
nothing relevant), and `model`, the reranker alias. Each entry in `results`
carries `document_id`, `collection`, `content`, `metadata`, the stage-2
`relevance_score`, and the stage-1 `distance`.

Searching a collection that holds no documents is a **200 with an empty result
set**, not a 404. `candidates_considered: 0` is how a caller distinguishes
"nothing was searched" from "nothing matched".

### Upstream failures

`/embed` and `/rerank` share their failure handling:

- **504** — the worker timed out after 120s. Usually a large document list on a
  CPU-only machine.
- **502** — the worker was unreachable, answered non-2xx, or returned a body
  that was not JSON.

The full upstream detail goes to the server log. The client receives a short
sentence, not a traceback.

`POST /documents` and `POST /search` inherit those same 504 and 502 behaviours
by calling the two proxy handlers rather than reimplementing them. A **503** on
either route means the database is unavailable, which is the same claim
`/health/ready` makes with the same status code.

Edge guard on worker-bound input (422):

Worker-bound text fields — `text` on `POST /embed` and each document entry on
`POST /rerank` — are capped at **2048 characters**. `query` on `POST /search` is
capped at **1991 characters** by default, because `/search` prepends the bge
query prefix before forwarding the combined string to the worker. The smaller
query allowance is exact arithmetic on the fixed 57-character prefix, not a token
estimate. A longer value is refused at the API edge with **422** naming the field
and the effective limit, instead of being forwarded to a worker that would answer
with a permanent 502.

The 2048-character figure is a CHARACTER proxy for the worker's 512-token
ceiling and cannot be exact: tokenisation is not a function of character count
alone, so pathological low-density input (long unbroken character runs) can
still exceed the worker's token limit below 2048 characters. That input is
passed through and produces a **502** — permanent, not retryable (retrying
fails the same way every time).

`POST /rerank`'s 512-token ceiling applies to the **(query, passage) PAIR**, not
to either field in isolation. Two values that are each individually valid can
still be refused by the worker because their combined length exceeds the
ceiling. That is a known residual, stated here rather than concealed behind the
per-field limit.

502: transient vs permanent:

A **502** is **either**:

- **Transient (retryable):** the worker is unreachable, answered a non-2xx
  status, or returned a body that was not JSON. Retry, optionally with backoff.
- **Permanent (not retryable):** the input the API forwarded is one the worker
  refuses — for example pathological low-density text below the 2048-character
  edge limit that still exceeds the worker's 512-token ceiling. Do not retry;
  it will fail the same way every time.

The client-facing detail is a short sentence naming the worker and the HTTP
status, e.g. `{"detail":"embedder returned HTTP 500"}`. The full upstream worker
detail is logged server-side only and is **not** echoed into the client-facing
response.

## Configuration

All values come from `.env`, created by copying `.env.example`.

| Key | Default | Consumed by | Meaning |
|---|---|---|---|
| `API_HOST_PORT` | `8000` | compose | Host-side port for `api`. The only published port reachable from off-host; `postgres` publishes one too, but bound to loopback. |
| `API_INTERNAL_PORT` | `8000` | compose | Port `api` listens on inside the network. Must stay `8000`: `api/Dockerfile` binds it as a literal in an exec-form `CMD`, where no shell expands anything. |
| `EMBEDDER_INTERNAL_PORT` | `8080` | compose | Port the embedder listens on. Must stay `8080` — see [Design notes](#design-notes). |
| `RERANKER_INTERNAL_PORT` | `8080` | compose | Same constraint as the embedder. |
| `EMBEDDER_MODEL_ALIAS` | `bge-small-en-v1.5` | compose, `api` | The name the worker registers the model under (`--alias`), and the name the API requests it by. |
| `RERANKER_MODEL_ALIAS` | `bge-reranker-base` | compose, `api` | Same, for the reranker. |
| `EMBEDDING_DIM` | `384` | compose, `api` | The width the embedder produces, cross-checked against the `vector(384)` column that migration 0001 created. Read by `api/app/config.py` (`get_settings`); a value that disagrees with the schema is rejected at construction, not at the INSERT. |
| `QUERY_PREFIX` | `Represent this sentence for searching relevant passages: ` | `api` | bge-small-en-v1.5's instruction string, prepended to the QUERY by `POST /search` and to nothing else — `/embed` and `POST /documents` forward text bare. Read by `api/app/config.py`. Not a per-request setting, and `SearchRequest` has no field through which a caller could change it. |
| `RETRIEVAL_CANDIDATES` | `10` | `api` | Stage-1 funnel size: how many candidates the vector store returns before reranking. Read by `api/app/config.py` (`funnel_from_environment`) and clamped by `Funnel.clamped` — a caller may ask for fewer, never more. Sized at 10 rather than the 50 this table previously documented, because the reranker is a CPU cross-encoder that scores every candidate; see the constant's comment for the reasoning. |
| `RERANK_TOP_K` | `5` | `api` | Stage-2 result count: how many reranked documents the caller receives. Read by `api/app/config.py`, and validated against `RETRIEVAL_CANDIDATES` — a `top_k` above the candidate count is refused at startup rather than silently returning a shorter list. |

All four of `EMBEDDING_DIM`, `QUERY_PREFIX`, `RETRIEVAL_CANDIDATES` and
`RERANK_TOP_K` are read by the code. `docker-compose.yml` passes only
`EMBEDDING_DIM` of the four into the `api` container — along with
`DATABASE_URL`, `DB_DSN_SOURCE` and `AWS_REGION`, which select the database and
are covered under [Two database deployments](#two-database-deployments) — so in
the default compose setup `QUERY_PREFIX`, `RETRIEVAL_CANDIDATES` and
`RERANK_TOP_K` resolve to the defaults in the table above regardless of what a
local `.env` says.

Three more variables are read by the code but are **not** in `.env.example`,
because the compose-network defaults are already correct and no override is
needed in normal use:

| Key | Default | Read by |
|---|---|---|
| `EMBEDDER_URL` | `http://embedder:8080` | `api/app/main.py` |
| `RERANKER_URL` | `http://reranker:8080` | `api/app/main.py` |
| `API_URL` | `http://localhost:8000` | `api/tests/test_db.py`, `test_documents.py`, `test_search.py`, `test_integration.py`; `scripts/load_corpus.py` |

`.env` is gitignored and must never be committed. `.env.example` is safe to
commit and contains no secrets.

## Design notes

### Models are loaded by path, not by repo name

Both workers start with `-m /models/<file>.gguf` rather than by naming a
HuggingFace repo with `--hf-repo`. The reason is that `--hf-repo` resolves
weights through the container's own cache at `/root/.cache/huggingface/`, which
is not the bind mount — so `./models:/models` was not actually serving the
model, and a container rebuild re-downloaded roughly 290MB. Loading by path
makes `/models` the single source of truth for the weights and makes
`scripts/fetch-models.sh` the single provisioning path.

The cost of that decision: `fetch-models.sh` must run before the first
`docker compose up`. Because the containers load by path, a model missing from
`/models` now fails loudly at startup instead of being silently re-downloaded
into a throwaway cache. That is the intended behaviour.

### Both workers are pinned to port 8080

The published `llama.cpp` image ships its own healthcheck hardcoded to port
8080:

```
HEALTHCHECK CMD curl -f http://localhost:8080/health
```

A service listening on any other port therefore fails its own healthcheck, and
`depends_on: condition: service_healthy` never fires — the API sits in
`health: starting` forever. This was a real bug during development. Both
inference services are pinned to 8080 for this reason, and the compose file
restates the probe with a literal 8080 so that our probe and the image's
inherited probe cannot drift apart.

If you change `EMBEDDER_INTERNAL_PORT` or `RERANKER_INTERNAL_PORT` in `.env`,
the healthcheck breaks.

### The query prefix is deliberately absent from `/embed`

`bge-small-en-v1.5` was trained with a fixed instruction prepended to **search
queries only**:

```
Represent this sentence for searching relevant passages: 
```

Documents must never carry it. Both are encoded into the same vector space, but
only document vectors are stored and retrieved, so prefixing a document moves
it off the manifold the other documents live on and makes it much harder to
match. The damage is silent and permanent: it is written into whatever database
holds the vector, and nothing in the response says it happened.

`POST /embed` therefore forwards `text` bare. This is a decision, not an
oversight and not a missing feature. It is also the right default for this
route: `/embed` does not know whether its text will be a query or a document,
and a document is the expensive one to get wrong.

**Do not add the prefix to `/embed`.** It belongs on a `/search` route, which
~~does not exist in this milestone. Until it does, the prefix appears in the code
only in comments.~~ **That was written before Milestone 3 and is no longer true.**
`POST /search` exists and is where the prefix is applied — `api/app/config.py`
reads it from `QUERY_PREFIX`, exactly as the table above describes.

## Troubleshooting

**1. `cp: cannot stat '.env.example': No such file or directory`**

You are in the wrong directory. Check that your shell prompt ends with the
repository path. Run the setup commands from the repository root, which is
where `docker-compose.yml`, `.env.example` and `scripts/` all live.

**2. Reranker healthcheck failing, or `api` stuck at `health: starting`**

Start by reading what the containers are actually doing. Recent output from
every service, or one service followed live:

```
docker compose logs --tail=50
docker compose logs -f embedder
docker compose logs --since 5m
docker compose logs -f reranker
```

`--since 5m` is the one to reach for when a container is exiting and restarting
repeatedly: the restart cycle is the signal, and the full log buries it.
Substitute `-f reranker` for `-f embedder` when the failure is on the reranker,
which is what this item is about.

A container sitting in `health: starting` for a long time is usually still
loading its model off disk; that progress appears in that worker's own logs, not
in the `api` logs. A worker that exits and restarts repeatedly is a different
problem from one that is merely slow, and the logs tell the two apart. The `api`
logs are the ones to read when a request returns 502 or 504, because the API
records the upstream detail server-side while the caller receives only a short
sentence — see [Upstream failures](#upstream-failures).

The `llama.cpp` image hardcodes its healthcheck to port 8080. A worker moved to
any other port can never pass it, so `depends_on: condition: service_healthy`
never fires. Both workers are pinned to 8080 in `.env` for this reason. Check
that `EMBEDDER_INTERNAL_PORT` and `RERANKER_INTERNAL_PORT` are still `8080`.

**3. `bad substitution` from `fetch-models.sh`**

A real bug, since fixed in commit `4a176c5`. In bash, `${var}` expands a
variable and `$(cmd)` runs a command. Writing `${du -h ... | cut -f1}`
expands as neither and fails. Command substitution is `$(...)`, not `${...}`.

**4. `python3 -m venv .venv` fails with `ensurepip is not available`**

Standard on Ubuntu and Debian, where the `python3-venv` package is not part of
the base install. Fix it with:

```
sudo apt install python3-venv
```

Then re-run the venv creation.

**5. Models re-downloading on every start, or a service healthy while not
actually using `./models`**

A symptom of the `--hf-repo` versus `-m` distinction above: weights resolved by
repo name land in the container's own cache at `/root/.cache/huggingface/`, not
in the bind mount. Verify that the containers are started with
`-m /models/<file>.gguf` and that `./models` holds both GGUF files.

**6. A model is missing at startup**

Expected, given the design. `scripts/fetch-models.sh` must run before the first
`docker compose up`, and before any later rebuild. Run it and start the stack
again. The script skips files that are already present and non-empty.

## Project status

Milestone 3 is closed. The verified record — what was checked on AWS, by whom,
and what the results do not establish — is `docs/verification-milestone-3.md`;
**§12 is the authority** and §12.5 is the acceptance table. What does **not**
exist yet, so nobody goes looking for it:

- **No authentication.** The API's published port — the only one reachable from
  off-host — is open to anything that can reach the host. On AWS the ALB restricts
  access by source CIDR, which is a network-level restriction and **not**
  authentication.
- **CPU-only.** GPU acceleration is possible — the development host has an
  RTX 5070 Ti with CUDA 13.4 — and was deliberately deferred.

What exists, verified on AWS against a live `t3.small` behind a public ALB and
against RDS: the database (**PostgreSQL with pgvector**, holding stored document
vectors), document **ingestion**, and **collection-scoped retrieval and
reranking** through `POST /search`, which applies the query prefix and the funnel
sizes documented in [Configuration](#configuration). All five M3 acceptance
criteria are verified in the cloud environment. Also verified there: `GET
/health/ready` HTTP 200, `POST /search` HTTP 200, the connection authenticating
as `lemondrop_app` rather than the RDS master, the EC2 instance role being
**denied** the RDS master secret, 10 of 10 adversarial isolation canaries passing
in both directions, and search surviving an API container restart. **The
evidence, and the boundaries of that evidence — a container restart rather than an
EC2 reboot, isolation at the response boundary, a single latency observation
rather than a distribution, and a synthetic corpus — are in
`docs/verification-milestone-3.md`, not restated here.** §12.4 there lists what is
still outstanding.
