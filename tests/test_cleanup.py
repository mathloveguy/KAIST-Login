from unittest.mock import MagicMock

import pytest

from kaist_login.errors import BrokerError
from kaist_login.gmail import GmailOTP


def test_trash_only_single_selected_message():
    client = GmailOTP.__new__(GmailOTP)
    client.service = MagicMock()
    client._candidate_ids = {"used-message"}
    client.trash_used("used-message")
    client.service.users().messages().trash.assert_called_once_with(userId="me", id="used-message")
    assert not client._candidate_ids


@pytest.mark.parametrize("ids", [set(), {"other"}, {"used-message", "other"}])
def test_cannot_trash_arbitrary_or_ambiguous_messages(ids):
    client = GmailOTP.__new__(GmailOTP)
    client.service = MagicMock()
    client._candidate_ids = ids
    with pytest.raises(BrokerError, match="otp_message_not_selected"):
        client.trash_used("used-message")
    client.service.users.assert_not_called()


def test_old_readonly_connection_requires_new_consent(store):
    store.set_mail_cleanup(True)
    store.seal("gmail", {"scopes": ["https://www.googleapis.com/auth/gmail.readonly"]})
    with pytest.raises(BrokerError, match="gmail_reconnect_required"):
        GmailOTP(store)


@pytest.mark.parametrize("login_success,cleanup_error,enabled", [(True, False, True), (True, True, True), (False, False, True), (True, False, False), (True, False, None)])
async def test_cleanup_only_after_verified_login(store, monkeypatch, login_success, cleanup_error, enabled):
    if enabled is not None:
        store.set_mail_cleanup(enabled)
    import kaist_login.browser as module
    client = MagicMock()
    if cleanup_error:
        client.trash_used.side_effect = RuntimeError("PRIVATE-service-error")
    checks = 0
    async def reach(*args):
        pass
    async def ready(*args):
        nonlocal checks
        checks += 1
        return login_success and checks >= 3
    async def submit(*args):
        pass
    async def mfa(*args):
        return module.PendingOTP(client, "used-message")
    async def save(*args):
        client.trash_used.assert_not_called()
    monkeypatch.setattr(module, "reach_sso", reach)
    monkeypatch.setattr(module, "is_ready", ready)
    monkeypatch.setattr(module, "submit_password", submit)
    monkeypatch.setattr(module, "run_mfa", mfa)
    monkeypatch.setattr(module, "save_session", save)
    if login_success:
        result = await module.authenticate(None, None, store, "klms", timeout=2)
        assert result.otp_cleanup == ("kept" if not enabled else "failed" if cleanup_error else "trashed")
        if enabled:
            client.trash_used.assert_called_once_with("used-message")
        else:
            client.trash_used.assert_not_called()
        assert not store.config()["login_blocked"]
    else:
        with pytest.raises(BrokerError, match="needs_user"):
            await module.authenticate(None, None, store, "klms", timeout=0.1)
        client.trash_used.assert_not_called()


def test_expired_refresh_token_requires_reconnect(store, monkeypatch):
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials
    store.seal("gmail", {"scopes": ["https://www.googleapis.com/auth/gmail.modify"],
                         "token_uri": "https://oauth2.googleapis.com/token",
                         "refresh_token": "FAKE", "client_id": "x", "client_secret": "y",
                         "token": "old", "expiry": "2000-01-01T00:00:00Z"})
    def refuse(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")
    monkeypatch.setattr(Credentials, "refresh", refuse)
    with pytest.raises(BrokerError, match="gmail_reconnect_required"):
        GmailOTP(store)


async def test_gmail_problem_stops_before_password_submission(store, monkeypatch):
    import kaist_login.browser as module
    store.save_account("fake-user", "FAKE-secret", "student@gmail.com")
    config = store.config()
    config["mfa"] = {"path": "/auth/mfa", "code": "#code", "verify": "#verify"}
    store.save_config(config)
    async def reach(*args):
        pass
    async def ready(*args):
        return False
    async def submit(*args):
        raise AssertionError("password must not be submitted")
    def broken_gmail(store):
        raise BrokerError("gmail_reconnect_required")
    monkeypatch.setattr(module, "reach_sso", reach)
    monkeypatch.setattr(module, "is_ready", ready)
    monkeypatch.setattr(module, "submit_password", submit)
    monkeypatch.setattr(module, "mailbox_client", broken_gmail)
    with pytest.raises(BrokerError, match="gmail_reconnect_required"):
        await module.authenticate(None, None, store, "klms", timeout=1)
    assert not store.config()["login_blocked"]
