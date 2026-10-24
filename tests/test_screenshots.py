from claimlab.evidence.capture import ScreenshotCapturer, is_public_http_url
from claimlab.evidence.store import EvidenceImageStore


def test_public_url_guard_rejects_private_and_non_http():
    assert not is_public_http_url("http://127.0.0.1/x")
    assert not is_public_http_url("http://localhost/x")
    assert not is_public_http_url("file:///etc/passwd")
    assert not is_public_http_url("http://10.0.0.1/x")
    assert not is_public_http_url("ftp://example.com/x")
    assert is_public_http_url("https://example.com/x")


def test_image_store_roundtrip_and_expiry():
    store = EvidenceImageStore(ttl_seconds=60, max_runs=2)
    store.put("run-1", 1, b"abc", "image/jpeg")
    record = store.get("run-1", 1)
    assert record is not None and record.data == b"abc"
    assert store.get("run-1", 2) is None
    expired = EvidenceImageStore(ttl_seconds=-1)
    expired.put("run-2", 1, b"abc")
    assert expired.get("run-2", 1) is None


def test_capturer_disabled_is_a_noop(tmp_path):
    from claimlab.config import Settings

    settings = Settings(screenshot_enabled=False)
    capturer = ScreenshotCapturer(settings)
    assert capturer.enabled is False
    shot = __import__("asyncio").run(capturer.capture("https://example.com"))
    assert shot.error
    assert shot.data == b""
