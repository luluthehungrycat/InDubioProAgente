"""Append-only SQLite event journal. Replay is deliberately explicit.

Scenario restoration lives in ``indubio.scenarios.restore``; this module only stores and
loads payloads and never interprets them.
"""

import sqlite3
from pathlib import Path

from indubio.core.models import TrialEvent


class EventStore:
    def __init__(self, path: str | Path) -> None:
        self.connection = sqlite3.connect(str(path))
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS events (
                simulation_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY(simulation_id, sequence)
            )"""
        )
        self.connection.commit()

    def append(self, simulation_id: str, event: TrialEvent) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO events (simulation_id, sequence, payload) VALUES (?, ?, ?)",
                (simulation_id, event.sequence, event.model_dump_json()),
            )

    def load(self, simulation_id: str) -> list[TrialEvent]:
        rows = self.connection.execute(
            "SELECT payload FROM events WHERE simulation_id = ? ORDER BY sequence",
            (simulation_id,),
        ).fetchall()
        return [TrialEvent.model_validate_json(row[0]) for row in rows]

    def load_keyed(self, simulation_id: str) -> list[tuple[int, TrialEvent]]:
        """Like ``load``, but pairs each event with its stored ``sequence`` key (read-only).

        Used by restoration to check the row key against the payload's own sequence.
        """
        rows = self.connection.execute(
            "SELECT sequence, payload FROM events WHERE simulation_id = ? ORDER BY sequence",
            (simulation_id,),
        ).fetchall()
        return [(row[0], TrialEvent.model_validate_json(row[1])) for row in rows]

    def close(self) -> None:
        self.connection.close()
