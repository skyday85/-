# Unified Main Agent App

Одна клиентская кодовая база для macOS и iPhone. Интерфейс написан на React/Vite и упаковывается Tauri 2 для macOS и iOS.

## Что уже есть

- единая навигация по модулям;
- центральный экран Главного агента;
- единая почтовая лента;
- подключение Gmail/Outlook через backend OAuth flow;
- адаптивный интерфейс для Mac и iPhone;
- единый HTTPS backend-контракт;
- минимальные Tauri permissions без доступа клиента к базе данных или почтовым токенам.

## Запуск локально

```bash
npm install
npm run tauri dev
```

Для iOS требуется macOS + Xcode и настройка iOS target через Tauri CLI.

```bash
npm run tauri ios init
npm run tauri ios dev
```

## Backend

Клиент не обращается напрямую к Gmail, Outlook, Finance DB или Fleet DB. Все вызовы идут через общий backend API. В production `VITE_API_BASE_URL` должен быть HTTPS.

Ожидаемые endpoints:

- `GET /client/bootstrap?platform=mac|iphone`
- `GET /mail/inbox`
- `POST /mail/accounts/gmail/authorize`
- `POST /mail/accounts/outlook/authorize`

## Безопасность

- OAuth refresh tokens и client secrets остаются в серверном integration layer;
- desktop/mobile client не получает DB credentials;
- Tauri capability начинается с `core:default` и расширяется только точечно;
- plain HTTP допускается только для локального `127.0.0.1` development server;
- production API — только HTTPS/TLS.

## Следующее

1. HTTP API adapter поверх `UnifiedClientApi`.
2. Реальная сессия пользователя и secure cookie/token handoff.
3. APNs push registration и backend notification delivery.
4. Рабочие экраны Finance/Fleet/Sales/Marketing/Procurement.
5. Подписание macOS/iOS приложений и TestFlight/App Store pipeline.

## Users and connected mailboxes

An organization administrator can open **Управление почтой** in the app,
create a user with the external authentication provider's verified user ID,
assign specific Gmail/Outlook mailboxes and grant forwarding approval separately.
Creating a user here does not set a password or enroll them in the authentication
provider: the identity administrator must provision sign-in separately.

A connected mailbox belongs to its original OAuth account owner; users receive
scoped read grants rather than copied tokens. Multiple users can have access
to one mailbox, and one user can see several assigned mailboxes in one inbox.
Revoked/disabled accounts lose access to their mail views and forwarding queue.

## Content recognition and forwarding

Administrators configure per-mailbox phrases, destination email, whether to
inspect attachments, and whether matching mail requires review or is forwarded
automatically. The default is review. Image/PDF OCR is optional on the server.
Users with approval permission can preview the source and download original
attachments before making a forwarding decision. Gmail forwards the intact
source message as .eml; Outlook uses its provider-native forward operation.

## Duplicate mail and assigned accounts

The unified inbox displays one logical message when the same original email
reaches several mailboxes assigned to the current user. The message shows a
source count and a tooltip listing ONLY that user's assigned receiving
addresses. Staff can filter by a specific assigned source or select all.
Deactivated/revoked user-mailbox assignments disappear immediately.

Duplicate detection first uses the original RFC Internet Message-ID extracted
by Gmail and Outlook. If an account does not expose this header, the collector
only falls back when sender, subject, substantial full plaintext, attachment
metadata, and arrival time match conservatively across different accounts.
Distinct RFC Message-IDs always remain separate, even if letter templates
are identical. Ambiguous matches remain separate rather than losing mail.
Unread state is aggregated across the visible source copies.

No original provider email is deleted or moved. Each source copy retains its
original account, provider message ID, attachments, read state and history.
This preserves provider synchronization, authorizations and operational audit.

Administrator provisioning sequence:
1. Provision the user's verified subject in the trusted identity provider.
2. Create the matching user record under **Управление почтой**.
3. An administrator connects each Gmail/Outlook mailbox through the OAuth
   flow while working in the appropriate organization.
4. Assign that organization's registered mailboxes to the chosen staff and
   optionally grant permission to approve forwarding.
5. Revocation is immediate for shared inbox visibility; originals stay
   in their provider accounts and cannot be accessed via another source ID.
