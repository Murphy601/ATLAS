"""Browser connection. Default: attach to the IX/Chrome window YOU already opened.

The engine never launches a browser. IX Browser must expose a CDP debugging port.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, Response, sync_playwright

import config
from ego_task import is_ego_task_page

logger = logging.getLogger("ego.browser")

OnFrameSaved = Callable[[Path], None]

_EXT_RE = re.compile(r"\.(pcd|bin|ply)(?:$|\?)", re.IGNORECASE)


class LidarBrowser:
    """Attach to an already-open IX/Chrome window (CDP). Does not launch a browser."""

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
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._cdp = False
        self._lock = threading.Lock()
        self.saved_frames: list[Path] = []

    def attach(self, cdp_url: str | None = None, timeout_s: float = 180.0) -> Browser:
        """Connect to IX Browser / Chrome that you already opened. Never launches."""
        import time
        import urllib.request

        from ix_api import discover_cdp_http_urls

        def say(msg: str) -> None:
            print(msg, flush=True)
            logger.info(msg)

        say("Looking for an already-open IX profile (Local API port 53200, then CDP)...")
        self._playwright = sync_playwright().start()
        deadline = time.monotonic() + timeout_s
        last_error: Exception | None = None
        logged_api_miss = False
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            urls = []
            if cdp_url:
                urls.append(cdp_url)
            try:
                urls.extend(discover_cdp_http_urls())
            except Exception as exc:
                last_error = exc
            if not urls and not logged_api_miss:
                say(
                    "IX Local API is not reachable on 127.0.0.1:53200. "
                    "Enable it in IX Browser: Settings -> Local API (port 53200). "
                    "Then close and reopen the profile. Also scanning CDP 9222-9231..."
                )
                logged_api_miss = True
            urls.extend(_cdp_candidates(cdp_url))
            # unique preserve order
            seen: set[str] = set()
            unique = []
            for url in urls:
                if url not in seen:
                    seen.add(url)
                    unique.append(url)
            if attempt == 1 or attempt % 5 == 0:
                say(f"Attach attempt {attempt}: trying {len(unique)} address(es)...")
            for url in unique:
                try:
                    with urllib.request.urlopen(url.rstrip("/") + "/json/version", timeout=1.0) as resp:
                        resp.read()
                    self._browser = self._playwright.chromium.connect_over_cdp(url)
                    self._cdp = True
                    if self._browser.contexts:
                        self._context = self._browser.contexts[0]
                    say(f"Attached to IX/Chrome via {url}")
                    return self._browser
                except Exception as exc:
                    last_error = exc
                    continue
            time.sleep(2.0)
        raise RuntimeError(
            "Could not attach to the IX window that is already open.\n"
            "1. In IX Browser: Settings -> Local API -> enable, port 53200.\n"
            "2. Close the profile and open it again (keep the EGO task tab).\n"
            "3. Re-run run.ps1.\n"
            f"Last error: {last_error}"
        )

    def wait_for_task_page(self, timeout_s: float = 600.0) -> Page:
        """Poll open tabs until the EGO Focused Timeline UI is visible."""
        import time

        if self._browser is None:
            raise RuntimeError("Call attach() first")
        deadline = time.monotonic() + timeout_s
        print("Waiting for the EGO task tab (Focused Timeline)...", flush=True)
        logger.info("Waiting for an already-open EGO task tab (Focused Timeline)...")
        last_dump = 0.0
        while time.monotonic() < deadline:
            pages = self.iter_pages()
            now = time.monotonic()
            if now - last_dump > 8:
                titles = []
                for page in pages:
                    try:
                        titles.append(page.url)
                    except Exception:
                        titles.append("(tab)")
                print(f"Open tabs ({len(pages)}): {titles[:8]}", flush=True)
                last_dump = now
            for page in pages:
                if is_ego_task_page(page):
                    print(f"Found open task: {page.url}", flush=True)
                    logger.info("Found open task: %s", page.url)
                    self._context = page.context
                    return page
            time.sleep(config.POLL_INTERVAL_SEC)
        raise TimeoutError(
            "No EGO task UI found. Open the task in IX Browser until you see "
            "Focused Timeline / ego_rectified_canonical, then keep that tab focused."
        )

    def iter_pages(self) -> list[Page]:
        pages: list[Page] = []
        if self._browser is None:
            return pages
        for ctx in self._browser.contexts:
            pages.extend(ctx.pages)
        return pages

    def launch(self) -> BrowserContext:
        raise RuntimeError(
            "The engine does not open Chrome. Start IX Browser yourself, open the task, "
            "then run this script so it can attach."
        )

    def intercept_frames(self) -> None:
        """Attach response listeners on current and future pages."""
        contexts = []
        if self._browser is not None:
            contexts = list(self._browser.contexts)
        elif self._context is not None:
            contexts = [self._context]
        if not contexts:
            raise RuntimeError("Call attach() before intercept_frames()")
        for ctx in contexts:
            for page in ctx.pages:
                self._attach_page(page)
            ctx.on("page", self._attach_page)
        logger.info("Frame interception armed")

    def goto(self, url: str) -> Page:
        raise RuntimeError("The engine does not navigate for you. Open the task in IX Browser yourself.")

    def close(self) -> None:
        """Disconnect Playwright only. Never closes your IX Browser window."""
        self._context = None
        self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                logger.debug("Playwright stop after CDP attach failed", exc_info=True)
            self._playwright = None
        logger.info("Disconnected from IX Browser (window left open)")

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


def _cdp_candidates(explicit: str | None) -> list[str]:
    urls = []
    if explicit:
        urls.append(explicit)
    urls.append(config.CDP_URL)
    for port in config.CDP_PORTS:
        urls.append(f"http://127.0.0.1:{port}")
    # Preserve order, drop duplicates
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out
