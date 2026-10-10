import base64
import copy
import pytest
from kaist_login.gmail import extract_code, body_text


def mail(text="인증번호: 123456"):
    return {"internalDate": "1000000", "payload": {
        "mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()},
        "headers": [
            {"name": "From", "value": "KAIST <sso@kaist.ac.kr>"},
            {"name": "To", "value": "student@gmail.com"},
            {"name": "Subject", "value": "KAIST 로그인 인증번호"},
            {"name": "Authentication-Results", "value": "mx.google.com; dkim=pass header.i=@kaist.ac.kr; spf=pass"},
        ],
    }}


def extract(message, since=999):
    return extract_code(message, sender="sso@kaist.ac.kr", recipient="student@gmail.com",
                        subject_phrase="로그인 인증번호", since=since, now=1001)


def test_valid_otp():
    assert extract(mail()) == "123456"
    assert extract(mail("Your verification code: 654321")) == "654321"


@pytest.mark.parametrize("text", ["학번 123456", "인증번호: 1234567", "OTP: 123456 OTP: 654321", "OTP: 12345"])
def test_ambiguous_or_unlabeled_numbers_rejected(text):
    assert extract(mail(text)) is None


@pytest.mark.parametrize("header,value", [
    ("From", "sso@evil.test"), ("To", "someone@gmail.com"), ("Subject", "Other code"),
    ("Authentication-Results", "mx.google.com; dkim=fail header.i=@kaist.ac.kr"),
    ("Authentication-Results", "evil.test; dkim=pass header.i=@kaist.ac.kr"),
    ("Authentication-Results", "mx.google.com; dkim=pass header.i=@kaist.ac.kr.evil.test"),
])
def test_mail_identity_and_authentication_required(header, value):
    message = mail()
    for item in message["payload"]["headers"]:
        if item["name"] == header:
            item["value"] = value
    assert extract(message) is None


def test_old_mail_rejected():
    assert extract(mail(), since=1001) is None


def test_html_multipart_and_attachments():
    payload = mail()["payload"]
    payload["mimeType"] = "text/html"
    payload["body"]["data"] = base64.urlsafe_b64encode(b'<b>OTP:</b><span>123456</span><script>OTP: 999999</script>').decode()
    assert "999999" not in body_text(payload)
    attached = copy.deepcopy(payload)
    attached["filename"] = "attached.html"
    assert body_text(attached) == ""
