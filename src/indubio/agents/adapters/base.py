"""Provider-neutral proposal seam; no LLM or Hermes integration yet."""

from typing import Protocol

from indubio.core.models import Actor, Proposal, TrialEvent


class ParticipantAdapter(Protocol):
    async def next_proposal(
        self, actor: Actor, visible_history: list[TrialEvent], instructions: str
    ) -> Proposal:
        """Return typed proposal for engine validation; no direct state mutation."""
        ...
