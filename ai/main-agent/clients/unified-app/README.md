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
