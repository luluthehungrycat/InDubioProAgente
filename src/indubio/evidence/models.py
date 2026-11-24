"""Do not conflate ground truth, knowledge, disclosed evidence and findings."""

from enum import StrEnum
from pydantic import BaseModel, Field


class EpistemicLayer(StrEnum):
    HIDDEN_TRUTH = "hidden_truth"
    ACTOR_KNOWLEDGE = "actor_knowledge"
    DISCLOSED = "disclosed"
    ADMITTED = "admitted"
    FACT_FOUND = "fact_found"
    APPELLATE_RECORD = "appellate_record"


class EvidenceRecord(BaseModel):
    evidence_id: str
    summary: str
    layer: EpistemicLayer
    visible_to_actor_ids: set[str] = Field(default_factory=set)
    provenance: str | None = None
    source_timestamp: str | None = None


def is_visible(record: EvidenceRecord, actor_id: str) -> bool:
    # Never expose global hidden truth merely because an actor is a judge.
    return record.layer != EpistemicLayer.HIDDEN_TRUTH and actor_id in record.visible_to_actor_ids


def visible_records(records: list[EvidenceRecord], actor_id: str) -> list[EvidenceRecord]:
    # Same predicate as EvidenceRegistry; returns detached copies.
    return [record.model_copy(deep=True) for record in records if is_visible(record, actor_id)]
