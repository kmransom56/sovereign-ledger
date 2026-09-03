"""Sovereign Ledger application configuration.

Deliberately OUTSIDE the pure core: settings read the process environment
and logging writes to stderr. The domain trees (``ledger/``, ``reports/``)
stay I/O-free per boundary rule 1.
"""