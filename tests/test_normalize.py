import json

from claimlab.search.normalize import normalize_api_response, normalize_page, parse_pages_field


def test_official_pages_string_array():
    inner = {
        "title": "人工智能创新加速我国产业转型升级",
        "url": "https://www.cac.gov.cn/2025-02/26/c_123.htm",
        "date": "2025/02/26 09:37:00",
        "passage": "人工智能创新加速我国产业转型升级",
        "content": "人工智能创新加速我国产业转型升级...",
        "site": "中国网信网",
        "score": 0.8488,
        "pics": [{"caption": "配图", "origin_url": "https://example.com/a.jpg"}],
    }
    payload = {
        "Response": {
            "Pages": [json.dumps(inner, ensure_ascii=False)],
            "Query": "人工智能发展现状",
            "Version": "standard",
            "RequestId": "req-1",
        }
    }
    batch = normalize_api_response(payload, "api", 12.0)
    assert batch.ok
    assert batch.version == "standard"
    assert batch.request_id == "req-1"
    assert len(batch.pages) == 1
    page = batch.pages[0]
    assert page.title.startswith("人工智能")
    assert page.domain == "cac.gov.cn"
    assert page.date == "2025-02-26"
    assert page.pics[0]["caption"] == "配图"
    assert page.strength == "full-ish"


def test_images_alias_and_double_encoded_string():
    inner = json.dumps({"title": "t", "url": "https://m.ctrip.com/x", "images": [{"caption": "c", "origin_url": "u"}]})
    doubly = json.dumps(inner)
    pages, warnings = parse_pages_field([doubly])
    assert len(pages) == 1
    page = normalize_page(pages[0])
    assert page.domain == "m.ctrip.com"
    assert page.pics[0]["caption"] == "c"
    assert warnings == []


def test_malformed_page_is_skipped():
    pages, warnings = parse_pages_field(["not json", {"title": "ok"}])
    assert len(pages) == 1
    assert warnings


def test_api_error_object():
    batch = normalize_api_response(
        {"Response": {"Error": {"Code": "UnauthorizedOperation", "Message": "bad key"}}},
        "api",
    )
    assert not batch.ok
    assert "UnauthorizedOperation" in (batch.error or "")
    assert batch.error_kind == "auth"


def test_api_unexpected_shape_is_server_error():
    batch = normalize_api_response(["not an object"], "api")
    assert not batch.ok
    assert batch.error_kind == "server"


def test_empty_pages_is_ok():
    batch = normalize_api_response({"Response": {"Pages": [], "Version": "standard"}})
    assert batch.ok
    assert batch.pages == []

