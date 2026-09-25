"""Manual .eml/.mbox imports into the existing, grant-scoped unified inbox.

This path intentionally performs NO forwarding and changes NO provider mailbox.
It is usable before online IMAP connectors are deployed.
"""
from __future__ import annotations

import mailbox
import os
import re
import tempfile
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

MAX_UPLOAD = 45 * 1024 * 1024
MAX_MESSAGES = 1_000
MAX_ATTACHMENT = 12 * 1024 * 1024
EMAIL_RE = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")


def mailbox_address(address: str) -> str:
    normalized = address.strip().lower()
    if len(normalized) > 254 or not EMAIL_RE.fullmatch(normalized):
        raise ValueError("Enter a valid receiving mailbox address")
    return normalized


def parse_file(filename: str, content: bytes):
    """Return normalized messages and original attachment bytes."""
    extension = Path(filename).suffix.lower()
    if extension not in {".eml", ".mbox"}:
        raise ValueError("Upload .eml or .mbox files only")
    if not content or len(content) > MAX_UPLOAD:
        raise ValueError("File is empty or exceeds the 45 MB import limit")
    parser = BytesParser(policy=policy.default)
    if extension == ".eml":
        originals = [parser.parsebytes(content)]
    else:
        # Python's mailbox reader needs a filesystem path. The temporary copy
        # is destroyed in finally, and its basename never comes from the user.
        with tempfile.TemporaryDirectory(prefix="mail-import-") as folder:
            name = os.path.join(folder, "source.mbox")
            with open(name, "wb") as handle:
                os.chmod(name, 0o600)
                handle.write(content)
            box = mailbox.mbox(name, create=False)
            try:
                originals = [parser.parsebytes(item.as_bytes())
                             for index, item in enumerate(box)
                             if index < MAX_MESSAGES]
            finally:
                box.close()
    imported = []
    for position, item in enumerate(originals[:MAX_MESSAGES]):
        attachments = []
        body_text, body_html = "", ""
        for part_no, part in enumerate(item.walk()):
            if part.is_multipart():
                continue
            name = part.get_filename()
            mime = part.get_content_type()
            if name or part.get_content_disposition() == "attachment":
                binary = part.get_payload(decode=True) or b""
                if len(binary) > MAX_ATTACHMENT:
                    continue
                attachments.append({
                    "attachment_id": str(part_no),
                    "filename": name or "attachment",
                    "mime_type": mime,
                    "size_bytes": len(binary),
                    "_binary": binary,
                })
            elif mime in {"text/plain", "text/html"}:
                try:
                    text = part.get_content()
                except (LookupError, UnicodeError, ValueError):
                    text = ""
                if not isinstance(text, str):
                    text = ""
                if mime == "text/plain" and not body_text:
                    body_text = text[:250_000]
                elif mime == "text/html" and not body_html:
                    body_html = text[:250_000]
        try:
            stamp = parsedate_to_datetime(str(item.get("Date") or ""))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            received_at = stamp.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError):
            received_at = datetime.now(timezone.utc).isoformat()
        imported.append({
            "provider_message_id": f"import:{position}",
            "internet_message_id": str(item.get("Message-ID") or "") or None,
            "sender": next((address for _, address in
                            getaddresses([str(item.get("From", ""))]) if address), ""),
            "recipients": [address for _, address in getaddresses(
                [str(item.get("To", "")), str(item.get("Cc", ""))]) if address],
            "subject": str(item.get("Subject") or "")[:1000],
            "received_at": received_at,
            "body_text": body_text,
            "body_html": body_html or None,
            "attachments": attachments,
        })
    return imported
