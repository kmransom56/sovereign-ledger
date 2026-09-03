#!/usr/bin/env python3
"""Initialize Sovereign Ledger on SurrealDB (OLTP) + ClickHouse (OLAP).

Applies SurrealQL schema definitions in db/surreal/ and ClickHouse analytics
schemas in db/clickhouse/.

Usage:
    python3 scripts/init_surreal_db.py
"""

from __future__ import annotations

import logging
import os
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db.surreal_session import get_surreal_client  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("init_surreal_db")

SURREAL_DIR = REPO_ROOT / "db" / "surreal"
CLICKHOUSE_DIR = REPO_ROOT / "db" / "clickhouse"
CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "http://127.0.0.1:11084")


def init_surreal() -> None:
    client = get_surreal_client()
    if not client.ping():
        raise RuntimeError(
            f"Cannot connect to SurrealDB at {client.url}. Is surrealdb running?"
        )
    log.info("SurrealDB ping successful at %s", client.url)

    # Ensure NS and DB exist
    client.query(
        f"DEFINE NAMESPACE IF NOT EXISTS {client.ns}; "
        f"USE NS {client.ns}; "
        f"DEFINE DATABASE IF NOT EXISTS {client.db}; "
        f"USE DB {client.db};"
    )

    # Apply all .surql files in sorted order
    for path in sorted(SURREAL_DIR.glob("*.surql")):
        log.info("Applying SurrealDB schema: %s", path.name)
        sql = path.read_text(encoding="utf-8")
        client.query(sql)

    db_info = client.query("INFO FOR DB;")[0].get("result", {})
    tables = list(db_info.get("tables", {}).keys())
    log.info("SurrealDB initialized successfully. Active tables: %s", tables)


def init_clickhouse() -> None:
    try:
        req = urllib.request.Request(f"{CLICKHOUSE_URL}/?query=SELECT%201")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            if resp.getcode() != 200:
                raise RuntimeError(
                    f"ClickHouse returned HTTP {resp.getcode()}"
                )
    except Exception as e:
        log.warning(
            "ClickHouse not reachable at %s: %s (skipping OLAP)",
            CLICKHOUSE_URL,
            e,
        )
        return

    log.info("ClickHouse ping successful at %s", CLICKHOUSE_URL)
    for path in sorted(CLICKHOUSE_DIR.glob("*.sql")):
        log.info("Applying ClickHouse schema: %s", path.name)
        content = path.read_text(encoding="utf-8")
        statements = [s.strip() for s in content.split(";") if s.strip()]
        for stmt in statements:
            req = urllib.request.Request(
                f"{CLICKHOUSE_URL}/",
                data=stmt.encode("utf-8"),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10.0) as _:
                pass
    log.info("ClickHouse tax analytics initialized successfully.")


def main() -> int:
    log.info(
        "Starting Sovereign Ledger Dual-Database Initialization (SurrealDB + ClickHouse)..."
    )
    init_surreal()
    init_clickhouse()
    print("\n✅ Sovereign Ledger Database Initialization COMPLETE:")
    print(
        "   • SurrealDB (Transactional/OLTP):  http://127.0.0.1:11074 (sovereign/ledger)"
    )
    print(
        "   • ClickHouse (Analytics/OLAP):      http://127.0.0.1:11084 (ledger_analytics)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
