"""Persistent-context Playwright controller with point-cloud frame interception."""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Page, Playwright, Response, sync_playwright

import config

logger = logging.getLogger("lidar.browser")

OnFrameSaved = Callable[[Path], None]

_EXT_RE = re.compile(r"\.(pcd|bin|ply)(?:$|\?)", re.IGNORECASE)


class LidarBrowser:
    """Launch Chrome with a sticky profile and save 3D frame payloads locally."""

    def __init__(
        self,
        user_data_dir: Path | None = None,
        captures_dir: Path | None = None,
        on_frame_saved: OnFrameSaved | None = None,
        headless: bool = False,
    ) -> None:
        self.user_data_dir = Path(user_data_dir or config.USER_DATA_DIR)
        self.captures_dir = Path(captures_dir or config.DEBUG_CAPTURES)
        self.on_frame_saved = on_frame_saved
        self.headless = headless
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._lock = threading.Lock()
        self.saved_frames: list[Path] = []

    def launch(self) -> BrowserContext:
        """Start a persistent Chromium/Chrome context so logins survive restarts."""
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        launch_kwargs = {
            "user_data_dir": str(self.user_data_dir),
            "headless": self.headless,
            "viewport": {"width": 1440, "height": 900},
            "ignore_https_errors": False,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                channel=config.BROWSER_CHANNEL,
                **launch_kwargs,
            )
            logger.info("Launched persistent context with channel=%s", config.BROWSER_CHANNEL)
        except Exception as exc:
            logger.warning(
                "Chrome channel unavailable (%s); falling back to bundled Chromium",
                exc,
            )
            self._context = self._playwright.chromium.launch_persistent_context(
                **launch_kwargs,
            )
        self.intercept_frames()
        return self._context

    def intercept_frames(self) -> None:
        """Attach response listeners on current and future pages."""
        if self._context is None:
            raise RuntimeError("Call launch() before intercept_frames()")
        for page in self._context.pages:
            self._attach_page(page)
        self._context.on("page", self._attach_page)
        logger.info("Frame interception armed")

    def goto(self, url: str) -> Page:
        if self._context is None:
            raise RuntimeError("Call launch() before goto()")
        page = self._context.pages[0] if self._context.pages else self._context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        return page

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        logger.info("Browser closed")

    def _attach_page(self, page: Page) -> None:
        page.on("response", self._on_response)

    def _on_response(self, response: Response) -> None:
        try:
            url = response.url
            content_type = (response.headers.get("content-type") or "").lower()
            if not self._should_capture(url, content_type, response.status):
                return
            body = response.body()
            if not body or len(body) < 32:
                return
            path = self._write_capture(url, body)
            logger.info("Captured %s bytes from %s -> %s", len(body), url, path.name)
            if self.on_frame_saved is not None:
                self.on_frame_saved(path)
        except Exception:
            logger.exception("Failed to intercept response %s", getattr(response, "url", "?"))

    def _should_capture(self, url: str, content_type: str, status: int) -> bool:
        if status < 200 or status >= 300:
            return False
        if any(skip in content_type for skip in config.SKIP_CONTENT_TYPES):
            return False
        lowered = url.lower()
        path = urlparse(url).path.lower()
        if path.endswith(config.CAPTURE_EXTENSIONS) or _EXT_RE.search(url):
            return True
        if any(token in lowered for token in config.CAPTURE_URL_TOKENS):
            return True
        if "frame" in lowered and (
            any(token in lowered for token in config.CAPTURE_FRAME_TOKENS)
            or "octet-stream" in content_type
            or "application/json" in content_type
        ):
            return True
        return False

    def _write_capture(self, url: str, body: bytes) -> Path:
        ext = self._guess_extension(url, body)
        latest = self.captures_dir / f"latest_frame{ext}"
        with self._lock:
            latest.write_bytes(body)
            stamp = self.captures_dir / f"frame_{len(self.saved_frames):04d}{ext}"
            stamp.write_bytes(body)
            self.saved_frames.append(stamp)
            # Keep the canonical latest_frame.pcd pointer for the analyzer
            if ext != ".pcd":
                alias = self.captures_dir / "latest_frame.pcd"
                alias.write_bytes(body)
        return latest

    @staticmethod
    def _guess_extension(url: str, body: bytes) -> str:
        path = urlparse(url).path.lower()
        for ext in config.CAPTURE_EXTENSIONS:
            if path.endswith(ext):
                return ext
        head = body.lstrip()[:64]
        if head.startswith(b"{") or head.startswith(b"["):
            return ".json"
        if head.startswith(b"# .PCD") or head.startswith(b"VERSION") or head.startswith(b"FIELDS"):
            return ".pcd"
        return ".bin"
