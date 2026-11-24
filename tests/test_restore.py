"""Engine restoration from a trusted journal and its synthetic scenario manifest.

Synthetic actors and records only; the procedural rules are an unvalidated demonstrator.
"""

import json

import pytest

from indubio.core.engine import SimulationEngine
from indubio.core.models import (
    Actor,
    DiscloseEvidence,
    FileMotion,
    Mode,
    MovePhase,
    Object,
    Phase,
    Proposal,
    Role,
    RuleOnMotion,
    Speak,
    SubmitEvidence,
    TrialEvent,
)
from indubio.persistence.sqlite import EventStore
from indubio.scenarios import (
    LegacyJournalError,
    RestoreError,
    ScenarioManifest,
    build_engine,
    load_bundled_manifest,
    restore_engine,
    restore_from_store,
)
from indubio.scenarios.demo import SCENARIO_DEMO_SCRIPT

ALL_MODES = list(Mode)
VIEWERS = ["judge", "pros", "def", "acc", "wit", "obs"]

# The disclosure demo plus motions, a ruling, an objection and rejected attempts, so the
# history exercises phase, motions, grants, event-time redaction and rejected events.
SCRIPT: tuple[Proposal, ...] = SCENARIO_DEMO_SCRIPT[:7] + (
    Proposal(actor_id="def", action=FileMotion(motion_id="m1", grounds="Synthetic grounds")),
    # strict: rejected (duplicate); realistic: accepted with DEMO_MOTION_DUPLICATE.
    Proposal(actor_id="pros", action=FileMotion(motion_id="m1", grounds="Synthetic again")),
    Proposal(actor_id="judge", action=RuleOnMotion(
        motion_id="m1", ruling="denied", reasons="Synthetic reasons")),
    Proposal(actor_id="pros", action=Object(target_event_sequence=5, grounds="Synthetic")),
    # rejected in every mode: witness cannot move the phase.
    Proposal(actor_id="wit", action=MovePhase(destination=Phase.CLOSING)),
    Proposal(actor_id="acc", action=Speak(text="Synthetic statement")),
) + SCENARIO_DEMO_SCRIPT[7:]
NEXT = Proposal(actor_id="pros", action=SubmitEvidence(evidence_id="def-chat-export"))


def run(mode: Mode = Mode.STRICT, script=SCRIPT) -> SimulationEngine:
    engine = build_engine(load_bundled_manifest(), mode)
    for proposal in script:
        engine.propose(proposal)
    return engine


def journal(tmp_path, events, simulation_id="case"):
    store = EventStore(tmp_path / "events.sqlite3")
    for event in events:
        store.append(simulation_id, event)
    return store


def rows(store):
    return store.connection.execute(
        "SELECT simulation_id, sequence, payload FROM events ORDER BY simulation_id, sequence"
    ).fetchall()


def assert_same_state(restored: SimulationEngine, original: SimulationEngine) -> None:
    assert restored.events == original.events
    assert [e.model_dump_json() for e in restored.events] == [
        e.model_dump_json() for e in original.events
    ]
    assert restored.phase == original.phase
    assert restored.config == original.config
    assert restored.scenario_provenance == original.scenario_provenance
    assert restored._motions == original._motions
    assert restored._grants == original._grants
    for viewer in VIEWERS:
        assert restored.perspective(viewer) == original.perspective(viewer)
        assert restored.evidence_view(viewer) == original.evidence_view(viewer)


# --- positive restoration ------------------------------------------------------------


@pytest.mark.parametrize("mode", ALL_MODES)
def test_restores_full_state_from_sqlite_and_continues(tmp_path, mode):
    original = run(mode)
    events = original.events
    assert any(not e.accepted for e in events)  # rejected events are part of the check
    store = journal(tmp_path, events)

    restored = restore_from_store(store, "case", load_bundled_manifest())

    assert_same_state(restored, original)
    assert restored.config.mode == mode
    assert restored.phase == Phase.CLOSING
    # Strict rejected the duplicate filing; realistic accepted it with a finding.
    assert restored._motions == ({"m1": "def"} if mode == Mode.STRICT else {"m1": "pros"})
    assert restored._grants["def"] == {"pros-vendor-log": 1}
    assert restored._grants["pros"] == {"def-chat-export": 7}
    # Continue: the next proposal gets the next sequence number and identical outcome.
    expected = original.propose(NEXT)
    continued = restored.propose(NEXT)
    assert continued == expected and continued.sequence == len(events) + 1
    assert_same_state(restored, original)
    store.close()


def test_restored_motion_and_phase_state_drive_later_checks(tmp_path):
    restored = restore_engine(load_bundled_manifest(), run(Mode.STRICT).events)
    # Motion m1 was restored: a new duplicate is rejected and a ruling on it is accepted.
    dup = restored.propose(Proposal(actor_id="def", action=FileMotion(
        motion_id="m1", grounds="Synthetic")))
    assert not dup.accepted and [f.rule_id for f in dup.findings] == ["DEMO_MOTION_DUPLICATE"]
    # Phase CLOSING was restored: CLOSING -> JUDGMENT is the in-order transition.
    move = restored.propose(Proposal(actor_id="judge", action=MovePhase(
        destination=Phase.JUDGMENT)))
    assert move.accepted and move.phase_before == Phase.CLOSING


def test_restored_grants_and_event_time_projection(tmp_path):
    restored = restore_engine(load_bundled_manifest(), run(Mode.STRICT).events)
    pros = restored.perspective("pros")
    # Prosecution received the chat export at event 7; event 5 stays redacted for it.
    assert {e.evidence_id: e.disclosed_at_sequence for e in pros.evidence}[
        "def-chat-export"] == 7
    assert pros.events[4].redacted_fields
    # The restored grant lets prosecution submit the export now (in the evidence-free
    # closing phase this is procedural only, so strict rejects without an ACL finding).
    event = restored.propose(NEXT)
    assert [f.rule_id for f in event.findings] == ["DEMO_EVIDENCE_PHASE"]


def test_restore_engine_accepts_in_memory_history_and_detaches_it():
    original = run()
    events = original.events
    restored = restore_engine(load_bundled_manifest(), events)
    events[0].proposal.action.recipient_actor_id = "acc"  # caller edit after restore
    events.clear()
    assert_same_state(restored, original)


@pytest.mark.parametrize("mode", ALL_MODES)
def test_explicit_matching_mode_is_accepted(mode):
    restored = restore_engine(load_bundled_manifest(), run(mode).events, mode=mode.value)
    assert restored.config.mode == mode


def test_bundled_demo_script_restores():
    original = run(Mode.REALISTIC, SCENARIO_DEMO_SCRIPT)
    assert_same_state(restore_engine(load_bundled_manifest(), original.events), original)


# --- empty history -------------------------------------------------------------------


@pytest.mark.parametrize("mode", [None, *ALL_MODES])
def test_empty_history_is_a_fresh_engine(tmp_path, mode):
    restored = restore_engine(load_bundled_manifest(), [], mode=mode)
    fresh = build_engine(load_bundled_manifest(), mode or Mode.STRICT)
    assert_same_state(restored, fresh)
    assert restored.events == [] and restored.phase == Phase.OPENING
    assert restored.propose(NEXT).sequence == 1


def test_unknown_simulation_id_restores_as_empty(tmp_path):
    store = journal(tmp_path, run().events)
    restored = restore_from_store(store, "no-such-case", load_bundled_manifest())
    assert restored.events == []
    store.close()


# --- legacy and ineligible journals --------------------------------------------------


def test_direct_engine_journal_is_legacy_but_still_loadable(tmp_path):
    engine = SimulationEngine([Actor(actor_id="d", role=Role.DEFENDANT, display_name="D")])
    engine.propose(Proposal(actor_id="d", action=Speak(text="Synthetic")))
    store = journal(tmp_path, engine.events)
    assert store.load("case") == engine.events
    with pytest.raises(LegacyJournalError):
        restore_from_store(store, "case", load_bundled_manifest())
    store.close()


def test_pre_provenance_payload_is_legacy_but_still_loadable(tmp_path):
    events = run().events
    store = EventStore(tmp_path / "events.sqlite3")
    for event in events:
        payload = json.loads(event.model_dump_json())
        del payload["scenario"]  # exact pre-provenance payload shape
        store.connection.execute(
            "INSERT INTO events VALUES (?, ?, ?)", ("case", event.sequence, json.dumps(payload))
        )
    store.connection.commit()
    loaded = store.load("case")
    assert len(loaded) == len(events) and all(e.scenario is None for e in loaded)
    with pytest.raises(LegacyJournalError, match="EventStore.load"):
        restore_from_store(store, "case", load_bundled_manifest())
    store.close()


def test_mixed_stamped_and_unstamped_is_inconsistent_not_legacy():
    events = run().events
    events[3] = events[3].model_copy(update={"scenario": None})
    with pytest.raises(RestoreError, match="mixes") as info:
        restore_engine(load_bundled_manifest(), events)
    assert not isinstance(info.value, LegacyJournalError)


# --- sequence shape ------------------------------------------------------------------


@pytest.mark.parametrize("edit", ["gap", "duplicate", "reorder", "start_at_two"])
def test_non_contiguous_sequences_are_refused(edit):
    events = run().events
    if edit == "gap":
        del events[2]
    elif edit == "duplicate":
        events.insert(3, events[2])
    elif edit == "reorder":
        events[1], events[2] = events[2], events[1]
    else:
        del events[0]
    with pytest.raises(RestoreError, match="contiguous"):
        restore_engine(load_bundled_manifest(), events)


def test_truncated_prefix_restores_but_is_a_different_history():
    events = run().events
    restored = restore_engine(load_bundled_manifest(), events[:4])
    assert restored.events == events[:4]


def test_row_key_must_match_payload_sequence(tmp_path):
    events = run().events
    store = EventStore(tmp_path / "events.sqlite3")
    for key, event in enumerate(events, start=1):
        store.connection.execute(
            "INSERT INTO events VALUES (?, ?, ?)",
            ("case", key if key < 3 else key + 10, event.model_dump_json()),
        )
    store.connection.commit()
    with pytest.raises(RestoreError, match="row key"):
        restore_from_store(store, "case", load_bundled_manifest())
    store.close()


def test_unparseable_payload_is_refused(tmp_path):
    store = journal(tmp_path, run().events)
    store.connection.execute(
        "UPDATE events SET payload = '{\"sequence\": 2}' WHERE sequence = 2")
    store.connection.commit()
    with pytest.raises(RestoreError, match="payload"):
        restore_from_store(store, "case", load_bundled_manifest())
    store.close()


# --- scenario identity and digest ----------------------------------------------------


def manifest_with(**overrides) -> ScenarioManifest:
    data = load_bundled_manifest().model_dump(mode="json")
    data.update(overrides)
    return ScenarioManifest.model_validate(data)


def test_other_scenario_version_is_refused():
    with pytest.raises(RestoreError, match="scenario_version"):
        restore_engine(manifest_with(scenario_version="1.0.1"), run().events)


def test_other_setup_content_is_refused_by_digest():
    data = load_bundled_manifest().model_dump(mode="json")
    data["evidence"][-1]["summary"] = "SYNTHETIC SEALED TRUTH: a different origin"
    with pytest.raises(RestoreError, match="setup_digest"):
        restore_engine(ScenarioManifest.model_validate(data), run().events)


def test_descriptive_manifest_fields_do_not_block_restoration():
    restored = restore_engine(manifest_with(title="Retitled synthetic demo"), run().events)
    assert len(restored.events) == len(SCRIPT)


@pytest.mark.parametrize("field", ["scenario_id", "setup_digest"])
def test_single_event_provenance_edit_is_refused(field):
    events = run().events
    value = "0" * 64 if field == "setup_digest" else "other-scenario"
    events[5] = events[5].model_copy(
        update={"scenario": events[5].scenario.model_copy(update={field: value})})
    with pytest.raises(RestoreError, match=f"Event 6 .*{field}"):
        restore_engine(load_bundled_manifest(), events)


# --- ruleset metadata and mode -------------------------------------------------------


def with_metadata(events, index, **changes):
    metadata = dict(events[index].metadata)
    for key, value in changes.items():
        if value is None:
            metadata.pop(key)
        else:
            metadata[key] = value
    events[index] = events[index].model_copy(update={"metadata": metadata})
    return events


@pytest.mark.parametrize("changes,match", [
    ({"ruleset_version": "0.1.0-demo"}, "no migrations"),
    ({"ruleset_validation": "human_reviewed"}, "no migrations"),
    ({"ruleset": "other-ruleset"}, "no migrations"),
    ({"extra": "x"}, "metadata keys"),
    ({"mode": None}, "metadata keys"),
    ({"mode": "lenient"}, "unsupported mode"),
])
def test_ruleset_metadata_must_match_pinned_values(changes, match):
    events = with_metadata(run().events, 2, **changes)
    with pytest.raises(RestoreError, match=match):
        restore_engine(load_bundled_manifest(), events)


def test_live_mode_change_journal_is_refused():
    engine = build_engine(load_bundled_manifest(), Mode.STRICT)
    for index, proposal in enumerate(SCRIPT):
        if index == 5:
            engine.config.mode = Mode.REALISTIC  # public, mutable, not an event
        engine.propose(proposal)
    with pytest.raises(RestoreError, match="changes mode"):
        restore_engine(load_bundled_manifest(), engine.events)


def test_requested_mode_must_match_journal_mode():
    with pytest.raises(RestoreError, match="Requested mode"):
        restore_engine(load_bundled_manifest(), run(Mode.STRICT).events, mode=Mode.REALISTIC)


def test_relabeled_mode_fails_regeneration():
    # All events claim realistic, but the strict run rejected procedural attempts.
    events = run(Mode.STRICT).events
    for index in range(len(events)):
        with_metadata(events, index, mode="realistic")
    with pytest.raises(RestoreError, match="differs from its regeneration in: accepted"):
        restore_engine(load_bundled_manifest(), events)


# --- regeneration equality -----------------------------------------------------------


def test_flipped_rejection_is_refused():
    events = run().events
    index = next(i for i, e in enumerate(events) if not e.accepted)
    events[index] = events[index].model_copy(update={"accepted": True})
    with pytest.raises(RestoreError, match=f"Event {index + 1} differs .*accepted"):
        restore_engine(load_bundled_manifest(), events)


@pytest.mark.parametrize("update", [
    {"findings": []},
    {"phase_after": Phase.JUDGMENT},
    {"actor_id": "judge"},
])
def test_any_recorded_field_must_regenerate(update):
    events = run().events
    index = next(i for i, e in enumerate(events) if not e.accepted)
    events[index] = events[index].model_copy(update=update)
    with pytest.raises(RestoreError, match="differs from its regeneration"):
        restore_engine(load_bundled_manifest(), events)


def test_edited_proposal_changes_outcome_and_is_refused():
    # Event 1 accepted a disclosure; editing its evidence ID to sealed truth would be
    # rejected by the engine, so the recorded outcome cannot regenerate.
    events = run().events
    proposal = events[0].proposal.model_copy(update={"action": DiscloseEvidence(
        evidence_id="sealed-origin", recipient_actor_id="def")})
    events[0] = events[0].model_copy(update={"proposal": proposal})
    with pytest.raises(RestoreError, match="Event 1 differs .*accepted.*findings"):
        restore_engine(load_bundled_manifest(), events)


def test_unknown_actor_proposal_is_refused():
    events = run().events
    proposal = events[3].proposal.model_copy(update={"actor_id": "ghost"})
    events[3] = events[3].model_copy(update={"proposal": proposal, "actor_id": "ghost"})
    with pytest.raises(RestoreError, match="Event 4 could not be regenerated"):
        restore_engine(load_bundled_manifest(), events)


def test_appended_foreign_event_is_refused():
    events = run().events
    forged = events[-1].model_copy(update={
        "sequence": len(events) + 1,
        "proposal": Proposal(actor_id="obs", action=Speak(text="Synthetic")),
        "actor_id": "obs",
        "accepted": True,
        "findings": [],
    })
    with pytest.raises(RestoreError, match=f"Event {len(events) + 1} differs"):
        restore_engine(load_bundled_manifest(), [*events, forged])


# --- no partial engine, no journal mutation ------------------------------------------


@pytest.mark.parametrize("corrupt", ["regeneration", "provenance", "sequence", "legacy"])
def test_failed_restore_never_writes_the_journal(tmp_path, corrupt):
    events = run().events
    if corrupt == "regeneration":
        events[-1] = events[-1].model_copy(update={"accepted": not events[-1].accepted})
    elif corrupt == "provenance":
        events[-1] = events[-1].model_copy(update={"scenario": events[-1].scenario.model_copy(
            update={"scenario_version": "2"})})
    elif corrupt == "sequence":
        events[-1] = events[-1].model_copy(update={"sequence": 99})
    else:
        events = [e.model_copy(update={"scenario": None}) for e in events]
    store = journal(tmp_path, events)
    before, changes = rows(store), store.connection.total_changes
    snapshot = [e.model_copy(deep=True) for e in events]
    with pytest.raises(RestoreError):
        restore_from_store(store, "case", load_bundled_manifest())
    assert rows(store) == before and store.connection.total_changes == changes
    assert events == snapshot
    store.close()


def test_successful_restore_never_writes_the_journal(tmp_path):
    store = journal(tmp_path, run().events)
    before, changes = rows(store), store.connection.total_changes
    restored = restore_from_store(store, "case", load_bundled_manifest())
    restored.propose(NEXT)  # continuing does not persist anything by itself
    assert rows(store) == before and store.connection.total_changes == changes
    store.close()


def test_argument_types_are_checked():
    events = run().events
    with pytest.raises(TypeError):
        restore_engine(load_bundled_manifest().model_dump(), events)
    with pytest.raises(TypeError):
        restore_engine(load_bundled_manifest(), "events")
    with pytest.raises(TypeError, match="item 2"):
        restore_engine(load_bundled_manifest(), [events[0], events[1].model_dump()])
    with pytest.raises(TypeError):
        restore_from_store(object(), "case", load_bundled_manifest())
    with pytest.raises(ValueError):
        restore_engine(load_bundled_manifest(), events, mode="lenient")


def test_trial_event_subclass_is_refused():
    class Forged(TrialEvent):
        pass

    events = run().events
    events[0] = Forged.model_validate(events[0].model_dump())
    with pytest.raises(TypeError, match="item 1"):
        restore_engine(load_bundled_manifest(), events)


def test_existing_load_api_is_unchanged(tmp_path):
    events = run().events
    store = journal(tmp_path, events)
    assert store.load("case") == events
    assert [event for _, event in store.load_keyed("case")] == events
    store.close()


# --- documented API example (README "Restoring from a journal") ----------------------


def test_readme_api_example(tmp_path):
    from indubio.scenarios.demo import run_scenario_demo

    manifest = load_bundled_manifest()
    engine = run_scenario_demo(Mode.STRICT)
    store = EventStore(tmp_path / "journal.sqlite3")
    for event in engine.events:
        store.append("demo-1", event)

    restored = restore_from_store(store, "demo-1", manifest)
    assert restored.events == engine.events
    assert restored.phase == Phase.CLOSING
    event = restored.propose(Proposal(actor_id="judge", action=MovePhase(
        destination=Phase.JUDGMENT)))
    assert event.sequence == len(engine.events) + 1 and event.accepted
    store.append("demo-1", event)
    store.close()
