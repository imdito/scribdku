from jobs import (
    _page_progress,
    apply_progress,
    classify_error,
    parse_progress_line,
)


def new_job():
    return {
        "status": "running",
        "phase": "starting",
        "progress": 2.0,
        "pages_done": 0,
        "pages_total": None,
        "warnings": [],
    }


def test_parse_viewer_ready():
    assert parse_progress_line("Viewer ready: 316 page(s) detected.") == {
        "kind": "viewer",
        "pages_total": 316,
    }


def test_parse_batch_line():
    assert parse_progress_line("  Loading page batch 9-16/316...") == {
        "kind": "batch",
        "start": 9,
        "end": 16,
        "pages_total": 316,
    }


def test_parse_page_line():
    assert parse_progress_line(
        '  Page 1/316 1002x1296px -> 10.438"x13.500"'
    ) == {"kind": "page", "page": 1, "pages_total": 316}


def test_parse_merging_line():
    assert parse_progress_line("Merging 307 disk-spooled PDF pages...") == {
        "kind": "merging",
        "pages": 307,
    }


def test_parse_saved_lines():
    assert parse_progress_line("PDF saved successfully to: /data/jobs/x/a.pdf") == {
        "kind": "saved",
        "format": "pdf",
    }
    assert parse_progress_line("TXT saved successfully to: a.txt") == {
        "kind": "saved",
        "format": "txt",
    }
    assert parse_progress_line("DOCX saved successfully to: a.docx") == {
        "kind": "saved",
        "format": "docx",
    }


def test_parse_phase_lines():
    assert parse_progress_line("Starting Chrome browser...") == {"kind": "browser"}
    assert parse_progress_line("Reading document text and images...") == {
        "kind": "reading"
    }
    assert parse_progress_line("Building DOCX (downloading page images)...") == {
        "kind": "writing",
        "format": "docx",
    }
    assert parse_progress_line("Browser closed.") == {"kind": "browser_closed"}


def test_parse_ignores_noise():
    assert parse_progress_line("Cookie dialogs hidden.") is None
    assert parse_progress_line("Print CSS injected.") is None
    assert parse_progress_line("") is None


def test_page_progress_bounds():
    assert _page_progress(0, 10) == 5.0
    assert _page_progress(5, 10) == 47.5
    assert _page_progress(10, 10) == 90.0
    assert _page_progress(99, 10) == 90.0
    assert _page_progress(1, 0) == 5.0


def test_progress_sequence_is_monotonic_and_uses_real_pages():
    job = new_job()
    apply_progress(job, parse_progress_line("Viewer ready: 8 page(s) detected."))
    assert job["pages_total"] == 8
    assert job["phase"] == "pages"
    assert job["progress"] == 5.0

    apply_progress(job, parse_progress_line("  Loading page batch 1-3/8..."))
    assert job["message"] == "Memuat halaman 1–3 dari 8…"

    apply_progress(job, parse_progress_line("  Page 1/8 1000x1400px -> 10.4x14.6"))
    assert job["pages_done"] == 1
    assert job["progress"] == 15.6

    apply_progress(job, parse_progress_line("  Page 2/8 1000x1400px -> 10.4x14.6"))
    assert job["pages_done"] == 2
    first = job["progress"]

    apply_progress(job, parse_progress_line("  Page 1/8 1000x1400px -> 10.4x14.6"))
    assert job["progress"] >= first

    apply_progress(job, parse_progress_line("Merging 8 disk-spooled PDF pages..."))
    assert job["phase"] == "merging"
    assert job["progress"] == 94.0

    apply_progress(job, parse_progress_line("PDF saved successfully to: a.pdf"))
    assert job["phase"] == "writing"
    assert job["progress"] == 99.0
    assert job["pages_done"] == 8


def test_docx_writing_finalises_page_counter():
    job = new_job()
    apply_progress(job, {"kind": "viewer", "pages_total": 2})
    assert job["pages_done"] == 0
    apply_progress(job, {"kind": "writing", "format": "docx"})
    assert job["pages_done"] == 2
    assert job["progress"] == 96.0


def test_browser_closed_finalises_page_counter():
    job = new_job()
    apply_progress(job, {"kind": "viewer", "pages_total": 12})
    apply_progress(job, {"kind": "batch", "start": 9, "end": 12, "pages_total": 12})
    assert job["pages_done"] == 8
    apply_progress(job, {"kind": "browser_closed"})
    assert job["pages_done"] == 12


def test_skip_page_collects_warning_once():
    job = new_job()
    line = "  Skipping page 4: element missing"
    assert apply_progress(job, parse_progress_line(line)) is True
    apply_progress(job, parse_progress_line(line))
    assert job["warnings"] == ["Halaman 4 dilewati."]


def test_classify_invalid_url():
    code, message = classify_error("Invalid Scribd URL")
    assert code == "invalid_url"
    assert "Scribd" in message


def test_classify_cloudflare():
    code, message = classify_error(
        "Scribd showed a bot check (Cloudflare). This usually happens on VPS."
    )
    assert code == "blocked"
    assert "Cloudflare" in message


def test_classify_client_challenge_as_blocked():
    code, message = classify_error(
        "No printable document pages were detected.\n"
        "  Reason: The Scribd viewer did not load any pages.\n"
        "  Page title: 'Client Challenge'\n"
        "  Page URL: https://www.scribd.com/embeds/630915458/content"
    )
    assert code == "blocked"
    assert "proxy residensial" in message
    assert "Client Challenge" in message


def test_classify_not_found():
    code, message = classify_error(
        "The document was not found. It may have been deleted or made private."
    )
    assert code == "not_found"
    assert "tidak ditemukan" in message


def test_classify_password_and_private():
    assert classify_error(
        "The secret_password in this shared link may be wrong or expired."
    )[0] == "bad_password"
    assert classify_error("The document may be private.")[0] == "private"


def test_classify_login_and_timeout():
    assert classify_error("Scribd redirected to a login page.")[0] == "login_required"
    assert classify_error("Page.printToPDF timed out")[0] == "timeout"


def test_classify_browser_error():
    assert classify_error(
        "selenium.common.exceptions.SessionNotCreatedException: session not created"
    )[0] == "browser_error"


def test_classify_proxy_errors():
    assert classify_error("net::ERR_PROXY_AUTH_UNSUPPORTED")[0] == "proxy_auth"
    assert classify_error("net::ERR_TUNNEL_CONNECTION_FAILED")[0] == "proxy_error"


def test_classify_fallback():
    assert classify_error("something odd happened")[0] == "failed"
