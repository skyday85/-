import mailbox
from email.message import EmailMessage

import pytest

from mail_contour.archive_import import parse_file
from mail_contour.mail_access import AccessDenied
from runtime import MainAgentRuntime


def letter(message_id="<request@example.test>"):
    msg = EmailMessage()
    msg["From"] = "Customer <customer@example.test>"
    msg["To"] = "orders@example.test"
    msg["Date"] = "Thu, 24 Sep 2026 10:00:00 +0300"
    msg["Message-ID"] = message_id
    msg["Subject"] = "Заявка на перевозку"
    msg.set_content("Прошу рассчитать доставку из Москвы в Санкт-Петербург.")
    msg.add_attachment(b"document-one", maintype="application",
                       subtype="pdf", filename="request.pdf")
    return msg


def test_parse_eml_and_mbox(tmp_path):
    msg = letter()
    eml = parse_file("one.eml", msg.as_bytes())
    assert len(eml) == 1
    assert eml[0]["sender"] == "customer@example.test"
    assert eml[0]["internet_message_id"] == "<request@example.test>"
    assert eml[0]["attachments"][0]["_binary"] == b"document-one"
    assert parse_file("again.eml", msg.as_bytes())[0]["provider_message_id"] == eml[0]["provider_message_id"]
    box = mailbox.mbox(str(tmp_path / "inbox.mbox"))
    box.add(msg)
    box.flush()
    box.close()
    assert len(parse_file("inbox.mbox", (tmp_path / "inbox.mbox").read_bytes())) == 1


def test_archive_parser_rejects_unsupported_or_oversized():
    with pytest.raises(ValueError):
        parse_file("hello.zip", b"not mail")
    with pytest.raises(ValueError):
        parse_file("letter.eml", b"")
    with pytest.raises(ValueError):
        parse_file("letter.eml", b"x" * (45 * 1024 * 1024 + 1))


def test_import_isolated_by_org_read_only_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_DATABASE_PATH", str(tmp_path / "state.sqlite3"))
    monkeypatch.setenv("APP_ORGANIZATION_ID", "one")
    monkeypatch.setenv("MAIL_BOOTSTRAP_OWNER_USER_ID", "boss")
    monkeypatch.setenv("MAIL_BOOTSTRAP_OWNER_EMAIL", "boss@example.test")
    monkeypatch.setenv("FLEET_API_BASE_URL", "http://127.0.0.1:3000")
    monkeypatch.setenv("FLEET_MAIN_AGENT_API_KEY", "test")
    runtime = MainAgentRuntime()
    d = runtime.mail_directory
    d.bootstrap_owner("other", "other-admin", "another@example.test")
    d.create_user("one", "boss", user_id="staff", email="staff@example.test",
                  display_name="Staff")
    original = letter().as_bytes()
    first = runtime.import_mail_archive("one", "boss", address="orders@example.test",
                                        filename="sample.eml", content=original)
    again = runtime.import_mail_archive("one", "boss", address="orders@example.test",
                                        filename="sample.eml", content=original)
    assert first["imported"] == 1 and first["auto_forward"] is False
    assert again["imported"] == 0 and again["already_present"] == 1
    assert runtime.visible_mailbox("other", "other-admin") == []
    assert runtime.visible_mailbox("one", "staff") == []
    d.grant_account("one", "boss", owner_user_id="boss", provider="archive",
                    account_id=first["account_id"], recipient_user_id="staff",
                    address="orders@example.test", can_forward=False)
    inbox = runtime.visible_mailbox("one", "staff")
    assert len(inbox) == 1
    assert inbox[0]["classification"] == "transport_request"
    assert inbox[0]["source_count"] == 1
    source = runtime._decode_scoped_mail_id(inbox[0]["email_id"])
    attachment = runtime.mail_persistence.archive_attachment(
        "one", "boss", source[1], "2")
    assert attachment["content_bytes"] == b"document-one"
    with pytest.raises(AccessDenied):
        runtime.visible_mail_message("other", "other-admin", inbox[0]["email_id"])
    # Imported letters must never trigger events or automatic forwarding.
    result = runtime.visible_process_mail("one", "staff", inbox[0]["email_id"])
    assert result["classification"] == "transport_request"
    assert runtime.integration_outbox.list_for_user("boss") == []


def test_two_imported_receiving_accounts_show_one_logical_email(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_DATABASE_PATH", str(tmp_path / "mail.sqlite3"))
    monkeypatch.setenv("APP_ORGANIZATION_ID", "company")
    monkeypatch.setenv("MAIL_BOOTSTRAP_OWNER_USER_ID", "boss")
    monkeypatch.setenv("MAIL_BOOTSTRAP_OWNER_EMAIL", "boss@example.test")
    monkeypatch.setenv("FLEET_API_BASE_URL", "http://127.0.0.1:3000")
    monkeypatch.setenv("FLEET_MAIN_AGENT_API_KEY", "test")
    runtime = MainAgentRuntime()
    for address in ("first@example.test", "second@example.test"):
        result = runtime.import_mail_archive(
            "company", "boss", address=address, filename="same.eml",
            content=letter().as_bytes())
        assert result["imported"] == 1
    one = runtime.visible_mailbox("company", "boss")
    assert len(one) == 1
    assert one[0]["source_count"] == 2
