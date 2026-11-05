# T16 spec: Operations — monitoring, alerts, secrets, runbook

Implementation spec for RFC-6 ticket **T16** (rows F02–F05, F08, F09, F12, F18, G03).
Repository: `Texas-Inference/platform`. Depends on **T13** (compose stack) and builds
on T01–T03.

## Goal

Make the T13 stack operable. TLS is terminated by Caddy; secrets at rest are
managed with SOPS and age; Prometheus, Grafana, Loki, Alertmanager and uptime
checks run beside the app; alerts fire within five minutes of a failed service;
per-organization views come from `usage_event` and logs (never metric labels); and
admin login is on its own path. Done means `checks/check-T16` prints `PASS`.

## Scope — files and services touched

All paths are in `Texas-Inference/platform`.

- `deploy/compose.yml` — add `prometheus`, `grafana`, `loki`, `alertmanager`, `uptime` (pinned images + digests), on the `data`/`edge` networks as appropriate; no public port except Grafana behind Caddy.
- `deploy/Caddyfile` — Grafana and the admin login path; TLS already from T13.
- `deploy/ops/prometheus.yml`, `deploy/ops/alerts.yml`, `deploy/ops/alertmanager.yml`, `deploy/ops/loki.yml`, `deploy/ops/grafana/dashboards.json` *(new)*.
- `.sops.yaml` and `deploy/env/*.sops.yaml` *(new)* — encrypt the T13 `env` files with age; plaintext only on the host at deploy time.
- `deploy/init-secrets.sh` — write SOPS-encrypted files; resolve `age` key from the secret store.
- `app/src` — `/metrics` on the server (RFC-6 section 8.5 names), if not already present; admin login path distinct from customer login.
- `docs/T16-runbook.md` *(new)* — on-call runbook.
- `checks/check-T16` *(new)* — PASS/FAIL check.

## Interfaces and data

- **Metrics** (exact names, RFC-6 §8.5, no organization label):
  `cp_token_exchanges_total{result}`, `cp_session_requests_total{mode,result}`,
  `cp_entitlement_checks_total{caller,result}`, `cp_entitlement_check_seconds{caller}`,
  `cp_gateway_auth_total{result}`, `ledger_grants_total{result}`,
  `ledger_unsettled_tokens`, `cp_usage_records_total{result}`, `cp_usage_gaps_total`,
  `cp_relay_lag_seconds`, `cp_allowance_refusals_total{window}`,
  `rental_reservations{state}`.
- **Health:** `GET /health` → `200 {"status":"ok"}` for each service.
- **Alerts (minimum):** `ServiceDown` (`up == 0`, for 2m), `HighErrorRate` (5xx > 5%,
  10m), `HighLatency` (p95 > 2s, 10m), `EntitlementRefusalSpike`
  (`increase(cp_allowance_refusals_total[10m]) > 20`), `NoMetrics`
  (`absent(up)`, 5m). Route to `[DISCOVER]` pager; each rule carries
  `severity` and `runbook_url`.
- **Secrets:** every T13 `deploy/env/*` file becomes SOPS-encrypted
  (`*.sops.yaml`) with age; no plaintext secret in git, an image or a build arg.
  Record inventory in `docs/T16-runbook.md` (name, owner, used-by, rotation).
- **Per-organization views:** Grafana and Loki queries filter by `org_id` present
  in `usage_event` rows and in logs; **never** by a metric label (RFC-6 T16 item 2).
- **[DISCOVER]:** paging provider, uptime provider, age recipient, existing
  `/metrics` support, and the admin login path name.

## Step-by-step instructions

1. **Discovery.** Read `deploy/compose.yml`, `deploy/Caddyfile`, `deploy/env/*.example`,
   `app/main.wasp`, and `docs/T13-spec.md`. Record: services, ports, health paths,
   existing metrics, admin vs customer login routes, and the pager/uptime providers.
2. **Instrument.** Ensure each service exposes `/health` and `/metrics` with the
   exact names above. Add a Prometheus scrape config; do not add an `org` label to
   any metric.
3. **Monitoring stack.** Add `prometheus`, `grafana`, `loki`, `alertmanager` and an
   uptime check to `deploy/compose.yml` (pinned image + digest). Persist volumes
   with fixed names and the `org.ti.stack=prod` label; `restart: unless-stopped`;
   memory limits and the `json-file` log driver, matching T13.
4. **Dashboards and alerts.** Create `deploy/ops/grafana/dashboards.json` (valid
   Grafana JSON: platform overview + per-service panels for up, RPS, errors, p95,
   allowance refusals, unsettled tokens) and `deploy/ops/alerts.yml` with the rules
   above. Route to the pager; include `runbook_url`.
5. **Secrets.** Add `.sops.yaml` (age recipient `[DISCOVER]`) and encrypt every
   `deploy/env/*` file to `*.sops.yaml`. Update `deploy/deploy.sh` to decrypt at
   deploy time and `deploy/init-secrets.sh` to write encrypted files. Remove
   plaintext secrets from the machine's `/etc/ti` at rest (keep only decrypted
   copies needed by compose, or decrypt to a tmpfs).
6. **Per-organization views.** Add Grafana/Loki views that filter by `org_id` from
   `usage_event` and log fields (never metric labels). Document the queries.
7. **Admin login.** Put admin login on its own path, distinct from customer login;
   restrict to platform admins; document the path.
8. **Runbook.** `docs/T16-runbook.md`: Start, Stop, Rollback, Incidents
   (ServiceDown, high errors, high latency, entitlement refusal spike), Credits
   (`ENTITLEMENT_EXHAUSTED` surface, top-up, customer-facing resend), Escalation,
   On-call, Secret rotation, and the alert→runbook map.
9. **Check.** Add `checks/check-T16` (below), make it executable; `checks/run-all.sh`
   picks it up automatically.

## Check script — `checks/check-T16`

Adds `checks/check-T16` (executed by `checks/run-all.sh`, which requires the last
line to start `PASS:`). Config checks always run; the destructive drill runs only
with `DRILL=1` on staging.

```bash
#!/usr/bin/env bash
# RFC-6 T16: monitoring, alerts, secrets, runbook.
#   checks/check-T16            config checks only
#   DRILL=1 checks/check-T16    also stop the server and require an alert within 5m
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
fail=0
p(){ echo "PASS: $1"; }; f(){ echo "FAIL: $1"; fail=1; }

for f in deploy/compose.yml deploy/Caddyfile \
         deploy/ops/prometheus.yml deploy/ops/alerts.yml deploy/ops/alertmanager.yml \
         deploy/ops/loki.yml deploy/ops/grafana/dashboards.json .sops.yaml \
         docs/T16-runbook.md; do
  [ -e "$f" ] && p "exists $f" || f "missing $f"
done

python3 - <<'PY' || fail=1
import json, yaml
for f in ["deploy/ops/prometheus.yml","deploy/ops/alerts.yml","deploy/ops/alertmanager.yml","deploy/ops/loki.yml"]:
    yaml.safe_load(open(f))
json.load(open("deploy/ops/grafana/dashboards.json"))
print("PASS: ops configs parse")
PY

# No plaintext secrets (allow encrypted sops files only).
if grep -RInE --exclude-dir=.git --exclude='*.sops.yaml' \
     'sk-[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY|password[[:space:]]*[:=][[:space:]]*[^$]' \
     deploy app 2>/dev/null | grep -vE 'example|\.sops\.yaml'; then
  f "plaintext secret found"; else p "no plaintext secrets"; fi

# Required metric/alert names.
for m in cp_token_exchanges_total cp_session_requests_total cp_entitlement_checks_total \
         cp_entitlement_check_seconds cp_gateway_auth_total ledger_grants_total \
         ledger_unsettled_tokens cp_usage_records_total cp_usage_gaps_total \
         cp_relay_lag_seconds cp_allowance_refusals_total rental_reservations; do
  grep -Rq "$m" deploy/ops app/src 2>/dev/null && p "metric $m" || f "metric $m"
done
for a in ServiceDown HighErrorRate HighLatency EntitlementRefusalSpike NoMetrics; do
  grep -q "alert:[[:space:]]*$a" deploy/ops/alerts.yml && p "alert $a" || f "alert $a"
done

# Runbook sections.
for s in Start Stop Rollback Incidents Credits Escalation On-call; do
  grep -qi "$s" docs/T16-runbook.md && p "runbook $s" || f "runbook $s"
done

# Admin login must be its own path.
grep -RqiE 'admin' deploy/Caddyfile app/main.wasp 2>/dev/null && p "admin path present" || f "admin path missing"

# Per-org views must not use metric labels.
if grep -RqiE 'org_id' deploy/ops/grafana/dashboards.json deploy/ops/loki.yml; then
  p "org_id present in views"; else f "org_id missing in views"; fi

# Optional destructive drill: server stops -> ServiceDown alert within 5m.
if [ "${DRILL:-0}" = "1" ]; then
  AM="${ALERTMANAGER_URL:-http://localhost:9093}"
  docker compose -f deploy/compose.yml stop server >/dev/null 2>&1
  ok=0
  for _ in $(seq 1 60); do
    if curl -fsS "$AM/api/v2/alerts" 2>/dev/null | grep -q '"alertname":"ServiceDown"'; then ok=1; break; fi
    sleep 5
  done
  docker compose -f deploy/compose.yml start server >/dev/null 2>&1
  [ "$ok" = 1 ] && p "ServiceDown alert within 5m" || f "no ServiceDown alert within 5m"
fi

[ "$fail" -eq 0 ] && { echo "PASS: T16 operations verified"; exit 0; } \
                  || { echo "FAIL: T16 operations"; exit 1; }
```

## Out of scope

- Application features, billing, sessions, the inference gateway (T19).
- Provisioning a managed monitoring backend; use the self-hosted stack above.
- Cloudflare Access/WAF on the public edge.
- The withdrawn T17 and the paused queue-proxy.

## Dependencies

- **T13** merged (compose stack, Caddy TLS, backups).
- **T01–T03** in `platform` (CI, contract, org/roles/RLS).
- `[DISCOVER]`: paging provider, uptime provider, age recipient, admin login path.
- RFC-6 §8.5 metric names and the section 8.3 entitlement error surface.
- Host has `docker compose`, `sops`, `age`, `curl`, `python3` with PyYAML.

## Rollback

Revert the PR; `docker compose` drops the new services. No migrations. Restore
plaintext `/etc/ti` handling from T13 if SOPS rollout is reverted.
