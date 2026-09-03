"""Hash-chained append-only audit log for the Sovereign Ledger (HR-10).

Every audit event commits to the hash of the event before it:

    genesis:   hash₀ = SHA-256(canonical(payload₀) ‖ SEPARATOR ‖ GENESIS_PREV_HASH)
    event i:   hashᵢ = SHA-256(canonical(payloadᵢ) ‖ SEPARATOR ‖ hashᵢ₋₁)

so mutating ANY event's payload (or swapping its position) breaks every
verification from that point on (T-15: an undetected tamper is a
phase-exit blocker).

CANONICAL SERIALIZATION — the design risk pinned by a golden vector in
``tests/test_audit.py`` (sub-task spec, "Blockers & Risks" row 2):

* the payload is serialized as JSON with SORTED keys (every level),
  ``separators=(",", ":")`` (no whitespace), ``ensure_ascii=True`` and
  ``allow_nan=False``; the value domain is ints, strings, bools, None,
  lists/tuples and str-keyed mappings — floats are refused outright
  (never float money, never float ids), so the encoding is fully
  deterministic;
* the hash preimage is ``canonical(payload) ‖ SEPARATOR ‖ prev_hash``
  with an explicit ``‖`` separator (UTF-8), hashed with SHA-256.

The chain lives in pure value objects: an :class:`AuditEvent` is
immutable and computes its own ``hash`` at construction (callers cannot
forge one); :class:`AuditLog` is an append-only list the caller persists
(D-8 — the storage boundary additionally refuses UPDATE/DELETE on
``audit_log`` rows, so the chain's guarantees hold in storage too).

Field mapping to ``audit_log`` (0001_core.sql): ``seq`` → row id
(implicit by position), ``timestamp`` → ``ts`` (caller-supplied ISO
string — no clock reads), ``actor``/``action``/``entity``/``entity_id``
→ the like-named columns, ``prev_hash``/``hash`` → the like-named
columns.

Purity contract (hard rule 1): standard library only; no I/O of any
kind, no clock reads, no randomness. ``scripts/check_boundaries.py``
fails the build if a forbidden I/O token ever appears under
``ledger/``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

__all__ = [
    "AuditEvent",
    "AuditLog",
    "AuditLogError",
    "ChainBrokenError",
    "GENESIS_PREV_HASH",
    "SEPARATOR",
    "canonical_payload",
    "event_hash",
    "verify_chain",
]

#: The explicit separator between canonical payload bytes and the prev
#: hash inside the hash preimage — the UTF-8 encoding of '‖' (U+2016),
#: a byte sequence JSON can never produce, keeping preimage ambiguity
#: structurally zero.
SEPARATOR = b"\xe2\x80\x96"

#: The prev-hash pinned under the genesis event (no event precedes it).
GENESIS_PREV_HASH = "0" * 64


class AuditLogError(ValueError):
    """Base class for audit-log domain errors."""


class ChainBrokenError(AuditLogError):
    """Chain verification failed — an event was mutated, reordered or forged."""


def _validate_payload(node: Any) -> None:
    """Refuse anything outside the canonical encoding's value domain."""
    if node is None or isinstance(node, bool) or isinstance(node, int):
        return
    if isinstance(node, str):
        return
    if isinstance(node, float):
        raise TypeError("float values are forbidden in audit payloads (determinism)")
    if isinstance(node, Mapping):
        for key, value in node.items():
            if not isinstance(key, str):
                raise TypeError(f"audit payload keys must be str; got {type(key).__name__}")
            _validate_payload(value)
        return
    if isinstance(node, (list, tuple)):
        for item in node:
            _validate_payload(item)
        return
    raise TypeError(
        f"unsupported audit payload value type {type(node).__name__} "
        "(ints, strings, bools, None, lists, str-keyed mappings only)"
    )


def canonical_payload(payload: Mapping[str, Any]) -> bytes:
    """Canonical bytes for a payload: sorted keys, explicit separators.

    Contract (fixed here, pinned byte-for-byte by the golden vector in
    ``tests/test_audit.py``):

    * JSON, UTF-8, ``ensure_ascii=True`` (pure-ASCII output);
    * keys sorted at every level (``sort_keys=True``);
    * ``separators=(",", ":")`` — no whitespace;
    * ``allow_nan=False`` — NaN/Infinity can never silently encode;
    * value domain per :func:`_validate_payload` — floats refused.

    Raises:
        TypeError: a non-Mapping payload, a non-str key, a float value
            or any value outside the domain.
        ValueError: NaN/Infinity through a nested unvalidated path.
    """
    if not isinstance(payload, Mapping):
        raise TypeError(f"canonical_payload expects a Mapping; got {type(payload).__name__}")
    _validate_payload(payload)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def event_hash(payload: Mapping[str, Any], prev_hash: str) -> str:
    """SHA-256 of ``canonical(payload) ‖ SEPARATOR ‖ prev_hash``.

    This IS the chain rule — one function, one preimage, no
    recomputation ambiguity (the golden vector pins it byte-for-byte).

    Raises:
        TypeError: non-Mapping payload or non-str prev_hash.
    """
    if not isinstance(prev_hash, str):
        raise TypeError(f"prev_hash must be a str; got {type(prev_hash).__name__}")
    canonical = canonical_payload(payload)
    preimage = canonical + SEPARATOR + prev_hash.encode("utf-8")
    return hashlib.sha256(preimage).hexdigest()


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One append-only audit record with its chain commitments.

    ``payload`` is the tamper-evident content (sorted-key canonical
    encoding, validated at construction); ``prev_hash`` commits to the
    previous event's hash (:data:`GENESIS_PREV_HASH` under the first
    event); ``hash`` is this event's own commitment, computed AT
    CONSTRUCTION — the caller cannot supply or forge one.
    ``timestamp`` is a caller-supplied ISO string — no clock reads.
    """

    seq: int
    timestamp: str
    actor: str
    action: str
    entity: str
    payload: Mapping[str, Any]
    entity_id: str | None = None
    prev_hash: str = GENESIS_PREV_HASH
    hash: str = field(default="")

    def __post_init__(self) -> None:
        if isinstance(self.seq, bool) or not isinstance(self.seq, int):
            raise TypeError("AuditEvent.seq must be an int")
        if not isinstance(self.timestamp, str) or not self.timestamp.strip():
            raise ValueError("AuditEvent.timestamp must be a non-empty string")
        if not isinstance(self.actor, str) or not self.actor.strip():
            raise ValueError("AuditEvent.actor must be a non-empty string")
        if not isinstance(self.action, str) or not self.action.strip():
            raise ValueError("AuditEvent.action must be a non-empty string")
        if not isinstance(self.entity, str) or not self.entity.strip():
            raise ValueError("AuditEvent.entity must be a non-empty string")
        if self.entity_id is not None and (
            not isinstance(self.entity_id, str) or not self.entity_id.strip()
        ):
            raise ValueError("AuditEvent.entity_id must be a non-empty string or None")
        if not isinstance(self.payload, Mapping):
            raise TypeError("AuditEvent.payload must be a Mapping")
        canonical_payload(self.payload)  # raises for out-of-domain payloads
        if not isinstance(self.prev_hash, str) or len(self.prev_hash) != 64:
            raise ValueError("AuditEvent.prev_hash must be a 64-char hex digest")
        int(self.prev_hash, 16)  # raises ValueError for non-hex prev_hash
        # The hash is computed here — an event always carries its own
        # commitment; a forged hash field can never be smuggled in.
        object.__setattr__(self, "hash", event_hash(self.payload, self.prev_hash))


@dataclass
class AuditLog:
    """An append-only in-memory audit chain — persistence is the caller's job.

    :meth:`append` is the ONLY writer: it derives ``seq`` and
    ``prev_hash`` from the chain tail (the caller supplies neither, so
    linkage cannot be forged) and re-verifies the WHOLE chain after the
    append, so corruption of an already-stored event can never hide
    behind a successful append. :meth:`verify` refuses any tamper.
    """

    events: list[AuditEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        events = list(self.events)
        object.__setattr__(self, "events", events)
        self.verify()

    def append(
        self,
        *,
        timestamp: str,
        actor: str,
        action: str,
        entity: str,
        payload: Mapping[str, Any],
        entity_id: str | None = None,
    ) -> AuditEvent:
        """Append ONE event — prev-hash linkage derived and validated (HR-10).

        Returns:
            The appended :class:`AuditEvent`.

        Raises:
            ChainBrokenError: the chain (with the new event) fails
                verification.
        """
        last = self.events[-1] if self.events else None
        event = AuditEvent(
            seq=(last.seq + 1) if last is not None else 0,
            timestamp=timestamp,
            actor=actor,
            action=action,
            entity=entity,
            entity_id=entity_id,
            payload=payload,
            prev_hash=(last.hash if last is not None else GENESIS_PREV_HASH),
        )
        self.events.append(event)
        verify_chain(self.events)
        return event

    def verify(self) -> list[str]:
        """Verify the full chain — REFUSES any tamper (HR-10/T-15).

        Returns:
            The chain's hashes in order (one per event).

        Raises:
            ChainBrokenError: any event fails verification.
        """
        return verify_chain(self.events)


def verify_chain(events: Sequence[AuditEvent]) -> list[str]:
    """Verify an event chain; return the hashes, or REFUSE (HR-10).

    Checks, in order: strict sequence numbering (each event's ``seq``
    equals its position), prev-hash linkage (each event commits to the
    previous event's hash; the first commits to
    :data:`GENESIS_PREV_HASH`), and hash recomputation — the SHA-256
    preimage of every event must match its stored ``hash`` exactly.
    Mutating any event's payload, or swapping two events, breaks the
    recomputation or the linkage and raises.

    Returns:
        The chain's hashes in order (one per event).

    Raises:
        ChainBrokenError: sequence, linkage or hash mismatch.
    """
    chain = tuple(events)
    prev_hash = GENESIS_PREV_HASH
    hashes: list[str] = []
    for position, event in enumerate(chain):
        if not isinstance(event, AuditEvent):
            raise ChainBrokenError(
                f"audit position {position}: expected an AuditEvent; got {type(event).__name__}"
            )
        if event.seq != position:
            raise ChainBrokenError(
                f"audit event seq {event.seq} out of order at position {position} "
                "(sequence numbers must advance by exactly 1)"
            )
        if event.prev_hash != prev_hash:
            raise ChainBrokenError(
                f"audit event {event.seq}: prev_hash {event.prev_hash!r} does not commit to "
                f"the previous hash {prev_hash!r} — chain is broken"
            )
        expected_hash = event_hash(event.payload, event.prev_hash)
        if event.hash != expected_hash:
            raise ChainBrokenError(
                f"audit event {event.seq}: hash {event.hash!r} does not match the recomputed "
                f"hash {expected_hash!r} — payload mutated or forged (HR-10)"
            )
        prev_hash = event.hash
        hashes.append(event.hash)
    return hashes