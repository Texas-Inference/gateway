from __future__ import annotations

import httpx

from .config import settings
from .models import KeyInfo, UserInfo

# Hop-by-hop / auth headers we never forward verbatim.
_DROP_REQ_HEADERS = {"host", "content-length", "connection", "accept-encoding"}


class LiteLLMClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.litellm_base_url.rstrip("/"),
            timeout=httpx.Timeout(300.0, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- admin -----------------------------------------------------------
    async def key_info(self, key: str) -> KeyInfo | None:
        r = await self._client.get(
            "/key/info",
            params={"key": key},
            headers={"Authorization": f"Bearer {settings.litellm_master_key}"},
        )
        if r.status_code != 200:
            return None
        data = r.json()
        info = data.get("info", data)
        uid = info.get("user_id")
        if not uid:
            return None
        rpm = info.get("rpm_limit") or settings.default_key_rpm
        return KeyInfo(user_id=uid, rpm_limit=int(rpm), blocked=bool(info.get("blocked")))

    async def user_info(self, user_id: str) -> UserInfo | None:
        r = await self._client.get(
            "/user/info",
            params={"user_id": user_id},
            headers={"Authorization": f"Bearer {settings.litellm_master_key}"},
        )
        if r.status_code != 200:
            return None
        data = r.json()
        info = data.get("user_info", data)
        mb = info.get("max_budget")
        return UserInfo(
            user_id=user_id,
            max_budget=float(mb) if mb is not None else None,
            spend=float(info.get("spend") or 0.0),
            rpm_limit=int(info["rpm_limit"]) if info.get("rpm_limit") else None,
        )

    # ---- proxying --------------------------------------------------------
    def _headers(self, headers: dict[str, str]) -> dict[str, str]:
        return {k: v for k, v in headers.items() if k.lower() not in _DROP_REQ_HEADERS}

    async def forward(
        self, path: str, headers: dict[str, str], body: bytes
    ) -> httpx.Response:
        return await self._client.request(
            "POST", path, headers=self._headers(headers), content=body
        )

    async def stream(
        self, path: str, headers: dict[str, str], body: bytes
    ) -> httpx.Response:
        req = self._client.build_request(
            "POST", path, headers=self._headers(headers), content=body
        )
        return await self._client.send(req, stream=True)


litellm = LiteLLMClient()
