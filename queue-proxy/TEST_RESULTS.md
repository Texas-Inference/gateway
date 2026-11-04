# Queue-proxy — test results

All tests were run against the **self-hosted model** (`selfhost-test` → SGLang/Qwen
on a rented GPU via a Cloudflare quick tunnel), through the queue proxy, not
against DeepSeek/Kimi upstreams.

- Gateway (LiteLLM): `https://superstackai-gateway.fly.dev`
- Queue proxy: `https://superstackai-queue.fly.dev` (1 machine)
- `MAX_WAIT_SECONDS=120`; normal rate window = 60s
- Date: 2026-10-30

## 1. Good response within the limit ✅
- Single request through the queue proxy → **HTTP 200**, coherent reply.
- Spend logged with the tunnel `api_base`.

## 2. Queue instead of failing at the RPM limit ✅
Temp key `rpm_limit=2`; 3 concurrent requests:

```
req@1.1s   200
req@1.3s   200
req@61.6s  200   <- queued across the 60s window, then served (no 429)
```

## 3. Budget exceeded -> hold -> top-up -> drain ✅
Temp user `max_budget=$0.00002`. LiteLLM now enforces budget (model is a config
model with non-zero cost) and returns **HTTP 422 `budget_exceeded`**:

```
{"error":{"message":"ExceededBudget: User=... Spend=3.9e-05, Budget=2e-05",
          "type":"budget_exceeded","code":"422"}}
```

Through the queue proxy:

```
call1 -> 200 (spend 3.9e-05, now over budget)
call2 -> held 16.3s (proxy requeued + paused the user)
top-up: max_budget -> $0.01
call2 -> 200   <- resumed automatically
```

The proxy treats any `budget_exceeded` response (400/402/422/429) as
"requeue + pause this user until budget refreshes".

## 4. Round-robin across 10 keys, over capacity ✅
Temp user, 10 keys, 20 concurrent requests; proxy forced to `3 per 3s` window
(test override):

```
statuses: {200: 20}    total: 19.0s    max latency: 18.9s (< MAX_WAIT 120)

grant key sequence: [6,7,8,10,4,2,5,1,9,3, 6,7,8,10,4,2,5,1,9,3]
per-key counts:     {1:2, 2:2, 3:2, 4:2, 5:2, 6:2, 7:2, 8:2, 9:2, 10:2}
```

Cycles **all 10 keys** (twice), equal share — round-robin, not FIFO.

> An earlier 2-key run looked like `A,A,B,B`; that was because capacity (3)
> absorbed A's two + B's first, leaving only one queued job. With genuinely
> over-capacity load (above) the RR interleaving is confirmed.

## 5. Cost / spend accounting ✅
```
2026-10-30T09:43:29  spend=3.8e-05  tokens=35   (31 in x 1e-6 + 4 out x 2e-6)
```

## 6. Deterministic tests (local) ✅
- `tests/test_round_robin.py`: interleave, skip-no-capacity, uneven-queue
  fairness, window reset — all pass.
- Fake-upstream integration: passthrough 200; upstream 429 -> requeue -> 200;
  over-budget -> hold -> 429 at `MAX_WAIT`.

## Caveats
- `selfhost-test` is a **config model** (cost 1e-6/2e-6). Its `api_base` is an
  **ephemeral quick tunnel**; on tunnel restart, edit `litellm/config.fly.yaml`
  and redeploy (or adopt a named tunnel).
- Test-mode overrides (`FORCE_USER_RPM`, `FORCE_KEY_RPM`, short `WINDOW_SECONDS`)
  were used for the live RR test and removed afterwards.
- v1 is in-memory / single replica (see `REDIS.md`).
