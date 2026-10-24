"""The tests write to a database of their own, never to the one the hub serves.

Every test makes workspaces, types and records, and many of them shared; run against the development
database, they show up in every workspace's pickers and lists. So before any test module imports the app,
DATABASE_URL is pointed at a sibling database (`<name>_test`, or TEST_DATABASE_URL when set), which is
recreated empty for each run and migrated to head, triggers included, which `Base.metadata.create_all` alone
would not give (ARGUS_TESTS_KEEP_DATABASE=1 keeps the previous run's).
"""
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parent.parent


def _test_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    url = make_url(os.environ["DATABASE_URL"])
    name = url.database or "app"
    return url.set(database=name if name.endswith("_test") else f"{name}_test").render_as_string(hide_password=False)


def _ensure(url: str) -> None:
    """A fresh test database for every run: tests that use fixed keys, or count what they made, would
    otherwise meet what the previous run left behind."""
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if os.environ.get("ARGUS_TESTS_KEEP_DATABASE") != "1":
            conn.execute(text(f'drop database if exists "{target.database}" with (force)'))
        if not conn.scalar(text("select 1 from pg_database where datname = :n"), {"n": target.database}):
            conn.execute(text(f'create database "{target.database}"'))
    admin.dispose()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True,
                   env={**os.environ, "DATABASE_URL": url}, stdout=subprocess.DEVNULL)


# A publication in a test must not start indexing in a thread behind the test's back
# (test_knowledge_schedule.py turns it on where it is what is tested).
os.environ.setdefault("ARGUS_KNOWLEDGE_SCHEDULER", "off")
os.environ.setdefault("ARGUS_IMPORT_SCHEDULER", "off")

if os.environ.get("DATABASE_URL") and os.environ.get("ARGUS_TESTS_USE_DATABASE_URL") != "1":
    os.environ["DATABASE_URL"] = _test_url()
    _ensure(os.environ["DATABASE_URL"])
