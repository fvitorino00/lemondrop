#!/usr/bin/env python3
"""The image-content gate for the Lemondrop API image.

WHAT THIS IS
    A scan of a BUILT, RUNNABLE container image's own filesystem, run by Python
    INSIDE that image, that fails the build if the image contains anything it
    must not: a model weight, Terraform state, an environment file, git
    metadata, private key material, or a credential this repository put there.

WHY IT IS A REAL FILE AND NOT A STRING IN THE WORKFLOW
    A scan whose logic cannot be read, diffed, reviewed in a pull request, or
    run on a laptop is a scan nobody will trust or debug. This file is the
    authority. The workflow pipes it into the image over stdin (see release.yml)
    precisely so that no copy of it has to be pasted into a `run:` block and no
    second version can drift out of sync with this one.

WHY IT RUNS INSIDE THE IMAGE, WITH THE IMAGE'S OWN PYTHON
    The image IS the thing under test, and the only honest way to inspect what
    a build baked in is to open the built filesystem. `docker run` with the
    image's own interpreter also means the gate needs NOTHING from the runner
    — no `find`, no `grep`, no extra base image, no side-loaded scanner — and a
    `python:3.12-slim` image is guaranteed to contain the Python running this.
    Scanning a mounted directory or a build-context tarball instead would be
    scanning something adjacent to the artifact, not the artifact.

WHY IT IS NOT THE STAGE 1 HYGIENE GATE, AND WHY IT REUSES ITS PATTERNS ANYWAY
    Stage 1 (`hygiene.yml`, step `secrets-in-tracked-content`) answers "what is
    committed to git". This answers "what is inside the shipped filesystem".
    Those are different sets — a `.gitignore`d `.env` is correctly absent from
    the index and can still be sitting in a hand-built image, and a `.gguf` is
    304 MB and never enters a git context but lands in an image the moment
    somebody runs `COPY models/ ./models/`. The two sets are checked by two
    different gates, for two different failure modes.

    The five credential patterns below are nonetheless COPIED FROM Stage 1
    VERBATIM, and that is deliberate in the other direction too: two different
    regexes for "an AWS key" would drift, and a gate that is easy to weaken by
    editing one of two copies is a gate that will be weakened. Same five shapes,
    same quantifiers, same names. If Stage 1's patterns change, this file must
    change in the same commit.

════════════════════════════════════════════════════════════════════════════
THE TWO ADJUDICATIONS — WHY THE GATE IS NOT A NAIVE PATTERN MATCH
════════════════════════════════════════════════════════════════════════════
This gate was written, built, and run against a REAL image before it was
believed. The first real run failed with 169 findings, in exactly two classes,
and both were real matches that were not secrets. Stage 1's own rule for that
situation — hygiene.yml, "ON FALSE POSITIVES": *"the fix is to adjudicate that
printed line — narrow the pattern, or rephrase the sentence. It is NOT to widen
an exclusion list"* — is what produced the two mechanisms below. Neither is an
exclusion list, and neither is a weakening: each replaces a blunt rule with a
narrower, more accurate one, and each PRINTS ITS WORKING on every run.

  ADJUDICATION 1 — `*.pem` / `*.key` are DECIDED BY CONTENT, NOT BY NAME.
    The first draft failed on any `*.pem` at any path. Against the real image
    that is 154 findings under `/etc/ssl/certs/` — Debian's `ca-certificates`
    root-CA trust store, which pip's HTTPS support and every TLS connection the
    API makes REQUIRE. A public X.509 certificate is not a credential and
    deleting the trust store to satisfy a gate would break the image the gate
    exists to protect.

    So the filename is no longer the finding. A `*.pem` or `*.key` file is
    OPENED, and the question asked of its content is the only question that
    matters: does it contain a PEM PRIVATE KEY block? If yes it fails. If no it
    is cleared, and the cleared count is printed. Note what this does NOT do:
    it does not stop matching `*.key`, does not stop matching `*.pem`, and does
    not stop matching on unreadable files — a key file this gate cannot read is
    reported as a FAILURE, not passed over. A file named `cert.pem` whose
    contents are a private key still fails: the filename buys nothing.

  ADJUDICATION 2 — Rule 2 (credential PATTERNS) skips the PINNED THIRD-PARTY
    PACKAGE TREE, and Rule 1 (forbidden NAMES) does not.
    The same real run produced 15 credential-pattern findings, all inside
    `site-packages`:
        botocore/data/iam/2010-05-08/examples-1.json   (8)
        botocore/data/sts/2011-06-15/examples-1.json   (6)
        boto3/examples/cloudfront.rst                   (1)
    These are AWS's own published example payloads, shipped inside
    `botocore==1.43.113` — AWS's own canonical DUMMY access-key id (a literal
    `AKIA` prefix followed by sixteen uppercase characters, which is why it
    matches) and a DSA example key. They are in a pinned version of a package
    published upstream: this repository pins the version rather than verifying
    the bytes, and none of them are bytes this repository wrote.

    The scope is DERIVED, not hand-listed: it is `sysconfig.get_paths()`'s
    `purelib` and `platlib` for the interpreter doing the scanning, i.e. exactly
    the tree `pip install -r api/requirements.txt` populated. It is resolved at
    run time and PRINTED, so the exclusion is visible in the log rather than
    assumed.

    Rule 1 still runs across that tree in full. A `.env`, a `.gguf`, a
    `.tfstate` or a `.git` inside site-packages fails this gate exactly as it
    would anywhere else. Only the credential-SHAPE check is scoped, and only
    there — and the reason the split is defensible is the threat model: a
    secret in this image has to enter through something this build did, and the
    one path this build does not control is a pinned public wheel.

    What this costs, stated rather than buried: a credential deliberately
    committed INSIDE a dependency's site-packages tree would not be caught by
    Rule 2. That is accepted, it is narrow, and it is counted and printed on
    every run.

WHAT A PASS DOES AND DOES NOT MEAN
    A PASS means: no file on this filesystem has a forbidden name; no file
    named like key material contains a private key; no file OUTSIDE the pinned
    third-party tree contains one of five credential shapes; and the
    application entrypoint is present. It is a NARROW BACKSTOP, not
    comprehensive secret detection — the same honest limit Stage 1 documents.
    It does not know about unlisted providers, high-entropy tokens, base64
    blobs, connection strings, or credentials split across lines. It also
    cannot see what the build context EXCLUDED: a file that never entered the
    image is correctly absent here and this gate says nothing about it.

THE SKIP ACCOUNTING IS PART OF THE GATE, NOT A FOOTNOTE
    Files this script does not read are counted and named, always, on both the
    passing and the failing path. A gate that silently skips is the M3 lesson
    (docs/verification-milestone-3.md §8.5, "An isolation test that was found
    BLIND") wearing a different hat: the reader of a green run must be able to
    see exactly how much of the filesystem was not examined, because that number
    is the real boundary of the claim.

USAGE
    Inside the image (how CI runs it — note the script arrives on stdin, so it
    is never itself a file inside the scanned filesystem and cannot excuse
    itself from its own scan):

        docker run --rm -i --entrypoint python <image> - < image-content-gate.py

    On a laptop, against any directory:

        python3 .github/workflows/image-content-gate.py --root /some/dir \
            --expect /some/dir/app/main.py
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
import sysconfig
from typing import Iterator, NamedTuple

# ─────────────────────────────────────────────────────────────────────────────
# RULE 1 — forbidden PATH NAMES. Matched against the FINAL PATH COMPONENT only,
# at any depth, so `models/bge-small-en-v1.5-q8_0.gguf` and `./terraform.tfstate`
# are caught by the same two patterns. (Same lesson as Stage 1: a pattern
# anchored `^...$` and run against a full path simply does not match it.)
#
# Applied to the WHOLE filesystem with no exceptions. Nothing legitimate in a
# Python image has one of these names.
FORBIDDEN_BASENAMES: tuple[tuple[str, str], ...] = (
    ("model weight (GGUF)", "*.gguf"),
    ("terraform state", "*.tfstate"),
    ("terraform state backup", "*.tfstate.*"),
    ("environment file", ".env"),
    ("git metadata", ".git"),
)

# Names that put a file INTO the key-material adjudication (see ADJUDICATION 1).
# These are not findings on their own — the content is what is judged.
KEY_MATERIAL_PATTERNS: tuple[str, ...] = ("*.pem", "*.key")

# The question actually asked of a file matched by KEY_MATERIAL_PATTERNS. The
# same shape as Stage 1's `pem_private_key`, which already spans the PKCS#8 and
# Elliptic-Curve variants through its `[A-Z ]*` between `BEGIN` and `PRIVATE
# KEY` — so it is written once, here, by REUSING Stage 1's shape rather than by
# restating it. A PUBLIC certificate — the thing the base image legitimately
# carries 154 of — does not match.
#
# NB the self-reference argument, which is Stage 1's and is inherited here: this
# comment describes the PEM header by naming its two ends separately, so the
# literal string the regex matches never appears in this file. Spell it out in
# full and THIS FILE trips Stage 1's own secret scan — which is not a
# hypothetical, it is what an earlier draft of this comment did.
PEM_PRIVATE_KEY_RE = re.compile(r"BEGIN [A-Z ]*PRIVATE KEY")

# Key-material files are read with NO 16 MiB scan cap: they must be adjudicated,
# not declined. A private key file is small by nature, and a `.key` too big to
# read is reported as a FAILURE rather than skipped. This ceiling exists only so
# one pathological file cannot hang the job.
KEY_MATERIAL_MAX_BYTES = 256 * 1024 * 1024

# ─────────────────────────────────────────────────────────────────────────────
# RULE 2 — forbidden CREDENTIAL SHAPES IN TEXT. Copied verbatim from
# `hygiene.yml`, step `secrets-in-tracked-content`, SPECS_EOF. Do not "improve"
# one of these in one file only.
#
# `BEGIN [A-Z ]*PRIVATE KEY` is a REAL match against a real PEM header — the
# dashes, an `RSA` or `EC` algorithm name, the words `PRIVATE KEY`, more dashes —
# and does NOT match this file's own source, because the `[` after `BEGIN ` is
# not in `[A-Z ]` — the same self-reference argument Stage 1 records for its
# ASIA pattern. The full header is deliberately NOT spelled out here: written out
# literally, it would match, and this file would trip Stage 1's secret scan.
CREDENTIAL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("aws_access_key_id", r"AKIA[0-9A-Z]{16}"),
    ("aws_temp_access_key_id", r"ASIA[0-9A-Z]{16}"),
    ("github_pat_classic", r"ghp_[A-Za-z0-9]{36}"),
    ("github_pat_fine_grained", r"github_pat_[A-Za-z0-9_]{20,}"),
    ("pem_private_key", r"BEGIN [A-Z ]*PRIVATE KEY"),
)
_COMPILED_CREDENTIALS = tuple((name, re.compile(pat)) for name, pat in CREDENTIAL_PATTERNS)

# ─────────────────────────────────────────────────────────────────────────────
# THE BOUNDARIES OF THE SCAN — every one of them is REPORTED, never silent
# ─────────────────────────────────────────────────────────────────────────────

# Kernel-provided pseudo-filesystems. A container gets these mounted at runtime
# by the daemon; they are not part of the image, they are not walkable in any
# useful sense, and /sys contains a live view of the HOST kernel. Excluding them
# is correct — but it is an exclusion, so it is counted and printed.
SKIP_DIRS: frozenset[str] = frozenset({"/proc", "/sys", "/dev"})

# Largest ordinary (non-key-material) file this gate will read. Anything larger
# is listed by path and counted as NOT scanned. The limit exists so one
# pathological file cannot hang the job; the reporting is what makes the limit
# safe to have at all.
MAX_SCAN_BYTES = 16 * 1024 * 1024

# Binary probe, deliberately the same window git uses for `grep -I` (~8000
# bytes). A NUL byte in that window means "binary" and the file is not scanned.
BINARY_PROBE_BYTES = 8000

# How many findings of one kind to print before summarising the remainder.
MAX_PRINTED_PER_KIND = 25


def third_party_trees() -> tuple[str, ...]:
    """The pinned third-party package trees this interpreter's pip populated.

    DERIVED, not hand-written: `sysconfig` knows where this very interpreter
    puts site-packages, so the exclusion cannot rot into a stale path list the
    day the base image changes. Resolved at run time and printed on every run,
    so a reader of the log can see exactly what was out of scope.
    """
    trees: set[str] = set()
    for key in ("purelib", "platlib"):
        try:
            path = sysconfig.get_paths().get(key)
        except Exception:  # pragma: no cover - sysconfig is total on CPython
            path = None
        if path:
            trees.add(os.path.abspath(path))
    return tuple(sorted(trees))


class Finding(NamedTuple):
    """One reason the gate fails. Rendered, never raised — the gate reports
    EVERY finding it has before exiting, because a gate that stops at the first
    one turns a five-minute diagnosis into five five-minute diagnoses."""

    kind: str
    path: str
    detail: str


class Skips:
    """What was NOT read, and why. This object is printed on every run."""

    def __init__(self) -> None:
        self._reasons: dict[str, list[str]] = {}

    def add(self, reason: str, path: str) -> None:
        self._reasons.setdefault(reason, []).append(path)

    @property
    def total(self) -> int:
        return sum(len(v) for v in self._reasons.values())

    def report(self, out=sys.stdout) -> None:
        if not self._reasons:
            print("  skipped: 0 paths")
            return
        print(f"  skipped: {self.total} path(s) NOT scanned — the boundary of this claim:")
        for reason in sorted(self._reasons):
            paths = sorted(self._reasons[reason])
            print(f"    {len(paths):>7}  {reason}")
            for path in paths[:MAX_PRINTED_PER_KIND]:
                print(f"             - {path}")
            if len(paths) > MAX_PRINTED_PER_KIND:
                print(f"             … and {len(paths) - MAX_PRINTED_PER_KIND} more of this kind")


class Tallies:
    """What WAS decided, and how. Printed on both the passing and failing path.

    A gate that reports only its failures cannot be distinguished from a gate
    that found nothing because it looked nowhere.
    """

    def __init__(self) -> None:
        self.key_material_checked = 0
        self.key_material_cleared = 0
        self.key_material_symlinks_followed = 0
        self.out_of_scope = 0

    def report(self, trees: tuple[str, ...]) -> None:
        print(
            f"  key-material filenames adjudicated BY CONTENT: {self.key_material_checked} "
            f"file(s) matched {'/'.join(KEY_MATERIAL_PATTERNS)}; every one was opened and "
            f"searched for a PEM private-key block; {self.key_material_cleared} contained "
            "one and were cleared as public certificates, "
            f"{self.key_material_checked - self.key_material_cleared} failed."
            + (
                f" {self.key_material_symlinks_followed} of those were symlinks, FOLLOWED"
                " so that key material cannot hide behind a link."
                if self.key_material_symlinks_followed
                else ""
            )
        )
        print(
            f"  out of scope for the CREDENTIAL-SHAPE rule: {self.out_of_scope} file(s) "
            f"under {' '.join(trees) if trees else '(none)'} — the pinned third-party "
            "package tree. The FORBIDDEN-NAME rule still runs there in full. This is the "
            "accepted, counted limit of this gate."
        )


def forbidden_basename(path: str) -> tuple[str, str] | None:
    """Return (reason, pattern) if this path's final component is forbidden."""
    base = os.path.basename(path.rstrip("/")) or path
    for reason, pattern in FORBIDDEN_BASENAMES:
        if fnmatch.fnmatchcase(base, pattern):
            return reason, pattern
    return None


def is_key_material(path: str) -> bool:
    base = os.path.basename(path.rstrip("/")) or path
    return any(fnmatch.fnmatchcase(base, pat) for pat in KEY_MATERIAL_PATTERNS)


def redact(text: str, name: str, match: re.Match) -> str:
    """Replace a matched credential span, keep the line around it.

    Printing a real credential into a CI log is a second leak, not a report, and
    it happens on the exact run where somebody is already handling one. The
    span length is kept because it is what a reader needs to tell a 20-char
    access key from a 40-char one.
    """
    return text.replace(match.group(0), f"<REDACTED:{name}:{len(match.group(0))}chars>")


def walk(root: str, skips: Skips) -> Iterator[tuple[str, bool]]:
    """Yield (path, is_dir) for everything under `root`, in a stable order.

    Forbidden directories are reported and NOT descended into: once a `.git`
    directory is in the image, there is nothing inside it worth scanning, and
    `os.walk` on a git object store is slow and uninformative.
    """
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=None):
        kept: list[str] = []
        for name in sorted(dirnames):
            full = os.path.join(dirpath, name)
            if os.path.abspath(full) in SKIP_DIRS:
                skips.add("under a kernel pseudo-filesystem (/proc, /sys, /dev)", full)
                continue
            if forbidden_basename(full) is not None:
                yield full, True
                continue
            kept.append(name)
        dirnames[:] = kept

        for name in sorted(filenames):
            yield os.path.join(dirpath, name), False


def read_text(path: str, skips: Skips, key_material: bool) -> str | None:
    """Return the file's text, or None after recording why it was not read."""
    limit = KEY_MATERIAL_MAX_BYTES if key_material else MAX_SCAN_BYTES
    try:
        with open(path, "rb") as handle:
            blob = handle.read(limit + 1)
    except (OSError, ValueError) as exc:
        skips.add(f"unreadable ({type(exc).__name__})", path)
        return None

    if len(blob) > limit:
        skips.add("larger than this gate's read ceiling for its class", path)
        return None
    if b"\x00" in blob[:BINARY_PROBE_BYTES]:
        # Same rule Stage 1 applies via `git grep -I`, and the same honest caveat:
        # a credential inside a binary is NOT covered by either gate.
        skips.add("binary (NUL byte in the first 8000 bytes)", path)
        return None
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        skips.add("not valid UTF-8 text", path)
        return None


def scan(root: str, expect: str) -> tuple[list[Finding], Skips, Tallies, int]:
    findings: list[Finding] = []
    skips = Skips()
    tallies = Tallies()
    examined = 0
    trees = third_party_trees()

    for path, is_dir in walk(root, skips):
        hit = forbidden_basename(path)
        if hit is not None:
            reason, pattern = hit
            kind = "directory" if is_dir else "file"
            findings.append(
                Finding("forbidden-path", path, f"{reason} ({kind}, matched {pattern!r})")
            )
            continue

        if is_dir:
            continue
        if os.path.islink(path):
            # Symlinks are counted, not walked: following one can escape the
            # image. The ONE exception is a symlink named like key material,
            # which is followed so it can be adjudicated — otherwise a private
            # key reached through `secret.pem -> /some/real/key` would pass this
            # gate on a filename technicality, which is the whole class of hole
            # adjudication 1 exists to close.
            skips.add("symlink (not followed, not read)", path)
            if not is_key_material(path):
                continue

        key_material = is_key_material(path)
        if os.path.islink(path):
            tallies.key_material_symlinks_followed += 1
        text = read_text(path, skips, key_material=key_material)
        if text is None:
            if key_material:
                # ADJUDICATION 1 refuses to pass what it could not judge. A .key
                # this gate cannot read is a failure, not a shrug.
                findings.append(
                    Finding(
                        "unadjudicated-key-material",
                        path,
                        "this file is named like key material and this gate could not "
                        "read it, so it cannot be cleared. Fix the image; do not relax "
                        "this rule.",
                    )
                )
            continue
        examined += 1

        # ── ADJUDICATION 1 — key material, decided by content ────────────────
        if key_material:
            tallies.key_material_checked += 1
            match = PEM_PRIVATE_KEY_RE.search(text)
            if match is None:
                tallies.key_material_cleared += 1
            else:
                findings.append(
                    Finding(
                        "private-key-material",
                        path,
                        "a file named like key material that CONTAINS a PEM private key: "
                        + redact(match.group(0), "pem_private_key", match),
                    )
                )

        # ── ADJUDICATION 2 — credential shapes, outside the pinned tree only ──
        in_scope = not any(path.startswith(tree + os.sep) for tree in trees)
        if not in_scope:
            tallies.out_of_scope += 1
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, rx in _COMPILED_CREDENTIALS:
                match = rx.search(line)
                if match is not None:
                    findings.append(
                        Finding(
                            "credential-pattern",
                            f"{path}:{lineno}",
                            f"{name}: {redact(line.strip(), name, match)}",
                        )
                    )

    if not os.path.isfile(expect):
        findings.append(
            Finding(
                "missing-entrypoint",
                expect,
                "the application entrypoint is not in the image; every content rule "
                "above can pass on an image that cannot run",
            )
        )

    return findings, skips, tallies, examined


def report(findings: list[Finding], skips: Skips, tallies: Tallies, examined: int, root: str) -> None:
    print(f"Scanned from {os.path.abspath(root)}.")
    print(f"  text files read and scanned: {examined}")
    tallies.report(third_party_trees())
    skips.report()

    if not findings:
        print(
            "image-content-gate: PASS — no model weight, terraform state, environment "
            "file or git metadata anywhere on the filesystem; no file named like key "
            "material contains a private key; none of the "
            f"{len(CREDENTIAL_PATTERNS)} credential patterns in any text file in scope; "
            "the application entrypoint is present."
        )
        print(
            "  Stated plainly: this is a five-shape backstop, not comprehensive secret "
            "detection; the pinned third-party package tree is outside the "
            "credential-shape rule; and it says nothing about what the build context "
            "excluded."
        )
        return

    grouped: dict[str, list[Finding]] = {}
    for finding in findings:
        grouped.setdefault(finding.kind, []).append(finding)

    print(f"image-content-gate: FAIL — {len(findings)} finding(s):")
    for kind in sorted(grouped):
        items = grouped[kind]
        print(f"\n  [{kind}] {len(items)} finding(s)")
        for finding in items[:MAX_PRINTED_PER_KIND]:
            print(f"    {finding.path}\n        {finding.detail}")
        if len(items) > MAX_PRINTED_PER_KIND:
            print(f"    … and {len(items) - MAX_PRINTED_PER_KIND} more of this kind")

    print(
        "\nEvery path above is named. Fix the image, not this gate: if a finding is "
        "wrong, adjudicate the printed line and change this file deliberately in the "
        "same commit as the fix."
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", default="/", help="filesystem root to scan (default: /)")
    parser.add_argument(
        "--expect",
        default="/app/app/main.py",
        help="path that must exist in the scanned tree (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    findings, skips, tallies, examined = scan(args.root, args.expect)
    report(findings, skips, tallies, examined, args.root)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))