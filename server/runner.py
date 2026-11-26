#!/usr/bin/env python3
"""Run one Scribd download as an isolated subprocess.

The worker starts this file, one process per job. Keeping the heavy Selenium
export in its own process makes cancellation reliable (the whole process group
is terminated) and keeps a browser crash away from the API process.

The original downloader is used unchanged; only the Chrome binary and
ChromeDriver paths are overridden so the container finds them.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Exported documents and debug artifacts can contain private link data.
os.umask(0o077)

from backend_bridge import load_backend  # noqa: E402
from protocol import ERROR_MARKER, JOB_MARKER, RESULT_MARKER  # noqa: E402


def _parse_proxy(raw: str):
    """Parse SCRIBD_PROXY into (server, username, password, scheme)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"http://{raw}"

    parsed = urlsplit(raw)
    if not parsed.hostname:
        raise ValueError("SCRIBD_PROXY bukan URL proxy yang valid.")

    scheme = (parsed.scheme or "http").lower()
    default_ports = {
        "http": 80,
        "https": 443,
        "socks4": 1080,
        "socks5": 1080,
        "socks5h": 1080,
    }
    if scheme not in default_ports:
        raise ValueError(
            f"Skema proxy '{scheme}' tidak didukung. Gunakan http:// atau socks5://."
        )

    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port or default_ports[scheme]
    server = f"{scheme}://{host}:{port}"
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    return server, username, password, scheme


def _build_proxy_auth_extension(username: str, password: str) -> Path:
    """Create a tiny Manifest V3 extension that answers proxy auth prompts."""
    directory = Path(tempfile.mkdtemp(prefix="scribd-proxy-auth-"))
    manifest = {
        "manifest_version": 3,
        "name": "Scribd proxy auth",
        "version": "1.0",
        "permissions": ["webRequest", "webRequestAuthProvider"],
        "host_permissions": ["<all_urls>"],
        "background": {"service_worker": "background.js"},
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    background = f"""chrome.webRequest.onAuthRequired.addListener(
  function (details, callback) {{
    callback({{
      authCredentials: {{
        username: {json.dumps(username)},
        password: {json.dumps(password)}
      }}
    }});
  }},
  {{urls: ["<all_urls>"]}},
  ["asyncBlocking"]
);
"""
    (directory / "background.js").write_text(background, encoding="utf-8")
    atexit.register(shutil.rmtree, directory, True)
    return directory


def install_chrome_overrides(module) -> None:
    """Point Selenium at the browser and driver shipped with the image."""
    chrome_bin = os.getenv("CHROME_BIN", "").strip()
    driver_bin = os.getenv("CHROMEDRIVER", "").strip()
    proxy = _parse_proxy(os.getenv("SCRIBD_PROXY", ""))

    if proxy:
        server, username, _, _ = proxy
        print(
            f"Using proxy {server} (auth: {'yes' if username else 'no'})",
            flush=True,
        )

    original_build_options = module.build_chrome_options

    def build_chrome_options(runtime_profile_dir):
        options = original_build_options(runtime_profile_dir)
        if chrome_bin and Path(chrome_bin).is_file():
            options.binary_location = chrome_bin
        if proxy:
            server, username, password, scheme = proxy
            options.add_argument(f"--proxy-server={server}")
            bypass = os.getenv("SCRIBD_PROXY_BYPASS", "localhost;127.0.0.1")
            options.add_argument(f"--proxy-bypass-list={bypass}")
            if username:
                if scheme in {"http", "https"}:
                    extension = _build_proxy_auth_extension(username, password)
                    options.add_argument(f"--disable-extensions-except={extension}")
                    options.add_argument(f"--load-extension={extension}")
                    print(
                        "Proxy auth extension enabled. If the proxy still rejects "
                        "the browser, run with SCRIBD_HEADLESS=0.",
                        flush=True,
                    )
                else:
                    print(
                        "WARNING: Chrome cannot authenticate SOCKS proxies. Use an "
                        "HTTP proxy with credentials or IP allow-listing.",
                        flush=True,
                    )
        return options

    module.build_chrome_options = build_chrome_options

    if not driver_bin:
        return

    from selenium.webdriver.chrome.service import Service

    real_webdriver = module.webdriver

    class WebdriverProxy:
        """Delegate everything to selenium.webdriver, forcing the driver path."""

        def __getattr__(self, name):
            return getattr(real_webdriver, name)

        def Chrome(self, *args, **kwargs):
            kwargs.setdefault("service", Service(executable_path=driver_bin))
            return real_webdriver.Chrome(*args, **kwargs)

    module.webdriver = WebdriverProxy()


def emit(marker: str, payload: dict) -> None:
    print(f"{marker} {json.dumps(payload, ensure_ascii=False)}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Scribd download job.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--format", required=True, choices=("pdf", "txt", "docx"))
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        module = load_backend()
        install_chrome_overrides(module)

        jobs, invalid = module.plan_downloads([args.url])
        if invalid or not jobs:
            emit(ERROR_MARKER, {"message": "Invalid Scribd URL", "code": "invalid_url"})
            return 2

        job = jobs[0]
        emit(
            JOB_MARKER,
            {
                "base_name": job["base_name"],
                "doc_id": job["info"]["doc_id"],
                "title_url": job["url"],
            },
        )

        saved = module.download_document(job, (args.format,), str(output_dir))
    except Exception as exc:  # noqa: BLE001 - reported to the API as job failure
        message = str(exc).strip() or exc.__class__.__name__
        traceback.print_exc()
        emit(
            ERROR_MARKER,
            {
                "message": message[:8000],
                "type": exc.__class__.__name__,
            },
        )
        return 1

    emit(
        RESULT_MARKER,
        {
            "saved": {fmt: str(path) for fmt, path in saved.items()},
            "base_name": job["base_name"],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
