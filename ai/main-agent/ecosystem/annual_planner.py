"""Annual/monthly planning ledger; changes to approved plans need explicit approval."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4


class PlanConflict(ValueError):
    pass


def _str(value, field, limit=300):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"{field} must be non-empty and <= {limit} characters")
    return value.strip()


def _now():
    return datetime.now(timezone.utc).isoformat()


class AnnualPlanner:
    """State is isolated by organization and never changes a connected app."""

    def __init__(self, path: str):
        self.path = path
        self._lock = RLock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS annual_plans (
              plan_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, year INTEGER NOT NULL,
              objective TEXT NOT NULL, status TEXT NOT NULL, created_by TEXT NOT NULL,
              approved_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS annual_plans_by_org
              ON annual_plans(organization_id,year);
            CREATE TABLE IF NOT EXISTS annual_milestones (
              milestone_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES annual_plans(plan_id),
              organization_id TEXT NOT NULL, month INTEGER NOT NULL, title TEXT NOT NULL,
              status TEXT NOT NULL, business_case_id TEXT, updated_at TEXT NOT NULL,
              UNIQUE(plan_id,month,title)
            );
            CREATE TABLE IF NOT EXISTS annual_plan_proposals (
              proposal_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES annual_plans(plan_id),
              organization_id TEXT NOT NULL, milestone_id TEXT NOT NULL,
              next_status TEXT NOT NULL, reason TEXT NOT NULL, submitted_by TEXT NOT NULL,
              status TEXT NOT NULL, decided_by TEXT, created_at TEXT NOT NULL, decided_at TEXT
            );
            CREATE TABLE IF NOT EXISTS annual_plan_audit (
              audit_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES annual_plans(plan_id),
              organization_id TEXT NOT NULL, actor_id TEXT NOT NULL,
              action TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL
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

    @staticmethod
    def _get(db, org, plan_id):
        result = db.execute("SELECT * FROM annual_plans WHERE organization_id=? AND plan_id=?",
                            (org, plan_id)).fetchone()
        if result is None:
            raise KeyError(plan_id)
        return result

    @staticmethod
    def _audit(db, org, plan_id, actor, action, details):
        db.execute("INSERT INTO annual_plan_audit VALUES (?,?,?,?,?,?,?)",
                   (str(uuid4()), plan_id, org, actor, action,
                    json.dumps(details, ensure_ascii=False, sort_keys=True), _now()))

    def create(self, organization_id, year: int, objective, actor_id):
        org = _str(organization_id, "organization_id")
        actor = _str(actor_id, "actor_id")
        objective = _str(objective, "objective", 1000)
        if not isinstance(year, int) or isinstance(year, bool) or year < 2020 or year > 2100:
            raise ValueError("year out of range")
        plan_id, now = str(uuid4()), _now()
        with self._lock, self._db() as db:
            db.execute("INSERT INTO annual_plans VALUES (?,?,?,?,?,?,?,?,?)",
                       (plan_id, org, year, objective, "draft", actor, None, now, now))
            self._audit(db, org, plan_id, actor, "plan_created", {"year": year})
        return self.get(org, plan_id)

    def get(self, organization_id, plan_id):
        org = _str(organization_id, "organization_id")
        with self._lock, self._db() as db:
            result = dict(self._get(db, org, plan_id))
            for table, key in (("annual_milestones", "milestones"), ("annual_plan_proposals", "proposals"),
                               ("annual_plan_audit", "audit")):
                rows = db.execute(f"SELECT * FROM {table} WHERE organization_id=? AND plan_id=? ORDER BY rowid",
                                  (org, plan_id)).fetchall()
                result[key] = [dict(row) for row in rows]
            for row in result["audit"]:
                row["details"] = json.loads(row["details"])
            total = len(result["milestones"])
            result["progress"] = {"total": total,
                                  "done": sum(m["status"] == "done" for m in result["milestones"]),
                                  "blocked": sum(m["status"] == "blocked" for m in result["milestones"])}
            return result

    def list(self, organization_id, year: int | None = None):
        org = _str(organization_id, "organization_id")
        with self._lock, self._db() as db:
            if year is not None:
                rows = db.execute("SELECT * FROM annual_plans WHERE organization_id=? AND year=? ORDER BY created_at DESC",
                                  (org, year)).fetchall()
            else:
                rows = db.execute("SELECT * FROM annual_plans WHERE organization_id=? ORDER BY year DESC,created_at DESC",
                                  (org,)).fetchall()
            return [dict(row) for row in rows]

    def add_milestone(self, organization_id, plan_id, month: int, title: str,
                      actor_id: str, business_case_id: str | None = None):
        org, actor = _str(organization_id, "organization_id"), _str(actor_id, "actor_id")
        title = _str(title, "title", 500)
        if type(month) is not int or month < 1 or month > 12:
            raise ValueError("month must be in 1..12")
        if business_case_id is not None:
            business_case_id = _str(business_case_id, "business_case_id")
        with self._lock, self._db() as db:
            plan = self._get(db, org, plan_id)
            if plan["status"] != "draft":
                raise PlanConflict("approved plan structure cannot be changed without a separate revision")
            existing = db.execute("SELECT * FROM annual_milestones WHERE plan_id=? AND month=? AND title=?",
                                  (plan_id, month, title)).fetchone()
            if existing:
                return dict(existing)
            item_id, now = str(uuid4()), _now()
            db.execute("INSERT INTO annual_milestones VALUES (?,?,?,?,?,?,?,?)",
                       (item_id, plan_id, org, month, title, "planned", business_case_id, now))
            self._audit(db, org, plan_id, actor, "milestone_added",
                        {"milestone_id": item_id, "month": month, "business_case_id": business_case_id})
            return {"milestone_id": item_id, "month": month, "title": title,
                    "status": "planned", "business_case_id": business_case_id}

    def approve(self, organization_id, plan_id, actor_id):
        org, actor = _str(organization_id, "organization_id"), _str(actor_id, "actor_id")
        with self._lock, self._db() as db:
            plan = self._get(db, org, plan_id)
            if plan["status"] != "draft":
                raise PlanConflict("plan is already approved")
            if actor != plan["created_by"]:
                raise PlanConflict("only the plan owner can approve")
            count = db.execute("SELECT COUNT(*) FROM annual_milestones WHERE plan_id=?",
                               (plan_id,)).fetchone()[0]
            if count == 0:
                raise PlanConflict("plan must contain at least one user-defined milestone")
            now = _now()
            db.execute("UPDATE annual_plans SET status='approved',approved_by=?,updated_at=? WHERE plan_id=?",
                       (actor, now, plan_id))
            self._audit(db, org, plan_id, actor, "plan_approved", {"milestones": count})
        return self.get(org, plan_id)

    def propose_milestone_status(self, organization_id, plan_id, milestone_id, next_status,
                                 reason, actor_id):
        org, actor = _str(organization_id, "organization_id"), _str(actor_id, "actor_id")
        reason = _str(reason, "reason", 1000)
        if next_status not in {"planned", "in_progress", "done", "blocked"}:
            raise ValueError("unsupported milestone status")
        with self._lock, self._db() as db:
            plan = self._get(db, org, plan_id)
            if plan["status"] != "approved":
                raise PlanConflict("only approved plans accept status proposals")
            milestone = db.execute("SELECT * FROM annual_milestones WHERE organization_id=? AND plan_id=? AND milestone_id=?",
                                   (org, plan_id, milestone_id)).fetchone()
            if not milestone:
                raise KeyError(milestone_id)
            if milestone["status"] == next_status:
                raise PlanConflict("status is unchanged")
            pending = db.execute("SELECT proposal_id FROM annual_plan_proposals WHERE milestone_id=? AND status='pending'",
                                 (milestone_id,)).fetchone()
            if pending:
                raise PlanConflict("another change proposal is pending")
            proposal_id, now = str(uuid4()), _now()
            db.execute("INSERT INTO annual_plan_proposals VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (proposal_id, plan_id, org, milestone_id, next_status, reason, actor,
                        "pending", None, now, None))
            self._audit(db, org, plan_id, actor, "milestone_status_proposed",
                        {"proposal_id": proposal_id, "next_status": next_status})
            return {"proposal_id": proposal_id, "status": "pending"}

    def decide_proposal(self, organization_id, plan_id, proposal_id, actor_id, approved: bool):
        org, actor = _str(organization_id, "organization_id"), _str(actor_id, "actor_id")
        if type(approved) is not bool:
            raise ValueError("approved must be boolean")
        with self._lock, self._db() as db:
            plan = self._get(db, org, plan_id)
            if actor != plan["created_by"]:
                raise PlanConflict("only the plan owner can decide changes")
            proposal = db.execute(
                "SELECT * FROM annual_plan_proposals WHERE organization_id=? AND plan_id=? AND proposal_id=?",
                (org, plan_id, proposal_id)).fetchone()
            if not proposal:
                raise KeyError(proposal_id)
            if proposal["status"] != "pending":
                raise PlanConflict("proposal already decided")
            now, status = _now(), ("approved" if approved else "rejected")
            db.execute("UPDATE annual_plan_proposals SET status=?,decided_by=?,decided_at=? WHERE proposal_id=?",
                       (status, actor, now, proposal_id))
            if approved:
                db.execute("UPDATE annual_milestones SET status=?,updated_at=? WHERE milestone_id=?",
                           (proposal["next_status"], now, proposal["milestone_id"]))
            self._audit(db, org, plan_id, actor, "proposal_decided",
                        {"proposal_id": proposal_id, "decision": status})
        return self.get(org, plan_id)

    def overview(self, organization_id, plan_id, business_cases=None):
        result = self.get(organization_id, plan_id)
        linked = {case["case_id"]: case["status"] for case in (business_cases or [])}
        signals = []
        for milestone in result["milestones"]:
            case_id = milestone["business_case_id"]
            if case_id and case_id in linked:
                signals.append({"milestone_id": milestone["milestone_id"],
                                "case_id": case_id, "case_status": linked[case_id],
                                "attention": linked[case_id] in {"blocked", "needs_review"}})
        result["case_monitoring"] = signals
        result["requires_attention"] = (
            result["progress"]["blocked"] > 0 or any(x["attention"] for x in signals))
        return result
