from urllib.parse import unquote, urlsplit

from .errors import BrokerError

SITES = {"klms": "https://klms.kaist.ac.kr/", "dooray": "https://kaist.gov-dooray.com/"}
SSO_HOST = "sso.kaist.ac.kr"
SERVICE_HOSTS = {urlsplit(u).hostname for u in SITES.values()}
NAV_HOSTS = SERVICE_HOSTS | {SSO_HOST}


def host(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.port not in (None, 443) or "\\" in url
                or any(ord(c) < 32 for c in url)):
            return ""
        return parsed.hostname or ""
    except ValueError:
        return ""


def service_url(url: str) -> str:
    if host(url) not in SERVICE_HOSTS:
        raise BrokerError("url_not_allowed")
    # This broker is for information retrieval, not arbitrary authenticated GETs.
    lowered = unquote(url).lower()
    if any(word in lowered for word in (
        "logout", "signout", "sign-out", "delete", "remove", "unsubscribe",
        "sesskey=", "token=", "password=", "samlrequest", "samlresponse",
    )):
        raise BrokerError("sensitive_or_mutating_url")
    return url


def auth_url(url: str) -> bool:
    if host(url) == SSO_HOST:
        return True
    path = urlsplit(url).path.lower()
    return any(part in path for part in ("/login", "/auth/", "/idp/", "/signin"))


def safe_location(url: str) -> str:
    """Do not return SAML assertions, auth query parameters, or fragments."""
    parsed = urlsplit(url)
    return f"https://{host(url)}{parsed.path}" if host(url) else ""
