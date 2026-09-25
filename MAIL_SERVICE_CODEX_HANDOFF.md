# Codex handoff: extract Mail Service to an independent repository

**Destination (create as PRIVATE first):** `skyday85/mail-service`
**Source snapshot:** `skyday85/-`, branch `codex/mail-service-extraction`,
working files below `ai/main-agent/` and stacked source draft PRs #1-#4.
**Do not merge source PRs or copy the source Git history.** It contains
unrelated Fleet/Finance/Main Agent components and is presently public.

The destination is a separate, independently deployable application with its
own `main`, `develop`, and `feature/*` branches. Work first on
`feature/standalone-mail-extraction` from destination `develop`.

## Current code map

- `mail_contour/`: logical inbox, safe duplicate grouping, message ingestion,
  provider adapters, assigned-user permissions, routing, archive import,
  persistence and deduplicated business side effects.
- `mail_gateway/`: independent Gmail/Outlook OAuth backend and encrypted
  token vault. Keep it separate from the user-facing application server.
- `http_api/mail_admin_router.py`, mail portions of `http_api/app.py`:
  organization-scoped admin and mail APIs. Existing `app.py` includes unrelated
  Finance/Fleet routes; **extract**, do not copy the entire module unchanged.
- `clients/unified-app/`: React/Vite/Tauri shell, mail screens and API. Existing
  default `App.tsx` includes Finance/Fleet/other modules; reduce it to mail
  rather than silently keeping those modules as dependencies.
- `tests/test_mail_*.py`, `test_cross_mail_dedup.py`,
  `test_unified_mail_and_clients.py`: select/refactor tests for mail-only
  initialization. Do not import the old combined `runtime.MainAgentRuntime`
  in the final destination.
- `MAIL_SERVICE_BETA_RU.md`: description of temporary manual .eml/.mbox import.
  This is **not** live IMAP support.

## Target layout (names can change if architecture improves)

```text
mail-service/
  AGENTS.md
  README.md
  .env.example
  .gitignore
  backend/
    app/               # independently runnable mail-only FastAPI
    mail/              # account/grant/inbox/dedup/sync/classification/archive
    integrations/      # optional HTTPS outbox, no fleet imports
    migrations/
    tests/
  gateway/             # provider clients + encrypted secret vault, isolated
  client/              # mail-only React/Vite + optional Tauri
  docs/
    SECURITY.md
    MAILBOX_CONNECT.md
    OPERATIONS.md
  .github/workflows/ci.yml
```

Have two distinct deployables: user-facing API and the credentials-owning
gateway. Use a durable worker/scheduler for ingestion and OCR processing.
Define a provider interface so Gmail, Outlook, Mail.ru, Yandex and Timeweb
feed the SAME immutable source-message model.

## Phased PRs and definition of done

**PR 1 — Standalone isolation**
- Establish the destination from selected *files*, not copied Git history.
- Rename the app to a mail-only product; remove combined navigation and its
  Finance/Fleet startup, environment variables and database requirements.
- Standalone owner/admin/member identities: replace the existing directory-only
  account stub with genuine sign-in/invites before production exposure.
- Introduce separately configured mail-service database and own migrations;
  organization identifiers on all data boundaries. Never reference fleet DB.
- Preserve existing archive importer, mailbox grants, dedup, immutable source
  copies, and provider OAuth. Check import authorization and attachment retrieval.
- New repository CI checks Python, TS build, mocks, and Tauri build/check as
  supported. Both services can start with only mail-service configuration.

**PR 2 — Safe online IMAP**
- Fixed TLS verified IMAP adapters with per-organization allowlisted hosts:
  Mail.ru, Yandex, and Timeweb. Do not accept an arbitrary host from a browser.
  Corporate Timeweb-hosted domains require explicit admin verification, not a
  hard-coded customer address.
- Secure connect UI with address, designated provider, and app password (or
  provider-approved auth); send credentials only over HTTPS to the gateway.
  Never expose secrets through normal API replies, browser state persistence,
  logs, analytics or source control. Encrypt at rest, separate vault access
  from app DB, support disconnect and secret rotation.
- Default read-only `EXAMINE`/`SELECT readonly`, `BODY.PEEK[]`; never
  change provider read flags or issue destructive IMAP operations. Do not
  implement SMTP until separately authorized.
- Initial backfill (at least last 30 days) with multi-page continuation.
  Incremental IMAP sync tracks mailbox UIDVALIDITY + UID and recovers from
  UID validity changes. A burst of >100 new messages must not lose older
  unseen mail. Provider errors should be retried with bounded backoff and
  operator-visible status; ambiguous effects must not auto-resend.
- Mock IMAP integration tests and isolated wrong-credential tests.

**PR 3 — Real multi-mailbox workflow**
- Connect real provider test accounts (not business credentials in CI),
  collect messages plus attachments, preserve RFC Message-ID.
- Show cross-account duplicates once while retaining all source addresses
  and per-source originals. Maintain conservative fallback; never combine
  different known Message-IDs.
- Classify transport requests, invoices, contracts, documents, security and
  technical alerts. Routing actions remain manual until the owner authorizes
  specific rules.
- Grant/revoke per-user access without sharing passwords or exposing mail
  across organizations; test cross-org isolation and revocation.
- Optional fleet integration only through an independently authenticated,
  versioned HTTPS API/event contract. Its outage must not prevent mail startup
  or inbox browsing. Do not modify Fleet code or deployment in this migration.

**PR 4 — Production hardening and deployment**
- Resolve real authentication, migration/backup, externalized encrypted file
  storage, CI secrets, throttling, large message handling and attachment safety.
- Protect HTTPS ingress; do not make development header identity remotely
  reachable. Correct CORS, CSRF/session handling, audit and retention.
- Independently deploy to approved hosting only after security checks, provide
  Mac and iPhone clients backed by the same organization dataset.
- The independent emergency-security system integration is a future separate
  authorized interface; never expose deletion/lockout operations to this app.

## First Codex task (paste after creating/authorizing the private repo)

> Build PR 1 from this source reference into this new private repository.
> Extract only Mail Service functionality from
> `skyday85/-:codex/mail-service-extraction/ai/main-agent`.
> Implement a minimal independent mail-only backend and web/Tauri client.
> Eliminate all direct imports, startup dependencies and database access
> to Fleet, Finance and Main Agent. Preserve archive import, scoped grants,
> read-only treatment of imported sources, Gmail/Outlook OAuth, duplicate
> grouping and original attachments. Use synthetic fixtures and a clean Git
> history. First write a short dependency map, then implement the extraction,
> add executable tests and CI, run them, and create a draft PR from
> `feature/standalone-mail-extraction` into `develop`. Do not touch the
> source or Fleet repositories; do not deploy or ask for live mailbox secrets.
> Call out any existing defects discovered, including cross-org leakage,
> dropped mail above one 100-message page, unsafe automatic actions, or
> authentication gaps. Report exactly which tests you ran and failures.
