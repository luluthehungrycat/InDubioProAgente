"""Versioned scenario provenance stamped on trusted committed events.

Provenance answers one audit question for every committed event: *which scenario setup
was this engine running?* It is trusted engine metadata, never actor input, and it is
never projected to actors (see "Privacy" below).

A ``ScenarioProvenance`` has two independent parts, and a consumer that checks a journal
against a scenario (``indubio.scenarios.restore``) must compare **all**
fields exactly:

* **Identity**, as declared by the scenario author: ``scenario_schema_version``,
  ``scenario_id`` and ``scenario_version``. Identity is a claim; it does not prove
  content.
* **Setup digest**: ``setup_digest`` is the SHA-256 of the canonical encoding of the
  normalized setup the engine actually runs (``canonical_setup_bytes``), computed by the
  engine from its own private snapshots, not from the caller's objects. Two setups the
  engine treats identically have the same digest; any setup difference the engine can
  observe changes it. ``setup_canonicalization`` and ``setup_digest_algorithm`` name the
  exact encoding and hash, so a future encoding is a new, explicit version rather than a
  silent change. ``provenance_schema`` versions this model itself.

Canonical setup (``indubio.scenario-setup/1``), one JSON object:

* ``canonicalization``: the literal ``"indubio.scenario-setup/1"`` (domain separation).
* ``jurisdiction``: the engine's ``SimulationConfig.jurisdiction`` (the ruleset ID). The
  ruleset version, the simulation mode and the opt-in floor ruleset are run parameters
  already recorded in each event's ``metadata``; they are not part of the scenario setup.
* ``actors``: every actor's ``actor_id``, ``role``, ``human_controlled`` and
  ``display_name``, **sorted by** ``actor_id``. Actor order is not semantic: the engine
  keys actors by ID and projections sort participants by ID.
* ``evidence``: every registry record (hidden truth included) with ``evidence_id``,
  ``summary``, ``layer``, ``visible_to_actor_ids`` (**sorted**; it is a set),
  ``provenance`` and ``source_timestamp``, **in registry order**. Evidence order is
  semantic: evidence views and projections list records in registry order.

Encoding: ``json.dumps`` with sorted keys, ``(",", ":")`` separators, ASCII-only escapes
and NaN rejected, then UTF-8. Strings are hashed exactly as the engine stores them (no
Unicode normalization or trimming), because the engine compares IDs exactly. Nothing
depends on ``PYTHONHASHSEED``, set iteration order or the process. The field lists are
explicit, and a test pins them to the model fields, so a new ``Actor`` or
``EvidenceRecord`` field forces a deliberate canonicalization version bump.

Privacy: the digest is unsalted and covers sealed hidden-truth content, so it is a
*confirmation oracle* (anyone holding it can test a guess of the full setup). It is
trusted audit data like the rest of the journal and must not be shown to actors.
Projections never include event ``scenario`` provenance or ``metadata``.

Not covered: the digest binds setup content, not authorship or integrity of the journal
(not tamper-evident, no signature). Restoring engine state from a journal is
``indubio.scenarios.restore``, which checks this provenance and regenerates every event.
"""

import hashlib
import json
from collections.abc import Iterable

from indubio.core.models import (
    PROVENANCE_SCHEMA,
    SETUP_CANONICALIZATION,
    SETUP_DIGEST_ALGORITHM,
    Actor,
    ScenarioIdentity,
    ScenarioProvenance,
)
from indubio.evidence.registry import EvidenceRegistry

# Explicit canonical field lists (see module docstring); pinned to the models by tests.
CANONICAL_ACTOR_FIELDS = ("actor_id", "role", "human_controlled", "display_name")
CANONICAL_EVIDENCE_FIELDS = (
    "evidence_id", "summary", "layer", "visible_to_actor_ids", "provenance",
    "source_timestamp",
)


def _canonical_setup(
    jurisdiction: str, actors: Iterable[Actor], evidence: EvidenceRegistry
) -> dict[str, object]:
    actor_docs = []
    for actor in actors:
        if not isinstance(actor, Actor):
            raise TypeError("Canonical setup requires Actor instances")
        actor_docs.append({
            "actor_id": actor.actor_id,
            "role": str(actor.role.value),
            "human_controlled": bool(actor.human_controlled),
            "display_name": actor.display_name,
        })
    actor_docs.sort(key=lambda doc: doc["actor_id"])
    ids = [doc["actor_id"] for doc in actor_docs]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate actor IDs in canonical setup")
    if not isinstance(evidence, EvidenceRegistry):
        raise TypeError("Canonical setup requires an EvidenceRegistry")
    evidence_docs = []
    for evidence_id in evidence:  # registry order is semantic and preserved
        record = evidence.get(evidence_id)
        evidence_docs.append({
            "evidence_id": record.evidence_id,
            "summary": record.summary,
            "layer": str(record.layer.value),
            "visible_to_actor_ids": sorted(record.visible_to_actor_ids),
            "provenance": record.provenance,
            "source_timestamp": record.source_timestamp,
        })
    return {
        "canonicalization": SETUP_CANONICALIZATION,
        "jurisdiction": jurisdiction,
        "actors": actor_docs,
        "evidence": evidence_docs,
    }


def canonical_setup_bytes(
    jurisdiction: str, actors: Iterable[Actor], evidence: EvidenceRegistry
) -> bytes:
    """Deterministic canonical encoding of a normalized engine setup (trusted API)."""
    document = _canonical_setup(jurisdiction, actors, evidence)
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def setup_digest(jurisdiction: str, actors: Iterable[Actor], evidence: EvidenceRegistry) -> str:
    """Lowercase hex SHA-256 of ``canonical_setup_bytes``."""
    return hashlib.sha256(canonical_setup_bytes(jurisdiction, actors, evidence)).hexdigest()


def scenario_provenance(
    identity: ScenarioIdentity,
    jurisdiction: str,
    actors: Iterable[Actor],
    evidence: EvidenceRegistry,
) -> ScenarioProvenance:
    if type(identity) is not ScenarioIdentity:
        # Exact type: a ready-made provenance (or a subclass) would let a caller assert a
        # digest instead of the engine computing it from what it actually runs.
        raise TypeError("identity must be a ScenarioIdentity (the digest is engine-computed)")
    # Revalidate: a ``model_construct``-built identity must not bypass field checks.
    identity = ScenarioIdentity.model_validate(identity.model_dump())
    return ScenarioProvenance(
        provenance_schema=PROVENANCE_SCHEMA,
        setup_canonicalization=SETUP_CANONICALIZATION,
        setup_digest_algorithm=SETUP_DIGEST_ALGORITHM,
        scenario_schema_version=identity.scenario_schema_version,
        scenario_id=identity.scenario_id,
        scenario_version=identity.scenario_version,
        setup_digest=setup_digest(jurisdiction, actors, evidence),
    )


__all__ = [
    "CANONICAL_ACTOR_FIELDS",
    "CANONICAL_EVIDENCE_FIELDS",
    "PROVENANCE_SCHEMA",
    "SETUP_CANONICALIZATION",
    "SETUP_DIGEST_ALGORITHM",
    "ScenarioIdentity",
    "ScenarioProvenance",
    "canonical_setup_bytes",
    "scenario_provenance",
    "setup_digest",
]
