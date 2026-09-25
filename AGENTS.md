# Codex instructions: independent Mail Service extraction

This branch is a **transition reference**, not the new Mail Service repository.
The real product must live in a separate **private** repository, preferably
`skyday85/mail-service`, with its own `main`, `develop`, feature branches,
CI, database, configuration, secrets, and deployment. Do not merge this
extraction branch into the source repository's `main` as a substitute.

## Scope and ownership

- Source: `skyday85/-`, branch `codex/mail-service-extraction`,
  path `ai/main-agent/`. It includes the work from stacked draft PRs #1-#4.
- Destination: a user-created private repository. **Never** assume that
  `skyday85/fleet-management` is the destination. Do not edit its branches,
  history, database, migrations, or production deployment.
- Mail Service is an independent program, not a feature branch of Fleet.
  Integration with Fleet and a future Main Agent is ONLY via versioned,
  authenticated, optional HTTPS APIs/events. No cross-repository relative
  imports or direct foreign-database queries.
- Never copy provider passwords, OAuth tokens, real mail messages or attached
  documents into Git, issues, test fixtures, PR bodies, CI logs, or agent prompts.
  The source repository is public; use synthetic addresses in code and docs.
  Start the new private repo with a **clean history**, not a mirror of the
  combined application history.

## Extraction

Read `MAIL_SERVICE_CODEX_HANDOFF.md` before changing code.
Move mail-specific code and tests only from `ai/main-agent/mail_contour`,
`mail_gateway`, `http_api`, `clients/unified-app`, and the minimal
mail-only supporting abstractions. Resolve imports so startup, sync, and tests
never require Fleet, Finance, or the combined Main Agent runtime.

Work iteratively via PRs against destination `develop` and leave
destination `main` stable. First establish a tested standalone extraction,
then implement read-only IMAP connectors (Mail.ru, Yandex, Timeweb), then
production security, deployment, and real mailbox acceptance checks.

## Non-negotiable acceptance

- Gmail/Outlook OAuth and read-only IMAP connections in a gateway-only secrets
  boundary; secure UI input rather than chat-based collection.
- First run can backfill at least 30 days of mail, including >100 new messages
  between syncs; use provider-appropriate incremental markers (IMAP UIDVALIDITY
  + UID checkpoints, Gmail history and Microsoft delta or equivalent verified
  pagination) to avoid gaps.
- One logical message across mailboxes when safe to deduplicate, with original
  source copies and attachments preserved and no duplicate outbound side effects.
- Strong per-organization, per-user authorization checked at data access,
  retrieval, and attachment endpoints. No trusted client-supplied identity
  headers in production without an authenticating gateway.
- In initial IMAP mode: no deletion, moving, flag changes, SMTP, or automatic
  forwarding. Imported archives are permanently read-only.
- Verified secret-at-rest encryption, HTTPS only outside localhost,
  credential rotation/revocation and operational audit.
- CI must run Python tests, frontend build and applicable macOS/Tauri checks.
  Demonstrate runtime startup and E2E mock-account ingestion, not just
  presence of UI screens.

See the companion handoff document for concrete tasks and verification.
