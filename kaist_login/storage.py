from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
from platformdirs import user_data_path

from .errors import BrokerError

SERVICE = "org.kaist-login.local.v1"


def native_keyring():
    # Instantiate the native backend explicitly. Never accept plaintext, null,
    # environment-selected, or third-party fallback backends.
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring
        return Keyring()
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring
        return WinVaultKeyring()
    raise BrokerError("unsupported_os")


def data_dir() -> Path:
    return user_data_path("KAISTLogin", appauthor=False, roaming=False)


def atomic_write(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        if os.name != "nt":
            path.chmod(0o600)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Store:
    def __init__(self, root: Path | None = None, backend=None):
        self.root = root if root is not None else data_dir()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.backend = backend if backend is not None else native_keyring()

    def config(self) -> dict:
        path = self.root / "config.json"
        return json.loads(path.read_text("utf-8")) if path.exists() else {}

    def save_config(self, config: dict):
        atomic_write(self.root / "config.json", json.dumps(config).encode())

    def secret(self, name: str) -> str | None:
        return self.backend.get_password(SERVICE, name)

    def set_secret(self, name: str, value: str):
        self.backend.set_password(SERVICE, name, value)

    def delete_secret(self, name: str):
        if self.secret(name) is not None:
            self.backend.delete_password(SERVICE, name)

    def _cipher(self, create=False) -> Fernet:
        key = self.secret("encryption-key")
        if not key and create:
            key = Fernet.generate_key().decode("ascii")
            self.set_secret("encryption-key", key)
        if not key:
            raise BrokerError("encryption_key_missing")
        return Fernet(key.encode("ascii"))

    def seal(self, name: str, value: dict):
        if name not in {"session", "gmail"}:
            raise BrokerError("invalid_store_name")
        encrypted = self._cipher(create=True).encrypt(json.dumps(value).encode())
        atomic_write(self.root / f"{name}.sealed", encrypted)

    def unseal(self, name: str) -> dict | None:
        if name not in {"session", "gmail"}:
            raise BrokerError("invalid_store_name")
        path = self.root / f"{name}.sealed"
        if not path.exists():
            return None
        try:
            return json.loads(self._cipher().decrypt(path.read_bytes()))
        except Exception:
            raise BrokerError("encrypted_state_unavailable") from None

    def forget_session(self):
        (self.root / "session.sealed").unlink(missing_ok=True)

    def save_account(self, username: str, password: str, email: str):
        if not username.strip() or not password:
            raise BrokerError("account_fields_required")
        old = self.config()
        self.set_secret("sso-password", password)
        self.forget_session()
        # Changing identities must not reuse the old mailbox authorization.
        if old.get("external_email") != email.strip():
            (self.root / "gmail.sealed").unlink(missing_ok=True)
        retained = old if old.get("username") == username.strip() else {}
        if old.get("external_email") != email.strip():
            retained.pop("mfa", None)
        retained.update(username=username.strip(), external_email=email.strip(), login_blocked=False)
        self.save_config(retained)

    def status(self) -> dict:
        config = self.config()
        return {"username": config.get("username"),
                "external_email": config.get("external_email"),
                "configured": bool(config.get("username")),
                "session_saved": (self.root / "session.sealed").exists(),
                "gmail_connected": (self.root / "gmail.sealed").exists()}

    def forget_all(self):
        for name in ("session.sealed", "gmail.sealed", "config.json"):
            (self.root / name).unlink(missing_ok=True)
        self.delete_secret("sso-password")
        self.delete_secret("encryption-key")
