from __future__ import annotations

import base64
import os
import time
from dataclasses import replace
from email.utils import getaddresses
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from .token_store import EncryptedFileTokenStore, OAuthTokenRecord


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
MICROSOFT_AUTH_BASE = "https://login.microsoftonline.com"
GRAPH_API = "https://graph.microsoft.com/v1.0"


def _b64url_decode(value: str) -> str:
    if not value:
        return ""
    value += "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8", errors="replace")


def _addresses(raw: str) -> list[str]:
    return [address for _, address in getaddresses([raw]) if address]


class OAuthProviderClient:
    provider: str

    def __init__(self, store: EncryptedFileTokenStore) -> None:
        self.store = store
        self.http = httpx.Client(timeout=30.0)

    def list_accounts(self) -> list[dict[str, Any]]:
        return [
            {
                "account_id": item.account_id,
                "address": item.address,
                "display_name": item.display_name,
            }
            for item in self.store.list_provider(self.provider)
        ]

    def connection_state(self, account_id: str) -> dict[str, Any]:
        item = self.store.get(self.provider, account_id)
        return {
            "connected": True,
            "scopes": list(item.scopes),
            "reauth_required": not bool(item.refresh_token),
        }

    def authorization_url(self, *, redirect_uri: str, state: str, scopes: tuple[str, ...]) -> str:
        raise NotImplementedError

    def complete_authorization(self, *, code: str, redirect_uri: str, scopes: tuple[str, ...]) -> dict[str, Any]:
        raise NotImplementedError

    def fetch_messages(self, account_id: str, *, cursor: Optional[str], limit: int) -> dict[str, Any]:
        raise NotImplementedError

    def fetch_attachment(self, account_id: str, provider_message_id: str, attachment_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def _valid_access_token(self, account_id: str) -> str:
        record = self.store.get(self.provider, account_id)
        if record.expires_at and record.expires_at > int(time.time()) + 60:
            return record.access_token
        refreshed = self.refresh(record)
        self.store.upsert(refreshed)
        return refreshed.access_token

    def refresh(self, record: OAuthTokenRecord) -> OAuthTokenRecord:
        raise NotImplementedError


class GmailClient(OAuthProviderClient):
    provider = "gmail"

    @property
    def client_id(self) -> str:
        return os.environ["GOOGLE_OAUTH_CLIENT_ID"]

    @property
    def client_secret(self) -> str:
        return os.environ["GOOGLE_OAUTH_CLIENT_SECRET"]

    def authorization_url(self, *, redirect_uri: str, state: str, scopes: tuple[str, ...]) -> str:
        return GOOGLE_AUTH_URL + "?" + urlencode({
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        })

    def complete_authorization(self, *, code: str, redirect_uri: str, scopes: tuple[str, ...]) -> dict[str, Any]:
        response = self.http.post(GOOGLE_TOKEN_URL, data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        })
        response.raise_for_status()
        token = response.json()
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        profile = self.http.get(f"{GMAIL_API}/users/me/profile", headers=headers)
        profile.raise_for_status()
        address = profile.json()["emailAddress"]
        record = OAuthTokenRecord(
            provider=self.provider,
            account_id=address.lower(),
            address=address,
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token"),
            expires_at=int(time.time()) + int(token.get("expires_in", 3600)),
            scopes=tuple(token.get("scope", " ".join(scopes)).split()),
            display_name=address,
        )
        self.store.upsert(record)
        return {"account_id": record.account_id, "address": record.address, "display_name": record.display_name}

    def refresh(self, record: OAuthTokenRecord) -> OAuthTokenRecord:
        if not record.refresh_token:
            raise RuntimeError("Gmail reauthorization required")
        response = self.http.post(GOOGLE_TOKEN_URL, data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": record.refresh_token,
            "grant_type": "refresh_token",
        })
        response.raise_for_status()
        token = response.json()
        return replace(
            record,
            access_token=token["access_token"],
            expires_at=int(time.time()) + int(token.get("expires_in", 3600)),
            scopes=tuple(token.get("scope", " ".join(record.scopes)).split()),
        )

    def _walk_parts(self, payload: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
        text, html = "", ""
        attachments: list[dict[str, Any]] = []
        stack = [payload]
        while stack:
            part = stack.pop()
            body = part.get("body") or {}
            mime = part.get("mimeType", "")
            filename = part.get("filename", "")
            if filename and body.get("attachmentId"):
                attachments.append({
                    "attachment_id": body["attachmentId"],
                    "filename": filename,
                    "mime_type": mime,
                    "size_bytes": body.get("size"),
                })
            elif body.get("data"):
                decoded = _b64url_decode(body["data"])
                if mime == "text/plain" and not text:
                    text = decoded
                elif mime == "text/html" and not html:
                    html = decoded
            stack.extend(reversed(part.get("parts") or []))
        return text, html, attachments

    def fetch_messages(self, account_id: str, *, cursor: Optional[str], limit: int) -> dict[str, Any]:
        token = self._valid_access_token(account_id)
        headers = {"Authorization": f"Bearer {token}"}
        params: dict[str, Any] = {"maxResults": min(limit, 100), "labelIds": "INBOX"}
        if cursor:
            params["pageToken"] = cursor
        page = self.http.get(f"{GMAIL_API}/users/me/messages", headers=headers, params=params)
        page.raise_for_status()
        messages = []
        for ref in page.json().get("messages", []):
            item = self.http.get(
                f"{GMAIL_API}/users/me/messages/{ref['id']}",
                headers=headers,
                params={"format": "full"},
            )
            item.raise_for_status()
            raw = item.json()
            payload = raw.get("payload") or {}
            header_map = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
            text, html, attachments = self._walk_parts(payload)
            messages.append({
                "provider_message_id": raw["id"],
                "thread_id": raw.get("threadId"),
                "sender": (_addresses(header_map.get("from", "")) or [header_map.get("from", "")])[0],
                "recipients": _addresses(header_map.get("to", "")),
                "subject": header_map.get("subject", ""),
                "received_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(raw.get("internalDate", "0")) / 1000)),
                "body_text": text or raw.get("snippet", ""),
                "body_html": html or None,
                "attachments": attachments,
                "labels": raw.get("labelIds", []),
                "unread": "UNREAD" in raw.get("labelIds", []),
                "direction": "incoming",
            })
        return {"messages": messages, "next_cursor": page.json().get("nextPageToken")}

    def fetch_attachment(self, account_id: str, provider_message_id: str, attachment_id: str) -> dict[str, Any]:
        token = self._valid_access_token(account_id)
        response = self.http.get(
            f"{GMAIL_API}/users/me/messages/{provider_message_id}/attachments/{attachment_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return {"attachment_id": attachment_id, "content_base64url": response.json().get("data", "")}


class OutlookClient(OAuthProviderClient):
    provider = "outlook"

    @property
    def tenant(self) -> str:
        return os.getenv("MICROSOFT_OAUTH_TENANT", "common")

    @property
    def client_id(self) -> str:
        return os.environ["MICROSOFT_OAUTH_CLIENT_ID"]

    @property
    def client_secret(self) -> str:
        return os.environ["MICROSOFT_OAUTH_CLIENT_SECRET"]

    @property
    def auth_url(self) -> str:
        return f"{MICROSOFT_AUTH_BASE}/{self.tenant}/oauth2/v2.0/authorize"

    @property
    def token_url(self) -> str:
        return f"{MICROSOFT_AUTH_BASE}/{self.tenant}/oauth2/v2.0/token"

    def authorization_url(self, *, redirect_uri: str, state: str, scopes: tuple[str, ...]) -> str:
        return self.auth_url + "?" + urlencode({
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": " ".join(scopes),
            "state": state,
        })

    def complete_authorization(self, *, code: str, redirect_uri: str, scopes: tuple[str, ...]) -> dict[str, Any]:
        response = self.http.post(self.token_url, data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "scope": " ".join(scopes),
        })
        response.raise_for_status()
        token = response.json()
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        profile = self.http.get(f"{GRAPH_API}/me", headers=headers, params={"$select": "id,displayName,mail,userPrincipalName"})
        profile.raise_for_status()
        me = profile.json()
        address = me.get("mail") or me.get("userPrincipalName")
        record = OAuthTokenRecord(
            provider=self.provider,
            account_id=str(me["id"]),
            address=str(address),
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token"),
            expires_at=int(time.time()) + int(token.get("expires_in", 3600)),
            scopes=tuple(token.get("scope", " ".join(scopes)).split()),
            display_name=me.get("displayName"),
        )
        self.store.upsert(record)
        return {"account_id": record.account_id, "address": record.address, "display_name": record.display_name}

    def refresh(self, record: OAuthTokenRecord) -> OAuthTokenRecord:
        if not record.refresh_token:
            raise RuntimeError("Outlook reauthorization required")
        response = self.http.post(self.token_url, data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": record.refresh_token,
            "grant_type": "refresh_token",
            "scope": " ".join(record.scopes),
        })
        response.raise_for_status()
        token = response.json()
        return replace(
            record,
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token") or record.refresh_token,
            expires_at=int(time.time()) + int(token.get("expires_in", 3600)),
            scopes=tuple(token.get("scope", " ".join(record.scopes)).split()),
        )

    def fetch_messages(self, account_id: str, *, cursor: Optional[str], limit: int) -> dict[str, Any]:
        token = self._valid_access_token(account_id)
        headers = {"Authorization": f"Bearer {token}"}
        url = cursor or f"{GRAPH_API}/me/mailFolders/inbox/messages"
        params = None if cursor else {
            "$top": min(limit, 100),
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,subject,from,toRecipients,receivedDateTime,body,bodyPreview,isRead,hasAttachments",
        }
        page = self.http.get(url, headers=headers, params=params)
        page.raise_for_status()
        messages = []
        for raw in page.json().get("value", []):
            attachments = []
            if raw.get("hasAttachments"):
                att = self.http.get(
                    f"{GRAPH_API}/me/messages/{raw['id']}/attachments",
                    headers=headers,
                    params={"$select": "id,name,contentType,size,isInline"},
                )
                att.raise_for_status()
                attachments = [
                    {
                        "attachment_id": x["id"],
                        "filename": x.get("name", "attachment"),
                        "mime_type": x.get("contentType", "application/octet-stream"),
                        "size_bytes": x.get("size"),
                    }
                    for x in att.json().get("value", [])
                    if not x.get("isInline")
                ]
            sender = ((raw.get("from") or {}).get("emailAddress") or {}).get("address", "")
            recipients = [
                (x.get("emailAddress") or {}).get("address", "")
                for x in raw.get("toRecipients", [])
                if (x.get("emailAddress") or {}).get("address")
            ]
            body = raw.get("body") or {}
            body_html = body.get("content") if body.get("contentType") == "html" else None
            body_text = body.get("content") if body.get("contentType") == "text" else raw.get("bodyPreview", "")
            messages.append({
                "provider_message_id": raw["id"],
                "thread_id": raw.get("conversationId"),
                "sender": sender,
                "recipients": recipients,
                "subject": raw.get("subject", ""),
                "received_at": raw.get("receivedDateTime"),
                "body_text": body_text,
                "body_html": body_html,
                "attachments": attachments,
                "labels": ["INBOX"],
                "unread": not bool(raw.get("isRead", False)),
                "direction": "incoming",
            })
        return {"messages": messages, "next_cursor": page.json().get("@odata.nextLink")}

    def fetch_attachment(self, account_id: str, provider_message_id: str, attachment_id: str) -> dict[str, Any]:
        token = self._valid_access_token(account_id)
        response = self.http.get(
            f"{GRAPH_API}/me/messages/{provider_message_id}/attachments/{attachment_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        raw = response.json()
        return {
            "attachment_id": attachment_id,
            "filename": raw.get("name"),
            "mime_type": raw.get("contentType"),
            "content_base64": raw.get("contentBytes"),
        }
