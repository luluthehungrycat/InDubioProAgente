"""Immutable, actor-scoped evidence registry.

The registry snapshots records at construction and only ever hands out deep copies.
Scoped views never include ``HIDDEN_TRUTH`` records, whatever their visibility list says,
so no actor (including a judge) gains accidental omniscience.

API scope:

* ``visible_to`` and ``accessible_ids`` are the actor-scoped APIs and are what the engine
  exposes to actors.
* ``__len__``, ``__iter__`` (registry-wide evidence IDs, including hidden truth),
  ``get``, ``actor_ids`` and ``snapshot`` are trusted setup/validation APIs for scenario authors
  and the engine. They are not actor views and must never be handed to an actor.

Construction happens exactly once: calling ``__init__`` again on an existing instance
raises instead of replacing the backing mapping.
"""

from collections.abc import Iterable, Iterator
from types import MappingProxyType
from typing import NoReturn

from indubio.evidence.models import EvidenceRecord, is_visible


class EvidenceRegistry:
    __slots__ = ("_records",)

    def __init__(self, records: Iterable[EvidenceRecord] = ()) -> None:
        try:
            EvidenceRegistry._records.__get__(self)
        except AttributeError:
            pass
        else:
            raise AttributeError("EvidenceRegistry is immutable and cannot be reinitialized")
        snapshot: dict[str, EvidenceRecord] = {}
        for record in records:
            if not isinstance(record, EvidenceRecord):
                raise TypeError("EvidenceRegistry accepts EvidenceRecord instances only")
            if record.evidence_id in snapshot:
                raise ValueError(f"Duplicate evidence ID: {record.evidence_id!r}")
            snapshot[record.evidence_id] = record.model_copy(deep=True)
        object.__setattr__(self, "_records", MappingProxyType(snapshot))

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("EvidenceRegistry is immutable")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError("EvidenceRegistry is immutable")

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[str]:
        """Trusted setup API: all evidence IDs, including hidden truth. Not an actor view."""
        return iter(self._records)

    def snapshot(self) -> "EvidenceRegistry":
        """Trusted setup API: an independent registry built from deep copies.

        The engine keeps its own snapshot so both evidence views and the derived ACL come
        from one stable record set that no caller holds a reference to.
        """
        return EvidenceRegistry(self._records.values())

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        """Trusted setup API: a detached copy of any record, including hidden truth."""
        record = self._records.get(evidence_id)
        return None if record is None else record.model_copy(deep=True)

    def visible_to(self, actor_id: str) -> list[EvidenceRecord]:
        """Detached copies of the records this actor may see, in registration order."""
        return [
            record.model_copy(deep=True)
            for record in self._records.values() if is_visible(record, actor_id)
        ]

    def accessible_ids(self, actor_id: str) -> frozenset[str]:
        """Evidence IDs the actor may reference; never includes hidden truth."""
        return frozenset(
            evidence_id for evidence_id, record in self._records.items()
            if is_visible(record, actor_id)
        )

    def actor_ids(self) -> frozenset[str]:
        """Trusted setup API: every actor named in any visibility list (for validation)."""
        return frozenset(
            actor_id for record in self._records.values()
            for actor_id in record.visible_to_actor_ids
        )
