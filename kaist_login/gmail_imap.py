"""Gmail IMAP using an OS-stored app password; no Cloud project or OAuth token."""
from __future__ import annotations

import base64
import imaplib
import re
import ssl
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser

from .errors import BrokerError
from .gmail import extract_code

HOST = "imap.gmail.com"


def payload_from_mime(message):
    """Reuse the validated sender/recipient/DKIM/OTP parser for MIME messages."""
    payload = {"mimeType": message.get_content_type(),
               "filename": message.get_filename() or "",
               "headers": [{"name": key, "value": str(value)} for key, value in message.items()]}
    if message.get_content_type() == "message/rfc822":
        return payload
    if message.is_multipart():
        # Attached messages are not evidence for this email's authentication code.
        payload["parts"] = [payload_from_mime(part) for part in message.iter_parts()]
    else:
        payload["body"] = {"data": base64.urlsafe_b64encode(message.get_payload(decode=True) or b"").decode()}
    return payload


@contextmanager
def mailbox(email: str, app_password: str, *, readonly=True):
    connection = None
    try:
        connection = imaplib.IMAP4_SSL(HOST, 993, ssl_context=ssl.create_default_context(), timeout=10)
        connection.debug = 0
        connection.login(email, app_password)
        status, _ = connection.select("INBOX", readonly=readonly)
        if status != "OK":
            raise BrokerError("gmail_imap_inbox_unavailable")
        yield connection
    except BrokerError:
        raise
    except imaplib.IMAP4.error:
        raise BrokerError("gmail_imap_auth_or_command_failed") from None
    except (OSError, TimeoutError):
        raise BrokerError("gmail_imap_connection_failed") from None
    finally:
        if connection is not None:
            try:
                # LOGOUT only. CLOSE/EXPUNGE could permanently remove other mail.
                connection.logout()
            except Exception:
                pass


def check_connection(email: str, app_password: str):
    with mailbox(email, app_password):
        pass


def uidvalidity(connection):
    _, data = connection.response("UIDVALIDITY")
    if not data or not data[0] or not data[0].isdigit():
        raise BrokerError("gmail_imap_uidvalidity_missing")
    return data[0]


class IMAPGmailOTP:
    def __init__(self, store):
        self.store = store
        self.email = store.config().get("external_email", "")
        self.password = store.secret("gmail-imap-password")
        if not self.email or not self.password:
            raise BrokerError("gmail_imap_setup_required")
        self._selected = {}
        # Fail before any KAIST password is submitted if mailbox access is broken.
        check_connection(self.email, self.password)

    def candidates(self, since: float, rule: dict):
        sender = rule["sender"]
        if not re.fullmatch(r"[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+", sender):
            raise BrokerError("invalid_otp_sender")
        # IMAP SINCE is day-granular; extract_code enforces the exact timestamp.
        months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
        date = datetime.fromtimestamp(since - 86400, timezone.utc)
        day = f"{date.day:02d}-{months[date.month - 1]}-{date.year}"
        matches, selected = [], {}
        with mailbox(self.email, self.password) as connection:
            validity = uidvalidity(connection)
            status, data = connection.uid("SEARCH", None, "SINCE", day, "FROM", f'"{sender}"')
            if status != "OK":
                raise BrokerError("gmail_imap_search_failed")
            for uid in (data[0] or b"").split()[-20:]:
                if not uid.isdigit():
                    raise BrokerError("gmail_imap_invalid_uid")
                status, sizes = connection.uid("FETCH", uid, "(RFC822.SIZE)")
                if status != "OK":
                    continue
                size = re.search(rb"RFC822.SIZE (\d+)", b" ".join(x for x in sizes if isinstance(x, bytes)))
                if not size or int(size[1]) > 2_000_000:
                    continue
                status, fetched = connection.uid("FETCH", uid, "(INTERNALDATE X-GM-MSGID BODY.PEEK[])")
                if status != "OK":
                    continue
                literals = [item for item in fetched if isinstance(item, tuple)]
                if len(literals) != 1:
                    continue
                metadata, raw = literals[0]
                stamp = imaplib.Internaldate2tuple(metadata)
                identity = re.search(rb"X-GM-MSGID (\d+)", metadata)
                if stamp is None or identity is None:
                    continue
                mime = BytesParser(policy=policy.default).parsebytes(raw)
                message = {"internalDate": str(int(time.mktime(stamp) * 1000)),
                           "payload": payload_from_mime(mime)}
                code = extract_code(message, sender=sender, recipient=self.email,
                                    subject_phrase=rule["subject_phrase"], since=since, now=time.time())
                if code:
                    message_id = identity[1].decode("ascii")
                    matches.append((message_id, code))
                    selected[message_id] = (uid, validity)
        self._selected = selected
        return matches

    def trash_used(self, message_id: str):
        if set(self._selected) != {message_id}:
            raise BrokerError("otp_message_not_selected")
        uid, validity = self._selected[message_id]
        with mailbox(self.email, self.password, readonly=False) as connection:
            if uidvalidity(connection) != validity:
                raise BrokerError("gmail_imap_mailbox_changed")
            status, data = connection.uid("FETCH", uid, "(X-GM-MSGID)")
            identity = re.search(rb"X-GM-MSGID (\d+)", b" ".join(x for x in data if isinstance(x, bytes)))
            if status != "OK" or identity is None or identity[1].decode() != message_id:
                raise BrokerError("gmail_imap_message_changed")
            # Gmail's system Trash label moves this message to recoverable Trash.
            # Never use \Deleted, CLOSE, or EXPUNGE.
            status, _ = connection.uid("STORE", uid, "+X-GM-LABELS", r"(\Trash)")
            if status != "OK":
                raise BrokerError("gmail_imap_trash_failed")
            status, data = connection.uid("FETCH", uid, "(X-GM-LABELS)")
            labels = b" ".join(x for x in data if isinstance(x, bytes))
            if status != "OK" or not re.search(rb"\\Trash(?=[\s)\"])", labels):
                raise BrokerError("gmail_imap_trash_unconfirmed")
        self._selected.clear()
