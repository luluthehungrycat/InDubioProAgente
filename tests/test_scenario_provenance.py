"""Scenario provenance on committed events: stability, binding, privacy, persistence."""

import json
import os
import subprocess
import sys
import unicodedata

import pytest
from pydantic import ValidationError

from indubio.core.engine import SimulationEngine
from indubio.core.models import (
    Actor,
    Mode,
    Proposal,
    Role,
    ScenarioIdentity,
    ScenarioProvenance,
    SimulationConfig,
    Speak,
    SubmitEvidence,
    TrialEvent,
)
from indubio.core.projection import PerspectiveProjection, ProjectedEvent
from indubio.core.provenance import (
    CANONICAL_ACTOR_FIELDS,
    CANONICAL_EVIDENCE_FIELDS,
    canonical_setup_bytes,
    scenario_provenance,
    setup_digest,
)
from indubio.evidence.models import EpistemicLayer, EvidenceRecord
from indubio.evidence.registry import EvidenceRegistry
from indubio.persistence.sqlite import EventStore
from indubio.scenarios import ScenarioManifest, build_engine, load_bundled_manifest
from indubio.scenarios.demo import SCENARIO_DEMO_SCRIPT, run_scenario_demo

JURISDICTION = "de-criminal-demo-unvalidated"
VIEWERS = ["judge", "pros", "def", "acc", "wit", "obs"]
# Golden digest of the bundled fixture's normalized setup. If this changes, the fixture or
# the canonical encoding changed: bump ``scenario_version`` or the canonicalization
# version deliberately instead of updating this value silently.
BUNDLED_DIGEST = "e6563c8de315765107b290a0ca25a535d03a56599eaeac909496b94165e2a126"
IDENTITY = ScenarioIdentity(
    scenario_schema_version="indubio.scenario/1", scenario_id="s1", scenario_version="1"
)


def manifest_data():
    return load_bundled_manifest().model_dump(mode="json")


def manifest(**overrides):
    data = manifest_data()
    data.update(overrides)
    return ScenarioManifest.model_validate(data)


def digest_of(data):
    return ScenarioManifest.model_validate(data).provenance().setup_digest


def actors():
    return [
        Actor(actor_id="j", role=Role.JUDGE, display_name="J"),
        Actor(actor_id="p", role=Role.PROSECUTOR, display_name="P"),
        Actor(actor_id="d", role=Role.DEFENSE, display_name="D"),
    ]


def records():
    return [
        EvidenceRecord(evidence_id="e1", summary="Synthetic", layer=EpistemicLayer.ACTOR_KNOWLEDGE,
                       visible_to_actor_ids={"p", "d"}),
        EvidenceRecord(evidence_id="sealed", summary="Synthetic sealed fact",
                       layer=EpistemicLayer.HIDDEN_TRUTH),
    ]


# --- stamping on committed events -------------------------------------------------------

@pytest.mark.parametrize("mode", list(Mode))
def test_every_event_accepted_or_rejected_carries_the_manifest_provenance(mode):
    expected = load_bundled_manifest().provenance()
    engine = run_scenario_demo(mode)
    events = engine.events
    assert len(events) == len(SCENARIO_DEMO_SCRIPT)
    assert {event.accepted for event in events} == {True, False}
    assert all(event.scenario == expected for event in events)
    assert engine.scenario_provenance == expected


def test_bundled_provenance_identity_and_golden_digest():
    provenance = load_bundled_manifest().provenance()
    assert provenance.provenance_schema == "indubio.scenario-provenance/1"
    assert provenance.scenario_schema_version == "indubio.scenario/1"
    assert provenance.scenario_id == "synthetic-disclosure-demo"
    assert provenance.scenario_version == "1.0.0"
    assert provenance.setup_canonicalization == "indubio.scenario-setup/1"
    assert provenance.setup_digest_algorithm == "sha256"
    assert provenance.setup_digest == BUNDLED_DIGEST
    assert provenance.identity == load_bundled_manifest().identity()


def test_mode_is_a_run_parameter_not_part_of_the_setup():
    strict = build_engine(load_bundled_manifest(), Mode.STRICT)
    realistic = build_engine(load_bundled_manifest(), Mode.REALISTIC)
    assert strict.scenario_provenance == realistic.scenario_provenance


def test_direct_engine_digest_matches_standalone_function():
    engine = SimulationEngine(actors(), evidence=EvidenceRegistry(records()), scenario=IDENTITY)
    event = engine.propose(Proposal(actor_id="j", action=Speak(text="Synthetic")))
    assert event.scenario.setup_digest == setup_digest(
        JURISDICTION, actors(), EvidenceRegistry(records()))
    assert event.scenario.identity == IDENTITY


# --- determinism and normalization ------------------------------------------------------

@pytest.mark.parametrize("seed", ["0", "1", "4242", "random"])
def test_digest_is_stable_across_processes_and_hash_seeds(seed):
    code = (
        "from indubio.scenarios.demo import run_scenario_demo\n"
        "engine = run_scenario_demo()\n"
        "print(engine.events[-1].scenario.setup_digest)\n"
    )
    env = {**os.environ, "PYTHONHASHSEED": seed}
    out = subprocess.run([sys.executable, "-c", code], env=env, check=True,
                         capture_output=True, text=True).stdout.strip()
    assert out == BUNDLED_DIGEST


def test_actor_order_is_not_semantic():
    data = manifest_data()
    data["actors"] = list(reversed(data["actors"]))
    assert digest_of(data) == BUNDLED_DIGEST


def test_visibility_order_is_not_semantic():
    data = manifest_data()
    for record in data["evidence"]:
        record["visible_to_actor_ids"] = list(reversed(record["visible_to_actor_ids"]))
    assert digest_of(data) == BUNDLED_DIGEST
    # Set iteration order never leaks into the encoding.
    first = canonical_setup_bytes(JURISDICTION, actors(), EvidenceRegistry(records()))
    reordered = [records()[0].model_copy(update={"visible_to_actor_ids": {"d", "p"}}),
                 records()[1]]
    assert canonical_setup_bytes(JURISDICTION, actors(), EvidenceRegistry(reordered)) == first


def test_evidence_order_is_semantic():
    data = manifest_data()
    data["evidence"] = list(reversed(data["evidence"]))
    assert digest_of(data) != BUNDLED_DIGEST


def test_descriptive_fields_do_not_change_the_digest_but_identity_is_kept_apart():
    renamed = manifest(title="Other title", disclaimer="Other synthetic disclaimer")
    assert renamed.provenance() == load_bundled_manifest().provenance()
    bumped = manifest(scenario_version="1.0.1").provenance()
    assert bumped.setup_digest == BUNDLED_DIGEST
    assert bumped != load_bundled_manifest().provenance()
    other_id = manifest(scenario_id="another-synthetic").provenance()
    assert other_id.identity != load_bundled_manifest().identity()


ACTOR_EDITS = [
    ("display_name", "Renamed"),
    ("role", "defense"),
    ("human_controlled", True),
]
EVIDENCE_EDITS = [
    ("summary", "SYNTHETIC: changed"),
    ("layer", "disclosed"),
    ("visible_to_actor_ids", ["pros", "def"]),
    ("provenance", "other synthetic source"),
    ("source_timestamp", "2026-01-01T00:00:00Z"),
]


@pytest.mark.parametrize("field,value", ACTOR_EDITS)
def test_every_actor_field_changes_the_digest(field, value):
    data = manifest_data()
    data["actors"][1][field] = value  # "pros"
    assert digest_of(data) != BUNDLED_DIGEST


@pytest.mark.parametrize("field,value", EVIDENCE_EDITS)
def test_every_evidence_field_changes_the_digest(field, value):
    data = manifest_data()
    data["evidence"][1][field] = value  # "pros-vendor-log"
    assert digest_of(data) != BUNDLED_DIGEST


def test_sealed_truth_content_is_bound_and_ids_are_not_unicode_normalized():
    data = manifest_data()
    data["evidence"][-1]["summary"] = "SYNTHETIC SEALED TRUTH: a different fictional origin"
    assert digest_of(data) != BUNDLED_DIGEST
    nfc = unicodedata.normalize("NFC", "zeuge-ä")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    a = [Actor(actor_id=nfc, role=Role.WITNESS, display_name="W")]
    b = [Actor(actor_id=nfd, role=Role.WITNESS, display_name="W")]
    assert setup_digest(JURISDICTION, a, EvidenceRegistry()) != setup_digest(
        JURISDICTION, b, EvidenceRegistry())


def test_jurisdiction_and_actor_set_are_bound():
    base = setup_digest(JURISDICTION, actors(), EvidenceRegistry(records()))
    assert setup_digest("other-ruleset", actors(), EvidenceRegistry(records())) != base
    assert setup_digest(JURISDICTION, actors()[:2], EvidenceRegistry(records())) != base


def test_canonical_encoding_shape():
    raw = canonical_setup_bytes(JURISDICTION, list(reversed(actors())), EvidenceRegistry(records()))
    raw.decode("ascii")  # ASCII-only escapes
    document = json.loads(raw)
    assert document["canonicalization"] == "indubio.scenario-setup/1"
    assert document["jurisdiction"] == JURISDICTION
    assert [a["actor_id"] for a in document["actors"]] == ["d", "j", "p"]
    assert [e["evidence_id"] for e in document["evidence"]] == ["e1", "sealed"]
    assert document["evidence"][0]["visible_to_actor_ids"] == ["d", "p"]
    assert raw == json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def test_canonical_field_lists_cover_every_model_field():
    # Adding a field to Actor or EvidenceRecord must be a deliberate canonicalization bump.
    assert set(CANONICAL_ACTOR_FIELDS) == set(Actor.model_fields)
    assert set(CANONICAL_EVIDENCE_FIELDS) == set(EvidenceRecord.model_fields)
    document = json.loads(canonical_setup_bytes(
        JURISDICTION, actors(), EvidenceRegistry(records())))
    assert set(document["actors"][0]) == set(CANONICAL_ACTOR_FIELDS)
    assert set(document["evidence"][0]) == set(CANONICAL_EVIDENCE_FIELDS)


def test_duplicate_actor_ids_cannot_be_digested():
    with pytest.raises(ValueError):
        setup_digest(JURISDICTION, actors() + actors()[:1], EvidenceRegistry())


# --- mutation isolation -----------------------------------------------------------------

def test_caller_mutation_after_construction_cannot_change_provenance():
    caller_actors = actors()
    caller_records = records()
    registry = EvidenceRegistry(caller_records)
    config = SimulationConfig()
    engine = SimulationEngine(caller_actors, config, evidence=registry, scenario=IDENTITY)
    before = engine.scenario_provenance
    caller_actors[0].display_name = "Edited"
    caller_records[0].summary = "Edited"
    config.jurisdiction = "edited"
    event = engine.propose(Proposal(actor_id="j", action=Speak(text="Synthetic")))
    assert event.scenario == before == scenario_provenance(
        IDENTITY, JURISDICTION, actors(), EvidenceRegistry(records()))


def test_provenance_on_returned_events_is_immutable_and_detached():
    engine = run_scenario_demo()
    event = engine.events[0]
    with pytest.raises(ValidationError):
        event.scenario.setup_digest = "0" * 64
    event.scenario = None
    assert engine.events[0].scenario == load_bundled_manifest().provenance()


# --- validation and trust boundary ------------------------------------------------------

def test_engine_refuses_a_caller_asserted_digest():
    forged = load_bundled_manifest().provenance()
    with pytest.raises(TypeError):
        SimulationEngine(actors(), evidence=EvidenceRegistry(records()), scenario=forged)


def test_engine_refuses_an_unvalidated_identity():
    bad = ScenarioIdentity.model_construct(
        scenario_schema_version="indubio.scenario/1", scenario_id="", scenario_version="1")
    with pytest.raises(ValidationError):
        SimulationEngine(actors(), evidence=EvidenceRegistry(records()), scenario=bad)


def test_scenario_provenance_requires_a_registry_not_a_legacy_acl():
    with pytest.raises(ValueError):
        SimulationEngine(actors(), available_evidence={"p": ["e1"]}, scenario=IDENTITY)


@pytest.mark.parametrize("update", [
    {"setup_digest": "E" * 64},
    {"setup_digest": "abc"},
    {"provenance_schema": "indubio.scenario-provenance/2"},
    {"setup_canonicalization": "indubio.scenario-setup/2"},
    {"setup_digest_algorithm": "md5"},
    {"scenario_id": ""},
    {"unexpected": "field"},
])
def test_provenance_model_fails_closed(update):
    data = load_bundled_manifest().provenance().model_dump()
    data.update(update)
    with pytest.raises(ValidationError):
        ScenarioProvenance.model_validate(data)


# --- persistence and legacy compatibility ----------------------------------------------

def test_provenance_round_trips_through_sqlite(tmp_path):
    engine = run_scenario_demo(Mode.REALISTIC)
    store = EventStore(tmp_path / "events.sqlite")
    for event in engine.events:
        store.append("sim-1", event)
    loaded = store.load("sim-1")
    raw = store.connection.execute("SELECT payload FROM events ORDER BY sequence").fetchall()
    store.close()
    assert loaded == engine.events
    assert all(event.scenario == engine.scenario_provenance for event in loaded)
    assert all(json.loads(row[0])["scenario"]["setup_digest"] == BUNDLED_DIGEST for row in raw)


def test_pre_provenance_journal_payload_loads_and_keeps_its_exact_shape():
    payload = (
        '{"sequence":1,"actor_id":"d","phase_before":"opening","phase_after":"opening",'
        '"proposal":{"actor_id":"d","action":{"kind":"speak","text":"No comment"}},'
        '"accepted":true,"findings":[],"metadata":{"mode":"strict",'
        '"ruleset":"de-criminal-demo-unvalidated","ruleset_version":"0.1.0-demo",'
        '"ruleset_validation":"unvalidated_demonstrator"}}'
    )
    event = TrialEvent.model_validate_json(payload)
    assert event.scenario is None
    assert event.model_dump_json() == payload


def test_direct_engine_events_have_no_provenance_and_unchanged_shape(tmp_path):
    engine = SimulationEngine([Actor(actor_id="d", role=Role.DEFENDANT, display_name="D")])
    event = engine.propose(Proposal(actor_id="d", action=Speak(text="No comment")))
    assert engine.scenario_provenance is None and event.scenario is None
    assert "scenario" not in json.loads(event.model_dump_json())
    assert "scenario" not in event.model_dump()
    store = EventStore(tmp_path / "events.sqlite")
    store.append("case", event)
    assert store.load("case") == [event]
    store.close()


def test_direct_registry_engine_without_identity_has_no_provenance():
    engine = SimulationEngine(actors(), evidence=EvidenceRegistry(records()))
    event = engine.propose(Proposal(actor_id="p", action=SubmitEvidence(evidence_id="e1")))
    assert event.scenario is None


# --- privacy ----------------------------------------------------------------------------

def test_provenance_is_never_projected_to_actors():
    assert "scenario" not in ProjectedEvent.model_fields
    assert "scenario" not in PerspectiveProjection.model_fields
    for mode in Mode:
        engine = run_scenario_demo(mode)
        for viewer in VIEWERS:
            dumped = engine.perspective(viewer).model_dump_json()
            assert BUNDLED_DIGEST not in dumped
            assert "synthetic-disclosure-demo" not in dumped
            assert "scenario-provenance" not in dumped
            assert "setup_digest" not in dumped
