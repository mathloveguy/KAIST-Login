"""Gmail OAuth and narrowly filtered OTP extraction. Never return mail to MCP."""
from __future__ import annotations

import base64
import codecs
import json
import re
import time
from email.message import Message
from email.utils import getaddresses, parseaddr
from pathlib import Path
from html.parser import HTMLParser

from .errors import BrokerError

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
READ_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def requested_scopes(store, delete_otp_email=None):
    enabled = store.config().get("delete_otp_email", False) if delete_otp_email is None else delete_otp_email
    return SCOPES if enabled else READ_SCOPES


def scopes_sufficient(saved, scopes):
    granted = set(saved.get("scopes", []))
    return set(scopes).issubset(granted) or (scopes == READ_SCOPES and set(SCOPES).issubset(granted))


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.ignored = max(0, self.ignored - 1)

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def part_charset(payload: dict) -> str:
    # Gmail returns part bytes in their declared charset; Korean mail is often EUC-KR.
    header = Message()
    for item in payload.get("headers", []):
        if item.get("name", "").lower() == "content-type":
            header["Content-Type"] = item.get("value", "")
    charset = header.get_content_charset() or "utf-8"
    try:
        name = codecs.lookup(charset).name
    except LookupError:
        return "utf-8"
    # CP949 is a superset of EUC-KR and is what Korean senders actually emit.
    return "cp949" if name == "euc_kr" else name


def body_text(payload: dict) -> str:
    pieces = []
    # Do not download attachments or traverse embedded attached emails.
    if payload.get("filename"):
        return ""
    if payload.get("mimeType") in {"text/plain", "text/html"}:
        raw = payload.get("body", {}).get("data", "")
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode(part_charset(payload), "replace")
        if payload.get("mimeType") == "text/html":
            parser = PlainText()
            parser.feed(decoded)
            decoded = " ".join(parser.parts)
        pieces.append(decoded)
    for part in payload.get("parts", []):
        pieces.append(body_text(part))
    return "\n".join(pieces)


def extract_code(message: dict, *, sender: str, recipient: str,
                 subject_phrase: str, since: float, now: float) -> str | None:
    stamp = int(message.get("internalDate", 0)) / 1000
    if stamp < since or stamp > now + 30 or now - stamp > 300:
        return None
    payload = message.get("payload", {})
    headers = payload.get("headers", [])
    def values(name):
        return [h.get("value", "") for h in headers if h.get("name", "").lower() == name]
    from_headers = values("from")
    if len(from_headers) != 1 or parseaddr(from_headers[0])[1].lower() != sender.lower():
        return None
    recipients = {addr.lower() for _, addr in getaddresses(values("to") + values("delivered-to"))}
    if recipient.lower() not in recipients:
        return None
    if not subject_phrase or not any(subject_phrase.casefold() in s.casefold() for s in values("subject")):
        return None
    # Require Gmail's authentication result with aligned DKIM. Display From alone
    # does not authenticate an OTP sender. Forwarded mail may require manual MFA.
    domain = sender.rsplit("@", 1)[-1].lower()
    authenticated = False
    for result in values("authentication-results"):
        if not result.lower().lstrip().startswith("mx.google.com;"):
            continue
        for clause in result.lower().split(";"):
            match = re.search(r"dkim=pass\b.*?header\.(?:i|d)=@?([a-z0-9.-]+)", clause)
            if match and (domain == match[1] or domain.endswith("." + match[1])):
                authenticated = True
    if not authenticated:
        return None
    text = body_text(payload)
    # Anchor to the code label and reject ambiguity; never use an arbitrary number.
    # A short digit-free gap allows "인증번호는 [123456]" style phrasing.
    codes = set(re.findall(r"(?:인증\s*(?:번호|코드)|verification\s*code|one[- ]time\s*(?:password|code)|OTP)[^0-9\n]{0,12}?([0-9]{6})(?![0-9])", text, re.I))
    return next(iter(codes)) if len(codes) == 1 else None


def connect(store, client_file: str, delete_otp_email=None):
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise BrokerError("oauth_dependencies_required") from None

    email = store.config().get("external_email", "")
    if not email:
        raise BrokerError("external_email_required")
    config = json.loads(Path(client_file).read_text("utf-8"))
    installed = config.get("installed", {})
    if (installed.get("auth_uri") != "https://accounts.google.com/o/oauth2/auth"
            or installed.get("token_uri") != "https://oauth2.googleapis.com/token"):
        raise BrokerError("official_google_desktop_client_required")
    scopes = requested_scopes(store, delete_otp_email)
    flow = InstalledAppFlow.from_client_config(config, scopes, autogenerate_code_verifier=True)
    credentials = flow.run_local_server(
        host="127.0.0.1", port=0, open_browser=True, timeout_seconds=180,
        authorization_prompt_message="", success_message="Gmail 연결 확인 중입니다. 이 창을 닫아도 됩니다.",
        access_type="offline", prompt="consent", login_hint=email,
    )
    granted = credentials.granted_scopes or credentials.scopes or []
    if not scopes_sufficient({"scopes": granted}, scopes):
        raise BrokerError("gmail_reconnect_required")
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    if profile["emailAddress"].lower() != email.lower():
        raise BrokerError("gmail_account_mismatch")
    store.seal("gmail", json.loads(credentials.to_json()))
    config = store.config()
    config.update(gmail_backend="oauth", gmail_imap_connected=False)
    if delete_otp_email is not None:
        config["delete_otp_email"] = delete_otp_email
    store.save_config(config)
    store.delete_secret("gmail-imap-password")


class GmailOTP:
    def __init__(self, store):
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.exceptions import RefreshError
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError:
            raise BrokerError("oauth_dependencies_required") from None
        self.store = store
        saved = store.unseal("gmail")
        if not saved:
            raise BrokerError("gmail_not_connected")
        # Do not relabel an old readonly token with broader requested scopes.
        scopes = requested_scopes(store)
        if not scopes_sufficient(saved, scopes):
            raise BrokerError("gmail_reconnect_required")
        # Pin the destination even if stored data was generated by an older release.
        if saved.get("token_uri") != "https://oauth2.googleapis.com/token":
            raise BrokerError("invalid_oauth_destination")
        credentials = Credentials.from_authorized_user_info(saved, saved.get("scopes", scopes))
        if credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
            except RefreshError:
                # Revoked, or expired after 7 days in an OAuth app left in "Testing".
                raise BrokerError("gmail_reconnect_required") from None
            store.seal("gmail", json.loads(credentials.to_json()))
        self.service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        self._candidate_ids = set()

    def candidates(self, since: float, rule: dict) -> list[tuple[str, str]]:
        # Query syntax contains only locally validated sender and a numeric time.
        sender = rule["sender"]
        if not re.fullmatch(r"[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+", sender):
            raise BrokerError("invalid_otp_sender")
        ids = self.service.users().messages().list(
            userId="me", q=f"from:{sender} after:{int(since)}", maxResults=20,
        ).execute().get("messages", [])
        matches = []
        for entry in ids:
            message = self.service.users().messages().get(
                userId="me", id=entry["id"], format="full",
            ).execute()
            code = extract_code(message, sender=sender,
                                recipient=self.store.config()["external_email"],
                                subject_phrase=rule["subject_phrase"], since=since, now=time.time())
            if code:
                matches.append((entry["id"], code))
        self._candidate_ids = {message_id for message_id, _ in matches}
        return matches

    def trash_used(self, message_id: str):
        """Called internally only after successful SSO, never exposed as an MCP tool."""
        if self._candidate_ids != {message_id}:
            raise BrokerError("otp_message_not_selected")
        self.service.users().messages().trash(userId="me", id=message_id).execute()
        self._candidate_ids.clear()
