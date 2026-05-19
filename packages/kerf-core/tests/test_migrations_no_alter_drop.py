"""Pin: consolidated migration files must contain no ALTER TABLE / DROP TABLE shims.

Contract: DBs are always reset on deploy (loop_dev.sh / loop_main.sh drop the
public schema before re-applying migrations).  Every column must live in its
originating CREATE TABLE block — ALTER-ADD-COLUMN shims are unreachable and
mislead readers about the authoritative schema definition.

Regex mirrors the acceptance gate in T-307 (grep -nE pattern on ^\\s* prefix).
"""

import pathlib
import re

_MIGRATIONS_DIR = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src/kerf_core/db/migrations"
)

_FORBIDDEN = re.compile(
    r"^\s*(alter\s+table|drop\s+table|drop\s+column|drop\s+index|drop\s+constraint)",
    re.IGNORECASE,
)


def test_no_alter_or_drop_in_migrations():
    """Each consolidated migration file must have zero ALTER/DROP shims."""
    offending: list[str] = []

    for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        for lineno, line in enumerate(sql_file.read_text().splitlines(), start=1):
            if _FORBIDDEN.match(line):
                offending.append(f"{sql_file.name}:{lineno}: {line.rstrip()}")

    assert not offending, (
        "Found forbidden ALTER TABLE / DROP TABLE shims in migration files.\n"
        "Fold each column/constraint into the originating CREATE TABLE block.\n\n"
        + "\n".join(offending)
    )
