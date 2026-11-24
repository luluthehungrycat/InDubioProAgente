"""Immutable, actor-scoped evidence registry.

The registry snapshots records at construction and only ever hands out deep copies.
Scoped views never include ``HIDDEN_TRUTH`` records, whatever their visibility list says,
so no actor (including a judge) gains accidental omniscience.
"""

from collections.abc import Iterable, Iterator
from types import MappingProxyType
from typing import NoReturn

from indubio.evidence.models import EvidenceRecord, is_visible


class EvidenceRegistry:
    __slots__ = ("_records",)

    def __init__(self, records: Iterable[EvidenceRecord] = ()) -> None:
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
        return iter(self._records)

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
        return frozenset(
            actor_id for record in self._records.values()
            for actor_id in record.visible_to_actor_ids
        )
