import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()
EVERY = int(os.getenv("RATE_LIMIT_EVERY", "0"))
KEY_RPM = int(os.getenv("KEY_RPM", "1000"))
USER_RPM = int(os.getenv("USER_RPM", "1000"))
_n = 0


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/key/info")
async def key_info(key: str = ""):
    return {"info": {"user_id": "u1", "rpm_limit": KEY_RPM, "blocked": False}}


@app.get("/user/info")
async def user_info(user_id: str = ""):
    mb = os.getenv("MAX_BUDGET")
    return {
        "user_info": {
            "user_id": user_id,
            "max_budget": float(mb) if mb is not None else None,
            "spend": float(os.getenv("SPEND", "0.0")),
            "rpm_limit": USER_RPM,
        }
    }


@app.post("/v1/chat/completions")
async def chat(req: Request):
    global _n
    _n += 1
    if EVERY and _n % EVERY == 0:
        return JSONResponse(
            {"error": {"message": "rate limited", "type": "throttling_error", "code": "429"}},
            status_code=429,
            headers={"retry-after": "1"},
        )
    return {
        "id": "x",
        "object": "chat.completion",
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "_n": _n,
        "auth": req.headers.get("authorization", ""),
    }
