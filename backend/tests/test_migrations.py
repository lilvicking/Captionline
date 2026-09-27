"""Alembic migration invariants.

The production database was created by `alembic init`, which declares
`alembic_version.version_num` as `VARCHAR(32)`. That column is never widened
here, because widening a live column is a larger and riskier change than
keeping revision identifiers short. Instead this module asserts the invariant
that makes the chain safe to deploy: **every** revision identifier and every
`down_revision` reference must fit in 32 characters.

This is a cheap, static check that runs on every test invocation, so a long
identifier is caught in CI rather than at deploy time.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"

#: The width of `alembic_version.version_num` on the production PostgreSQL
#: database, as created by `alembic init`.
ALEMBIC_VERSION_COLUMN_LENGTH = 32

_MIGRATION_FILES = sorted(VERSIONS_DIR.glob("*.py"))


def _string_literal(source: str, name: str) -> str | None:
    """Read a module-level `name: str = "value"` assignment without importing it.

    Parsing instead of importing keeps the check independent of whether the
    module's own imports happen to be satisfied, and it cannot execute anything.
    """
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        target = node.target
        if isinstance(target, ast.Name) and target.id == name:
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
            return None
    return None


def _load(path: Path) -> tuple[str, str | None]:
    source = path.read_text(encoding="utf-8")
    revision = _string_literal(source, "revision")
    assert revision is not None, f"{path.name} does not define a string `revision`"
    return revision, _string_literal(source, "down_revision")


def _by_revision() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in _MIGRATION_FILES:
        revision, _ = _load(path)
        result[revision] = path
    return result


def test_migration_files_are_discovered():
    """Guard against this module silently testing nothing."""
    assert len(_MIGRATION_FILES) >= 5, (
        f"expected the full migration chain in {VERSIONS_DIR}, "
        f"found {len(_MIGRATION_FILES)}: {[p.name for p in _MIGRATION_FILES]}"
    )


@pytest.mark.parametrize("path", _MIGRATION_FILES, ids=lambda p: p.name)
def test_revision_identifier_fits_the_alembic_version_column(path: Path):
    """A revision id longer than the column breaks the deploy at runtime.

    Production failed exactly this way: `StringDataRightTruncation` while
    writing `0004_account_deletion_and_consent` (33 chars) into VARCHAR(32).
    """
    revision, _ = _load(path)

    assert len(revision) <= ALEMBIC_VERSION_COLUMN_LENGTH, (
        f"{path.name}: revision {revision!r} is {len(revision)} characters, "
        f"but alembic_version.version_num is VARCHAR({ALEMBIC_VERSION_COLUMN_LENGTH}). "
        "Rename the revision before it is applied in production."
    )


@pytest.mark.parametrize("path", _MIGRATION_FILES, ids=lambda p: p.name)
def test_down_revision_reference_fits_the_column(path: Path):
    """A `down_revision` is written into the same column, so it must also fit."""
    _, down_revision = _load(path)

    if down_revision is None:
        return  # the base revision legitimately has no parent

    assert len(down_revision) <= ALEMBIC_VERSION_COLUMN_LENGTH, (
        f"{path.name}: down_revision {down_revision!r} is {len(down_revision)} "
        f"characters, which does not fit "
        f"VARCHAR({ALEMBIC_VERSION_COLUMN_LENGTH})."
    )


def test_chain_is_linear_and_unambiguous():
    """Exactly one base revision and one head, with no branches or cycles."""
    revisions: dict[str, str | None] = {}
    for path in _MIGRATION_FILES:
        revision, down_revision = _load(path)
        assert revision not in revisions, f"duplicate revision id {revision!r}"
        revisions[revision] = down_revision

    bases = [rev for rev, down in revisions.items() if down is None]
    assert len(bases) == 1, f"expected exactly one base revision, found {bases}"

    targets = [down for down in revisions.values() if down is not None]
    assert len(targets) == len(set(targets)), "two revisions point at the same parent (a branch)"

    for revision, down_revision in revisions.items():
        if down_revision is not None:
            assert down_revision in revisions, (
                f"{revision!r} revises unknown {down_revision!r}"
            )


def test_every_parent_reference_resolves_and_chain_reaches_the_base():
    """Walk from the head back to the base to prove the chain is walkable."""
    revisions: dict[str, str | None] = {}
    for path in _MIGRATION_FILES:
        revision, down_revision = _load(path)
        revisions[revision] = down_revision

    heads = [rev for rev, down in revisions.items() if rev not in set(revisions.values())]
    assert len(heads) == 1, f"expected exactly one head, found {sorted(heads)}"

    seen: set[str] = set()
    cursor: str | None = heads[0]
    while cursor is not None:
        assert cursor not in seen, f"cycle detected at {cursor!r}"
        seen.add(cursor)
        cursor = revisions[cursor]

    assert len(seen) == len(revisions), "some revisions are unreachable from the head"


def test_no_stale_long_deletion_and_consent_reference_remains():
    """The 33-character identifier must not survive as a live reference.

    Only actual identifier references and the `Revision ID:` / `Revises:`
    docstring headers are checked. A prose comment is allowed to name the old
    value, because the migration deliberately documents why it was renamed.
    """
    stale = "0004_account_deletion_and_consent"

    for path in _MIGRATION_FILES:
        revision, down_revision = _load(path)
        assert stale not in revision, f"{path.name} still declares the old revision id"
        if down_revision is not None:
            assert stale not in down_revision, f"{path.name} still revises the old id"

        # Strip comments before scanning the docstring headers, so the
        # explanatory note about the failed deploy is not mistaken for a link.
        source = "\n".join(
            line for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        for header in re.findall(r"^(?:Revision ID|Revises):\s*(\S+)", source, re.M):
            assert stale not in header, (
                f"{path.name} still names the old id in its docstring header: {header!r}"
            )


def test_expected_head_after_this_hotfix():
    """Pin the chain head so a rename is a deliberate, visible change."""
    revisions = {revision for revision, _ in ((_load(p)[0], None) for p in _MIGRATION_FILES)}
    assert "0004_account_consent" in revisions
    assert "0005_rate_limit_buckets" in revisions


def test_every_revision_id_writes_into_a_32_character_column():
    """Reproduce the production failure mode against a length-constrained column.

    There is no local PostgreSQL here, so this stands in for one: a column that
    accepts at most 32 characters, which is what `alembic init` creates for
    `alembic_version.version_num`. Writing every identifier through it proves the
    chain can actually be applied where it failed before.
    """
    import sqlite3

    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE alembic_version ("
            "  version_num VARCHAR(32) NOT NULL,"
            "  CHECK (length(version_num) <= 32)"
            ")"
        )

        for path in _MIGRATION_FILES:
            revision, _ = _load(path)
            try:
                connection.execute(
                    "INSERT INTO alembic_version (version_num) VALUES (?)", (revision,)
                )
            except sqlite3.Error as exc:  # pragma: no cover - only on regression
                pytest.fail(
                    f"{path.name}: revision {revision!r} ({len(revision)} chars) "
                    f"does not fit VARCHAR(32): {exc}"
                )

        stored = [
            row[0]
            for row in connection.execute("SELECT version_num FROM alembic_version")
        ]
        assert len(stored) == len(_MIGRATION_FILES)
    finally:
        connection.close()


def test_the_original_33_character_identifier_is_what_would_have_failed():
    """Guard the regression: the old id must genuinely exceed the column.

    If this ever stopped failing, the test above would no longer be proving
    anything, because the constraint would be vacuous.
    """
    import sqlite3

    stale = "0004_account_deletion_and_consent"
    assert len(stale) == 33

    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE alembic_version ("
            "  version_num VARCHAR(32) NOT NULL,"
            "  CHECK (length(version_num) <= 32)"
            ")"
        )
        with pytest.raises(sqlite3.Error):
            connection.execute(
                "INSERT INTO alembic_version (version_num) VALUES (?)", (stale,)
            )
    finally:
        connection.close()


def test_revision_file_name_matches_its_identifier():
    """A filename that disagrees with the revision is a trap for the next reader.

    Alembic uses the `revision` value, not the filename, so a mismatch would work
    while being confusing; this keeps the two aligned.
    """
    for path in _MIGRATION_FILES:
        revision, _ = _load(path)
        stem = path.stem
        assert stem == revision, (
            f"{path.name} declares revision {revision!r}; rename the file to match"
        )
