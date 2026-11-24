"""Synthetic scenario manifest: a typed, versioned description of a case's initial state.

A manifest declares synthetic actors and the scenario-initial evidence records with their
epistemic layer and per-actor visibility. It is trusted setup input written by a scenario
author, never by an actor or model; ``build_engine`` turns it into a ``SimulationEngine``
with an immutable ``EvidenceRegistry``. After that, visibility only changes through
accepted ``DiscloseEvidence`` events.

Scope: synthetic fixtures only (``synthetic`` must be ``true``). No real-case import, no
legal characterization and no validated procedure. The manifest is plain data: loading
performs no network access and executes nothing.

Validation (fails closed with ``pydantic.ValidationError``): unknown fields, unknown
schema version, duplicate actor or evidence IDs, visibility lists naming unknown actors,
and ``hidden_truth`` records with any visibility. Sealed truth is evaluator-only by
construction rather than relying solely on the registry's layer filter.
"""

from importlib import resources
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from indubio.core.engine import SimulationEngine
from indubio.core.models import Actor, Mode, SimulationConfig
from indubio.evidence.models import EpistemicLayer, EvidenceRecord
from indubio.evidence.registry import EvidenceRegistry

SCHEMA_VERSION = "indubio.scenario/1"
BUNDLED_FIXTURES = frozenset({"synthetic_disclosure_demo"})


class ManifestEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    layer: EpistemicLayer
    visible_to_actor_ids: tuple[str, ...] = ()
    provenance: str | None = None
    source_timestamp: str | None = None

    def to_record(self) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=self.evidence_id,
            summary=self.summary,
            layer=self.layer,
            visible_to_actor_ids=set(self.visible_to_actor_ids),
            provenance=self.provenance,
            source_timestamp=self.source_timestamp,
        )


class ScenarioManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["indubio.scenario/1"]
    scenario_id: str = Field(min_length=1)
    scenario_version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    synthetic: Literal[True]
    disclaimer: str = Field(min_length=1)
    jurisdiction: str = Field(min_length=1)
    actors: tuple[Actor, ...] = Field(min_length=1)
    evidence: tuple[ManifestEvidence, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> "ScenarioManifest":
        actor_ids = [actor.actor_id for actor in self.actors]
        if len(set(actor_ids)) != len(actor_ids):
            raise ValueError("Duplicate actor IDs in manifest")
        evidence_ids = [record.evidence_id for record in self.evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("Duplicate evidence IDs in manifest")
        known = set(actor_ids)
        for record in self.evidence:
            if len(set(record.visible_to_actor_ids)) != len(record.visible_to_actor_ids):
                raise ValueError(f"Duplicate visibility entry on {record.evidence_id!r}")
            unknown = set(record.visible_to_actor_ids) - known
            if unknown:
                raise ValueError(
                    f"Evidence {record.evidence_id!r} names unknown actors: {sorted(unknown)}"
                )
            if record.layer == EpistemicLayer.HIDDEN_TRUTH and record.visible_to_actor_ids:
                raise ValueError(
                    f"Hidden-truth record {record.evidence_id!r} must not list any actor"
                )
        return self

    def registry(self) -> EvidenceRegistry:
        return EvidenceRegistry(record.to_record() for record in self.evidence)


def load_manifest(source: str | Path) -> ScenarioManifest:
    """Parse a manifest from a JSON file path (``Path``) or a JSON string (``str``)."""
    text = source.read_text(encoding="utf-8") if isinstance(source, Path) else source
    return ScenarioManifest.model_validate_json(text)


def load_bundled_manifest(name: str = "synthetic_disclosure_demo") -> ScenarioManifest:
    """Load a packaged synthetic fixture by name (allowlisted; no path traversal)."""
    if name not in BUNDLED_FIXTURES:
        raise ValueError(f"Unknown bundled scenario: {name!r}")
    text = resources.files("indubio.scenarios").joinpath(
        "fixtures", f"{name}.json"
    ).read_text(encoding="utf-8")
    return load_manifest(text)


def build_engine(manifest: ScenarioManifest, mode: Mode = Mode.STRICT) -> SimulationEngine:
    """Initialize an engine from a validated manifest; the ruleset must be registered."""
    if not isinstance(manifest, ScenarioManifest):
        raise TypeError("build_engine requires a validated ScenarioManifest")
    config = SimulationConfig(jurisdiction=manifest.jurisdiction, mode=mode)
    return SimulationEngine(manifest.actors, config, evidence=manifest.registry())
