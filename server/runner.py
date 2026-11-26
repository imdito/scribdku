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
import json
import os
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Exported documents and debug artifacts can contain private link data.
os.umask(0o077)

from backend_bridge import load_backend  # noqa: E402
from protocol import ERROR_MARKER, JOB_MARKER, RESULT_MARKER  # noqa: E402


def install_chrome_overrides(module) -> None:
    """Point Selenium at the browser and driver shipped with the image."""
    chrome_bin = os.getenv("CHROME_BIN", "").strip()
    driver_bin = os.getenv("CHROMEDRIVER", "").strip()

    original_build_options = module.build_chrome_options

    def build_chrome_options(runtime_profile_dir):
        options = original_build_options(runtime_profile_dir)
        if chrome_bin and Path(chrome_bin).is_file():
            options.binary_location = chrome_bin
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
