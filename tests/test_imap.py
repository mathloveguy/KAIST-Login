import imaplib
import ssl
import time
from contextlib import contextmanager
from email.message import EmailMessage
from unittest.mock import MagicMock

import pytest

import kaist_login.gmail_imap as module
from kaist_login.errors import BrokerError


def test_app_password_is_native_only_and_not_in_outputs(store):
    secret = "abcd efgh ijkl mnop"
    store.save_imap("student@gmail.com", secret)
    assert store.secret("gmail-imap-password") == "abcdefghijklmnop"
    assert store.status()["gmail_backend"] == "imap"
    assert not store.status()["delete_otp_email"]
    disk = b"".join(p.read_bytes() for p in store.root.iterdir() if p.is_file())
    assert b"abcdefghijklmnop" not in disk
    assert "abcdefghijklmnop" not in str(store.status())
    store.forget_all()
    assert store.secret("gmail-imap-password") is None


def test_changing_mail_account_drops_app_password(store):
    store.save_imap("one@gmail.com", "abcdefghijklmnop")
    store.save_account("student", "FAKE-sso", "two@gmail.com")
    assert store.secret("gmail-imap-password") is None
    assert not store.status()["gmail_connected"]


def test_imap_validates_tls_and_masks_auth_error(monkeypatch):
    connection = MagicMock()
    connection.login.side_effect = imaplib.IMAP4.error("FAKE-secret-auth-error")
    constructor = MagicMock(return_value=connection)
    monkeypatch.setattr(module.imaplib, "IMAP4_SSL", constructor)
    with pytest.raises(BrokerError, match="gmail_imap_auth_or_command_failed") as error:
        module.check_connection("student@gmail.com", "FAKE-secret")
    assert "FAKE-secret" not in str(error.value)
    args, kwargs = constructor.call_args
    assert args == ("imap.gmail.com", 993)
    assert kwargs["ssl_context"].verify_mode == ssl.CERT_REQUIRED
    assert kwargs["ssl_context"].check_hostname
    assert kwargs["timeout"] == 10
    connection.close.assert_not_called()
    connection.expunge.assert_not_called()
    connection.logout.assert_called_once()


@pytest.fixture
def client(store, monkeypatch):
    store.save_imap("student@gmail.com", "abcdefghijklmnop")
    monkeypatch.setattr(module, "check_connection", lambda *args: None)
    return module.IMAPGmailOTP(store)


def patch_mailbox(monkeypatch, connection):
    @contextmanager
    def mailbox(*args, **kwargs):
        yield connection
    monkeypatch.setattr(module, "mailbox", mailbox)


def test_fetch_peek_mime_charset_and_precise_time(client, monkeypatch):
    connection = MagicMock()
    connection.response.return_value = ("UIDVALIDITY", [b"100"])
    now = time.time()
    # Internaldate uses an English day-month-year time and an explicit zone.
    internal = time.strftime('%d-%b-%Y %H:%M:%S +0000', time.gmtime(now))
    raw = (f'From: KAIST <sso@kaist.ac.kr>\r\nTo: student@gmail.com\r\nSubject: KAIST OTP\r\n'
           'Authentication-Results: mx.google.com; dkim=pass header.i=@kaist.ac.kr\r\n'
           'Content-Type: text/plain; charset=EUC-KR\r\n\r\n').encode() + '인증번호는 [123456]'.encode('cp949')
    def uid(command, *args):
        if command == "SEARCH":
            return "OK", [b"1"]
        if args[-1] == "(RFC822.SIZE)":
            return "OK", [b"1 (RFC822.SIZE 400)"]
        assert args[-1] == "(INTERNALDATE X-GM-MSGID BODY.PEEK[])"
        return "OK", [(f'1 (UID 1 INTERNALDATE "{internal}" X-GM-MSGID 123 BODY[] {{400}}'.encode(), raw), b')']
    connection.uid.side_effect = uid
    patch_mailbox(monkeypatch, connection)
    rule = {"sender": "sso@kaist.ac.kr", "subject_phrase": "KAIST OTP"}
    assert client.candidates(now - 2, rule) == [("123", "123456")]
    assert client.candidates(now + 10, rule) == []
    connection.store.assert_not_called()


@pytest.mark.parametrize("changed", ["no", "uidvalidity", "message"])
def test_trash_rechecks_identity_and_never_expunge(client, monkeypatch, changed):
    client._selected = {"123": (b"1", b"100")}
    connection = MagicMock()
    connection.response.return_value = ("UIDVALIDITY", [b"200" if changed == "uidvalidity" else b"100"])
    def uid(command, *args):
        if command == "STORE":
            assert args == (b"1", "+X-GM-LABELS", r"(\Trash)")
            return "OK", [b"done"]
        if args[-1] == "(X-GM-MSGID)":
            return "OK", [b"1 (X-GM-MSGID 999)" if changed == "message" else b"1 (X-GM-MSGID 123)"]
        return "OK", [b'1 (X-GM-LABELS ("\\Trash"))']
    connection.uid.side_effect = uid
    patch_mailbox(monkeypatch, connection)
    if changed == "no":
        client.trash_used("123")
        assert not client._selected
    else:
        with pytest.raises(BrokerError):
            client.trash_used("123")
        assert not any(call.args[0] == "STORE" for call in connection.uid.call_args_list)
    connection.close.assert_not_called()
    connection.expunge.assert_not_called()


def test_attached_email_not_treated_as_otp():
    message = EmailMessage()
    message.set_content("Original plain body")
    attached = EmailMessage()
    attached.set_content("OTP: 999999")
    message.add_attachment(attached)
    from kaist_login.gmail import body_text
    assert "999999" not in body_text(module.payload_from_mime(message))


def test_default_imap_needs_no_google_packages(store, monkeypatch):
    import builtins
    import kaist_login.browser as browser
    store.save_imap("student@gmail.com", "abcdefghijklmnop")
    original = builtins.__import__
    def importing(name, *args, **kwargs):
        if name.startswith(("google.", "googleapiclient", "google_auth_oauthlib")):
            raise AssertionError("default IMAP must not use Google API dependencies")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", importing)
    monkeypatch.setattr(module, "check_connection", lambda *args: None)
    assert isinstance(browser.mailbox_client(store), module.IMAPGmailOTP)
