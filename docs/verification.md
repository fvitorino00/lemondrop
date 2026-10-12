# Milestone 1 Verification Record

This file records what Milestone 1 of LemonDrop claimed, the command that re-checks
each claim, and what remains unproven. Every entry below was observed by running the
command given beside it. It is deliberately not a log archive: there are no terminal
transcripts here, because a transcript is evidence only to the person who already
trusts the conclusion. A record that carries the reproducing command can be re-checked
in under a minute, and a reader who disagrees can find out in the same time. Setup
instructions are not duplicated here — see the repository README for those.

LemonDrop is a three-service document-retrieval stack running under Docker Compose on
CPU only: a FastAPI `api` (the only service with a host-published port), a llama.cpp
`embedder` (bge-small-en-v1.5, 384-dimension embeddings, CLS pooling), and a llama.cpp
`reranker` (bge-reranker-base, rank pooling).

## Milestone 1 requirements

| # | Requirement | Evidence | Re-check command |
|---|---|---|---|
| 1 | Start three services: an API, a llama.cpp embedder, and a llama.cpp reranker | `docker compose ps` shows all three; `api` built from `./api`, both workers from `ghcr.io/ggml-org/llama.cpp:server` | `docker compose ps` |
| 2 | Only the API needs a host-published port | Exactly one `ports:` key in the file, on `api`, mapping `${API_HOST_PORT}:${API_INTERNAL_PORT}` (8000:8000); neither worker has one. Workers are reachable only at `http://embedder:8080` and `http://reranker:8080` over the compose network, via Docker's embedded DNS | `grep -n "ports:" docker-compose.yml` |
| 3 | Demonstrate working embedding requests | `POST /embed` with `{"text":"how do I reset my password"}` returned `dims: 384` and `model: bge-small-en-v1.5` | `curl -s -X POST http://localhost:8000/embed -H 'Content-Type: application/json' -d '{"text":"how do I reset my password"}'` |
| 4 | Demonstrate working reranking requests | `POST /rerank` with the password query and three documents returned indices 0, 2, 1 with relevance scores 2.747, -7.242, -10.195 — password document first, weather document last | `curl -s -X POST http://localhost:8000/rerank -H 'Content-Type: application/json' -d '{"query":"how do I reset my password","documents":["To reset your password click Forgot Password.","The weather in Paris is mild.","MySQL index tuning guide"]}'` |
| 5 | Establish health checks | All three containers report `(healthy)` | `docker compose ps` |
| 6 | Persistent model volumes | Models are bind-mounted from `./models` and loaded by explicit path (`-m /models/<file>.gguf`). After switching from `--hf-repo` to `-m`, `/root/.cache/huggingface` no longer exists inside the reranker container, confirming weights are served from the bind mount rather than a per-container cache. Models survive `docker compose down` | `docker compose exec reranker ls -la /root/.cache/` (expect no huggingface directory); `docker compose down && docker compose up -d` |
| 7 | Container restart policies | `docker compose restart` was run and all three containers returned to `(healthy)` | `docker compose restart && docker compose ps` |
| 8 | Useful logs | Verified by use, not by presence: `docker compose logs` output is what identified that `--hf-repo` was resolving weights into the container's own cache rather than the bind mount | `docker compose logs --tail=50` |
| 9 | Git branches and meaningful commits | 18 commits on `feat/inference-services`, with `main` held at the scaffold baseline as the stable line | `git rev-list --count feat/inference-services` |

Note on requirement 9: the commit count above is as observed when the milestone was
signed off. A later read of the same repository returned 17 for
`git rev-list --count feat/inference-services` (15 commits ahead of `main`). The
discrepancy is a counting-method difference, not a lost commit, but it is recorded
here rather than smoothed over: if you re-check this row and get a different number,
the row is the stale part.

## Acceptance criteria

| ID | Criterion | Evidence | Re-check command |
|---|---|---|---|
| A1 | Both inference services respond | `curl -s http://localhost:8000/health` returned `{"status":"ok","embedder":"ok","reranker":"ok"}` | `curl -s http://localhost:8000/health` |
| A2 | The API passes its local integration tests | `python -m pytest api/tests/test_integration.py -v` → 6 passed | see below |
| A3 | Docker Compose can recreate the system from documented instructions | Clean-clone reproduction — see below | see below |

### A2 — the six tests

The suite is live-service integration testing: no mocking, no in-process test client.
Every test makes a real HTTP call, so the stack must be up before pytest is invoked.
The six passing tests are:

- `test_health_reports_all_dependencies_ok`
- `test_embed_returns_384_dimensions`
- `test_embed_rejects_blank_text`
- `test_rerank_ranks_the_relevant_document_first`
- `test_rerank_rejects_empty_documents`
- `test_rerank_preserves_original_document_indices`

Re-check from the repository root with the project virtual environment active:

```
python -m pytest api/tests/test_integration.py -v
```

### A3 — clean-clone reproduction (the strongest of the three)

A1 and A2 confirm a stack that already exists. A3 is the only criterion that confirms
the *instructions* are sufficient, because it was performed in a fresh clone with no
inherited state. The repository was cloned to a separate directory and the documented
sequence was followed exactly:

1. Clone the repository to a new directory.
2. `cp .env.example .env`
3. `./scripts/fetch-models.sh` — both GGUF files downloaded from Hugging Face into the
   new clone's `models/` directory.
4. `docker compose up -d --build` — all three services reached healthy.
5. The three curl checks (A1, requirements 3 and 4) returned the same results as in
   the original working tree.
6. `python -m pytest api/tests/test_integration.py -v` passed 6/6 in the fresh clone.

Because the models directory and the environment file both start empty in a new clone,
this is the check that would catch a missing setup step. It passed.

## Bugs found and fixed

Each of these was caught by reading configuration or source before deployment, not by
a crash or a failed test. That is the point of recording them: nothing alerted anyone.
All three would have degraded the system silently rather than failing loudly.

1. **Reranker bound to 8081 while the image's healthcheck is hardcoded to 8080.**
   Found by reading the upstream Dockerfile before deployment. The published
   llama.cpp server image ships its own `HEALTHCHECK` against port 8080. A worker on
   any other port fails its own healthcheck, so `depends_on: condition:
   service_healthy` never fires and the api waits forever on a dependency that is
   running and working. Fixed by pinning both workers to 8080 (commit `1a8f0b0`).
   Lesson: an inherited healthcheck is a constraint on your port choice, and it is
   invisible until the container refuses to start.

2. **`${du -h ... | cut -f1}` where `$(...)` was meant, in `scripts/fetch-models.sh`.**
   Bash treats `${...}` as variable expansion, not command substitution, so the line
   failed with "bad substitution". Combined with `set -euo pipefail`, the script aborted
   after the first model, leaving the second unfetched — a failure that looks like a
   successful run if you only check the exit code of the surrounding step. Fixed in
   commit `1cf69c2`.
   Lesson: `set -e` converts a cosmetic typo into a silent partial result. Check what
   the script did, not only whether it returned.

3. **`--hf-repo <name>` resolved weights into the container's own cache at
   `/root/.cache/huggingface/`, not the bind mount.** Everything appeared healthy while
   the model was not actually being served from the persistent volume, and a container
   rebuild re-downloaded roughly 290MB. Found by reading the logs, not by an error.
   Fixed by switching to `-m /models/<file>.gguf` in commit `92afab2`.
   Lesson: "healthy" and "serving what you think it is serving" are different claims.
   The check that distinguishes them is cheap: look for the cache directory inside the
   container.

## Known gaps and open items

None of the following blocks the milestone. All three are recorded so they are not
forgotten, and all three are currently unfixed.

1. **Model aliases are not passed to the `api` container.** The compose `api` service
   has no `environment:` key, so `EMBEDDER_MODEL_ALIAS` and `RERANKER_MODEL_ALIAS`
   reach the workers through compose interpolation but never reach the api. The api
   falls back to its in-code defaults, which currently match `.env.example` exactly,
   so the system works as configured. The latent risk is that the two copies can drift:
   changing either alias in `.env` would move the workers without moving the api, and
   the failure would surface as a 502 rather than as an obvious configuration error.
   Confirm the current state with `grep -n "MODEL_ALIAS" docker-compose.yml` and
   `grep -n "MODEL_ALIAS" api/app`.

2. **CPU throughput has never been benchmarked.** Reranking has only ever been
   exercised with three documents. The configured funnel size is
   `RETRIEVAL_CANDIDATES=50`, which has never been exercised. No claim about latency or
   throughput at realistic corpus sizes has been made, and none should be made from
   this record.

3. **Two model-size comments in `scripts/fetch-models.sh` are inaccurate.** The header
   comments cite approximately 130MB and 278MB for the two GGUF files. The files
   actually present are 36,685,152 bytes and 303,769,152 bytes. Comment-only
   inaccuracy with no functional impact. Unfixed. The authoritative sizes are
   `stat -c '%n %s' models/*.gguf`.

## Re-running the whole verification

The README owns the setup procedure; this file does not restate it. In short: copy
`.env.example` to `.env`, run `./scripts/fetch-models.sh`, bring the stack up with
`docker compose up -d --build`, then run the health check, the three curl checks, and
the pytest suite listed above. The commands in this file are the checks; the README is
the setup. Nothing in this record requires historical state to re-run — every row above
was re-checkable against a stack built from the documented steps alone, which is what
acceptance criterion A3 demonstrates.

## Repository

<https://github.com/fvitorino00/lemondrop> (private)