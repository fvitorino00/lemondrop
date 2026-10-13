"""Fully mocked tests for `lemondrop_app_bootstrap.py`.

NOTHING HERE TOUCHES THE NETWORK OR A DATABASE. `subprocess.run` (which is how
every psql call in the script happens) and the whole boto3 session are replaced
before `main()` is called. The module is loaded by path because its filename is
not a valid Python identifier.

The map below covers the eight earlier corrections and the five later ones:

    1  py_compile / the psql precondition       -> module imports; the old walrus
                                                    SyntaxError cannot exist here
    2  reconcile() returns text                  -> test_reconcile_returns_text
    3  pre-existence gate before any write       -> test_pre_existing_role_aborts,
                                                    test_pre_existing_secret_aborts
    4  never DROP ROLE on a secret error         -> test_create_secret_raises_is_uncertain
    5  no credential leakage                    -> test_no_credential_leakage,
                                                    and stderr withheld in test 8
    6  preserved flags / verification from SSM   -> test_happy_path (password taken
                                                    from the secret, not memory)
    7  broadened logging gate                   -> test_logging_gate_*, test_pgaudit_*
    8  Terraform findings                       -> header-only; asserted by
                                                    test_happy_path's summary text
    +  the attribute check must compare "t|f|f|f" -> test_role_attribute_mismatch_reports_raw

    9  FIX 1  pgaudit.log = 'none' proceeds       -> TestPgauditHandling
   10  FIX 2a unreadable GUC blocks             -> TestFailClosedLoggingGate
   11  FIX 2b unparseable duration BLOCKS       -> TestFailClosedLoggingGate
                                                    (the old check read
                                                    `... is not None and ... >= 0`,
                                                    so None passed — a fail-open)
   12  FIX 2c pgaudit read error is not "absent" -> TestPgauditHandling
   13  FIX 3   Write 1 is CREATE ROLE only      -> TestCreateRoleIssuesOnlyCreateRole
   14  FIX 4a  DeletedDate means absent         -> TestSoftDeletedSecret
   15  FIX 4b/4c recovery advice + JMESPath     -> TestReconcile

Every one of 9–15 is a REGRESSION test: each was confirmed to FAIL against the
pre-fix code by mutating the script back to the old logic and re-running.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

# ── boto3 AVAILABILITY ────────────────────────────────────────────────────────
# boto3 is installed in this project's .venv but not in the system interpreter
# that `python3 -m unittest` resolves to. The script's only boto3 use is
# `boto3.Session(...)`, and every test replaces that attribute before main() is
# called, so where the real package is unavailable a stub is registered instead —
# one that RAISES if anything reaches it. A stub that could open a connection
# would defeat the point of a mocked suite; this one cannot.
try:  # pragma: no cover — environment-dependent
    import boto3 as _boto3  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _stub = types.ModuleType("boto3")

    def _no_session(*_args, **_kwargs):
        raise AssertionError(
            "the real boto3 was replaced by a stub, and nothing patched "
            "boto3.Session — a test is missing its mock.patch"
        )

    _stub.Session = _no_session
    sys.modules["boto3"] = _stub

# ── LOAD THE MODULE BY PATH (the filename contains a dash) ────────────────────
_SPEC = importlib.util.spec_from_file_location(
    "lemondrop_app_bootstrap",
    Path(__file__).with_name("lemondrop_app_bootstrap.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)

GENERATED = "GENERATED-PASSWORD-SENTINEL"
MASTER_PW = "MASTER-PASSWORD-SENTINEL"
MASTER_USER_NAME = "lemondrop_master"
MASTER_ARN = "arn:aws:secretsmanager:eu-west-1:111122223333:secret:rds-managed-master-abc"


class FakePsql:
    """Stand-in for `subprocess.run`. Routes on the SQL sent on stdin.

    Every value it returns is a canned answer; nothing is parsed from a real
    server. `sql_log` is what the assertions read to prove what was — and was
    not — sent to the database.
    """

    def __init__(self) -> None:
        self.sql_log: list[str] = []
        self.passwords_used: list[str] = []
        self.users_used: list[str] = []
        # Configurable answers.
        self.role_count = "0"
        self.log_statement = "none"
        self.log_min_duration = "-1"
        self.pgaudit = ""  # empty string means "setting absent, returned NULL"
        self.pgaudit_raises = False
        self.log_statement_raises = False
        self.log_min_duration_raises = False
        self.attrs = "t|f|f|f"
        self.current_user = "lemondrop_app"
        self.fail_on = ""  # substring of SQL to fail on

    # -- the fake subprocess.run ------------------------------------------------
    def __call__(self, argv, **kwargs):
        sql = kwargs.get("input", "")
        self.sql_log.append(sql)
        self.passwords_used.append(kwargs.get("env", {}).get("PGPASSWORD", ""))
        conninfo = argv[-1]
        self.users_used.append(
            conninfo.split("user=")[1].split()[0] if "user=" in conninfo else "?"
        )

        if self.fail_on and self.fail_on in sql:
            return self._failed(argv, sql)

        if "count(*) FROM pg_roles" in sql:
            out = self.role_count
        elif "current_setting('log_statement'" in sql:
            if self.log_statement_raises:
                # A dropped tunnel: the query never returns. The script must
                # treat this as UNKNOWN and block — not as a setting value.
                return self._failed(argv, sql)
            out = self.log_statement
        elif "current_setting('log_min_duration_statement'" in sql:
            if self.log_min_duration_raises:
                return self._failed(argv, sql)
            out = self.log_min_duration
        elif "current_setting('pgaudit.log'" in sql:
            if self.pgaudit_raises:
                return self._failed(argv, sql)
            out = self.pgaudit
        elif "SELECT rolcanlogin" in sql:
            out = self.attrs
        elif "SELECT current_user" in sql:
            out = self.current_user
        else:
            # CREATE ROLE. Everything else the script might send — GRANTs, and the
            # pg_type/pg_class probes `create_role()` used to issue — falls here
            # and returns nothing. The assertions read `sql_log` directly to prove
            # those statements were never sent in the first place.
            out = ""
        return subprocess.CompletedProcess(argv, returncode=0, stdout=out + "\n", stderr="")

    @staticmethod
    def _failed(argv, sql):
        return subprocess.CompletedProcess(
            argv,
            returncode=1,
            # psql quotes the failing statement into stderr. A realistic fake has
            # to reproduce that, or the credential-hygiene assertions would pass
            # against a strawman.
            stdout="",
            stderr=f'ERROR:  syntax error at or near "PASSWORD"\nLINE 1: {sql}\n',
        )

    # -- assertions helpers ----------------------------------------------------
    def sent(self, needle: str) -> list[str]:
        return [s for s in self.sql_log if needle in s]

    def create_role_calls(self) -> list[str]:
        return self.sent("CREATE ROLE")


class ResourceNotFoundException(Exception):
    """Mirrors botocore's generated class name AND its `response` shape.

    Both halves matter. The script reads `response["Error"]["Code"]`, so a fake
    that only sets the class name would send it down the "could not determine"
    path, and a fake that only sets `response` would hide a real coupling bug.
    """

    def __init__(self) -> None:
        super().__init__("Secrets Manager can't find the specified secret.")
        self.response = {"Error": {"Code": "ResourceNotFoundException"}}


class BootstrapTestCase(unittest.TestCase):
    """Installs the full mock stack. Every test starts from here."""

    def setUp(self) -> None:
        self.psql = FakePsql()

        self.ssm = mock.MagicMock()
        self.ssm.get_parameter.side_effect = self._ssm_parameter

        self.secrets = mock.MagicMock()
        # Keyed by SecretId, exactly as Secrets Manager behaves. This is what lets
        # the happy-path test PROVE that the verification login used the app
        # password read back from the secret: a double that answered every call
        # with the master's payload would make that assertion meaningless.
        master_body = json.dumps(
            {"username": MASTER_USER_NAME, "password": MASTER_PW, "engine": "postgres"}
        )
        app_body = json.dumps(
            {
                "username": mod.ROLE_NAME,
                "password": GENERATED,
                "engine": "postgres",
                "dbname": "lemondrop",
            }
        )

        def _secret_value(SecretId):  # noqa: N803 — boto3's keyword is capitalised
            return {"SecretString": master_body if SecretId == MASTER_ARN else app_body}

        self.secrets.get_secret_value.side_effect = _secret_value
        # Absent by default: a Secrets Manager secret that does not exist is
        # reported by botocore as ResourceNotFoundException, NOT as a null result.
        self.set_secret_state("absent")
        self.secrets.create_secret.return_value = {
            "ARN": "arn:aws:secretsmanager:eu-west-1:111122223333:secret:lemondrop/dev/db/app-xyz"
        }

        session = mock.MagicMock()
        session.client.side_effect = lambda name, *a, **k: (
            self.ssm if name == "ssm" else self.secrets
        )

        patches = [
            # side_effect keeps the real call recorded in call_args_list, so a
            # test can assert on the argv the script would really have used.
            mock.patch.object(mod.subprocess, "run", side_effect=self.psql),
            mock.patch.object(mod.boto3, "Session", return_value=session),
            mock.patch.object(mod.shutil, "which", lambda name: "/usr/bin/psql"),
            mock.patch.object(mod.os.path, "isfile", lambda path: True),
            mock.patch.object(mod.secrets_module, "token_urlsafe", lambda n: GENERATED),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def _ssm_parameter(Name):  # noqa: N803 — boto3's keyword is capitalised
        values = {
            mod.SSM_HOST: "lemondrop-dev.abc.eu-west-1.rds.amazonaws.com",
            mod.SSM_PORT: "5432",
            mod.SSM_SECRET_ARN: MASTER_ARN,
        }
        if Name not in values:
            raise AssertionError(f"unexpected SSM parameter {Name!r}")
        return {"Parameter": {"Value": values[Name]}}

    def set_secret_state(self, state: str) -> None:
        """Arrange the three states `describe_secret` can actually report.

        "absent" raises ResourceNotFoundException, "live" SUCCEEDS with no
        DeletedDate, and "deleted" SUCCEEDS WITH one. The last two are the point:
        botocore gives no exception at all for a soft-deleted secret, so any check
        written against the exception alone cannot tell them apart from a live one.
        """
        if state == "absent":
            self.secrets.describe_secret.side_effect = ResourceNotFoundException()
        elif state == "live":
            self.secrets.describe_secret.side_effect = None
            self.secrets.describe_secret.return_value = {
                "Secret": {"Name": mod.SECRET_NAME, "CreatedDate": "2026-01-01T00:00:00Z"}
            }
        elif state == "deleted":
            self.secrets.describe_secret.side_effect = None
            self.secrets.describe_secret.return_value = {
                "Secret": {
                    "Name": mod.SECRET_NAME,
                    "CreatedDate": "2026-01-01T00:00:00Z",
                    "DeletedDate": "2026-01-08T00:00:00Z",
                }
            }
        else:
            raise AssertionError(f"unknown secret state {state!r}")

    # -- driver ----------------------------------------------------------------
    def run_script(self) -> tuple[int, str]:
        """Run main() with stdout+stderr captured. Returns (exit_code, output)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mod.main()
        return code, out.getvalue() + err.getvalue()


# ══ 1. HAPPY PATH ═════════════════════════════════════════════════════════════
class TestHappyPath(BootstrapTestCase):
    def test_happy_path_writes_both_stores_then_verifies(self):
        code, output = self.run_script()

        self.assertEqual(code, 0, output)

        # Both writes happened, in order: the role is created BEFORE the secret,
        # because a failed secret write is recoverable while a failed role write
        # leaves a role holding a password nobody stored.
        self.assertEqual(len(self.psql.create_role_calls()), 1, output)
        self.secrets.create_secret.assert_called_once()

        # The password the role was given is the one the secret received.
        role_sql = self.psql.create_role_calls()[0]
        self.assertIn(f"PASSWORD '{GENERATED}'", role_sql)
        payload = json.loads(self.secrets.create_secret.call_args.kwargs["SecretString"])
        self.assertEqual(payload["password"], GENERATED)
        self.assertEqual(payload["username"], mod.ROLE_NAME)
        # Correction 6: SecretString, never SecretBinary.
        self.assertNotIn("SecretBinary", self.secrets.create_secret.call_args.kwargs)

        # The verification login used the password RETRIEVED FROM Secrets Manager.
        # Asserted by identity against the stored payload, not by comparing to the
        # generated constant — the point is that the two stores agree.
        login_idx = next(i for i, s in enumerate(self.psql.sql_log) if "current_user" in s)
        self.assertEqual(self.psql.users_used[login_idx], mod.ROLE_NAME)
        self.assertEqual(self.psql.passwords_used[login_idx], payload["password"])
        self.assertEqual(self.psql.passwords_used[0], MASTER_PW)  # the setup calls
        self.assertIn("RETRIEVED FROM Secrets Manager", output)

        # Correction 6: the connection string is the one that was specified.
        self.assertIn("WRITE 1", output)
        self.assertIn("WRITE 2", output)
        self.assertIn("VERIFICATION", output)
        # Correction 8: the hand-off to Terraform is stated, not done.
        self.assertIn(mod.SSM_SECRET_ARN, output)
        self.assertIn("Repoint, do not add a second parameter", output)
        # The logging gate printed every value it read.
        self.assertIn("log_statement", output)
        self.assertIn("log_min_duration_statement", output)
        self.assertIn("pgaudit.log", output)

    def test_psql_invocation_keeps_X_and_offers_sql_on_stdin(self):
        """Correction 5/6: `-X`, verify-full, host+hostaddr, and no secret in argv."""
        self.run_script()
        real_argv = self.psql.sql_log  # sanity: the fake did run
        self.assertTrue(real_argv)
        captured_argv = mod.subprocess.run.call_args_list[0].args[0]
        self.assertIn("-X", captured_argv)
        self.assertIn("ON_ERROR_STOP=1", captured_argv)
        conninfo = captured_argv[-1]
        self.assertIn("sslmode=verify-full", conninfo)
        self.assertIn(f"sslrootcert={mod.CA_BUNDLE}", conninfo)
        self.assertIn("hostaddr=127.0.0.1", conninfo)
        self.assertIn("port=15432", conninfo)
        self.assertIn("host=lemondrop-dev.abc.eu-west-1.rds.amazonaws.com", conninfo)
        # The SQL — and therefore the password — is on stdin, never in argv.
        self.assertNotIn("CREATE ROLE", " ".join(captured_argv))


# ══ 2 & 3. PRE-EXISTENCE GATE ══════════════════════════════════════════════════
class TestPreExistenceGate(BootstrapTestCase):
    def test_pre_existing_role_aborts_before_any_write(self):
        self.psql.role_count = "1"
        code, output = self.run_script()

        self.assertEqual(code, 1)
        self.assertIn("PRE-EXISTENCE GATE", output)
        self.assertIn("unknown to this script", output)
        # THE assertion: no secret was created.
        self.secrets.create_secret.assert_not_called()
        self.assertEqual(self.psql.create_role_calls(), [])

    def test_pre_existing_secret_aborts_before_any_write(self):
        self.set_secret_state("live")  # describe succeeds, no DeletedDate
        code, output = self.run_script()

        self.assertEqual(code, 1)
        self.assertIn("PRE-EXISTENCE GATE", output)
        self.assertIn(mod.SECRET_NAME, output)
        self.assertIn("earlier attempt at this procedure", output)
        # THE assertion: CREATE ROLE never reached the database.
        self.assertEqual(self.psql.create_role_calls(), [])
        self.secrets.create_secret.assert_not_called()

    def test_unknown_secret_state_is_not_treated_as_absent(self):
        """An AccessDenied describe must stop the run, not read as 'no secret'."""
        self.secrets.describe_secret.side_effect = Exception("AccessDeniedException")
        self.secrets.describe_secret.response = {"Error": {"Code": "AccessDeniedException"}}
        code, output = self.run_script()

        self.assertEqual(code, 1)
        self.assertIn("could not determine", output)
        self.assertEqual(self.psql.create_role_calls(), [])
        self.secrets.create_secret.assert_not_called()


# ══ 4. create_secret RAISES — NO COMPENSATION ══════════════════════════════════
class TestCreateSecretRaises(BootstrapTestCase):
    def test_create_secret_raises_is_uncertain_and_drops_nothing(self):
        self.secrets.create_secret.side_effect = RuntimeError(
            "An error occurred (InternalFailure) when calling the CreateSecret "
            "operation: connection reset"
        )
        code, output = self.run_script()

        self.assertEqual(code, 1)
        self.assertIn("UNCERTAIN", output)
        # THE regression assertion for correction 4: the procedure never tells the
        # operator to run a DROP ROLE. (The word appears in the surrounding prose,
        # explaining WHY it does not — which is the point of it being there.)
        for line in output.splitlines():
            self.assertFalse(line.strip().startswith("DROP ROLE"), line)
        self.assertEqual(self.psql.sent("DROP"), [], "no DROP statement was issued")
        self.assertEqual(self.psql.sent("ALTER ROLE"), [], "the role was left untouched")
        # The role write DID happen and is reported as the known half.
        self.assertEqual(len(self.psql.create_role_calls()), 1)
        # The reconciliation procedure was printed.
        self.assertIn("RECOVERY", output)
        self.assertIn("describe-secret", output)
        self.assertIn("pg_roles", output)
        self.assertIn("does NOT drop", output)
        # And the AWS error was rendered without its message, which can echo
        # request parameters — one of which is the secret value.
        self.assertIn("RuntimeError", output)
        self.assertNotIn("connection reset", output)


# ══ 5 & 6. LOGGING GATE ════════════════════════════════════════════════════════
class TestLoggingGate(BootstrapTestCase):
    def _assert_refused_before_writes(self, code, output):
        self.assertEqual(code, 1, output)
        self.assertIn("REFUSING", output)
        self.assertEqual(self.psql.create_role_calls(), [], "CREATE ROLE must not be sent")
        self.secrets.create_secret.assert_not_called()

    def test_ddl_refuses_because_ddl_logs_create_role(self):
        self.psql.log_statement = "ddl"
        code, output = self.run_script()
        self._assert_refused_before_writes(code, output)
        self.assertIn("'ddl' logs it exactly as readily as 'all'", output)

    def test_all_refuses(self):
        self.psql.log_statement = "all"
        code, output = self.run_script()
        self._assert_refused_before_writes(code, output)

    def test_none_proceeds(self):
        self.psql.log_statement = "none"
        code, output = self.run_script()
        self.assertEqual(code, 0, output)
        self.assertEqual(len(self.psql.create_role_calls()), 1)

    def test_duration_logging_of_zero_refuses(self):
        """log_min_duration_statement = 0 logs every statement, password included."""
        self.psql.log_min_duration = "0"
        code, output = self.run_script()
        self._assert_refused_before_writes(code, output)
        self.assertIn("log_min_duration_statement", output)

    def test_pgaudit_non_empty_refuses(self):
        self.psql.pgaudit = "ddl, write, read"
        code, output = self.run_script()
        self._assert_refused_before_writes(code, output)
        self.assertIn("pgaudit", output)

    def test_gate_prints_every_value_it_read(self):
        self.psql.log_statement = "none"
        self.psql.log_min_duration = "-1"
        _, output = self.run_script()
        for expected in ("log_statement", "none", "log_min_duration_statement",
                         "-1", "pgaudit.log", "not installed"):
            self.assertIn(expected, output)


# ══ 7. pgaudit ABSENT vs IDLE vs RECORDING vs UNKNOWN ══════════════════════════
class TestPgauditHandling(BootstrapTestCase):
    """pgaudit has three real outcomes and one phantom.

    An installed-but-idle extension (`log = 'none'`) is the SAFE, EXPECTED
    configuration and must not block. Only pgaudit actually RECORDING refuses.
    The phantom is the read that never returned: reporting that as "not
    installed" was the fail-open this class exists to keep fixed.
    """

    def _assert_refused_before_writes(self, code, output):
        self.assertEqual(code, 1, output)
        self.assertIn("REFUSING", output)
        self.assertEqual(self.psql.create_role_calls(), [], "CREATE ROLE must not be sent")
        self.secrets.create_secret.assert_not_called()

    def test_pgaudit_none_proceeds(self):
        """FIX 1 (regression): pgaudit INSTALLED and configured to 'none' is safe."""
        self.psql.pgaudit = "none"
        code, output = self.run_script()

        self.assertEqual(code, 0, output)
        self.assertIn("pgaudit.log                   = none", output)
        self.assertEqual(len(self.psql.create_role_calls()), 1)
        self.secrets.create_secret.assert_called_once()

    def test_pgaudit_ddl_refuses_before_any_write(self):
        """FIX 1: only the RECORDING values block, and they block before writes."""
        self.psql.pgaudit = "ddl"
        code, output = self.run_script()
        self._assert_refused_before_writes(code, output)
        self.assertIn("pgaudit.log is 'ddl'", output)

    def test_pgaudit_query_error_blocks_and_is_not_reported_as_not_installed(self):
        """FIX 2c / required test 4 (regression): a raised read is UNKNOWN.

        The previous behaviour mapped ANY exception to "not installed" and let the
        run proceed — so a dropped tunnel, a permission error and a genuinely
        absent extension were indistinguishable, and two of the three are reasons
        to stop.
        """
        self.psql.pgaudit_raises = True  # the query never returns
        code, output = self.run_script()

        self._assert_refused_before_writes(code, output)
        self.assertIn("pgaudit.log could not be read", output)
        self.assertIn("cannot vouch for", output)
        # THE regression assertion: an unknown read must not be reported as a
        # known-absent extension.
        self.assertNotIn("pgaudit.log                   = not installed", output)
        self.assertNotIn("= not installed", output)

    def test_pgaudit_null_setting_is_treated_as_not_installed(self):
        """Required test 5: an EMPTY result is a real answer — the GUC is absent."""
        self.psql.pgaudit = ""  # current_setting(..., true) returns NULL
        code, output = self.run_script()

        self.assertEqual(code, 0, output)
        self.assertIn("pgaudit.log                   = not installed", output)
        self.assertEqual(len(self.psql.create_role_calls()), 1)
        self.secrets.create_secret.assert_called_once()

    def test_pgaudit_empty_and_none_are_the_only_passing_values(self):
        """The safe set is exactly two values, and 'off' is not one of them."""
        self.assertEqual(set(mod.PGAUDIT_IDLE), {"none", "not installed"})


# ══ FIX 2b. FAIL CLOSED ON AN UNPARSEABLE SETTING ═════════════════════════════
class TestFailClosedLoggingGate(BootstrapTestCase):
    """An unreadable or unparseable logging setting must BLOCK.

    The bug this class is named for: the check read
    `if duration_value is not None and duration_value >= 0`, so
    `_duration_to_ms()` returning None — an unparseable value — was silently
    treated as SAFE. A threshold nobody can parse is not known to be -1.
    """

    def _assert_refused_before_writes(self, code, output):
        self.assertEqual(code, 1, output)
        self.assertIn("REFUSING", output)
        self.assertEqual(self.psql.create_role_calls(), [], "CREATE ROLE must not be sent")
        self.secrets.create_secret.assert_not_called()

    def test_unparseable_duration_refuses(self):
        """Required test 3 — THE regression test for the fail-open bug."""
        self.psql.log_min_duration = "banana"
        code, output = self.run_script()

        self._assert_refused_before_writes(code, output)
        self.assertIn("log_min_duration_statement is 'banana'", output)
        self.assertIn("blocks rather than assumes", output)

    def test_empty_duration_refuses(self):
        """An empty reading is unknown, and unknown blocks — same as unparseable."""
        self.psql.log_min_duration = ""
        code, output = self.run_script()
        self._assert_refused_before_writes(code, output)
        self.assertIn("log_min_duration_statement", output)

    def test_unparseable_duration_never_parses_to_a_safe_number(self):
        """Unit-level: the parser says None, and the CALLER must block on None."""
        self.assertIsNone(mod._duration_to_ms("banana"))
        self.assertIsNone(mod._duration_to_ms(""))
        self.assertIsNone(mod._duration_to_ms("unavailable"))  # legacy sentinel
        # …and the negative control: -1 genuinely parses, and is the safe value.
        self.assertEqual(mod._duration_to_ms("-1"), -1)

    def test_unreadable_log_statement_refuses(self):
        """FIX 2a: the literal 'unavailable' is gone; a failed read is a failure."""
        self.psql.log_statement_raises = True
        code, output = self.run_script()

        self._assert_refused_before_writes(code, output)
        self.assertIn("log_statement could not be read", output)
        self.assertNotIn("= unavailable", output)

    def test_unreadable_duration_refuses(self):
        self.psql.log_min_duration_raises = True
        code, output = self.run_script()

        self._assert_refused_before_writes(code, output)
        self.assertIn("log_min_duration_statement could not be read", output)

    def test_no_reader_can_return_a_string_that_looks_like_a_value(self):
        """`unavailable` must be unreachable as a sentinel in every reader."""
        for reader in (
            lambda: mod._setting("log_statement", label="x"),
            mod._pgaudit_log_setting,
        ):
            read = reader()
            self.assertFalse(read.unreadable, "the fake answers, so this must be readable")
            self.assertNotEqual(read.value, "unavailable")
            self.assertIsInstance(read.unreadable, bool)


# ══ FIX 3. WRITE 1 IS `CREATE ROLE` ONLY ══════════════════════════════════════
class TestCreateRoleIssuesOnlyCreateRole(BootstrapTestCase):
    """Required test 6 — THE regression test for the removed grants.

    `create_role()` used to issue `CREATE ROLE` plus four conditional grants,
    each guarded by a probe query for whether the object existed yet. All of it
    is deferred past the migration now, because a GRANT against an object that
    does not exist fails and a conditional grant would encode an ordering the
    operator's sequence forbids.
    """

    def test_no_grant_of_any_kind_reaches_psql(self):
        code, output = self.run_script()
        self.assertEqual(code, 0, output)

        # THE assertion, on the SQL text actually sent — not on a mock's call
        # count, which would pass even if a GRANT were hidden inside the batch.
        self.assertEqual(self.psql.sent("GRANT"), [], "no GRANT may reach psql")
        for fragment in (
            "USAGE ON SCHEMA",
            "CONNECT ON DATABASE",
            "USAGE ON TYPE",
            "SELECT, INSERT, UPDATE",
            "ALTER DEFAULT PRIVILEGES",
            "OWNER TO",
        ):
            self.assertEqual(self.psql.sent(fragment), [], fragment)

        # …and the probes those grants required are gone too.
        self.assertEqual(self.psql.sent("FROM pg_type"), [])
        self.assertEqual(self.psql.sent("FROM pg_class"), [])

    def test_exactly_one_statement_is_sent_and_it_is_the_create_role(self):
        code, output = self.run_script()
        self.assertEqual(code, 0, output)

        writes = self.psql.create_role_calls()
        self.assertEqual(len(writes), 1, output)
        sql = writes[0]
        self.assertIn(f"CREATE ROLE {mod.ROLE_NAME}", sql)
        self.assertIn("LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE", sql)
        self.assertIn(f"PASSWORD '{GENERATED}'", sql)
        # One statement: a single trailing semicolon and no internal one.
        self.assertEqual(sql.count(";"), 1, sql)

    def test_run_says_grants_were_deferred_and_names_where(self):
        _, output = self.run_script()
        self.assertIn("No grants are issued here", output)
        self.assertIn("apply_deferred_grants", mod.DEFERRED_GRANTS_STEP)
        self.assertIn("NOT IMPLEMENTED", mod.DEFERRED_GRANTS_STEP)
        self.assertIn(mod.DEFERRED_GRANTS_STEP, output)
        # The summary must NOT claim grants were applied.
        self.assertIn("no grants were applied", output)

    def test_summary_does_not_claim_grants_were_applied(self):
        import io as _io, contextlib as _ctx

        out = _io.StringIO()
        with _ctx.redirect_stdout(out):
            mod.summary("arn:aws:secretsmanager:eu-west-1:1:secret:app-x")
        text = out.getvalue()
        self.assertNotIn("applied:", text)
        self.assertIn("NOT DONE, BY DESIGN", text)
        self.assertIn("no access to `documents`", text)


# ══ FIX 4a. SOFT-DELETED SECRETS ══════════════════════════════════════════════
class TestSoftDeletedSecret(BootstrapTestCase):
    """`describe_secret` SUCCEEDS for a soft-deleted secret and returns a
    DeletedDate. An existence check written against the exception alone therefore
    reads it as LIVE — and after the 7-day recovery window the name is free, so
    an operator who deleted the secret and waited could never re-run.
    """

    def test_soft_deleted_secret_is_treated_as_absent_and_says_so(self):
        """Required test 7: absent for the gate's purposes, and REPORTED."""
        self.set_secret_state("deleted")
        code, output = self.run_script()

        self.assertEqual(code, 0, output)
        # Said so, in the gate message, because it is a surprising distinction.
        self.assertIn("SOFT-DELETED", output)
        self.assertIn("treated as ABSENT", output)
        self.assertIn("DeletedDate", output)
        self.assertIn("7-day", output)
        # And the run actually proceeded rather than refusing.
        self.assertEqual(len(self.psql.create_role_calls()), 1)
        self.secrets.create_secret.assert_called_once()

    def test_live_secret_still_refuses(self):
        """Required test 8: DeletedDate absent → pre-existing → refused."""
        self.set_secret_state("live")
        code, output = self.run_script()

        self.assertEqual(code, 1, output)
        self.assertIn("PRE-EXISTENCE GATE", output)
        self.assertIn(mod.SECRET_NAME, output)
        self.assertEqual(self.psql.create_role_calls(), [])
        self.secrets.create_secret.assert_not_called()

    def test_secret_state_classifies_all_three(self):
        for state, expected in (
            ("absent", mod.SECRET_ABSENT),
            ("live", mod.SECRET_LIVE),
            ("deleted", mod.SECRET_SOFT_DELETED),
        ):
            with self.subTest(state=state):
                self.doCleanups()
                self.setUp()
                self.set_secret_state(state)
                self.assertEqual(mod.secret_state(self.secrets), expected)
                self.assertEqual(mod.secret_exists(self.secrets), expected == mod.SECRET_LIVE)


# ══ 8. NO CREDENTIAL LEAKAGE ══════════════════════════════════════════════════
class TestNoCredentialLeakage(BootstrapTestCase):
    """Every failure path, checked for both credentials in combined output."""

    FAILURES = {
        "pre-existing role": lambda t: setattr(t.psql, "role_count", "1"),
        "log_statement=ddl": lambda t: setattr(t.psql, "log_statement", "ddl"),
        "pgaudit non-empty": lambda t: setattr(t.psql, "pgaudit", "ddl"),
        "create_secret raises": lambda t: setattr(
            t.secrets, "create_secret", mock.Mock(side_effect=RuntimeError("boom"))
        ),
        "CREATE ROLE fails at the server": lambda t: setattr(
            t.psql, "fail_on", "CREATE ROLE"
        ),
        "attribute check fails": lambda t: (
            setattr(t.psql, "attrs", "t|f|f|t"), setattr(t.psql, "role_count", "1")
        ),
    }

    def test_no_credential_leakage(self):
        for label, arrange in self.FAILURES.items():
            with self.subTest(failure=label):
                # Tear the previous arrangement down first, so each failure runs
                # against a clean mock stack rather than a mutated one.
                self.doCleanups()
                self.setUp()
                arrange(self)
                code, output = self.run_script()
                self.assertNotIn(GENERATED, output, f"generated password leaked: {label}")
                self.assertNotIn(MASTER_PW, output, f"master password leaked: {label}")
                self.assertEqual(code, 1, f"{label} should have exited non-zero")

    def test_happy_path_also_prints_no_password(self):
        code, output = self.run_script()
        self.assertEqual(code, 0, output)
        self.assertNotIn(GENERATED, output)
        self.assertNotIn(MASTER_PW, output)

    def test_server_stderr_quoting_the_statement_is_withheld(self):
        """A failing CREATE ROLE makes psql echo the statement; it must not print."""
        self.psql.fail_on = "CREATE ROLE"
        _, output = self.run_script()
        self.assertIn("withheld", output)
        self.assertNotIn(GENERATED, output)


# ══ 9. reconcile() RETURNS TEXT ════════════════════════════════════════════════
class TestReconcile(BootstrapTestCase):
    def test_reconcile_returns_text(self):
        text = mod.reconcile()

        self.assertIsInstance(text, str)  # NOT None — correction 2
        self.assertTrue(text.strip())
        self.assertIn(mod.SECRET_NAME, text)      # the secret
        self.assertIn(mod.ROLE_NAME, text)        # the role
        self.assertIn(mod.SSM_SECRET_ARN, text)   # the hand-off
        # Read-only commands only, and the secret is never asked for by value.
        self.assertIn("describe-secret", text)
        for line in text.splitlines():
            if line.strip().startswith("aws secretsmanager"):
                self.assertNotIn("get-secret-value", line)
        # The procedure never PRINTS a DROP ROLE command. (It explains, in prose,
        # why one must not be run — so the absence of the string is not the
        # assertion; the absence of a command line is.)
        for line in text.splitlines():
            self.assertFalse(line.strip().startswith("DROP ROLE"), line)
        # Every one of the four outcomes is spelled out.
        for case in ("secret EXISTS, role EXISTS", "secret EXISTS, role ABSENT",
                     "secret ABSENT, role EXISTS", "NEITHER EXISTS"):
            self.assertIn(case, text)

    def test_reconcile_output_is_usable_as_an_sys_exit_payload(self):
        """The original bug: None concatenated into a sys.exit string → TypeError."""
        text = mod.reconcile()
        payload = f"UNCERTAIN\n{text}"
        self.assertIsInstance(payload, str)

    @staticmethod
    def _branch(text: str, heading: str) -> str:
        """Return the body of one of step 2's outcomes, heading included."""
        lines = text.splitlines()
        start = next(i for i, line in enumerate(lines) if line.strip() == heading)
        body = [lines[start]]
        for line in lines[start + 1:]:
            if line.startswith("   ") and not line.startswith("    ") and line.strip():
                break  # the next outcome heading
            body.append(line)
        return "\n".join(body)

    def test_absent_secret_with_existing_role_does_not_advise_a_bare_rerun(self):
        """Required test 9 (regression): the old advice could not work.

        The procedure used to say "rotate it, then re-run to create the secret".
        Re-running cannot work: the pre-existence gate refuses whenever the role
        exists, so the second run aborts at the same gate having created nothing.
        The reason has to be stated, because "just run it again" is exactly what an
        operator would try.
        """
        text = mod.reconcile()
        branch = self._branch(text, "secret ABSENT, role EXISTS")

        # States WHY a bare re-run cannot work, and names the gate as the reason.
        self.assertIn("RE-RUNNING ALONE CANNOT FIX THIS", branch)
        self.assertIn("The pre-existence gate refuses whenever", branch)
        self.assertIn("aborts at exactly the same gate", branch)

        # Offers paths that DO work: drop the role yourself, or make the secret by
        # hand from a rotated value.
        self.assertIn("DROP ROLE", branch)
        self.assertIn("Drop the role yourself", branch)
        self.assertIn("create-secret", branch)
        self.assertIn("BY HAND", branch)
        self.assertIn("ALTER ROLE", branch)

        # And no bare "just re-run" survives anywhere in the branch. Every line
        # mentioning a re-run either forbids it or attaches a precondition to it.
        for line in branch.splitlines():
            if "re-run" in line.lower():
                self.assertNotRegex(
                    line.strip(),
                    r"^(and |then |so )?re-run\b( to| this|$)",
                    f"bare re-run advice: {line!r}",
                )

        # A real DROP ROLE command is offered, but as a psql invocation — never as
        # a bare statement line, and never by this script.
        drop_lines = [ln for ln in branch.splitlines() if "DROP ROLE" in ln]
        self.assertTrue(drop_lines)
        for line in drop_lines:
            if line.strip().startswith("DROP ROLE"):
                self.fail(f"DROP ROLE offered as a bare command line: {line!r}")

    def test_describe_query_is_valid_jmespath_after_interpolation(self):
        """FIX 4c: braces must render, and the projection must include DeletedDate.

        The command is built with an f-string, where `{{` emits a literal `{`. A
        query that renders as `Secret.{{…}}` is rejected by the CLI at the
        operator's shell — long after this script exits — and a projection missing
        DeletedDate leaves them unable to tell a live secret from a soft-deleted
        one without a second call.
        """
        text = mod.reconcile()
        line = next(ln for ln in text.splitlines() if "describe-secret" in ln)

        # Rendered, not source: no doubled braces survived interpolation.
        self.assertNotIn("{{", line)
        self.assertNotIn("}}", line)
        self.assertIn("--query 'Secret.{", line)
        self.assertIn("DeletedDate:DeletedDate", line)
        self.assertIn("Name:Name", line)
        # Exactly one balanced projection.
        self.assertEqual(line.count("{"), 1)
        self.assertEqual(line.count("}"), 1)

        expression = line.split("--query '", 1)[1].rsplit("'", 1)[0]
        try:
            import jmespath  # noqa: PLC0415 — optional dependency
        except ImportError:  # pragma: no cover — environment-dependent
            self.skipTest("jmespath is not installed; structural checks still ran")
        else:
            # Compiles as the AWS CLI's own parser would compile it, and selects
            # exactly the four fields — DeletedDate included, so one call is
            # enough to tell a live secret from a soft-deleted one.
            compiled = jmespath.compile(expression)
            self.assertEqual(
                sorted(compiled.search({"Secret": {}})),
                ["ARN", "CreatedDate", "DeletedDate", "Name"],
            )

    def test_the_procedure_prints_deleted_date_guidance(self):
        """One describe call must be enough to pick a branch."""
        text = mod.reconcile()
        self.assertIn("DeletedDate", text)
        self.assertIn("SOFT-DELETED", text)
        self.assertIn("treats as ABSENT", text)


# ══ THE ADDITIONAL FIX: the attribute check compares the right string ═════════
class TestAttributeCheck(BootstrapTestCase):
    def test_role_attribute_mismatch_reports_raw_value(self):
        self.psql.attrs = "t|f|f|t"  # rolcreaterole is wrongly true
        code, output = self.run_script()

        self.assertEqual(code, 1)
        # The raw value is printed so a mismatch is diagnosable.
        self.assertIn("'t|f|f|t'", output)
        self.assertIn("'t|f|f|f'", output)
        self.assertIn("not the one this run created", output)

    def test_correct_attributes_are_not_reported_as_a_failure(self):
        """Regression: a `|`-stripped comparison failed on a correct role."""
        self.psql.attrs = "t|f|f|f"
        code, output = self.run_script()
        self.assertEqual(code, 0, output)
        self.assertNotIn("STOPPED", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)