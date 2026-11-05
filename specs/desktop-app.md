# Spec: Desktop app (macOS + Windows) — signed installers, notarization, auto-update

Product spec for a desktop app that **wraps `ti-connect` without changing its
verification code**, ships signed installers for macOS and Windows, and updates
itself. Everything ships under **Texas Inference** accounts, never personal ones.

Repository: `[DISCOVER]` (new `ti-desktop`). Builds on RFC-6/RFC-8; `ti-connect`
is a hard dependency (Liam).

## Goal

A macOS and Windows app that starts `ti-connect`, exposes a local chat/compatible
UI, and never touches `ti-connect`'s verification logic. Installers are signed and
(macOS) notarized; updates are signed and verified. Release artifacts are built by
CI using Texas Inference Apple/Windows signing credentials.

## Scope — files and services touched

- Desktop shell + lifecycle (start/stop `ti-connect`, health, logs): `src/main/*`.
- Bundled `ti-connect` (as a dependency; not patched): `vendor/` or package dep.
- UI (reuse the web app's chat/verification badge where possible): `src/ui/*`.
- Build/sign/notarize config: `tauri.conf.json` **or** `electron-builder.yml` `[DISCOVER]`.
- CI release workflow: `.github/workflows/release.yml`.
- Update feed manifest + client verifier: `src/updater/*`, `latest.json`.
- Docs: `docs/release.md` (signing, rollback).

## Interfaces and data

- **ti-connect**: its local server/API `[DISCOVER]`. Wrap only; **assert no diff**
  to its verification modules (hash or `git diff --quiet`).
- **App lifecycle**: start sidecar on an ephemeral local port; health check; clean
  shutdown; relay its verification status to the badge.
- **Update manifest** `latest.json`:
  `{version, notes, pub_date, platforms: {"darwin-universal": {url, signature}, "windows-x86_64": {url, signature}}}`.
  Clients verify the signature before installing.
- **Signing inputs (CI secrets, TI scope):** `APPLE_TEAM_ID`, `APPLE_SIGNING_IDENTITY`,
  `APPLE_ID` or App Store Connect API key (`APPLE_API_KEY_ID`, `APPLE_API_ISSUER`),
  `APPLE_NOTARY_KEYCHAIN_PROFILE`; Windows `WINDOWS_CERT`/`AZURE_TRUSTED_SIGNING_*`,
  `WINDOWS_TIMESTAMP_URL`; `UPDATE_FEED_URL` + update signing key.
- **Versioning:** semver; monotonic builds; update refuses downgrades.

## Step-by-step instructions

1. **Discovery.** Read `ti-connect` README/entrypoint and its verification modules.
   Record runtime (Node/native), API, and confirm it can be imported without edits.
   Read RFC-6 T11 (badge wording) and RFC-8 protected transport.
2. **Choose shell.** Pick Tauri (Rust) or Electron based on `ti-connect`'s runtime;
   prefer the smallest shell that can bundle it. Record the decision.
3. **Scaffold.** Add the shell; start/stop `ti-connect`; surface its verification
   status (reuse the chat app's badge states). Assert `ti-connect` files are
   unchanged in CI.
4. **Build installers.** macOS universal (`arm64+x86_64`) `.dmg`/`.pkg`; Windows
   `.msi`/`.msix` (x86_64 and arm64 if supported).
5. **Sign + notarize (macOS).** `codesign --deep --force --options runtime` with the
   TI **Developer ID Application** identity; `xcrun notarytool submit --wait` with
   the TI App Store Connect API key; `xcrun stapler staple`.
6. **Sign (Windows).** `signtool sign /tr <timestamp> /td sha256 /fd sha256` with the
   TI certificate (or Azure Trusted Signing); verify with `signtool verify /pa`.
7. **Auto-update.** Publish signed artifacts + `latest.json` to the TI feed; client
   verifies the signature, applies a staged rollout, and can roll back. Refuse an
   unsigned or downgrade update.
8. **CI release.** A tag builds both platforms on macOS/Windows runners with the TI
   secrets; uploads artifacts + manifest; records provenance. No personal accounts.
9. **QA.** Fresh install, launch, sidecar health, verification badge, update from
   previous version, uninstall.
10. **Check.** Add `checks/check-desktop` (below).

## Check script — `checks/check-desktop`

Prints `PASS:` last and exits 0. Signature checks run on the respective runners; on
a runner without `codesign`/`signtool`, CI must still assert artifacts are signed
(the script fails if it cannot verify).

```bash
#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
fail=0
p(){ echo "PASS: $1"; }; f(){ echo "FAIL: $1"; fail=1; }

# 1. ti-connect verification code untouched
[ -d vendor/ti-connect ] && (git diff --quiet -- vendor/ti-connect && p "ti-connect unchanged" || f "ti-connect modified") \
  || p "ti-connect is an external dependency (no vendored diff)"

# 2. artifacts
ls dist/*.dmg dist/*.msi >/dev/null 2>&1 && p "installers present" || f "installers missing"
python3 -c 'import json;json.load(open("dist/latest.json"))' 2>/dev/null && p "update manifest valid" || f "update manifest invalid"

# 3. macOS signature + notarization
if command -v codesign >/dev/null; then
  APP=$(ls -d dist/*.app 2>/dev/null | head -1)
  [ -n "$APP" ] && codesign --verify --deep --strict "$APP" && p "mac signed" || f "mac sign"
  [ -n "$APP" ] && spctl -a -vv "$APP" && p "mac gatekeeper" || f "mac gatekeeper"
  command -v stapler >/dev/null && [ -n "$APP" ] && stapler validate "$APP" && p "mac notarization stapled" || f "mac notarization"
fi

# 4. Windows signature
if command -v signtool >/dev/null; then
  MSI=$(ls dist/*.msi 2>/dev/null | head -1)
  [ -n "$MSI" ] && signtool verify /pa "$MSI" && p "win signed" || f "win sign"
fi

[ "$fail" -eq 0 ] && { echo "PASS: desktop app verified"; exit 0; } || { echo "FAIL: desktop app"; exit 1; }
```

## Out of scope

- Changing `ti-connect` verification code or its crypto.
- Server, ledger, control plane, gateway.
- App-store distribution (unless a stakeholder requires it; then add a separate spec).

## Dependencies

- **`ti-connect`** (Liam) with a documented interface; no edits allowed.
- **Texas Inference Apple Developer Program** (team, Developer ID Application cert,
  App Store Connect API key for notarization).
- **Texas Inference Windows signing** (cert or Azure Trusted Signing) + timestamp.
- **TI-owned update feed** and signing keys; CI secrets scoped to the TI org.
- macOS and Windows CI runners.
- `[DISCOVER]`: shell choice, `ti-connect` runtime/API, artifact formats.
