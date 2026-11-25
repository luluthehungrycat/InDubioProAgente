"""Deterministic engine restoration from a trusted journal and its synthetic scenario.

``restore_engine(manifest, events)`` rebuilds a fresh engine with ``build_engine`` and
re-submits every recorded proposal, in order, through the ordinary
``SimulationEngine.propose`` path. Nothing is copied from the journal into engine state:
phase, motions, disclosure grants, event-time projections and sequence numbering are
whatever the canonical engine transitions regenerate. Each regenerated event must equal
the recorded one exactly, rejected events included, or restoration fails.

Checks, all before an engine is returned (fail closed, ``RestoreError``):

1. **Shape:** every item is a ``TrialEvent``; sequences are exactly ``1..n`` in order
   (no gaps, duplicates or reordering).
2. **Eligibility:** every event carries ``ScenarioProvenance``. A journal with no
   provenance at all (pre-provenance payloads, direct non-scenario engines) raises
   ``LegacyJournalError``; it stays loadable with ``EventStore.load`` but is not eligible
   for restoration, because nothing binds it to a scenario setup. A journal that mixes
   stamped and unstamped events is inconsistent.
3. **Scenario identity and digest:** every event's provenance equals
   ``manifest.provenance()`` in every field (schema, identity, canonicalization,
   algorithm and setup digest). A different scenario version or setup is refused.
4. **Pinned ruleset metadata:** every event's ``metadata`` has exactly the keys the
   engine writes, and the recorded ruleset ID, version and validation status equal the
   currently registered ruleset's. There are no migrations: a journal recorded under a
   different ruleset version is refused, not reinterpreted.
5. **Floor control:** an event's ``metadata`` either has no floor keys (an unscheduled
   run, including every journal recorded before floor control existed) or exactly
   ``FLOOR_METADATA_KEYS``, and all events agree. Recorded floor semantics must be
   ``indubio.floor/1`` and the floor ruleset ID, version and validation status must equal
   the registered floor pack's (no migrations). If ``floor_rules`` (an ID) is passed,
   the journal must record exactly that floor ruleset; an unscheduled journal is a
   mismatch. The restored engine runs with the journal's floor control. For an empty
   history, ``floor_rules`` selects it (default ``None``: no floor control), like
   ``mode``.
6. **Run mode:** the recorded ``mode`` must be a ``Mode`` value, and all events must
   record the same mode. The engine's ``config`` is public and mutable, so a live run can
   change mode between proposals, but such a change is not itself an event; restoration
   does not infer an unrecorded transition and refuses mixed-mode journals. If ``mode``
   is passed it must equal the journal's mode. The restored engine runs in that mode.
7. **Regeneration:** each regenerated event equals the recorded event (``==`` and the
   JSON-mode dump). A proposal the engine refuses outright (unknown actor, out-of-schema
   action) is a journal the engine could not have produced and fails too.

**Empty history** is a valid journal of zero events: the result equals
``build_engine(manifest, mode, floor_rules=floor_rules)``, with ``mode`` defaulting to ``Mode.STRICT`` like
``build_engine``. Note that ``EventStore.load`` returns ``[]`` for an unknown simulation
ID as well, so an empty restore cannot tell "new" from "misspelled".

Not covered: tamper evidence or authenticity (a consistent, regenerable journal written
by someone else restores like any other; the journal is trusted input), schema or
ruleset migrations, ``SimulationConfig`` fields other than ``jurisdiction`` and ``mode``
(they are not recorded; ``build_engine`` defaults are used, and the current engine does
not read them), and concurrent writers. Restoration reads only: it never writes to the
journal or the caller's objects.
"""

from collections.abc import Iterable

from pydantic import ValidationError

from indubio.core.engine import SimulationEngine
from indubio.core.floor import FLOOR_SEMANTICS
from indubio.core.models import Mode, TrialEvent
from indubio.jurisdictions.registry import get_floor_ruleset, get_ruleset
from indubio.persistence.sqlite import EventStore
from indubio.scenarios.manifest import ScenarioManifest, build_engine

# Exactly the keys ``SimulationEngine.propose`` writes into ``TrialEvent.metadata``.
EVENT_METADATA_KEYS = frozenset({"mode", "ruleset", "ruleset_version", "ruleset_validation"})
# The additional keys it writes, all together, only with floor control.
FLOOR_METADATA_KEYS = frozenset({
    "floor_semantics", "floor_rules", "floor_rules_version", "floor_rules_validation",
})


class RestoreError(ValueError):
    """The history cannot be restored against this manifest; no engine was returned."""


class LegacyJournalError(RestoreError):
    """The history carries no scenario provenance (legacy or direct-engine journal).

    It remains loadable through ``EventStore.load``; it is just not bound to a scenario
    and therefore not eligible for scenario restoration.
    """


def _detached(events: Iterable[TrialEvent]) -> list[TrialEvent]:
    if isinstance(events, (str, bytes)) or not isinstance(events, Iterable):
        raise TypeError("events must be an iterable of TrialEvent")
    history: list[TrialEvent] = []
    for index, event in enumerate(events, start=1):
        if type(event) is not TrialEvent:
            raise TypeError(f"History item {index} is not a TrialEvent")
        try:
            # The journal's own encoding: compare against what the journal would hold,
            # and never share objects with the caller.
            history.append(TrialEvent.model_validate_json(event.model_dump_json(warnings=False)))
        except (ValueError, AttributeError) as error:
            raise RestoreError(f"History item {index} is not a valid TrialEvent") from error
    return history


def _check_sequences(history: list[TrialEvent]) -> None:
    for expected, event in enumerate(history, start=1):
        if event.sequence != expected:
            raise RestoreError(
                f"History is not contiguous: position {expected} holds sequence "
                f"{event.sequence}"
            )


def _check_provenance(manifest: ScenarioManifest, history: list[TrialEvent]) -> None:
    stamped = [event.scenario is not None for event in history]
    if history and not any(stamped):
        raise LegacyJournalError(
            "History carries no scenario provenance (legacy or direct-engine journal); "
            "it can be loaded with EventStore.load but not restored against a scenario"
        )
    if not all(stamped):
        first = stamped.index(False) + 1
        raise RestoreError(f"History mixes stamped and unstamped events (event {first})")
    expected = manifest.provenance()
    for event in history:
        if event.scenario != expected:
            differing = sorted(
                name for name in type(expected).model_fields
                if getattr(event.scenario, name) != getattr(expected, name)
            )
            raise RestoreError(
                f"Event {event.sequence} scenario provenance differs from the manifest in: "
                f"{', '.join(differing)}"
            )


def _check_floor(history: list[TrialEvent]) -> tuple[bool, str | None]:
    """``(recorded, floor ruleset ID or None)``; ``recorded`` is false for no events."""
    recorded: set[str | None] = set()
    for event in history:
        keys = set(event.metadata)
        if keys == EVENT_METADATA_KEYS:
            recorded.add(None)
            continue
        if keys != EVENT_METADATA_KEYS | FLOOR_METADATA_KEYS:
            raise RestoreError(f"Event {event.sequence} metadata keys are not the engine's")
        floor_id = event.metadata["floor_rules"]
        if event.metadata["floor_semantics"] != FLOOR_SEMANTICS:
            raise RestoreError(
                f"Event {event.sequence} records floor semantics "
                f"{event.metadata['floor_semantics']!r}, not {FLOOR_SEMANTICS!r}"
            )
        try:
            pinned = get_floor_ruleset(floor_id).metadata
        except ValueError as error:
            raise RestoreError(f"Event {event.sequence}: {error}") from error
        for key, value in {
            "floor_rules_version": pinned.version,
            "floor_rules_validation": pinned.validation_status,
        }.items():
            if event.metadata[key] != value:
                raise RestoreError(
                    f"Event {event.sequence} records {key}={event.metadata[key]!r}, but the "
                    f"registered floor ruleset has {value!r} (no migrations)"
                )
        recorded.add(floor_id)
    if len(recorded) > 1:
        raise RestoreError(
            "History changes floor control; floor control is fixed for a run"
        )
    return (True, recorded.pop()) if recorded else (False, None)


def _check_metadata(manifest: ScenarioManifest, history: list[TrialEvent]) -> Mode | None:
    pinned = get_ruleset(manifest.jurisdiction).metadata
    expected = {
        "ruleset": pinned.ruleset_id,
        "ruleset_version": pinned.version,
        "ruleset_validation": pinned.validation_status,
    }
    modes: set[str] = set()
    for event in history:
        if not EVENT_METADATA_KEYS <= set(event.metadata):  # exact keys: ``_check_floor``
            raise RestoreError(f"Event {event.sequence} metadata keys are not the engine's")
        for key, value in expected.items():
            if event.metadata[key] != value:
                raise RestoreError(
                    f"Event {event.sequence} records {key}={event.metadata[key]!r}, but the "
                    f"registered ruleset has {value!r} (no migrations)"
                )
        recorded = event.metadata["mode"]
        if recorded not in {member.value for member in Mode}:
            raise RestoreError(f"Event {event.sequence} records unsupported mode {recorded!r}")
        modes.add(recorded)
    if len(modes) > 1:
        raise RestoreError(
            f"History changes mode ({', '.join(sorted(modes))}); mode changes are not "
            "events and are not restored"
        )
    return Mode(modes.pop()) if modes else None


def restore_engine(
    manifest: ScenarioManifest,
    events: Iterable[TrialEvent],
    *,
    mode: Mode | str | None = None,
    floor_rules: str | None = None,
) -> SimulationEngine:
    """A fresh engine whose committed history regenerates ``events`` exactly.

    ``floor_rules``, if passed, must equal the journal's floor ruleset ID; for an empty
    history it selects floor control (default ``None``: none).

    ``events`` is a trusted, ordered history (e.g. ``EventStore.load(...)``). Raises
    ``LegacyJournalError`` for an unstamped history, ``RestoreError`` for any other
    inconsistency, and ``TypeError`` for wrong argument types; no engine is returned and
    nothing is written in any failure case. See the module docstring for the checks.
    """
    if not isinstance(manifest, ScenarioManifest):
        raise TypeError("restore_engine requires a validated ScenarioManifest")
    requested = Mode(mode) if mode is not None else None
    if floor_rules is not None and not isinstance(floor_rules, str):
        raise TypeError("floor_rules must be a floor ruleset ID or None")
    history = _detached(events)
    _check_sequences(history)
    _check_provenance(manifest, history)
    journal_mode = _check_metadata(manifest, history)
    if journal_mode is not None and requested is not None and requested != journal_mode:
        raise RestoreError(
            f"Requested mode {requested.value!r} differs from the journal's mode "
            f"{journal_mode.value!r}"
        )
    run_mode = journal_mode or requested or Mode.STRICT
    floor_recorded, journal_floor = _check_floor(history)
    if floor_recorded and floor_rules is not None and floor_rules != journal_floor:
        raise RestoreError(
            f"Requested floor rules {floor_rules!r} differ from the journal's "
            f"{journal_floor!r}"
        )
    run_floor = journal_floor if floor_recorded else floor_rules

    # Local until every event has been regenerated; discarded on any failure.
    engine = build_engine(manifest, run_mode, floor_rules=run_floor)
    for recorded in history:
        try:
            regenerated = engine.propose(recorded.proposal)
        except (TypeError, ValueError, PermissionError) as error:
            raise RestoreError(
                f"Event {recorded.sequence} could not be regenerated: {error}"
            ) from error
        if regenerated != recorded or (
            regenerated.model_dump(mode="json") != recorded.model_dump(mode="json")
        ):
            differing = sorted(
                name for name in TrialEvent.model_fields
                if getattr(regenerated, name) != getattr(recorded, name)
            )
            raise RestoreError(
                f"Event {recorded.sequence} differs from its regeneration in: "
                f"{', '.join(differing) or 'serialization'}"
            )
    if engine.events != history:  # pragma: no cover - defensive
        raise RestoreError("Restored history does not equal the journal")
    return engine


def restore_from_store(
    store: EventStore,
    simulation_id: str,
    manifest: ScenarioManifest,
    *,
    mode: Mode | str | None = None,
    floor_rules: str | None = None,
) -> SimulationEngine:
    """Read-only convenience: restore ``simulation_id`` from a SQLite ``EventStore``.

    Also requires each row's stored ``sequence`` key to equal its payload's sequence.
    Unparseable payloads raise ``RestoreError``. The journal is only read.
    """
    if not isinstance(store, EventStore):
        raise TypeError("store must be an EventStore")
    try:
        rows = store.load_keyed(simulation_id)
    except ValidationError as error:
        raise RestoreError("Journal payload is not a valid TrialEvent") from error
    for key, event in rows:
        if key != event.sequence:
            raise RestoreError(
                f"Journal row key {key} does not match payload sequence {event.sequence}"
            )
    return restore_engine(
        manifest, [event for _, event in rows], mode=mode, floor_rules=floor_rules
    )


__all__ = [
    "EVENT_METADATA_KEYS",
    "FLOOR_METADATA_KEYS",
    "LegacyJournalError",
    "RestoreError",
    "restore_engine",
    "restore_from_store",
]
