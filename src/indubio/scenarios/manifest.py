"""Synthetic scenario manifest: a typed, versioned description of a case's initial state.

A manifest declares synthetic actors and the scenario-initial evidence records with their
epistemic layer and per-actor visibility. It is trusted setup input written by a scenario
author, never by an actor or model; ``build_engine`` turns it into a ``SimulationEngine``
with an immutable ``EvidenceRegistry``. After that, visibility only changes through
accepted ``DiscloseEvidence`` events.

Scope: synthetic fixtures only (``synthetic`` must be ``true``). No real-case import, no
legal characterization and no validated procedure. The manifest is plain data: loading
performs no network access and executes nothing.

Provenance: every event of an engine built here carries ``ScenarioProvenance`` (schema
version, scenario ID and version, and a deterministic SHA-256 digest of the normalized
setup the engine runs; see ``indubio.core.provenance``). Provenance is trusted audit data
and is never projected to actors.

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
from indubio.core.models import (
    Actor,
    Mode,
    ScenarioIdentity,
    ScenarioProvenance,
    SimulationConfig,
)
from indubio.core.provenance import scenario_provenance
from indubio.evidence.models import EpistemicLayer, EvidenceRecord
from indubio.evidence.registry import EvidenceRegistry
from indubio.jurisdictions.registry import get_floor_ruleset

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

    def identity(self) -> ScenarioIdentity:
        return ScenarioIdentity(
            scenario_schema_version=self.schema_version,
            scenario_id=self.scenario_id,
            scenario_version=self.scenario_version,
        )

    def provenance(self) -> ScenarioProvenance:
        """The provenance an engine built from this manifest stamps on its events.

        Trusted audit data (the digest covers sealed content); never hand it to actors.
        ``title`` and ``disclaimer`` are descriptive and not part of the engine setup, so
        they do not affect the digest; the identity fields are compared separately.
        """
        return scenario_provenance(
            self.identity(), self.jurisdiction, self.actors, self.registry()
        )


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


def build_engine(
    manifest: ScenarioManifest,
    mode: Mode = Mode.STRICT,
    *,
    floor_rules: str | None = None,
) -> SimulationEngine:
    """Initialize an engine from a validated manifest; the ruleset must be registered.

    ``floor_rules`` opts into floor control (``indubio.core.floor``) with the registered
    floor ruleset of that ID. It is a run parameter like ``mode``: it is recorded in every
    event's ``metadata``, not in the scenario setup digest, so the same manifest can be
    run with or without a speaking queue. Default ``None``: unscheduled, as before.
    """
    if not isinstance(manifest, ScenarioManifest):
        raise TypeError("build_engine requires a validated ScenarioManifest")
    if floor_rules is not None and not isinstance(floor_rules, str):
        raise TypeError("floor_rules must be a registered floor ruleset ID")
    config = SimulationConfig(jurisdiction=manifest.jurisdiction, mode=mode)
    engine = SimulationEngine(
        manifest.actors, config, evidence=manifest.registry(), scenario=manifest.identity(),
        floor_rules=get_floor_ruleset(floor_rules) if floor_rules is not None else None,
    )
    # Defense in depth: the engine digests its own snapshot; it must equal the digest of
    # the manifest as declared, or the manifest-to-engine conversion lost something.
    if engine.scenario_provenance != manifest.provenance():  # pragma: no cover - defensive
        raise RuntimeError("Engine setup does not match the scenario manifest")
    return engine
