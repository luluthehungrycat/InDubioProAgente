"""Typed, versioned contract between the deterministic engine and jurisdiction rule packs.

A ruleset only *evaluates* a read-only snapshot and returns procedural findings. It never
mutates engine state, never decides acceptance and never participates in security checks
(actor authority, evidence ACL, structural references); those remain unconditional in
``indubio.core.engine`` regardless of ruleset or mode.
"""

from datetime import date
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from indubio.core.models import Action, Mode, Phase, Role, RuleFinding

ValidationStatus = Literal["unvalidated_demonstrator", "placeholder", "human_reviewed"]


class RuleSource(BaseModel):
    """Citation for one executable rule; required before a pack may claim review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authority: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    section: str = Field(min_length=1)
    retrieved_on: date


class RulesetMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ruleset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    validation_status: ValidationStatus
    effective_date: date | None = None
    sources: tuple[RuleSource, ...] = ()
    disclaimer: str = Field(min_length=1)

    @model_validator(mode="after")
    def _reviewed_requires_provenance(self) -> "RulesetMetadata":
        # Invariant 4: no pack may present itself as reviewed law without sources and date.
        if self.validation_status == "human_reviewed" and not (
            self.sources and self.effective_date
        ):
            raise ValueError("human_reviewed rulesets require sources and an effective_date")
        return self


class RuleContext(BaseModel):
    """Immutable snapshot handed to a ruleset; it cannot reach the live engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Mode
    phase: Phase
    committed_event_count: int = Field(ge=0)
    motion_ids: frozenset[str] = frozenset()
    actor_role: Role


@runtime_checkable
class JurisdictionRuleset(Protocol):
    @property
    def metadata(self) -> RulesetMetadata: ...

    def evaluate(self, context: RuleContext, action: Action) -> list[RuleFinding]:
        """Return procedural findings only; the engine rejects any other severity."""
        ...
