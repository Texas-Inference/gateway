"""Pure round-robin primitives (stdlib only) so they are trivially unit-testable."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from .models import Job


class WindowCounter:
    """Fixed-window counter (like a per-minute RPM limiter)."""

    def __init__(self, window: float) -> None:
        self.window = window
        self._start = time.monotonic()
        self._count = 0

    def _roll(self) -> None:
        now = time.monotonic()
        if now - self._start >= self.window:
            self._start = now
            self._count = 0

    @property
    def count(self) -> int:
        self._roll()
        return self._count

    def hit(self) -> None:
        self._roll()
        self._count += 1


class RoundRobinState:
    """Per-user round-robin over per-key FIFO queues.

    Fairness rule: each pick advances a cursor over the user's keys, so queued
    work is dispatched interleaved across keys (not first-come-first-served).
    """

    def __init__(self) -> None:
        self.order: list[str] = []
        self.queues: dict[str, deque[Job]] = defaultdict(deque)
        self.cursor = 0

    def register_key(self, key_id: str) -> None:
        if key_id not in self.queues:
            self.queues[key_id] = deque()
            self.order.append(key_id)

    def enqueue(self, job: Job) -> None:
        self.register_key(job.key_id)
        self.queues[job.key_id].append(job)

    def depth(self) -> int:
        return sum(len(q) for q in self.queues.values())

    def pick(self, key_capacity=None) -> Job | None:
        n = len(self.order)
        if n == 0:
            return None
        for i in range(n):
            idx = (self.cursor + i) % n
            key_id = self.order[idx]
            q = self.queues[key_id]
            if q and (key_capacity is None or key_capacity(key_id)):
                job = q.popleft()
                self.cursor = (idx + 1) % n
                return job
        return None
