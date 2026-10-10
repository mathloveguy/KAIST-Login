from __future__ import annotations

import asyncio
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

from filelock import FileLock, Timeout
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

from .errors import BrokerError, safe_errors
from .gmail import GmailOTP
from .policy import NAV_HOSTS, SITES, SSO_HOST, auth_url, host, safe_location, service_url
from .storage import Store


def mailbox_client(store):
    backend = store.config().get("gmail_backend")
    if backend == "oauth" or (backend is None and (store.root / "gmail.sealed").exists()):
        return GmailOTP(store)
    from .gmail_imap import IMAPGmailOTP
    return IMAPGmailOTP(store)


@dataclass(repr=False)
class PendingOTP:
    client: GmailOTP
    message_id: str


@dataclass(repr=False)
class AuthResult:
    redactions: list[str]
    otp_cleanup: str = "not_used"


@asynccontextmanager
async def session(store, *, headed=True):
    # Debug protocol logs can contain fill() arguments. Disable before driver spawn.
    for name in ("DEBUG", "PWDEBUG", "DEBUG_FILE", "PW_TEST_TRACE_DIR"):
        os.environ.pop(name, None)
    lock = FileLock(str(store.root / "broker.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        raise BrokerError("broker_busy") from None
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=not headed)
            try:
                state = store.unseal("session")
                context = await browser.new_context(
                    storage_state=state, accept_downloads=False, service_workers="block",
                )
                context.set_default_timeout(10000)

                async def guard(route):
                    request = route.request
                    # Cross-origin redirects cannot receive credentials or assertions.
                    if request.is_navigation_request() and host(request.url) not in NAV_HOSTS:
                        await route.abort()
                        return
                    try:
                        on_auth = auth_url(request.frame.url)
                    except Exception:
                        on_auth = True
                    if on_auth and host(request.url) not in NAV_HOSTS:
                        await route.abort()
                        return
                    await route.continue_()

                await context.route("**/*", guard)
                page = await context.new_page()
                # Suppress JS alert text at the tool boundary, keep dialogs from hanging.
                page.on("dialog", lambda dialog: dialog.dismiss())
                yield context, page
            finally:
                await browser.close()
    finally:
        lock.release()


async def is_ready(page, site, store=None):
    if host(page.url) != host(SITES[site]) or auth_url(page.url):
        return False
    if await page.locator('input[type="password"]:visible').count():
        return False
    marker = store.config().get("success", {}).get(site) if store else None
    if marker:
        element = page.locator(marker["selector"])
        if (await element.count() == 1 and await element.is_visible()
                and (await element.inner_text()).strip() == marker["text"]):
            return True
    # Positive UI evidence; a redirect alone is not evidence of authentication.
    if site == "klms":
        return bool(await page.locator('a[href*="/login/logout.php"]').count())
    return await page.get_by_role("button", name=re.compile(r"^(로그아웃|Log\s*out|Sign\s*out)$", re.I)).count() > 0 or await page.get_by_role("link", name=re.compile(r"^(로그아웃|Log\s*out|Sign\s*out)$", re.I)).count() > 0


async def click_unique(page, selector):
    if host(page.url) != SSO_HOST:
        raise BrokerError("unexpected_mfa_origin")
    locator = page.locator(selector)
    if await locator.count() != 1 or not await locator.is_visible():
        raise BrokerError("mfa_layout_changed")
    await locator.click()


async def run_mfa(page, store, started: float, deadline: float, redactions: list[str], client=None):
    rule = store.config().get("mfa")
    if not rule or host(page.url) != SSO_HOST:
        return False
    # The rule is learned locally, not supplied by an LLM or a webpage.
    if urlsplit(page.url).path != rule["path"]:
        return False
    client = client or await asyncio.to_thread(mailbox_client, store)
    if rule.get("choose_email"):
        await click_unique(page, rule["choose_email"])
    if rule.get("send"):
        started = time.time()
        await click_unique(page, rule["send"])
    while time.monotonic() < deadline:
        matches = await asyncio.to_thread(client.candidates, started, rule)
        if len(matches) > 1:
            raise BrokerError("ambiguous_otp")
        if matches:
            message_id, code = matches[0]
            if host(page.url) != SSO_HOST or urlsplit(page.url).path != rule["path"]:
                raise BrokerError("unexpected_mfa_origin")
            field = page.locator(rule["code"])
            if await field.count() != 1 or not await field.is_visible():
                raise BrokerError("mfa_layout_changed")
            redactions.append(code)
            await field.fill(code)
            await click_unique(page, rule["verify"])
            # One code submission only. Never retry failed or stale codes.
            return PendingOTP(client, message_id)
        await asyncio.sleep(2)
    raise BrokerError("otp_timeout")


async def reach_sso(page, site, store=None):
    await page.goto(SITES[site], wait_until="domcontentloaded")
    for _ in range(30):
        if host(page.url) == SSO_HOST or await is_ready(page, site, store):
            return
        if site == "klms":
            link = page.locator('a[href^="https://sso.kaist.ac.kr/auth/kaist/user/login/view"]')
            if await link.count() == 1:
                await link.click()
        else:
            button = page.get_by_role("button", name="교직원 / 재학생 / 졸업생", exact=True)
            if await button.count() == 1:
                await button.click()
        await asyncio.sleep(0.5)


async def submit_password(page, store, redactions):
    if host(page.url) != SSO_HOST or urlsplit(page.url).path != "/auth/kaist/user/login/view":
        raise BrokerError("unexpected_login_page")
    config = store.config()
    if config.get("login_blocked"):
        raise BrokerError("login_requires_local_reset")
    if time.time() - config.get("last_attempt", 0) < 60:
        raise BrokerError("login_cooldown")
    if not config.get("username"):
        raise BrokerError("setup_required")
    await page.locator('a[href="#loginTab02"]').click()
    if host(page.url) != SSO_HOST:
        raise BrokerError("unexpected_login_page")
    password = store.secret("sso-password")
    if not password:
        raise BrokerError("setup_required")
    redactions.append(password)
    config.update(last_attempt=time.time(), login_blocked=True)
    store.save_config(config)
    await page.locator("#login_id").fill(config["username"])
    await page.locator("#login_pwd").fill(password)
    if host(page.url) != SSO_HOST:
        raise BrokerError("unexpected_login_page")
    await page.locator('a[href="javascript:loginProc();"]').click()


async def authenticate(page, context, store, site, *, manual=False, timeout=150):
    redactions = []
    await reach_sso(page, site, store)
    deadline = time.monotonic() + timeout
    started = time.time()
    client = None
    if not await is_ready(page, site, store) and not manual:
        if store.config().get("mfa"):
            # Fail on an expired/revoked Gmail token before the one-shot password
            # submission, so a mailbox problem does not leave login_blocked set.
            client = await asyncio.to_thread(mailbox_client, store)
        await submit_password(page, store, redactions)
    mfa_done = False
    while time.monotonic() < deadline:
        if await is_ready(page, site, store):
            await save_session(context, store)
            config = store.config()
            config["login_blocked"] = False
            store.save_config(config)
            cleanup = "not_used"
            if isinstance(mfa_done, PendingOTP):
                cleanup = "kept"
                if store.config().get("delete_otp_email", False):
                    try:
                        await asyncio.to_thread(mfa_done.client.trash_used, mfa_done.message_id)
                        cleanup = "trashed"
                    except Exception:
                        # Authentication succeeded; never repeat it to retry cleanup.
                        cleanup = "failed"
            return AuthResult(redactions, cleanup)
        if not manual and not mfa_done:
            mfa_done = await run_mfa(page, store, started, deadline, redactions, client)
        # The user can complete MFA/CAPTCHA locally in the visible browser.
        await asyncio.sleep(0.5)
    raise BrokerError("needs_user_login_or_success_marker")


async def save_session(context, store):
    # Never serialize plaintext state to disk, screenshots, or a trace.
    store.seal("session", await context.storage_state(indexed_db=True))


async def read_content(page, redactions, limit):
    if host(page.url) not in {host(url) for url in SITES.values()} or auth_url(page.url):
        raise BrokerError("authentication_page_not_readable")
    if await page.locator('input[type="password"]:visible, input[autocomplete="one-time-code"]:visible').count():
        raise BrokerError("authentication_page_not_readable")
    # Extract text nodes only, never input values, HTML, scripts, headers or storage.
    result = await page.evaluate("""() => {
      const root = document.body;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const out = []; let node;
      while ((node = walker.nextNode())) {
        const p = node.parentElement;
        if (!p || p.closest('script,style,input,textarea,select,form,[hidden],[contenteditable]')) continue;
        if (!p.getClientRects().length) continue;
        const text = node.textContent.trim(); if (text) out.push(text);
      }
      return out.join('\\n');
    }""")
    for secret in redactions:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    return {"status": "ok", "location": safe_location(page.url),
            "text": result[:limit], "truncated": len(result) > limit}


class Broker:
    """Public Python interface. It never returns a Page, password, token or cookie."""

    def __init__(self, store=None):
        self.store = store if store is not None else Store()

    @safe_errors
    async def login(self, site: str, *, manual=False, timeout=150):
        if site not in SITES:
            raise BrokerError("unknown_site")
        async with session(self.store) as (context, page):
            result = await authenticate(page, context, self.store, site, manual=manual, timeout=timeout)
            return {"status": "authenticated", "site": site, "otp_cleanup": result.otp_cleanup}

    @safe_errors
    async def read(self, site: str, url: str | None = None, limit=20000):
        if site not in SITES:
            raise BrokerError("unknown_site")
        target = service_url(url or SITES[site])
        if host(target) != host(SITES[site]):
            raise BrokerError("site_url_mismatch")
        limit = max(1, min(limit, 50000))
        async with session(self.store) as (context, page):
            auth = await authenticate(page, context, self.store, site)
            secrets = auth.redactions
            # Redact even when an existing session avoided retrieving the password.
            password = self.store.secret("sso-password")
            if password:
                secrets.append(password)
            await page.goto(target, wait_until="domcontentloaded")
            try:
                # SPA pages such as Dooray render after XHR; allow a bounded settle time.
                await page.wait_for_load_state("networkidle", timeout=5000)
            except PlaywrightTimeoutError:
                pass
            result = await read_content(page, secrets, limit)
            result["otp_cleanup"] = auth.otp_cleanup
            await save_session(context, self.store)
            return result
