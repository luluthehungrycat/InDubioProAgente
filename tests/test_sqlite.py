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
