# Cutover: repoint existing model names to the self-hosted GPU

Goal: stop sending traffic to the old upstreams (SiliconFlow / OpenCode Zen) and
send it to your own GPU instead — **with rollback**.

## ⚠️ Do NOT run this against the Qwen test model
Repointing `kimi3` / `deepseek-v3` to the current tunnel would serve **Qwen 0.5B**
under those names — users would silently get a toy model. Run the cutover **only
after** the B300 serves **DeepSeek-V4.1-Flash** and quality is verified.

## Current routing (baseline to restore on rollback)
| model name | points to | upstream |
|---|---|---|
| `deepseek-v3` | `openai/deepseek-ai/DeepSeek-V3` | `https://api.siliconflow.com/v1` |
| `kimi3` | `openai/kimi-k3` | `https://opencode.ai/zen/v1` |
| `kimi-k3` | `openai/kimi-k3` | `https://opencode.ai/zen/v1` |
| `selfhost-test` | `openai/qwen-tiny` | your tunnel |

- `deepseek-v3` is defined in **`litellm/config.fly.yaml`** (static) → change +
  **redeploy**.
- `kimi3`, `kimi-k3`, `selfhost-test` are **DB models** (added via UI/API) → edit
  or delete/re-add via UI/API.

Record the upstream keys' values (Fly secrets) before editing:
```sh
fly secrets list -a superstackai-gateway
# you'll need SILICONFLOW_API_KEY / OPENCODE_ZEN_API_KEY if you delete+re-add
```

## Cutover options

### Option A — switch the app to a new model name (safest, recommended)
Leave the old entries untouched; change what the app/user sends to
`deepseek-v4.1` (a new entry pointing at your GPU). Rollback = revert the app config.
- Pros: no risk to live entries; instant rollback.
- Needs: the app to read a configurable model name (or a quick code change).

Add the production entry (name can be `deepseek-v4.1`):
```sh
GATEWAY=https://superstackai-gateway.fly.dev
MK=<master-key>
TUNNEL=https://<named-tunnel-host>

curl -sS -X POST "$GATEWAY/model/new" -H "Authorization: Bearer $MK" -H "Content-Type: application/json" \
  -d "{\"model_name\":\"deepseek-v4.1\",\"litellm_params\":{\"model\":\"openai/deepseek-ai/DeepSeek-V4.1-Flash-1017\",\"api_base\":\"$TUNNEL/v1\",\"api_key\":\"os.environ/SELFHOST_DS_KEY\"},\"model_info\":{\"input_cost_per_token\":0.0,\"output_cost_per_token\":0.0}}"
```
Then point the app at `deepseek-v4.1`.

### Option B — repoint the SAME name (no app change)
Replace what `kimi3` / `deepseek-v3` resolves to, so existing app calls now hit the GPU.

**B1 — DB model (`kimi3`): via UI (preferred)**
- LiteLLM UI → Models → `kimi3` → Edit → set:
  - `model` = `openai/deepseek-ai/DeepSeek-V4.1-Flash-1017`
  - `api_base` = `https://<tunnel>/v1`
  - `api_key` = the SGLang upstream key (or `os.environ/SELFHOST_DS_KEY`)
- Save (no redeploy).
- Rollback: edit back to `openai/kimi-k3` + `https://opencode.ai/zen/v1` + old key.

**B2 — config model (`deepseek-v3`): edit + redeploy**
1. Edit `litellm/config.fly.yaml` model entry to:
   ```yaml
   - model_name: "deepseek-v3"
     litellm_params:
       model: "openai/deepseek-ai/DeepSeek-V4.1-Flash-1017"
       api_base: "https://<tunnel>/v1"
       api_key: "os.environ/SELFHOST_DS_KEY"
   ```
2. `fly deploy -a superstackai-gateway` (from `litellm/`).
3. Rollback: `git checkout litellm/config.fly.yaml && fly deploy -a superstackai-gateway`.

> Prefer **Option A** if the app can use a new model name; it avoids editing live
> entries and gives a clean rollback.

## Verify the cutover
```sh
# should now answer from the GPU for the repointed name
curl -sS "$GATEWAY/v1/chat/completions" -H "Authorization: Bearer $MK" \
  -H "Content-Type: application/json" \
  -d '{"model":"kimi3","messages":[{"role":"user","content":"ping"}]}'

# spend log should show the new api_base for that model_group
curl -sS "$GATEWAY/spend/logs" -H "Authorization: Bearer $MK" \
  | python3 -c "import sys,json;[print(r.get('startTime'),r.get('model_group'),r.get('api_base')) for r in json.load(sys.stdin)[-10:]]"
```

## Confirm no traffic still hits the old upstreams
Use the script:
```sh
GATEWAY=https://superstackai-gateway.fly.dev \
MK=<master-key> \
SINCE=2026-11-01T00:00:00Z \
./usage-check.sh
```
- It groups spend logs by `model_group`, prints the `api_base`s, and **flags** any
  traffic to `api.siliconflow.com` or `opencode.ai/zen` (exit code 2).
- Also check the providers' own dashboards (SiliconFlow, OpenCode Zen) to confirm
  usage has stopped.

## Rollback checklist
- **Option A:** revert the app's model name → done.
- **B1 (`kimi3`):** UI → edit back to `openai/kimi-k3` / `https://opencode.ai/zen/v1` / old key.
- **B2 (`deepseek-v3`):** `git checkout litellm/config.fly.yaml` → `fly deploy -a superstackai-gateway`.
- Re-run `usage-check.sh` to confirm traffic returns to the old upstream.

## Pre-cutover gates
- [ ] B300 serving **DeepSeek-V4.1-Flash** and quality verified.
- [ ] **Named tunnel** (stable hostname), not a quick tunnel.
- [ ] Real `input/output_cost_per_token` set for the model.
- [ ] Token counts verified against the real model.
- [ ] Rollback values recorded (this file + Fly secrets).
