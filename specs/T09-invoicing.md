# T09 spec: Invoicing under the credit model (RFC-6 rev. 2–4 Nov, PR #16)

Implementation spec for RFC-6 ticket **T09** (rows D01, A07), under the **credit
model** in RFC #16. Depends on **T07** (ledger/meter) and **T04** (plan/model_rate).
Blocked on **RFC #16 merging**.

Repository: `Texas-Inference/platform`.

## Goal

Invoices reconcile row-by-row to the credit model:
- **Coding plan:** plan charge + the period's usage summed from `usage_event`; **no
  overage line** (L9).
- **Production API:** each credit purchase (`Purchase.credits_granted`, admin
  `credit_grant`) and the period's usage **priced at the `model_rate` that applied
  when each request ran**.
- **Lane:** the lane charge.
Done means `checks/check-T09` prints `PASS`.

## Scope — files and services touched

- `app/src/payment/*` and the billing service — invoice generation job.
- Ledger reads: `usage_event`, `credit_balance`, `credit_grant`, `model_rate`,
  `plan`, `plan_stripe_price`, `stripe_account`, `Purchase` (RFC-6 §6, PR #16).
- Stripe integration per brand (`stripe_account`); `CreateBillingSession`,
  `GetBilling` (RFC-8 §3.1).
- `docs/T09-runbook.md` (reconciliation report).
- `checks/check-T09` *(new)*.

## Interfaces and data

- **Pricing:** `model_rate(product, offering_id, input_per_million,
  output_per_million, cache_read_per_million, effective_from)` is insert-only. Price
  each `usage_event` at the rate whose `effective_from <= started_at` is latest.
  Never price in the client or console.
- **Usage:** `usage_event` unique on `receipt_id`; `input_tokens`, `output_tokens`,
  `cached_input_tokens`; billed per product.
- **Credits:** production API debits `credit_balance` at settlement; `credit_grant`
  is insert-only (admin) and `Purchase.credits_granted` records purchased credits.
  Coding plans have no top-ups/overage (L9).
- **Invoice model per product:**
  | Product | Invoice lines |
  |---|---|
  | coding_plan | plan charge; usage (credits) for the period; no overage |
  | production_api | each credit purchase; usage priced at `model_rate`; remaining balance shown |
  | lane | lane charge |
  | rental | out of scope here (T10 bills GPU-hours) |
- **Upgrades:** take effect at once with Stripe proration; customer portal for
  payment methods and past invoices.
- **Idempotency:** one invoice per `(org_id, period, product)`; Stripe invoice IDs
  stored; replays add nothing.

## Step-by-step instructions

1. **Discovery.** Read RFC-6 rev. 2–4 Nov (§2 L9/L26, §6 tables, §7.3/7.4, §9 T07/T09)
  and PR #16 diff; read T04/T07 code. Record the plan, `model_rate`, `credit_*`,
  `stripe_account` schemas and the ledger's settlement source.
2. **Usage valuation.** Add a pure function `price_usage(org, period)` that joins
  `usage_event` to the effective `model_rate` and returns per-product line items.
   Unit-test the effective-date boundary and cached-input.
3. **Invoice assembly.** Build invoices per product: coding plan (plan + usage), the
  production API (purchases + priced usage + remaining balance), lane (lane charge).
   No overage line for coding plans.
4. **Stripe per brand.** Resolve the `stripe_account` by brand; create/close invoices
  idempotently; store Stripe invoice IDs; handle proration on upgrades.
5. **Reconciliation.** A job that reconciles each closed invoice to the sum of that
  period's `usage_event`, the credit purchases/grants, and the lane charge; records
  mismatches for the runbook.
6. **Customer portal.** Ensure `CreateBillingSession` opens the Stripe portal for
  payment methods and past invoices.
7. **Tests.** Unit (valuation, boundaries), integration (Stripe test mode end to
  end), smoke (nightly reconciliation reports zero mismatch).
8. **Check.** Add `checks/check-T09` (below).

## Check script — `checks/check-T09`

Prints `PASS:` last and exits 0 on success. Runs against Stripe **test mode** and a
seeded ledger.

```bash
#!/usr/bin/env bash
# RFC-6 T09 under the credit model (RFC #16). Requires Stripe test mode + a seeded
# ledger (usage_event, model_rate, credit_balance, credit_grant, plan).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
fail=0
p(){ echo "PASS: $1"; }; f(){ echo "FAIL: $1"; fail=1; }

[ -n "${T09_ORG_ID:-}" ] && p "fixture org set" || f "T09_ORG_ID not set"
[ -n "${STRIPE_TEST_KEY:-}" ] && p "stripe test key set" || f "STRIPE_TEST_KEY not set"

python3 checks/t09/price_usage.py --check 2>/dev/null \
  && p "usage priced at effective model_rate" || f "usage pricing"
python3 checks/t09/invoice_reconcile.py --check 2>/dev/null \
  && p "invoice reconciles to usage_event" || f "invoice reconciliation"
python3 checks/t09/credits_reconcile.py --check 2>/dev/null \
  && p "credit purchases + grants appear" || f "credit reconciliation"
python3 checks/t09/no_overage.py --check 2>/dev/null \
  && p "no overage line on coding plans" || f "coding-plan overage found"
python3 checks/t09/idempotent.py --check 2>/dev/null \
  && p "invoice generation idempotent" || f "invoice not idempotent"

[ "$fail" -eq 0 ] && { echo "PASS: T09 invoicing verified"; exit 0; } || { echo "FAIL: T09 invoicing"; exit 1; }
```

`checks/t09/*.py` are small fixtures the ticket adds: they read the seeded ledger,
recompute expected lines, and compare to the generated invoice.

## Out of scope

- Tax filing, revenue recognition, dunning, multi-currency (unless RFC #16 requires).
- Worker metering and grant settlement (T07).
- Rental GPU-hour billing (T10).

## Dependencies

- **RFC #16 merged** (PR #16): credit model, `model_rate`, `credit_balance`,
  `credit_grant`, `stripe_account`, `CREDITS_EXHAUSTED` proposal.
- **T07** (ledger/meter) and **T04** (plan + `model_rate`).
- **Texas Inference Stripe accounts** per brand (test + live) and products/prices.
- `checks/t09/` fixtures; nightly reconciliation job.
