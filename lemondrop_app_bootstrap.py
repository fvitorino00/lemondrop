#!/usr/bin/env python3
"""Bootstrap the least-privilege `lemondrop_app` role and its credential.

WHAT THIS DOES, IN TWO WRITES
    Write 1  CREATE ROLE lemondrop_app in RDS Postgres, with a generated password.
             ONE STATEMENT, and no grants: the operator's agreed sequence is role
             first, Alembic migration next, table grants only after `documents`
             exists. See DEFERRED_GRANTS_POINTER for where those land.
    Write 2  Store that password as the Secrets Manager secret `lemondrop/dev/db/app`.

    Then it proves the two stores agree by connecting as `lemondrop_app` using the
    password RETRIEVED BACK FROM Secrets Manager — not the one still in this
    process's memory. That check is the point: a DSN built from the in-memory
    value would pass even if the secret had been written wrong, and a deployment
    whose application role cannot log in is discovered at first request.

    THIS IS NOT ATOMIC. AWS and Postgres share no transaction, and there is no
    compensating action anywhere in this file. A half-finished run is a state to
    be READ and reconciled by a human, not a mess for the script to tidy up —
    see `reconcile()`.

THE FOUR REFUSALS, AND WHY EACH IS NOT A WARNING
    Pre-existence gate     Something already exists. Stop. Adopting a stranger's
                          role means adopting a password nobody knows; adopting a
                          stranger's secret means running against a credential from
                          a previous attempt that this run did not verify.
    Logging gate           The generated password is literal SQL text inside
                          CREATE ROLE, and PostgreSQL can be configured to write
                          statement text into the log. If it can, the credential
                          is written to disk in cleartext. Read the settings, print
                          them, and refuse rather than change anything: altering an
                          RDS parameter is the operator's decision, not a side
                          effect of a bootstrap script. The gate also fails
                          CLOSED: a setting it cannot read, or cannot parse, is a
                          setting it cannot vouch for, and blocks the run.
    UNCERTAIN on AWS error A create-secret call that raised tells us the RESPONSE
                          failed, not that the WRITE failed. Nothing here deletes
                          anything to "clean up".
    Credential hygiene     No password — generated or master — appears in any
                          printed output, any exception message, or any exit
                          payload. `psql` is run with `-X` and with SQL on stdin,
                          with the password in PGPASSWORD, so it never reaches argv
                          and never reaches ~/.psqlrc.

TERRAFORM RECONCILIATION — VERIFIED FINDINGS, STATED, NOT RE-DERIVED HERE
    1. `infra/` contains NO `aws_secrets_manager_secret` resource. Hand-creating
       `lemondrop/dev/db/app` therefore cannot collide with a planned Terraform
       resource — but it also means Terraform does not know the secret exists.

    2. `infra/iam.tf:509` defines `aws_ssm_parameter.app_db_secret_arn`, whose
       value is currently the MASTER secret ARN
       (`aws_db_instance.db[0].master_user_secret[0].secret_arn`).
       It must be REPOINTED at the app secret ARN. Do NOT add a second parameter:
       the application reads the leaf `secret-arn`, so a second parameter under a
       new name is invisible to the resolver and would leave the master ARN in
       place for the instance role to keep reading.

    3. The resolver (`api/app/config.py`) reads `/lemondrop/dev/db/secret-arn` and
       uses only the secret's `username` and `password` fields. Repointing that
       parameter therefore requires NO resolver code change.

    4. CREDENTIAL VALUES MUST NEVER ENTER TERRAFORM STATE. The secret's value may
       reach Terraform only as an ARN — via a `data` source or a variable — never
       as a plaintext argument to a resource. State is plaintext on disk and in
       every state backend; a password in state is a password in the repository's
       history, the CI cache, and every plan output.

    5. No Terraform-managed RDS parameter group exists, so the logging settings
       this script reads are AWS defaults. Changing them is out-of-band and needs
       the operator's explicit approval. This script only reads and refuses.

THE SSM PARAMETER IS NOT UPDATED BY THIS SCRIPT
    This run leaves `/lemondrop/dev/db/secret-arn` pointing at the master secret.
    Until it is repointed, the deployed application still uses the master
    credential. That is a deliberate hand-off: the repoint is a Terraform change
    that must be reviewed, and doing it out of band here would hide a Terraform
    edit inside a one-off script.

OPERATOR INPUT
    psql, an SSM port-forward already open on 127.0.0.1:15432, and the RDS CA
    bundle at /tmp/rds-global-bundle.pem. Credentials for everything else are
    resolved from AWS through the `lemondrop` profile.
"""

from __future__ import annotations

import json
import os
import secrets as secrets_module
import shutil
import subprocess
import sys

import boto3

# ── WHAT WE POINT AT ──────────────────────────────────────────────────────────
# The profile is named on every single boto3 call. An ambient profile is a
# different account, and a bootstrap that creates a login in the wrong account is
# a finding in someone else's account rather than a failure here.
PROFILE = "lemondrop"
REGION = "eu-west-1"

SSM_PREFIX = "/lemondrop/dev/db"
SSM_HOST = f"{SSM_PREFIX}/host"
SSM_PORT = f"{SSM_PREFIX}/port"
SSM_SECRET_ARN = f"{SSM_PREFIX}/secret-arn"

ROLE_NAME = "lemondrop_app"
SECRET_NAME = "lemondrop/dev/db/app"
CA_BUNDLE = "/tmp/rds-global-bundle.pem"

# `hostaddr` is the address libpq actually opens a socket to — the local end of
# the port-forward — while `host` is what `sslmode=verify-full` checks the
# certificate's CN/SAN against. Using the same value for both would verify the
# certificate against "127.0.0.1" and fail on every run, or, if verification were
# relaxed to `require`, would authenticate an encrypted connection to whatever
# answered that port. Both halves are load-bearing.
TUNNEL_HOST = "127.0.0.1"
TUNNEL_PORT = 15432

# The database the application connects to. NOT read from AWS: `config.py`
# deliberately keeps the database name out of SSM and out of the secret, and reads
# it from DB_NAME with this same default. Using the same variable means this
# script grants against the database the application will actually open.
APP_DATABASE = os.environ.get("DB_NAME", "lemondrop").strip() or "lemondrop"

# `psql -t -A` renders these four booleans pipe-separated. Compared as the exact
# string the server produces, because a substring or a `|`-stripped comparison
# reports failure on a role that is exactly right — and an operator who is told
# "the role is wrong" when it is not will go looking for the thing that is wrong.
EXPECTED_ATTRS = "t|f|f|f"
ATTR_QUERY = (
    "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole "
    f"FROM pg_roles WHERE rolname = '{ROLE_NAME}'"
)

PSQL_TIMEOUT_SECONDS = 60

# The ONLY pgaudit.log readings that do not mean "pgaudit is recording":
#   'not installed'  the GUC does not exist — pgaudit is not loaded, so nothing
#                    can be recording. A real, reported answer.
#   'none'           pgaudit IS loaded and configured to record nothing. This is
#                    the safe, expected configuration of an installed-but-idle
#                    extension, and it must NOT block a run.
# Anything else — 'ddl', 'role', 'ddl, write, read', … — is pgaudit recording
# statement text, and is refused. 'off' is deliberately absent: it is not a
# pgaudit.log value, so treating it as safe would be an unearned exception.
PGAUDIT_IDLE = ("none", "not installed")

# ── DEFERRED GRANTS — POINTER ONLY, NOT APPLIED HERE ──────────────────────────
# >>> WRITE 1 IS `CREATE ROLE` AND NOTHING ELSE. THE GRANTS BELOW ARE NOT ISSUED
# >>> BY THIS SCRIPT, AT ANY POINT, UNDER ANY CONDITION. THIS IS INTENTIONAL.
#
# WHY: the operator's agreed sequence is role first, Alembic migration next,
# table grants only after `documents` exists. `GRANT ... ON TABLE public.documents`
# against a table that does not exist fails, and a conditional grant would encode
# an ordering the sequence forbids — the same command would leave two different
# privilege states depending on whether it ran before or after the migration.
#
# `CONNECT ON DATABASE` and `USAGE ON SCHEMA public` are omitted from the list
# because PostgreSQL grants both to PUBLIC by default: they add no least-privilege
# protection, and re-granting a default only looks like a control.
#
# WHERE THEY WILL BE APPLIED:
#     `apply_deferred_grants()` — a post-migration step that DOES NOT EXIST YET.
#     It must run after the Alembic migration that creates `documents` and after
#     pgvector's CREATE EXTENSION. Do NOT add it to this file's write path; a
#     second, earlier grant path is the defect this deferral exists to remove.
DEFERRED_GRANTS_STEP = "apply_deferred_grants() — post-migration, NOT IMPLEMENTED"
DEFERRED_GRANTS_POINTER = (
    f"the grants named in {DEFERRED_GRANTS_STEP} — "
    "SELECT/INSERT/UPDATE ON TABLE public.documents, USAGE ON TYPE vector"
)

# ── STATE FILLED IN BY main() ─────────────────────────────────────────────────
# Module-level rather than threaded through every signature: this is a linear
# script run once by one operator, and the alternative is a parameter that
# appears in eleven signatures and carries nothing that is not already a constant.
DB_HOST = ""
DB_PORT = 5432
MASTER_USER = ""
MASTER_PASSWORD = ""
APP_PASSWORD = ""
MASTER_SECRET_ARN = ""


class BootstrapError(RuntimeError):
    """A failure whose message is safe to print.

    Every message in this file is written from constants, parameter names and
    return codes. No exception message, no `sys.exit` payload and no printed line
    may contain a password — generated or master — because all three end up in
    shell scrollback, CI logs and SSM Session Manager transcripts.
    """


# ── PRECONDITIONS ─────────────────────────────────────────────────────────────
def check_preconditions() -> None:
    """Verify the three things that must be true before anything is attempted."""
    if shutil.which("psql") is None:
        raise BootstrapError(
            "psql was not found on PATH. This script does not install it and "
            "does not substitute another client; a different client renders "
            "booleans and errors differently, which is exactly what the checks "
            "below depend on."
        )

    if not os.path.isfile(CA_BUNDLE):
        raise BootstrapError(
            f"the RDS CA bundle is missing at {CA_BUNDLE}. With sslmode=verify-full "
            "there is no correct way to proceed without it, and there is no "
            f"correct way to proceed with it absent. Download it to {CA_BUNDLE} "
            "and re-run. (truststore.pki.rds.amazonaws.com/global/"
            "global-bundle.pem)"
        )

    if not (APP_DATABASE.replace("_", "").isalnum()):
        # The database name is interpolated into the libpq conninfo as
        # `dbname=...`, with whitespace and `=` as the delimiters, and there is no
        # parameter binding for a libpq keyword value. Refuse rather than
        # quote-and-hope: a name carrying a space would silently split the
        # keyword in two and connect to a different database than the one named.
        raise BootstrapError(
            "DB_NAME contains characters that cannot be used in a libpq connection "
            "keyword. Set DB_NAME to the database's real name and re-run."
        )


# ── AWS ───────────────────────────────────────────────────────────────────────
def aws_clients() -> tuple[object, object]:
    """Return `(ssm, secretsmanager)` clients for the named profile and region."""
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    return session.client("ssm"), session.client("secretsmanager")


def read_ssm_parameter(ssm: object, name: str) -> str:
    """Return the value of one SSM parameter, or raise a message naming it."""
    try:
        response = ssm.get_parameter(Name=name)
    except Exception as exc:  # noqa: BLE001 — every botocore failure mode
        raise BootstrapError(
            f"reading the SSM parameter {name} failed: {describe_aws_error(exc)}. "
            f"The local profile {PROFILE!r} needs ssm:GetParameter on it."
        ) from None
    value = (response.get("Parameter") or {}).get("Value")
    if not value:
        raise BootstrapError(
            f"the SSM parameter {name} was read but carries no Value. The "
            "parameter exists and is readable, so the problem is its type or "
            "shape — not the policy."
        )
    return str(value).strip()


def read_credential(secrets: object, secret_arn: str) -> tuple[str, str]:
    """Return `(username, password)` from a secret's JSON payload.

    Used twice: for the RDS-managed MASTER secret this script connects as, and
    again in `verify()` for the APP secret — the second read is the one that
    proves the two stores agree.

    The response body is never logged, never `%r`-formatted and never attached
    to an exception. A `logger.debug("secret: %s", body)` is the single line that
    turns this function into a credential leak, and it reads as helpful while
    debugging a parse failure.
    """
    try:
        response = secrets.get_secret_value(SecretId=secret_arn)
    except Exception as exc:  # noqa: BLE001
        raise BootstrapError(
            f"reading the secret {secret_arn} failed: {describe_aws_error(exc)}. "
            "The profile needs secretsmanager:GetSecretValue on it."
        ) from None

    try:
        body = json.loads(response["SecretString"])
        username = body["username"]
        password = body["password"]
    except (ValueError, KeyError, TypeError):
        raise BootstrapError(
            f"the secret {secret_arn} did not have the expected JSON shape "
            "with `username` and `password`. That points at the secret, not at "
            "this script: an RDS-managed secret always carries both fields."
        ) from None

    if not isinstance(username, str) or not isinstance(password, str) or not password:
        raise BootstrapError(
            f"the secret {secret_arn} is missing a usable `username` or "
            "`password` field."
        )
    return username, password


SECRET_ABSENT = "absent"
SECRET_LIVE = "live"
SECRET_SOFT_DELETED = "soft-deleted"


def secret_state(secrets: object) -> str:
    """Classify `lemondrop/dev/db/app` as absent, live, or soft-deleted.

    `describe-secret` is used rather than `get-secret-value` on purpose: this only
    needs to know whether the secret is there, and `get-secret-value` would pull a
    credential into this process's memory for no reason. The response is filtered
    to metadata in the query the operator is given, because a `describe-secret`
    run without a filter prints the ARN and dates but invites the reader to
    widen the filter, and `get-secret-value` prints the password.

    THE SOFT-DELETED CASE IS THE ONE THAT USED TO WEDGE THE SCRIPT.
    `describe_secret` SUCCEEDS for a soft-deleted secret and returns a
    `DeletedDate` — there is no error, so every "does it exist?" check written
    against the exception alone answers "yes". But a soft-deleted secret holds no
    usable value, and after the documented 7-day recovery window AWS releases the
    name and `create_secret` with it genuinely succeeds. An operator who deleted
    the secret, waited, and re-ran therefore hit a gate that refused while
    refusing for the wrong reason, with nothing they could do about it.

    So `DeletedDate` is what decides: absent or null means LIVE and
    pre-existing; present means SOFT-DELETED and treated as ABSENT — because that
    is the state that can actually be written to, and because deleting the secret
    is precisely the operator saying "this name is free".
    """
    try:
        response = secrets.describe_secret(SecretId=SECRET_NAME)
    except Exception as exc:  # noqa: BLE001 — every botocore failure mode
        # Matched on the error CODE, not on a class name or a message: botocore's
        # generated exception classes are not the documented contract, and the
        # code is the only part of the failure that means precisely "absent".
        if aws_error_code(exc) == "ResourceNotFoundException":
            return SECRET_ABSENT
        raise BootstrapError(
            f"could not determine whether {SECRET_NAME} exists: "
            f"{describe_aws_error(exc)}. Refusing to proceed: an unknown is not the "
            "same as absent, and this script will not create over something it "
            "could not see."
        ) from None

    deleted_date = ((response or {}).get("Secret") or {}).get("DeletedDate")
    return SECRET_SOFT_DELETED if deleted_date else SECRET_LIVE


def secret_exists(secrets: object) -> bool:
    """True only if the secret exists AND has not been soft-deleted.

    The boolean view of `secret_state()`, kept for callers that need only the
    yes/no. It is deliberately NOT "describe_secret succeeded": a soft-deleted
    secret answers that question with a success and is still not something this
    script can read, adopt, or write over until its name is released. Callers
    that need to explain that difference to an operator should call
    `secret_state()` and say which of the three they got.
    """
    return secret_state(secrets) == SECRET_LIVE


def create_secret(secrets: object) -> str:
    """Write the app credential to Secrets Manager. Returns the secret ARN.

    `SecretString`, never `SecretBinary`: the resolver in `api/app/config.py`
    parses `SecretString` as JSON. A binary blob would store correctly and then
    fail at resolution, hours later, in a different process.
    """
    payload = json.dumps(
        {
            "username": ROLE_NAME,
            "password": APP_PASSWORD,
            "engine": "postgres",
            "host": DB_HOST,
            "port": int(DB_PORT),
            "dbname": APP_DATABASE,
        }
    )
    response = secrets.create_secret(
        Name=SECRET_NAME,
        Description=(
            "Least-privilege application credential for PostgreSQL. "
            "Created by lemondrop_app_bootstrap.py. The ARN, never the value, "
            "belongs in Terraform."
        ),
        SecretString=payload,
        Tags=[{"Key": "Application", "Value": "lemondrop"}, {"Key": "ManagedBy", "Value": "lemondrop_app_bootstrap.py"}],
    )
    return str(response.get("ARN") or SECRET_NAME)


# ── psql ──────────────────────────────────────────────────────────────────────
def psql(
    sql: str,
    *,
    label: str,
    user: str | None = None,
    password: str | None = None,
    dbname: str = APP_DATABASE,
    reveal_stderr: bool = True,
) -> str:
    """Run one statement through psql and return its stdout, stripped.

    `user` and `password` default to the master credential, resolved from the
    module globals at CALL time and not as default arguments: a default argument
    is bound once, when this `def` executes, which here is at import — before
    `main()` has read the secret. A default of `password=MASTER_PASSWORD` would
    therefore be a frozen empty string, and every privileged call in this script
    would connect with an empty password. The signature says None; the body
    resolves it.

    WHY `-X`: psql reads `~/.psqlrc` by default. That file can set
    `client_min_messages`, a `\\set` variable, a `PROMPT`, or — the reason this
    is not merely tidy — an `ECHO`/`\timing` toggle or a `search_path` that
    changes what a statement in this script actually does. A bootstrap whose
    behaviour depends on a dotfile is a bootstrap that behaves differently on the
    operator's laptop than on the jump host. `-X` ignores it.

    WHY stdin, NOT `-c`: the CREATE ROLE statement contains the generated
    password. On a command line it is visible to every user on the host through
    `ps`, it lands in shell history and in any process-accounting trail, and
    psql's own error output can echo it back. On stdin it is in none of those.
    The password itself travels in `PGPASSWORD`, which is inherited by children
    rather than being rendered in a process listing.

    WHY the error message carries no stderr for credential-bearing statements:
    a failing `CREATE ROLE ... PASSWORD 'x'` makes libpq quote the offending
    statement, so the raw stderr contains the password. `reveal_stderr=False`
    withholds it for exactly those calls.
    """
    if user is None:
        user = MASTER_USER
    if password is None:
        password = MASTER_PASSWORD
    if not user or not password:
        # Unreachable through main(), which resolves the credential before any
        # query. Reachable by a future caller that forgets — and an empty
        # PGPASSWORD produces a confusing authentication failure rather than an
        # obvious one, so it is refused here.
        raise BootstrapError(
            "no credential to connect with: the master user and password must be "
            "resolved from Secrets Manager before any query is run."
        )

    conninfo = (
        f"host={DB_HOST} hostaddr={TUNNEL_HOST} port={TUNNEL_PORT} "
        f"dbname={dbname} user={user} "
        f"sslmode=verify-full sslrootcert={CA_BUNDLE}"
    )
    argv = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-t", "-A", "-F", "|", conninfo]

    # PGPASSWORD is placed on a copy of the environment rather than exported into
    # this process, so nothing else this script later spawns inherits it by
    # accident.
    env = dict(os.environ)
    env["PGPASSWORD"] = password

    try:
        proc = subprocess.run(
            argv, input=sql, env=env, capture_output=True, text=True,
            timeout=PSQL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise BootstrapError(
            f"{label}: psql did not return within {PSQL_TIMEOUT_SECONDS}s. The "
            "statement's outcome is UNKNOWN — see reconcile()."
        ) from None
    except OSError as exc:
        raise BootstrapError(f"{label}: psql could not be started ({exc.__class__.__name__}).") from None

    if proc.returncode != 0:
        if reveal_stderr:
            detail = (proc.stderr or "").strip() or "(no stderr)"
        else:
            detail = (
                "withheld: this statement carries a credential, and psql quotes "
                "the failing statement into stderr"
            )
        raise BootstrapError(f"{label} failed (psql exit {proc.returncode}): {detail}")

    return (proc.stdout or "").strip()


def role_exists() -> bool:
    """True if `lemondrop_app` already exists in pg_roles."""
    count = psql(
        f"SELECT count(*) FROM pg_roles WHERE rolname = '{ROLE_NAME}'",
        label="check whether the application role already exists",
    )
    return count.strip() not in ("", "0")


# ── GATES ─────────────────────────────────────────────────────────────────────
def pre_existence_gate(secrets: object) -> None:
    """Refuse to run if EITHER the role or the secret already exists.

    Both halves are refusals, not adoptions, and for different reasons.

    A PRE-EXISTING SECRET means the credential may belong to a previous attempt
    at this exact procedure — a run that created the secret and then died, or a
    run whose role write was rolled back by hand. Overwriting it destroys the only
    copy of a credential something may already be using; adopting it means this
    run reports success for a password it never verified.

    A PRE-EXISTING ROLE means someone else created it, with a password this
    script has never seen. `CREATE ROLE` would fail, but a "create if not exists"
    wrapper would succeed and hand the application a credential whose owner is
    unknown. So: stop, name which one exists, and let the operator decide.

    A SOFT-DELETED SECRET is neither. `describe_secret` succeeds for it and
    returns a `DeletedDate`; it carries no usable value, and after the 7-day
    recovery window the name itself is free. Treating it as pre-existing — which
    is what a success response implies — stranded any operator who deleted the
    secret and waited, with no way to discover why. So it is treated as ABSENT,
    and the run says so out loud, because it is a surprising distinction and one
    an operator reading only the outcome would not expect.
    """
    state = secret_state(secrets)
    existing_secret = state == SECRET_LIVE
    existing_role = role_exists()

    if state == SECRET_SOFT_DELETED:
        print(
            f"PRE-EXISTENCE GATE — {SECRET_NAME!r} exists but is SOFT-DELETED "
            "(DeletedDate is\n  set), so it is being treated as ABSENT. It holds no "
            "usable value, and once AWS\n  releases the name after the 7-day "
            "recovery window, creating over it succeeds. This is\n  a different "
            "state from 'never existed': see the reconciliation procedure."
        )

    if not (existing_secret or existing_role):
        return

    found = []
    if existing_role:
        found.append(
            f"the PostgreSQL role {ROLE_NAME!r} exists (found in pg_roles)"
        )
    if existing_secret:
        found.append(
            f"the Secrets Manager secret {SECRET_NAME!r} exists"
        )

    raise BootstrapError(
        "PRE-EXISTENCE GATE — refusing to proceed. Found: "
        + "; ".join(found)
        + ".\n\n"
        "Nothing has been created, changed or overwritten.\n"
        "A pre-existing secret may belong to an earlier attempt at this procedure, "
        "whose password this run cannot verify. A pre-existing role was created "
        "by someone else with a password unknown to this script, and adopting it "
        "would hand the application a credential whose owner nobody can name.\n"
        "Delete or rename the offending object yourself and re-run, or, if you "
        "know which state you want, do the reconciliation by hand. This script "
        "will not adopt either one."
    )


def logging_gate() -> None:
    """Read every PostgreSQL logging setting that could capture the password.

    `log_statement = 'none'` is NOT sufficient evidence on its own. The password
    is literal SQL text inside `CREATE ROLE`, and 'ddl' logs DDL — which is
    exactly this statement — as readily as 'all' does. So 'none' and 'off' are
    the only safe values, and the others must be refused rather than reasoned
    about.

    Two further mechanisms are read because both write statement TEXT:

      log_min_duration_statement  Logs the full text of any statement slower
                                 than its threshold. `-1` (the default) is off;
                                 `0` logs EVERY statement, which for this script
                                 is a guaranteed capture of the password. Any
                                 non-negative value is refused for that reason,
                                 even though a slow CREATE ROLE is unlikely —
                                 "unlikely" is not "impossible", and the cost of
                                 being wrong here is a cleartext credential in a
                                 log file with an RDS retention policy.

      pgaudit.log                An audit extension that records statements
                                 independently of log_statement. Three
                                 outcomes, and only ONE of them records:

                                   not installed  the GUC does not exist, so
                                                   pgaudit is not loaded. A real
                                                   answer, reported as such.
                                   'none'         pgaudit IS loaded and is
                                                   configured to record nothing.
                                                   This is the ordinary, safe
                                                   configuration — an installed
                                                   but idle extension — and it
                                                   must NOT block the run.
                                   anything else  recording. Refused.

                                 A read that RAISED is none of those three and
                                 is not treated as "not installed" — see the
                                 fail-closed rule below.

    FAIL CLOSED, NOT OPEN. A logging setting this script cannot read is a
    setting it cannot vouch for, so an unreadable or unparseable value BLOCKS.
    The direction of travel matters: every refusal in this gate exists because
    the alternative is writing a cleartext password to a log file that nobody
    would be looking for. A "could not determine" that resolves to "probably
    fine" is the same outcome with a worse name. So an unreadable GUC, an
    unparseable duration and a pgaudit read that errored are all refusals — not
    warnings, not defaults, and not silent passes.

    This gate READS AND REFUSES. It never sets a parameter. No Terraform-managed
    parameter group exists, so these are AWS defaults; changing them is an
    out-of-band change that belongs to the operator, and a bootstrap script that
    silences an instance's logging as a side effect is not a script anyone
    should run unattended.
    """
    log_statement = _setting("log_statement", label="read log_statement")
    duration = _setting("log_min_duration_statement", label="read log_min_duration_statement")
    pgaudit = _pgaudit_log_setting()

    print("LOGGING GATE — read only; this script changes no RDS setting.")
    print(f"  log_statement                 = {log_statement.render()}")
    print(f"  log_min_duration_statement    = {duration.render()}")
    print(f"  pgaudit.log                   = {pgaudit.render()}")
    print(
        "  These values are printed so they can be judged, rather than trusted as a "
        "single\n  pass/fail boolean. Only 'none' and 'off' keep CREATE ROLE ... "
        "PASSWORD\n  out of the log; 'ddl' logs it exactly as readily as 'all'."
    )

    # ── FAIL CLOSED #1: a setting that could not be read ─────────────────────
    # Checked FIRST and checked as a group, because a refusal here is a refusal
    # about the gate's own ability to do its job. A logging setting this script
    # cannot read is a setting it cannot vouch for: the run proceeds to embed a
    # cleartext password in DDL on the strength of an assumption about a value
    # nobody successfully retrieved. Every reader below records the failure as a
    # failure — no reader can return a string that merely looks like a safe
    # value — so there is no code path on which an unreadable read is treated as
    # safe.
    unreadable = [r for r in (log_statement, duration, pgaudit) if r.unreadable]
    if unreadable:
        raise BootstrapError(
            "REFUSING: "
            + "; ".join(f"{r.name} could not be read ({r.error})" for r in unreadable)
            + ". Nothing has been written.\n"
            "This blocks rather than warns because a logging setting this script "
            "cannot read is a setting it cannot vouch for. A dropped SSM tunnel, a "
            "permissions problem and a genuinely absent GUC all reach this code as "
            "the same 'no answer', and only the last of those is a reason to "
            "continue. Restore the connection — or read the value by hand and set "
            "it explicitly — and re-run."
        )

    # ── log_statement ───────────────────────────────────────────────────────
    if log_statement.value.strip().lower() not in ("none", "off"):
        raise BootstrapError(
            f"REFUSING: log_statement is {log_statement.value!r}, not 'none' or 'off'. "
            "The generated password is literal text inside CREATE ROLE, and at this "
            "setting PostgreSQL writes that text to the log. Set log_statement to "
            "'none' on the instance (a change only the operator should approve) and "
            "re-run. Nothing has been written."
        )

    # ── log_min_duration_statement ──────────────────────────────────────────
    duration_value = _duration_to_ms(duration.value)
    if duration_value is None:
        # FAIL CLOSED #2, and the one that used to fail OPEN. The historical
        # check was `if duration_value is not None and duration_value >= 0`,
        # which meant _duration_to_ms returning None — an unparseable value — was
        # silently treated as SAFE. A value nobody can parse is a value nobody
        # can classify as "-1", and assuming it is off is precisely the assumption
        # this gate exists to refuse. There is no "unknown is probably fine"
        # branch here.
        raise BootstrapError(
            f"REFUSING: log_min_duration_statement is {duration.value!r}, which is not "
            "a number and not a number with a unit (ms, s, min). Nothing has been "
            "written.\nThis blocks rather than assumes: an unparseable threshold is "
            "not known to be -1, and a threshold that cannot be read cannot be "
            "promised not to capture CREATE ROLE ... PASSWORD. Set it explicitly to "
            "-1 (the default) on the instance and re-run."
        )
    if duration_value >= 0:
        raise BootstrapError(
            f"REFUSING: log_min_duration_statement is {duration.value!r}. A non-negative "
            "value logs the full statement text of anything slow enough to exceed "
            "it, and 0 means every statement — including CREATE ROLE ... PASSWORD. "
            "Set it to -1 (the default) and re-run. Nothing has been written."
        )

    # ── pgaudit.log ─────────────────────────────────────────────────────────
    # 'none' is safe and must pass: an installed-but-idle extension is the normal
    # configuration, and refusing it would train operators to disable the gate's
    # warnings rather than fix their instance. 'not installed' is the other safe
    # answer. 'off' is deliberately absent — it is not a pgaudit.log value.
    if pgaudit.value.strip().lower() not in PGAUDIT_IDLE:
        raise BootstrapError(
            f"REFUSING: pgaudit.log is {pgaudit.value!r}, so pgaudit is recording "
            "statements independently of log_statement. Set pgaudit.log to 'none' — "
            "installed and idle — or unload the extension, and re-run. Nothing has "
            "been written."
        )


class _SettingRead:
    """The outcome of reading ONE PostgreSQL setting.

    A read has exactly two possible results, and conflating them is the bug this
    type exists to make impossible: a VALUE (the server answered) or a FAILURE
    (we do not know). The earlier design returned the literal string
    `"unavailable"` on failure. For log_statement that happened to block the run
    only by accident — it matched no safe value — and it was indistinguishable
    from a real setting whose text happened to be that word, and from a value a
    future caller might add to a safe list without thinking.

    Carrying the failure as its own attribute means every consumer must handle
    it explicitly. There is no string here that can be mistaken for a setting
    value, so there is no code path on which an unreadable read reads as safe.
    """

    __slots__ = ("name", "value", "error")

    def __init__(self, name: str, value: str | None = None, error: str | None = None) -> None:
        self.name = name
        self.value = "" if value is None else value
        self.error = error

    @property
    def unreadable(self) -> bool:
        return self.error is not None

    def render(self) -> str:
        """How the setting appears in the gate's printed block."""
        if self.unreadable:
            return f"UNREADABLE — {self.error}"
        return self.value


def _setting(name: str, *, label: str) -> _SettingRead:
    """Read one GUC, returning either its value or the reason it is unknown.

    `current_setting(name, true)` is used so a genuinely absent GUC returns NULL
    (rendered by `psql -t -A` as an empty string) instead of raising. A psql
    failure here is therefore NOT "this setting does not exist" — it is "the
    answer did not arrive", which is a tunnel, a permission or a server problem.
    It is recorded as an error rather than substituted, so `logging_gate()` can
    refuse; see the fail-closed note there.
    """
    try:
        value = psql(
            f"SELECT current_setting('{name}', true)",
            label=label,
            reveal_stderr=False,
        )
    except BootstrapError as exc:
        return _SettingRead(name, error=str(exc))
    return _SettingRead(name, value=value.strip())


def _duration_to_ms(value: str) -> int | None:
    """Parse `log_min_duration_statement` into milliseconds, or None if unparseable.

    None means UNKNOWN, and the only correct thing a caller can do with unknown
    here is block: the value might be 0. The empty string and the legacy
    `"unavailable"` sentinel both map to None for the same reason — they are not
    a threshold, so they cannot be a safe threshold.

    `"unavailable"` is not produced anywhere any more; it is still mapped to None
    defensively so that the word can never reach a comparison against a safe
    value list if an older caller or a hand-patch reintroduces it.
    """
    text = (value or "").strip().lower()
    if text in ("", "unavailable", "null", "none"):
        return None
    for suffix, multiplier in (("ms", 1), ("s", 1000), ("min", 60_000)):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            multiplier_local = multiplier
            break
    else:
        multiplier_local = 1
    try:
        return int(text) * multiplier_local
    except ValueError:
        return None


def _pgaudit_log_setting() -> _SettingRead:
    """Read `pgaudit.log`, distinguishing "absent GUC" from "no answer".

    The two are different facts and the earlier code merged them: any exception
    was reported as "not installed", so a connection failure, a permissions
    problem or a dropped tunnel all read as "pgaudit is absent, carry on" — the
    exact fail-open this gate must not do, on the one setting whose whole purpose
    is to record statement text.

      * An EMPTY result from `current_setting('pgaudit.log', true)` is a genuine
        answer. The GUC does not exist, so pgaudit is not loaded and nothing can
        be recording. That is reported as `not installed` and it does not block.

      * A RAISED error is not an answer. It means the query did not return, and
        "we do not know whether pgaudit is recording" is not the same as "it is
        not". It is recorded as an error, and `logging_gate()` refuses on it.
    """
    try:
        value = psql(
            "SELECT current_setting('pgaudit.log', true)",
            label="read pgaudit.log",
            reveal_stderr=False,
        )
    except BootstrapError as exc:
        return _SettingRead("pgaudit.log", error=str(exc))
    text = value.strip()
    if not text or text.lower() == "null":
        # NULL rendered by `psql -t -A`: the GUC genuinely does not exist.
        return _SettingRead("pgaudit.log", value="not installed")
    return _SettingRead("pgaudit.log", value=text)


# ── WRITES ────────────────────────────────────────────────────────────────────
def generate_password() -> str:
    """Return the password for the new role.

    `token_urlsafe` is chosen so the value can be embedded in a SQL literal
    without escaping: its alphabet is `[A-Za-z0-9_-]`, so it can contain no quote,
    no backslash and no dollar-quote. The assertion below is belt and braces —
    `psql` has no parameter binding for a password inside DDL, so the literal has
    to be provably safe rather than probably safe.
    """
    password = secrets_module.token_urlsafe(32)
    if any(ch in password for ch in ("'", "\\", "`")):
        raise BootstrapError(
            "the generated password contains a character that cannot be embedded "
            "safely as a SQL literal. This should be unreachable; refusing rather "
            "than quoting it and hoping."
        )
    return password


def create_role() -> None:
    """Write 1: `CREATE ROLE` and NOTHING ELSE.

    This issues exactly one statement. It used to also issue four conditional
    grants (`USAGE ON SCHEMA public`, `CONNECT ON DATABASE`,
    `USAGE ON TYPE vector`, `SELECT/INSERT/UPDATE ON documents`), each guarded by
    a probe query for whether the object existed yet. All of that is gone, along
    with the probes, for one reason:

        THE OPERATOR'S AGREED SEQUENCE IS role FIRST, Alembic migration NEXT,
        table grants only AFTER `documents` EXISTS.

    A `GRANT` against an object that does not exist fails outright, and a
    conditional "grant only if present" would encode an ordering the sequence
    explicitly forbids: the grants would silently skip on a fresh instance and
    quietly apply on a migrated one, so the same command would leave two
    different privilege states depending on when it ran. The ordering is real
    state, not a detail to be handled.

    Two of the removed grants never mattered for least privilege:
    `CONNECT ON DATABASE` and `USAGE ON SCHEMA public` are granted to `PUBLIC` by
    PostgreSQL by default, so every role — including this one — already has them.
    Re-granting a default adds no protection and adds a privilege that a future
    `REVOKE ... FROM PUBLIC` would appear to remove while silently not mattering.
    The grants that actually carry privilege are the table and type ones, and
    those are exactly the ones that cannot be issued before the migration.

    WHERE THE DEFERRED GRANTS GO: `apply_deferred_grants()` — see
    `DEFERRED_GRANTS_POINTER` below. That post-migration step DOES NOT EXIST YET.
    Nothing in this file applies them, and this file will not grow a second,
    earlier path that applies them: one grant step, after the migration.

    The statement carries the password, so `reveal_stderr` is off — psql quotes a
    failing statement into its error output.
    """
    statement = (
        f"CREATE ROLE {ROLE_NAME} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
        f"INHERIT PASSWORD '{APP_PASSWORD}'"
    )
    print(f"WRITE 1 — CREATE ROLE {ROLE_NAME}. No grants are issued here.")

    psql(statement + ";", label="create the application role", reveal_stderr=False)
    print(f"  issued: 1 statement, CREATE ROLE {ROLE_NAME} WITH LOGIN NOSUPERUSER "
          "NOCREATEDB\n            NOCREATEROLE INHERIT")
    print("  deliberately NOT granted by this step: DELETE, DDL, and every other")
    print("  role's data.")
    print(f"  NO grants were applied: {DEFERRED_GRANTS_POINTER}")
    print("  They are deferred past the Alembic migration by the agreed sequence —")
    print("  GRANT against a table that does not exist yet fails.")


def write_secret(secrets: object) -> str:
    """Write 2: store the credential in Secrets Manager. Returns the ARN.

    Any exception propagates to `main()`, which treats the outcome as UNCERTAIN
    and mutates nothing. This function has no `except` clause on purpose: there
    is no local recovery that is safer than the global uncertainty.
    """
    print(f"WRITE 2 — create the Secrets Manager secret {SECRET_NAME}.")
    arn = create_secret(secrets)
    print(f"  created: {arn}")
    print("  the value was sent as SecretString, never SecretBinary.")
    return arn


# ── VERIFICATION ──────────────────────────────────────────────────────────────
def verify(secrets: object, secret_arn: str) -> None:
    """Prove the role exists, is unprivileged, and that the two stores agree."""
    print("VERIFICATION — reading state back.")

    attrs = psql(ATTR_QUERY, label="read back the role attributes")
    print(f"  role attributes (rolcanlogin|rolsuper|rolcreatedb|rolcreaterole) = {attrs!r}")
    if attrs != EXPECTED_ATTRS:
        raise BootstrapError(
            f"the role attributes are {attrs!r}, expected {EXPECTED_ATTRS!r}. "
            "The role was created by this script with LOGIN NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE, so this means the role now in the database is "
            "not the one this run created. Investigate before deploying."
        )

    retrieved = read_credential(secrets, secret_arn)[1]
    whoami = psql(
        "SELECT current_user",
        label="authenticate as the application role",
        user=ROLE_NAME,
        password=retrieved,
        reveal_stderr=False,
    )
    print(f"  authenticated as {whoami!r} using the password RETRIEVED FROM Secrets Manager.")
    if whoami != ROLE_NAME:
        raise BootstrapError(
            f"connected to the instance but current_user is {whoami!r}, not "
            f"{ROLE_NAME!r}. The two stores disagree about the credential."
        )
    print(
        "  This check is the one that matters: a login built from the in-memory "
        "password\n  would pass even if the secret had been written incorrectly."
    )


def summary(secret_arn: str) -> None:
    print()
    print("=" * 72)
    print("DONE — two writes, both verified.")
    print(f"  role    : {ROLE_NAME} (login only, no superuser, no DDL, no DELETE)")
    print(f"  secret  : {secret_arn}")
    print(f"  db      : {DB_HOST}:{DB_PORT} (via 127.0.0.1:{TUNNEL_PORT})")
    print()
    print("  NOT DONE, BY DESIGN — no grants were applied by this run:")
    print(f"    {DEFERRED_GRANTS_POINTER}.")
    print("    They are deferred past the Alembic migration that creates `documents`.")
    print()
    print("STILL TO DO BY HAND — the deployment is not switched over:")
    print(f"  1. Repoint {SSM_SECRET_ARN} in infra/iam.tf:509 to the ARN above.")
    print("     Repoint, do not add a second parameter: the resolver reads this")
    print("     exact leaf, and a second name would be invisible to it.")
    print("  2. Run the Alembic migration, THEN apply the deferred table and type")
    print(f"     grants — {DEFERRED_GRANTS_STEP}. Until that step exists and runs, the")
    print("     application role has no access to `documents` at all.")
    print("  3. The secret's VALUE must never enter Terraform state. Pass the ARN")
    print("     as a data source or a variable; never a plaintext resource argument.")
    print("  4. Narrow the instance role (verification-milestone-3.md §11.4) so it can")
    print("     no longer read the master secret. Until then, using the app")
    print("     credential is a convention and not a control.")
    print("=" * 72)


# ── RECONCILIATION ────────────────────────────────────────────────────────────
def reconcile() -> str:
    """Return the recovery procedure as TEXT.

    It returns rather than prints, because its whole purpose is to be routed into
    `sys.exit(...)`. A helper that printed and returned None would raise
    TypeError inside the exact failure path it exists to describe — the operator
    would be handed a traceback instead of the procedure.
    """
    # JMESPath. The braces are DOUBLED because this is an f-string: `{{` emits a
    # literal `{`. It must be an f-string — without the prefix `{{` survives
    # interpolation verbatim and the command renders as `Secret.{{…}}`, which the
    # AWS CLI rejects with a JMESPathError at the operator's shell, long after
    # this script has exited and can no longer say so. `f"…Secret.{{…}}"` renders
    # `Secret.{…}`, which is what the CLI must receive; a stray `}}` would emit a
    # second closing brace and break it the same way.
    #
    # DeletedDate is in the projection so ONE call tells the operator whether the
    # secret is LIVE or soft-deleted. Without it they cannot distinguish the two,
    # and the two demand different branches of step 2 below.
    describe = (
        f"aws secretsmanager describe-secret --profile {PROFILE} --region {REGION} "
        f"--secret-id {SECRET_NAME} "
        f"--query 'Secret.{{Name:Name,ARN:ARN,CreatedDate:CreatedDate,"
        f"DeletedDate:DeletedDate}}'"
    )
    role_query = (
        f"SELECT rolname, rolcanlogin, rolcreatedb FROM pg_roles "
        f"WHERE rolname = '{ROLE_NAME}'"
    )
    return f"""\
RECOVERY — the state is UNCERTAIN, and nothing below is assumed either way.

The create_secret call raised. That is a statement about the RESPONSE. AWS may
have committed the write and then failed to answer: a timeout is not proof of
failure. It is equally possible that nothing was written at all.

There is no compensating action here, deliberately. This script does NOT drop
{ROLE_NAME}. A DROP ROLE issued to "clean up" an uncertain secret write can
delete the role while leaving the secret live — a working credential that
nothing can authenticate against, which is strictly worse than the uncertainty
this procedure exists to resolve.

1. DETERMINE WHAT ACTUALLY EXISTS. Both commands are read-only.

   {describe}

     Metadata only. Do NOT widen this to get-secret-value; that prints the
     password into your terminal and into the session transcript.

     A DeletedDate in that output means the secret is SOFT-DELETED, which this
     script treats as ABSENT everywhere below: it holds no usable value, and
     the name becomes reusable after the 7-day recovery window. No DeletedDate
     means the secret is LIVE and its value is one you must not adopt.

   psql -X "host={DB_HOST or '<rds-hostname>'} hostaddr={TUNNEL_HOST} port={TUNNEL_PORT} \
dbname=postgres user=<master> sslmode=verify-full sslrootcert={CA_BUNDLE}" \\
     -t -A -c "{role_query}"

2. THEN MATCH WHAT YOU FOUND:

   secret EXISTS, role EXISTS
       Nothing to repair. Verify the login, then repoint {SSM_SECRET_ARN}.

   secret EXISTS, role ABSENT
       The role write failed. The secret holds a password nothing uses. Delete
       the secret yourself and re-run this script from the top. Do not let the
       script adopt it — it cannot verify the value it would inherit.

   secret ABSENT, role EXISTS
       The role exists holding a password that is now stored nowhere: this
       process is exiting, so the generated value dies with it. That is the only
       certain thing here.

       RE-RUNNING ALONE CANNOT FIX THIS. The pre-existence gate refuses whenever
       the role exists, so a second run aborts at exactly the same gate having
       created nothing. This is not a transient condition that will clear on its
       own — it is a standing refusal, and "run it again" is the one suggestion
       guaranteed not to help. Two paths that do work, both manual:

         (a) Drop the role yourself, then re-run this script from the top:

                 psql -X "host={DB_HOST or '<rds-hostname>'} hostaddr={TUNNEL_HOST} \\
             port={TUNNEL_PORT} dbname=postgres user=<master> \\
             sslmode=verify-full sslrootcert={CA_BUNDLE}" \\
                 -c "DROP ROLE {ROLE_NAME};"

             Confirm first that nothing depends on this role holding that
             password: dropping it revokes the login immediately and
             irreversibly. That check is yours, not this script's.

         (b) Or keep the role and create the secret BY HAND from a rotated
             value, without re-running anything:

                 ALTER ROLE {ROLE_NAME} PASSWORD '<new value>';

                 aws secretsmanager create-secret --profile {PROFILE} --region {REGION} \\
                   --name {SECRET_NAME} \\
                   --secret-string '{{"username":"{ROLE_NAME}","password":"<new value>","engine":"postgres","host":"{DB_HOST or '<rds-hostname>'}","port":{DB_PORT},"dbname":"{APP_DATABASE}"}}'

             One line for --secret-string on purpose: a backslash continuation
             INSIDE the single quotes is a literal backslash in the JSON, and the
             paste would not parse. Rotate first and use the SAME new value in
             both commands, or the two stores will disagree in exactly the way
             this script exists to detect. The doubled braces in the source are
             there because this text is an f-string; what is printed is plain JSON.

       Either path is a decision about state this script cannot vouch for, so it
       performs neither. Choose one, then repoint {SSM_SECRET_ARN} and carry on
       with the remaining hand-off steps in the summary.

   NEITHER EXISTS
       Safe to re-run from the top. The pre-existence gate will pass.

   secret SOFT-DELETED, role EXISTS
       Identical to "secret ABSENT, role EXISTS" above — that is the whole point
       of treating a DeletedDate as absent. Use path (a) or (b).
"""


def aws_error_code(exc: BaseException) -> str | None:
    """Return the AWS error code carried by a botocore exception, or None.

    Separate from `describe_aws_error` because code COMPARISON is needed
    (`ResourceNotFoundException` means "absent", anything else means "unknown"),
    and a composed description string is not comparable to a code.
    """
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = (response.get("Error") or {}).get("Code")
        if isinstance(code, str) and code:
            return code
    return None


def describe_aws_error(exc: BaseException) -> str:
    """Return a short, credential-free description of a botocore exception.

    Never `str(exc)`. A `ClientError` raised while CREATING the secret can render
    request parameters in its message, and the request parameter is the secret
    value. Only the class name and the AWS error code are safe.
    """
    parts = [type(exc).__name__]
    code = aws_error_code(exc)
    if code:
        parts.append(f"AWS code {code}")
    return " / ".join(parts)


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main() -> int:
    """Run the bootstrap. Returns the process exit code."""
    global DB_HOST, DB_PORT, MASTER_USER, MASTER_PASSWORD, APP_PASSWORD, MASTER_SECRET_ARN

    try:
        check_preconditions()
        ssm, secrets = aws_clients()

        DB_HOST = read_ssm_parameter(ssm, SSM_HOST)
        DB_PORT = int(read_ssm_parameter(ssm, SSM_PORT))
        MASTER_SECRET_ARN = read_ssm_parameter(ssm, SSM_SECRET_ARN)
        MASTER_USER, MASTER_PASSWORD = read_credential(secrets, MASTER_SECRET_ARN)
        print(
            f"Target: {DB_HOST}:{DB_PORT} via {TUNNEL_HOST}:{TUNNEL_PORT}, "
            f"authenticating as the master user read from {MASTER_SECRET_ARN}."
        )

        pre_existence_gate(secrets)
        logging_gate()

        APP_PASSWORD = generate_password()

        create_role()

        # WRITE 2, and the one path with no compensation.
        try:
            secret_arn = write_secret(secrets)
        except Exception as exc:  # noqa: BLE001 — deliberately broad, see below
            # The role exists at this point, and the secret's existence does not.
            # Any "cleanup" here is a guess about which side committed, and a
            # wrong guess destroys a working object to tidy an uncertain one. So:
            # report, do not mutate, exit non-zero, hand over the procedure.
            sys.stderr.write(
                f"\nUNCERTAIN — create_secret raised ({describe_aws_error(exc)}).\n"
                "The role was created. Whether the secret exists is UNKNOWN and "
                "this\nscript will not guess: nothing is being deleted.\n\n"
                + reconcile()
                + "\n"
            )
            return 1

        verify(secrets, secret_arn)
        summary(secret_arn)
        return 0

    except BootstrapError as exc:
        sys.stderr.write(f"\nSTOPPED — {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())