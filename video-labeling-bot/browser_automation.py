import os
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

SELECTORS = {
    "start_time_input": 'input[name="startTime"], input[id*="start"], input[placeholder*="Start"]',
    "end_time_input": 'input[name="endTime"], input[id*="end"], input[placeholder*="End"]',
    "label_input": 'textarea[name="label"], input[name="label"], textarea[placeholder*="Label"]',
    "add_timestamp_btn": 'button:has-text("Add Segment"), button:has-text("Add Timestamp")',
    "submit_btn": 'button:has-text("Submit"), button[type="submit"]',
}


class VideoBrowserBot:
    def __init__(
        self, user_data_dir: str = "./browser_session", headless: bool = False
    ):
        """Initializes Playwright with persistent context to maintain user sessions."""
        self.user_data_dir = user_data_dir
        self.headless = headless
        self.playwright = None
        self.browser_context = None
        self.page = None

    def start(self, url: str):
        """Launches Chromium browser using persistent browser session state."""
        self.playwright = sync_playwright().start()
        launch_args = {
            "user_data_dir": self.user_data_dir,
            "headless": self.headless,
            "args": ["--start-maximized"],
            "viewport": None,
        }
        if self.headless:
            launch_args["args"] = [
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ]
            launch_args["viewport"] = {"width": 1280, "height": 720}

        self.browser_context = self.playwright.chromium.launch_persistent_context(
            **launch_args
        )
        self.page = (
            self.browser_context.pages[0]
            if self.browser_context.pages
            else self.browser_context.new_page()
        )
        print(f"[Browser Bot]: Navigating to {url}...")
        self.page.goto(url, wait_until="networkidle")

    def wait_for_manual_login(
        self, check_selector: str = 'button:has-text("Submit")', timeout: int = 120
    ):
        """Pauses execution to allow initial manual authentication if required."""
        print(
            "[Browser Bot]: Complete manual authentication in the browser window..."
        )
        try:
            self.page.wait_for_selector(check_selector, timeout=timeout * 1000)
            print("[Browser Bot]: Active task interface detected.")
        except PlaywrightTimeoutError:
            print("[Browser Bot]: Interface detection timeout. Continuing...")

    def _fill_first_match(self, selector_group: str, value: str) -> bool:
        """Fills the first visible selector in a comma-separated CSS group."""
        selectors = [part.strip() for part in selector_group.split(",")]
        last_error = None
        for selector in selectors:
            locator = self.page.locator(selector).first
            try:
                if locator.count() == 0:
                    continue
                locator.fill(str(value), timeout=5000)
                return True
            except Exception as exc:
                last_error = exc
                continue
        if last_error:
            raise last_error
        raise RuntimeError(f"No matching visible input for: {selector_group}")

    def add_timestamp_and_label(self, start_time: str, end_time: str, label: str):
        """Populates time interval inputs and label text in the UI."""
        try:
            print(
                f"[Browser Bot]: Entering [{start_time} - {end_time}] -> '{label}'"
            )

            self._fill_first_match(SELECTORS["start_time_input"], str(start_time))
            time.sleep(0.3)

            self._fill_first_match(SELECTORS["end_time_input"], str(end_time))
            time.sleep(0.3)

            self._fill_first_match(SELECTORS["label_input"], label)
            time.sleep(0.3)

            add_btn = self.page.locator(SELECTORS["add_timestamp_btn"]).first
            if add_btn.count() > 0 and add_btn.is_visible():
                add_btn.click()
                print("[Browser Bot]: Timestamp segment added.")

        except Exception as e:
            print(f"[Browser Bot Error]: Failed to inject data - {e}")

    def submit_final_task(self):
        """Triggers the task submission button in the browser."""
        try:
            submit_btn = self.page.locator(SELECTORS["submit_btn"]).first
            if submit_btn.count() > 0 and submit_btn.is_visible():
                submit_btn.click()
                print("[Browser Bot]: Task submitted successfully.")
            else:
                print("[Browser Bot]: Submit button not accessible or disabled.")
        except Exception as e:
            print(f"[Browser Bot Error]: Submission failed - {e}")

    def stop(self):
        """Safely terminates browser resources."""
        if self.browser_context:
            self.browser_context.close()
        if self.playwright:
            self.playwright.stop()
        print("[Browser Bot]: Session closed.")
