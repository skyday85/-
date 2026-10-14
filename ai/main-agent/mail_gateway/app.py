from __future__ import annotations

import hmac
import os
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .providers import GmailClient, OutlookClient
from .token_store import EncryptedFileTokenStore


class AuthorizePayload(BaseModel):
    redirect_uri: str
    state: str = Field(min_length=16, max_length=512)
    scopes: list[str]


class CallbackPayload(AuthorizePayload):
    code: str = Field(min_length=1)


def _require_https_or_local(url: str) -> None:
    if url.startswith("https://") or url.startswith("http://localhost") or url.startswith("http://127.0.0.1"):
        return
    raise HTTPException(status_code=400, detail="redirect_uri must use HTTPS outside localhost")


def _service_auth(authorization: Optional[str] = Header(default=None)) -> None:
    expected = os.environ.get("MAIL_GATEWAY_SERVICE_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Gateway service token is not configured")
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid service token")


def _mail_user(x_mail_user: Optional[str] = Header(default=None, alias="X-Mail-User")) -> str:
    user_id = (x_mail_user or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="X-Mail-User is required")
    return user_id


store = EncryptedFileTokenStore()
providers = {"gmail": GmailClient(store), "outlook": OutlookClient(store)}
app = FastAPI(title="Organization Mail Gateway", version="0.2.0", docs_url=None if os.getenv("APP_ENV") == "production" else "/docs", redoc_url=None)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "providers": sorted(providers)}


def _provider(name: Literal["gmail", "outlook"]):
    return providers[name]


@app.get("/v1/providers/{provider}/accounts", dependencies=[Depends(_service_auth)])
def list_accounts(provider: Literal["gmail", "outlook"], user_id: str = Depends(_mail_user)):
    return {"accounts": _provider(provider).list_accounts(user_id)}


@app.get("/v1/providers/{provider}/accounts/{account_id}/state", dependencies=[Depends(_service_auth)])
def account_state(provider: Literal["gmail", "outlook"], account_id: str, user_id: str = Depends(_mail_user)):
    try:
        return _provider(provider).connection_state(user_id, account_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Mail account not found") from exc


@app.post("/v1/providers/{provider}/authorize", dependencies=[Depends(_service_auth)])
def authorize(provider: Literal["gmail", "outlook"], payload: AuthorizePayload, user_id: str = Depends(_mail_user)):
    _require_https_or_local(payload.redirect_uri)
    return {"authorization_url": _provider(provider).authorization_url(redirect_uri=payload.redirect_uri, state=payload.state, scopes=tuple(payload.scopes))}


@app.post("/v1/providers/{provider}/oauth/callback", dependencies=[Depends(_service_auth)])
def oauth_callback(provider: Literal["gmail", "outlook"], payload: CallbackPayload, user_id: str = Depends(_mail_user)):
    _require_https_or_local(payload.redirect_uri)
    return _provider(provider).complete_authorization(user_id=user_id, code=payload.code, redirect_uri=payload.redirect_uri, scopes=tuple(payload.scopes))


@app.get("/v1/providers/{provider}/accounts/{account_id}/messages", dependencies=[Depends(_service_auth)])
def messages(provider: Literal["gmail", "outlook"], account_id: str, cursor: Optional[str] = None, limit: int = 100, user_id: str = Depends(_mail_user)):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
    try:
        return _provider(provider).fetch_messages(user_id, account_id, cursor=cursor, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Mail account not found") from exc


@app.get("/v1/providers/{provider}/accounts/{account_id}/messages/{provider_message_id}/attachments/{attachment_id}", dependencies=[Depends(_service_auth)])
def attachment(provider: Literal["gmail", "outlook"], account_id: str, provider_message_id: str, attachment_id: str, user_id: str = Depends(_mail_user)):
    try:
        return _provider(provider).fetch_attachment(user_id, account_id, provider_message_id, attachment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Mail account not found") from exc
