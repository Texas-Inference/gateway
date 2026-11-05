# Spec: Customer chat web app (encrypted, live verification badge)

Product spec for the customer chat app. RFC-6 covers the console (T11); it does
**not** cover the app where users chat. This spec does. Depends on **Liam's browser
encryption client** (do not reimplement encryption).

Repository: `[DISCOVER]` (new chat frontend, or a new route in `Texas-Inference/platform`).
Builds on RFC-6 and RFC-8; consumes the Management API (T18) and worker gateway (T19).

## Goal

A web app where a signed-in user chats with an inference session, sees a **live
encryption badge** driven by Liam's browser client, and — when prepaid credits run
out — gets an **in-chat error that stays in the message list**, with a **Resend**
button that succeeds once credits are added. No server route ever carries a
readable prompt (RFC-6 L10/L11).

## Scope — files and services touched

- Chat UI (composer, message list, streaming, error bubble, Resend): `[DISCOVER]` path.
- Encryption integration (wrap Liam's browser client; badge state): `[DISCOVER]`.
- API/session client (token exchange, sessions, usage, billing): `[DISCOVER]`.
- Tests (unit + Playwright e2e) and `checks/check-chat-app`.
- No changes to the worker, ledger, or gateway (T18/T19 own those).

## Interfaces and data

- **Auth/session (RFC-8 §3, RFC-6 §7):** `POST /v1/auth/token` (API key → access
  token), `POST /v1/sessions` (offering, `mode` = `pooled`|`exclusive`, `route`),
  `GetSession`, `RenewSession`, `ReleaseSession`, `GetUsage`, `GetSigningKeys`,
  `CreateBillingSession` (top-up).
- **Worker (via T19 gateway):** `GetSessionEvidence`, `CreateChatCompletion`,
  `CreateMessage`, `CreateResponse`; bodies are the **RFC-8 protected envelope**
  (ciphertext only).
- **Liam's browser encryption client** `[DISCOVER]`: initialise, encrypt request,
  decrypt stream, verify evidence, and emit a verification status
  (`verified | degraded | off`). Do not modify its verification code.
- **Credits exhaustion:** production API returns **`CREDITS_EXHAUSTED` (402, no
  `reset_at`)** per RFC-6 rev. (PR #16; gated on RFC-8 6.1). Coding plans return
  `ENTITLEMENT_EXHAUSTED` (429 + `reset_at`). The UI handles both; only the 402
  path uses Resend-until-top-up.
- **Resend idempotency:** each message has `client_message_id`; resend reuses it and
  the `Idempotency-Key`, so a retried request never double-bills.
- **Badge contract:** "verified" only for a **fresh** session that passed every
  check; failure states shown otherwise. Label an exported bundle "evidence
  verified", never "session verified" (RFC-6 T11 wording).

## Step-by-step instructions

1. **Discovery.** Read RFC-6 §1/§5/§8 and T11, RFC-8 §2.5/§3/§4/protected-transport,
   and Liam's browser client README. Record app repo/framework, auth flow, the
   encryption client's exact API, and the session/streaming routes. Confirm no
   route accepts plaintext (L10).
2. **Scaffold.** Add the chat route/app (auth required). Message list + composer +
   streaming renderer. No plaintext leaves the browser: only the client's
   encrypted envelope is POSTed.
3. **Session + verification.** Exchange the API key for a token, create a session,
   fetch `GetSessionEvidence`, run the client's verify, and drive the badge from its
   status/change callback.
4. **Live badge.** Show `verified|degraded|off`; on a stale or failed verification,
   show the failure state and withhold "verified". e2e covers all three fixtures.
5. **Credits-exhausted UX.** On `402 CREDITS_EXHAUSTED` (or `429
   ENTITLEMENT_EXHAUSTED`), keep the user's message visible and render an in-chat
   error with a **Resend** button. Resend re-submits the same encrypted payload +
   `Idempotency-Key`; on success replace the error; on repeated 402 keep it and
   offer the top-up link (`CreateBillingSession`).
6. **Usage + top-up.** Show credit balance/allowance from `GetUsage`; open Stripe
   billing session for top-up; refresh balance after return.
7. **Tests.** Unit (state machine, error mapping, idempotency), Playwright e2e with
   a mock gateway (badge states, ciphertext-only assertion, 402→resend→success).
8. **Check.** Add `checks/check-chat-app` (below).

## Check script — `checks/check-chat-app`

Adds a script that prints `PASS:` last and exits 0 on success (so `checks/run-all.sh`
accepts it). Uses the e2e suite against the mock gateway.

```bash
#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
fail=0
p(){ echo "PASS: $1"; }; f(){ echo "FAIL: $1"; fail=1; }

npm --prefix . run -s test:unit 2>/dev/null && p "unit tests" || f "unit tests"
npx playwright test e2e/encryption_badge.spec.ts 2>/dev/null && p "badge states" || f "badge states"
npx playwright test e2e/ciphertext_only.spec.ts 2>/dev/null && p "no plaintext to server" || f "no plaintext to server"
npx playwright test e2e/credits_exhausted.spec.ts 2>/dev/null && p "402 error + resend" || f "402 error + resend"
npx playwright test e2e/resend_after_topup.spec.ts 2>/dev/null && p "resend succeeds after top-up" || f "resend after top-up"

[ "$fail" -eq 0 ] && { echo "PASS: chat app verified"; exit 0; } || { echo "FAIL: chat app"; exit 1; }
```

The e2e suite must assert the server/mock received **only** ciphertext (no prompt
text) on every inference call.

## Out of scope

- The console (RFC-6 T11), desktop app, server/ledger, gateway authorization (T19).
- Changing Liam's encryption client or its verification code.
- Passkey-unlocked chat history (RFC-6 Q11).

## Dependencies

- **Liam's browser encryption client** (package + API doc) — hard dependency.
- RFC-8 protected transport and the Management API (T18) / gateway (T19).
- T05/T07 (keys, sessions, credits) and **RFC #16** for `CREDITS_EXHAUSTED`.
- Mock gateway for e2e; Playwright; auth from the platform.
- `[DISCOVER]`: app repo/framework and the exact encryption-client API names.
