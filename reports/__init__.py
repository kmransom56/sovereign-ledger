"""Sovereign Ledger reports package — pure derivations over the ledger.

Nothing under ``reports/`` may import web frameworks, database drivers, or
HTTP clients; ``scripts/check_boundaries.py`` fails the build on any
violation. Persistence is the caller's job (adapters in ``app/``).
"""