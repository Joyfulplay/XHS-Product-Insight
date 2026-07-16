from pathlib import Path
from types import SimpleNamespace

import pytest

from app.data.crawlers.xhs_client import (
    ApiRequestError,
    AuthRequiredError,
    BrowserNotFoundError,
    XiaohongshuScraper,
    translate_client_exception,
)


class FakeProfilePath:
    def __init__(self, parts=()):
        self.parts = tuple(parts)

    def __truediv__(self, child):
        return FakeProfilePath((*self.parts, child))

    def mkdir(self, **_kwargs):
        return None

    def __str__(self):
        return "/".join(self.parts) or "fake-profile"


def make_scraper(browser: str = "auto") -> XiaohongshuScraper:
    return XiaohongshuScraper(
        profile_dir=FakeProfilePath(("xhs-profile",)),
        max_candidates=50,
        max_notes=10,
        max_comments=20,
        min_note_likes=10,
        min_comment_likes=2,
        delay=1,
        headless=True,
        browser=browser,
    )


class FakeContext:
    def __init__(self, cookies=None, pages=None):
        self._cookies = cookies or []
        self.pages = pages or []
        self.closed = False

    def cookies(self, _url):
        return self._cookies

    def close(self):
        self.closed = True


class FakePage:
    def __init__(self, closed=False, url="about:blank", goto_error=None):
        self.closed = closed
        self.url = url
        self.goto_error = goto_error
        self.visited = []

    def goto(self, url, **kwargs):
        self.visited.append((url, kwargs))
        if self.goto_error:
            raise self.goto_error
        self.url = url

    def is_closed(self):
        return self.closed


class FakeChromium:
    def __init__(self, results):
        self.results = list(results)
        self.channels = []

    def launch_persistent_context(self, _profile, **kwargs):
        self.channels.append(kwargs["channel"])
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_auto_browser_prefers_edge():
    context = FakeContext()
    chromium = FakeChromium([context])

    launched, browser_name = make_scraper()._launch_system_browser(
        SimpleNamespace(chromium=chromium),
        headless=False,
    )

    assert launched is context
    assert browser_name == "edge"
    assert chromium.channels == ["msedge"]


def test_auto_browser_falls_back_to_chrome():
    context = FakeContext()
    chromium = FakeChromium([RuntimeError("edge missing"), context])

    launched, browser_name = make_scraper()._launch_system_browser(
        SimpleNamespace(chromium=chromium),
        headless=False,
    )

    assert launched is context
    assert browser_name == "chrome"
    assert chromium.channels == ["msedge", "chrome"]


def test_explicit_browser_does_not_fall_back():
    chromium = FakeChromium([RuntimeError("edge missing")])

    with pytest.raises(BrowserNotFoundError):
        make_scraper(browser="edge")._launch_system_browser(
            SimpleNamespace(chromium=chromium),
            headless=False,
        )

    assert chromium.channels == ["msedge"]


def test_browser_cookie_mapping_requires_complete_session():
    scraper = make_scraper()
    context = FakeContext(
        [
            {"name": "a1", "value": "a1-value"},
            {"name": "webId", "value": "web-id"},
            {"name": "web_session", "value": "session-value"},
            {"name": "empty", "value": ""},
        ]
    )

    cookies = scraper._browser_cookies(context)

    assert cookies == {
        "a1": "a1-value",
        "webId": "web-id",
        "web_session": "session-value",
    }
    assert scraper._has_required_login_cookies(cookies)
    assert not scraper._has_required_login_cookies({"a1": "a1-value"})


def test_guest_cookies_are_not_confirmed_login():
    guest_cookies = {
        "a1": "a1-value",
        "webId": "web-id",
        "web_session": "guest-session",
    }

    assert not XiaohongshuScraper._confirmed_login_state(
        guest_cookies,
        initial_session="",
        prompt_seen=True,
        prompt_visible=True,
        logged_in_marker=False,
    )
    assert not XiaohongshuScraper._confirmed_login_state(
        guest_cookies,
        initial_session="",
        prompt_seen=False,
        prompt_visible=False,
        logged_in_marker=False,
    )


def test_changed_session_and_closed_login_prompt_confirm_login():
    account_cookies = {
        "a1": "a1-value",
        "webId": "web-id",
        "web_session": "account-session",
    }

    assert XiaohongshuScraper._confirmed_login_state(
        account_cookies,
        initial_session="guest-session",
        prompt_seen=True,
        prompt_visible=False,
        logged_in_marker=False,
    )


def test_wait_for_login_detects_closed_browser():
    page = SimpleNamespace(is_closed=lambda: True)

    with pytest.raises(AuthRequiredError, match="浏览器已被关闭"):
        make_scraper()._wait_for_login_cookies(
            FakeContext(),
            page,
            timeout_seconds=1,
        )


def test_wait_for_login_times_out_with_missing_cookie_names():
    page = SimpleNamespace(is_closed=lambda: False)

    with pytest.raises(AuthRequiredError, match="a1, webId, web_session"):
        make_scraper()._wait_for_login_cookies(
            FakeContext(),
            page,
            timeout_seconds=0,
        )


def test_login_navigation_only_waits_for_commit():
    page = FakePage()

    XiaohongshuScraper._navigate_to_login(page)

    assert page.visited[0][0] == "https://www.xiaohongshu.com/login"
    assert page.visited[0][1]["wait_until"] == "commit"
    assert page.visited[0][1]["timeout"] == 20_000


def test_login_navigation_timeout_continues_on_xhs_page():
    page = FakePage(
        url="https://www.xiaohongshu.com/login",
        goto_error=RuntimeError("timeout"),
    )

    XiaohongshuScraper._navigate_to_login(page)


def test_login_navigation_failure_before_xhs_raises_error():
    page = FakePage(goto_error=RuntimeError("network error"))

    with pytest.raises(ApiRequestError, match="无法打开小红书登录页"):
        XiaohongshuScraper._navigate_to_login(page)


def test_login_saves_browser_cookies(monkeypatch):
    required = [
        {"name": "a1", "value": "a1-value"},
        {"name": "webId", "value": "web-id"},
        {"name": "web_session", "value": "session-value"},
    ]
    page = FakePage()
    context = FakeContext(required, pages=[page])
    chromium = FakeChromium([context])
    playwright = SimpleNamespace(chromium=chromium)

    class PlaywrightManager:
        def __enter__(self):
            return playwright

        def __exit__(self, *_args):
            return None

    saved = []
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: PlaywrightManager())
    monkeypatch.setattr("xhs_cli.cookies.save_cookies", lambda cookies: saved.append(cookies))
    monkeypatch.setattr("xhs_cli.cookies.get_cookie_path", lambda: Path("cookies.json"))

    scraper = make_scraper()
    monkeypatch.setattr(scraper, "_has_logged_in_marker", lambda _page: True)

    result = scraper.login()

    assert result == Path("cookies.json")
    assert saved == [
        {
            "a1": "a1-value",
            "webId": "web-id",
            "web_session": "session-value",
        }
    ]
    assert page.visited
    assert context.closed


def test_api_minus_104_maps_to_auth_required():
    class FakeApiError(Exception):
        code = -104
        response = {"code": -104, "msg": "account has no permission"}

    normalized = translate_client_exception(FakeApiError("API error"))

    assert isinstance(normalized, AuthRequiredError)
