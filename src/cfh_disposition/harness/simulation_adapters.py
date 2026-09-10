"""Synthetic-only clock and create-only CRM transport, never an API client."""

import copy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass
class SimulationClock:
    now: datetime = datetime(2035, 1, 1, tzinfo=UTC)

    def advance(self, *, days=0, hours=0):
        self.now += timedelta(days=days, hours=hours)
        return self.now


class FakeCanonicalStore:
    """I/O adapter only. Call the real validator/matcher before using it."""

    def __init__(self):
        self.records = {}
        self.duplicates_prevented = 0
        self.fail_next = False

    def create(self, record):
        if not str(record.get("id", "")).startswith("simulation-"):
            raise AssertionError("Only synthetic records may enter this adapter")
        if self.fail_next:
            self.fail_next = False
            raise TimeoutError("Injected fake storage timeout")
        if record["id"] in self.records:
            self.duplicates_prevented += 1
            return False
        self.records[record["id"]] = copy.deepcopy(record)
        return True

    def list(self):
        return copy.deepcopy(list(self.records.values()))
