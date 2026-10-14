from __future__ import annotations

import json
from typing import Any, Dict
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class HttpIntegrationDispatcher:
    """Secure service-to-service dispatcher for messenger/CRM integration gateways.

    The Main Agent sends a neutral business event. The external integration
    gateway decides whether it goes to Telegram, WhatsApp, a corporate chat,
    CRM or another application and which user/channel receives it.
    """

    def __init__(self, base_url: str, service_token: str, timeout: float = 15.0) -> None:
        base_url = base_url.rstrip("/")
        if not base_url.startswith("https://") and not (
            base_url.startswith("http://localhost") or base_url.startswith("http://127.0.0.1")
        ):
            raise ValueError("Integration gateway must use HTTPS outside localhost")
        if not service_token:
            raise ValueError("Integration gateway service token is required")
        self.base_url = base_url
        self.service_token = service_token
        self.timeout = timeout

    def dispatch(self, event: Dict[str, Any]) -> Dict[str, Any]:
        payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.base_url}/v1/events",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.service_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Idempotency-Key": str(event["event_id"]),
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # nosec B310: base URL validated above
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {"accepted": True}
        except HTTPError as exc:
            raise RuntimeError(f"Integration gateway HTTP {exc.code}") from exc
