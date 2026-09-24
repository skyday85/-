from __future__ import annotations

import io
from itertools import islice
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Any


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def message_text(message: dict) -> str:
    body = message.get("body_text") or ""
    if not body and message.get("body_html"):
        parser = _PlainText()
        parser.feed(str(message["body_html"])[:200_000])
        body = " ".join(parser.parts)
    return (str(message.get("subject", "")) + "\n" + str(body))[:100_000]


def attachment_text(content: bytes, mime: str) -> tuple[str, str]:
    """Extract text from trusted MIME allowlist, bounded for resource safety.

    The OCR executable is optional; missing OCR/PDF dependencies are reported,
    never treated as evidence for an automatic routing decision.
    """
    if not content or len(content) > 10 * 1024 * 1024:
        return "", "size_unsupported"
    if mime == "application/pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return "", "pdf_extractor_unavailable"
        try:
            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted:
                return "", "encrypted_pdf"
            result: list[str] = []
            for page in islice(reader.pages, 5):
                result.append((page.extract_text() or "")[:15_000])
            text = "\n".join(result)[:50_000]
            if text.strip():
                return text, "extracted"
            if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
                return "", "scanned_pdf_needs_review"
            # Optional local development fallback; production should isolate the
            # PDF renderer and OCR executable in a resource-limited worker.
            with tempfile.TemporaryDirectory(prefix="mail-pdf-ocr-") as directory:
                source = Path(directory) / "source.pdf"
                source.write_bytes(content)
                render = subprocess.run(
                    [shutil.which("pdftoppm"), "-f", "1", "-l", "2", "-r", "100",
                     "-gray", "-png", str(source), str(Path(directory) / "page")],
                    capture_output=True, timeout=15, check=False
                )
                if render.returncode:
                    return "", "pdf_ocr_render_failed"
                words = []
                for image in sorted(Path(directory).glob("page-*.png"))[:2]:
                    if image.stat().st_size > 8 * 1024 * 1024:
                        return "", "pdf_ocr_page_too_large"
                    recognized = subprocess.run(
                        [shutil.which("tesseract"), str(image), "stdout", "-l", "rus+eng"],
                        capture_output=True, timeout=12, check=False
                    )
                    if recognized.returncode:
                        return "", "pdf_ocr_failed"
                    words.append(recognized.stdout.decode("utf-8", errors="replace")[:25_000])
                result = "\n".join(words)[:50_000]
                return result, "recognized" if result.strip() else "scanned_pdf_needs_review"
        except Exception:
            return "", "pdf_parse_failed"
    if mime in {"image/png", "image/jpeg", "image/webp"}:
        executable = shutil.which("tesseract")
        if not executable:
            return "", "ocr_unavailable"
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime]
        with tempfile.TemporaryDirectory(prefix="mail-ocr-") as directory:
            path = Path(directory) / ("attachment" + suffix)
            path.write_bytes(content)
            try:
                completed = subprocess.run([executable, str(path), "stdout", "-l", "rus+eng"],
                                           capture_output=True, timeout=12, check=False)
            except subprocess.TimeoutExpired:
                return "", "ocr_timeout"
            if completed.returncode:
                return "", "ocr_failed"
            text = completed.stdout.decode("utf-8", errors="replace")[:50_000]
            return text, "recognized" if text.strip() else "ocr_empty"
    if mime == "text/plain":
        return content.decode("utf-8", errors="replace")[:50_000], "extracted"
    return "", "mime_unsupported"


class MailTextRouter:
    """Generate reviewable forwarding candidates for administrator-owned rules."""

    def __init__(self, directory, fetch_attachment: Callable[[str, str, str], dict]):
        self.directory = directory
        self.fetch_attachment = fetch_attachment

    def inspect(self, *, organization_id: str, owner_user_id: str, message: dict,
                provider: str) -> dict[str, Any]:
        rules = self.directory.rules_for_account(organization_id, owner_user_id,
                                                  provider, str(message["account_id"]))
        if not rules:
            return {"jobs": [], "recognition": []}
        main_text = message_text(message).casefold()
        need_attachments = [r for r in rules if r["scan_attachments"] and
                            (r["match_text"] != "*" and r["match_text"] not in main_text)]
        attachments: list[dict] = []
        if need_attachments:
            for item in message.get("attachments", [])[:8]:
                mime = str(item.get("mime_type") or "").lower()
                if mime not in {"application/pdf", "image/png", "image/jpeg", "image/webp", "text/plain"}:
                    attachments.append({"name": item.get("filename"), "status": "mime_unsupported", "text": ""})
                    continue
                try:
                    result = self.fetch_attachment(owner_user_id, message["email_id"], item["attachment_id"])
                    extracted, status = attachment_text(result["content_bytes"], mime)
                except Exception:
                    extracted, status = "", "extraction_failed"
                attachments.append({"name": item.get("filename"), "status": status, "text": extracted.casefold()})
        jobs = []
        for rule in rules:
            term = rule["match_text"]
            matched_in = None
            if term == "*" or term in main_text:
                matched_in = "message"
            elif rule["scan_attachments"] and any(term in a["text"] for a in attachments):
                matched_in = "attachment"
            elif rule["scan_attachments"] and attachments and any(
                a["status"] not in {"extracted", "recognized", "ocr_empty", "mime_unsupported"}
                for a in attachments
            ):
                # A reviewer can inspect the actual attachment rather than
                # silently trusting unrecognized text; never auto-send here.
                matched_in = "unverified_attachment"
            if matched_in is None:
                continue
            job = self.directory.queue_job(rule=rule, email_id=str(message["email_id"]),
                                            matched_in=matched_in)
            jobs.append({"job_id": job["job_id"], "status": job["status"],
                         "matched_in": matched_in, "mode": rule["mode"],
                         "destination": rule["destination"]})
        return {"jobs": jobs, "recognition": [
            {"filename": a["name"], "status": a["status"]} for a in attachments
        ]}
