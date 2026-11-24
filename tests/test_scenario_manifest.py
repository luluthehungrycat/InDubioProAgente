"""Synthetic scenario manifest loading, validation and the offline scenario demo."""

import json
import sys

import pytest
from pydantic import ValidationError

from indubio.core.models import Mode, Role
from indubio.core.projection import EventVisibility
from indubio.evidence.models import EpistemicLayer
from indubio.scenarios import (
    SCHEMA_VERSION,
    ScenarioManifest,
    build_engine,
    load_bundled_manifest,
    load_manifest,
)
from indubio.scenarios.demo import SCENARIO_DEMO_SCRIPT, run_scenario_demo

VIEWERS = ["judge", "pros", "def", "acc", "wit", "obs"]


def minimal(**overrides):
    data = {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": "s1",
        "scenario_version": "1",
        "title": "Synthetic",
        "synthetic": True,
        "disclaimer": "Synthetic only",
        "jurisdiction": "de-criminal-demo-unvalidated",
        "actors": [
            {"actor_id": "j", "role": "judge", "display_name": "J"},
            {"actor_id": "p", "role": "prosecutor", "display_name": "P"},
        ],
        "evidence": [
            {"evidence_id": "e1", "summary": "Synthetic", "layer": "actor_knowledge",
             "visible_to_actor_ids": ["p"]},
        ],
    }
    data.update(overrides)
    return data


# --- loading ---------------------------------------------------------------------------

def test_bundled_manifest_loads_and_initializes_engine():
    manifest = load_bundled_manifest()
    assert manifest.schema_version == SCHEMA_VERSION and manifest.synthetic is True
    engine = build_engine(manifest, Mode.STRICT)
    assert set(engine.actors) == set(VIEWERS)
    assert engine.actors["wit"].role == Role.WITNESS
    assert engine.events == []
    assert engine.perspective("pros").accessible_evidence_ids == (
        "ex-receipt", "pros-internal-note", "pros-vendor-log")
    assert engine.perspective("wit").evidence == ()
    for viewer in VIEWERS:
        assert "sealed-origin" not in engine.perspective(viewer).model_dump_json()


def test_load_manifest_from_path_and_string(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps(minimal()), encoding="utf-8")
    assert load_manifest(path) == load_manifest(json.dumps(minimal()))


def test_bundled_manifest_name_is_allowlisted():
    for name in ["../../pyproject", "missing", ""]:
        with pytest.raises(ValueError):
            load_bundled_manifest(name)


def test_manifest_is_frozen_and_engine_owns_a_snapshot():
    manifest = ScenarioManifest.model_validate(minimal())
    with pytest.raises(ValidationError):
        manifest.title = "edited"
    engine = build_engine(manifest)
    assert engine.perspective("p").evidence[0].summary == "Synthetic"


def test_build_engine_requires_validated_manifest():
    with pytest.raises(TypeError):
        build_engine(minimal())


# --- validation fails closed ------------------------------------------------------------

@pytest.mark.parametrize("overrides", [
    {"schema_version": "indubio.scenario/2"},
    {"synthetic": False},
    {"unexpected": "field"},
    {"actors": []},
    {"actors": [{"actor_id": "j", "role": "judge", "display_name": "J"}] * 2},
    {"actors": [{"actor_id": "j", "role": "deity", "display_name": "J"}]},
    {"evidence": [{"evidence_id": "e1", "summary": "S", "layer": "disclosed"}] * 2},
    {"evidence": [{"evidence_id": "e1", "summary": "S", "layer": "disclosed",
                   "visible_to_actor_ids": ["ghost"]}]},
    {"evidence": [{"evidence_id": "e1", "summary": "S", "layer": "disclosed",
                   "visible_to_actor_ids": ["p", "p"]}]},
    {"evidence": [{"evidence_id": "e1", "summary": "S", "layer": "hidden_truth",
                   "visible_to_actor_ids": ["j"]}]},
    {"evidence": [{"evidence_id": "e1", "summary": "S", "layer": "disclosed",
                   "secret": "x"}]},
])
def test_invalid_manifests_are_rejected(overrides):
    with pytest.raises(ValidationError):
        ScenarioManifest.model_validate(minimal(**overrides))


def test_unknown_jurisdiction_fails_at_engine_build():
    manifest = ScenarioManifest.model_validate(minimal(jurisdiction="us-federal-made-up"))
    with pytest.raises(ValueError):
        build_engine(manifest)


# --- scenario demo ----------------------------------------------------------------------

def outcomes(engine):
    return [(e.accepted, [f.rule_id for f in e.findings]) for e in engine.events]


def test_scenario_demo_strict_and_realistic_outcomes():
    strict, realistic = run_scenario_demo(Mode.STRICT), run_scenario_demo(Mode.REALISTIC)
    assert len(strict.events) == len(SCENARIO_DEMO_SCRIPT) == 9
    common = [
        (True, []),
        (False, ["AUTH_DISCLOSE_RECIPIENT", "ACL_EVIDENCE"]),
        (False, ["ACL_EVIDENCE"]),
        (True, []), (True, []), (True, []), (True, []), (True, []),
    ]
    assert outcomes(strict) == [*common, (False, ["DEMO_DISCLOSURE_PHASE"])]
    assert outcomes(realistic) == [*common, (True, ["DEMO_DISCLOSURE_PHASE"])]
    assert "pros-vendor-log" not in strict.perspective("judge").accessible_evidence_ids
    assert "pros-vendor-log" in realistic.perspective("judge").accessible_evidence_ids


@pytest.mark.parametrize("mode", [Mode.STRICT, Mode.REALISTIC])
def test_scenario_demo_isolation(mode):
    engine = run_scenario_demo(mode)
    for viewer in VIEWERS:
        dumped = engine.perspective(viewer).model_dump_json()
        assert "sealed-origin" not in dumped or viewer == "pros"  # own rejected attempt
        assert "SEALED TRUTH" not in dumped
        if viewer != "pros":
            assert "pros-internal-note" not in dumped or viewer == "def"
            assert "internal prosecution working note" not in dumped
    witness = engine.perspective("wit")
    assert witness.accessible_evidence_ids == ()
    assert {e.visibility for e in witness.events} <= {
        EventVisibility.PUBLIC, EventVisibility.PUBLIC_REDACTED, EventVisibility.WITHHELD}
    pros = {e.sequence: e for e in engine.perspective("pros").events}
    assert pros[5].visibility == EventVisibility.PUBLIC_REDACTED  # before event 7 grant
    assert pros[7].visibility == EventVisibility.RECIPIENT
    received = {r.evidence_id: r for r in engine.perspective("pros").evidence}
    assert received["def-chat-export"].disclosed_at_sequence == 7
    assert received["def-chat-export"].layer == EpistemicLayer.ACTOR_KNOWLEDGE


def test_scenario_demo_is_deterministic():
    first, second = run_scenario_demo(Mode.REALISTIC), run_scenario_demo(Mode.REALISTIC)
    assert first.events == second.events
    for viewer in VIEWERS:
        assert first.perspective(viewer) == second.perspective(viewer)


def run_cli(monkeypatch, capsys, *argv):
    from indubio.__main__ import main
    monkeypatch.setattr(sys, "argv", ["indubio", *argv])
    main()
    return capsys.readouterr().out.strip().splitlines()


def test_scenario_demo_cli(monkeypatch, capsys):
    lines = run_cli(monkeypatch, capsys, "scenario-demo", "--mode", "strict")
    assert len(lines) == 9
    assert json.loads(lines[0])["proposal"]["action"]["kind"] == "disclose_evidence"
    lines = run_cli(monkeypatch, capsys, "scenario-demo", "--perspective", "wit")
    assert len(lines) == 10
    assert json.loads(lines[-1])["viewer_actor_id"] == "wit"
    monkeypatch.setattr(sys, "argv", ["indubio", "scenario-demo", "--perspective", "nobody"])
    from indubio.__main__ import main
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 2


def test_default_demo_is_unchanged(monkeypatch, capsys):
    lines = run_cli(monkeypatch, capsys, "demo")
    events = [json.loads(line) for line in lines]
    assert [e["proposal"]["action"]["kind"] for e in events] == [
        "move_phase", "speak", "file_motion", "rule_on_motion", "move_phase"]
    assert [e["accepted"] for e in events] == [True, True, True, True, True]
    assert events[-1]["findings"][0]["rule_id"] == "DEMO_PHASE_ORDER"
