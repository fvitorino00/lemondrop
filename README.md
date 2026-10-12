# lemondrop

A two-stage document-retrieval stack, running on CPU under Docker Compose.
Two `llama.cpp` workers do the inference — one embeds text into 384-dimension
vectors, the other scores query/document pairs — and a small FastAPI service
stands in front of them as the only reachable endpoint. This milestone delivers
the three services and the HTTP surface that calls them. There is no database,
no ingestion and no retrieval yet; the API forwards to the models and nothing
more.

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

Three services, defined in `docker-compose.yml`:

1. **`embedder`** — `llama.cpp` serving `bge-small-en-v1.5` (Q8_0 GGUF).
   Produces 384-dimension embeddings with CLS pooling. Endpoint `/v1/embeddings`.
   Image `ghcr.io/ggml-org/llama.cpp:server`.
2. **`reranker`** — `llama.cpp` serving `bge-reranker-base` (Q8_0 GGUF).
   Cross-encoder relevance scoring with rank pooling. Endpoint `/v1/rerank`.
   Same image.
3. **`api`** — FastAPI orchestrator, built from `./api` rather than pulled.
   Routes `GET /health`, `POST /embed`, `POST /rerank`. It is the only service
   with a published port.

```
                    host
                      │
              :8000   │   the only published port
                      ▼
             ┌────────────────┐
             │      api       │   FastAPI, built from ./api
             └───────┬────────┘
                     │  http://embedder:8080
                     │  http://reranker:8080
            ┌────────┴────────┐
            ▼                 ▼
     ┌────────────┐    ┌────────────┐
     │  embedder  │    │  reranker  │
     │  :8080     │    │  :8080     │
     └────────────┘    └────────────┘
            ▲                 ▲
            └────────┬────────┘
                 ./models:/models
```

Port topology. The compose file contains exactly one `ports:` key, and it is on
`api`:

| Service    | Reachable from the host at   |
|------------|------------------------------|
| `api`      | `localhost:8000`             |
| `embedder` | not published — `http://embedder:8080` only, inside the compose network |
| `reranker` | not published — `http://reranker:8080` only, inside the compose network |

Both workers listen on 8080 inside their own network namespaces. That is not a
conflict: separate containers have separate namespaces, so the two sockets are
different. What distinguishes the services is the name, not the port — Docker's
embedded DNS resolves `embedder` and `reranker` on the default network.

`api` depends on both workers with `condition: service_healthy`, so it starts
only once each worker has passed its healthcheck. `llama.cpp` answers `/health`
with 503 while it is still reading the GGUF off disk, so a plain `depends_on`
would start the API against two unready dependencies.

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
- `docker compose up -d --build` — starts the stack in the background, building
  the `api` image from `./api`.
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

**3. Reranking.** Confirms the reranker is loaded and ordering correctly:

```
curl -s http://localhost:8000/rerank \
  -H "Content-Type: application/json" \
  -d '{"query":"how do I reset my password","documents":["To reset your password click Forgot Password.","The weather in Paris is mild.","MySQL index tuning guide"]}'
```

```
{"results":[{"index":0,"relevance_score":2.747},{"index":2,"relevance_score":-7.242},{"index":1,"relevance_score":-10.195}],"model":"bge-reranker-base"}
```

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

Six tests, all passing against the running stack. Test names and count only —
pytest's own column layout and timings are not shown:

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

All three routes are served by the `api` service on `localhost:8000`.

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
worth scoring is retrieval's job, and that does not exist yet.

### Upstream failures

`/embed` and `/rerank` share their failure handling:

- **504** — the worker timed out after 120s. Usually a large document list on a
  CPU-only machine.
- **502** — the worker was unreachable, answered non-2xx, or returned a body
  that was not JSON.

The full upstream detail goes to the server log. The client receives a short
sentence, not a traceback.

## Configuration

All values come from `.env`, created by copying `.env.example`.

| Key | Default | Consumed by | Meaning |
|---|---|---|---|
| `API_HOST_PORT` | `8000` | compose | Host-side port for `api`. The only published port. |
| `API_INTERNAL_PORT` | `8000` | compose | Port `api` listens on inside the network. Must stay `8000`: `api/Dockerfile` binds it as a literal in an exec-form `CMD`, where no shell expands anything. |
| `EMBEDDER_INTERNAL_PORT` | `8080` | compose | Port the embedder listens on. Must stay `8080` — see [Design notes](#design-notes). |
| `RERANKER_INTERNAL_PORT` | `8080` | compose | Same constraint as the embedder. |
| `EMBEDDER_MODEL_ALIAS` | `bge-small-en-v1.5` | compose, `api` | The name the worker registers the model under (`--alias`), and the name the API requests it by. |
| `RERANKER_MODEL_ALIAS` | `bge-reranker-base` | compose, `api` | Same, for the reranker. |
| `EMBEDDING_DIM` | `384` | nothing yet | **Currently unused by the code.** Declared for sizing the future vector store index; reserved for a `/search` route that does not exist yet. |
| `QUERY_PREFIX` | `Represent this sentence for searching relevant passages: ` | nothing yet | **Currently unused by the code.** Reserved for the future `/search` route, which does not exist yet; `/embed` deliberately does not apply it. |
| `RETRIEVAL_CANDIDATES` | `50` | nothing yet | **Currently unused by the code.** Stage-1 funnel size, reserved for the future `/search` route. |
| `RERANK_TOP_K` | `5` | nothing yet | **Currently unused by the code.** Stage-2 result count, reserved for the future `/search` route. |

The four variables marked "unused" above are declared but no code reads them.
They are placeholders for a `/search` route that does not exist in this
milestone. Changing them has no effect on the running system today.

Three more variables are read by the code but are **not** in `.env.example`,
because the compose-network defaults are already correct and no override is
needed in normal use:

| Key | Default | Read by |
|---|---|---|
| `EMBEDDER_URL` | `http://embedder:8080` | `api/app/main.py` |
| `RERANKER_URL` | `http://reranker:8080` | `api/app/main.py` |
| `API_URL` | `http://localhost:8000` | `api/tests/test_integration.py` |

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
does not exist in this milestone. Until it does, the prefix appears in the code
only in comments.

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

A real bug, since fixed in commit `1cf69c2`. In bash, `${var}` expands a
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

This milestone delivers the three services and the HTTP surface that calls them.
What does **not** exist yet, so nobody goes looking for it:

- **No database.** No document ingestion, no storage of vectors, nothing to
  persist. The `api` service is stateless and mounts no volumes.
- **No `/search` endpoint.** The API forwards to the models; it does not
  retrieve or rank anything itself. The query prefix, the candidate count and
  the top-K value are declared in `.env` but unread, waiting for this route.
- **No authentication.** The one published port is open to anything that can
  reach the host.
- **CPU-only.** GPU acceleration is possible — the development host has an
  RTX 5070 Ti with CUDA 13.4 — and was deliberately deferred.

What works today, verified: start the stack from a clean checkout, get three
healthy containers, get a 384-dimension embedding out of `/embed`, get a
correctly ordered ranking out of `/rerank`, and pass all six integration tests
against the live stack.
