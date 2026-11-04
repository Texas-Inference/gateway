#!/usr/bin/env bash
set -euo pipefail

# Summarize LiteLLM spend logs by model_group and flag any traffic still hitting
# the old upstreams (SiliconFlow / OpenCode Zen).
#
# Usage:
#   GATEWAY=https://... MK=sk-... ./usage-check.sh
#   GATEWAY=https://... MK=sk-... SINCE=2026-11-01T00:00:00Z ./usage-check.sh
#
# Exit codes: 0 = clean, 2 = old-upstream traffic detected.

: "${GATEWAY:?set GATEWAY}"
: "${MK:?set MK (LiteLLM master key)}"
SINCE="${SINCE:-}"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

if ! curl -sS "$GATEWAY/spend/logs" -H "Authorization: Bearer $MK" -o "$tmp"; then
  echo "FAIL: could not fetch /spend/logs"
  exit 1
fi

python3 - "$SINCE" "$tmp" <<'PY'
import sys, json
from collections import defaultdict

since = sys.argv[1]
with open(sys.argv[2]) as f:
    data = json.load(f)

rows = data if isinstance(data, list) else data.get("data", [])
if since:
    rows = [r for r in rows if (r.get("startTime") or "") >= since]

agg = defaultdict(lambda: {"n": 0, "tok": 0, "last": "", "bases": set()})
for r in rows:
    g = r.get("model_group") or r.get("model") or "?"
    a = agg[g]
    a["n"] += 1
    a["tok"] += r.get("total_tokens", 0) or 0
    t = r.get("startTime", "") or ""
    if t > a["last"]:
        a["last"] = t
    b = r.get("api_base") or ""
    if b:
        a["bases"].add(b)

print(f"logs considered: {len(rows)}" + (f"  (since {since})" if since else ""))
print(f"{'model_group':18} {'n':>5} {'tokens':>10}  last")
old = ("api.siliconflow.com", "opencode.ai/zen")
flagged = []
for g in sorted(agg):
    a = agg[g]
    bases = sorted(a["bases"])
    hit_old = any(any(o in b for o in old) for b in bases)
    if hit_old:
        flagged.append(g)
    print(f"{g:18} {a['n']:>5} {a['tok']:>10}  {a['last']}  {'[OLD-UPSTREAM]' if hit_old else ''}")
    for b in bases:
        print(f"{'':18}   -> {b}")

if flagged:
    print(f"\nWARNING: still hitting old upstreams via: {', '.join(flagged)}")
    sys.exit(2)
print("\nOK: no traffic to old upstreams in the considered window.")
PY
