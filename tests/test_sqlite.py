from indubio.core.engine import SimulationEngine
from indubio.core.models import Actor, Proposal, Role, Speak
from indubio.persistence.sqlite import EventStore


def test_persist_and_read(tmp_path):
    engine = SimulationEngine([Actor(actor_id="d", role=Role.DEFENDANT, display_name="D")])
    event = engine.propose(Proposal(actor_id="d", action=Speak(text="No comment")))
    store = EventStore(tmp_path / "events.sqlite3")
    store.append("case1", event)
    assert store.load("case1") == [event]
    store.close()


def test_persisted_event_ignores_later_caller_edits(tmp_path):
    engine = SimulationEngine([Actor(actor_id="d", role=Role.DEFENDANT, display_name="D")])
    proposal = Proposal(actor_id="d", action=Speak(text="No comment"))
    event = engine.propose(proposal)
    proposal.action.text = "Edited after commit"
    store = EventStore(tmp_path / "events.sqlite3")
    store.append("case1", engine.events[0])
    assert store.load("case1")[0].proposal.action.text == "No comment"
    store.close()
    assert event.proposal.action.text == "No comment"
