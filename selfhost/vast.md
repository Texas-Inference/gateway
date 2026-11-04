# Vast.ai cheatsheet (cheap script test)

Vast.ai gives you a **GPU container** (SSH in, no nested Docker), so use
`RUNTIME=bare` instead of the default `docker` wrapper. Plan B (Cloudflare
Tunnel) for exposure.

## Pick an instance

For the cheap test (`Qwen/Qwen2.5-0.5B-Instruct`, ~6 GB VRAM):

- **GPU:** 1× RTX 3060 12 GB (or 3090/4090 if cheap). `TP=1`.
- **Max CUDA ≥ 12.4** (so `lmsysorg/sglang:latest` runs; 12.2 can fail).
- **Reliability ≥ 98%** (prefer 99%+).
- **Disk ≥ 30 GB** (the sglang image is ~20 GB).
- **RAM ≥ 16 GB**, decent network.
- **On-demand** (not interruptible); set your **SSH key**.
- Image: `lmsysorg/sglang:latest` (for V4.1 use `lmsysorg/sglang:dev-dsv41` on B300/H200).

> Vast is a marketplace — verify the host's max CUDA before paying.

## Connect

```sh
ssh -p <port> root@<host>
nvidia-smi            # confirm GPU + driver/CUDA
python3 -c "import sglang; print(sglang.__version__)"
```

## Get the kit onto the instance

```sh
# from your laptop (copy just the kit)
scp -P <port> -r selfhost root@<host>:/root/selfhost

# or clone the repo on the instance
ssh -p <port> root@<host>
git clone <repo-url> /root/gateway && cd /root/gateway/selfhost
```

## Serve (no Docker)

From a checkout of this kit on the instance:

```sh
RUNTIME=bare \
MODEL_ID=Qwen/Qwen2.5-0.5B-Instruct \
SERVED_NAME=qwen-tiny \
IMAGE=lmsysorg/sglang:latest \
TP_SIZE=1 EP_SIZE=1 CONTEXT_LENGTH=32768 MEM_FRACTION=0.80 MAX_RUNNING=16 \
API_KEY="$(openssl rand -hex 24)" \
./serve.sh
```

Equivalent raw command:

```sh
python3 -m sglang.launch_server --model-path Qwen/Qwen2.5-0.5B-Instruct \
  --served-model-name qwen-tiny --host 0.0.0.0 --port 30000 \
  --tp-size 1 --ep-size 1 --context-length 32768 \
  --mem-fraction-static 0.80 --api-key <key>
```

Check it (new SSH session or `&`):

```sh
API_KEY=<key> MODEL=qwen-tiny ./smoke.sh
```

## Expose it

### Option 1 — Cloudflare quick tunnel (recommended, consistent with plan B)

`cloudflared` isn't in the SGLang image; install it (Debian-based image):

```sh
curl -L -o /usr/local/bin/cloudflared \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x /usr/local/bin/cloudflared

MODE=quick SGLANG_PORT=30000 ./cloudflared/run-cloudflared.sh
# copy https://<random>.trycloudflare.com
```

### Option 2 — Vast port mapping (public endpoint, no tunnel)

Vast maps container ports to a public `IP:port` (see the instance's "Connect"
panel). If you expose 30000 there, point LiteLLM straight at
`http://<vast-ip>:<mapped-port>/v1` with the SGLang `API_KEY`.
This is a **public** endpoint — use a strong key (or prefer Option 1).

## Wire LiteLLM

See `cloudflared/litellm-integration.md`:

- `api_base`: `https://<tunnel-url>/v1` (Option 1) or the Vast `IP:port` (Option 2)
- `api_key`: `os.environ/SELFHOST_DS_KEY` (set via `fly secrets set ...`)
- `model_name`: `selfhost-test`

## Verify + clean up

```sh
MODEL=selfhost-test VIRTUAL_KEY=<vk> GATEWAY_BASE=https://<gateway-host> ./test-connection.sh
```

Then **destroy the instance** in Vast (billing is per second; disk/bandwidth may
be billed separately). Delete the temporary LiteLLM entry.

## Notes / gotchas

- **No nested Docker** — always `RUNTIME=bare` (or the raw command) on Vast.
- The container is **ephemeral**: reinstall `cloudflared` each new instance.
- The quick-tunnel URL **changes every restart** (use a named tunnel for stable prod).
- 12 GB easily fits Qwen 0.5B; it does **not** fit DeepSeek (needs ~614 GB).
- Model downloads land in `HF_HOME` (defaults to `HF_CACHE`); a 0.5B model is ~1 GB.
