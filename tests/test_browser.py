import time
import pytest
from playwright.async_api import async_playwright

from kaist_login.browser import authenticate, read_content, submit_password, run_mfa
from kaist_login.errors import BrokerError


@pytest.fixture
async def browser_page():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        yield context, page
        await browser.close()


LOGIN = '''<a href="#loginTab02">ID/PW Login</a><input id="login_id">
<input id="login_pwd" type="password"><a href="javascript:loginProc();">Login</a>
<script>function loginProc(){ location.href='https://klms.kaist.ac.kr/my/'; }</script>'''


async def routes(context, fail=False):
    async def route(request_route):
        url = request_route.request.url
        if url == "https://klms.kaist.ac.kr/":
            html = '<a href="https://sso.kaist.ac.kr/auth/kaist/user/login/view">로그인</a>'
        elif "sso.kaist" in url:
            html = LOGIN if not fail else LOGIN.replace("location.href='https://klms.kaist.ac.kr/my/';", "return;")
        else:
            html = '<a href="/login/logout.php">Logout</a><main>Course information</main>'
        await request_route.fulfill(status=200, content_type="text/html", body=html)
    await context.route("**/*", route)


async def test_full_fake_login_saves_encrypted_state(browser_page, store):
    context, page = browser_page
    await routes(context)
    store.save_account("fake-user", "FAKE-secret", "")
    await authenticate(page, context, store, "klms", timeout=3)
    assert store.unseal("session") is not None
    assert not store.config()["login_blocked"]


async def test_failed_login_is_not_automatically_retried(browser_page, store):
    context, page = browser_page
    await routes(context, fail=True)
    store.save_account("fake-user", "FAKE-secret", "")
    with pytest.raises(BrokerError, match="needs_user"):
        await authenticate(page, context, store, "klms", timeout=1)
    assert store.config()["login_blocked"]
    with pytest.raises(BrokerError, match="login_requires_local_reset"):
        await submit_password(page, store, [])


async def test_read_hides_forms_scripts_and_secret_echo(browser_page):
    context, page = browser_page
    await context.route("**/*", lambda route: route.fulfill(content_type="text/html", body='''
      <p>Lesson 1</p><input value="FAKE-input"><form><p>FAKE-form</p></form>
      <script>const token="FAKE-token";</script><p>FAKE-secret</p><textarea>FAKE-area</textarea>
    '''))
    await page.goto("https://klms.kaist.ac.kr/course/view.php?id=1")
    result = await read_content(page, ["FAKE-secret"], 10000)
    assert "Lesson 1" in result["text"]
    assert "[REDACTED]" in result["text"]
    assert "FAKE" not in result["text"]


async def test_auth_page_never_readable(browser_page):
    context, page = browser_page
    await context.route("**/*", lambda route: route.fulfill(body="private"))
    await page.goto("https://sso.kaist.ac.kr/auth/kaist/user/login/view")
    with pytest.raises(BrokerError, match="authentication_page_not_readable"):
        await read_content(page, [], 1000)


async def test_password_not_filled_on_wrong_origin(browser_page, store):
    context, page = browser_page
    await context.route("**/*", lambda route: route.fulfill(body=LOGIN))
    await page.goto("https://evil.test/auth/kaist/user/login/view")
    with pytest.raises(BrokerError, match="unexpected_login_page"):
        await submit_password(page, store, [])
    assert await page.locator("#login_pwd").input_value() == ""


@pytest.mark.parametrize("ambiguous", [False, True])
async def test_otp_stays_internal_and_ambiguity_stops_submission(browser_page, store, monkeypatch, ambiguous):
    import kaist_login.browser as module
    context, page = browser_page
    await context.route("**/*", lambda route: route.fulfill(content_type="text/html", body='''
        <input id="code"><button id="verify" onclick="document.body.dataset.submitted='yes'">Verify</button>
    '''))
    await page.goto("https://sso.kaist.ac.kr/auth/test-mfa")
    store.save_config({"mfa": {"path": "/auth/test-mfa", "code": "#code", "verify": "#verify"}})
    class Mailbox:
        def __init__(self, store):
            pass
        def candidates(self, since, rule):
            return [("one", "123456"), ("two", "654321")] if ambiguous else [("one", "123456")]
    monkeypatch.setattr(module, "GmailOTP", Mailbox)
    redactions = []
    if ambiguous:
        with pytest.raises(BrokerError, match="ambiguous_otp"):
            await run_mfa(page, store, time.time(), time.monotonic() + 3, redactions)
        assert await page.locator("#code").input_value() == ""
    else:
        assert isinstance(await run_mfa(page, store, time.time(), time.monotonic() + 3, redactions), module.PendingOTP)
        assert redactions == ["123456"]
        assert await page.locator("body").get_attribute("data-submitted") == "yes"
