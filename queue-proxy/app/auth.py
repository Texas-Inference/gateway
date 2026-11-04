from __future__ import annotations

import hashlib
import time

from .config import settings
from .litellm import litellm
from .models import KeyInfo, UserInfo


def token_id(token: str) -> str:
    """Stable, non-reversible identifier for a virtual key (for RR + counters)."""
    return hashlib.sha256(token.encode()).hexdigest()[:32]


class AuthCache:
    def __init__(self) -> None:
        self._keys: dict[str, tuple[float, KeyInfo | None]] = {}
        self._users: dict[str, tuple[float, UserInfo | None]] = {}

    async def key(self, token: str) -> KeyInfo | None:
        now = time.monotonic()
        hit = self._keys.get(token)
        if hit and now - hit[0] < settings.auth_cache_ttl:
            return hit[1]
        info = await litellm.key_info(token)
        self._keys[token] = (now, info)
        return info

    async def user(self, user_id: str, force: bool = False) -> UserInfo | None:
        now = time.monotonic()
        hit = self._users.get(user_id)
        if not force and hit and now - hit[0] < settings.user_cache_ttl:
            return hit[1]
        info = await litellm.user_info(user_id)
        self._users[user_id] = (now, info)
        return info


auth = AuthCache()
