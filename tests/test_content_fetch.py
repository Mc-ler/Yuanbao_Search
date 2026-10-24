import asyncio
from types import SimpleNamespace

from claimlab.search.content_fetch import ContentFetcher, parse_html_text


def test_parse_html_strips_scripts_and_navigation():
    html = "<html><nav>菜单</nav><script>bad()</script><main><p>西安城墙始建于明代。</p></main></html>"
    text = parse_html_text(html)
    assert "西安城墙始建于明代" in text
    assert "菜单" not in text
    assert "bad" not in text


def test_fetch_disabled_for_fake_provider():
    settings = SimpleNamespace(
        content_fetch_enabled=True,
        search_provider="fake",
        offline=False,
        content_fetch_max_pages=3,
        content_fetch_timeout_seconds=2,
    )
    fetcher = ContentFetcher(settings)
    try:
        text, error = asyncio.run(fetcher.fetch("https://example.com"))
        assert text == ""
        assert error == "fetch_disabled"
    finally:
        asyncio.run(fetcher.close())


def test_fetch_blocks_private_url():
    settings = SimpleNamespace(
        content_fetch_enabled=True,
        search_provider="api",
        offline=False,
        content_fetch_max_pages=3,
        content_fetch_timeout_seconds=2,
    )
    fetcher = ContentFetcher(settings)
    try:
        text, error = asyncio.run(fetcher.fetch("http://127.0.0.1:8000"))
        assert text == ""
        assert error == "blocked_url"
    finally:
        asyncio.run(fetcher.close())
