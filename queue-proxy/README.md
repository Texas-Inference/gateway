# queue-proxy — fair per-user queue in front of LiteLLM

A standalone, OpenAI-compatible reverse proxy that sits in front of the LiteLLM
gateway and **queues** inference requests when a user hits their RPM or budget
limit — instead of failing them — then drains the queue **round-robin across the
user's keys**.

> The public URL (`https://superstackai-gateway.fly.dev`) must not change, so at
> cutover this proxy takes over that app name and LiteLLM moves to a private
> app. Until then it runs as its own app (`superstackai-queue`) for testing.

## What it does
- **Transparent reverse proxy** for all paths (`/key/*`, `/user/*`, `/model/*`,
  `/v1/models`, …). Only the inference paths are queued.
- **Auth** by validating the caller's virtual key via LiteLLM `/key/info`
  (cached). Blocked keys → 403 (membership gate).
- **Queue on RPM/TPM or budget**: under the limit → pass through; over it →
  enqueue and hold up to `MAX_WAIT_SECONDS` (default **120s**), then `429` with
  `Retry-After`.
- **Round-robin fairness** across a user's keys: queued work is dispatched
  interleaved (`k1,k2,k3,k1,…`), not first-come-first-served.
- **Budget top-up**: when the user is over budget, the queue holds; once spend
  drops below `max_budget` (top-up), it resumes draining.
- **Streaming** works: the handler performs the upstream call after it's granted,
  so SSE passes through.

## Request lifecycle
```
under limit ──▶ forward to LiteLLM ──▶ 200
over limit  ──▶ enqueue (per-key FIFO) ──▶ scheduler grants round-robin
             ──▶ forward ──▶ 200
             (or 429 + Retry-After after MAX_WAIT)
budget out  ──▶ hold ──▶ poll /user/info ──▶ top-up ──▶ drain ──▶ 200
```

## Config (env)
See `.env.example`. Key ones: `LITELLM_BASE_URL`, `LITELLM_MASTER_KEY`,
`MAX_WAIT_SECONDS`, `BUDGET_POLL_SECONDS`, `INFERENCE_PATHS`.

## Run locally (no LiteLLM needed for the scheduler tests)
```sh
python3 queue-proxy/tests/test_round_robin.py     # pure round-robin/fairness
```

Run the service:
```sh
cd queue-proxy
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
LITELLM_BASE_URL=http://127.0.0.1:4000 LITELLM_MASTER_KEY=sk-... \
  uvicorn app.main:app --port 8080
```
Then point a client at `http://localhost:8080/v1/...` instead of LiteLLM.

## Deploy (dev)
```sh
cd queue-proxy
fly apps create superstackai-queue -o gm-fellows
fly secrets set -a superstackai-queue \
  LITELLM_MASTER_KEY=<master-key>
fly deploy -a superstackai-queue
```
Set `LITELLM_BASE_URL` in `fly.toml [env]` to the **internal** LiteLLM URL
(e.g. `http://superstackai-gateway-litellm.internal:4000` at cutover; for dev
testing against the public URL you can use `https://superstackai-gateway.fly.dev`).

## Cutover (keep the URL)
1. Deploy LiteLLM to a **private app** (e.g. `superstackai-gateway-litellm`),
   configure its secrets (DATABASE_URL, REDIS_URL, keys).
2. Deploy `queue-proxy` **into the public app name** `superstackai-gateway`
   (rename/replace), with `LITELLM_BASE_URL` = the private LiteLLM `.internal`.
3. Clients/apps keep using `https://superstackai-gateway.fly.dev` unchanged.
4. Rollback: redeploy LiteLLM to the public app name.

## Status / roadmap
See **`TEST_RESULTS.md`** for live + deterministic results (all on the
self-hosted model) and **`REDIS.md`** for the Redis finding + HA plan.

- **v1 (this):** in-process state on a **single replica** (Fly keeps 1 machine).
  Queue + counters live in memory; `uuid` futures signal handlers. This is the
  simplest correct version for one machine.
- **Budget note:** this LiteLLM build returns **422 `budget_exceeded`** (not 429)
  and bypasses budget checks for **zero-cost** models; the proxy requires a
  non-zero model cost and requeues/pauses on any `budget_exceeded` response.
- **P4 (next):** move queues/counters to **Redis** (reuse `REDIS_URL` or a
  dedicated Redis with **AOF + `noeviction`**) for durability + multi-replica
  **HA** (needs Redis pub/sub for cross-replica grant signaling). Do **not**
  point a queue at an LRU cache-style Redis — eviction would drop jobs.
- **P4:** idempotency (avoid double-charge on crash), metrics/queue-depth
  dashboards, per-model limits.

## Notes
- `selfhost-test` is currently priced at **0**, so budget never depletes — set a
  nonzero `input/output_cost_per_token` (e.g. `1e-6` / `2e-6`) to test budget.
- The proxy keeps LiteLLM's own limits as a backstop; an upstream `429` is
  treated as "requeue with cooldown".
