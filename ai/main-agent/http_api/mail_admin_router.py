from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from mail_contour.mail_access import AccessDenied


class NewUser(BaseModel):
    user_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    email: str = Field(min_length=3)
    role: Literal["member", "admin"] = "member"


class ChangeStatus(BaseModel):
    active: bool


class AccountGrant(BaseModel):
    owner_user_id: str = Field(min_length=1)
    provider: Literal["gmail", "outlook"]
    account_id: str = Field(min_length=1)
    recipient_user_id: str = Field(min_length=1)
    can_forward: bool = False


class RoutingRule(BaseModel):
    owner_user_id: str = Field(min_length=1)
    provider: Literal["gmail", "outlook"]
    account_id: str = Field(min_length=1)
    match_text: str = Field(min_length=1)
    destination: str = Field(min_length=3)
    scan_attachments: bool = False
    mode: Literal["review", "auto"] = "review"


def build_mail_admin_router(runtime, authenticated_user, authenticated_organization) -> APIRouter:
    router = APIRouter(prefix="/mail")

    @router.get("/admin/users")
    def users(actor: str = Depends(authenticated_user), org: str = Depends(authenticated_organization)):
        return {"items": runtime.mail_directory.users(org, actor)}

    @router.post("/admin/users")
    def create_user(payload: NewUser, actor: str = Depends(authenticated_user),
                    org: str = Depends(authenticated_organization)):
        try:
            return runtime.mail_directory.create_user(org, actor, **payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/admin/users/{target_user_id}/status")
    def set_user_status(target_user_id: str, payload: ChangeStatus,
                        actor: str = Depends(authenticated_user), org: str = Depends(authenticated_organization)):
        try:
            return runtime.mail_directory.set_active(org, actor, target_user_id, payload.active)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="User not found") from exc

    @router.get("/admin/connected-accounts")
    def connected_accounts(owner_user_id: str, actor: str = Depends(authenticated_user),
                           org: str = Depends(authenticated_organization)):
        runtime.mail_directory.require_admin(org, actor)
        runtime.mail_directory.require_member(org, owner_user_id)
        return {"items": runtime.refresh_mail_accounts(owner_user_id)}

    @router.get("/admin/grants")
    def all_grants(actor: str = Depends(authenticated_user), org: str = Depends(authenticated_organization)):
        return {"items": runtime.mail_directory.all_grants(org, actor)}

    @router.post("/admin/grants")
    def grant_account(payload: AccountGrant, actor: str = Depends(authenticated_user),
                      org: str = Depends(authenticated_organization)):
        runtime.mail_directory.require_admin(org, actor)
        runtime.mail_directory.require_member(org, payload.owner_user_id)
        connected = runtime.refresh_mail_accounts(payload.owner_user_id)
        matching = [account for account in connected if
                    account["account_id"] == payload.account_id and account["provider"] == payload.provider]
        if not matching:
            raise HTTPException(status_code=404, detail="Connected account not found")
        try:
            return runtime.mail_directory.grant_account(
                org, actor, owner_user_id=payload.owner_user_id, provider=payload.provider,
                account_id=payload.account_id, recipient_user_id=payload.recipient_user_id,
                address=matching[0]["address"], can_forward=payload.can_forward)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.delete("/admin/grants")
    def revoke_account(owner_user_id: str, provider: Literal["gmail", "outlook"],
                       account_id: str, recipient_user_id: str,
                       actor: str = Depends(authenticated_user), org: str = Depends(authenticated_organization)):
        runtime.mail_directory.revoke_account(
            org, actor, owner_user_id=owner_user_id, provider=provider,
            account_id=account_id, recipient_user_id=recipient_user_id)
        return {"revoked": True}

    @router.get("/admin/rules")
    def list_rules(actor: str = Depends(authenticated_user), org: str = Depends(authenticated_organization)):
        return {"items": runtime.mail_directory.list_rules(org, actor)}

    @router.post("/admin/rules")
    def create_rule(payload: RoutingRule, actor: str = Depends(authenticated_user),
                    org: str = Depends(authenticated_organization)):
        try:
            return runtime.mail_directory.create_rule(
                org, actor, owner=payload.owner_user_id, provider=payload.provider,
                account_id=payload.account_id, match_text=payload.match_text,
                destination=payload.destination, scan_attachments=payload.scan_attachments,
                mode=payload.mode)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/forward-jobs")
    def forward_jobs(actor: str = Depends(authenticated_user), org: str = Depends(authenticated_organization)):
        return {"items": runtime.mail_directory.review_jobs(org, actor)}

    @router.post("/forward-jobs/{job_id}/approve")
    def approve(job_id: str, actor: str = Depends(authenticated_user),
                org: str = Depends(authenticated_organization)):
        try:
            return runtime.approve_forward(org, actor, job_id)
        except AccessDenied:
            raise
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Forwarding candidate not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Forward delivery uncertain; verify provider delivery") from exc

    @router.post("/forward-jobs/{job_id}/dismiss")
    def dismiss(job_id: str, actor: str = Depends(authenticated_user),
                org: str = Depends(authenticated_organization)):
        try:
            return runtime.mail_directory.dismiss_job(org, actor, job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Forwarding candidate not found") from exc

    return router
