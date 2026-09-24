"""Conservative, non-destructive deduplication of copies of the SAME email.

Never delete source messages: per-account read state, attachments, permissions,
provider IDs and audit records must remain independent. Only the shared view and
business processing collapse verified duplicates.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any, Iterable

CONTENT_WINDOW_SECONDS = 120


def _normalized(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def _hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def received_epoch(message: dict[str, Any]) -> int | None:
    raw = message.get("received_at")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp())
    except (TypeError, ValueError, OverflowError):
        return None


def internet_id(message: dict[str, Any]) -> str | None:
    raw = str(message.get("internet_message_id") or "").strip().strip("<>").strip()
    if not raw or len(raw) > 512 or any(ord(ch) < 33 for ch in raw):
        return None
    # Both Gmail Message-ID and Graph internetMessageId are RFC identifiers.
    # The sender/subject guard in is_duplicate prevents accepting an ID alone.
    if "@" not in raw:
        return None
    return raw.casefold()


def _envelope(message: dict[str, Any]) -> tuple[str, str]:
    sender = parseaddr(str(message.get("sender") or ""))[1]
    return sender.strip().casefold(), _normalized(message.get("subject"))


def content_signature(message: dict[str, Any]) -> str | None:
    """High-confidence fallback if at least one provider lacks an Internet ID.

    Requires an identical substantive PLAIN body, sender, subject, and attachment
    metadata; no subject-only or fuzzy/AI grouping of different correspondence.
    """
    body = _normalized(message.get("body_text"))
    sender, subject = _envelope(message)
    if not sender or not subject or len(body) < 80 or received_epoch(message) is None:
        return None
    attachments: list[tuple[str, int]] = []
    for item in message.get("attachments") or []:
        name = _normalized(item.get("filename"))
        size = item.get("size_bytes")
        if not name or not isinstance(size, int) or size < 0:
            return None  # Incomplete attachment metadata is unsafe for fallback.
        attachments.append((name, size))
    return _hash([sender, subject, body, sorted(attachments)])


def message_key(message: dict[str, Any]) -> str | None:
    mid = internet_id(message)
    if not mid:
        return None
    return "mid:" + _hash([mid, *_envelope(message)])


def same_message(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Message-ID is authoritative. Fallback never overrides two distinct IDs."""
    left_sender, left_subject = _envelope(left)
    right_sender, right_subject = _envelope(right)
    if not left_sender or left_sender != right_sender or left_subject != right_subject:
        return False
    left_mid, right_mid = internet_id(left), internet_id(right)
    if left_mid and right_mid:
        return left_mid == right_mid
    left_sig = content_signature(left)
    right_sig = content_signature(right)
    left_time, right_time = received_epoch(left), received_epoch(right)
    if not left_sig or left_sig != right_sig or left_time is None or right_time is None:
        return False
    # Never merge two different provider messages from the same physical account
    # purely by body similarity. A sender may send the same template twice.
    if (left.get("source_owner_user_id"), left.get("account_id")) == (
        right.get("source_owner_user_id"), right.get("account_id")
    ):
        return False
    return abs(left_time - right_time) <= CONTENT_WINDOW_SECONDS


def collapse_for_view(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge ONLY the sources visible to the requesting user.

    All original source records remain intact; the representative source link
    always resolves back through the existing organization grant check.
    """
    groups: list[list[dict[str, Any]]] = []
    by_mid: dict[str, list[int]] = {}
    by_content: dict[str, list[int]] = {}
    for item in rows:
        row = dict(item)
        mid, sig = message_key(row), content_signature(row)
        candidates = list(by_mid.get(mid, [])) if mid else []
        # Both indexes are checked even when a different provider lacks a
        # Message-ID; same_message rejects conflicting Internet IDs.
        if sig:
            candidates += [i for i in by_content.get(sig, []) if i not in candidates]
        matching = next(
            (index for index in candidates
             if any(same_message(existing, row) for existing in groups[index])
             and not any(
                 internet_id(existing) and internet_id(row)
                 and internet_id(existing) != internet_id(row)
                 for existing in groups[index]
             )),
            None,
        )
        if matching is None:
            matching = len(groups)
            groups.append([])
        groups[matching].append(row)
        if mid:
            by_mid.setdefault(mid, [])
            if matching not in by_mid[mid]:
                by_mid[mid].append(matching)
        if sig:
            by_content.setdefault(sig, [])
            if matching not in by_content[sig]:
                by_content[sig].append(matching)

    merged: list[dict[str, Any]] = []
    for copies in groups:
        # Prefer a fully processed, important, content-rich source for opening.
        representative = max(copies, key=lambda m: (
            m.get("review_status") is not None,
            m.get("importance") == "high",
            len(str(m.get("body_text") or "")),
        ))
        sources: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for copy in copies:
            key = (str(copy.get("source_owner_user_id") or copy.get("user_id") or ""),
                   str(copy.get("provider") or ""), str(copy.get("account_id") or ""))
            if key in seen:
                continue
            seen.add(key)
            sources.append({
                "email_id": copy["email_id"],
                "owner_user_id": key[0], "provider": key[1],
                "account_id": key[2],
                "address": copy.get("source_account_address") or "",
                "unread": bool(copy.get("unread")),
            })
        merged.append({
            **representative,
            "unread": any(c.get("unread") for c in copies),
            "importance": ("high" if any(c.get("importance") == "high" for c in copies)
                           else representative.get("importance", "normal")),
            "source_accounts": sources,
            "source_count": len(sources),
            "copy_count": len(copies),
            "group_folders": sorted({str(c.get("smart_folder") or "other") for c in copies}),
            "group_classifications": sorted({str(c["classification"]) for c in copies if c.get("classification")}),
            "group_routes": sorted({str(c["route_to"]) for c in copies if c.get("route_to")}),
            "group_search_text": " ".join(
                str(part or "") for copy in copies for part in
                (copy.get("sender"), copy.get("subject"), copy.get("body_text"))
            )[:80_000].casefold(),
        })
    merged.sort(key=lambda item: (item.get("importance") == "high",
                                   item.get("received_at") or ""), reverse=True)
    return merged
