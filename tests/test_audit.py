"""Hash-chain audit suite (HR-10 / T-15 core half) — golden vector + tampers.

The golden vector pins the WHOLE canonical serialization contract
byte-for-byte:

* canonical payload: JSON, sorted keys, ``(",", ":")`` separators,
  ``ensure_ascii=True``;
* preimage: ``canonical(payload) ‖ SEPARATOR('‖') ‖ prev_hash``;
* SHA-256 as the digest.

Recomputing the vector with plain hashlib (no :mod:`ledger.audit` code)
proves the format from the outside in. Every mutating tamper class is
exercised: payload edit, payload replacement, hash-field forgery,
prev-hash substitution, event reorder, event drop, forged-tail splice.

Purity (hard rule 1): this file performs no I/O against production
trees — it reads nothing, touches nothing; all values are constructed.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from ledger.audit import (
    GENESIS_PREV_HASH,
    SEPARATOR,
    AuditEvent,
    AuditLog,
    AuditLogError,
    ChainBrokenError,
    canonical_payload,
    event_hash,
    verify_chain,
)

TS = "2026-09-02T12:00:00+00:00"


# ---------------------------------------------------------------------------
# Golden vector (T-15 core): the chain rule, pinned byte-for-byte
# ---------------------------------------------------------------------------


def test_golden_vector_chain_rule() -> None:
    """SHA-256(canonical ‖ SEPARATOR ‖ prev_hash) — recomputed by hand."""
    payload = {"amount_cents": 10000, "memo": "seed money"}

    # 1. Canonical payload bytes are exactly this (sorted keys, no ws).
    expected_canonical = b'{"amount_cents":10000,"memo":"seed money"}'
    assert canonical_payload(payload) == expected_canonical
    assert canonical_payload(payload) == json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")

    # 2. Genesis hash: canonical ‖ ‖ GENESIS_PREV_HASH, SHA-256 — no
    #    ledger.audit code involved in this recomputation.
    preimage = expected_canonical + SEPARATOR + GENESIS_PREV_HASH.encode("utf-8")
    expected_hash = hashlib.sha256(preimage).hexdigest()
    assert expected_hash == "8eb549321505ae8eee9c59472ddc5d7f634fde17a419510bbdc1d8e08f52b0f1"
    assert event_hash(payload, GENESIS_PREV_HASH) == expected_hash

    event = AuditEvent(seq=0, timestamp=TS, actor="keith", action="post",
                       entity="journal_entry", entity_id="JE-MAY-1", payload=payload)
    assert event.prev_hash == GENESIS_PREV_HASH
    assert event.hash == expected_hash


def test_golden_vector_chained_events() -> None:
    """Event 1's preimage chains event 0's hash — second pinned vector."""
    payload0 = {"amount_cents": 10000, "memo": "seed money"}
    payload1 = {"amount_cents": -10000}
    event0 = AuditEvent(seq=0, timestamp=TS, actor="keith", action="post",
                        entity="journal_entry", entity_id="JE-MAY-1", payload=payload0)
    event1 = AuditEvent(seq=1, timestamp=TS, actor="keith", action="reverse",
                        entity="journal_entry", entity_id="JE-MAY-1", payload=payload1,
                        prev_hash=event0.hash)
    assert event1.hash == "bc2de34665bf3a51820e091db2888499fdec8d932b997e41ba0eb1fb5d9449f7"
    assert verify_chain([event0, event1]) == [event0.hash, event1.hash]


# ---------------------------------------------------------------------------
# AuditEvent construction: hash computed, never forgeable
# ---------------------------------------------------------------------------


def test_event_hash_is_computed_at_construction() -> None:
    """A forged hash field can never be smuggled past construction."""
    payload = {"k": "v"}
    forged = "f" * 64
    event = AuditEvent(seq=0, timestamp=TS, actor="a", action="act", entity="e",
                       payload=payload, hash="not-even-a-hash")
    assert event.hash == event_hash(payload, GENESIS_PREV_HASH)
    assert event.hash != forged


def test_event_rejects_garbage() -> None:
    """Field-level validation: types, emptiness, hex digests."""
    payload = {"k": "v"}
    good = dict(seq=0, timestamp=TS, actor="a", action="act", entity="e", payload=payload)
    with pytest.raises(TypeError):
        AuditEvent(seq=True, timestamp=TS, actor="a", action="act", entity="e", payload=payload)
    with pytest.raises(TypeError):
        AuditEvent(**{**good, "seq": "0"})
    with pytest.raises(ValueError):
        AuditEvent(**{**good, "timestamp": "   "})
    with pytest.raises(ValueError):
        AuditEvent(**{**good, "actor": ""})
    with pytest.raises(ValueError):
        AuditEvent(**{**good, "action": ""})
    with pytest.raises(ValueError):
        AuditEvent(**{**good, "entity": ""})
    with pytest.raises(ValueError):
        AuditEvent(**{**good, "entity_id": "   "})
    with pytest.raises(TypeError):
        AuditEvent(**{**good, "payload": ["not", "a", "mapping"]})
    with pytest.raises(ValueError):
        AuditEvent(**{**good, "prev_hash": "short"})
    with pytest.raises(ValueError):
        AuditEvent(**{**good, "prev_hash": "z" * 64})  # not hex
    with pytest.raises(TypeError):
        AuditEvent(**{**good, "payload": {"k": 1.5}})  # float money/ids are forbidden


def test_canonical_payload_domain() -> None:
    """Canonical encoding: sorted keys, nested, whitespace-free, ASCII."""
    assert canonical_payload({"b": 1, "a": 2}) == b'{"a":2,"b":1}'
    nested = {"z": {"b": 2, "a": [1, "x", None, True]}, "a": "ok"}
    encoded = canonical_payload(nested)
    assert encoded == b'{"a":"ok","z":{"a":[1,"x",null,true],"b":2}}'
    with pytest.raises(TypeError):
        canonical_payload(["nope"])
    with pytest.raises(TypeError):
        canonical_payload({1: "int-key"})
    with pytest.raises(TypeError):
        canonical_payload({"f": 0.5})
    with pytest.raises(TypeError):
        canonical_payload({"s": {"deep": 1.25}})


def test_event_hash_rejects_non_str_prev() -> None:
    with pytest.raises(TypeError):
        event_hash({"k": "v"}, b"not-a-str")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AuditLog: append-only writer, whole-chain verification after each append
# ---------------------------------------------------------------------------


def test_audit_log_append_and_verify() -> None:
    """Appending N events yields a verifiable chain (sub-task criterion)."""
    log = AuditLog()
    assert log.events == []
    appended = []
    for i in range(5):
        event = log.append(
            timestamp=TS,
            actor="keith",
            action="post",
            entity="journal_entry",
            entity_id=f"JE-{i}",
            payload={"amount_cents": 100 * (i + 1)},
        )
        assert event.seq == i
        appended.append(event)
        log.verify()  # whole chain verified after EVERY append
    assert appended[0].prev_hash == GENESIS_PREV_HASH
    for earlier, later in zip(appended, appended[1:]):
        assert later.prev_hash == earlier.hash
    assert log.verify() == [event.hash for event in appended]


def test_audit_log_accepts_seeded_chain() -> None:
    """A pre-seeded (restored) chain is accepted when it verifies."""
    event0 = AuditEvent(seq=0, timestamp=TS, actor="a", action="act", entity="e", payload={"n": 1})
    event1 = AuditEvent(seq=1, timestamp=TS, actor="a", action="act", entity="e",
                        payload={"n": 2}, prev_hash=event0.hash)
    log = AuditLog(events=[event0, event1])
    assert log.verify() == [event0.hash, event1.hash]


def test_audit_log_rejects_broken_seed() -> None:
    """Construction with a broken chain fails fast (restores are checked)."""
    event0 = AuditEvent(seq=0, timestamp=TS, actor="a", action="act", entity="e", payload={"n": 1})
    forged_tail = dataclasses.replace(event0, seq=1, payload={"n": 2})
    with pytest.raises(ChainBrokenError):
        AuditLog(events=[event0, forged_tail])


def test_audit_log_prevents_linkage_forgery() -> None:
    """seq/prev_hash are derived from the tail — callers cannot set them."""
    log = AuditLog()
    event0 = log.append(timestamp=TS, actor="a", action="act", entity="e", payload={"n": 1})
    event1 = log.append(timestamp=TS, actor="a", action="act", entity="e", payload={"n": 2})
    assert event0.prev_hash == GENESIS_PREV_HASH
    assert event1.prev_hash == event0.hash
    assert (event0.seq, event1.seq) == (0, 1)
    # A hand-built event with a wrong prev-hash is still constructible
    # (the hash is computed from whatever prev_hash is supplied), but
    # verify_chain will reject it because the linkage does not match.
    bad_event = AuditEvent(
        seq=1, timestamp=TS, actor="a", action="act", entity="e", payload={"n": 9},
        prev_hash="a" * 64,
    )
    with pytest.raises(ChainBrokenError):
        verify_chain([event0, bad_event])


# ---------------------------------------------------------------------------
# Tamper detection (T-15 core): every mutating tamper breaks verification
# ---------------------------------------------------------------------------


@pytest.fixture()
def chain() -> list[AuditEvent]:
    """A verified 3-event chain to tamper with."""
    log = AuditLog()
    for i in range(3):
        log.append(timestamp=TS, actor="keith", action="post", entity="journal_entry",
                   entity_id=f"JE-{i}", payload={"amount_cents": 1000 * (i + 1)})
    assert log.verify() is not None  # baseline chain verifies
    return list(log.events)


def test_tamper_payload_value_detected(chain: list[AuditEvent]) -> None:
    """The classic T-15 tamper: edit one event's amount, chain breaks.

    dataclasses.replace triggers __post_init__ which recomputes the
    hash from the new payload — so the event's own hash changes.
    The next event's prev_hash still points at the OLD hash, so the
    linkage check fires.  Either way the chain is broken.
    """
    victim = chain[1]
    mutated = dataclasses.replace(victim, payload={"amount_cents": 999_999})
    with pytest.raises(ChainBrokenError):
        verify_chain([chain[0], mutated, chain[2]])


def test_tamper_payload_key_detected(chain: list[AuditEvent]) -> None:
    """Adding a key changes the canonical bytes — detected."""
    mutated = dataclasses.replace(chain[1], payload={"amount_cents": 2000, "extra": "k"})
    with pytest.raises(ChainBrokenError):
        verify_chain([chain[0], mutated, chain[2]])


def test_tamper_hash_field_forgery_detected(chain: list[AuditEvent]) -> None:
    """Pasting a recomputed hash into a mutated event still breaks linkage.

    dataclasses.replace triggers __post_init__ which recomputes the
    hash from the new payload — so the event's own hash changes.
    The next event's prev_hash still points at the OLD hash, so the
    linkage check fires.
    """
    mutated = dataclasses.replace(chain[1], payload={"amount_cents": 999})
    with pytest.raises(ChainBrokenError):
        verify_chain([chain[0], mutated, chain[2]])
    # Forging ONLY the hash field (payload untouched) — bypass
    # __post_init__ to inject a forged hash into the frozen dataclass:
    forged = dataclasses.replace(chain[1])
    object.__setattr__(forged, "hash", "a" * 64)
    with pytest.raises(ChainBrokenError, match="payload mutated or forged"):
        verify_chain([chain[0], forged, chain[2]])


def test_tamper_prev_hash_rewrite_detected(chain: list[AuditEvent]) -> None:
    """Rewriting prev_hash breaks the commitment to the real predecessor."""
    mutated = dataclasses.replace(chain[1], prev_hash="b" * 64)
    with pytest.raises(ChainBrokenError, match="does not commit to"):
        verify_chain([chain[0], mutated, chain[2]])


def test_tamper_event_reorder_detected(chain: list[AuditEvent]) -> None:
    """Swapping two events breaks sequence numbering."""
    with pytest.raises(ChainBrokenError, match="out of order"):
        verify_chain([chain[1], chain[0], chain[2]])


def test_tamper_event_drop_detected(chain: list[AuditEvent]) -> None:
    """Removing a middle event breaks sequence numbering or linkage."""
    with pytest.raises(ChainBrokenError):
        verify_chain([chain[0], chain[2]])


def test_tamper_forged_tail_splice_detected(chain: list[AuditEvent]) -> None:
    """Splicing a forged continuation with a wrong prev_hash is detected.

    An attacker who knows the real tail hash can extend the chain
    legitimately (that is how append works).  A forged splice with a
    *wrong* prev_hash breaks the linkage check.
    """
    forged_tail = AuditEvent(seq=3, timestamp=TS, actor="attacker", action="forge",
                             entity="journal_entry", payload={"amount_cents": 999_999},
                             prev_hash="d" * 64)  # wrong prev_hash
    with pytest.raises(ChainBrokenError, match="does not commit to"):
        verify_chain(chain + [forged_tail])


def test_tamper_first_event_prev_swap_detected(chain: list[AuditEvent]) -> None:
    """Replacing GENESIS_PREV_HASH on the first event breaks the chain."""
    mutated = dataclasses.replace(chain[0], prev_hash="c" * 64)
    with pytest.raises(ChainBrokenError, match="does not commit to"):
        verify_chain([mutated, chain[1], chain[2]])


def test_verify_chain_rejects_non_event(chain: list[AuditEvent]) -> None:
    """A non-AuditEvent in the sequence is refused outright."""
    with pytest.raises(ChainBrokenError, match="expected an AuditEvent"):
        verify_chain([chain[0], "not-an-event", chain[2]])  # type: ignore[list-item]


def test_verify_empty_chain_is_valid() -> None:
    """An empty chain trivially verifies (no events, no linkage)."""
    assert verify_chain([]) == []


def test_audit_error_hierarchy() -> None:
    """AuditLogError is the ValueError base; ChainBrokenError its subclass."""
    from ledger.audit import AuditLogError as E

    assert issubclass(ChainBrokenError, E)
    assert issubclass(E, ValueError)
    assert issubclass(AuditLogError, ValueError)