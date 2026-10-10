import json
import pytest

from kaist_login.errors import BrokerError
from kaist_login.policy import host, service_url, safe_location
from kaist_login.storage import Store


def test_secrets_and_sessions_never_plaintext_on_disk(store):
    store.save_account("student", "FAKE-password-9087", "student@gmail.com")
    state = {"cookies": [{"value": "FAKE-session-token"}], "origins": []}
    store.seal("session", state)
    store.seal("gmail", {"refresh_token": "FAKE-refresh-token"})
    assert store.unseal("session") == state
    disk = b"".join(p.read_bytes() for p in store.root.iterdir() if p.is_file())
    for secret in (b"FAKE-password-9087", b"FAKE-session-token", b"FAKE-refresh-token"):
        assert secret not in disk
        assert secret.decode() not in json.dumps(store.status())


def test_cipher_tampering_rejected(store):
    store.seal("session", {"cookies": []})
    path = store.root / "session.sealed"
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 1
    path.write_bytes(data)
    with pytest.raises(BrokerError, match="encrypted_state_unavailable"):
        store.unseal("session")


def test_missing_key_does_not_replace_existing_session(store):
    store.seal("session", {"cookies": []})
    store.delete_secret("encryption-key")
    with pytest.raises(BrokerError):
        store.unseal("session")
    assert store.secret("encryption-key") is None


def test_account_change_clears_session_and_mail_authorization(store):
    store.save_account("one", "FAKE-one", "one@gmail.com")
    store.seal("session", {"cookies": []})
    store.seal("gmail", {"token": "FAKE-token"})
    store.save_account("two", "FAKE-two", "two@gmail.com")
    assert store.unseal("session") is None
    assert store.unseal("gmail") is None


@pytest.mark.parametrize("url", [
    "http://sso.kaist.ac.kr/", "https://sso.kaist.ac.kr.evil.test/",
    "https://sso.kaist.ac.kr@evil.test/", "https://klms.kaist.ac.kr:444/",
    "file:///etc/passwd", "javascript:alert(1)", "https://klms.kaist.ac.kr\\@evil.test/",
    "https://klms.kaist.ac.kr/logout.php", "https://klms.kaist.ac.kr/?sesskey=SECRET",
    "https://klms.kaist.ac.kr/%64elete", "https://kaist.gov-dooray.com/?token=SECRET",
])
def test_untrusted_or_sensitive_destinations_rejected(url):
    with pytest.raises(BrokerError):
        service_url(url)


def test_only_explicit_https_service_hosts_accepted():
    assert service_url("https://klms.kaist.ac.kr/course/view.php?id=1")
    assert not host("https://evil.test:badport/")
    assert safe_location("https://sso.kaist.ac.kr/auth?SAMLResponse=SECRET#token") == "https://sso.kaist.ac.kr/auth"


async def test_boundary_never_returns_raw_exception():
    from kaist_login.server import call_safely
    async def operation():
        raise RuntimeError("fill('FAKE-secret-password')")
    assert await call_safely(operation) == {"status": "error", "code": "operation_failed"}


def test_forget_removes_all_secrets(store):
    store.save_account("one", "FAKE-one", "one@gmail.com")
    store.seal("gmail", {"token": "FAKE-token"})
    store.forget_all()
    assert store.backend.data == {}
    assert store.config() == {}
    assert store.unseal("gmail") is None


async def test_python_api_sanitizes_raw_browser_errors(store, monkeypatch):
    from contextlib import asynccontextmanager
    import traceback
    import kaist_login.browser as module
    @asynccontextmanager
    async def failing_session(*args, **kwargs):
        raise RuntimeError("fill('FAKE-password')")
        yield
    monkeypatch.setattr(module, "session", failing_session)
    with pytest.raises(BrokerError, match="operation_failed") as caught:
        await module.Broker(store).login("klms")
    assert "FAKE-password" not in "".join(traceback.format_exception(caught.value))
