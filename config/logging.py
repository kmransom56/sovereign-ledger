"""Stdlib logging setup for the Sovereign Ledger.

Kept in ``config/`` (not the domain core) because emitting to stderr is
I/O. The pure core (``ledger/``, ``reports/``) may *use* loggers but this
module owns the handler/level wiring, driven by ``config.settings``.
"""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s :: %(message)s"


def configure_logging(level: str = "INFO") -> logging.Logger:
    """(Re)configure the root logger exactly once per call and return the ``ledger`` logger.

    Idempotent: existing handlers are removed before the single
    StreamHandler is attached, so repeated calls (tests, reloads) never
    duplicate output. Unknown levels raise ValueError from setLevel.
    """
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    root.setLevel(str(level).upper())
    return logging.getLogger("ledger")