"""Organization-scoped control-plane cases; no writes to application databases."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from ecosystem.project_registry import ProjectRegistry

CASE_TYPES = {"general", "procurement", "fleet_maintenance", "transport_request", "finance_review"}
SIGNAL_TYPES = {"observed", "progress", "completed", "failed", "review_requested"}
STATUSES = {"open", "in_progress", "needs_review", "blocked", "closed"}


class CaseConflict(ValueError):
    """Conflicting operation or reused external event ID."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required(value: str, field: str, limit: int = 300) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"{field} must be nonempty and at most {limit} characters")
    return value.strip()


class BusinessCaseStore:
    """SQLite development store; use shared transactional storage for multi-instance production."""

    def __init__(self, path: str, projects: ProjectRegistry | None = None):
        self.path = path
        self.projects = projects or ProjectRegistry()
        self._lock = RLock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS business_cases (
              case_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL,
              created_by TEXT NOT NULL, title TEXT NOT NULL, case_type TEXT NOT NULL,
              status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS business_cases_org ON business_cases(organization_id,updated_at);
            CREATE TABLE IF NOT EXISTS business_case_links (
              link_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES business_cases(case_id),
              organization_id TEXT NOT NULL, project_id TEXT NOT NULL,
              record_type TEXT NOT NULL, record_id TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(organization_id,case_id,project_id,record_type,record_id)
            );
            CREATE TABLE IF NOT EXISTS business_case_signals (
              signal_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES business_cases(case_id),
              organization_id TEXT NOT NULL, project_id TEXT NOT NULL,
              source_record_id TEXT NOT NULL, source_event_id TEXT NOT NULL,
              event_type TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(organization_id,project_id,source_event_id)
            );
            CREATE TABLE IF NOT EXISTS business_case_reviews (
              review_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES business_cases(case_id),
              organization_id TEXT NOT NULL, signal_id TEXT NOT NULL UNIQUE
                REFERENCES business_case_signals(signal_id),
              status TEXT NOT NULL, decision_by TEXT, decision_at TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS business_case_audit (
              audit_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES business_cases(case_id),
              organization_id TEXT NOT NULL, action TEXT NOT NULL, actor_id TEXT NOT NULL,
              details TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def _case(self, db, org, case_id):
        row = db.execute("SELECT * FROM business_cases WHERE organization_id=? AND case_id=?",
                         (org, case_id)).fetchone()
        if row is None:
            raise KeyError(case_id)
        return row

    def _project(self, project_id):
        project = self.projects.get(_required(project_id, "project_id"))
        if project is None or project.status != "active":
            raise ValueError("project is not registered as active")

    @staticmethod
    def _audit(db, org, case_id, action, actor, details):
        db.execute("INSERT INTO business_case_audit VALUES (?,?,?,?,?,?,?)",
                   (str(uuid4()), case_id, org, action, actor,
                    json.dumps(details, ensure_ascii=False, sort_keys=True), _now()))

    def create_case(self, organization_id: str, created_by: str, title: str,
                    case_type: str = "general") -> dict:
        org = _required(organization_id, "organization_id")
        actor = _required(created_by, "created_by")
        title = _required(title, "title")
        if case_type not in CASE_TYPES:
            raise ValueError("unsupported case_type")
        case_id, now = str(uuid4()), _now()
        with self._lock, self._db() as db:
            db.execute("INSERT INTO business_cases VALUES (?,?,?,?,?,?,?,?)",
                       (case_id, org, actor, title, case_type, "open", now, now))
            self._audit(db, org, case_id, "case_created", actor, {"case_type": case_type})
        return self.get_case(org, case_id)

    def list_cases(self, organization_id: str, status: str | None = None) -> list[dict]:
        org = _required(organization_id, "organization_id")
        if status is not None and status not in STATUSES:
            raise ValueError("unsupported status")
        with self._lock, self._db() as db:
            if status:
                rows = db.execute("SELECT * FROM business_cases WHERE organization_id=? AND status=? ORDER BY updated_at DESC",
                                  (org, status)).fetchall()
            else:
                rows = db.execute("SELECT * FROM business_cases WHERE organization_id=? ORDER BY updated_at DESC",
                                  (org,)).fetchall()
            return [dict(row) for row in rows]

    def get_case(self, organization_id: str, case_id: str) -> dict:
        org = _required(organization_id, "organization_id")
        with self._lock, self._db() as db:
            result = dict(self._case(db, org, case_id))
            for table, label in (("business_case_links", "links"), ("business_case_signals", "signals"),
                                 ("business_case_reviews", "reviews"), ("business_case_audit", "audit")):
                rows = db.execute(f"SELECT * FROM {table} WHERE case_id=? AND organization_id=? ORDER BY created_at,rowid",
                                  (case_id, org)).fetchall()
                result[label] = [dict(row) for row in rows]
            for event in result["signals"]:
                event["metadata"] = json.loads(event["metadata"])
            for entry in result["audit"]:
                entry["details"] = json.loads(entry["details"])
            return result

    def link_record(self, organization_id: str, case_id: str, project_id: str,
                    record_type: str, record_id: str, actor_id: str) -> dict:
        org, actor = _required(organization_id, "organization_id"), _required(actor_id, "actor_id")
        record_type, record_id = _required(record_type, "record_type"), _required(record_id, "record_id")
        self._project(project_id)
        with self._lock, self._db() as db:
            case = self._case(db, org, case_id)
            existing = db.execute("""
              SELECT * FROM business_case_links WHERE organization_id=? AND case_id=?
              AND project_id=? AND record_type=? AND record_id=?""",
              (org, case_id, project_id, record_type, record_id)).fetchone()
            if existing:
                return dict(existing)
            if case["status"] == "closed":
                raise CaseConflict("closed case cannot be modified")
            link_id, now = str(uuid4()), _now()
            db.execute("INSERT INTO business_case_links VALUES (?,?,?,?,?,?,?)",
                       (link_id, case_id, org, project_id, record_type, record_id, now))
            db.execute("UPDATE business_cases SET updated_at=? WHERE case_id=?", (now, case_id))
            self._audit(db, org, case_id, "record_linked", actor,
                        {"project_id": project_id, "record_type": record_type, "record_id": record_id})
            return {"link_id": link_id, "case_id": case_id, "organization_id": org,
                    "project_id": project_id, "record_type": record_type,
                    "record_id": record_id, "created_at": now}

    def record_signal(self, organization_id: str, case_id: str, project_id: str,
                      source_record_id: str, source_event_id: str, event_type: str,
                      metadata: dict[str, Any] | None = None) -> dict:
        org = _required(organization_id, "organization_id")
        source_record_id = _required(source_record_id, "source_record_id")
        source_event_id = _required(source_event_id, "source_event_id")
        self._project(project_id)
        if event_type not in SIGNAL_TYPES:
            raise ValueError("unsupported event_type")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        try:
            packed = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be JSON-serializable") from exc
        if len(packed.encode("utf-8")) > 16384:
            raise ValueError("metadata too large")
        with self._lock, self._db() as db:
            case = self._case(db, org, case_id)
            existing = db.execute("""
              SELECT * FROM business_case_signals WHERE organization_id=?
              AND project_id=? AND source_event_id=?""",
              (org, project_id, source_event_id)).fetchone()
            if existing:
                if (existing["case_id"], existing["source_record_id"],
                    existing["event_type"], existing["metadata"]) != (
                    case_id, source_record_id, event_type, packed):
                    raise CaseConflict("external event ID already used with different contents")
                return {**dict(existing), "metadata": json.loads(existing["metadata"]), "duplicate": True}
            if case["status"] == "closed":
                raise CaseConflict("closed case cannot be modified")
            signal_id, now = str(uuid4()), _now()
            db.execute("INSERT INTO business_case_signals VALUES (?,?,?,?,?,?,?,?,?)",
                       (signal_id, case_id, org, project_id, source_record_id,
                        source_event_id, event_type, packed, now))
            if event_type == "review_requested":
                db.execute("INSERT INTO business_case_reviews VALUES (?,?,?,?,?,?,?,?)",
                           (str(uuid4()), case_id, org, signal_id, "pending", None, None, now))
            status = case["status"]
            if event_type == "failed":
                status = "blocked"
            elif event_type == "review_requested" and status != "blocked":
                status = "needs_review"
            elif event_type in {"progress", "completed"} and status == "open":
                status = "in_progress"
            db.execute("UPDATE business_cases SET status=?,updated_at=? WHERE case_id=?",
                       (status, now, case_id))
            self._audit(db, org, case_id, "signal_received", f"integration:{project_id}",
                        {"source_record_id": source_record_id, "source_event_id": source_event_id,
                         "event_type": event_type})
            return {"signal_id": signal_id, "case_id": case_id, "organization_id": org,
                    "project_id": project_id, "source_record_id": source_record_id,
                    "source_event_id": source_event_id, "event_type": event_type,
                    "metadata": json.loads(packed), "created_at": now, "duplicate": False}

    def decide_review(self, organization_id: str, case_id: str, review_id: str,
                      actor_id: str, approved: bool) -> dict:
        org, actor = _required(organization_id, "organization_id"), _required(actor_id, "actor_id")
        if not isinstance(approved, bool):
            raise ValueError("approved must be boolean")
        with self._lock, self._db() as db:
            case = self._case(db, org, case_id)
            row = db.execute("""
              SELECT * FROM business_case_reviews WHERE organization_id=?
              AND case_id=? AND review_id=?""", (org, case_id, review_id)).fetchone()
            if row is None:
                raise KeyError(review_id)
            if row["status"] != "pending":
                raise CaseConflict("review already decided")
            now, decision = _now(), "approved" if approved else "rejected"
            db.execute("UPDATE business_case_reviews SET status=?,decision_by=?,decision_at=? WHERE review_id=?",
                       (decision, actor, now, review_id))
            pending = db.execute("SELECT count(*) FROM business_case_reviews WHERE case_id=? AND status='pending'",
                                 (case_id,)).fetchone()[0]
            status = ("blocked" if not approved or case["status"] == "blocked"
                      else "needs_review" if pending else "in_progress")
            db.execute("UPDATE business_cases SET status=?,updated_at=? WHERE case_id=?",
                       (status, now, case_id))
            self._audit(db, org, case_id, "review_decided", actor,
                        {"review_id": review_id, "decision": decision})
        return self.get_case(org, case_id)

    def resume_case(self, organization_id: str, case_id: str, actor_id: str,
                    reason: str) -> dict:
        org, actor = _required(organization_id, "organization_id"), _required(actor_id, "actor_id")
        reason = _required(reason, "reason", 1000)
        with self._lock, self._db() as db:
            case = self._case(db, org, case_id)
            if case["status"] != "blocked":
                raise CaseConflict("only blocked cases can be resumed")
            rejected = db.execute("SELECT count(*) FROM business_case_reviews WHERE case_id=? AND status='rejected'",
                                  (case_id,)).fetchone()[0]
            if rejected:
                raise CaseConflict("rejected review cannot be bypassed; open a corrected case")
            pending = db.execute("SELECT count(*) FROM business_case_reviews WHERE case_id=? AND status='pending'",
                                 (case_id,)).fetchone()[0]
            status, now = ("needs_review" if pending else "in_progress"), _now()
            db.execute("UPDATE business_cases SET status=?,updated_at=? WHERE case_id=?",
                       (status, now, case_id))
            self._audit(db, org, case_id, "case_resumed", actor, {"reason": reason})
        return self.get_case(org, case_id)

    def close_case(self, organization_id: str, case_id: str, actor_id: str) -> dict:
        org, actor = _required(organization_id, "organization_id"), _required(actor_id, "actor_id")
        with self._lock, self._db() as db:
            case = self._case(db, org, case_id)
            if case["status"] == "closed":
                return self.get_case(org, case_id)
            if case["status"] not in {"open", "in_progress"}:
                raise CaseConflict("blocked or review-pending cases cannot be closed")
            now = _now()
            db.execute("UPDATE business_cases SET status='closed',updated_at=? WHERE case_id=?",
                       (now, case_id))
            self._audit(db, org, case_id, "case_closed", actor, {})
        return self.get_case(org, case_id)
