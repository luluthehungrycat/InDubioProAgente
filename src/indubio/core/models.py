"""Model definitions: proposals, outcomes and events are intentionally distinct."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Mode(StrEnum):
    STRICT = "strict"
    REALISTIC = "realistic"
    EXPERIMENTAL = "experimental"


class Role(StrEnum):
    JUDGE = "judge"
    PROSECUTOR = "prosecutor"
    DEFENSE = "defense"
    DEFENDANT = "defendant"
    WITNESS = "witness"
    HUMAN_OBSERVER = "human_observer"


class Phase(StrEnum):
    OPENING = "opening"
    EVIDENCE = "evidence"
    CLOSING = "closing"
    JUDGMENT = "judgment"
    FINISHED = "finished"


PHASES = tuple(Phase)


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1)
    role: Role
    human_controlled: bool = False
    display_name: str = Field(min_length=1)


class Speak(BaseModel):
    kind: Literal["speak"] = "speak"
    text: str = Field(min_length=1)


class SubmitEvidence(BaseModel):
    kind: Literal["submit_evidence"] = "submit_evidence"
    evidence_id: str = Field(min_length=1)


class MovePhase(BaseModel):
    kind: Literal["move_phase"] = "move_phase"
    destination: Phase


class RuleOnMotion(BaseModel):
    kind: Literal["rule_on_motion"] = "rule_on_motion"
    motion_id: str = Field(min_length=1)
    ruling: Literal["granted", "denied"]
    reasons: str = Field(min_length=1)


class FileMotion(BaseModel):
    kind: Literal["file_motion"] = "file_motion"
    motion_id: str = Field(min_length=1)
    grounds: str = Field(min_length=1)


class Object(BaseModel):
    kind: Literal["object"] = "object"
    target_event_sequence: int = Field(ge=1)
    grounds: str = Field(min_length=1)


Action = Annotated[
    Speak | SubmitEvidence | MovePhase | RuleOnMotion | FileMotion | Object,
    Field(discriminator="kind"),
]


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str
    action: Action


class RuleFinding(BaseModel):
    rule_id: str
    description: str
    severity: Literal["procedural", "security"]
    status: Literal["potential", "confirmed_by_ruleset"] = "potential"


class TrialEvent(BaseModel):
    sequence: int = Field(ge=1)
    actor_id: str
    phase_before: Phase
    phase_after: Phase
    proposal: Proposal
    accepted: bool
    findings: list[RuleFinding] = Field(default_factory=list)
    # A deterministic rule finding is not a judicial legal determination.
    metadata: dict[str, str] = Field(default_factory=dict)


class SimulationConfig(BaseModel):
    jurisdiction: str = "de-criminal-demo-unvalidated"
    mode: Mode = Mode.STRICT
    seed: int = 0
    allow_judicial_errors: bool = True
    allow_counsel_errors: bool = True
    enable_appellate_review: bool = False  # reserved, not implemented
