"""Sovereign Ledger database access layer.

This package provides a PostgreSQL 16 connection pool factory plus a
serializable-isolation transaction context with bounded retry on
serialization failure (40001), per decision D-7.
"""