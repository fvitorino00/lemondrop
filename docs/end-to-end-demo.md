# End-to-end demonstration — plan

> ## ⚠️ NOT YET RECORDED.
>
> **No recording exists.** This file is a **plan** for the walkthrough the
> milestone asks for: a request travelling client → ALB → api →
> embedder/reranker → PostgreSQL → back. Nothing below has been executed, and no
> output is quoted. When the recording is made, its artifacts (commands, outputs,
> where they are kept) go here, and this banner comes down.

---

## 1. What this demonstrates, and what it does not

**It demonstrates** that one request traverses every layer of the deployed stack
and returns a correct answer — the arc the milestone wants shown, not just the
final working system.

**It does not demonstrate** correctness under load, latency, or high
availability. There is no load or soak testing anywhere in this repository
(`docs/deployment.md` §10 item 12), and the ALB idle-timeout field remains
unresolved (`docs/deployment.md` §10 item 4). Those stay out.

The route to record is **`POST /search`**, because it is the only route that
composes *both* workers *and* reads the store — so it exercises the entire chain
in one request. `/embed` would skip the database and the reranker, and `/health`
would skip everything but the ALB hop.

---

## 2. The request to record

One `POST /search` against a collection that holds at least one document, using
the known-good probe document. The probe and the corpus-anchoring check are
recorded in `docs/verification-milestone-3.md` §8.2; the corpus is
`/opt/lemondrop/data/corpus.json` (`docs/deployment.md` §0.2).

```bash
ALB_DNS="$(aws elbv2 describe-load-balancers \
  --names lemondrop-dev-alb \
  --query 'LoadBalancers[0].DNSName' --output text)"

curl -i "http://${ALB_DNS}/search" \
  -H 'Content-Type: application/json' \
  -d '{"collection":"<the collection the corpus was ingested under>","query":"<the known-good query>"}'
```

The ALB discovery command is `docs/deployment.md` §5.3; the collection and query
are whatever §8.2 of the M3 record pins. **Do not hardcode an endpoint hostname**
— `RUNBOOK.md`'s header explains why the M2 literals in that file are records,
not configuration.

---

## 3. The recording plan, hop by hop

Record each step and, alongside it, the artifact that would prove it. "Prove" is
strict: a green response from the top of the stack proves the request succeeded,
not that any particular hop was traversed.

| # | Step to record | Evidence that would prove the hop |
|---|---|---|
| 1 | Resolve the ALB DNS name (command above) | The command output showing the ALB hostname — establishes the client is dialling the load balancer, not an instance |
| 2 | `curl -i` the ALB from the operator `/32` | `HTTP/1.1 200` on the **public** endpoint. The status line and the response come from behind the ALB |
| 3 | Show the ALB forwarded to the api | The api container's own log of the request (`docker compose logs api`) with a timestamp matching step 2. **ALB access logs would be the direct proof but are OFF** (§5) |
| 4 | Show the api embedded the query | The **embedder** container log line for the request (`docker compose logs embedder`), timestamp-matched |
| 5 | Show PostgreSQL was queried for candidates | The response's `candidates_considered` > 0 (only produced by a store read), **plus** the RDS `postgresql` log if it carries the statement (§4 caveat) |
| 6 | Show the reranker scored the candidates | The **reranker** container log line (`docker compose logs reranker`), timestamp-matched |
| 7 | Show the ranked response returned | The `curl -i` body from step 2: `results[]` with `document_id`, `relevance_score`, `distance`, and `model` = the reranker alias |

**The recording must show the request crossing each layer, not just the answer.**
A single `curl` that returns 200 proves step 2 and step 7 and *implies* the
middle. Steps 3–6 are what turn "it worked" into "this request traversed these
components", and they are why the plan records them separately.

---

## 4. Which evidence sources exist today, and which need enabling

| Evidence source | Exists today? | Detail |
|---|---|---|
| `curl -i` from the operator | **Yes** | The normal client path; nothing to enable |
| `docker compose logs api` / `embedder` / `reranker` | **Yes** | On the host; `json-file` rotation at `10m` × 3 per service (`docker-compose.yml:152-158`). Collected over SSM Session Manager |
| RDS `postgresql` + `upgrade` logs → CloudWatch | **Yes — exported** | `enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]` (`infra/database.tf:280`) |
| ALB CloudWatch metrics | **Yes — published by default** | But **no dashboard and no alarm** are configured anywhere in `infra/*.tf` |
| Deployment / boot logs | **Yes** | `/var/log/lemondrop-deploy.log`, `/var/log/lemondrop-boot.log` |
| On-host diagnostic reports | **Yes** | `/var/lib/lemondrop/diagnostics/` (`scripts/diagnose.sh`) |
| **ALB access logs** | **No — OFF.** | See §5. |
| A per-request correlation id across api/worker logs | **Not documented** | No request-id propagation is described anywhere, so correlating one request across the three logs relies on **timestamps**. Do not claim a correlation id exists. |

**One caveat on step 5.** The `postgresql` log is *exported*, but whether it
contains the `SELECT` depends on PostgreSQL's `log_statement` setting, and **this
config does not set it** — there is no parameter-group resource in `infra/`.
So the direct "the database was queried" evidence may not be in that log. The
**reliable** evidence for step 5 is indirect and still sound:
`candidates_considered > 0` in the response can only be produced by a store
read, and the returned documents are the stored rows. Record which of the two you
actually got, and mark the log-based one `NOT OBSERVED` if the statement is not
there.

---

## 5. ALB access logs — plainly OFF

**ALB access logs are not enabled.** `lb_access_logs_enabled` defaults to
`false` (`infra/variables.tf:912-915`), and the ALB resource writes
`access_logs` **only** when that variable is true (`infra/load_balancer.tf:81-115`).
There is no S3 bucket for them — the config deliberately does not create one
(`infra/load_balancer.tf:347-359`).

So **step 3 cannot be proven by an ALB access log today.** To enable it, an
**existing** bucket in the **same region** is required:

```bash
terraform apply -var lb_access_logs_enabled=true \
                -var lb_access_logs_bucket=<an-existing-bucket-in-eu-west-1>
```

Two consequences to record if you enable it, both stated in the config:
access logs persist **request URLs** (here, the search text) into that bucket
(`infra/load_balancer.tf:96-100`), and the bucket's own access story becomes a
separate decision. **In this documentation pass nothing was enabled and nothing
was applied**; the ALB access-log switch is described, not thrown.

Without it, the ALB hop is evidenced by steps 1–2 (you dialled the ALB hostname
and got the app's response from the public endpoint, and no other publicly
reachable thing answers there) — which is real but **indirect**. Say so rather
than presenting `curl` as ALB access-log evidence.

---

## 6. Correlation and capture — how to make the steps one story

Because there is no request id (§4), the steps are tied together by **time**:

1. **Note the UTC time immediately before `curl`.**
2. Collect each log **with `--since`/`--until` around that time**, not `--tail`,
   so the window contains the request under test and nothing ambiguous.
3. Record the **command and its full output** beside each step, so a reader can
   re-run the assertion against the retained log.
4. Copy the api/embedder/reranker log excerpts **off the host** with the recording
   — they rotate away at ~30MB per service.

The record keeps the whole arc: the request, the four hops, the database read,
and the ranked answer. **A recording that shows only the final 200 has not
demonstrated the traversal** — it has demonstrated the endpoint.

---

## 7. What the recording will contain when it is made

- the ALB DNS discovery output;
- the `curl -i` request and its 200 response body;
- the api, embedder and reranker log excerpts for the request window;
- the database-query evidence actually obtained (`candidates_considered`, and the
  CloudWatch statement **or** an explicit `NOT OBSERVED`);
- the UTC timestamps that tie the above together;
- a one-line statement of whether **ALB access logs** were on for the recording
  (today: no).

Until those exist, this section is empty by intent, and the banner at the top
stands.
