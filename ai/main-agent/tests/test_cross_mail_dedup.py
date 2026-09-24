"""Regression coverage: one logical email across assigned mailboxes, without deletion."""
from __future__ import annotations

from pathlib import Path

import pytest

from mail_contour.deduplication import collapse_for_view, content_signature
from mail_contour.mail_access import AccessDenied
from mail_contour.processing_dedup import MailProcessingDeduper

ORG = "org-one"
OTHER_ORG = "org-two"
BODY = ("The same signed transport request with complete route details was copied to "
        "both company mailboxes and should be represented once in the unified inbox.")


def copy(*, account: str, provider: str, email_id: str, message_id: str | None,
         owner: str = "boss", time: str = "2026-09-24T10:00:00Z",
         body: str = BODY, subject: str = "Transport request", unread: bool = True) -> dict:
    return {
        "email_id": email_id,
        "source_owner_user_id": owner,
        "provider": provider,
        "account_id": account,
        "source_account_address": account + "@example.com",
        "internet_message_id": message_id,
        "sender": "client@example.com",
        "subject": subject,
        "body_text": body,
        "received_at": time,
        "attachments": [],
        "unread": unread,
        "smart_folder": "important_requests",
        "importance": "normal",
    }


def test_internet_id_merges_gmail_outlook_even_with_different_body_representations():
    first = copy(account="a", provider="gmail", email_id="gmail-1",
                 message_id="<original-123@example.com>", body="Gmail full text", unread=False)
    second = copy(account="b", provider="outlook", email_id="outlook-1",
                  message_id="original-123@example.com", body="Outlook preview", unread=True)
    second["importance"] = "high"
    grouped = collapse_for_view([first, second])
    assert len(grouped) == 1
    assert grouped[0]["source_count"] == 2
    assert grouped[0]["unread"] is True
    assert grouped[0]["importance"] == "high"
    assert {source["address"] for source in grouped[0]["source_accounts"]} == {
        "a@example.com", "b@example.com",
    }


def test_distinct_identified_letters_are_not_collapsed_even_when_text_is_identical():
    first = copy(account="a", provider="gmail", email_id="g1",
                 message_id="<first@example.com>")
    second = copy(account="b", provider="outlook", email_id="o1",
                  message_id="<second@example.com>")
    assert len(collapse_for_view([first, second])) == 2


def test_missing_id_uses_strict_body_and_time_fallback_only_across_accounts():
    first = copy(account="a", provider="gmail", email_id="g1",
                 message_id="<first@example.com>")
    second = copy(account="b", provider="outlook", email_id="o1", message_id=None,
                  time="2026-09-24T10:01:00+00:00")
    assert content_signature(first) == content_signature(second)
    assert len(collapse_for_view([first, second])) == 1
    far = {**second, "received_at": "2026-09-24T10:05:00Z"}
    assert len(collapse_for_view([first, far])) == 2
    same_account = {**second, "account_id": "a", "provider": "gmail"}
    assert len(collapse_for_view([first, same_account])) == 2
    short = {**second, "body_text": "Short text"}
    assert len(collapse_for_view([first, short])) == 2


def test_unidentified_letter_does_not_bridge_two_distinct_message_ids():
    first = copy(account="a", provider="gmail", email_id="m1",
                 message_id="<first@example.com>")
    second = copy(account="b", provider="outlook", email_id="m2",
                  message_id="<second@example.com>")
    unknown = copy(account="c", provider="gmail", email_id="m3", message_id=None)
    assert len(collapse_for_view([first, second, unknown])) == 3


def test_missing_attachment_metadata_blocks_guesswork():
    first = copy(account="a", provider="gmail", email_id="m1", message_id=None)
    second = copy(account="b", provider="outlook", email_id="m2", message_id=None)
    first["attachments"] = [{"filename": "invoice.pdf", "size_bytes": None}]
    second["attachments"] = [{"filename": "invoice.pdf", "size_bytes": 100}]
    assert content_signature(first) is None
    assert len(collapse_for_view([first, second])) == 2


def test_processing_ledger_survives_restart_and_is_separate_per_organization(tmp_path: Path):
    path = str(tmp_path / "mail.sqlite3")
    ledger = MailProcessingDeduper(path)
    a = copy(account="a", provider="gmail", email_id="m1",
             message_id="<same@example.com>")
    b = copy(account="b", provider="outlook", email_id="m2",
             message_id="<same@example.com>")
    claimed = ledger.claim(ORG, "boss", a)
    assert claimed["claimed"] is True
    ledger.finish(ORG, claimed["processing_key"], success=True)
    restarted = MailProcessingDeduper(path)
    duplicate = restarted.claim(ORG, "other-owner", b)
    assert duplicate["claimed"] is False
    assert duplicate["state"] == "processed"
    assert duplicate["primary_email_id"] == "m1"
    assert restarted.claim(OTHER_ORG, "another-owner", b)["claimed"] is True


def test_processing_ledger_never_auto_retries_ambiguous_failure(tmp_path: Path):
    ledger = MailProcessingDeduper(str(tmp_path / "mail.sqlite3"))
    original = copy(account="a", provider="gmail", email_id="m1",
                    message_id="<same@example.com>")
    claim = ledger.claim(ORG, "boss", original)
    ledger.finish(ORG, claim["processing_key"], success=False, error="possible_delivery")
    duplicate = ledger.claim(ORG, "boss", original)
    assert duplicate["claimed"] is False
    assert duplicate["state"] == "needs_review"


def test_fallback_processing_only_when_other_account_and_not_two_distinct_ids(tmp_path: Path):
    ledger = MailProcessingDeduper(str(tmp_path / "mail.sqlite3"))
    first = copy(account="a", provider="gmail", email_id="m1",
                 message_id="<first@example.com>")
    other = copy(account="b", provider="outlook", email_id="m2",
                 message_id=None, time="2026-09-24T10:00:40Z")
    different = copy(account="c", provider="outlook", email_id="m3",
                     message_id="<different@example.com>")
    assert ledger.claim(ORG, "boss", first)["claimed"] is True
    assert ledger.claim(ORG, "boss", other)["claimed"] is False
    assert ledger.claim(ORG, "boss", different)["claimed"] is True


def test_runtime_collects_once_and_limits_sources_to_assigned_mailboxes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MAIL_DATABASE_PATH", str(tmp_path / "runtime.sqlite3"))
    monkeypatch.setenv("FLEET_API_BASE_URL", "http://127.0.0.1:3000")
    monkeypatch.setenv("FLEET_MAIN_AGENT_API_KEY", "development-fleet-key")
    monkeypatch.setenv("APP_ORGANIZATION_ID", ORG)
    monkeypatch.setenv("MAIL_BOOTSTRAP_OWNER_USER_ID", "boss")
    monkeypatch.setenv("MAIL_BOOTSTRAP_OWNER_EMAIL", "boss@example.com")
    monkeypatch.delenv("INTEGRATION_GATEWAY_BASE_URL", raising=False)

    from runtime import MainAgentRuntime

    runtime = MainAgentRuntime()
    directory = runtime.mail_directory
    directory.create_user(ORG, "boss", user_id="staff", email="staff@example.com",
                          display_name="Dispatcher")
    directory.create_user(ORG, "boss", user_id="other", email="other@example.com",
                          display_name="Other")
    runtime.add_mail_account(user_id="boss", account_id="sales", address="sales@example.com",
                             provider="gmail")
    runtime.add_mail_account(user_id="boss", account_id="office", address="office@example.com",
                             provider="outlook")
    for provider, account_id in (("gmail", "sales"), ("outlook", "office")):
        directory.grant_account(
            ORG, "boss", owner_user_id="boss", provider=provider, account_id=account_id,
            recipient_user_id="staff", address=account_id + "@example.com",
        )
    runtime.ingest_mail("boss", [
        {"email_id": "g-1", "account_id": "sales", "provider_message_id": "g-provider",
         "internet_message_id": "<shared-request@example.com>", "sender": "client@example.com",
         "subject": "Заявка на перевозку", "received_at": "2026-09-24T10:00:00Z",
         "body_text": BODY, "unread": False},
        {"email_id": "o-1", "account_id": "office", "provider_message_id": "o-provider",
         "internet_message_id": "<shared-request@example.com>", "sender": "client@example.com",
         "subject": "Заявка на перевозку", "received_at": "2026-09-24T10:00:20Z",
         "body_text": BODY, "unread": True},
    ])
    assert runtime.process_mail("boss", "g-1", organization_id=ORG)["duplicate_suppressed"] is False
    assert runtime.process_mail("boss", "o-1", organization_id=ORG)["duplicate_suppressed"] is True
    assert len(runtime.integration_outbox.list_for_user("boss")) == 1

    merged = runtime.visible_mailbox(ORG, "staff")
    assert len(merged) == 1
    assert merged[0]["source_count"] == 2
    assert merged[0]["unread"] is True
    assert len(runtime.visible_mailbox(ORG, "staff", unread_only=True)) == 1
    assert runtime.visible_mailbox(ORG, "other") == []
    with pytest.raises(AccessDenied):
        runtime.visible_mailbox(OTHER_ORG, "staff")

    source = runtime._source_account_id("boss", "gmail", "sales")
    selected = runtime.visible_mailbox(ORG, "staff", source_id=source)
    assert len(selected) == 1
    assert selected[0]["source_count"] == 1
    with pytest.raises(AccessDenied):
        runtime.visible_mailbox(ORG, "other", source_id=source)

    directory.revoke_account(ORG, "boss", owner_user_id="boss", provider="outlook",
                             account_id="office", recipient_user_id="staff")
    assert runtime.visible_mailbox(ORG, "staff")[0]["source_count"] == 1
    assert runtime.visible_mail_state(ORG, "staff")["accounts"][0]["source_id"] == source
