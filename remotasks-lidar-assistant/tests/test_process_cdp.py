from pathlib import Path

import process_cdp
from process_cdp import command_line_cdp_urls, parse_debug_port, parse_user_data_dir, read_devtools_active_port


def test_parse_remote_debugging_port():
    cmd = r'C:\IX\chrome.exe --remote-debugging-port=18789 --lang=en-US'
    assert parse_debug_port(cmd) == 18789
    assert parse_debug_port("chrome.exe --headless") is None
    assert parse_debug_port("chrome.exe --remote-debugging-port=0") is None


def test_parse_user_data_dir_quoted_and_plain():
    quoted = r'chrome.exe --user-data-dir="C:\Users\user\AppData\Roaming\ixbrowser\p1"'
    assert parse_user_data_dir(quoted) == r"C:\Users\user\AppData\Roaming\ixbrowser\p1"
    plain = r"chrome.exe --user-data-dir=C:\ix\profile"
    assert parse_user_data_dir(plain) == r"C:\ix\profile"


def test_devtools_active_port_file(tmp_path: Path):
    (tmp_path / "DevToolsActivePort").write_text("19222\n/devtools/browser/abc\n", encoding="utf-8")
    assert read_devtools_active_port(tmp_path) == 19222


def test_command_line_urls_include_port_and_file(tmp_path: Path):
    (tmp_path / "DevToolsActivePort").write_text("15555\n", encoding="utf-8")
    cmd = f'chrome.exe --user-data-dir="{tmp_path}" --remote-debugging-port=14444'
    urls = command_line_cdp_urls(cmd)
    assert "http://127.0.0.1:14444" in urls
    assert "http://127.0.0.1:15555" in urls


def test_discover_cdp_http_urls_returns_live_devtools(monkeypatch) -> None:
    monkeypatch.setattr(
        process_cdp,
        "_candidate_http_urls",
        lambda: ["http://127.0.0.1:9222"],
    )
    monkeypatch.setattr(process_cdp, "probe_devtools", lambda url: True)
    assert process_cdp.discover_cdp_http_urls() == ["http://127.0.0.1:9222"]


def test_discover_cdp_http_urls_empty_when_port_is_not_devtools(monkeypatch) -> None:
    monkeypatch.setattr(
        process_cdp,
        "_candidate_http_urls",
        lambda: ["http://127.0.0.1:38607"],
    )
    monkeypatch.setattr(process_cdp, "probe_devtools", lambda url: False)
    assert process_cdp.discover_cdp_http_urls() == []
