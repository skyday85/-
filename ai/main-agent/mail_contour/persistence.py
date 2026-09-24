from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any


class MailPersistence:
    """Small SQLite persistence layer for the unified mail contour.

    SQLite is used as the durable local/dev store behind repository-neutral
    interfaces; production can later swap this implementation for PostgreSQL
    without changing mailbox/provider contracts.
    """

    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS mail_accounts (
              user_id TEXT NOT NULL, account_id TEXT NOT NULL, data TEXT NOT NULL,
              PRIMARY KEY(user_id, account_id)
            );
            CREATE TABLE IF NOT EXISTS mail_messages (
              user_id TEXT NOT NULL, email_id TEXT NOT NULL, data TEXT NOT NULL,
              PRIMARY KEY(user_id, email_id)
            );
            CREATE TABLE IF NOT EXISTS mail_provider_keys (
              user_id TEXT NOT NULL, provider TEXT NOT NULL, account_id TEXT NOT NULL,
              provider_message_id TEXT NOT NULL, email_id TEXT NOT NULL,
              PRIMARY KEY(user_id, provider, account_id, provider_message_id)
            );
            CREATE TABLE IF NOT EXISTS mail_sync_state (
              user_id TEXT NOT NULL, account_id TEXT NOT NULL, data TEXT NOT NULL,
              PRIMARY KEY(user_id, account_id)
            );
            CREATE TABLE IF NOT EXISTS integration_events (
              event_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fleet_document_candidates (
              candidate_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL,
              user_id TEXT NOT NULL, data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fleet_document_source_index (
              organization_id TEXT NOT NULL, user_id TEXT NOT NULL,
              source_email_id TEXT NOT NULL, attachment_id TEXT NOT NULL,
              candidate_id TEXT NOT NULL,
              PRIMARY KEY(organization_id, user_id, source_email_id, attachment_id)
            );
            """)
    
    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def put(self, table: str, key_columns: dict[str, Any], data: dict[str, Any]):
        columns = list(key_columns) + ["data"]
        values = [key_columns[x] for x in key_columns] + [json.dumps(data, ensure_ascii=False)]
        placeholders = ",".join("?" for _ in columns)
        conflict_keys = {"integration_events": ("event_id",), "fleet_document_candidates": ("candidate_id",)}.get(table)
        conflict = ",".join(conflict_keys or key_columns.keys())
        update = "data=excluded.data"
        with self._lock, self._connect() as db:
            db.execute(
                f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT({conflict}) DO UPDATE SET {update}", values
            )

    def all(self, table: str, where: str = "", params: tuple[Any, ...] = ()):
        with self._lock, self._connect() as db:
            rows = db.execute(f"SELECT data FROM {table} {where}", params).fetchall()
        return [json.loads(row["data"]) for row in rows]

    def delete(self, table: str, where: str, params: tuple[Any, ...]):
        with self._lock, self._connect() as db:
            db.execute(f"DELETE FROM {table} WHERE {where}", params)
