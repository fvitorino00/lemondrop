# Operation LemonDrop — Operator Maintenance Challenge

> **This file is preparation, not evidence.** Nothing in it has been executed.
> No scenario has been run, no fault has been injected, no result has been
> observed, and no recovery has been verified. It is a kit an operator can run
> unaided. Every result slot is empty and marked `NOT RUN`.

---

## Part 1 — How to run a scenario (the contract)

A scenario is an operator-driven exercise that follows the incident arc in
`INCIDENTS.md` §4. The arc is mandatory and ordered:

1. **Prediction before action.** The operator writes a testable hypothesis,
   a `confirms-if` statement, a `rejects-if` statement, and the expected
   symptom **before** the fault is injected. A hypothesis written after the
   evidence is a retelling, not a hypothesis.
2. **Broken-state capture before correction.** The operator captures the
   broken state with read-only tools **before** changing anything.
3. **Evidence in two tables.** Evidence that supports the hypothesis and
   evidence that rejects it are recorded separately, with commands, exit
   codes, and output. If one table has no rows, write `NONE` beneath it.
4. **Smallest defensible correction.** The operator applies the minimum
   change that addresses the established root cause — not the largest change
   that might also help.
5. **Verified recovery with a before/after diff.** The operator captures the
   recovered state with the **same** read-only tools, same arguments, same
   vantage point as the broken-state capture. The diff between the two is the
   recovery.

**Rejected hypotheses are preserved and never deleted.** A hypothesis that
fails stays in the record, marked `REJECTED`, with the evidence that rejected
it. The history of the investigation is part of the evidence
(`INCIDENTS.md:124-127`).

**A scenario is not complete until the same read-only capture has been taken
after recovery, and the before and after captures are the same measurement.**
Comparing a host-side report to a laptop-side curl compares two different
things and is not a valid diff (`INCIDENTS.md:71-78`).

### Standing rule: the operator drives the loop

Every scenario follows the loop in `docs/verification-milestone-5.md` §7:

> **PREDICT → EXECUTE → OBSERVE → EXPLAIN → REVIEW**

The agent may not manufacture, simulate, or infer any of those steps. The
operator performs each step, captures the result, and writes it down.

### Read-only capture pair

The on-host read-only pair is `scripts/verify-deployment.sh` and
`scripts/diagnose.sh` (`INCIDENTS.md:81-83`, `RUNBOOK.md:388-392`).
`verify-deployment.sh` reports what the host is running and whether it matches
the record (`scripts/verify-deployment.sh:5-6`). `diagnose.sh` reports container
health and the status of `/health/live` and `/health/ready`
(`scripts/diagnose.sh:5-6`). Both are safe on a host that is on fire, mid-deploy,
or never deployed to.

The concrete capture procedure, copied from `INCIDENTS.md:355-374`:

```bash
# BEFORE (broken state — capture it, do not fix it yet)
1. sudo /opt/lemondrop/scripts/verify-deployment.sh   | tee /root/inc-<id>-before-verify.txt
2. sudo /opt/lemondrop/scripts/diagnose.sh            # writes /var/lib/lemondrop/diagnostics/<stamp>.txt
3. Copy BOTH out of the host, and note the command, the time (UTC), and the vantage point.
4. Record the observed symptom from THAT output, not from memory.

# CHANGE
5. Make the smallest defensible correction. One change where possible.

# AFTER (recovered state — same tools, same arguments, same vantage point)
6. sudo /opt/lemondrop/scripts/verify-deployment.sh   | tee /root/inc-<id>-after-verify.txt
7. sudo /opt/lemondrop/scripts/diagnose.sh            # a second timestamped report
8. Copy both out of the host.

# DIFF
9. diff /root/inc-<id>-before-verify.txt /root/inc-<id>-after-verify.txt
10. The difference between the two is the recovery. Record it verbatim.
```

If the incident is in retrieval correctness, add the recorded known-good search
probe as a third measurement from the same consistent vantage point
(`INCIDENTS.md:376-379`).

---

## Part 2 — The three scenarios

The scenarios are ordered from least to most destructive:

1. **Application-correctness** — only one request path is wrong; the service
   remains up and reachable.
2. **Dependency** — one container is stopped; the service reports degraded
   readiness but remains manageable on the host.
3. **Networking** — the external path into the service is blocked; the host
   itself remains reachable through SSM.

---

### Scenario 1 — Application-correctness: the E5 search-query boundary fault

| Field | Value |
|---|---|
| **Category** | `INCIDENTS.md` §5.3 — application-correctness |
| **Fault class** | A request passes request-level validation but fails an internal re-validation after a fixed prefix is appended, producing an opaque HTTP 500 instead of a 422 |
| **Deployed defect** | `docs/verification-milestone-5.md` §8, finding **E5** |

#### ⚠️ Blast radius

This fault affects only the `/search` route for queries in the 1992–2048
character window on the deployed image. It does **not** stop the service, does
**not** affect `/embed` or `/rerank`, and does **not** touch the database or the
workers. It is a per-request correctness failure.

#### Prerequisites

- The service is healthy: `GET /health/ready` returns HTTP 200 through the ALB.
- The operator is present and can reach the ALB from the allow-listed address
  `213.22.54.159/32`.
- The operator has discovered the ALB DNS name (`docs/deployment.md` §5.3).
- The rollback target is known: the currently recorded `PREVIOUS_IMAGE_DIGEST`
  in `/var/lib/lemondrop/deployed-revision.env` (`docs/deployment.md` §4.6).
- A fixed revision is available. **The repository's local tree contains the E5
  fix, but no fixed image digest is named in this document.** The operator must
  obtain a fixed digest from a release run per `docs/deployment.md` §3.3, or
  build and publish one. If no fixed revision exists, this scenario cannot be
  completed past the correction step.

#### Prediction template (fill in before running step 1)

| Blank | Operator entry |
|---|---|
| **Hypothesis** | |
| **Confirms if** | |
| **Rejects if** | |
| **Expected symptom** | |

The operator must write the hypothesis, the confirms-if, the rejects-if, and
 the expected symptom in the table above before running the fault command. The
 fault class is described in the scenario header; the operator's prediction
 should be testable from that description.

#### The fault

Run from the operator workstation, after discovering the ALB DNS name:

```bash
ALB=$(aws elbv2 describe-load-balancers --names lemondrop-dev-alb \
      --query 'LoadBalancers[0].DNSName' --output text)

# A 2048-character query that should be rejected but instead crashes the route.
jq -nc '{collection: "it-support", query: ([range(410)] | map("word ") | add | .[0:2048])}' | \
  curl -sS -i "http://${ALB}/search" -H "Content-Type: application/json" --data-binary @-
```

(`docs/deployment.md` §5.3 for ALB discovery;
`docs/verification-milestone-5.md` §8 for the E5 command.)

#### The broken-state capture

Run on the host through SSM, **before** any correction:

```bash
# 1. Record what the host thinks it is running.
sudo /opt/lemondrop/scripts/verify-deployment.sh | tee /root/inc-e5-before-verify.txt

# 2. Record container health and endpoint status.
sudo /opt/lemondrop/scripts/diagnose.sh
# Copy /var/lib/lemondrop/diagnostics/<stamp>.txt off the host.

# 3. Record the broken /search behaviour from the operator vantage point.
ALB=$(aws elbv2 describe-load-balancers --names lemondrop-dev-alb \
      --query 'LoadBalancers[0].DNSName' --output text)
jq -nc '{collection: "it-support", query: ([range(410)] | map("word ") | add | .[0:2048])}' | \
  curl -sS -i "http://${ALB}/search" -H "Content-Type: application/json" --data-binary @- | \
  tee /root/inc-e5-before-search.txt

# 4. Record a control query that should still work.
jq -nc '{collection: "it-support", query: "recover a file a user deleted by mistake from the Recycle Bin"}' | \
  curl -sS -i "http://${ALB}/search" -H "Content-Type: application/json" --data-binary @- | \
  tee /root/inc-e5-before-control.txt
```

#### The smallest correction

The smallest defensible correction is to replace the running image with a
revision that closes the E5 defect class. That means a digest-pinned deploy of
the fixed revision:

```bash
sudo /opt/lemondrop/scripts/deploy.sh ghcr.io/fvitorino00/lemondrop-api@sha256:<fixed-64-hex-digest> <fixed-40-char-sha>
```

(`docs/deployment.md` §4.3.)

**Why this is minimal rather than merely effective:** it changes only the API
image and recreates only the `api` service; the embedder, reranker, and
database are untouched (`scripts/deploy.sh:132-133`,
`docs/deployment.md` §4.5 step 8). It is also the only correction that fixes
the contract: queries in the 1992–2048 window must return 422, not 500.

**Repository gap:** the repository has no pre-built fixed digest named in a
tracked file. `docker-compose.yml` and `.env.example` name digests that are
stale by construction (`docs/deployment.md` §3.2). The operator must obtain the
fixed digest from a successful `release` run's `publish` job summary
(`docs/deployment.md` §3.3), or build and publish the fixed tree first.

If no fixed revision is available, the operator must stop after the broken-state
capture and record that the scenario cannot be completed.

#### The recovery capture

Run the **same** commands as the broken-state capture after the deploy finishes
and `verify-deployment.sh` reports `AGREE`:

```bash
sudo /opt/lemondrop/scripts/verify-deployment.sh | tee /root/inc-e5-after-verify.txt
sudo /opt/lemondrop/scripts/diagnose.sh
# Copy the new /var/lib/lemondrop/diagnostics/<stamp>.txt off the host.

ALB=$(aws elbv2 describe-load-balancers --names lemondrop-dev-alb \
      --query 'LoadBalancers[0].DNSName' --output text)
jq -nc '{collection: "it-support", query: ([range(410)] | map("word ") | add | .[0:2048])}' | \
  curl -sS -i "http://${ALB}/search" -H "Content-Type: application/json" --data-binary @- | \
  tee /root/inc-e5-after-search.txt

jq -nc '{collection: "it-support", query: "recover a file a user deleted by mistake from the Recycle Bin"}' | \
  curl -sS -i "http://${ALB}/search" -H "Content-Type: application/json" --data-binary @- | \
  tee /root/inc-e5-after-control.txt
```

#### The diff

```bash
diff /root/inc-e5-before-verify.txt /root/inc-e5-after-verify.txt
diff /root/inc-e5-before-search.txt /root/inc-e5-after-search.txt
```

A clean recovery shows:

- `verify-deployment.sh` still reports `AGREE` (or the new digest agrees with
  the new record).
- The 2048-character query now returns HTTP 422 naming the `query` field and
  the effective limit, with `Content-Type: application/json`, instead of HTTP
  500 with `Content-Type: text/plain` and body `Internal Server Error`.
- The control query still returns HTTP 200 with the correct top result.

#### The record

Record the result in `INCIDENTS.md` §5.3, using the template in
`INCIDENTS.md` §4. Required fields include:

- `Timestamp detected (UTC, start)`
- `Detected by / from where`
- `Severity`
- `Affected component`
- `Route or path affected`
- Observed symptom
- Hypothesis with `confirms-if` / `rejects-if`
- Evidence supporting / rejecting tables
- Correction: the deploy of the fixed digest
- Verified recovery: before/after diff and the diff output
- Status: `RECOVERED` or `CLOSED` only after the after-capture matches the
  prediction

#### Residue

After recovery, confirm the fault is fully cleared and nothing else changed:

```bash
sudo /opt/lemondrop/scripts/verify-deployment.sh
sudo /opt/lemondrop/scripts/diagnose.sh
# The report must show 0 problems.

# Verify the E5 window is now rejected with 422, not 500.
ALB=$(aws elbv2 describe-load-balancers --names lemondrop-dev-alb \
      --query 'LoadBalancers[0].DNSName' --output text)
jq -nc '{collection: "it-support", query: ([range(410)] | map("word ") | add | .[0:2048])}' | \
  curl -sS -o /tmp/e5-residue.json -w '%{http_code}\n' "http://${ALB}/search" \
  -H "Content-Type: application/json" --data-binary @-
# Operator checks for: 422. If 500, the defect is still deployed.
```

#### Results table

| Step | Operator entry | Result | Exit code / HTTP status | Timestamp (UTC) |
|---|---|---|---|---|
| Prediction written before fault | | NOT RUN | | |
| ALB DNS discovered | | NOT RUN | | |
| Fault injected (2048-char query) | | NOT RUN | | |
| Broken-state verify-deployment.sh | | NOT RUN | | |
| Broken-state diagnose.sh report path | | NOT RUN | | |
| Broken-state /search response | | NOT RUN | | |
| Broken-state control query response | | NOT RUN | | |
| Hypothesis confirmed or rejected | | NOT RUN | | |
| Smallest correction applied | | NOT RUN | | |
| Recovery verify-deployment.sh | | NOT RUN | | |
| Recovery diagnose.sh report path | | NOT RUN | | |
| Recovery /search response | | NOT RUN | | |
| Recovery control query response | | NOT RUN | | |
| Diff reviewed | | NOT RUN | | |
| Residue check passed | | NOT RUN | | |
| Record written to INCIDENTS.md §5.3 | | NOT RUN | | |

---

### Scenario 2 — Dependency: embedder container stopped

| Field | Value |
|---|---|
| **Category** | `INCIDENTS.md` §5.2 — dependency |
| **Fault class** | A service the API depends on becomes unavailable, so `/health/ready` returns 503 while `/health/live` stays 200 |
| **Deployed context** | `INCIDENTS.md` §5.2: "the embedder or reranker failing its healthcheck so the API never becomes healthy" |

#### ⚠️ Blast radius

This fault makes the API unavailable for new `/search` requests that need
embedding, and it makes `/health/ready` return 503. `/health/live` remains 200
because the API process itself is healthy. The database and the reranker are
untouched. This is a dependency failure, not a code failure.

#### Prerequisites

- The service is healthy: `GET /health/ready` returns HTTP 200 through the ALB.
- The operator is present and can reach the host through SSM
  (`docs/deployment.md` §1.1, `RUNBOOK.md` §4).
- The operator can run `docker compose` commands on the host as root.
- The rollback target is known: the currently recorded `PREVIOUS_IMAGE_DIGEST`
  in `/var/lib/lemondrop/deployed-revision.env`.

#### Prediction template (fill in before running step 1)

| Blank | Operator entry |
|---|---|
| **Hypothesis** | |
| **Confirms if** | |
| **Rejects if** | |
| **Expected symptom** | |

The operator must write the hypothesis, the confirms-if, the rejects-if, and
 the expected symptom in the table above before running the fault command.

#### The fault

Run on the host through SSM:

```bash
sudo docker compose -p lemondrop stop embedder
```

(`RUNBOOK.md` §9 for restart semantics; `docker compose stop` is the inverse
of the documented restart operation.)

#### The broken-state capture

Run on the host, **before** any correction:

```bash
# 1. Record what the host thinks it is running.
sudo /opt/lemondrop/scripts/verify-deployment.sh | tee /root/inc-dep-before-verify.txt

# 2. Record container health and endpoint status.
sudo /opt/lemondrop/scripts/diagnose.sh
# Copy /var/lib/lemondrop/diagnostics/<stamp>.txt off the host.

# 3. Record the live vs ready split.
curl -sS -o /dev/null -w 'live=%{http_code}\n' http://127.0.0.1:8000/health/live | \
  tee /root/inc-dep-before-live.txt
curl -sS -o /dev/null -w 'ready=%{http_code}\n' http://127.0.0.1:8000/health/ready | \
  tee /root/inc-dep-before-ready.txt

# 4. Record container state.
sudo docker compose -p lemondrop ps | tee /root/inc-dep-before-ps.txt

# 5. Record a /search attempt (it should fail because embedding is unavailable).
jq -nc '{collection: "it-support", query: "recover a file a user deleted by mistake from the Recycle Bin"}' | \
  curl -sS -i http://127.0.0.1:8000/search -H "Content-Type: application/json" --data-binary @- | \
  tee /root/inc-dep-before-search.txt
```

#### The smallest correction

The smallest defensible correction is to restart only the stopped dependency:

```bash
sudo docker compose -p lemondrop restart embedder
```

(`RUNBOOK.md:403`.)

**Why this is minimal rather than merely effective:** a dependency failure does
not require a deploy or a rollback. Restarting the smallest thing — the stopped
container — restores the dependency without changing the running image, the
record, or the other services (`RUNBOOK.md` §9, three rules that keep a restart
from becoming an incident).

#### The recovery capture

Run the **same** commands after the embedder container returns to healthy:

```bash
sudo /opt/lemondrop/scripts/verify-deployment.sh | tee /root/inc-dep-after-verify.txt
sudo /opt/lemondrop/scripts/diagnose.sh
# Copy the new /var/lib/lemondrop/diagnostics/<stamp>.txt off the host.

curl -sS -o /dev/null -w 'live=%{http_code}\n' http://127.0.0.1:8000/health/live | \
  tee /root/inc-dep-after-live.txt
curl -sS -o /dev/null -w 'ready=%{http_code}\n' http://127.0.0.1:8000/health/ready | \
  tee /root/inc-dep-after-ready.txt

sudo docker compose -p lemondrop ps | tee /root/inc-dep-after-ps.txt

jq -nc '{collection: "it-support", query: "recover a file a user deleted by mistake from the Recycle Bin"}' | \
  curl -sS -i http://127.0.0.1:8000/search -H "Content-Type: application/json" --data-binary @- | \
  tee /root/inc-dep-after-search.txt
```

#### The diff

```bash
diff /root/inc-dep-before-verify.txt /root/inc-dep-after-verify.txt
diff /root/inc-dep-before-live.txt /root/inc-dep-after-live.txt
diff /root/inc-dep-before-ready.txt /root/inc-dep-after-ready.txt
diff /root/inc-dep-before-ps.txt /root/inc-dep-after-ps.txt
```

A clean recovery shows:

- `/health/live` stays 200 before and after.
- `/health/ready` returns 503 before and 200 after.
- `diagnose.sh` reports 0 problems after recovery.
- The known-good `/search` request returns HTTP 200 after recovery.

#### The record

Record the result in `INCIDENTS.md` §5.2, using the template in
`INCIDENTS.md` §4.

#### Residue

After recovery, confirm the fault is fully cleared:

```bash
sudo /opt/lemondrop/scripts/verify-deployment.sh
sudo /opt/lemondrop/scripts/diagnose.sh
# The report must show 0 problems.

sudo docker compose -p lemondrop ps
# embedder must be Up and healthy.

jq -nc '{collection: "it-support", query: "recover a file a user deleted by mistake from the Recycle Bin"}' | \
  curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/search \
  -H "Content-Type: application/json" --data-binary @-
# Operator checks for: 200.
```

#### Results table

| Step | Operator entry | Result | Exit code / HTTP status | Timestamp (UTC) |
|---|---|---|---|---|
| Prediction written before fault | | NOT RUN | | |
| Fault injected (embedder stopped) | | NOT RUN | | |
| Broken-state verify-deployment.sh | | NOT RUN | | |
| Broken-state diagnose.sh report path | | NOT RUN | | |
| Broken-state /health/live | | NOT RUN | | |
| Broken-state /health/ready | | NOT RUN | | |
| Broken-state docker compose ps | | NOT RUN | | |
| Broken-state /search response | | NOT RUN | | |
| Hypothesis confirmed or rejected | | NOT RUN | | |
| Smallest correction applied | | NOT RUN | | |
| Recovery verify-deployment.sh | | NOT RUN | | |
| Recovery diagnose.sh report path | | NOT RUN | | |
| Recovery /health/live | | NOT RUN | | |
| Recovery /health/ready | | NOT RUN | | |
| Recovery docker compose ps | | NOT RUN | | |
| Recovery /search response | | NOT RUN | | |
| Diff reviewed | | NOT RUN | | |
| Residue check passed | | NOT RUN | | |
| Record written to INCIDENTS.md §5.2 | | NOT RUN | | |

---

### Scenario 3 — Networking: ALB→host path blocked

| Field | Value |
|---|---|
| **Category** | `INCIDENTS.md` §5.1 — networking |
| **Fault class** | The path between the ALB and the application host is blocked, so external clients cannot reach the API while the host remains healthy locally |
| **Deployed context** | `INCIDENTS.md` §5.1: "the ALB not reaching the host, the host not reaching RDS, a security-group or route change, DNS, or a source-address change locking the operator out" |

#### ⚠️ Blast radius

**This fault touches the AWS account and production availability.** Blocking
the ALB→host path makes the public API unreachable. The host, the containers,
and the database remain healthy; only the network path from the internet is
broken. The operator must still be able to reach the host through SSM to
restore the path.

The rollback command for **this** fault is **not** `scripts/rollback.sh` — the
fault is in the network path, not in the deployed image. The correction is to
restore the network rule that was removed.

#### Prerequisites

- The service is healthy: `GET /health/ready` returns HTTP 200 through the ALB.
- The operator is present and can reach the host through SSM.
- The operator has AWS CLI permissions to read and modify EC2 security group
  rules, **or** can run `iptables` on the host as root.
- The operator has discovered the ALB DNS name and the application security
  group IDs (`docs/deployment.md` §5.3 for ALB; security group layout is in
  `infra/security_groups.tf:114-230`).
- **Repository gap:** the repository has no procedure for injecting a networking
  fault or for mutating AWS security groups. The operator must work out the
  exact commands. Two approaches are given below; the operator chooses one and
  records which was used.

#### Prediction template (fill in before running step 1)

| Blank | Operator entry |
|---|---|
| **Hypothesis** | |
| **Confirms if** | |
| **Rejects if** | |
| **Expected symptom** | |

The operator must write the hypothesis, the confirms-if, the rejects-if, and
 the expected symptom in the table above before running the fault command.

#### The fault

**Approach A — AWS security group (touches the AWS account):**

The repository has no procedure for this. The operator must work out the AWS
CLI commands. The shape is:

```bash
# Discover the application security group ID.
APP_SG=$(aws ec2 describe-security-groups \
  --filters Name=tag:Name,Values=lemondrop-dev-sg-app-ec2 \
  --query 'SecurityGroups[0].GroupId' --output text)

# Discover the ALB security group ID.
ALB_SG=$(aws ec2 describe-security-groups \
  --filters Name=tag:Name,Values=lemondrop-dev-sg-alb \
  --query 'SecurityGroups[0].GroupId' --output text)

# Discover the rule that allows port 8000 from the ALB SG.
RULE_ID=$(aws ec2 describe-security-group-rules \
  --filters Name="group-id",Values="$APP_SG" \
  --query 'SecurityGroupRules[?Description==`App port from the load balancer only`].SecurityGroupRuleId' \
  --output text)

# Inject the fault: revoke the rule.
aws ec2 revoke-security-group-ingress \
  --group-id "$APP_SG" \
  --security-group-rule-ids "$RULE_ID"
```

(`infra/security_groups.tf:222-230` describes the rule being revoked.)

**Approach B — host-level iptables (self-contained on the host):**

```bash
sudo iptables -A INPUT -p tcp --dport 8000 -j DROP
```

**Repository gap:** neither approach is documented in the repository's
procedures. The operator must choose one, record the choice, and verify it is
reversible before injecting the fault.

#### The broken-state capture

Run on the host, **before** any correction:

```bash
# 1. Record what the host thinks it is running.
sudo /opt/lemondrop/scripts/verify-deployment.sh | tee /root/inc-net-before-verify.txt

# 2. Record container health and endpoint status.
sudo /opt/lemondrop/scripts/diagnose.sh
# Copy /var/lib/lemondrop/diagnostics/<stamp>.txt off the host.

# 3. Record localhost health (should still work if only the network path is broken).
curl -sS -o /dev/null -w 'localhost ready=%{http_code}\n' http://127.0.0.1:8000/health/ready | \
  tee /root/inc-net-before-local.txt

# 4. Record public ALB health (should fail).
ALB=$(aws elbv2 describe-load-balancers --names lemondrop-dev-alb \
      --query 'LoadBalancers[0].DNSName' --output text)
curl -sS -o /dev/null -w 'alb ready=%{http_code}\n' --max-time 10 "http://${ALB}/health/ready" | \
  tee /root/inc-net-before-alb.txt

# 5. Record the security group state (Approach A) or iptables state (Approach B).
aws ec2 describe-security-group-rules \
  --filters Name="group-id",Values="$APP_SG" > /root/inc-net-before-sg-rules.txt
# OR
sudo iptables -L INPUT -n --line-numbers | tee /root/inc-net-before-iptables.txt
```

#### The smallest correction

**Approach A — restore the AWS security group rule:**

```bash
aws ec2 authorize-security-group-ingress \
  --group-id "$APP_SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=8000,ToPort=8000,UserIdGroupPairs=[{GroupId=$ALB_SG,Description=\"App port from the load balancer only\"}]"
```

**Approach B — remove the host-level iptables drop:**

```bash
sudo iptables -D INPUT -p tcp --dport 8000 -j DROP
```

**Why this is minimal rather than merely effective:** the deployed image and
containers are healthy; only the network rule was changed. Restoring that one
rule returns the system to its previous state without a deploy, rollback, or
service restart.

#### The recovery capture

Run the **same** commands after restoring the path and waiting for the ALB
target group to mark the target healthy again:

```bash
sudo /opt/lemondrop/scripts/verify-deployment.sh | tee /root/inc-net-after-verify.txt
sudo /opt/lemondrop/scripts/diagnose.sh
# Copy the new /var/lib/lemondrop/diagnostics/<stamp>.txt off the host.

curl -sS -o /dev/null -w 'localhost ready=%{http_code}\n' http://127.0.0.1:8000/health/ready | \
  tee /root/inc-net-after-local.txt

ALB=$(aws elbv2 describe-load-balancers --names lemondrop-dev-alb \
      --query 'LoadBalancers[0].DNSName' --output text)
curl -sS -o /dev/null -w 'alb ready=%{http_code}\n' --max-time 10 "http://${ALB}/health/ready" | \
  tee /root/inc-net-after-alb.txt

aws ec2 describe-security-group-rules \
  --filters Name="group-id",Values="$APP_SG" > /root/inc-net-after-sg-rules.txt
# OR
sudo iptables -L INPUT -n --line-numbers | tee /root/inc-net-after-iptables.txt
```

#### The diff

```bash
diff /root/inc-net-before-verify.txt /root/inc-net-after-verify.txt
diff /root/inc-net-before-local.txt /root/inc-net-after-local.txt
diff /root/inc-net-before-alb.txt /root/inc-net-after-alb.txt
# For Approach A:
diff /root/inc-net-before-sg-rules.txt /root/inc-net-after-sg-rules.txt
# For Approach B:
diff /root/inc-net-before-iptables.txt /root/inc-net-after-iptables.txt
```

A clean recovery shows:

- `localhost ready=200` before and after.
- `alb ready=503` (or timeout) before, `alb ready=200` after.
- For Approach A, the security group rule is absent before and present after.
- For Approach B, the iptables drop rule is present before and absent after.

#### The record

Record the result in `INCIDENTS.md` §5.1, using the template in
`INCIDENTS.md` §4.

#### Residue

After recovery, confirm the fault is fully cleared:

```bash
sudo /opt/lemondrop/scripts/verify-deployment.sh
sudo /opt/lemondrop/scripts/diagnose.sh
# The report must show 0 problems.

ALB=$(aws elbv2 describe-load-balancers --names lemondrop-dev-alb \
      --query 'LoadBalancers[0].DNSName' --output text)
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 10 "http://${ALB}/health/ready"
# Operator checks for: 200.

# For Approach A: confirm the rule is present.
aws ec2 describe-security-group-rules \
  --filters Name="group-id",Values="$APP_SG" \
  --query 'SecurityGroupRules[?Description==`App port from the load balancer only`]'

# For Approach B: confirm the drop rule is absent.
sudo iptables -L INPUT -n --line-numbers | grep -c 'dpt:8000 DROP' || true
# Operator checks for: 0.
```

#### Results table

| Step | Operator entry | Result | Exit code / HTTP status | Timestamp (UTC) |
|---|---|---|---|---|
| Prediction written before fault | | NOT RUN | | |
| Approach chosen (A or B) | | NOT RUN | | |
| Fault injected (ALB→host blocked) | | NOT RUN | | |
| Broken-state verify-deployment.sh | | NOT RUN | | |
| Broken-state diagnose.sh report path | | NOT RUN | | |
| Broken-state localhost /health/ready | | NOT RUN | | |
| Broken-state ALB /health/ready | | NOT RUN | | |
| Broken-state network rule state | | NOT RUN | | |
| Hypothesis confirmed or rejected | | NOT RUN | | |
| Smallest correction applied | | NOT RUN | | |
| Recovery verify-deployment.sh | | NOT RUN | | |
| Recovery diagnose.sh report path | | NOT RUN | | |
| Recovery localhost /health/ready | | NOT RUN | | |
| Recovery ALB /health/ready | | NOT RUN | | |
| Recovery network rule state | | NOT RUN | | |
| Diff reviewed | | NOT RUN | | |
| Residue check passed | | NOT RUN | | |
| Record written to INCIDENTS.md §5.1 | | NOT RUN | | |

---

## Part 3 — The second-engineer acceptance kit

### The criterion, verbatim

From `docs/verification-milestone-4.md` §13.1:

> *"A second engineer must be able to deploy a tested revision without manually
> reconstructing the original environment."*

The operationalisation of the same sentence, as written:

> **Verified — this is the acceptance criterion, and it must be tested by someone other than the
> author.** A second engineer, given only the runbook and repo access, deploys a SHA-tagged
> revision **without asking a question**, then rolls back, then confirms `/health` and a
> `/search` that returns correct results. **If the author runs this test themselves, the
> criterion is not met** — it is the definition of "without manually reconstructing."
>
> **Done when:** the acceptance sentence is true, witnessed by someone else.

### What the independent engineer receives

- The repository at a named commit.
- `RUNBOOK.md`.
- Nothing else: no help, no hints, no agent, no side-channel explanation.

### What the independent engineer must do

1. From the repository alone, identify that deployments are digest-pinned and
   that the digest must come from a successful `release` run on `main`
   (`docs/deployment.md` §3.4).
2. Obtain the registry manifest digest for the named revision from the
   `publish to GHCR` job summary or log (`docs/deployment.md` §3.3).
3. Confirm the digest is anonymously pullable (`docs/deployment.md` §3.3).
4. Deploy it on the host:
   ```bash
   sudo /opt/lemondrop/scripts/deploy.sh ghcr.io/fvitorino00/lemondrop-api@sha256:<64-hex> <40-char-sha>
   ```
   (`docs/deployment.md` §4.3.)
5. Confirm the deploy succeeded: `verify-deployment.sh` reports `AGREE`,
   readiness is HTTP 200, and the known-good search passes
   (`docs/deployment.md` §5.2).
6. Roll back:
   ```bash
   sudo /opt/lemondrop/scripts/rollback.sh
   ```
   (`docs/deployment.md` §6.1.)
7. Confirm rollback succeeded: `verify-deployment.sh` reports `AGREE` again,
   `/health` returns HTTP 200, and a known-good `/search` returns correct
   results (`docs/deployment.md` §6.3).

### What the operator must capture

- The independent engineer's full transcript (every command typed and every
  output returned).
- The before and after `DEPLOYED_REVISION` fields from
  `/var/lib/lemondrop/deployed-revision.env`.
- Every SSM `send-command` ID and `get-command-invocation` result.
- The exit code of every script invocation (`deploy.sh`, `rollback.sh`,
  `verify-deployment.sh`).
- UTC timestamps for each step.

### What makes the attempt fail

Any of the following invalidates the attempt:

- The independent engineer asks the operator a question.
- The operator gives a hint, a command, or any instruction beyond what is in
  `RUNBOOK.md` and the repository.
- The author or the author's agents run any part of the exercise.
- The deploy is not digest-pinned.
- The rollback is not performed.
- `/health` or the known-good `/search` is not confirmed after rollback.

### Revision to exercise

The exercise should use the currently deployed revision as the **rollback
 target** (the state the host returns to). The independent engineer must deploy
 a **different** tested revision over it, then roll back to this one:

| Field | Value |
|---|---|
| Image digest (rollback target) | `ghcr.io/fvitorino00/lemondrop-api@sha256:c2c1d81c5e743fb8b92b6b9e244179441c345d9441341e525d8d6865dfab39d4` |
| Source revision (rollback target) | `6cc54bc4c09182e37575c5fedb2ad57c71dc7d58` |

**Precondition:** the host must be running the digest and revision listed
 above at the start of the exercise. The independent engineer deploys a
 **different** tested revision over it, then rolls back to the digest and
 revision listed above. Because `deploy.sh` refuses a redundant deploy of the
 running digest (`docs/deployment.md` §4.2.1), the engineer must not attempt to
 deploy the same digest that is already running.

### Rollback-cost note

`rollback.sh` empties `PREVIOUS_*` on success, so there is exactly one rollback
and no second (`docs/deployment.md` §6.3). The second-engineer exercise spends
that one-way rollback. The operator must decide the order: run the three
incident scenarios first, or run the second-engineer acceptance first. Once the
rollback is spent, the host must be put back into a two-revision state (for
example, by deploying a different tested revision) before another rollback can
be demonstrated.

---

## Part 4 — What this document is not

- **No scenario in this document has been run.** Every result slot is empty and
  marked `NOT RUN`.
- **The incident count in `INCIDENTS.md` remains 0 of 3.** This document does
  not change that count.
- **The second-engineer criterion remains UNTESTED and NOT MET.** No
  independent engineer's transcript exists.
- **This file is preparation for an operator-driven exercise, not evidence of
  one.**
- **The 2026-10-21 client-perspective session and the 2026-10-22 release were
  demonstrations and tests respectively, not incident exercises.** No fault in
  this document may be counted as one of the three required incidents until the
  arc in Part 1 is actually performed and recorded in `INCIDENTS.md` §5.1 / §5.2
  / §5.3.

---

## Order rationale

The scenarios are ordered so the least destructive comes first.

1. **Application-correctness (E5)** affects a single request path. The service
   stays up, the containers stay running, and no infrastructure is changed. It
   is the safest first exercise.
2. **Dependency (embedder stopped)** degrades service readiness but is
   reversible with a single container restart. It touches one container, not the
   image or the network.
3. **Networking (ALB→host blocked)** severs the public path and touches the AWS
   account (or host-level firewall rules). It has the widest blast radius and
   is placed last so the operator has already practised the capture-and-recover
   arc twice.

---

## Index of repository artefacts this kit depends on

| Artefact | Citation | What the kit uses it for |
|---|---|---|
| Incident arc template | `INCIDENTS.md:94-171` | Mandatory sequence for every scenario |
| Networking incident definition | `INCIDENTS.md:185-189` | Category for Scenario 3 |
| Dependency incident definition | `INCIDENTS.md:193-201` | Category for Scenario 2 |
| Application-correctness incident definition | `INCIDENTS.md:205-216` | Category for Scenario 1 |
| Evidence-before-and-after procedure | `INCIDENTS.md:355-374` | Capture/diff method |
| Candidate fault E5 | `docs/verification-milestone-5.md` §8 | Fault for Scenario 1 |
| PREDICT → EXECUTE → OBSERVE → EXPLAIN → REVIEW | `docs/verification-milestone-5.md:168` | Operator loop |
| Deploy command | `docs/deployment.md:550` | Scenario 1 correction; second-engineer kit |
| Rollback command | `docs/deployment.md:844` | Second-engineer kit |
| Verify on host | `docs/deployment.md:746` | Capture commands in all scenarios |
| ALB DNS discovery | `docs/deployment.md` §5.3 | Public-endpoint probes |
| What a tested revision is | `docs/deployment.md` §3.4 | Second-engineer kit |
| How to obtain a digest | `docs/deployment.md` §3.3 | Second-engineer kit; Scenario 1 correction |
| Deploy/rollback decision table | `docs/deployment.md:432-437` | When to roll back vs investigate |
| Second-engineer criterion | `docs/verification-milestone-4.md` §13.1 | Verbatim quote in Part 3 |
| SSM access | `RUNBOOK.md:151-154` | Host access |
| SSM send-command / get-command-invocation | `RUNBOOK.md:160-168` | Non-interactive host commands |
| Restart one container | `RUNBOOK.md:403` | Scenario 2 correction |
| What "healthy" looks like | `RUNBOOK.md` §8.1 | Interpreting diagnose output |
| `verify-deployment.sh` usage | `scripts/verify-deployment.sh:5-6` | Read-only identity check |
| `diagnose.sh` usage | `scripts/diagnose.sh:5-6` | Read-only health report |
| Security group layout | `infra/security_groups.tf:114-230` | Scenario 3 fault boundary |
| `ec2_from_alb` rule | `infra/security_groups.tf:222-230` | Rule revoked/restored in Scenario 3 |

---

*End of kit. All result slots above are empty. The operator runs it; this file
records only the script.*
