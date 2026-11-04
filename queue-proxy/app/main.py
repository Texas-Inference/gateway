from __future__ import annotations

import json
import time
import uuid

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .auth import auth, token_id
from .config import settings
from .litellm import litellm
from .models import Job
from .scheduler import schedulers

app = FastAPI(title="queue-proxy")

# Headers we don't copy from the upstream response.
_DROP_RESP_HEADERS = {
    "content-length",
    "content-encoding",
    "transfer-encoding",
    "connection",
    "keep-alive",
}


def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return None


def _resp_headers(resp: httpx.Response) -> dict[str, str]:
    return {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in _DROP_RESP_HEADERS
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/_queue/stats")
async def stats() -> dict:
    return {
        "users": {
            uid: {
                "depth": s.state.depth(),
                "budget_blocked": s.budget_blocked,
                "user_rpm": s.user_rpm,
                "user_used": s.user_window.count,
                "keys": {
                    k: {
                        "queued": len(s.state.queues.get(k, [])),
                        "used": s.key_windows[k].count,
                        "rpm": s.key_rpm.get(k, settings.default_key_rpm),
                    }
                    for k in s.state.order
                },
                "recent_grants": list(s.recent),
            }
            for uid, s in schedulers._users.items()
        }
    }


async def _handle_inference(request: Request, path: str, body: bytes):
    token = _bearer(request)
    if not token:
        return JSONResponse({"error": {"message": "missing api key"}}, status_code=401)

    key_info = await auth.key(token)
    if key_info is None:
        return JSONResponse(
            {"error": {"message": "invalid api key"}}, status_code=401
        )
    if key_info.blocked:
        return JSONResponse(
            {"error": {"message": "api key blocked (membership inactive)"}},
            status_code=403,
        )

    try:
        parsed = json.loads(body) if body else {}
    except ValueError:
        parsed = {}
    stream = bool(parsed.get("stream"))

    job = Job(
        job_id=uuid.uuid4().hex,
        user_id=key_info.user_id,
        key_id=token_id(token),
        path=path,
        headers=dict(request.headers),
        body=body,
    )
    scheduler = schedulers.get(key_info.user_id)

    def _timeout_response() -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "message": "queue wait exceeded; try again later",
                    "type": "queue_timeout",
                    "code": "429",
                }
            },
            status_code=429,
            headers={"Retry-After": str(int(settings.max_wait_seconds))},
        )

    try:
        await scheduler.acquire(job, key_info)
    except TimeoutError:
        return _timeout_response()

    while True:
        if job.expired():
            return _timeout_response()

        try:
            if stream:
                resp = await litellm.stream(job.path, job.headers, job.body)
                if resp.status_code == 429:
                    retry_after = _retry_after(resp)
                    await resp.aread()
                    await resp.aclose()
                    await scheduler.requeue(job, key_info, cooldown=retry_after or 5.0)
                    continue
                if resp.status_code not in (200, 201):
                    body_read = await resp.aread()
                    if _is_budget_exceeded(resp.status_code, body_read):
                        await resp.aclose()
                        scheduler.mark_budget_blocked()
                        await scheduler.requeue(job, key_info, cooldown=settings.budget_poll_seconds)
                        continue
                    headers = _resp_headers(resp)
                    await resp.aclose()
                    return Response(
                        content=body_read,
                        status_code=resp.status_code,
                        headers=headers,
                        media_type=resp.headers.get("content-type"),
                    )
                headers = _resp_headers(resp)

                async def relay(r=resp):
                    try:
                        async for chunk in r.aiter_raw():
                            yield chunk
                    finally:
                        await r.aclose()

                return StreamingResponse(
                    relay(), status_code=resp.status_code, headers=headers
                )

            resp = await litellm.forward(job.path, job.headers, job.body)
            if resp.status_code == 429:
                retry_after = _retry_after(resp)
                await scheduler.requeue(job, key_info, cooldown=retry_after or 5.0)
                continue
            if _is_budget_exceeded(resp.status_code, resp.content):
                scheduler.mark_budget_blocked()
                await scheduler.requeue(job, key_info, cooldown=settings.budget_poll_seconds)
                continue
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=_resp_headers(resp),
                media_type=resp.headers.get("content-type"),
            )
        except TimeoutError:
            return _timeout_response()


def _retry_after(resp: httpx.Response) -> float | None:
    ra = resp.headers.get("retry-after")
    if not ra:
        return None
    try:
        return float(ra)
    except ValueError:
        return None


def _is_budget_exceeded(status: int, body: bytes) -> bool:
    """LiteLLM may report budget exhaustion as 400/422/429 with a budget_exceeded body."""
    if status not in (400, 402, 422, 429):
        return False
    text = body.lower()
    return b"budget_exceeded" in text or b"budget has been exceeded" in text


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def catch_all(request: Request, path: str):
    full_path = "/" + path
    body = await request.body()
    query = request.url.query
    target = full_path + (f"?{query}" if query else "")

    if request.method == "POST" and full_path in settings.inference_paths:
        return await _handle_inference(request, target, body)

    # Transparent reverse proxy for everything else (admin, models, etc.)
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in {"host", "content-length", "connection", "accept-encoding"}
    }
    resp = await litellm._client.request(
        request.method, target, headers=headers, content=body
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=_resp_headers(resp),
        media_type=resp.headers.get("content-type"),
    )


@app.on_event("shutdown")
async def _shutdown() -> None:
    await litellm.aclose()
