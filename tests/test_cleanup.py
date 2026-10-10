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
    store.seal("gmail", {"scopes": ["https://www.googleapis.com/auth/gmail.readonly"]})
    with pytest.raises(BrokerError, match="gmail_reconnect_required"):
        GmailOTP(store)


@pytest.mark.parametrize("login_success,cleanup_error", [(True, False), (True, True), (False, False)])
async def test_cleanup_only_after_verified_login(store, monkeypatch, login_success, cleanup_error):
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
        assert result.otp_cleanup == ("failed" if cleanup_error else "trashed")
        client.trash_used.assert_called_once_with("used-message")
        assert not store.config()["login_blocked"]
    else:
        with pytest.raises(BrokerError, match="needs_user"):
            await module.authenticate(None, None, store, "klms", timeout=0.1)
        client.trash_used.assert_not_called()
