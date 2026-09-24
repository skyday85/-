# Unified Application Shell

## Goal

The organization product is one application with one navigation model and one backend contract.
It must run as a desktop application on macOS and as a mobile application on iPhone without duplicating business logic.

## Product surface

Primary modules:

- Главный агент
- Почта
- Финансы
- Автопарк
- Продажи
- Маркетинг
- Закупки
- Задачи
- Уведомления

The same authenticated user works with the same organization data on Mac and iPhone.
Device clients adapt layout and interaction patterns only; business rules remain in backend services and specialized agents.

## Client strategy

The shell contract is intentionally framework-neutral at this stage. The production client should use a shared cross-platform codebase where practical, while retaining native capabilities for:

- macOS desktop windowing, menu bar and local notifications;
- iPhone push notifications, camera/file capture, share sheet and biometric unlock;
- secure token storage in platform keychain;
- deep links to mail threads, tasks, vehicles, deals and approval screens.

A browser version may reuse the same backend and route contracts, but desktop/mobile are first-class clients rather than wrappers around Outlook or other third-party applications.

## Mail as one window

All connected mail accounts are normalized into one unified inbox. Each message retains:

- provider;
- source account;
- provider message id;
- thread id;
- attachment references;
- original source ownership.

The user can filter by account/provider, but the default workspace is the consolidated inbox.
The Mail Collector analyzes the consolidated stream and delegates structured results through the Main Agent.

## Security

- Never store primary mailbox passwords in the Main Agent or client source code.
- Prefer OAuth for Gmail/Google Workspace and Microsoft 365/Outlook.
- Provider tokens belong to a protected integration/secret layer.
- Clients receive only scoped session credentials.
- Production external traffic is HTTPS/TLS only.
- Destructive Security Control functions remain outside the unified application and outside Main Agent permissions.

## Backend rule

The unified application is not a monolithic database. Each business module keeps ownership of its data. The client shell and Main Agent coordinate through versioned APIs/contracts and cross-domain identifiers.
