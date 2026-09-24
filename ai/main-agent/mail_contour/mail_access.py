from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4
from email.utils import parseaddr

ROLES = {"owner", "admin", "member"}
JOB_STATES = {"pending_review", "sending", "forwarded", "needs_reconciliation", "dismissed"}


class AccessDenied(PermissionError):
    pass


def _email(value: str) -> str:
    value = value.strip()
    name, address = parseaddr(value)
    if name or address != value or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value):
        raise ValueError("A valid plain email address is required")
    return address.lower()


class MailAccessDirectory:
    """Organization users, account grants and audited mail routing; no mailbox credentials.

    Authentication is performed by a trusted identity provider/proxy. Creating a user
    here never creates credentials or a session. SQLite is the development store.
    """

    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS org_mail_users (
                  organization_id TEXT NOT NULL, user_id TEXT NOT NULL,
                  display_name TEXT NOT NULL, email TEXT NOT NULL, role TEXT NOT NULL,
                  active INTEGER NOT NULL DEFAULT 1,
                  PRIMARY KEY (organization_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS org_mail_grants (
                  organization_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
                  provider TEXT NOT NULL, account_id TEXT NOT NULL,
                  recipient_user_id TEXT NOT NULL, address TEXT NOT NULL,
                  can_forward INTEGER NOT NULL DEFAULT 0,
                  PRIMARY KEY (organization_id, owner_user_id, provider, account_id, recipient_user_id)
                );
                CREATE TABLE IF NOT EXISTS org_mail_rules (
                  rule_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL,
                  owner_user_id TEXT NOT NULL, provider TEXT NOT NULL,
                  account_id TEXT NOT NULL, match_text TEXT NOT NULL,
                  destination TEXT NOT NULL, scan_attachments INTEGER NOT NULL DEFAULT 0,
                  mode TEXT NOT NULL DEFAULT 'review', enabled INTEGER NOT NULL DEFAULT 1,
                  created_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS org_mail_forward_jobs (
                  job_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL,
                  rule_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
                  provider TEXT NOT NULL, account_id TEXT NOT NULL,
                  email_id TEXT NOT NULL, destination TEXT NOT NULL,
                  matched_in TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending_review',
                  decided_by TEXT, provider_result TEXT, error_code TEXT,
                  UNIQUE(organization_id, rule_id, owner_user_id, email_id)
                );
                CREATE INDEX IF NOT EXISTS org_mail_grants_for_user
                  ON org_mail_grants (organization_id, recipient_user_id);
                CREATE INDEX IF NOT EXISTS org_mail_jobs_for_org
                  ON org_mail_forward_jobs (organization_id, status);
            """)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _row(row):
        if row is None:
            return None
        result = dict(row)
        for field in ("active", "can_forward", "scan_attachments", "enabled"):
            if field in result:
                result[field] = bool(result[field])
        return result

    def bootstrap_owner(self, organization_id: str, owner_user_id: str, email: str, display_name: str = "Owner") -> dict:
        """Only call with deployment-configured organization and trusted owner subject."""
        if not organization_id or not owner_user_id:
            raise ValueError("Bootstrap identity is required")
        with self._lock, self._db() as db:
            db.execute("""INSERT OR IGNORE INTO org_mail_users
                          (organization_id, user_id, display_name, email, role)
                          VALUES (?, ?, ?, ?, 'owner')""",
                       (organization_id, owner_user_id, display_name, _email(email)))
        return self.require_member(organization_id, owner_user_id)

    def require_member(self, org: str, user: str) -> dict:
        with self._db() as db:
            result = db.execute("""SELECT * FROM org_mail_users
                WHERE organization_id=? AND user_id=? AND active=1""", (org, user)).fetchone()
        if result is None:
            raise AccessDenied("User does not belong to this active organization")
        return self._row(result)

    def require_admin(self, org: str, user: str) -> dict:
        member = self.require_member(org, user)
        if member["role"] not in ("owner", "admin"):
            raise AccessDenied("Organization mail administrator required")
        return member

    def create_user(self, org: str, actor: str, *, user_id: str, email: str,
                    display_name: str, role: str = "member") -> dict:
        self.require_admin(org, actor)
        if role not in {"member", "admin"} or not user_id.strip() or not display_name.strip():
            raise ValueError("Invalid role or user identity")
        try:
            with self._lock, self._db() as db:
                db.execute("""INSERT INTO org_mail_users
                   (organization_id, user_id, display_name, email, role)
                   VALUES (?, ?, ?, ?, ?)""",
                   (org, user_id.strip(), display_name.strip(), _email(email), role))
        except sqlite3.IntegrityError as exc:
            raise ValueError("User already exists") from exc
        return self.require_member(org, user_id.strip())

    def users(self, org: str, actor: str) -> list[dict]:
        self.require_admin(org, actor)
        with self._db() as db:
            return [self._row(r) for r in db.execute(
                "SELECT * FROM org_mail_users WHERE organization_id=? ORDER BY display_name",
                (org,)).fetchall()]

    def set_active(self, org: str, actor: str, user_id: str, active: bool) -> dict:
        self.require_admin(org, actor)
        if actor == user_id and not active:
            raise ValueError("Cannot deactivate yourself")
        with self._lock, self._db() as db:
            target = db.execute("SELECT role FROM org_mail_users WHERE organization_id=? AND user_id=?",
                                (org, user_id)).fetchone()
            if target is None:
                raise KeyError(user_id)
            if target["role"] == "owner" and not active:
                raise ValueError("Cannot deactivate organization owner")
            db.execute("UPDATE org_mail_users SET active=? WHERE organization_id=? AND user_id=?",
                       (int(active), org, user_id))
        return self.require_member(org, user_id) if active else {"user_id": user_id, "active": False}

    def grant_account(self, org: str, actor: str, *, owner_user_id: str, provider: str,
                      account_id: str, recipient_user_id: str, address: str,
                      can_forward: bool = False) -> dict:
        self.require_admin(org, actor)
        self.require_member(org, owner_user_id)
        self.require_member(org, recipient_user_id)
        if provider.lower() not in {"gmail", "outlook"} or not account_id.strip():
            raise ValueError("Invalid mail account")
        with self._lock, self._db() as db:
            db.execute("""INSERT INTO org_mail_grants
                (organization_id, owner_user_id, provider, account_id,
                 recipient_user_id, address, can_forward)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(organization_id, owner_user_id, provider, account_id, recipient_user_id)
                DO UPDATE SET can_forward=excluded.can_forward, address=excluded.address""",
                (org, owner_user_id, provider.lower(), account_id, recipient_user_id, _email(address), int(can_forward)))
        return {"organization_id": org, "owner_user_id": owner_user_id, "provider": provider.lower(),
                "account_id": account_id, "recipient_user_id": recipient_user_id,
                "address": address.lower(), "can_forward": can_forward}

    def revoke_account(self, org: str, actor: str, *, owner_user_id: str, provider: str,
                       account_id: str, recipient_user_id: str) -> None:
        self.require_admin(org, actor)
        with self._lock, self._db() as db:
            db.execute("""DELETE FROM org_mail_grants WHERE organization_id=? AND
                owner_user_id=? AND provider=? AND account_id=? AND recipient_user_id=?""",
                (org, owner_user_id, provider, account_id, recipient_user_id))

    def grants(self, org: str, actor: str, *, user_id: str | None = None) -> list[dict]:
        member = self.require_member(org, actor)
        requested = user_id or actor
        if requested != actor and member["role"] not in ("admin", "owner"):
            raise AccessDenied("Cannot inspect other users' assignments")
        with self._db() as db:
            return [self._row(r) for r in db.execute("""
                SELECT g.* FROM org_mail_grants g
                JOIN org_mail_users u ON u.organization_id=g.organization_id
                   AND u.user_id=g.owner_user_id AND u.active=1
                JOIN org_mail_users r ON r.organization_id=g.organization_id
                   AND r.user_id=g.recipient_user_id AND r.active=1
                WHERE g.organization_id=? AND g.recipient_user_id=?
                ORDER BY g.address""", (org, requested)).fetchall()]

    def all_grants(self, org: str, actor: str) -> list[dict]:
        self.require_admin(org, actor)
        with self._db() as db:
            return [self._row(r) for r in db.execute("""
                SELECT g.* FROM org_mail_grants g
                JOIN org_mail_users u ON u.organization_id=g.organization_id
                   AND u.user_id=g.owner_user_id AND u.active=1
                JOIN org_mail_users r ON r.organization_id=g.organization_id
                   AND r.user_id=g.recipient_user_id AND r.active=1
                WHERE g.organization_id=? ORDER BY g.address, g.recipient_user_id
                """, (org,)).fetchall()]

    def assert_grant(self, org: str, actor: str, *, owner: str, provider: str,
                     account_id: str, forwarding: bool = False) -> dict:
        for grant in self.grants(org, actor):
            if (grant["owner_user_id"], grant["provider"], grant["account_id"]) == (owner, provider, account_id):
                if forwarding and not grant["can_forward"]:
                    break
                return grant
        raise AccessDenied("Mailbox not assigned to this user with required permission")

    def create_rule(self, org: str, actor: str, *, owner: str, provider: str,
                    account_id: str, match_text: str, destination: str,
                    scan_attachments: bool = False, mode: str = "review") -> dict:
        self.require_admin(org, actor)
        self.require_member(org, owner)
        if mode == "auto":
            self.assert_grant(org, actor, owner=owner, provider=provider,
                              account_id=account_id, forwarding=True)
        if mode not in {"review", "auto"}:
            raise ValueError("Unknown approval mode")
        term = match_text.strip().casefold()
        if len(term) < 3 and term != "*":
            raise ValueError("Use at least three characters or *")
        with self._lock, self._db() as db:
            existing = db.execute("""SELECT 1 FROM org_mail_grants
                 WHERE organization_id=? AND owner_user_id=? AND provider=? AND account_id=? LIMIT 1""",
                 (org, owner, provider, account_id)).fetchone()
            if existing is None:
                raise ValueError("Account must be assigned before creating a rule")
            rule_id = str(uuid4())
            db.execute("""INSERT INTO org_mail_rules
                 (rule_id, organization_id, owner_user_id, provider, account_id,
                 match_text, destination, scan_attachments, mode, created_by)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (rule_id, org, owner, provider, account_id, term, _email(destination),
                  int(scan_attachments), mode, actor))
        return self.get_rule(rule_id)

    def get_rule(self, rule_id: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT * FROM org_mail_rules WHERE rule_id=?", (rule_id,)).fetchone()
        if row is None:
            raise KeyError(rule_id)
        return self._row(row)

    def list_rules(self, org: str, actor: str) -> list[dict]:
        self.require_admin(org, actor)
        with self._db() as db:
            return [self._row(r) for r in db.execute(
                "SELECT * FROM org_mail_rules WHERE organization_id=?", (org,)).fetchall()]

    def rules_for_account(self, org: str, owner: str, provider: str, account_id: str) -> list[dict]:
        with self._db() as db:
            return [self._row(r) for r in db.execute("""
                SELECT * FROM org_mail_rules WHERE organization_id=?
                AND owner_user_id=? AND provider=? AND account_id=? AND enabled=1""",
                (org, owner, provider, account_id)).fetchall()]

    def queue_job(self, *, rule: dict, email_id: str, matched_in: str) -> dict:
        job_id = str(uuid4())
        with self._lock, self._db() as db:
            db.execute("""INSERT OR IGNORE INTO org_mail_forward_jobs
               (job_id, organization_id, rule_id, owner_user_id, provider,
                account_id, email_id, destination, matched_in)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
               (job_id, rule["organization_id"], rule["rule_id"], rule["owner_user_id"],
                rule["provider"], rule["account_id"], email_id, rule["destination"], matched_in))
            row = db.execute("""SELECT * FROM org_mail_forward_jobs
                WHERE organization_id=? AND rule_id=? AND owner_user_id=? AND email_id=?""",
                (rule["organization_id"], rule["rule_id"], rule["owner_user_id"], email_id)).fetchone()
        return self._row(row)

    def system_job(self, org: str, job_id: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT * FROM org_mail_forward_jobs WHERE organization_id=? AND job_id=?",
                             (org, job_id)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._row(row)

    def get_job(self, org: str, actor: str, job_id: str, *, forwarding: bool = False) -> dict:
        self.require_member(org, actor)
        with self._db() as db:
            row = db.execute("""SELECT * FROM org_mail_forward_jobs
                WHERE organization_id=? AND job_id=?""", (org, job_id)).fetchone()
        if row is None:
            raise KeyError(job_id)
        result = self._row(row)
        self.assert_grant(org, actor, owner=result["owner_user_id"], provider=result["provider"],
                          account_id=result["account_id"], forwarding=forwarding)
        return result

    def review_jobs(self, org: str, actor: str) -> list[dict]:
        self.require_member(org, actor)
        with self._db() as db:
            return [self._row(r) for r in db.execute("""
                SELECT DISTINCT j.* FROM org_mail_forward_jobs j
                JOIN org_mail_grants g ON j.organization_id=g.organization_id
                  AND j.owner_user_id=g.owner_user_id AND j.provider=g.provider
                  AND j.account_id=g.account_id
                JOIN org_mail_users u ON u.organization_id=g.organization_id
                  AND u.user_id=g.owner_user_id AND u.active=1
                WHERE j.organization_id=? AND g.recipient_user_id=?
                ORDER BY j.rowid DESC LIMIT 200""", (org, actor)).fetchall()]

    def claim_job(self, org: str, actor: str, job_id: str, *, automated: bool = False) -> dict:
        if not automated:
            self.get_job(org, actor, job_id, forwarding=True)
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT j.*, r.mode FROM org_mail_forward_jobs j
                JOIN org_mail_rules r ON r.rule_id=j.rule_id
                WHERE j.job_id=? AND j.organization_id=?""", (job_id, org)).fetchone()
            if row is None or row["status"] != "pending_review":
                raise ValueError("Forwarding job is not pending")
            if automated and (row["mode"] != "auto" or not row["owner_user_id"] == actor):
                raise AccessDenied("Automatic forwarding is not authorized")
            db.execute("""UPDATE org_mail_forward_jobs
               SET status='sending', decided_by=? WHERE job_id=? AND status='pending_review'""",
               ("system" if automated else actor, job_id))
        return self.get_rule(row["rule_id"]) | {"job_id": job_id, "email_id": row["email_id"],
              "destination": row["destination"], "owner_user_id": row["owner_user_id"],
              "provider": row["provider"], "account_id": row["account_id"]}

    def finish_job(self, job_id: str, *, success: bool, provider_result: str = "", error_code: str = "") -> None:
        with self._lock, self._db() as db:
            db.execute("""UPDATE org_mail_forward_jobs
                SET status=?, provider_result=?, error_code=?
                WHERE job_id=? AND status='sending'""",
                ("forwarded" if success else "needs_reconciliation",
                 provider_result[:200], error_code[:120], job_id))

    def dismiss_job(self, org: str, actor: str, job_id: str) -> dict:
        self.get_job(org, actor, job_id, forwarding=True)
        with self._lock, self._db() as db:
            db.execute("""UPDATE org_mail_forward_jobs
                SET status='dismissed', decided_by=?
                WHERE job_id=? AND organization_id=? AND status='pending_review'""",
                (actor, job_id, org))
        return self.get_job(org, actor, job_id)
