# E2E Manual Test — DeepSeek/self-hosted (via LiteLLM)

Manual, user-perspective end-to-end test of the self-hosted model exposed through
the LiteLLM gateway. Run now on the cheap **Qwen 0.5B** harness to validate the
plumbing (routing, auth, keys, usage, billing); re-run the model-specific items on
the real **DeepSeek-V4.1-Flash** when the B300 is up.

- **Environment:** gateway `https://superstackai-gateway.fly.dev`
- **Model under test:** `selfhost-test` → SGLang/Qwen on a rented GPU via a
  Cloudflare quick tunnel (URL ephemeral — redacted)
- **Registered models (real):** `selfhost-test`, `deepseek-v3`, `kimi3`, `kimi-k3`
  (the marketing showcase names are not registered)
- **Date:** 2026-10-30

> ⚠️ `selfhost-test` serves **Qwen 0.5B** — this validates plumbing/usage, **not**
> answer quality. No secrets (keys, tunnel URL, master key) are recorded here.

## Checklist & results

| # | Item | Result | Notes |
|---|---|---|---|
| 1 | Preconditions (GPU/SGLang up, tunnel up, entry points at tunnel, active membership) | ✅ Tested | |
| 2 | Create API key on the site as a user | ✅ Tested | |
| 3 | Auth: no/invalid key → 401, valid → 200 | ✅ Tested | |
| 4 | Routing: `selfhost-test` → GPU; `kimi-k3`/`deepseek-v3` → old upstreams (parallel) | ✅ Tested | |
| 5 | Spend log shows `selfhost-test` row + tunnel `api_base` + tokens | ⬜ Not run | |
| 6 | Basic chat returns a reply | ⬜ Not run | |
| 7 | Multi-turn follow-up | ⬜ Not run | |
| 8 | Streaming (`stream:true`) | ⬜ Not run | |
| 9 | Params (`max_tokens`, `temperature`, system prompt) | ⬜ Not run | |
| 10 | Long prompt under context; over-limit → clean error | ⬜ Not run | |
| 11 | Bad input: unknown model → 400, malformed body → 400 | ⬜ Not run | |
| 12 | Limits: ~60 rapid requests → 429 | ⬜ Not run | |
| 13 | Site usage page shows tokens for the key | ⬜ Not run | |
| 14 | Resilience: stop tunnel → 502; restart + repoint → works; detached tunnel survives tab close | ⬜ Not run | |
| 15 | Security: no secrets in UI; users can't see each other's data | ⬜ Not run | |
| 16 | Cleanup: delete test key (optional); Vast → Stop | ⬜ Not run | |

## How it was called (example)
```bash
curl -s https://superstackai-gateway.fly.dev/v1/chat/completions \
  -H "Authorization: Bearer <redacted>" \
  -H "Content-Type: application/json" \
  -d '{"model":"selfhost-test","messages":[{"role":"user","content":"ping"}]}'
```

## Caveats / follow-ups
- Quick-tunnel URL changes on restart → re-point `selfhost-test` `api_base` before
  each session (or move to a named tunnel for a stable URL).
- Re-run items 5–16, and the model-specific checks (256K context, multimodal,
  token counts, cost math, throughput), after switching to DeepSeek V4.1 on the B300.
- Keys, tunnel URLs, and master key are intentionally omitted from this doc.
