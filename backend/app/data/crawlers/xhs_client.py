"""小红书商品笔记单文件采集脚本。

主要流程：
1. 接收商品关键词、小红书链接，或淘宝/天猫商品链接。
2. 使用 xiaohongshu-cli 提供的签名接口搜索笔记、读取详情和一级评论。
3. 按点赞阈值筛选笔记和评论，并优先处理包含测评类关键词的候选。
4. 将结果写成一个 UTF-8 编码的结构化 JSON 文件。

关键词和小红书链接不会启动浏览器。只有输入淘宝/天猫链接且没有使用
``--query`` 指定搜索词时，才会临时启动 Playwright 读取商品标题。

首次使用前运行 ``python xhs_client.py --login``，通过系统 Edge/Chrome 扫码登录。
脚本只访问当前登录账号正常可见的公开内容，不尝试绕过验证码或平台限制。
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urljoin, urlparse


# ---------------------------------------------------------------------------
# 固定配置
# ---------------------------------------------------------------------------

XHS_HOME = "https://www.xiaohongshu.com"
SCHEMA_VERSION = "1.1"
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
SEARCH_PAGE_SIZE = 20
COMMENT_PAGE_LIMIT = 3
LOGIN_TIMEOUT_SECONDS = 300
LOGIN_URL = f"{XHS_HOME}/login"
REQUIRED_LOGIN_COOKIES = ("a1", "webId", "web_session")
BROWSER_CHANNELS = {
    "edge": "msedge",
    "chrome": "chrome",
}
XHS_NOTE_PATH = re.compile(r"/(?:explore|discovery/item|search_result)/([A-Za-z0-9]+)")
SUPPORTED_PRODUCT_HOSTS = ("taobao.com", "tmall.com")
PREFERRED_NOTE_KEYWORDS = (
    "测评",
    "使用体验",
    "长期使用",
    "优点",
    "缺点",
    "避雷",
    "降噪",
    "音质",
    "佩戴",
    "续航",
    "连接",
    "售后",
    "故障",
    "对比",
)


# ---------------------------------------------------------------------------
# 可识别的业务异常
# ---------------------------------------------------------------------------

class ScraperError(RuntimeError):
    """采集异常基类；code 会写入输出 JSON 的 errors 字段。"""

    code = "SCRAPER_ERROR"


class AuthRequiredError(ScraperError):
    """没有保存登录 Cookie，或者登录状态已经失效。"""

    code = "AUTH_REQUIRED"


class PlatformChallengeError(ScraperError):
    """平台要求安全验证，或当前 IP 受到访问限制。"""

    code = "PLATFORM_CHALLENGE"


class ClientSignatureError(ScraperError):
    """xiaohongshu-cli 的请求签名与当前平台接口不兼容。"""

    code = "SIGNATURE_ERROR"


class ApiRequestError(ScraperError):
    """接口返回了不能进一步分类的错误。"""

    code = "API_ERROR"


class BrowserNotFoundError(ScraperError):
    """系统中没有可由 Playwright 启动的 Edge 或 Chrome。"""

    code = "BROWSER_NOT_FOUND"


class UnsupportedInputError(ScraperError):
    """输入链接不在脚本支持范围内。"""

    code = "UNSUPPORTED_INPUT"


class ParseError(ScraperError):
    """接口或商品页面中没有解析出预期数据。"""

    code = "PARSE_ERROR"


# ---------------------------------------------------------------------------
# 通用数据处理函数
# ---------------------------------------------------------------------------

def now_iso() -> str:
    """返回带本地时区的 ISO 8601 时间。"""

    return datetime.now().astimezone().isoformat(timespec="seconds")


def clean_text(value: Any) -> str:
    """合并换行和连续空格，得到便于分析的单行文本。"""

    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def stable_hash(value: str, length: int = 32) -> str:
    """生成稳定的 SHA-256 摘要。"""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def author_hash(value: Any) -> str | None:
    """只保存作者标识的哈希，不把原始账号信息写入数据集。"""

    normalized = clean_text(value)
    return f"sha256:{stable_hash(normalized)}" if normalized else None


def parse_count(value: Any) -> int | None:
    """把“1.2万”“3k”等显示值转换为整数，无法识别时返回 None。"""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)

    text = clean_text(value).replace(",", "").lower()
    if not text or text in {"赞", "收藏", "评论", "分享", "-"}:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*([万千wk]?)", text)
    if not match:
        return None
    number = float(match.group(1))
    multiplier = {"万": 10_000, "w": 10_000, "千": 1_000, "k": 1_000}.get(
        match.group(2), 1
    )
    return int(number * multiplier)


def meets_like_threshold(value: Any, minimum: int) -> bool:
    """点赞数可解析且大于等于阈值时返回 True。"""

    count = parse_count(value)
    return count is not None and count >= minimum


def has_preferred_keyword(value: str) -> bool:
    """判断标题是否包含任意优先采集关键词。"""

    normalized = clean_text(value).casefold()
    return any(keyword.casefold() in normalized for keyword in PREFERRED_NOTE_KEYWORDS)


def prioritize_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """优先词命中项排在前面，各组内部保持原始搜索排名。"""

    return sorted(
        candidates,
        key=lambda item: (
            not has_preferred_keyword(item.get("title", "")),
            item.get("search_rank", 0),
        ),
    )


def first_value(mapping: Any, *keys: str) -> Any:
    """从字典中取得第一个存在且非空的字段值。"""

    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def as_bool(value: Any) -> bool:
    """兼容接口中的布尔值、0/1 和 true/false 字符串。"""

    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def format_publish_time(value: Any) -> str | None:
    """统一秒级/毫秒级时间戳；无法转换的页面文本原样保留。"""

    if value is None or value == "":
        return None

    numeric: float | None = None
    if isinstance(value, (int, float)):
        numeric = float(value)
    elif isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+)?", value.strip()):
        numeric = float(value.strip())

    if numeric is not None:
        if numeric > 10_000_000_000:
            numeric /= 1000
        try:
            return datetime.fromtimestamp(numeric).astimezone().isoformat(timespec="seconds")
        except (ValueError, OSError, OverflowError):
            pass
    return clean_text(value) or None


def note_id_from_url(url: str) -> str:
    """从小红书笔记 URL 中提取平台 ID。"""

    match = XHS_NOTE_PATH.search(urlparse(url).path)
    return match.group(1) if match else stable_hash(url, 20)


def canonical_note_url(note_id: str) -> str:
    """构造不包含 xsec_token 的规范笔记地址。"""

    return f"{XHS_HOME}/explore/{note_id}"


def note_reference_from_url(url: str) -> tuple[str, str, str]:
    """从笔记链接读取 note_id、xsec_token 和 xsec_source。"""

    note_id = note_id_from_url(url)
    query = parse_qs(urlparse(url).query)
    token = clean_text((query.get("xsec_token") or [""])[0])
    source = clean_text((query.get("xsec_source") or [""])[0])
    if not source:
        source = "pc_search" if "/search_result/" in urlparse(url).path else "pc_feed"
    return note_id, token, source


def classify_input(value: str) -> str:
    """判断输入是关键词、小红书链接，还是淘宝/天猫商品链接。"""

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return "keyword"

    host = parsed.netloc.lower().split(":", 1)[0]
    if host == "xhslink.com" or host.endswith(".xhslink.com"):
        return "xiaohongshu_url"
    if host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com"):
        if XHS_NOTE_PATH.search(parsed.path):
            return "xiaohongshu_note"
        if parsed.path.rstrip("/") == "/search_result":
            return "xiaohongshu_search"
        return "xiaohongshu_url"
    if any(host == domain or host.endswith(f".{domain}") for domain in SUPPORTED_PRODUCT_HOSTS):
        return "product_url"
    raise UnsupportedInputError("只支持商品关键词、小红书链接、淘宝链接和天猫链接")


def query_from_xhs_search_url(url: str) -> str:
    """从小红书搜索 URL 中读取关键词参数。"""

    query = parse_qs(urlparse(url).query)
    for key in ("keyword", "query", "q"):
        if query.get(key):
            return clean_text(unquote(query[key][0]))
    raise UnsupportedInputError("小红书搜索链接中没有找到 keyword 参数")


def clean_product_title(value: str) -> str:
    """去掉淘宝/天猫页面标题中的站点后缀。"""

    title = html.unescape(clean_text(value))
    for suffix in (
        "-淘宝网",
        "_淘宝网",
        "淘宝网 - 淘！我喜欢",
        "-天猫Tmall.com",
        "-理想生活上天猫",
        "天猫超市",
    ):
        if suffix in title:
            title = title.split(suffix, 1)[0]
    title = re.sub(r"^[【\[]?(?:淘宝|天猫)[】\]]?\s*", "", title)
    return clean_text(title.strip("-_| "))


def absolute_media_url(url: str, base_url: str) -> str:
    """补全 // 开头或相对形式的图片地址。"""

    if url.startswith("//"):
        return f"https:{url}"
    return urljoin(base_url, url)


def dedupe_urls(values: list[str], base_url: str) -> list[str]:
    """规范化并去重图片 URL，同时排除明显的头像和图标。"""

    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        url = absolute_media_url(clean_text(value), base_url)
        if not url or url.startswith("data:") or url in seen:
            continue
        if re.search(r"avatar|logo|icon|emoji", url, re.IGNORECASE):
            continue
        seen.add(url)
        output.append(url)
    return output


def translate_client_exception(exc: Exception) -> ScraperError:
    """把第三方客户端异常转换为本脚本稳定的错误码。"""

    if isinstance(exc, ScraperError):
        return exc
    name = type(exc).__name__
    message = clean_text(exc) or name
    response = getattr(exc, "response", None)
    error_code = getattr(exc, "code", None)
    if error_code is None and isinstance(response, dict):
        error_code = response.get("code")
    if str(error_code) == "-104" or "没有权限访问" in message or '"code": -104' in message:
        return AuthRequiredError("当前保存的是游客会话或登录已失效，请重新运行 --login")
    if name in {"NoCookieError", "SessionExpiredError"}:
        return AuthRequiredError("小红书登录状态不存在或已过期，请重新运行 --login")
    if name in {"NeedVerifyError", "IpBlockedError"}:
        return PlatformChallengeError(
            "小红书要求安全验证或限制了当前访问，脚本已停止且不会尝试绕过"
        )
    if name == "SignatureError":
        return ClientSignatureError(
            "接口签名已失效，请检查 xiaohongshu-cli 是否有兼容的新版本"
        )
    return ApiRequestError(message[:500])


def append_error(
    dataset: dict[str, Any],
    stage: str,
    exc: Exception,
    url: str | None = None,
) -> ScraperError:
    """向数据集追加格式统一的错误记录，并返回转换后的异常。"""

    normalized = translate_client_exception(exc)
    dataset["errors"].append(
        {
            "stage": stage,
            "code": normalized.code,
            "url": url,
            "message": clean_text(normalized)[:500],
        }
    )
    return normalized


def empty_dataset(
    source: str,
    input_type: str | None,
    resolved_query: str | None,
    max_candidates: int,
    max_notes: int,
    max_comments: int,
    min_note_likes: int,
    min_comment_likes: int,
) -> dict[str, Any]:
    """创建固定的输出骨架，确保成功和失败文件结构一致。"""

    return {
        "schema_version": SCHEMA_VERSION,
        "input": {
            "type": input_type,
            "value": source,
            "resolved_query": resolved_query,
        },
        "collected_at": None,
        "collection": {
            "candidate_limit": max_candidates,
            "note_limit": max_notes,
            "comments_per_note_limit": max_comments,
            "min_note_likes": min_note_likes,
            "min_comment_likes": min_comment_likes,
            "candidate_count": 0,
            "note_count": 0,
            "comment_count": 0,
        },
        "notes": [],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# 签名接口采集器
# ---------------------------------------------------------------------------

class XiaohongshuScraper:
    """使用一个 XhsClient 会话完成一轮搜索、详情和评论采集。"""

    def __init__(
        self,
        profile_dir: Path,
        max_candidates: int,
        max_notes: int,
        max_comments: int,
        min_note_likes: int,
        min_comment_likes: int,
        delay: float,
        headless: bool,
        browser: str = "auto",
    ) -> None:
        self.profile_dir = profile_dir
        self.max_candidates = max_candidates
        self.max_notes = max_notes
        self.max_comments = max_comments
        self.min_note_likes = min_note_likes
        self.min_comment_likes = min_comment_likes
        self.delay = max(1.0, delay)
        self.headless = headless
        self.browser = browser

    @staticmethod
    def _import_client_components() -> tuple[Any, Callable[[], Any], Callable[[], Path]]:
        """延迟导入依赖，让 --help 在依赖未安装时仍可正常显示。"""

        try:
            from xhs_cli.client import XhsClient
            from xhs_cli.cookies import get_cookie_path, load_saved_cookies
        except ImportError as exc:
            raise ScraperError(
                "缺少 xiaohongshu-cli。请运行：pip install xiaohongshu-cli==0.6.4"
            ) from exc
        return XhsClient, load_saved_cookies, get_cookie_path

    def login(self) -> Path:
        """使用系统 Edge/Chrome 扫码登录，并保存浏览器产生的 Cookie。"""

        try:
            from playwright.sync_api import sync_playwright
            from xhs_cli.cookies import get_cookie_path, save_cookies
        except ImportError as exc:
            raise ScraperError(
                "缺少 Playwright 或 xiaohongshu-cli，请先安装爬虫 requirements.txt"
            ) from exc

        with sync_playwright() as playwright:
            context, browser_name = self._launch_system_browser(playwright, headless=False)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                self._navigate_to_login(page)

                cookies = self._browser_cookies(context)
                login_prompt_visible = self._has_visible_login_prompt(page)
                already_logged_in = (
                    self._has_required_login_cookies(cookies)
                    and self._has_logged_in_marker(page)
                    and not login_prompt_visible
                )
                if not already_logged_in:
                    initial_session = cookies.get("web_session", "")
                    self._open_login_prompt(page)
                    print(
                        f"已打开系统 {browser_name.title()}，请使用小红书 App 扫码并在手机上确认登录。"
                    )
                    print("登录完成前请不要关闭浏览器，最长等待 5 分钟。")
                    cookies = self._wait_for_login_cookies(
                        context,
                        page,
                        timeout_seconds=LOGIN_TIMEOUT_SECONDS,
                        initial_session=initial_session,
                        prompt_seen=login_prompt_visible,
                    )
                else:
                    print(f"系统 {browser_name.title()} 的独立配置已经登录。")

                # save_cookies 会附加 saved_at；浏览器 Cookie 本身不包含本地元数据。
                save_cookies(cookies)
            finally:
                context.close()
        return get_cookie_path()

    @staticmethod
    def _navigate_to_login(page: Any) -> None:
        """进入专用登录页，只等待服务器开始响应，不等待全部前端资源。"""

        try:
            page.goto(LOGIN_URL, wait_until="commit", timeout=20_000)
        except Exception as exc:
            current_url = clean_text(getattr(page, "url", ""))
            parsed = urlparse(current_url)
            if parsed.netloc == "xiaohongshu.com" or parsed.netloc.endswith(".xiaohongshu.com"):
                print("小红书登录页加载较慢，已继续等待页面中的扫码登录。")
                return
            raise ApiRequestError(f"无法打开小红书登录页：{clean_text(exc)}") from exc

    def _browser_candidates(self) -> tuple[str, ...]:
        """返回浏览器尝试顺序；显式指定时不做其他回退。"""

        if self.browser == "auto":
            return ("edge", "chrome")
        return (self.browser,)

    def _launch_system_browser(self, playwright: Any, headless: bool) -> tuple[Any, str]:
        """启动系统 Edge/Chrome，并为每种浏览器使用独立资料目录。"""

        failures: list[str] = []
        for browser_name in self._browser_candidates():
            channel = BROWSER_CHANNELS[browser_name]
            browser_profile = self.profile_dir / browser_name
            browser_profile.mkdir(parents=True, exist_ok=True)
            try:
                context = playwright.chromium.launch_persistent_context(
                    str(browser_profile),
                    channel=channel,
                    headless=headless,
                    viewport={"width": 1440, "height": 1000},
                )
                print(f"正在使用系统 {browser_name.title()}。")
                return context, browser_name
            except Exception as exc:
                failures.append(f"{browser_name}: {clean_text(exc)[:160]}")

        requested = "Edge 或 Chrome" if self.browser == "auto" else self.browser.title()
        detail = "；".join(failures)
        raise BrowserNotFoundError(
            f"无法启动系统 {requested}。请确认浏览器已安装且配置目录未被占用。{detail}"
        )

    @staticmethod
    def _browser_cookies(context: Any) -> dict[str, str]:
        """从小红书域名读取 Cookie，并转换为 xiaohongshu-cli 所需字典。"""

        return {
            clean_text(cookie.get("name")): clean_text(cookie.get("value"))
            for cookie in context.cookies(XHS_HOME)
            if clean_text(cookie.get("name")) and clean_text(cookie.get("value"))
        }

    @staticmethod
    def _has_required_login_cookies(cookies: dict[str, str]) -> bool:
        """确认签名和登录所需的三个 Cookie 都已经产生。"""

        return all(cookies.get(name) for name in REQUIRED_LOGIN_COOKIES)

    @staticmethod
    def _has_visible_login_prompt(page: Any) -> bool:
        """检查登录弹窗、登录容器或可见登录按钮。"""

        try:
            for selector in (
                "[class*='login-container']",
                "[class*='login-modal']",
                "[class*='loginContainer']",
            ):
                locators = page.locator(selector)
                for index in range(locators.count()):
                    if locators.nth(index).is_visible():
                        return True

            buttons = page.get_by_role("button", name="登录", exact=True)
            return any(buttons.nth(index).is_visible() for index in range(buttons.count()))
        except Exception:
            return False

    @staticmethod
    def _has_logged_in_marker(page: Any) -> bool:
        """通过侧边栏当前账号的“我”入口确认页面已经进入登录态。"""

        try:
            links = page.locator("a[href*='/user/profile/']")
            for index in range(links.count()):
                link = links.nth(index)
                if link.is_visible() and clean_text(link.inner_text()) == "我":
                    return True
        except Exception:
            return False
        return False

    @staticmethod
    def _confirmed_login_state(
        cookies: dict[str, str],
        initial_session: str,
        prompt_seen: bool,
        prompt_visible: bool,
        logged_in_marker: bool,
    ) -> bool:
        """游客 Cookie 不算登录；必须看到会话变化和明确的页面状态变化。"""

        session = cookies.get("web_session", "")
        session_changed = bool(session and session != initial_session)
        page_confirmed = logged_in_marker or (prompt_seen and not prompt_visible)
        return (
            XiaohongshuScraper._has_required_login_cookies(cookies)
            and session_changed
            and page_confirmed
        )

    @staticmethod
    def _open_login_prompt(page: Any) -> bool:
        """搜索页没有自动弹出登录框时，点击第一个可见登录按钮。"""

        try:
            buttons = page.get_by_role("button", name="登录", exact=True)
            for index in range(buttons.count()):
                button = buttons.nth(index)
                if button.is_visible():
                    button.click()
                    return True
        except Exception:
            # 页面结构变化时仍允许用户在可见浏览器中手动点击登录。
            return False
        return False

    def _wait_for_login_cookies(
        self,
        context: Any,
        page: Any,
        timeout_seconds: float,
        initial_session: str = "",
        prompt_seen: bool = False,
    ) -> dict[str, str]:
        """等待真实账号登录，不能把字段齐全的游客 Cookie 当成成功。"""

        deadline = time.monotonic() + timeout_seconds
        last_cookies: dict[str, str] = {}
        while time.monotonic() < deadline:
            if page.is_closed():
                raise AuthRequiredError("登录完成前浏览器已被关闭")
            try:
                last_cookies = self._browser_cookies(context)
            except Exception as exc:
                if page.is_closed():
                    raise AuthRequiredError("登录完成前浏览器已被关闭") from exc
                raise ApiRequestError(f"读取浏览器 Cookie 失败：{clean_text(exc)}") from exc
            prompt_visible = self._has_visible_login_prompt(page)
            prompt_seen = prompt_seen or prompt_visible
            logged_in_marker = self._has_logged_in_marker(page)
            if self._confirmed_login_state(
                last_cookies,
                initial_session,
                prompt_seen,
                prompt_visible,
                logged_in_marker,
            ):
                # 给浏览器少量时间写完同一批响应 Cookie。
                time.sleep(1)
                final_cookies = self._browser_cookies(context)
                if self._confirmed_login_state(
                    final_cookies,
                    initial_session,
                    prompt_seen,
                    self._has_visible_login_prompt(page),
                    self._has_logged_in_marker(page),
                ):
                    return final_cookies
                last_cookies = final_cookies
            time.sleep(1)

        missing = [name for name in REQUIRED_LOGIN_COOKIES if not last_cookies.get(name)]
        if not missing:
            raise AuthRequiredError(
                "等待扫码登录超时：检测到游客 Cookie，但没有确认真实账号登录"
            )
        raise AuthRequiredError(
            f"等待扫码登录超时，缺少 Cookie：{', '.join(missing)}"
        )

    def _open_client(self) -> Any:
        """读取扫码保存的 Cookie，并创建本次采集共用的客户端。"""

        client_class, load_saved_cookies, _ = self._import_client_components()
        cookies = load_saved_cookies()
        if not cookies:
            raise AuthRequiredError("没有找到登录状态，请先运行：python xhs_client.py --login")

        # saved_at 是客户端的本地元数据，不应作为 Cookie 发给网站。
        normalized = {
            str(key): str(value)
            for key, value in cookies.items()
            if key != "saved_at" and value is not None
        }
        if not normalized.get("a1") or not normalized.get("web_session"):
            raise AuthRequiredError("保存的登录状态不完整，请重新运行 --login")
        return client_class(
            normalized,
            timeout=30.0,
            request_delay=self.delay,
            max_retries=3,
        )

    def collect(
        self,
        source: str,
        query_override: str | None = None,
        client: Any | None = None,
    ) -> dict[str, Any]:
        """执行一次完整采集；client 参数用于测试时注入内存假客户端。"""

        input_type = classify_input(source)
        resolved_query: str | None = None
        final_source = source

        # 小红书短链接先解析重定向，再按真实地址决定是笔记还是搜索。
        if input_type == "xiaohongshu_url":
            final_source = self._follow_redirect(source)
            input_type = classify_input(final_source)
            if input_type == "xiaohongshu_url":
                raise UnsupportedInputError("这个小红书链接不是笔记链接或搜索链接")

        if input_type == "keyword":
            resolved_query = query_override or clean_text(source)
        elif input_type == "xiaohongshu_search":
            resolved_query = query_override or query_from_xhs_search_url(final_source)
        elif input_type == "product_url":
            resolved_query = query_override or self._resolve_product_query(source)

        if input_type != "xiaohongshu_note" and not resolved_query:
            raise ParseError("没有获得可用于搜索小红书的商品关键词")

        dataset = empty_dataset(
            source,
            input_type,
            resolved_query,
            self.max_candidates,
            self.max_notes,
            self.max_comments,
            self.min_note_likes,
            self.min_comment_likes,
        )

        owns_client = client is None
        active_client = client or self._open_client()
        try:
            if input_type == "xiaohongshu_note":
                note_id, token, xsec_source = note_reference_from_url(final_source)
                candidate = {
                    "note_id": note_id,
                    "url": canonical_note_url(note_id),
                    "title": "",
                    "like_count": None,
                    "search_rank": None,
                    "xsec_token": token,
                    "xsec_source": xsec_source,
                }
                note, _ = self._collect_note(active_client, candidate, dataset, None)
                if note is not None:
                    dataset["notes"].append(note)
            else:
                self._collect_search(active_client, resolved_query or "", dataset)
        finally:
            dataset["collected_at"] = now_iso()
            dataset["collection"]["note_count"] = len(dataset["notes"])
            dataset["collection"]["comment_count"] = sum(
                len(note.get("comments", [])) for note in dataset["notes"]
            )
            if owns_client:
                active_client.close()
        return dataset

    def _follow_redirect(self, url: str) -> str:
        """使用普通 HTTP 客户端解析小红书短链接，不启动浏览器。"""

        try:
            import httpx

            with httpx.Client(follow_redirects=True, timeout=30.0) as http:
                response = http.get(
                    url,
                    headers={"user-agent": "Mozilla/5.0 Chrome/124 Safari/537.36"},
                )
                response.raise_for_status()
                return str(response.url)
        except Exception as exc:
            raise ApiRequestError(f"小红书短链接解析失败：{clean_text(exc)}") from exc

    def _resolve_product_query(self, url: str) -> str:
        """仅在输入淘宝/天猫链接时，用 Playwright 提取商品标题。"""

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ScraperError(
                "解析淘宝/天猫链接需要 Playwright；也可以使用 --query 直接指定关键词"
            ) from exc

        with sync_playwright() as playwright:
            context, _ = self._launch_system_browser(playwright, headless=self.headless)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                try:
                    page.wait_for_function(
                        """
                        () => {
                          const selectors = [
                            '[class*="ItemTitle"]', '[class*="itemTitle"]',
                            '[class*="mainTitle"]', 'h1', 'meta[property="og:title"]'
                          ];
                          return selectors.some((selector) => {
                            const node = document.querySelector(selector);
                            const value = node?.content || node?.innerText || node?.textContent;
                            return value && value.trim().length > 3;
                          });
                        }
                        """,
                        timeout=15_000,
                    )
                except Exception:
                    pass
                raw_title = page.evaluate(
                    """
                    () => {
                      const selectors = [
                        '[class*="ItemTitle"]', '[class*="itemTitle"]',
                        '[class*="mainTitle"]', 'h1', 'meta[property="og:title"]'
                      ];
                      for (const selector of selectors) {
                        const node = document.querySelector(selector);
                        const value = node?.content || node?.innerText || node?.textContent;
                        if (value && value.trim().length > 3) return value.trim();
                      }
                      return document.title || '';
                    }
                    """
                )
            finally:
                context.close()

        query = clean_product_title(raw_title)
        if not query or query in {"淘宝", "天猫", "登录", "页面不存在"}:
            raise ParseError("无法从商品页提取标题；可以使用 --query 手动指定商品关键词")
        print(f"从商品链接识别到关键词：{query}")
        return query

    @staticmethod
    def _api_call(action: Callable[[], Any]) -> Any:
        """执行一次接口调用，并稳定转换第三方异常。"""

        try:
            return action()
        except Exception as exc:
            raise translate_client_exception(exc) from exc

    def _search(self, client: Any, query: str) -> list[dict[str, Any]]:
        """分页读取搜索结果，按平台 ID 去重并保留原始排名。"""

        candidates: list[dict[str, Any]] = []
        seen_note_ids: set[str] = set()
        page = 1

        while len(candidates) < self.max_candidates:
            payload = self._api_call(
                lambda: client.search_notes(
                    query,
                    page=page,
                    page_size=SEARCH_PAGE_SIZE,
                )
            )
            if not isinstance(payload, dict):
                raise ParseError("搜索接口没有返回字典结构")

            items = payload.get("items") or []
            if not isinstance(items, list):
                raise ParseError("搜索接口的 items 字段不是列表")

            before = len(candidates)
            for item in items:
                if not isinstance(item, dict):
                    continue
                card = first_value(item, "note_card", "noteCard") or {}
                if not isinstance(card, dict):
                    card = {}
                note_id = clean_text(
                    first_value(item, "id", "note_id", "noteId")
                    or first_value(card, "note_id", "noteId", "id")
                )
                if not note_id or note_id in seen_note_ids:
                    continue

                interact = first_value(card, "interact_info", "interactInfo") or {}
                likes = parse_count(first_value(interact, "liked_count", "likedCount", "likes"))
                token = clean_text(
                    first_value(item, "xsec_token", "xsecToken")
                    or first_value(card, "xsec_token", "xsecToken")
                )
                source = clean_text(
                    first_value(item, "xsec_source", "xsecSource")
                    or first_value(card, "xsec_source", "xsecSource")
                    or "pc_search"
                )
                seen_note_ids.add(note_id)
                candidates.append(
                    {
                        "note_id": note_id,
                        "url": canonical_note_url(note_id),
                        "title": clean_text(first_value(card, "title", "display_title")),
                        "like_count": likes,
                        "search_rank": len(candidates) + 1,
                        "xsec_token": token,
                        "xsec_source": source,
                    }
                )
                if len(candidates) >= self.max_candidates:
                    break

            if len(candidates) >= self.max_candidates:
                break
            if not as_bool(payload.get("has_more")) or not items:
                break
            # 某一页全是重复或非笔记结果时继续下一页，但设置合理的总页数上限。
            if page >= max(3, (self.max_candidates + SEARCH_PAGE_SIZE - 1) // SEARCH_PAGE_SIZE + 2):
                break
            page += 1
            if len(candidates) == before and page > 3:
                break
        return candidates

    def _collect_search(
        self,
        client: Any,
        query: str,
        dataset: dict[str, Any],
    ) -> None:
        """持续处理候选，直到获得目标数量的有效笔记。"""

        candidates = self._search(client, query)
        dataset["collection"]["candidate_count"] = len(candidates)

        for candidate in prioritize_candidates(candidates):
            if len(dataset["notes"]) >= self.max_notes:
                break
            card_likes = candidate.get("like_count")
            if card_likes is not None and card_likes < self.min_note_likes:
                continue

            try:
                note, fatal_comment_error = self._collect_note(
                    client,
                    candidate,
                    dataset,
                    query,
                )
            except Exception as exc:
                normalized = append_error(
                    dataset,
                    "collect_note",
                    exc,
                    candidate["url"],
                )
                if isinstance(
                    normalized,
                    (AuthRequiredError, PlatformChallengeError, ClientSignatureError),
                ):
                    break
                continue

            if note is not None:
                dataset["notes"].append(note)
            if fatal_comment_error:
                break

    def _unwrap_note_payload(self, payload: Any) -> dict[str, Any]:
        """兼容 Feed items/note_card 和 HTML 直接笔记两种详情结构。"""

        if not isinstance(payload, dict):
            raise ParseError("笔记详情接口没有返回字典结构")
        items = payload.get("items")
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                card = first_value(first, "note_card", "noteCard")
                if isinstance(card, dict):
                    return card
                return first
        nested = first_value(payload, "note_card", "noteCard", "note")
        if isinstance(nested, dict):
            return nested
        return payload

    @staticmethod
    def _image_urls(raw: dict[str, Any], base_url: str) -> list[str]:
        """从不同版本的图片对象中提取正文图片地址。"""

        image_list = first_value(raw, "image_list", "imageList", "images") or []
        if not isinstance(image_list, list):
            return []
        values: list[str] = []
        for image in image_list:
            if isinstance(image, str):
                values.append(image)
                continue
            if not isinstance(image, dict):
                continue
            direct = first_value(
                image,
                "url_default",
                "urlDefault",
                "url_pre",
                "urlPre",
                "url",
            )
            if direct:
                values.append(clean_text(direct))
                continue
            info_list = first_value(
                image,
                "info_list",
                "infoList",
                "image_info_list",
                "imageInfoList",
            ) or []
            if isinstance(info_list, list):
                for info in info_list:
                    if isinstance(info, dict) and first_value(info, "url"):
                        values.append(clean_text(first_value(info, "url")))
                        break
        return dedupe_urls(values, base_url)

    @staticmethod
    def _tag_names(raw: dict[str, Any]) -> list[str]:
        """把标签对象列表转换为纯文本标签列表。"""

        tag_list = first_value(raw, "tag_list", "tagList", "tags") or []
        if not isinstance(tag_list, list):
            return []
        output: list[str] = []
        for tag in tag_list:
            value = first_value(tag, "name", "title") if isinstance(tag, dict) else tag
            text = clean_text(value).lstrip("#")
            if text and text not in output:
                output.append(text)
        return output

    def _normalize_note(
        self,
        payload: Any,
        candidate: dict[str, Any],
        search_query: str | None,
    ) -> dict[str, Any] | None:
        """将客户端详情结果映射为现有 JSON Schema 1.1。"""

        raw = self._unwrap_note_payload(payload)
        note_id = clean_text(
            first_value(raw, "note_id", "noteId", "id") or candidate["note_id"]
        )
        title = clean_text(first_value(raw, "title") or candidate.get("title"))
        body = clean_text(first_value(raw, "desc", "description", "text"))
        if not title and not body:
            raise ParseError("笔记详情中没有标题或正文")

        interact = first_value(raw, "interact_info", "interactInfo") or {}
        engagement = {
            "likes": parse_count(first_value(interact, "liked_count", "likedCount", "likes")),
            "favorites": parse_count(
                first_value(interact, "collected_count", "collectedCount", "favorites")
            ),
            "comments": parse_count(
                first_value(interact, "comment_count", "commentCount", "comments")
            ),
            "shares": parse_count(first_value(interact, "share_count", "shareCount", "shares")),
        }
        if not meets_like_threshold(engagement["likes"], self.min_note_likes):
            return None

        user = first_value(raw, "user", "author", "user_info", "userInfo") or {}
        author = (
            first_value(user, "user_id", "userId", "id", "nickname", "name", "red_id")
            if isinstance(user, dict)
            else user
        )
        url = canonical_note_url(note_id)
        return {
            "note_id": note_id,
            "url": url,
            "search_query": search_query,
            "search_rank": candidate.get("search_rank"),
            "title": title,
            "text": body,
            "tags": self._tag_names(raw),
            "publish_time": format_publish_time(
                first_value(raw, "time", "publish_time", "publishTime", "create_time", "createTime")
            ),
            "author_id_hash": author_hash(author),
            "engagement": engagement,
            "images": [
                {"position": index, "url": image_url}
                for index, image_url in enumerate(self._image_urls(raw, url))
            ],
            "comments": [],
        }

    def _collect_note(
        self,
        client: Any,
        candidate: dict[str, Any],
        dataset: dict[str, Any],
        search_query: str | None,
    ) -> tuple[dict[str, Any] | None, bool]:
        """读取详情；只有点赞达标后才请求评论。"""

        payload = self._api_call(
            lambda: client.get_note_detail(
                candidate["note_id"],
                xsec_token=candidate.get("xsec_token", ""),
                xsec_source=candidate.get("xsec_source", ""),
            )
        )
        note = self._normalize_note(payload, candidate, search_query)
        if note is None:
            return None, False

        try:
            note["comments"] = self._collect_comments(client, candidate)
            return note, False
        except Exception as exc:
            normalized = append_error(dataset, "collect_comments", exc, note["url"])
            fatal = isinstance(
                normalized,
                (AuthRequiredError, PlatformChallengeError, ClientSignatureError),
            )
            # 评论失败不能让已经成功取得的笔记正文丢失。
            note["comments"] = []
            return note, fatal

    def _collect_comments(
        self,
        client: Any,
        candidate: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """最多读取三页一级评论，达到保存上限后立即停止。"""

        if self.max_comments == 0:
            return []

        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursor = ""

        for _ in range(COMMENT_PAGE_LIMIT):
            payload = self._api_call(
                lambda current_cursor=cursor: client.get_comments(
                    candidate["note_id"],
                    cursor=current_cursor,
                    xsec_token=candidate.get("xsec_token", ""),
                    xsec_source=candidate.get("xsec_source", ""),
                )
            )
            if not isinstance(payload, dict):
                raise ParseError("评论接口没有返回字典结构")
            rows = payload.get("comments") or []
            if not isinstance(rows, list):
                raise ParseError("评论接口的 comments 字段不是列表")

            for row in rows:
                if not isinstance(row, dict):
                    continue
                text = clean_text(first_value(row, "content", "text"))
                if not text:
                    continue
                user = first_value(row, "user_info", "userInfo", "user", "author") or {}
                author = (
                    first_value(user, "user_id", "userId", "id", "nickname", "name", "red_id")
                    if isinstance(user, dict)
                    else user
                )
                identity = clean_text(first_value(row, "id", "comment_id", "commentId"))
                if not identity:
                    identity = stable_hash(f"{author}:{text}", 20)
                if identity in seen:
                    continue
                seen.add(identity)

                likes = parse_count(first_value(row, "like_count", "likeCount", "likes"))
                if not meets_like_threshold(likes, self.min_comment_likes):
                    continue
                output.append(
                    {
                        "comment_id": identity,
                        "text": text,
                        "author_id_hash": author_hash(author),
                        "likes": likes,
                        "publish_time": format_publish_time(
                            first_value(
                                row,
                                "create_time",
                                "createTime",
                                "publish_time",
                                "publishTime",
                                "time",
                            )
                        ),
                    }
                )
                if len(output) >= self.max_comments:
                    return output

            next_cursor = clean_text(payload.get("cursor"))
            if not as_bool(payload.get("has_more")) or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return output


# ---------------------------------------------------------------------------
# 命令行入口与 JSON 输出
# ---------------------------------------------------------------------------

def default_output_path() -> Path:
    """生成带时间戳的默认输出文件名，避免覆盖上一次结果。"""

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_RAW_DATA_DIR / f"xhs_dataset_{stamp}.json"


def write_dataset(path: Path, dataset: dict[str, Any]) -> None:
    """以 UTF-8 和缩进格式写出 JSON，中文不会转义成 Unicode 编码。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """定义命令行参数及中文帮助信息。"""

    parser = argparse.ArgumentParser(
        description="输入商品关键词或链接，通过签名接口采集小红书笔记并输出结构化 JSON",
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="商品关键词、小红书链接、淘宝链接或天猫链接",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="打开系统 Edge/Chrome，扫码登录小红书",
    )
    parser.add_argument(
        "--browser",
        choices=("auto", "edge", "chrome"),
        default="auto",
        help="登录和商品页解析使用的系统浏览器，默认 auto（Edge 后 Chrome）",
    )
    parser.add_argument("--query", help="为商品链接手动指定小红书搜索关键词")
    parser.add_argument("--output", type=Path, help="JSON 输出路径")
    parser.add_argument("--candidates", type=int, default=50, help="最多读取多少个候选，默认 50")
    parser.add_argument("--max-notes", type=int, default=10, help="最多保存多少篇有效笔记，默认 10")
    parser.add_argument(
        "--max-comments",
        type=int,
        default=20,
        help="每篇最多保存多少条点赞达标的一级评论，默认 20",
    )
    parser.add_argument(
        "--min-note-likes",
        type=int,
        default=10,
        help="只保留点赞数大于等于该值的笔记，默认 10",
    )
    parser.add_argument(
        "--min-comment-likes",
        type=int,
        default=2,
        help="只保留点赞数大于等于该值的评论，默认 2",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="签名接口请求的最小间隔秒数，最低且默认 1 秒",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path(".runtime/xhs-profile"),
        help="登录和解析淘宝/天猫商品页时使用的独立浏览器配置目录",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="仅解析淘宝/天猫商品页时让浏览器无界面运行",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """根据命令行参数执行登录或采集，并返回进程退出码。"""

    scraper = XiaohongshuScraper(
        profile_dir=args.profile_dir.resolve(),
        max_candidates=max(1, args.candidates),
        max_notes=max(1, args.max_notes),
        max_comments=max(0, args.max_comments),
        min_note_likes=max(0, args.min_note_likes),
        min_comment_likes=max(0, args.min_comment_likes),
        delay=args.delay,
        headless=args.headless,
        browser=args.browser,
    )

    if args.login:
        try:
            cookie_path = scraper.login()
        except Exception as exc:
            normalized = translate_client_exception(exc)
            print(f"登录失败 [{normalized.code}]：{normalized}", file=sys.stderr)
            return 1
        print(f"登录状态已保存到：{cookie_path}")
        return 0

    if not args.source:
        print("请提供商品关键词或链接；首次使用请先运行 --login", file=sys.stderr)
        return 2

    output = (args.output or default_output_path()).resolve()
    try:
        dataset = scraper.collect(args.source, query_override=args.query)
    except Exception as exc:
        normalized = translate_client_exception(exc)
        dataset = empty_dataset(
            args.source,
            None,
            args.query,
            scraper.max_candidates,
            scraper.max_notes,
            scraper.max_comments,
            scraper.min_note_likes,
            scraper.min_comment_likes,
        )
        dataset["collected_at"] = now_iso()
        dataset["errors"].append(
            {
                "stage": "crawl",
                "code": normalized.code,
                "url": args.source if args.source.startswith(("http://", "https://")) else None,
                "message": clean_text(normalized)[:500],
            }
        )
        write_dataset(output, dataset)
        print(
            f"采集失败 [{normalized.code}]，错误信息已写入：{output}",
            file=sys.stderr,
        )
        return 1

    write_dataset(output, dataset)
    counts = dataset["collection"]
    error_count = len(dataset["errors"])
    if counts["note_count"] == 0 and error_count:
        print(
            f"采集失败：读取 {counts['candidate_count']} 个候选，但没有获得有效笔记；"
            f"{error_count} 个错误已写入：{output}",
            file=sys.stderr,
        )
        return 1
    if dataset["input"]["type"] != "xiaohongshu_note" and counts["note_count"] < scraper.max_notes:
        print(
            f"候选已耗尽或不满足筛选条件，仅获得 "
            f"{counts['note_count']}/{scraper.max_notes} 篇有效笔记。"
        )
    print(
        f"采集完成：{counts['note_count']} 篇笔记，"
        f"{counts['comment_count']} 条一级评论，{error_count} 个失败。输出：{output}"
    )
    return 0


def main() -> None:
    """程序入口：处理 Windows 中文输出、解析参数并执行任务。"""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    try:
        exit_code = run(args)
    except KeyboardInterrupt:
        print("已停止。", file=sys.stderr)
        exit_code = 130
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
