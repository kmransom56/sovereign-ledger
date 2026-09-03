"""Pytest fixtures for sovereign-ledger DB tests.

Session-scoped scratch PostgreSQL 16 in rootless podman:
    image    docker.io/library/postgres:16-alpine (pulled locally)
    name     sovereign-ledger-test-pg
    port     127.0.0.1:11241 -> container 5432
             (11240 and 15432 are off-limits — used by other things)
    DSN      postgresql://ledger:ledger@127.0.0.1:11241/ledger_test

Lifecycle per pytest session: `podman run --rm -d`, wait-ready via a
`pg_isready` loop, CREATE DATABASE ledger_test, run scripts/init_db.py
(migrations 0001.. + CoA seed), yield the DSN, then `podman rm -f` in
teardown. ALL later e2e/DB tests reuse this ONE container and database —
never start a second Postgres; append-only tables make tests order- and
state-sensitive by design, so write new tests against this fixture.

Stale containers from crashed runs are removed up front (podman rm -f).
Requires: podman on PATH; the postgres:16-alpine image present locally.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CONTAINER = "sovereign-ledger-test-pg"
IMAGE = "docker.io/library/postgres:16-alpine"
HOST_PORT = 11241
TEST_DSN = f"postgresql://ledger:ledger@127.0.0.1:{HOST_PORT}/ledger_test"
READY_TIMEOUT_S = 60


def _podman(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["podman", *args], check=False, capture_output=True, text=True
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"podman {' '.join(args)} failed (rc={proc.returncode}):\n"
            f"stdout: {proc.stdout.strip()}\nstderr: {proc.stderr.strip()}"
        )
    return proc


def _wait_ready() -> None:
    """Wait until Postgres accepts REAL queries, not just pg_isready.

    The postgres image runs a temporary server while bootstrapping its
    initdb; pg_isready can briefly succeed against it and the next psql call
    then fails to connect (exit 2). So: pg_isready first, then a psql
    SELECT 1 loop — the same connectivity init_db will rely on.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        probe = _podman(
            "exec", CONTAINER, "pg_isready", "-U", "ledger", "-d", "ledger",
            check=False,
        )
        if probe.returncode == 0:
            select = _podman(
                "exec", CONTAINER, "psql", "-U", "ledger", "-d", "ledger",
                "-c", "SELECT 1",
                check=False,
            )
            if select.returncode == 0:
                return
        time.sleep(0.5)
    raise RuntimeError(
        f"scratch Postgres {CONTAINER} not ready after {READY_TIMEOUT_S}s "
        f"(last pg_isready: {probe.stderr.strip() or probe.stdout.strip()})"
    )


def _ss_listening() -> str:
    return subprocess.run(
        ["ss", "-ltn"], capture_output=True, text=True, check=True
    ).stdout


def _assert_port_free() -> None:
    if f":{HOST_PORT} " not in _ss_listening():
        return
    # Port is bound. If it is a scratch container leaked by a previously
    # interrupted session (teardown never ran), reclaim it — it is ours.
    # `ps -a` (not `ps`): a Stopping/Exited leftover still owns the port.
    ps = _podman(
        "ps", "-a", "--filter", f"name=^{CONTAINER}$", "--format", "{{.ID}}",
        check=False,
    )
    if ps.stdout.strip():
        # -t 0: SIGKILL immediately — graceful postgres shutdown releases the
        # port asynchronously and would race the ss() re-check below.
        _podman("rm", "-f", "-t", "0", CONTAINER, check=False)
        for _ in range(20):  # poll up to ~10s for the port to actually free
            if f":{HOST_PORT} " not in _ss_listening():
                return
            time.sleep(0.5)
    raise RuntimeError(
        f"host port {HOST_PORT} is already bound by a foreign listener — "
        "refusing to start the scratch container (it must own "
        "127.0.0.1:11241 exclusively)"
    )


@pytest.fixture(scope="session")
def scratch_pg() -> str:
    """Scratch PostgreSQL 16 container; yields the ledger_test DSN.

    Session-scoped so the whole test suite pays podman startup + migration
    cost exactly once. Teardown removes the container even on failure.
    """
    _assert_port_free()
    # A container from a previously crashed session would collide by name.
    _podman("rm", "-f", CONTAINER, check=False)

    _podman(
        "run", "--rm", "-d",
        "--name", CONTAINER,
        "-p", f"127.0.0.1:{HOST_PORT}:5432",
        "-e", "POSTGRES_USER=ledger",
        "-e", "POSTGRES_PASSWORD=ledger",
        "-e", "POSTGRES_DB=ledger",
        IMAGE,
    )
    try:
        _wait_ready()

        # Fresh scratch database per session; CREATE DATABASE cannot run in a
        # transaction block, hence via psql -c.
        _podman(
            "exec", CONTAINER, "psql", "-U", "ledger", "-d", "ledger",
            "-c", "CREATE DATABASE ledger_test",
        )

        # Migrations + CoA seed, exactly as a user would run them (no import
        # shortcuts): scripts/init_db.py reads DATABASE_URL from the env.
        os.environ["DATABASE_URL"] = TEST_DSN
        from scripts.init_db import main as init_db_main

        init_db_main()

        yield TEST_DSN
    finally:
        _podman("rm", "-f", CONTAINER, check=False)