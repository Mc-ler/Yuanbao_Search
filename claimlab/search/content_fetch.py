"""Best-effort full-text fetch for public result URLs.

This is deliberately narrow: only SearchPro/A-B result pages, only public
http(s), bounded size/time, and failures are reported as errors. Callers must
keep the original snippet/passage and continue; a fetch must never abort a
research run.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

import httpx

from ..evidence.capture import is_public_http_url
from .normalize import strip_html

_IGNORED = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _IGNORED:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _IGNORED and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def parse_html_text(html: str) -> str:
    parser = _TextParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return strip_html(html)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return text


class ContentFetcher:
    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.enabled = bool(
            getattr(settings, "content_fetch_enabled", True)
            and getattr(settings, "search_provider", "") == "api"
            and not getattr(settings, "offline", False)
        )
        self.max_pages = max(0, int(getattr(settings, "content_fetch_max_pages", 3)))
        self.timeout = max(2, int(getattr(settings, "content_fetch_timeout_seconds", 8)))
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=5.0),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ConfirmingEverything/1.0)"},
        )

    async def fetch(self, url: str) -> tuple[str, str]:
        if not self.enabled:
            return "", "fetch_disabled"
        if not is_public_http_url(url):
            return "", "blocked_url"
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as exc:
            return "", f"transport:{type(exc).__name__}"
        if response.status_code >= 400:
            return "", f"HTTP {response.status_code}"
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type and "html" not in content_type:
            return "", "not_html"
        if len(response.content) > 1_000_000:
            return "", "too_large"
        text = parse_html_text(response.text)
        if len(text) < 200:
            return "", "too_short"
        return text[:20_000], ""

    async def close(self) -> None:
        await self._client.aclose()
