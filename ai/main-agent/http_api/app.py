from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app_shell.client_api import ClientContext
from mail_contour.http_gateway import HttpOAuthMailGateway
from mail_contour.provider_adapters import GmailProviderAdapter, OutlookProviderAdapter
from runtime import build_runtime


class AuthorizeRequest(BaseModel):
    return_to: str = "/mail"


class AgentCommandRequest(BaseModel):
    text: str


class BankTransactionPayload(BaseModel):
    transaction_id: str = Field(min_length=1)
    date: str = Field(min_length=1)
    amount: str = Field(min_length=1)
    direction: Literal["income", "expense"]
    counterparty_name: str = ""
    purpose: str = ""
    bank_reference: Optional[str] = None


class BankImportRequest(BaseModel):
    transactions: list[BankTransactionPayload]


class ConfirmClassificationRequest(BaseModel):
    operation_type: Optional[str] = None
    category: Optional[str] = None
    rationale: Optional[str] = None


class FleetDocumentAssignmentRequest(BaseModel):
    vehicle_id: Optional[str] = None
    purchase_id: Optional[str] = None
    repair_id: Optional[str] = None


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class SignedOAuthState:
    MAX_AGE_SECONDS = 15 * 60

    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise RuntimeError("APP_OAUTH_STATE_SECRET must contain at least 32 characters")
        self.secret = secret.encode("utf-8")

    def issue(self, provider: str, user_id: str, return_to: str) -> str:
        payload = {"provider": provider, "user_id": user_id, "return_to": return_to if return_to.startswith("/") else "/mail", "iat": int(time.time()), "nonce": secrets.token_urlsafe(16)}
        encoded = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = _b64encode(hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def consume(self, state: str, provider: str) -> tuple[str, str]:
        try:
            encoded, signature = state.split(".", 1)
            expected = _b64encode(hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                raise ValueError("signature")
            payload = json.loads(_b64decode(encoded).decode("utf-8"))
            age = int(time.time()) - int(payload["iat"])
            if age < 0 or age > self.MAX_AGE_SECONDS or payload.get("provider") != provider:
                raise ValueError("invalid")
            user_id = str(payload.get("user_id") or "").strip()
            if not user_id:
                raise ValueError("user")
            return_to = str(payload.get("return_to") or "/mail")
            return user_id, return_to if return_to.startswith("/") else "/mail"
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid or expired OAuth state") from exc


def _is_local_origin(origin: str) -> bool:
    return origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost")


def _configure_integrations(runtime) -> None:
    base_url = os.getenv("MAIL_GATEWAY_BASE_URL", "").strip()
    token = os.getenv("MAIL_GATEWAY_SERVICE_TOKEN", "").strip()
    if base_url and token:
        runtime.register_standard_mail_providers(HttpOAuthMailGateway(base_url, token))


def _oauth_state_secret() -> str:
    configured = os.getenv("APP_OAUTH_STATE_SECRET", "").strip()
    if configured:
        return configured
    if os.getenv("APP_ENV", "development") == "production":
        raise RuntimeError("APP_OAUTH_STATE_SECRET is required in production")
    return secrets.token_urlsafe(48)


runtime = build_runtime()
_configure_integrations(runtime)
oauth_states = SignedOAuthState(_oauth_state_secret())
app = FastAPI(title="Main Agent Unified API", version="0.3.0")

allowed_origins = [x.strip() for x in os.getenv("APP_ALLOWED_ORIGINS", "").split(",") if x.strip()]
if os.getenv("APP_ENV", "development") == "development":
    allowed_origins.extend(["http://localhost:1420", "http://127.0.0.1:1420"])
app.add_middleware(CORSMiddleware, allow_origins=sorted(set(allowed_origins)), allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Authenticated-User", "X-Device-Id", "X-App-Version"])


def authenticated_user(request: Request) -> str:
    env = os.getenv("APP_ENV", "development")
    user = request.headers.get("X-Authenticated-User", "").strip()
    if user:
        return user
    if env == "development" and (request.client.host if request.client else "") in {"127.0.0.1", "::1", "testclient"}:
        return "local-development-user"
    raise HTTPException(status_code=401, detail="Authenticated user required")


def public_api_base(request: Request) -> str:
    configured = os.getenv("PUBLIC_API_BASE_URL", "").rstrip("/")
    base = configured or str(request.base_url).rstrip("/")
    if not base.startswith("https://") and not _is_local_origin(base):
        raise HTTPException(status_code=500, detail="PUBLIC_API_BASE_URL must use HTTPS")
    return base


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mail_providers": runtime.mail_providers.list_providers()}


@app.get("/client/bootstrap")
def bootstrap(request: Request, platform: Literal["mac", "iphone"], user_id: str = Depends(authenticated_user)) -> dict:
    return runtime.client_api.bootstrap(ClientContext(user_id=user_id, device_id=request.headers.get("X-Device-Id", "unknown-device"), platform=platform, app_version=request.headers.get("X-App-Version", "development")))


@app.get("/finance/transactions")
def finance_transactions(_user: str = Depends(authenticated_user)):
    return runtime.list_bank_transactions()


@app.get("/finance/review")
def finance_review(_user: str = Depends(authenticated_user)):
    return runtime.finance_review_queue()


@app.post("/finance/import")
def finance_import(payload: BankImportRequest, _user: str = Depends(authenticated_user)):
    return {"imported": runtime.import_bank_transactions([x.model_dump() for x in payload.transactions])}


@app.post("/finance/transactions/{transaction_id}/classify")
def finance_classify(transaction_id: str, _user: str = Depends(authenticated_user)):
    try:
        return runtime.propose_bank_classification(transaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Bank transaction not found") from exc


@app.post("/finance/transactions/{transaction_id}/confirm")
def finance_confirm(transaction_id: str, payload: ConfirmClassificationRequest, _user: str = Depends(authenticated_user)):
    try:
        return runtime.confirm_bank_classification(transaction_id, operation_type=payload.operation_type, category=payload.category, rationale=payload.rationale)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Bank transaction not found") from exc


@app.get("/mail/inbox")
def inbox(account_id: list[str] = Query(default=[]), unread_only: bool = False, classification: Optional[str] = None, routed_to: Optional[str] = None, search: Optional[str] = None, smart_folder: Optional[str] = None, user_id: str = Depends(authenticated_user)):
    return runtime.client_api.get_mailbox(user_id, account_ids=account_id, unread_only=unread_only, classification=classification, routed_to=routed_to, search=search, smart_folder=smart_folder)


@app.get("/mail/messages/{email_id}")
def mail_message(email_id: str, user_id: str = Depends(authenticated_user)):
    try:
        return runtime.client_api.get_mail_message(user_id, email_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Mail message not found") from exc


@app.post("/mail/messages/{email_id}/process")
def process_mail(email_id: str, user_id: str = Depends(authenticated_user)):
    try:
        return runtime.client_api.process_mail_message(user_id, email_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Mail message not found") from exc


@app.post("/mail/sync")
def sync_mail(user_id: str = Depends(authenticated_user)):
    return runtime.client_api.refresh_mail(user_id)


@app.get("/mail/integration-events")
def mail_integration_events(user_id: str = Depends(authenticated_user)):
    return runtime.client_api.get_integration_events(user_id)


@app.get("/fleet/document-candidates")
def fleet_document_candidates(user_id: str = Depends(authenticated_user)):
    return runtime.client_api.get_fleet_document_candidates(user_id)


@app.post("/fleet/document-candidates/{candidate_id}/assign")
def assign_fleet_document(candidate_id: str, payload: FleetDocumentAssignmentRequest, user_id: str = Depends(authenticated_user)):
    try:
        result = runtime.fleet_document_queue.assign(user_id, candidate_id, vehicle_id=payload.vehicle_id, purchase_id=payload.purchase_id, repair_id=payload.repair_id)
        runtime.integration_outbox.publish(user_id=user_id, event_type="fleet_document_ready", source="mail_document_queue", source_id=candidate_id, title=result["filename"], payload=result, destinations=("fleet",), priority="high")
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Document candidate not found") from exc


@app.post("/fleet/document-candidates/{candidate_id}/dismiss")
def dismiss_fleet_document(candidate_id: str, user_id: str = Depends(authenticated_user)):
    try:
        return runtime.fleet_document_queue.dismiss(user_id, candidate_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Document candidate not found") from exc


@app.post("/mail/accounts/{provider}/authorize")
def begin_authorization(provider: Literal["gmail", "outlook"], payload: AuthorizeRequest, request: Request, user_id: str = Depends(authenticated_user)):
    if provider not in runtime.mail_providers.list_providers():
        raise HTTPException(status_code=503, detail="Mail gateway is not configured")
    state = oauth_states.issue(provider, user_id, payload.return_to)
    redirect_uri = f"{public_api_base(request)}/mail/oauth/{provider}/callback"
    return {"authorization_url": runtime.begin_mail_authorization(user_id=user_id, provider=provider, redirect_uri=redirect_uri, state=state)}


@app.get("/mail/oauth/{provider}/callback")
def oauth_callback(provider: Literal["gmail", "outlook"], request: Request, state: str, code: Optional[str] = None, error: Optional[str] = None):
    user_id, return_to = oauth_states.consume(state, provider)
    client_base = os.getenv("PUBLIC_CLIENT_BASE_URL", "http://localhost:1420").rstrip("/")
    if not client_base.startswith("https://") and not _is_local_origin(client_base):
        raise HTTPException(status_code=500, detail="PUBLIC_CLIENT_BASE_URL must use HTTPS")
    if error:
        return RedirectResponse(f"{client_base}{return_to}?mail_error={provider}")
    if not code:
        raise HTTPException(status_code=400, detail="OAuth code is missing")
    redirect_uri = f"{public_api_base(request)}/mail/oauth/{provider}/callback"
    runtime.complete_mail_authorization(user_id=user_id, provider=provider, code=code, redirect_uri=redirect_uri, state=state)
    return RedirectResponse(f"{client_base}{return_to}?mail_connected={provider}")


@app.post("/agent/commands")
def agent_command(payload: AgentCommandRequest, _user: str = Depends(authenticated_user)):
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Command text is required")
    return runtime.agent.handle(text)
