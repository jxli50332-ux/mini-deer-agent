"""读取公开静态网页，并把主要正文整理为有界的结构化工具结果。"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
from html.parser import HTMLParser
from typing import Annotated
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from langchain_core.tools import StructuredTool


logger = logging.getLogger(__name__)

_FETCH_TIMEOUT_SECONDS = 10
_MAX_REDIRECTS = 5
_MAX_DOWNLOAD_BYTES = 1_000_000
_MAX_CONTENT_CHARACTERS = 12_000
_MAX_TITLE_CHARACTERS = 300
_MAX_URL_CHARACTERS = 2_048
_BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata.azure.internal",
}
_SUPPORTED_CONTENT_TYPES = {
    "application/xhtml+xml",
    "text/html",
    "text/plain",
}
_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
    "User-Agent": "MiniDeerAgent/0.1 (+public read-only web fetch)",
}
_BLOCKED_REMOTE_TAG_NAMES = {
    "analysis",
    "behavior",
    "confidentiality",
    "identity",
    "ignore",
    "important",
    "instruction",
    "override",
    "prompt",
    "system",
    "system-reminder",
    "system_reminder",
    "tool_policy",
}
_BLOCKED_REMOTE_TAG_PATTERN = re.compile(
    r"<\s*/?\s*(?:"
    + "|".join(re.escape(name) for name in sorted(_BLOCKED_REMOTE_TAG_NAMES))
    + r")\b[^>]*>?",
    re.IGNORECASE,
)
_REMOTE_BOUNDARY_PATTERN = re.compile(
    r"--- BEGIN USER INPUT ---|--- END USER INPUT ---"
)


def _resolve_host_addresses(hostname: str) -> tuple[str, ...]:
    """解析目标主机的全部地址，供每次服务端请求前执行 SSRF 筛选。"""
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return ()
    return tuple(dict.fromkeys(str(info[4][0]) for info in infos))


def _is_blocked_address(value: str) -> bool:
    """拒绝内网、回环、链路本地、元数据和其他不可公开路由的地址。"""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return True
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _validate_public_url(value: str) -> tuple[str | None, str | None]:
    """返回规范 URL；任何不安全或无法验证的目标都在创建 HTTP 客户端前失败关闭。"""
    normalized = value.strip()
    if len(normalized) > _MAX_URL_CHARACTERS:
        return None, "网页地址过长。"
    try:
        parsed = urlsplit(normalized)
        # 读取 port 会触发非法端口格式校验，不能把解析异常延后到 httpx。
        _ = parsed.port
    except ValueError:
        return None, "只支持包含有效主机名的 HTTP(S) URL。"

    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None, "只支持包含有效主机名的 HTTP(S) URL。"
    if parsed.username is not None or parsed.password is not None:
        return None, "该地址被网页读取安全策略拒绝。"

    hostname = parsed.hostname.strip().rstrip(".").lower()
    if (
        hostname in _BLOCKED_HOSTNAMES
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
    ):
        return None, "该地址被网页读取安全策略拒绝。"

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        addresses = _resolve_host_addresses(hostname)
        if not addresses:
            return None, "网页地址无法解析。"
    else:
        addresses = (str(literal),)

    if any(_is_blocked_address(address) for address in addresses):
        return None, "该地址被网页读取安全策略拒绝。"

    # 片段不会发送到服务器，移除它可让工具结果和最终引用保持确定。
    safe_url = urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path,
            parsed.query,
            "",
        )
    )
    return safe_url, None


def _create_http_client() -> httpx.Client:
    """创建不自动跟随重定向的同步客户端，使每个新目标都能重新执行安全检查。"""
    return httpx.Client(
        headers=_REQUEST_HEADERS,
        timeout=_FETCH_TIMEOUT_SECONDS,
        follow_redirects=False,
        trust_env=False,
    )


def _create_async_http_client() -> httpx.AsyncClient:
    """创建可被 Agent Run 取消的异步网页客户端。"""
    return httpx.AsyncClient(
        headers=_REQUEST_HEADERS,
        timeout=_FETCH_TIMEOUT_SECONDS,
        follow_redirects=False,
        trust_env=False,
    )


class _ArticleTextExtractor(HTMLParser):
    """使用标准库提取标题与可读文本，优先采用 main/article 中的正文。"""

    _BLOCK_TAGS = {
        "address",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
    }
    _IGNORED_TAGS = {
        "aside",
        "canvas",
        "footer",
        "form",
        "header",
        "nav",
        "noscript",
        "script",
        "style",
        "svg",
        "template",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._title_depth = 0
        self._head_depth = 0
        self._ignored_depth = 0
        self._primary_depth = 0
        self._title_parts: list[str] = []
        self._all_parts: list[str] = []
        self._primary_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """跟踪正文、标题和应丢弃的页面结构。"""
        del attrs
        normalized = tag.lower()
        if normalized == "head":
            self._head_depth += 1
        if normalized == "title":
            self._title_depth += 1
        if normalized in self._IGNORED_TAGS:
            self._ignored_depth += 1
        if normalized in {"main", "article"}:
            self._primary_depth += 1
        if normalized in self._BLOCK_TAGS:
            self._append_break()

    def handle_endtag(self, tag: str) -> None:
        """结束结构区域，并为块元素补充自然段边界。"""
        normalized = tag.lower()
        if normalized in self._BLOCK_TAGS:
            self._append_break()
        if normalized in {"main", "article"} and self._primary_depth > 0:
            self._primary_depth -= 1
        if normalized in self._IGNORED_TAGS and self._ignored_depth > 0:
            self._ignored_depth -= 1
        if normalized == "title" and self._title_depth > 0:
            self._title_depth -= 1
        if normalized == "head" and self._head_depth > 0:
            self._head_depth -= 1

    def handle_data(self, data: str) -> None:
        """标题单独保存；脚本、导航和 head 中的其他文本不进入正文。"""
        if self._title_depth > 0:
            self._title_parts.append(data)
            return
        if self._ignored_depth > 0 or self._head_depth > 0:
            return
        self._all_parts.append(data)
        if self._primary_depth > 0:
            self._primary_parts.append(data)

    def _append_break(self) -> None:
        """用换行标记块边界，最终统一压缩多余空白。"""
        if self._ignored_depth > 0 or self._head_depth > 0:
            return
        self._all_parts.append("\n")
        if self._primary_depth > 0:
            self._primary_parts.append("\n")

    @staticmethod
    def _normalize(parts: list[str]) -> str:
        """保留自然段，同时移除网页排版产生的重复空白。"""
        text = "".join(parts).replace("\xa0", " ")
        text = re.sub(r"[ \t\f\v]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    def article(self) -> tuple[str, str]:
        """返回规范标题和正文；存在 main/article 时优先避免外围噪音。"""
        title = self._normalize(self._title_parts)
        primary = self._normalize(self._primary_parts)
        content = primary or self._normalize(self._all_parts)
        return title, content


def _extract_page(
    body: str,
    *,
    content_type: str,
    url: str,
) -> tuple[str, str]:
    """从 HTML 或纯文本响应中提取标题与正文。"""
    if content_type == "text/plain":
        content = _neutralize_remote_content(_ArticleTextExtractor._normalize([body]))
        return urlsplit(url).hostname or url, content

    parser = _ArticleTextExtractor()
    parser.feed(body)
    parser.close()
    title, content = parser.article()
    return (
        title or (urlsplit(url).hostname or url),
        _neutralize_remote_content(content),
    )


def _neutralize_remote_content(content: str) -> str:
    """中和网页伪造的系统标签与输入边界，同时保留其可读文本证据。"""
    escaped = _BLOCKED_REMOTE_TAG_PATTERN.sub(
        lambda match: match.group(0).replace("<", "&lt;").replace(">", "&gt;"),
        content,
    )
    return _REMOTE_BOUNDARY_PATTERN.sub(
        lambda match: (
            "[BEGIN USER INPUT]"
            if match.group(0) == "--- BEGIN USER INPUT ---"
            else "[END USER INPUT]"
        ),
        escaped,
    )


def _render_result(
    requested_url: str,
    *,
    url: str | None = None,
    title: str = "",
    content: str = "",
    truncated: bool = False,
    error: str | None = None,
) -> str:
    """生成模型、前端和历史恢复共同使用的稳定 JSON 工具结果。"""
    bounded_requested_url = requested_url[:_MAX_URL_CHARACTERS]
    payload: dict[str, object] = {
        "requested_url": bounded_requested_url,
        "url": (url or bounded_requested_url)[:_MAX_URL_CHARACTERS],
        "title": title[:_MAX_TITLE_CHARACTERS],
        "content": content,
        "characters": len(content),
        "truncated": truncated,
    }
    if error is not None:
        payload["error"] = error
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _supported_content_type(response: httpx.Response) -> str | None:
    """只允许本功能能够安全转成正文的响应类型。"""
    raw = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not raw:
        # 少数静态站点遗漏 Content-Type；按 HTML 解析仍比直接拒绝更实用。
        return "text/html"
    return raw if raw in _SUPPORTED_CONTENT_TYPES else None


def _decode_body(response: httpx.Response, body: bytes) -> str:
    """按响应声明解码，错误字节使用替换符，避免整个 Run 因编码失败终止。"""
    encoding = response.encoding or "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _read_sync_response(
    client: httpx.Client,
    requested_url: str,
    initial_url: str,
) -> str:
    """同步读取网页，并在每一次重定向前重新验证目标。"""
    current_url = initial_url
    for redirect_count in range(_MAX_REDIRECTS + 1):
        with client.stream("GET", current_url) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location or redirect_count >= _MAX_REDIRECTS:
                    return _render_result(
                        requested_url,
                        url=current_url,
                        error="网页重定向次数过多或缺少目标地址。",
                    )
                target, error = _validate_public_url(urljoin(current_url, location))
                if error is not None or target is None:
                    return _render_result(
                        requested_url,
                        url=current_url,
                        error="该重定向目标被网页读取安全策略拒绝。",
                    )
                current_url = target
                continue

            if response.status_code >= 400:
                return _render_result(
                    requested_url,
                    url=current_url,
                    error=f"网页返回 HTTP {response.status_code}。",
                )
            content_type = _supported_content_type(response)
            if content_type is None:
                return _render_result(
                    requested_url,
                    url=current_url,
                    error="该地址不是可读取的 HTML 或纯文本网页。",
                )

            chunks: list[bytes] = []
            size = 0
            download_truncated = False
            for chunk in response.iter_bytes():
                remaining = _MAX_DOWNLOAD_BYTES - size
                if len(chunk) > remaining:
                    chunks.append(chunk[:remaining])
                    download_truncated = True
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size >= _MAX_DOWNLOAD_BYTES:
                    download_truncated = True
                    break

            title, extracted = _extract_page(
                _decode_body(response, b"".join(chunks)),
                content_type=content_type,
                url=current_url,
            )
            if not extracted:
                return _render_result(
                    requested_url,
                    url=current_url,
                    title=title,
                    error="网页没有可提取的正文。",
                )
            content_truncated = len(extracted) > _MAX_CONTENT_CHARACTERS
            content = extracted[:_MAX_CONTENT_CHARACTERS]
            return _render_result(
                requested_url,
                url=current_url,
                title=title[:_MAX_TITLE_CHARACTERS],
                content=content,
                truncated=download_truncated or content_truncated,
            )

    raise AssertionError("redirect loop must return within configured bound")


async def _read_async_response(
    client: httpx.AsyncClient,
    requested_url: str,
    initial_url: str,
) -> str:
    """异步读取网页；网络等待直接暴露取消点，不用线程包装 AsyncClient。"""
    current_url = initial_url
    for redirect_count in range(_MAX_REDIRECTS + 1):
        async with client.stream("GET", current_url) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location or redirect_count >= _MAX_REDIRECTS:
                    return _render_result(
                        requested_url,
                        url=current_url,
                        error="网页重定向次数过多或缺少目标地址。",
                    )
                target, error = await asyncio.to_thread(
                    _validate_public_url,
                    urljoin(current_url, location),
                )
                if error is not None or target is None:
                    return _render_result(
                        requested_url,
                        url=current_url,
                        error="该重定向目标被网页读取安全策略拒绝。",
                    )
                current_url = target
                continue

            if response.status_code >= 400:
                return _render_result(
                    requested_url,
                    url=current_url,
                    error=f"网页返回 HTTP {response.status_code}。",
                )
            content_type = _supported_content_type(response)
            if content_type is None:
                return _render_result(
                    requested_url,
                    url=current_url,
                    error="该地址不是可读取的 HTML 或纯文本网页。",
                )

            chunks: list[bytes] = []
            size = 0
            download_truncated = False
            async for chunk in response.aiter_bytes():
                remaining = _MAX_DOWNLOAD_BYTES - size
                if len(chunk) > remaining:
                    chunks.append(chunk[:remaining])
                    download_truncated = True
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size >= _MAX_DOWNLOAD_BYTES:
                    download_truncated = True
                    break

            body = _decode_body(response, b"".join(chunks))
            title, extracted = await asyncio.to_thread(
                _extract_page,
                body,
                content_type=content_type,
                url=current_url,
            )
            if not extracted:
                return _render_result(
                    requested_url,
                    url=current_url,
                    title=title,
                    error="网页没有可提取的正文。",
                )
            content_truncated = len(extracted) > _MAX_CONTENT_CHARACTERS
            content = extracted[:_MAX_CONTENT_CHARACTERS]
            return _render_result(
                requested_url,
                url=current_url,
                title=title[:_MAX_TITLE_CHARACTERS],
                content=content,
                truncated=download_truncated or content_truncated,
            )

    raise AssertionError("redirect loop must return within configured bound")


def _web_fetch(
    url: Annotated[str, "用户提供或 web_search 返回的精确 HTTP(S) URL"],
) -> str:
    """读取公开网页的正文；不支持登录页面、动态浏览器、PDF 或附件下载。"""
    requested_url = url.strip()[:_MAX_URL_CHARACTERS]
    safe_url, error = _validate_public_url(url)
    if error is not None or safe_url is None:
        return _render_result(requested_url, error=error or "网页地址无效。")

    try:
        with _create_http_client() as client:
            return _read_sync_response(client, requested_url, safe_url)
    except Exception as exc:
        # 日志只记录异常类型，不把 URL、页面或代理配置写入日志。
        logger.warning("网页读取失败：%s", type(exc).__name__)
        return _render_result(
            requested_url,
            url=safe_url,
            error="网页暂时无法读取，请稍后重试。",
        )


async def _web_fetch_async(
    url: Annotated[str, "用户提供或 web_search 返回的精确 HTTP(S) URL"],
) -> str:
    """异步读取公开网页，使网络等待可以响应 Agent Run 取消。"""
    requested_url = url.strip()[:_MAX_URL_CHARACTERS]
    safe_url, error = await asyncio.to_thread(_validate_public_url, url)
    if error is not None or safe_url is None:
        return _render_result(requested_url, error=error or "网页地址无效。")

    try:
        async with _create_async_http_client() as client:
            return await _read_async_response(client, requested_url, safe_url)
    except Exception as exc:
        logger.warning("网页读取失败：%s", type(exc).__name__)
        return _render_result(
            requested_url,
            url=safe_url,
            error="网页暂时无法读取，请稍后重试。",
        )


web_fetch = StructuredTool.from_function(
    func=_web_fetch,
    coroutine=_web_fetch_async,
    name="web_fetch",
    description=(
        "读取公开网页的正文，适合在 web_search 后深入了解某个精确来源；"
        "不支持登录页面、动态浏览器、PDF 或附件。"
    ),
)
