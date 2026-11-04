# selfhost — DeepSeek V4.1 on our own GPUs

Run `deepseek-ai/DeepSeek-V4.1-Flash` (native FP4/FP8, 256K context) on the 8x
B300 node and plug it into the existing LiteLLM gateway. The gateway app is not
modified — only a model entry is added/repointed.

**Active topology — plan B (Cloudflare Tunnel), no relay, no Tailscale:**

```
GPU box: SGLang :30000 + cloudflared ──▶ Cloudflare edge (https://ds.example.com)
LiteLLM (Fly) ── https://ds.example.com/v1 ──▶ cloudflared ──▶ SGLang
```

> Plan A (Tailscale + Fly relay) is kept in `relay/` for reference only.

## Layout

| Path | Purpose |
|---|---|
| `serve.sh` | SGLang launcher (env-driven; OpenAI `/v1`; `PRINT_ONLY=1` to echo only) |
| `download-weights.sh` | Pre-download HF weights to a volume |
| `smoke.sh` / `bench.sh` | Correctness + throughput checks |
| `test-connection.sh` | Walks GPU -> tunnel -> gateway and reports each hop |
| `.env.example` | Profiles: `prod` (V4.1) / `dryrun` (V4-Flash) / `tiny` (script test) |
| `recipe.md` | **Pinned SGLang configs** (B300 4x TP4·EP4 + DSpark; T4 tiny) |
| `cutover.md` | Repoint `kimi3`/`deepseek-v3` to the GPU (with rollback) |
| `usage-check.sh` | Flag traffic still hitting old upstreams (SiliconFlow/Zen) |
| `check-cuda.sh` | Pre-flight gate: verify driver CUDA before installing |
| `runpod.md` | Rented-GPU runs: cheap smoke -> dry run -> prod |
| `vast.md` | Vast.ai cheatsheet (no nested Docker -> `RUNTIME=bare`) |
| `handoff.md` | Working with the colleague who rents the GPU (you SSH + run it) |
| `cloudflared/` | **Plan B (active):** expose SGLang via Cloudflare Tunnel |
| `litellm-integration.md` | Add/repoint the model entry (Tailscale/relay version) |
| `systemd/sglang.service` | Run on the 8x B300 node |
| `relay/` | **Plan A (reference):** private Fly relay (Tailscale + Caddy) |
| `stub/` | Zero-GPU OpenAI stub for pipeline validation |

## Why this is simple

- DeepSeek ships **official FP4/FP8 checkpoints, MIT-licensed (public)** — no
  self-quantization, no HF token. Checkpoint `deepseek-ai/DeepSeek-V4.1-Flash-1017`
  (~510 GB download).
- V4.1-Flash needs **~614 GB VRAM** — fits one 8x B300 (2.1 TB) with headroom.
- KV cache is tiny (~890 B/token FP4), so 256K context is cheap.
- ⚠️ V4.1 is **not in an SGLang release yet** — use the preview image
  `lmsysorg/sglang:dev-dsv41` (see `recipe.md`).

## Execution order

### Phase A — build the kit (no GPU)
1. Copy `.env.example` -> `.env` and edit.
2. Sanity-check scripts:
   ```sh
   bash -n serve.sh download-weights.sh smoke.sh bench.sh test-connection.sh
   ```
3. (Optional) pre-flight the SGLang command without a GPU:
   ```sh
   API_KEY=x PRINT_ONLY=1 ./serve.sh
   ```

### Phase B — Cloudflare Tunnel (no GPU)
4. Follow `cloudflared/README.md`:
   - **Quick tunnel (test, no account):** on the GPU box (or later),
     `MODE=quick SGLANG_PORT=30000 ./cloudflared/run-cloudflared.sh`.
   - **Named tunnel (prod):** create the tunnel, route DNS, run `cloudflared`
     with your config/token.
   - Then add the LiteLLM entry from `cloudflared/litellm-integration.md`,
     pointing at `https://<tunnel-host>/v1`.
   > Plan A (relay + Tailscale) alternative: `relay/` + `relay/test-relay.md`.

### Phase C — cheap GPU smoke (primary path; local testing not required)
5. Rent **1x L4/A10/4090** and run the tiny model — see "Cheap smoke" in
   `runpod.md`. Walk the chain with `test-connection.sh`. Skip straight to Phase D
   if you'd rather use the dry-run size.
   - *No-GPU alternative (optional):* `stub/README.md` validates routing without
     any GPU.

### Phase D — dry run on real weights (optional)
6. Run `runpod.md` with `deepseek-ai/DeepSeek-V4-Flash` on 2x H200. Skip if you'd
   rather go straight to the node.

### Phase E — the 8x B300 node
7. Install NVIDIA drivers, Docker, `nvidia-container-toolkit`.
8. Install the service:
   ```sh
   sudo cp systemd/sglang.service /etc/systemd/system/sglang.service
   sudo mkdir -p /etc/selfhost && sudo cp .env /etc/selfhost/sglang.env
   sudo systemctl daemon-reload && sudo systemctl enable --now sglang
   ```
9. Download weights (prod profile) with `download-weights.sh`.
10. Copy the kit to `/opt/selfhost` (matching the systemd `WorkingDirectory`).
11. Verify: `API_KEY=<key> ./smoke.sh` and `./bench.sh`.
12. Expose it via Cloudflare Tunnel (plan B):
    ```sh
    MODE=config CF_CONFIG=$HOME/.cloudflared/config.yml ./cloudflared/run-cloudflared.sh
    ```
    (or `MODE=token CF_TOKEN=<token> ...`). The public hostname now reaches SGLang.

### Phase F — production
13. Add the LiteLLM entry (`cloudflared/litellm-integration.md`) and verify with a user key.
14. Load-test; tune `MAX_RUNNING` / `MEM_FRACTION`.
15. Clean up: stub, rental pod, temporary LiteLLM entries.

## Switching models later

Edit `MODEL_ID` (and parallel/KV flags) in `.env`, restart `serve.sh`, and update
the model entry if the served name changes. The user-facing model name can stay
the same, so users are unaffected.

## GPU-specific flags

See **`recipe.md`** for the pinned B300 (TP4·EP4 + DSpark) and T4 configs, the
preview image, and the **8× B300 topology decision** (single TP8 vs 2× TP4·EP4).
The prod `EXTRA_ARGS` are already set in `.env.example`. Note the hard constraint
**CP=1, DCP=1**. Verify the preview image tag before the production run.
