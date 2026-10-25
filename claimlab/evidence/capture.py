"""Best-effort evidence screenshots via headless Chrome + CDP.

Only public http(s) URLs are allowed (SSRF guard). The page is opened in a
temporary headless Chrome profile, the snippet is highlighted/scrolled into
view when possible, and a JPEG viewport is returned. Any failure returns a
Screenshot with error set; callers must fall back to text metadata.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    import websockets
except Exception:  # pragma: no cover - optional dependency
    websockets = None  # type: ignore[assignment]

from ..search.normalize import strip_html

_WINDOWS_CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
_SNIPPET_RE = re.compile(r"\s+")


@dataclass
class Screenshot:
    url: str
    data: bytes = b""
    media_type: str = "image/jpeg"
    width: int = 0
    height: int = 0
    matched: bool = False
    error: str | None = None


def detect_chrome(explicit: str = "") -> str:
    if explicit and Path(explicit).exists():
        return explicit
    for name in ("chrome", "google-chrome", "chromium", "chromium-browser", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in _WINDOWS_CHROME:
        if Path(candidate).exists():
            return candidate
    return ""


def _is_private_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def is_public_http_url(url: str) -> bool:
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return False
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return False
    if parts.username or parts.password:
        return False
    host = parts.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return False
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError:
        return False
    if not infos:
        return False
    return all(not _is_private_address(info[4][0]) for info in infos)


def _clean_snippet(snippet: str) -> str:
    text = strip_html(snippet or "")
    return _SNIPPET_RE.sub(" ", text).strip()[:80]


class _CDP:
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self._next = 0

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next += 1
        request_id = self._next
        await self.connection.send(
            json.dumps({"id": request_id, "method": method, "params": params or {}})
        )
        while True:
            raw = await self.connection.recv()
            message = json.loads(raw)
            if message.get("id") != request_id:
                continue
            if message.get("error"):
                raise RuntimeError(str(message["error"]))
            return message.get("result", {})


class ScreenshotCapturer:
    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.chrome = detect_chrome(settings.screenshot_chrome)
        self.enabled = bool(
            getattr(settings, "screenshot_enabled", False)
            and self.chrome
            and websockets is not None
        )
        self.reason = (
            ""
            if self.enabled
            else (
                "EVIDENCE_SCREENSHOTS disabled"
                if not getattr(settings, "screenshot_enabled", False)
                else "Chrome not found"
                if not self.chrome
                else "websockets not installed"
            )
        )
        # Shared across all research requests in this process. Without this,
        # repeated UI calls can spawn several Chrome instances at once and
        # exhaust the desktop session.
        self._gate = asyncio.Semaphore(2)
        self.last_error = ""

    async def capture(self, url: str, snippet: str = "", timeout_ms: int | None = None) -> Screenshot:
        if not self.enabled:
            return Screenshot(url=url, error=self.reason or "screenshots disabled")
        if not is_public_http_url(url):
            return Screenshot(url=url, error="blocked non-public URL")
        timeout = (timeout_ms or self.settings.screenshot_timeout_ms) / 1000
        try:
            async with self._gate:
                shot = await asyncio.wait_for(self._capture(url, snippet), timeout=timeout + 2)
                # Chrome occasionally exits before it writes DevToolsActivePort
                # (profile lock, antivirus, first-run). One fresh-profile retry
                # is cheap and turns a transient failure into evidence.
                if shot.error and (
                    "chrome exited" in shot.error or "DevTools port" in shot.error
                ):
                    shot = await asyncio.wait_for(self._capture(url, snippet), timeout=timeout + 2)
                self.last_error = shot.error or ""
                return shot
        except asyncio.TimeoutError:
            self.last_error = "screenshot timeout"
            return Screenshot(url=url, error=self.last_error)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
            return Screenshot(url=url, error=self.last_error)

    async def capture_many(self, sources: list[dict[str, Any]], limit: int | None = None) -> dict[int, Screenshot]:
        if not self.enabled:
            return {}
        cap = max(0, min(limit if limit is not None else self.settings.screenshot_max, self.settings.screenshot_max))
        selected = [item for item in sources if item.get("url")][:cap]
        if not selected:
            return {}
        semaphore = asyncio.Semaphore(2)

        async def one(item: dict[str, Any]) -> tuple[int, Screenshot]:
            async with semaphore:
                shot = await self.capture(str(item.get("url") or ""), str(item.get("passage") or ""))
                return int(item.get("n") or 0), shot

        results = await asyncio.gather(*(one(item) for item in selected), return_exceptions=True)
        output: dict[int, Screenshot] = {}
        for result in results:
            if isinstance(result, Exception):
                continue
            number, shot = result
            output[number] = shot
        return output

    async def _capture(self, url: str, snippet: str) -> Screenshot:
        # Keep profiles inside the project state dir. The system temp dir can be
        # ACL-restricted or cleaned by other processes, which is exactly the
        # "chrome exited before DevTools started" failure mode we saw.
        profile_root = Path(getattr(self.settings, "state_dir", None) or tempfile.gettempdir()) / "screenshot-profiles"
        try:
            profile_root.mkdir(parents=True, exist_ok=True)
            # Do not use tempfile.mkdtemp here: on Windows under a restricted
            # token it can create a child directory whose ACL rejects every
            # subsequent write (including Chrome's own profile files).
            profile = profile_root / f"shot-{uuid.uuid4().hex[:10]}"
            profile.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            return Screenshot(
                url=url,
                error=f"profile dir unavailable: {type(exc).__name__}: {str(exc)[:160]}",
            )
        stderr_path = Path(profile) / "chrome-stderr.log"
        stderr_handle = None
        process: subprocess.Popen[bytes] | None = None
        try:
            args = [
                self.chrome,
                "--headless=new",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--hide-scrollbars",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-sync",
                "--disable-breakpad",
                "--disable-crash-reporter",
                "--window-size=1200,900",
                "--remote-debugging-port=0",
                f"--user-data-dir={profile}",
                "about:blank",
            ]
            stderr_handle = open(stderr_path, "wb")
            kwargs: dict[str, Any] = {"stdout": subprocess.DEVNULL, "stderr": stderr_handle}
            if sys.platform == "win32":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(args, **kwargs)
            port_file = Path(profile) / "DevToolsActivePort"
            port = 0
            for _ in range(150):  # 15s: cold Chrome start on Windows is slow
                if port_file.exists():
                    lines = port_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if lines:
                        port = int(lines[0])
                        break
                if process.poll() is not None:
                    stderr_handle.flush()
                    tail = stderr_path.read_text(encoding="utf-8", errors="ignore")[-300:].replace("\n", " ")
                    return Screenshot(
                        url=url,
                        error=f"chrome exited before DevTools started: {tail}".strip(),
                    )
                await asyncio.sleep(0.1)
            if not port:
                stderr_handle.flush()
                tail = stderr_path.read_text(encoding="utf-8", errors="ignore")[-200:].replace("\n", " ")
                return Screenshot(url=url, error=f"chrome DevTools port not found: {tail}".strip())
            target = await asyncio.to_thread(self._page_target, port)
            if not target:
                return Screenshot(url=url, error="no page target")
            async with websockets.connect(target, max_size=None, open_timeout=5) as connection:
                cdp = _CDP(connection)
                await cdp.call("Page.enable")
                await cdp.call(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": 1200, "height": 900, "deviceScaleFactor": 1, "mobile": False},
                )
                await cdp.call("Page.navigate", {"url": url})
                for _ in range(30):
                    try:
                        ready = await cdp.call(
                            "Runtime.evaluate",
                            {"expression": "document.readyState", "returnByValue": True},
                        )
                    except Exception:
                        ready = {}
                    value = (ready.get("result") or {}).get("value")
                    if value in {"interactive", "complete"}:
                        break
                    await asyncio.sleep(0.2)
                await asyncio.sleep(1.0)
                matched = False
                snippet = _clean_snippet(snippet)
                if snippet:
                    probe_expression = (
                        "document.body ? document.body.innerText.includes("
                        + json.dumps(snippet, ensure_ascii=False)
                        + ") : false"
                    )
                    for _ in range(15):
                        try:
                            probe = await cdp.call(
                                "Runtime.evaluate",
                                {"expression": probe_expression, "returnByValue": True},
                            )
                        except Exception:
                            probe = {}
                        if (probe.get("result") or {}).get("value"):
                            break
                        await asyncio.sleep(0.2)
                    expression = self._highlight_expression(snippet)
                    try:
                        result = await cdp.call(
                            "Runtime.evaluate",
                            {"expression": expression, "returnByValue": True},
                        )
                        matched = bool((result.get("result") or {}).get("value"))
                    except Exception:
                        matched = False
                    await asyncio.sleep(0.3)
                shot = await cdp.call(
                    "Page.captureScreenshot",
                    {"format": "jpeg", "quality": 70, "fromSurface": True},
                )
                data = base64.b64decode(shot.get("data") or "")
                if not data:
                    return Screenshot(url=url, error="empty screenshot")
                return Screenshot(
                    url=url,
                    data=data,
                    media_type="image/jpeg",
                    width=1200,
                    height=900,
                    matched=matched,
                )
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except Exception:
                    process.kill()
            if stderr_handle is not None:
                try:
                    stderr_handle.close()
                except Exception:
                    pass
            shutil.rmtree(profile, ignore_errors=True)

    @staticmethod
    def _page_target(port: int) -> str:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
                targets = json.loads(response.read().decode("utf-8"))
        except Exception:
            return ""
        for target in targets:
            if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                return str(target["webSocketDebuggerUrl"])
        return ""

    @staticmethod
    def _highlight_expression(snippet: str) -> str:
        needle = json.dumps(snippet, ensure_ascii=False)
        return (
            "(() => { const needle = " + needle + ";"
            " if (!needle || !document.body) return false;"
            " const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);"
            " let node;"
            " while ((node = walker.nextNode())) {"
            "  const text = node.nodeValue || '';"
            "  const idx = text.indexOf(needle);"
            "  if (idx >= 0) {"
            "   try {"
            "    const range = document.createRange();"
            "    range.setStart(node, idx);"
            "    range.setEnd(node, Math.min(text.length, idx + needle.length));"
            "    const mark = document.createElement('mark');"
            "    mark.style.background = '#ffe066';"
            "    mark.style.outline = '2px solid #d97706';"
            "    range.surroundContents(mark);"
            "    mark.scrollIntoView({block: 'center'});"
            "   } catch (e) { const el = node.parentElement; if (el) el.scrollIntoView({block: 'center'}); }"
            "   return true;"
            "  }"
            " }"
            " return false;"
            "})()"
        )
