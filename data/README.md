# `data/` — Milestone 3 synthetic runbook corpus

## What this is

`corpus.json` is a **synthetic** corpus of 40 technical runbooks used to exercise the
LemonDrop Milestone 3 retrieval system: ingestion, chunking, embedding, and
**collection-scoped** semantic search.

**It is synthetic. It was generated for Milestone 3 by this project. It was not supplied by
the operator, not supplied by a third party, and is not real-world documentation.** Every
runbook was written from scratch by the build agent. There are no real credentials, no real
AWS account identifiers, no real hostnames, and no real personal data anywhere in the file —
only generic placeholders such as `<INSTANCE_ID>`, `<VPC_ID>`, and `<TG_ARN>`.

The file's `synthetic: true` flag and its `generation_note` say so, and they must not be
edited to imply otherwise.

## Why it exists

A full search of this repository found **no dataset**: no `data/`, `datasets/`, `runbooks/`,
or `corpus/` directory, and no corpus file of any kind. The operator was told this and
explicitly decided that we generate a synthetic corpus instead, with the provenance recorded
here so an official dataset can replace it later without anyone mistaking it for real data.

## Structure

- **40 documents total**, split evenly across two collections of **20 each**:
  - `infrastructure` — AWS / cloud operations runbooks (owner `platform-team`)
  - `it-support` — end-user support runbooks (owner `it-support`)

Every document has a `Purpose:` line, six numbered steps with concrete commands or console
paths, and a closing `Verification:` line. Content runs 167–279 words (mean 220), which is
long enough to be chunked into multiple embeddings rather than collapsing into a single
trivial vector.

The 20 `it-support` documents cover all 20 required end-user topics. Three topics that are
naturally one support workflow are documented together rather than split: shared-drive grants
and repository requests share `support-resource-access-grant`, and a slow external display and
second-monitor setup share `support-external-monitor-setup`. The canaries absorb three further
required topics (MFA reset for a locked-out user, offboarding access removal, and the
workstation backup/restore workflow), which is why 20 required topics fit exactly 20 documents.

## The isolation canaries

Ten of the 40 documents — five in each collection — are flagged
`"metadata": {"isolation_canary": true}`. They are **deliberately near-identical in wording,
step structure, and topic across the two collections**, and they differ only in subject
domain: an AWS infrastructure action versus the analogous end-user support action.

| # | `infrastructure` | `it-support` | Shared shape |
|---|---|---|---|
| 1 | `infra-aws-iam-key-rotation` | `support-service-account-password-rotation` | rotating the credential for the lemondrop **service account** |
| 2 | `infra-rds-snapshot-restore` | `support-workstation-backup-and-restore` | restoring from a scheduled **backup / snapshot** |
| 3 | `infra-security-group-ingress` | `support-admin-console-access-grant` | granting a new **administrator** a rule of access |
| 4 | `infra-drain-unhealthy-target` | `support-departing-employee-access-removal` | forcing the old holder out **before** the handover/replacement |
| 5 | `infra-rds-master-password-rotation` | `support-mfa-reset-locked-out-user` | rotating the secret factor for a **locked-out** principal |

For example, `infra-rds-master-password-rotation` and `support-mfa-reset-locked-out-user`
share the same six-step skeleton almost line for line — record the current state, generate a
strong replacement, change the enrolled factor first, update the stored backup, restart the
consumers, roll forward rather than back — and differ only in whether the subject is a database
password in Secrets Manager or an authenticator enrolment on a user account.

**These documents are load-bearing for the acceptance criterion.** A semantically meaningful
search over each one returns its near-identical twin as the top-scoring neighbour across the
whole corpus. So the strongest possible isolation test is:

> Run a search scoped to `collection = "infrastructure"` and assert that **none** of the five
> `infrastructure` canary ids' twins (`support-*` ids) appear in the result set at all — not
> ranked lower, not listed as a "related" suggestion, absent. And the same test mirrored for
> `it-support`.

A lexical or naive system fails this immediately, because the twins share most of their
words. A retrieval layer that ignores the collection filter fails it too. A system that
passes this has genuinely scoped the search and is done.

## Document schema

The wrapper object:

```json
{
  "corpus_version": "1.0.0",
  "synthetic": true,
  "generation_note": "...",
  "generator": "lemondrop-milestone-3",
  "document_count": 40,
  "collections": ["infrastructure", "it-support"],
  "documents": [ ... ]
}
```

Each document:

```json
{
  "id": "infra-aws-iam-key-rotation",
  "collection": "infrastructure",
  "content": "Purpose: ... 1. ... 2. ... Verification: ...",
  "metadata": {
    "title": "Rotate an AWS IAM access key for the service account",
    "tags": ["aws", "iam", "credentials", "rotation"],
    "owner": "platform-team",
    "severity": "medium",
    "updated_at": "2026-03-14",
    "isolation_canary": false
  }
}
```

Field contract:

| Field | Rule |
|---|---|
| `id` | lowercase, hyphen-separated, unique across all 40, prefixed `infra-` or `support-` |
| `collection` | exactly `infrastructure` or `it-support` |
| `content` | 150–350 words, plain text, numbered steps, `Purpose:` first, `Verification:` last |
| `metadata.title` | clean human title |
| `metadata.tags` | 3–5 lowercase tags |
| `metadata.owner` | `platform-team` for infrastructure, `it-support` for it-support |
| `metadata.severity` | one of `low`, `medium`, `high` |
| `metadata.updated_at` | ISO date `YYYY-MM-DD`, spanning 2025–2026 |
| `metadata.isolation_canary` | JSON boolean; `true` only for the ten canary documents |

## Replacing this with an official dataset

Nothing downstream should depend on this particular file's contents — only on its shape. To
swap in a real corpus:

1. **Overwrite `data/corpus.json`** with the official file. Keep the wrapper keys
   (`corpus_version`, `synthetic`, `document_count`, `collections`, `documents`) and the
   document schema above exactly as they are, so the ingest path needs no change.
2. Set `"synthetic": false` and rewrite `generation_note` to state the real provenance and
   date. Do not leave the synthetic note attached to a third-party dataset.
3. If the official dataset has no isolation canaries, either drop the canary tests or add
   equivalent cross-collection near-duplicates deliberately. Do not remove the test and
   silently lose the isolation guarantee.
4. Re-run the counts (`document_count == len(documents)`, per-collection split) as part of the
   swap, and update this README to describe the new corpus.

No code outside `data/` needs to change. If you would rather point the ingest path at a
different file entirely, that is a cleaner route and this directory can be deleted outright.