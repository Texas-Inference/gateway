from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class KeyInfo:
    user_id: str
    rpm_limit: int
    blocked: bool


@dataclass
class UserInfo:
    user_id: str
    max_budget: float | None
    spend: float
    rpm_limit: int | None
    fetched_at: float = field(default_factory=time.monotonic)


@dataclass
class Job:
    """A queued inference request.

    ``grant`` is resolved by the scheduler when the job may be dispatched. The
    HTTP handler then performs the actual upstream call (so streaming works
    naturally). ``deadline`` bounds the total wait (MAX_WAIT).
    """

    job_id: str
    user_id: str
    key_id: str
    path: str
    headers: dict[str, str]
    body: bytes
    enqueued_at: float = field(default_factory=time.monotonic)
    deadline: float = 0.0
    grant: asyncio.Future = field(default=None)  # type: ignore[assignment]

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def expired(self) -> bool:
        return time.monotonic() >= self.deadline
