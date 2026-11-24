"""Model definitions: proposals, outcomes and events are intentionally distinct."""

from enum import StrEnum
from typing import Annotated, Literal, get_args

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


class DiscloseEvidence(BaseModel):
    """Grant one known recipient access to one evidence record the discloser holds.

    Single recipient by design: a multi-recipient payload would tell each recipient who
    else received the record. The engine validates authority, record existence and the
    discloser's current access in every mode; see ``indubio.core.disclosure``.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["disclose_evidence"] = "disclose_evidence"
    evidence_id: str = Field(min_length=1)
    recipient_actor_id: str = Field(min_length=1)


class Object(BaseModel):
    kind: Literal["object"] = "object"
    target_event_sequence: int = Field(ge=1)
    grounds: str = Field(min_length=1)


Action = Annotated[
    Speak | SubmitEvidence | MovePhase | RuleOnMotion | FileMotion | Object
    | DiscloseEvidence,
    Field(discriminator="kind"),
]

# The exact model classes of the ``Action`` union, derived from the schema itself so the
# engine boundary and the authorization table cannot drift from the journal contract.
# A runtime action whose class is not one of these (a subclass, a foreign object) is
# outside the schema and is refused before any event exists.
ACTION_TYPES: tuple[type[BaseModel], ...] = get_args(get_args(Action)[0])


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str
    action: Action


class RuleFinding(BaseModel):
    rule_id: str
    description: str
    severity: Literal["procedural", "security"]
    status: Literal["potential", "confirmed_by_ruleset"] = "potential"


PROVENANCE_SCHEMA = "indubio.scenario-provenance/1"
SETUP_CANONICALIZATION = "indubio.scenario-setup/1"
SETUP_DIGEST_ALGORITHM = "sha256"


class ScenarioIdentity(BaseModel):
    """Author-declared scenario identity handed to the engine by trusted setup code.

    Identity is a claim, not proof of content; see ``indubio.core.provenance``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_schema_version: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    scenario_version: str = Field(min_length=1)


class ScenarioProvenance(BaseModel):
    """Scenario identity plus the engine-computed digest of its normalized setup.

    Stamped on every committed event (accepted or rejected) of a scenario-built engine.
    Trusted audit data: never projected to actors. A consumer matching a journal against
    a scenario must compare every field exactly. See ``indubio.core.provenance``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    provenance_schema: Literal["indubio.scenario-provenance/1"]
    scenario_schema_version: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    scenario_version: str = Field(min_length=1)
    setup_canonicalization: Literal["indubio.scenario-setup/1"]
    setup_digest_algorithm: Literal["sha256"]
    setup_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def identity(self) -> ScenarioIdentity:
        return ScenarioIdentity(
            scenario_schema_version=self.scenario_schema_version,
            scenario_id=self.scenario_id,
            scenario_version=self.scenario_version,
        )


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
    # Scenario provenance; ``None`` for direct (non-scenario) engines and legacy journals.
    # Omitted from serialization when ``None`` so those payloads keep their exact shape.
    scenario: ScenarioProvenance | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class SimulationConfig(BaseModel):
    jurisdiction: str = "de-criminal-demo-unvalidated"
    mode: Mode = Mode.STRICT
    seed: int = 0
    allow_judicial_errors: bool = True
    allow_counsel_errors: bool = True
    enable_appellate_review: bool = False  # reserved, not implemented
