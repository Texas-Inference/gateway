# Redis: what exists, what didn't, and what's next

## Finding: there was no Redis request queue
The existing deployment used Redis for **rate limiting and caching only**:

- LiteLLM uses `REDIS_URL` for key cache + rate-limit counters.
- The older `llm-gateway/` / `provider-gateway/` proxies use Redis for a
  fixed-window RPM counter:
  ```python
  key = f"ratelimit:rpm:{user_id}"
  pipe.incr(key); pipe.expire(key, 60)
  if rpm > RPM_LIMIT: return 429
  ```
  That is a **counter**, not a queue.

No component ever stored "requests over the limit" in Redis, and there was no
round-robin worker draining a queue. That behavior is new in `queue-proxy/`.

## v1: in-memory, single replica
`queue-proxy` v1 keeps its queues, counters and round-robin cursor **in process
memory**, and uses in-process asyncio futures to "grant" a queued request. This
is correct and simple **on a single Fly machine** (we run exactly 1).

Consequence: on restart/redeploy, in-flight held requests are lost, and it
cannot be horizontally scaled (a job enqueued on replica A can't be granted by
replica B).

## P4 (next): Redis-backed store + HA
For durability and multi-replica HA:

- Store per-user/per-key queues and the RR cursor in **Redis** (Lists or Streams),
  namespaced (e.g. `q:{uid}:{key}`, `rr:{uid}`) to avoid colliding with LiteLLM's
  keys.
- Use a **dedicated Redis** (or at least a separate DB index) with
  **`appendonly yes`** and **`maxmemory-policy noeviction`**. Do **not** put a
  queue on an LRU cache-style Redis — eviction would silently drop jobs.
- For multi-replica grant signaling, use **Redis pub/sub** (or Streams consumer
  groups) so the replica holding the HTTP connection is told "you may dispatch".
- Add idempotency (avoid double-charge on crash) and queue-depth metrics.

## Note: budget-exceeded status code
This LiteLLM build returns **HTTP 422** with `type: budget_exceeded` (not 429),
and it **skips all budget checks for zero-cost models**. `queue-proxy` therefore:

- requires the model to have a non-zero cost in LiteLLM (config `model_info`),
  and
- treats any `budget_exceeded` response (400/402/422/429) as "requeue + pause
  this user until budget refreshes", not as a terminal error.
