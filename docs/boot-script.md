# The boot script — design rationale

This document holds the design rationale, failure history and known limits for
`scripts/boot.sh`, the cloud-init `user_data` script that boots the lemondrop
application host.

It exists as a separate file for a hard, mechanical reason: **EC2 rejects
`user_data` longer than 16,384 bytes.** The rationale used to live inside the
heredoc in `infra/compute.tf`, where it was measured at **24,994 bytes**
rendered — 8,610 bytes over the ceiling, 71% of it comment prose. See
[The 16KB ceiling](#the-16kb-ceiling-and-this-split) below.

The script keeps the comments that are needed at 3am to diagnose something.
Everything moved here.

---

## What this script does and why it exists

`aws_instance.app` boots with no application on it. This script is what turns a
bare AL2023 host into a running stack, in six steps:

1. Install packages and verify `curl`
2. Install the Docker Compose v2 plugin
3. Fetch the application source
4. Generate `.env` from `.env.example`
5. Download ~340MB of model weights from HuggingFace
6. Start the Compose stack and verify `/health`

It is the only place the host's configuration is applied, because EC2 gives you
exactly one shot at it per instance. `user_data_replace_on_change = true` in
`compute.tf` forces a replacement rather than an in-place update when this
changes — without it Terraform would report "updated in place" and leave the
host running the OLD boot script forever, which is a class of bug that produces
a confidently-wrong deployment. Forcing replacement makes the plan say what is
actually true: the script is part of the host's identity.

### The failure that shaped it

The previous version of this script died at its FIRST `dnf install` and told
nobody why. Amazon Linux 2023 ships `curl-minimal`, which already provides
`/usr/bin/curl`; asking dnf to install full `curl` next to it is a package
conflict, dnf refused, `set -e` aborted the script, and every later step —
docker, compose, the models, the stack — never ran. The target group was
registered, the port was published, and nothing was listening, which is exactly
what an ALB reports as 502.

That failure was invisible because of a verification gap worth naming: an
earlier pass checked this script with `bash -n`. That proves SYNTAX and nothing
else. The package database that rejected the install lives on AWS's side, so no
amount of reading, linting or shell-parsing can reach it — only running the
instance can. **"It parses" is not "it runs."**

Two things therefore changed. First, do not assume a package layout the host may
not have: use what AL2023 already ships, and install from where AL2023 actually
publishes things. Second, make the script name its own failure. The ERR trap
below costs four lines and turns "the log stops for no reason" into "line N
exited 1: `<the exact command>`". **The log from the failed boot was 305 bytes
and identified nothing.**

### Logging

Every step announces itself to `/var/log/lemondrop-boot.log` AND to
`/var/log/cloud-init-output.log`. A failed boot on a host with no SSH key and no
public IP is otherwise a mystery, and "mystery" is the most expensive kind of
infrastructure bug: the only handle you have is the log written to tell you
where it stopped. Read it with:

```
sudo tail -n 100 /var/log/lemondrop-boot.log
sudo cat  /var/log/cloud-init-output.log
```

`tee` is allowed to fail here WITHOUT taking the script down with it. A log
write that fails (read-only fs, full disk, bad perms) must not become the reason
the boot dies with no explanation — that is the exact failure shape this script
exists to eliminate, and a logger that can kill its own caller is one more way
to produce it.

### No secrets

There are no credentials in this script, and that is a decision rather than a
style preference. `user_data` is the wrong place for a secret for three separate
reasons:

1. **It is readable by anyone who can call `DescribeInstanceAttribute`.**
   `user_data` is returned in full by `ec2:DescribeInstanceAttribute` — a much
   broader permission than `ec2:StartInstances` or `ec2:TerminateInstances`. A
   read-only operational role with those two is a completely normal setup, and it
   would hand over the database password to it.
2. **It is written to disk, in plain text, forever.**
   `/var/lib/cloud/instances/<instance-id>/user-data.txt`. Anyone with SSM shell
   access, any read-only file role, any volume backup, any forensic image of the
   instance. It survives reboots.
3. **It is echoed to a launch-time log.** cloud-init writes `user_data` and its
   stdout to `/var/log/cloud-init-output.log`. Anything printed there gets
   captured by whatever reads that log — a log shipper, an S3 export, a support
   bundle — and that is the path credentials actually leak through in practice.

The database password is fetched AT RUNTIME by the application, through the
instance role, from Secrets Manager. See the bottom of `iam.tf` for the exact
call.

---

## Why AL2023 specifically

The AMI is resolved from SSM, never hardcoded. A hardcoded AMI ID is a future
incident, and probably a quiet one: it is a pointer into a regional catalogue
AWS edits continuously, and a retired ID returns an error at launch. The worst
of the three failure shapes is the common one — a regional lookup can resolve an
ID you did not intend, the instance boots, and the problem surfaces hours later
as a driver error or a kernel panic. The SSM public parameter resolves to the
CURRENT AMI in the CURRENT region at plan time, and lives in AWS's public
namespace so it resolves on a fresh account before anything else exists.

For a development host that boots its own images and downloads its own models,
"current and patched" beats "identical to March". The trade is byte-for-byte
reproducibility of the host.

The install line carries three notes. `docker` is the runtime for all three
services (installed a few lines later, as an extras topic). `git` is needed
because the application source is cloned, not baked into the AMI. `curl` is
NOT INSTALLED — see below.

### The curl-minimal conflict

AL2023 ships `curl-minimal`, which provides `/usr/bin/curl` and handles the HTTPS
this script needs. Installing full `curl` alongside it is a package conflict:
requesting full `curl` next to curl-minimal is the conflict that killed the
previous boot.
Installing nothing is strictly more robust than installing something, so the
script uses what is there and VERIFIES it below. The guard that reports a
missing curl says so explicitly: "AL2023 normally provides curl via the
curl-minimal package, so reaching this means the image is not a stock AL2023
AMI." That is a clear, readable error if curl really is missing, rather than the
dnf conflict dump that this guard exists to make unnecessary.

The trust store is not in doubt either, and the evidence is on the record: the
failed boot's dnf got far enough to resolve dependencies, which means it had
already downloaded repository metadata over HTTPS, which means the system CA
bundle on this AMI is present and working. `ca-certificates` is listed in the
install as a belt-and-braces no-op — on a stock AMI it is already installed and
dnf reports "Nothing to do" — and it cannot conflict with anything, because it
IS the preinstalled trust store package.

### Docker as an extras topic

AL2023 publishes the Docker Engine as an EXTRAS TOPIC, and the extras
repository is not enabled by default. `dnf install docker` is therefore a "No
match for argument: docker" failure on a stock AL2023 image — the same shape of
failure as the curl line, one step later, waiting for anyone to remove the first
one. This is how AL2023 ships docker.

Two guards make this robust to the packaging detail being different from what is
documented: the `command -v` test means a re-run never calls the installer at
all, and the `||` falls back to dnf so that an image which DOES carry docker in
its base repo still ends up with docker rather than with a failed boot.

### Waiting for the daemon

`systemctl enable --now` does not wait. That is what the poll loop in step 1 is
for — see [Why the script fails loudly](#why-the-script-fails-loudly-and-how)
below, where the transient `activating` state is covered in full.

### Compose v2

The AL2023 docker package does not reliably bundle the Compose v2 CLI plugin, and
this stack needs it — `docker-compose` (v1, hyphenated) is a different command
with different flags. The script tries the packaged plugin first and installs the
official binary only if it is genuinely absent.

The release is PINNED rather than "latest": an unpinned curl-to-shell of a
binary is the same reproducibility problem as a hardcoded AMI id, and it would
also break silently whenever GitHub changes a URL. `linux-x86_64` matches the
AMI architecture; on an ARM host that asset name 404s, which `set -e` turns into
a loud, immediate failure instead of a mysterious one.

`/usr/libexec/docker/cli-plugins` is one of the docker CLI's default plugin
search paths on Linux, which is why the plugin is installed there rather than
into a path only this script knows about.

The plugin is downloaded to a `.part` file and moved into place only on success.
The old version wrote directly to the final path: an interrupted transfer left a
truncated file sitting at the name docker looks for, and every LATER run would
then find a plugin that existed, was executable, and was garbage. That is the
same "plausible-looking file poisons the next run" failure `fetch-models.sh`
already guards against for the GGUFs.

---

## Step 3 — fetching the application source

The instance starts with no copy of the application, so it fetches one. The
clone is `--depth 1` because a boot does not need history; it needs the current
tree, and a shallow clone is several times faster on a small instance.

### The private repository problem — UNFIXED

**Step 3 currently fails on boot.** The clone target is a private GitHub
repository, and an anonymous clone from the instance cannot authenticate.

If the repository is PRIVATE this step fails with an authentication error and
says so in the log. That is expected, and it is **NOT fixed by putting a token
in the URL** — see `var.app_source_url` for why that is not done here. `user_data`
is returned in full by `ec2:DescribeInstanceAttribute`, is written to disk in
plain text at `/var/lib/cloud/instances/<instance-id>/user-data.txt`, and is
echoed to `/var/log/cloud-init-output.log`. A token placed in the boot script
leaks through all three paths.

The alternatives are a baked AMI, a deploy key delivered by a mechanism that
does not embed it in `user_data`, a registry the instance can pull from
anonymously, or making the repository public. This is an operator decision and
is deliberately left open.

---

## Step 4 — the generated `.env`

`.env` is gitignored, so it never arrives with the clone — and Compose
substitutes empty strings for missing variables, which is how a stack ends up
with `API_HOST_PORT=""` and a compose file that still looks fine. It is
generated here from the committed `.env.example`.

**Regenerated every boot, on purpose.** This file is machine-owned and never
hand-edited, and its one variable that matters here — `API_HOST_PORT` — must
agree with `local.app_port`, which is ALSO what the ALB target group is
configured with. An operator-edited `.env` would drift out of agreement with the
load balancer and produce a stack that is healthy and unreachable, which is the
worst possible combination of properties. Overwriting is the correct behaviour
for a generated file.

The line below the `sed` VERIFIES the substitution happened. It is not
decoration: `sed` only rewrites a line that already matches `^API_HOST_PORT=`, so
if `.env.example` ever loses that key the `sed` silently does nothing, Compose
interpolates an empty host port, and the result is a stack that is healthy and
unreachable — the exact failure the paragraph above warns about, arrived at by
the quietest possible route. Assert it instead.

### Do not add a DATABASE_URL here

For whoever adds database support to the api: do NOT add a `DATABASE_URL` line
to this script. There is no password to put in one, and the endpoint hostname is
not knowable from this file — both are fetched at runtime from SSM and Secrets
Manager through the instance role. See the bottom of `iam.tf`.

---

## Step 6 — starting the stack

The api builds locally from `./api` (it has a `build:` section, no published
image); the two workers pull the published llama.cpp image.

The pull is NAMED per service on purpose. A bare `docker compose pull` pulls
every service, including the api — whose image `lemondrop-api` is built here and
exists in no registry, so that command could only ever fail and could only ever
trip its own "WARNING: pull failed" line. Pulling the two services that
genuinely have published images makes the warning mean something when it
appears.

Post-boot, the script confirms the api answers `/health`, so that "the stack is
up" is an OBSERVED fact rather than an assumption.

---

## Why the script fails loudly, and how

A boot script runs once, unattended, on a host with no SSH key and no public IP.
If it fails silently there is no second chance and no handle. So every failure
path names itself.

### `set -Eeuo pipefail`

`-E` (errtrace) is NOT optional decoration here, and `-Eeuo pipefail` is the
combination that makes the trap below actually fire everywhere a command can
fail. Without it the ERR trap is NOT
inherited by shell functions, so a failure inside `log`/`die`/`on_err` would go
untrapped. `-Eeuo pipefail` is the combination that makes the trap fire
everywhere a command can fail.

`pipefail` matters at step 5: because that pipeline's status is the WORST of its
two commands, a failed download aborts the boot there and nowhere else. What was
missing before was any record of WHICH line did it — that is what the ERR trap
supplies.

### The ERR trap

The single highest-value line in this script. Any uncaught non-zero exit prints
the LINE NUMBER, the COMMAND, and the EXIT CODE, then the EXIT trap prints the
terminal marker. Without it a failed boot is a log that stops for no visible
reason — which is precisely how the previous version of this script spent an
evening.

### `die` — deliberate aborts

`die` is named, logged, then exits: a deliberate abort with a stated reason. It
is used for conditions a human must resolve (missing curl, docker that will not
start) so that "the operator chose to stop" never looks like "something
crashed".

### The EXIT trap and the verdict marker

The EXIT trap always fires, on success and on failure, so the last line of the
log is always a verdict rather than a truncation. `BOOT_STATUS` is set on every
path — `SUCCESS`, `FAILED`, `FINISHED WITH WARNINGS` — and the EXIT trap prints
it. The final `BOOT_STATUS=` assignment before `exit 0` therefore SETS the verdict
rather than printing it, and the last line of the log is always the same shape
no matter which path the boot took.

### A shell trap worth remembering

Command substitution in an argument position does not trip `set -e`. The `.env`
verification used to be `log "  $(grep ...)"`, where a grep that matched nothing
returned 1 and was **swallowed**: it printed an empty line and the boot carried
on. That is why it is an explicit `if ! grep -q ...` test now.

Similarly, the wait loop exists because `systemctl enable --now` QUEUES the
start job; it does not wait for
dockerd to finish initialising. `systemctl is-active` called immediately
afterwards legitimately returns non-zero while the unit is still `activating`,
which on a cold t3.micro takes real seconds. The previous version treated that
transient state as fatal and exited 1 with "the docker service did not start" —
a message that is both wrong and unactionable, on a host where dockerd was about
to come up fine. So the script polls until the daemon is genuinely answering,
and asks `docker info` as well as systemd: a unit can be `active` a moment
before the socket is usable, and `docker info` is the check that actually proves
the next step can talk to it.

---

## The idempotency boundary

Every step either checks before it acts or is natively idempotent (dnf,
amazon-linux-extras behind a `command -v` guard, git pull, the model fetcher's
skip-if-present, compose up), so a re-run over a HEALTHY prior run converges on
the same state rather than duplicating work or failing on things that already
exist. That matters for two reasons: `user_data_replace_on_change` re-runs this
on every script change, and an operator debugging a boot will re-run it by hand.

**The boundary, stated so the claim is not read as stronger than it is:
idempotent means "safe to repeat", NOT "repairs whatever it finds".** A prior
boot that failed part-way leaves partial state behind, and this script does not
clean that up for you.

Step 3 is the clearest case. An `$APP_DIR` that exists but is not a git checkout
halts the boot with a named error rather than deleting the directory or cloning
over it, because deciding that a half-built directory is disposable is the
operator's call, not this script's. Other steps may have similar boundaries.
Read a failure, resolve it, re-run.

### Why step 3 refuses rather than repairs

`$APP_DIR` existing but not being a checkout is reachable, not theoretical: a
first boot that failed at an earlier step can leave the directory behind, and so
can anyone — or anything — removing `.git` from an otherwise perfectly good
tree.

The old guard tested only `[ -d "$APP_DIR/.git" ]`, so this case fell through to
`git clone`, which fails with "destination path already exists and is not an
empty directory". Under `set -e` that aborts the boot with a git error that
never mentions the real problem: the directory is not empty AND is not a repo.
Two distinct faults, one unhelpful message.

The test is `-e` on `.git` rather than `-d` because in a worktree or submodule
`.git` is a FILE, not a directory — the old `-d` test would misclassify a
working checkout as this fatal case and refuse a tree that was perfectly fine.

It is deliberately NOT `git rev-parse --git-dir`, which looks tidier and is
wrong here: rev-parse reports success for any directory NESTED INSIDE a
repository, inheriting from the parent. If anything above `$APP_DIR` were ever a
checkout, an empty or partial `$APP_DIR` would be misread as a valid one, and
the `git pull --ff-only` would then run against the PARENT repository. `-e`
asks only about `$APP_DIR/.git`, so the answer cannot come from somewhere else.

Deliberately NOT auto-repaired. Deleting `$APP_DIR` to make the clone succeed
would be a bootstrap that silently destroys whatever it finds — and that
directory can hold a generated `.env`, downloaded model weights, and hand-edits,
none of which this script is entitled to discard. Fail loudly, name the fault,
and let a human decide.

An EMPTY leftover directory is deliberately NOT caught by this branch: `git
clone` into an empty directory succeeds, so halting there would break a boot
that used to work for no gain. The condition tests for non-emptiness precisely so
this fatal path fires only where the clone would genuinely have failed.

---

## The known limits

These are accepted, not solved.

### Boot-time model download vs the ALB health window

~340MB of GGUF is downloaded FROM HuggingFace AT BOOT. This is the slow step,
it happens on every fresh instance, and it is why the ALB target group runs at
the maximum `unhealthy_threshold` it is allowed — see
`var.app_health_check_unhealthy_threshold` and `load_balancer.tf`. Note that
even at that maximum the tolerance window is 10 × 30s = 5 minutes, which this
boot can exceed. **The real fix is baking the models into the AMI.**

If step 5 fails, EVERYTHING downstream fails, and the api never becomes healthy
because its compose healthcheck waits on two workers whose models are not on
disk. So the script lets it fail LOUDLY there, where the cause is visible,
rather than quietly later.

The post-boot check waits 300 seconds, because the api's own compose healthcheck
waits for BOTH workers to finish loading their models into memory — a correct
boot legitimately looks unhealthy for a while. It exits 0 even on timeout,
deliberately: a non-zero exit would mark the boot as failed at the cloud-init
layer, which is noise on top of an ALB grace period that is already handling the
real delay, and it would bury the diagnostics below, which are the thing the
operator actually needs. A loud warning beats a failure code that says nothing
about which of six steps went wrong.

The verification loop is a C-style loop rather than `seq 1 60`: it drops a
dependency on coreutils' `seq` for no gain, and `$((i * 5))` keeps the
elapsed-seconds figure.

### t3.micro memory: 913Mi vs ~410MB

`t3.micro` is ~913Mi total with no swap, and the two GGUFs alone are ~410MB
resident once both workers have loaded them. That is tight. It is not a change
to the instance type — that is the operator's call — but if this boot is killed
here, the memory line above is the first evidence.

This is why the script records `free -m` and `df -h` BEFORE the stack starts. An
OOM kill and a full root volume are both SILENT from the outside: the container
dies, the ALB sees nothing on 8000, and the boot log reads like a clean run that
simply never became healthy. Writing the numbers down first means the next
person can compare them against what the host looked like at the moment of
failure instead of guessing after the fact. If the boot is killed there, the
memory line is the first evidence.

---

## The 16KB ceiling and this split

**EC2 rejects `user_data` longer than 16,384 bytes:**

```
Error: expected length of user_data to be in the range (0 - 16384), got #!/usr/bin/env bash ...
```

`infra/compute.tf` was 39,834 bytes, 71% of it comment prose describing a failure
the static checks could not catch. The rendered heredoc body measured **24,994
bytes** — 8,610 bytes over the limit.

Note what the limit actually applies to: the rendered `user_data` string, the
content between `<<-EOF` and `EOF`, including every byte of indentation.
`<<-EOF` strips leading **TABS only**, not spaces. This file uses 4-SPACE
indentation inside the heredoc, so those spaces remain in the rendered
`user_data` and count toward the limit. Every measurement here is of the real
rendered bytes.

So the rationale moved to this document. `scripts/boot.sh` is now the editable
copy — it can be linted, read, diffed and tested independently of Terraform,
which a heredoc cannot. The script keeps its operational comments: why AL2023
needs `amazon-linux-extras` instead of `dnf install docker`, what each guard
prevents and what the failure looks like, and the non-obvious shell semantics
that will bite at 3am. The design history moved here.

Current state, measured:

| | bytes |
|---|---|
| Rendered heredoc (4-space indent, what AWS counts) | **16,180** |
| De-indented `scripts/boot.sh` | 15,068 |
| Ceiling | 16,384 |
| **Headroom** | **204** |

### For whoever adds to this script next

Headroom is **204 bytes**. Someone will add a feature in six months and hit the
ceiling again. Before you add a comment, measure — don't eyeball, and don't
count characters:

```sh
# byte count of the file itself
wc -c scripts/boot.sh

# byte count of the RENDERED heredoc — this is the one that must stay
# under 16,384, because it is what EC2 validates
S=$(grep -n 'user_data = <<-EOF' infra/compute.tf | cut -d: -f1)
E=$(grep -n '^  EOF$'        infra/compute.tf | cut -d: -f1)
sed -n "$((S+1)),$((E-1))p" infra/compute.tf | wc -c
```

The rendered size is larger than the file size by 4 bytes per non-blank line
(the heredoc indentation is not stripped), plus every multi-byte character
counts its full UTF-8 width. A character count will lie to you: an earlier
draft of this split measured 16,264 "bytes" by counting characters and was in
fact 17,067 bytes of UTF-8 — over the limit by 683. ASCII section rules instead
of box-drawing ones recovered 640 bytes on their own.

If you are out of room, the honest move is to put the *rationale* here in
`docs/boot-script.md` — linkable and searchable rather than buried in a heredoc
— and keep only what someone needs to diagnose a failure at 3am.