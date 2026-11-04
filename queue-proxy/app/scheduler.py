from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from .auth import auth
from .config import settings
from .models import Job, KeyInfo
from .rr import RoundRobinState, WindowCounter


class UserScheduler:
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self.state = RoundRobinState()
        self.lock = asyncio.Lock()
        self.user_window = WindowCounter(settings.window_seconds)
        self.key_windows: dict[str, WindowCounter] = defaultdict(
            lambda: WindowCounter(settings.window_seconds)
        )
        self.key_rpm: dict[str, int] = {}
        self.user_rpm: int = settings.force_user_rpm or settings.default_user_rpm
        self.budget_blocked = False
        self.cooldown_until = 0.0
        self._task: asyncio.Task | None = None
        self._last_user_refresh = 0.0
        self.recent: deque = deque(maxlen=100)  # (timestamp, key_id) of grants

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    # -- public API --------------------------------------------------------
    async def submit(self, job: Job, key_info: KeyInfo) -> None:
        async with self.lock:
            self.key_rpm[job.key_id] = settings.force_key_rpm or key_info.rpm_limit
            self.state.enqueue(job)
        self.start()

    async def acquire(self, job: Job, key_info: KeyInfo) -> None:
        """Enqueue and wait until the scheduler grants dispatch (bounded)."""
        job.deadline = time.monotonic() + settings.max_wait_seconds
        job.grant = asyncio.get_running_loop().create_future()
        await self.submit(job, key_info)
        remaining = max(0.0, job.deadline - time.monotonic())
        try:
            await asyncio.wait_for(job.grant, timeout=remaining)
        except asyncio.TimeoutError as e:
            raise TimeoutError("queue wait exceeded MAX_WAIT") from e

    def mark_budget_blocked(self) -> None:
        """Stop granting for this user until the next budget refresh says otherwise."""
        self.budget_blocked = True
        self._last_user_refresh = 0.0

    async def requeue(self, job: Job, key_info: KeyInfo, cooldown: float = 0.0) -> None:
        """Put a job back (e.g. after an upstream 429) and wait again."""
        if cooldown > 0:
            self.cooldown_until = max(self.cooldown_until, time.monotonic() + cooldown)
        job.grant = asyncio.get_running_loop().create_future()
        await self.submit(job, key_info)
        remaining = max(0.0, job.deadline - time.monotonic())
        try:
            await asyncio.wait_for(job.grant, timeout=remaining)
        except asyncio.TimeoutError as e:
            raise TimeoutError("queue wait exceeded MAX_WAIT") from e

    # -- budget / limits ---------------------------------------------------
    async def _refresh_user(self) -> None:
        now = time.monotonic()
        interval = (
            settings.budget_poll_seconds
            if self.budget_blocked
            else settings.user_cache_ttl
        )
        if now - self._last_user_refresh < interval:
            return
        self._last_user_refresh = now
        info = await auth.user(self.user_id, force=True)
        if info is None:
            return
        if settings.force_user_rpm:
            self.user_rpm = settings.force_user_rpm
        elif info.rpm_limit:
            self.user_rpm = info.rpm_limit
        if info.max_budget is None:
            self.budget_blocked = False
        else:
            self.budget_blocked = info.spend >= info.max_budget

    def _key_has_capacity(self, key_id: str) -> bool:
        limit = self.key_rpm.get(key_id, settings.default_key_rpm)
        if limit <= 0:
            return True
        return self.key_windows[key_id].count < limit

    # -- scheduler loop ----------------------------------------------------
    async def _run(self) -> None:
        while True:
            try:
                await self._refresh_user()

                now = time.monotonic()
                if now < self.cooldown_until:
                    await asyncio.sleep(min(0.2, self.cooldown_until - now))
                    continue

                if self.budget_blocked:
                    await asyncio.sleep(settings.budget_poll_seconds)
                    continue

                async with self.lock:
                    if self.state.depth() == 0:
                        await asyncio.sleep(settings.scheduler_tick_seconds)
                        continue

                    while True:
                        if self.user_rpm and self.user_window.count >= self.user_rpm:
                            break
                        job = self.state.pick(self._key_has_capacity)
                        if job is None:
                            break
                        if job.expired():
                            if job.grant and not job.grant.done():
                                job.grant.set_exception(
                                    TimeoutError("queue wait exceeded MAX_WAIT")
                                )
                            continue
                        self.user_window.hit()
                        self.key_windows[job.key_id].hit()
                        self.recent.append((round(time.time(), 3), job.key_id))
                        if job.grant and not job.grant.done():
                            job.grant.set_result(None)

                await asyncio.sleep(settings.scheduler_tick_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:  # keep the loop alive
                await asyncio.sleep(0.5)


class SchedulerRegistry:
    def __init__(self) -> None:
        self._users: dict[str, UserScheduler] = {}

    def get(self, user_id: str) -> UserScheduler:
        s = self._users.get(user_id)
        if s is None:
            s = UserScheduler(user_id)
            self._users[user_id] = s
        return s


schedulers = SchedulerRegistry()
