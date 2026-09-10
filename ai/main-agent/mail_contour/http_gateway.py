from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class HttpOAuthMailGateway:
    """HTTPS client for the external credential-owning mail gateway."""

    def __init__(self, base_url: str, service_token: str, timeout: float = 20.0) -> None:
        normalized = base_url.rstrip("/")
        if not normalized.startswith("https://") and not (
            normalized.startswith("http://127.0.0.1") or normalized.startswith("http://localhost")
        ):
            raise ValueError("Mail gateway must use HTTPS outside localhost")
        self.base_url = normalized
        self.service_token = service_token
        self.timeout = timeout

    def _request(self, method: str, path: str, *, user_id: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        if not user_id.strip():
            raise ValueError("user_id is required for mail gateway calls")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.service_token}",
                "X-Mail-User": user_id,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # nosec B310: URL validated in __init__
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Mail gateway HTTP {exc.code}: {raw[:500]}") from exc

    def list_accounts(self, provider: str, user_id: str) -> Iterable[Dict[str, Any]]:
        return self._request("GET", f"/v1/providers/{provider}/accounts", user_id=user_id).get("accounts", [])

    def connection_state(self, provider: str, user_id: str, account_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/providers/{provider}/accounts/{quote(account_id, safe='')}/state", user_id=user_id)

    def build_authorization_url(self, provider: str, *, user_id: str, redirect_uri: str, state: str, scopes: tuple[str, ...]) -> str:
        result = self._request("POST", f"/v1/providers/{provider}/authorize", user_id=user_id, payload={"redirect_uri": redirect_uri, "state": state, "scopes": list(scopes)})
        return str(result["authorization_url"])

    def complete_authorization(self, provider: str, *, user_id: str, code: str, redirect_uri: str, state: str, scopes: tuple[str, ...]) -> Dict[str, Any]:
        return self._request("POST", f"/v1/providers/{provider}/oauth/callback", user_id=user_id, payload={"code": code, "redirect_uri": redirect_uri, "state": state, "scopes": list(scopes)})

    def fetch_messages(self, provider: str, user_id: str, account_id: str, *, cursor: Optional[str], limit: int) -> Dict[str, Any]:
        query = urlencode({"limit": limit, **({"cursor": cursor} if cursor else {})})
        return self._request("GET", f"/v1/providers/{provider}/accounts/{quote(account_id, safe='')}/messages?{query}", user_id=user_id)

    def fetch_attachment(self, provider: str, user_id: str, account_id: str, provider_message_id: str, attachment_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/providers/{provider}/accounts/{quote(account_id, safe='')}/messages/{quote(provider_message_id, safe='')}/attachments/{quote(attachment_id, safe='')}", user_id=user_id)
