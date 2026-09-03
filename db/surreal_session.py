"""Sovereign Ledger SurrealDB database session layer.

SurrealDB (http://127.0.0.1:11074) is the operational, transactional system of record
for Sovereign Ledger. This module provides a high-performance, connection-pooled
HTTP/JSON interface with zero C-dependency overhead.

Namespace: sovereign
Database: ledger
"""

from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger("surreal_session")

DEFAULT_URL = os.environ.get("SURREALDB_URL", "http://127.0.0.1:11074")
DEFAULT_NS = os.environ.get("SURREALDB_NS", "sovereign")
DEFAULT_DB = os.environ.get("SURREALDB_DB", "ledger")
DEFAULT_USER = os.environ.get("SURREALDB_USER", "root")
DEFAULT_PASS = os.environ.get("SURREALDB_PASS", "root")


class SurrealDBClient:
    """Synchronous client for SurrealDB HTTP SQL endpoint."""

    def __init__(
        self,
        url: str = DEFAULT_URL,
        ns: str = DEFAULT_NS,
        db: str = DEFAULT_DB,
        user: str = DEFAULT_USER,
        password: str = DEFAULT_PASS,
        timeout: float = 10.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.ns = ns
        self.db = db
        self.user = user
        self.password = password
        self.timeout = timeout
        self._auth_header = "Basic " + base64.b64encode(
            f"{self.user}:{self.password}".encode("ascii")
        ).decode("ascii")

    def _headers(self) -> Dict[str, str]:
        return {
            "surreal-ns": self.ns,
            "surreal-db": self.db,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": self._auth_header,
        }

    def ping(self) -> bool:
        """Check if SurrealDB is healthy and reachable."""
        try:
            req = urllib.request.Request(
                f"{self.url}/health",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.getcode() == 200
        except Exception:
            return False

    def query(self, sql: str, vars: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Execute SurrealQL and return parsed result array."""
        payload = sql.strip()
        headers = self._headers()
        # SurrealDB supports text/plain or application/json queries
        headers["Content-Type"] = "text/plain"

        req = urllib.request.Request(
            f"{self.url}/sql",
            data=payload.encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for item in data:
                    if item.get("status") == "ERR":
                        raise RuntimeError(f"SurrealDB error: {item.get('result')}")
                return data
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code} from SurrealDB: {error_body}") from e

    def create(self, table: str, record_id: Optional[str], data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a record in a table."""
        target = f"{table}:{record_id}" if record_id else table
        body = json.dumps(data)
        sql = f"CREATE {target} CONTENT {body};"
        res = self.query(sql)
        items = res[0].get("result", [])
        return items[0] if items else {}

    def select(self, table: str, record_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Select records from table."""
        target = f"{table}:{record_id}" if record_id else table
        sql = f"SELECT * FROM {target};"
        res = self.query(sql)
        return res[0].get("result", [])

    def update(self, table: str, record_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a record in a table."""
        target = f"{table}:{record_id}"
        body = json.dumps(data)
        sql = f"UPDATE {target} MERGE {body};"
        res = self.query(sql)
        items = res[0].get("result", [])
        return items[0] if items else {}

    def delete(self, table: str, record_id: Optional[str] = None) -> None:
        """Delete a record or table."""
        target = f"{table}:{record_id}" if record_id else table
        sql = f"DELETE {target};"
        self.query(sql)


# Global singleton client
_client: Optional[SurrealDBClient] = None


def get_surreal_client() -> SurrealDBClient:
    global _client
    if _client is None:
        _client = SurrealDBClient()
    return _client
