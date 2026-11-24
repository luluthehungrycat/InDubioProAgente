"""Scoped evidence registry: immutability, hidden-truth sealing and legacy ACL handling."""

import pytest

from indubio.core.engine import SimulationEngine
from indubio.core.models import (
    Actor,
    Mode,
    MovePhase,
    Phase,
    Proposal,
    Role,
    SimulationConfig,
    SubmitEvidence,
)
from indubio.evidence.models import EpistemicLayer, EvidenceRecord, visible_records
from indubio.evidence.registry import EvidenceRegistry

ACTOR_IDS = ("j", "p", "d")


@pytest.fixture
def actors():
    return [
        Actor(actor_id="j", role=Role.JUDGE, display_name="Synthetic Judge"),
        Actor(actor_id="p", role=Role.PROSECUTOR, display_name="Synthetic Prosecutor"),
        Actor(actor_id="d", role=Role.DEFENSE, display_name="Synthetic Defense"),
    ]


@pytest.fixture
def records():
    return [
        EvidenceRecord(
            evidence_id="truth", summary="Synthetic sealed fact",
            layer=EpistemicLayer.HIDDEN_TRUTH, visible_to_actor_ids=set(ACTOR_IDS),
        ),
        EvidenceRecord(
            evidence_id="exhibit_a", summary="Synthetic disclosed exhibit",
            layer=EpistemicLayer.DISCLOSED, visible_to_actor_ids={"j", "d"},
        ),
        EvidenceRecord(
            evidence_id="note_p", summary="Synthetic prosecution note",
            layer=EpistemicLayer.ACTOR_KNOWLEDGE, visible_to_actor_ids={"p"},
        ),
    ]


def ids(view):
    return [record.evidence_id for record in view]


def test_scoped_views_match_legacy_visibility_semantics(records):
    registry = EvidenceRegistry(records)
    for actor_id in (*ACTOR_IDS, "stranger"):
        assert ids(registry.visible_to(actor_id)) == ids(visible_records(records, actor_id))
    assert ids(registry.visible_to("j")) == ["exhibit_a"]
    assert ids(registry.visible_to("p")) == ["note_p"]
    assert registry.visible_to("stranger") == []


def test_hidden_truth_never_in_any_view_or_acl(actors, records):
    registry = EvidenceRegistry(records)
    for actor_id in ACTOR_IDS:
        assert "truth" not in ids(registry.visible_to(actor_id))
        assert "truth" not in registry.accessible_ids(actor_id)
    engine = SimulationEngine(actors, evidence=registry)
    for actor_id in ACTOR_IDS:
        view = engine.evidence_view(actor_id)
        assert all(r.layer != EpistemicLayer.HIDDEN_TRUTH for r in view)
        assert all("Synthetic sealed fact" not in r.model_dump_json() for r in view)


@pytest.mark.parametrize("mode", list(Mode))
def test_hidden_truth_cannot_be_submitted_in_any_mode(actors, records, mode):
    engine = SimulationEngine(
        actors, SimulationConfig(mode=mode), evidence=EvidenceRegistry(records)
    )
    engine.propose(Proposal(actor_id="j", action=MovePhase(destination=Phase.EVIDENCE)))
    for actor_id in ACTOR_IDS:
        event = engine.propose(
            Proposal(actor_id=actor_id, action=SubmitEvidence(evidence_id="truth"))
        )
        assert not event.accepted
        assert [f.rule_id for f in event.findings] == ["ACL_EVIDENCE"]


@pytest.mark.parametrize("mode", list(Mode))
def test_registry_scope_drives_engine_acl(actors, records, mode):
    engine = SimulationEngine(
        actors, SimulationConfig(mode=mode), evidence=EvidenceRegistry(records)
    )
    engine.propose(Proposal(actor_id="j", action=MovePhase(destination=Phase.EVIDENCE)))
    allowed = engine.propose(Proposal(actor_id="d", action=SubmitEvidence(evidence_id="exhibit_a")))
    denied = engine.propose(Proposal(actor_id="d", action=SubmitEvidence(evidence_id="note_p")))
    assert allowed.accepted and allowed.findings == []
    assert not denied.accepted and denied.findings[0].rule_id == "ACL_EVIDENCE"


def test_registry_is_isolated_from_input_mutation(actors, records):
    source = list(records)
    registry = EvidenceRegistry(source)
    engine = SimulationEngine(actors, evidence=registry)
    records[0].layer = EpistemicLayer.DISCLOSED
    records[1].visible_to_actor_ids.add("p")
    records[2].summary = "Edited"
    source.append(EvidenceRecord(
        evidence_id="late", summary="x", layer=EpistemicLayer.DISCLOSED,
        visible_to_actor_ids={"p"},
    ))
    assert ids(registry.visible_to("p")) == ["note_p"]
    assert registry.visible_to("p")[0].summary == "Synthetic prosecution note"
    assert "truth" not in registry.accessible_ids("j")
    assert ids(engine.evidence_view("p")) == ["note_p"]
    assert len(registry) == 3


def test_registry_is_isolated_from_output_mutation(actors, records):
    registry = EvidenceRegistry(records)
    engine = SimulationEngine(actors, evidence=registry)
    for view in (registry.visible_to("j"), engine.evidence_view("j")):
        view[0].visible_to_actor_ids.add("p")
        view[0].summary = "Tampered"
        view.append(records[0])
        view.clear()
    assert ids(registry.visible_to("p")) == ["note_p"]
    assert registry.visible_to("j")[0].summary == "Synthetic disclosed exhibit"
    assert ids(engine.evidence_view("j")) == ["exhibit_a"]
    assert "exhibit_a" not in registry.accessible_ids("p")


def test_registry_is_immutable(records):
    registry = EvidenceRegistry(records)
    with pytest.raises(AttributeError):
        registry._records = {}
    with pytest.raises(AttributeError):
        del registry._records
    with pytest.raises(TypeError):
        registry._records["x"] = records[0]
    with pytest.raises(AttributeError):
        registry.extra = 1


def test_registry_rejects_duplicates_and_foreign_types(records):
    with pytest.raises(ValueError):
        EvidenceRegistry([records[1], records[1].model_copy()])
    with pytest.raises(TypeError):
        EvidenceRegistry([{"evidence_id": "raw"}])


def test_engine_registry_validation(actors, records):
    registry = EvidenceRegistry(records)
    with pytest.raises(ValueError):
        SimulationEngine(actors, available_evidence={"d": {"exhibit_a"}}, evidence=registry)
    with pytest.raises(ValueError):
        SimulationEngine(actors[:1], evidence=registry)  # registry names unknown actors
    with pytest.raises(TypeError):
        SimulationEngine(actors, evidence=records)
    engine = SimulationEngine(actors, evidence=registry)
    with pytest.raises(PermissionError):
        engine.evidence_view("stranger")


def test_visible_records_returns_detached_copies(records):
    view = visible_records(records, "j")
    view[0].summary = "Tampered"
    assert records[1].summary == "Synthetic disclosed exhibit"


# --- Legacy available_evidence call pattern --------------------------------------------

@pytest.mark.parametrize("grant", [{"exhibit_a"}, ["exhibit_a"], ("exhibit_a",),
                                   frozenset({"exhibit_a"})])
def test_legacy_acl_accepts_collections(actors, grant):
    engine = SimulationEngine(
        actors, SimulationConfig(mode=Mode.REALISTIC), available_evidence={"d": grant}
    )
    event = engine.propose(Proposal(actor_id="d", action=SubmitEvidence(evidence_id="exhibit_a")))
    assert event.accepted
    assert engine.evidence_view("d") == []  # legacy grants carry no records to show


def test_legacy_acl_rejects_bare_string(actors):
    # Previously {"d": "ab"} silently granted evidence IDs "a" and "b".
    with pytest.raises(TypeError):
        SimulationEngine(actors, available_evidence={"d": "ab"})
    with pytest.raises(TypeError):
        SimulationEngine(actors, available_evidence={"d": [""]})


def test_legacy_acl_rejects_unknown_actor(actors):
    with pytest.raises(ValueError):
        SimulationEngine(actors, available_evidence={"ghost": {"exhibit_a"}})


def test_legacy_acl_snapshot_ignores_generator_reuse_and_later_edits(actors):
    grants = {"d": (x for x in ["exhibit_a"])}
    engine = SimulationEngine(
        actors, SimulationConfig(mode=Mode.REALISTIC), available_evidence=grants
    )
    grants["p"] = ["exhibit_a"]
    ok = engine.propose(Proposal(actor_id="d", action=SubmitEvidence(evidence_id="exhibit_a")))
    denied = engine.propose(Proposal(actor_id="p", action=SubmitEvidence(evidence_id="exhibit_a")))
    assert ok.accepted
    assert not denied.accepted and denied.findings[0].rule_id == "ACL_EVIDENCE"


# --- Lifecycle: reinitialization and view/ACL coherence ---------------------------------

@pytest.mark.parametrize("mode", [Mode.STRICT, Mode.REALISTIC])
def test_reinitialization_rejected_and_engine_view_acl_stay_coherent(actors, records, mode):
    registry = EvidenceRegistry(records)
    engine = SimulationEngine(actors, SimulationConfig(mode=mode), evidence=registry)
    replacement = [
        EvidenceRecord(
            evidence_id="planted", summary="Synthetic planted record",
            layer=EpistemicLayer.DISCLOSED, visible_to_actor_ids={"d"},
        )
    ]
    with pytest.raises(AttributeError):
        registry.__init__(replacement)
    with pytest.raises(AttributeError):
        EvidenceRegistry.__init__(registry, [])
    with pytest.raises(AttributeError):
        object.__setattr__(registry, "not_a_slot", {})
    # The caller's instance is unchanged.
    assert list(registry) == ["truth", "exhibit_a", "note_p"]

    # Even a forced slot overwrite on the caller's instance cannot reach the engine.
    EvidenceRegistry._records.__set__(registry, {})
    assert ids(engine.evidence_view("d")) == ["exhibit_a"]

    engine.propose(Proposal(actor_id="j", action=MovePhase(destination=Phase.EVIDENCE)))
    planted = engine.propose(
        Proposal(actor_id="d", action=SubmitEvidence(evidence_id="planted"))
    )
    assert not planted.accepted
    assert any(f.rule_id == "ACL_EVIDENCE" for f in planted.findings)
    submitted = engine.propose(
        Proposal(actor_id="d", action=SubmitEvidence(evidence_id="exhibit_a"))
    )
    assert submitted.accepted
    # Every ID an actor sees is submittable and vice versa (same snapshot).
    for actor_id in ACTOR_IDS:
        assert set(ids(engine.evidence_view(actor_id))) == engine._evidence_acl[actor_id]


def test_snapshot_is_independent_deep_copy(records):
    registry = EvidenceRegistry(records)
    copy = registry.snapshot()
    assert copy is not registry and list(copy) == list(registry)
    copy.visible_to("d")[0].summary = "Tampered"
    assert registry.visible_to("d")[0].summary == "Synthetic disclosed exhibit"
