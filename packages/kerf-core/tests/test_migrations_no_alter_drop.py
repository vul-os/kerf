"""Pin: migrations may not DROP, and may only ALTER in the one guarded form.

This file used to ban ALTER outright, on the stated contract that "DBs are
always reset on deploy (loop_dev.sh / loop_main.sh drop the public schema
before re-applying migrations)". That contract described a hosted deployment
Kerf no longer is. The default install is now an embedded SQLite file at
~/.kerf/kerf.db that nobody ever drops, and self-hosted Postgres is somebody's
real database. Under a no-reset install, folding a column into its originating
CREATE TABLE reaches *new* databases only: CREATE TABLE IF NOT EXISTS is a
no-op everywhere else, so the column silently never arrives. That is not
hypothetical — user_provider_keys.base_url was folded in and reached no
existing database until the ALTER below was added alongside it.

So the rule is now narrower rather than absent:

  * DROP of any kind stays banned. There is no reset to recover from a
    mistake, and a fold that drops a column destroys data on every install.
  * ALTER TABLE is allowed only as a single-line ADD COLUMN IF NOT EXISTS.
    That is the exact form migrations/runner.py can make idempotent — it
    strips the qualifier for SQLite (which has no such syntax) and skips the
    statement when PRAGMA table_info already shows the column. Any other
    shape, including a multi-line ALTER, is unguarded and will abort a
    re-run, so it stays banned.

The column still belongs in its CREATE TABLE block as well: that is what new
installs read, and the ALTER is the delivery mechanism for old ones. Both, not
either.
"""

import pathlib
import re

_MIGRATIONS_DIR = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src/kerf_core/db/migrations"
)

_ALTER = re.compile(r"^\s*alter\s+table\b", re.IGNORECASE)
_DROP = re.compile(
    r"^\s*(drop\s+table|drop\s+column|drop\s+index|drop\s+constraint)",
    re.IGNORECASE,
)

# The single guarded form. Must be one statement on one line, terminated —
# runner.py's guard matches per line and cannot split a wrapped statement.
_ALLOWED_ALTER = re.compile(
    r"^\s*alter\s+table\s+\w+\s+add\s+column\s+if\s+not\s+exists\s+\w+\b.*;\s*$",
    re.IGNORECASE,
)


def _lines():
    for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        for lineno, line in enumerate(sql_file.read_text().splitlines(), start=1):
            yield sql_file.name, lineno, line


def test_no_drops_in_migrations():
    offending = [
        f"{name}:{lineno}: {line.rstrip()}"
        for name, lineno, line in _lines()
        if _DROP.match(line)
    ]
    assert not offending, (
        "Found DROP statements in migration files. Installs are never reset, "
        "so a DROP destroys real data on every existing database.\n\n"
        + "\n".join(offending)
    )


def test_alters_are_only_guarded_add_columns():
    offending = [
        f"{name}:{lineno}: {line.rstrip()}"
        for name, lineno, line in _lines()
        if _ALTER.match(line) and not _ALLOWED_ALTER.match(line)
    ]
    assert not offending, (
        "Found an ALTER TABLE that the migration runner cannot make "
        "idempotent. The only supported form is a single-line\n"
        "  alter table <t> add column if not exists <c> <type>;\n"
        "which the runner rewrites for SQLite and skips when the column "
        "already exists.\n\n"
        + "\n".join(offending)
    )


def test_added_columns_also_exist_in_their_create_table():
    """An ALTER alone reaches existing installs but not new ones.

    CREATE TABLE is what a fresh database reads; the ALTER is the delivery
    mechanism for databases that already ran an earlier version of the file.
    Adding only one of the two is a silent split-brain: fresh installs and
    upgraded installs end up with different schemas.
    """
    missing = []
    for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        text = sql_file.read_text()
        for m in re.finditer(
            r"^\s*alter\s+table\s+(\w+)\s+add\s+column\s+if\s+not\s+exists\s+(\w+)\b",
            text, re.IGNORECASE | re.MULTILINE,
        ):
            table, column = m.group(1), m.group(2)
            create = re.search(
                rf"create\s+table\s+if\s+not\s+exists\s+{table}\s*\((.*?)\n\);",
                text, re.IGNORECASE | re.DOTALL,
            )
            if not create or not re.search(
                rf"^\s*{column}\s+\w", create.group(1), re.IGNORECASE | re.MULTILINE
            ):
                missing.append(
                    f"{sql_file.name}: {table}.{column} is added by ALTER but is "
                    f"not a column of its CREATE TABLE block"
                )
    assert not missing, "\n".join(missing)
