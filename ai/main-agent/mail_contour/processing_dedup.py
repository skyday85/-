"""Durable organization-scoped, idempotent business processing of duplicate mail.

The first received source may emit business events, document candidates and
forwarding jobs. Other copies are classified for their own mailbox, but do not
repeat downstream side effects. Ambiguous failures require manual reconciliation
rather than an unsafe second send/transfer.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from mail_contour.deduplication import (
    CONTENT_WINDOW_SECONDS, content_signature, message_key, received_epoch,
)


def _key(parts: list[object]) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":"), ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


class MailProcessingDeduper:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS org_mail_processing (
                    organization_id TEXT NOT NULL,
                    processing_key TEXT NOT NULL,
                    internet_key TEXT,
                    content_signature TEXT,
                    received_epoch INTEGER,
                    primary_owner TEXT NOT NULL,
                    primary_account_id TEXT NOT NULL,
                    primary_email_id TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'processing',
                    error TEXT,
                    PRIMARY KEY (organization_id, processing_key)
                );
                CREATE INDEX IF NOT EXISTS org_mail_processing_mid
                   ON org_mail_processing (organization_id, internet_key);
                CREATE INDEX IF NOT EXISTS org_mail_processing_fallback
                   ON org_mail_processing (organization_id, content_signature, received_epoch);
            """)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def claim(self, organization_id: str, owner_user_id: str, message: dict[str, Any]) -> dict[str, Any]:
        if not organization_id.strip() or not owner_user_id.strip():
            raise ValueError("Organization and source owner are required")
        mid = message_key(message)
        sig = content_signature(message)
        timestamp = received_epoch(message)
        source_account = str(message["account_id"])
        source_email_id = str(message["email_id"])
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = None
            reason = None
            if mid:
                existing = db.execute("""SELECT * FROM org_mail_processing
                    WHERE organization_id=? AND internet_key=? LIMIT 1""",
                    (organization_id, mid)).fetchone()
                if existing is not None:
                    reason = "same_internet_message_id"
            if existing is None and sig and timestamp is not None:
                candidates = db.execute("""SELECT * FROM org_mail_processing
                    WHERE organization_id=? AND content_signature=?
                    AND received_epoch BETWEEN ? AND ?""",
                    (organization_id, sig, timestamp - CONTENT_WINDOW_SECONDS,
                     timestamp + CONTENT_WINDOW_SECONDS)).fetchall()
                # When two distinct RFC message IDs are present they identify
                # distinct mail. Only an absent ID permits content fallback.
                candidates = [r for r in candidates
                              if not mid or r["internet_key"] is None]
                # Ambiguous matches (two real emails with identical content)
                # must not be guessed into a single business event.
                if len(candidates) == 1 and (
                    candidates[0]["primary_owner"] != owner_user_id or
                    candidates[0]["primary_account_id"] != source_account
                ):
                    existing = candidates[0]
                    reason = "identical_content_within_two_minutes"
                    if mid and existing["internet_key"] is None:
                        db.execute("""UPDATE org_mail_processing
                            SET internet_key=? WHERE organization_id=? AND processing_key=?""",
                            (mid, organization_id, existing["processing_key"]))
            if existing is not None:
                return {
                    "claimed": False, "reason": reason,
                    "primary_owner": existing["primary_owner"],
                    "primary_email_id": existing["primary_email_id"],
                    "primary_account_id": existing["primary_account_id"],
                    "state": existing["state"],
                }

            processing_key = mid or ("fallback:" + _key([sig, timestamp, owner_user_id, source_account])
                                      if sig else "source:" +
                                      _key([owner_user_id, source_account, source_email_id]))
            db.execute("""INSERT INTO org_mail_processing
                (organization_id, processing_key, internet_key, content_signature, received_epoch,
                 primary_owner, primary_account_id, primary_email_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (organization_id, processing_key, mid, sig, timestamp,
                 owner_user_id, source_account, source_email_id))
            return {"claimed": True, "processing_key": processing_key,
                    "primary_owner": owner_user_id, "primary_email_id": source_email_id,
                    "state": "processing"}

    def finish(self, organization_id: str, processing_key: str, *, success: bool,
               error: str = "") -> None:
        with self._lock, self._db() as db:
            result = db.execute("""UPDATE org_mail_processing SET state=?, error=?
                WHERE organization_id=? AND processing_key=? AND state='processing'""",
                ("processed" if success else "needs_review", error[:120],
                 organization_id, processing_key))
            if result.rowcount != 1:
                raise KeyError("Unknown or already finalized processing claim")
