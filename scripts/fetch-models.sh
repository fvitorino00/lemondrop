#!/usr/bin/env bash
#
# fetch-models.sh — download the two GGUF weights lemondrop needs.
#
# ── WHY this script exists ────────────────────────────────────────────────────
# Both containers are started with `-m /models/<file>.gguf`, so they read the
# weights straight out of the bind-mounted /models directory by path. They used
# to be started with `--hf-repo <repo-name>`, which resolves weights through the
# container's own cache at /root/.cache/huggingface/ — not the bind mount — so
# ./models:/models was not actually serving the model, persistence across a
# rebuild was not guaranteed, and the weights existed twice on disk. Loading by
# path makes /models the single source of truth for the weights, which makes
# this script the only way weights reach disk: it has to run before the first
# `docker compose up`. Letting the image pull its own weights on first boot is
# convenient for a throwaway demo and wrong for this project, for two reasons:
#
#   1. PERSISTENCE. Docker's writable container layer is not a storage
#      guarantee. Anything the image downloaded at runtime is at the mercy of
#      container recreation, and a volume that gets `docker compose down -v`'d
#      takes the weights with it. Fetching once into ./models — a directory
#      bind-mounted into both containers — means the weights are plain files on
#      the native ext4 filesystem, surviving restarts, rebuilds and volume
#      teardown, and visible to ordinary tools like du and ls.
#   2. RE-DOWNLOAD COST. bge-small-en-v1.5 is ~130MB and bge-reranker-base is
#      ~278MB. Re-fetching them on every cold start is minutes of waiting and
#      bandwidth for bytes we already have.
#
# So: run this ONCE, before the first `docker compose up`. The weights are then
# present in ./models, the bind mount exposes them to both containers at /models,
# and startup is a memory load from disk rather than a network fetch. Because
# the containers load by path, a model missing from /models now fails loudly at
# startup instead of being silently re-downloaded into a throwaway cache.
#
# IDEMPOTENT BY DESIGN. Re-running is safe and cheap: a file that is already
# present and non-empty is skipped. Nothing under models/ is committed — .gitignore
# blocks *.gguf and models/*.
#
# SELF-CONTAINED BY DESIGN — it reads NOTHING from its caller. Every path and
# URL below is derived from this script's own location, so there is no variable
# for a parent to export and no `set -u` trapdoor if one is forgotten. It is
# invoked by the boot script as a separate `bash` process, which would not even
# inherit non-exported parent variables.
#
# Usage:  ./scripts/fetch-models.sh
#         (works from any directory; the project root is resolved from the
#          script's own location)

set -euo pipefail

# ── Dependency preflight ──────────────────────────────────────────────────────
# Every download below goes through `curl`, from PATH. On Amazon Linux 2023 that
# is the preinstalled `curl-minimal`, which is entirely sufficient for HTTPS and
# is deliberately NOT replaced: installing full `curl` alongside it is a package
# conflict that dnf refuses, and a boot that dies on that refusal never reaches
# this script at all.
#
# This check exists for the other direction — so that a host genuinely missing
# curl produces one readable line naming the fix, instead of a "curl: command
# not found" buried in a download failure.
if ! command -v curl >/dev/null 2>&1; then
  echo "FATAL: curl is not on PATH, so the weights cannot be downloaded." >&2
  echo "       On Amazon Linux 2023, install the 'curl-minimal' package." >&2
  echo "       Do NOT install full 'curl' — it conflicts with curl-minimal." >&2
  exit 1
fi

# ── Resolve paths relative to this script, not to $PWD ───────────────────────
# This script lives at <project-root>/scripts/fetch-models.sh. Resolving from
# the script location means `./scripts/fetch-models.sh`, `bash /abs/path/…` and
# `scripts/fetch-models.sh` from the root all behave identically. BASH_SOURCE
# gives the script's own path even when invoked through a symlink-free bash.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODEL_DIR="${PROJECT_ROOT}/models"

# Both GGUFs are downloaded here and bind-mounted into the containers.
mkdir -p "${MODEL_DIR}"

# Canonical HuggingFace file-download endpoint. It 302-redirects to a CDN, which
# is exactly why curl must be given -L below.
HF_BASE="https://huggingface.co"

# ── Embedder weights ─────────────────────────────────────────────────────────
# Stage 1 of the retrieval funnel: bge-small-en-v1.5, Q8_0 quantisation.
# Filename confirmed against the repo listing at
# https://huggingface.co/ggml-org/bge-small-en-v1.5-Q8_0-GGUF
EMBEDDER_REPO="ggml-org/bge-small-en-v1.5-Q8_0-GGUF"
EMBEDDER_FILE="bge-small-en-v1.5-q8_0.gguf"

# ── Reranker weights ─────────────────────────────────────────────────────────
# Stage 2 of the retrieval funnel: bge-reranker-base, Q8_0 quantisation.
# Filename confirmed against the repo listing at
# https://huggingface.co/magicunicorn/bge-reranker-base-Q8_0-GGUF
# (which contains exactly one GGUF: bge-reranker-base-q8_0.gguf)
RERANKER_REPO="magicunicorn/bge-reranker-base-Q8_0-GGUF"
RERANKER_FILE="bge-reranker-base-q8_0.gguf"

# fetch <repo> <file> — download one GGUF into ./models unless it is already
# there and non-empty.
#
# Failure handling, deliberately loud:
#   * curl -f  turns HTTP 4xx/5xx into a non-zero exit. Without -f, curl happily
#     writes a 404 error page into the target file and reports success.
#   * -L follows the redirect to the CDN (HF_BASE/... is not itself the bytes).
#   * set -euo pipefail is in force, so a failed download aborts the whole script
#     with a non-zero status rather than leaving a plausible-looking file behind.
#     --retry 3 (below) changes WHEN a failure is declared, not WHETHER one is:
#     three failed attempts still return 1 and still stop the boot.
#   * The transfer lands on a .part file and is moved into place only on success.
#     This matters: the idempotency check below treats "exists and non-empty" as
#     done, so a half-written file from an interrupted run would otherwise be
#     skipped forever and silently poison the model directory.
fetch() {
  local repo="$1"
  local file="$2"
  local dest="${MODEL_DIR}/${file}"
  local part="${dest}.part"
  local url="${HF_BASE}/${repo}/resolve/main/${file}"

  if [[ -s "${dest}" ]]; then
    echo "==> SKIP  ${file} (already present, $(du -h "${dest}" | cut -f1))"
    return 0
  fi

  echo "==> FETCH ${file}"
  echo "        from https://huggingface.co/${repo}"
  echo "        to   ${dest}"

  # --progress-bar would spam a non-tty CI log; --silent keeps the progress
  # lines below as the only output. -o writes the body, not the headers.
  #
  # --retry 3: ~410MB over a fresh NAT gateway on a t3.micro is exactly the
  # shape of transfer where a single dropped connection is a normal event rather
  # than a fault. This does NOT soften the fail-loudly behaviour below — if all
  # three attempts fail the function still returns 1 and the boot still stops —
  # it just stops a routine network blip from killing a boot that had nothing
  # wrong with it. --retry-connrefused covers the cold-start window where the
  # NAT gateway's DNS has not settled yet.
  if ! curl -fL --silent --show-error \
      --retry 3 --retry-connrefused --retry-delay 5 \
      --output "${part}" "${url}"; then
    echo "==> FAILED to download ${file} from ${url}" >&2
    rm -f "${part}"          # never leave a truncated file that would be skipped
    return 1
  fi

  # Guard against a 200 response with an empty body (e.g. an HTML error page
  # served with a success status) being promoted into models/.
  if [[ ! -s "${part}" ]]; then
    echo "==> FAILED: ${url} returned an empty file" >&2
    rm -f "${part}"
    return 1
  fi

  mv "${part}" "${dest}"
  echo "==> OK    ${file} ($(du -h "${dest}" | cut -f1))"
}

echo "lemondrop — fetching model weights"
echo "project root : ${PROJECT_ROOT}"
echo "model dir    : ${MODEL_DIR}"
echo

fetch "${EMBEDDER_REPO}" "${EMBEDDER_FILE}"
fetch "${RERANKER_REPO}" "${RERANKER_FILE}"

echo
echo "All weights present:"
# `|| true`: reaching this line means both fetch() calls returned 0, so both
# files exist and the glob is guaranteed to match. The guard is there anyway
# because an unmatched glob is passed to ls as a literal string and ls returns 2
# — which under `set -e` would abort a download that had in fact just succeeded.
ls -lh "${MODEL_DIR}"/*.gguf || true
echo
echo "Next:  cp .env.example .env && docker compose up -d"