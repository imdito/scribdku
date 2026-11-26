"""Job queue, persistence and live progress for the Scribd downloader API."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import sys
import uuid
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import backend_bridge
from protocol import ERROR_MARKER, RESULT_MARKER

logger = logging.getLogger("scribd.jobs")

SUPPORTED_FORMATS = ("pdf", "docx", "txt")
MEDIA_TYPES = {
    "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class JobError(Exception):
    """An error that maps directly to an API response."""

    status_code = 400
    code = "job_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidURLError(JobError):
    status_code = 400
    code = "invalid_url"


class InvalidFormatError(JobError):
    status_code = 400
    code = "invalid_format"


class JobNotFoundError(JobError):
    status_code = 404
    code = "not_found"


class JobConflictError(JobError):
    status_code = 409
    code = "conflict"


class BackendUnavailableError(JobError):
    status_code = 503
    code = "backend_unavailable"


VIEWER_RE = re.compile(r"Viewer ready:\s*(\d+)\s+page\(s\) detected")
BATCH_RE = re.compile(r"Loading page batch\s+(\d+)-(\d+)/(\d+)")
PAGE_RE = re.compile(r"^\s*Page\s+(\d+)/(\d+)\s+\d+x\d+px")
MERGING_RE = re.compile(r"Merging\s+(\d+)\s+disk-spooled")
SKIP_RE = re.compile(r"Skipping page\s+(\d+)")
SAVE_RE = re.compile(r"(PDF|TXT|DOCX) saved successfully")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _page_progress(done: int, total: int) -> float:
    if total <= 0:
        return 5.0
    ratio = min(max(done, 0), total) / total
    return round(5.0 + 85.0 * ratio, 1)


def parse_progress_line(line: str) -> dict | None:
    """Translate one line of downloader output into a progress update."""
    text = (line or "").rstrip("\r\n")
    stripped = text.strip()
    if not stripped:
        return None

    match = VIEWER_RE.search(text)
    if match:
        return {"kind": "viewer", "pages_total": int(match.group(1))}

    match = BATCH_RE.search(text)
    if match:
        return {
            "kind": "batch",
            "start": int(match.group(1)),
            "end": int(match.group(2)),
            "pages_total": int(match.group(3)),
        }

    match = PAGE_RE.match(text)
    if match:
        return {
            "kind": "page",
            "page": int(match.group(1)),
            "pages_total": int(match.group(2)),
        }

    match = MERGING_RE.search(text)
    if match:
        return {"kind": "merging", "pages": int(match.group(1))}

    match = SAVE_RE.search(text)
    if match:
        return {"kind": "saved", "format": match.group(1).lower()}

    match = SKIP_RE.search(text)
    if match:
        return {"kind": "skip", "page": int(match.group(1))}

    if "Starting Chrome browser" in text:
        return {"kind": "browser"}
    if "Reading document text and images" in text:
        return {"kind": "reading"}
    if "Building DOCX" in text:
        return {"kind": "writing", "format": "docx"}
    if stripped == "Browser closed.":
        return {"kind": "browser_closed"}

    return None


def apply_progress(job: dict, update: dict) -> bool:
    """Apply a parsed progress update to a job in place.

    Returns True when the job changed and should be persisted.
    """
    kind = update["kind"]
    progress = float(job.get("progress") or 0.0)

    if kind == "viewer":
        total = int(update["pages_total"])
        job["pages_total"] = total
        job["phase"] = "pages"
        job["message"] = f"Viewer siap — {total} halaman terdeteksi."
        job["progress"] = max(progress, 5.0)
        return True

    if kind == "batch":
        total = int(update["pages_total"])
        start = int(update["start"])
        end = int(update["end"])
        done = max(int(job.get("pages_done") or 0), start - 1)
        job["pages_total"] = total
        job["pages_done"] = min(done, total)
        job["phase"] = "pages"
        job["message"] = f"Memuat halaman {start}–{end} dari {total}…"
        job["progress"] = max(progress, _page_progress(done, total))
        return True

    if kind == "page":
        total = int(update["pages_total"])
        done = int(update["page"])
        job["pages_total"] = total
        job["pages_done"] = min(done, total)
        job["phase"] = "pages"
        job["message"] = f"Mengambil halaman {done} dari {total}…"
        job["progress"] = max(progress, _page_progress(done, total))
        return True

    if kind == "reading":
        job["phase"] = "pages"
        job["message"] = "Membaca teks dan gambar halaman…"
        return True

    if kind == "merging":
        job["phase"] = "merging"
        job["message"] = f"Menggabungkan {int(update['pages'])} halaman…"
        job["progress"] = max(progress, 94.0)
        return True

    if kind == "writing":
        job["phase"] = "writing"
        job["message"] = "Menyusun file akhir…"
        job["progress"] = max(progress, 96.0)
        if job.get("pages_total"):
            job["pages_done"] = job["pages_total"]
        return True

    if kind == "saved":
        job["phase"] = "writing"
        job["message"] = f"File {update['format'].upper()} selesai dibuat."
        job["progress"] = max(progress, 99.0)
        if job.get("pages_total"):
            job["pages_done"] = job["pages_total"]
        return True

    if kind == "browser":
        job["phase"] = "browser"
        job["message"] = "Menjalankan browser…"
        job["progress"] = max(progress, 3.0)
        return True

    if kind == "browser_closed":
        if progress < 96.0:
            job["phase"] = "writing"
            job["message"] = "Menutup browser dan menyusun file…"
            job["progress"] = 96.0
        if job.get("pages_total"):
            job["pages_done"] = job["pages_total"]
        return True

    if kind == "skip":
        warnings = job.setdefault("warnings", [])
        warning = f"Halaman {int(update['page'])} dilewati."
        if warning not in warnings:
            warnings.append(warning)
        job["message"] = warning
        return True

    return False


def classify_error(message: str, *, stderr: str = "", stdout_tail: str = "") -> tuple[str, str]:
    """Map a backend failure to a stable code and a user-facing Indonesian message."""
    text = f"{message}\n{stderr}\n{stdout_tail}".lower()

    if "invalid scribd url" in text or "not a valid scribd" in text:
        return "invalid_url", "Tautan bukan link dokumen Scribd yang valid."
    if any(
        marker in text
        for marker in (
            "client challenge",
            "datadome",
            "captcha-delivery",
            "dd_cookie",
            "challenge-platform",
        )
    ):
        return (
            "blocked",
            "Scribd menampilkan tantangan bot (Client Challenge/DataDome). IP server ini "
            "diblokir — gunakan proxy residensial (SCRIBD_PROXY) atau jalankan dari "
            "jaringan rumahan.",
        )
    if any(
        marker in text
        for marker in (
            "bot check",
            "cloudflare",
            "just a moment",
            "checking your browser",
            "verify you are human",
            "attention required",
            "cf-chl",
            "captcha",
        )
    ):
        return (
            "blocked",
            "Scribd menampilkan pemeriksaan bot (Cloudflare). Coba lagi beberapa saat lagi "
            "atau dari jaringan yang berbeda.",
        )
    if any(marker in text for marker in ("denied access", "access denied", "403 forbidden")):
        return (
            "blocked",
            "Scribd menolak akses dari jaringan server ini. Coba lagi dari jaringan lain.",
        )
    if any(
        marker in text
        for marker in (
            "document was not found",
            "document not found",
            "can't display this document",
            "no longer available",
            "has been removed",
            "page not found",
        )
    ):
        return "not_found", "Dokumen tidak ditemukan. Mungkin sudah dihapus atau dijadikan privat."
    if "secret_password in this shared link may be wrong" in text:
        return "bad_password", "secret_password pada link ini salah atau sudah kedaluwarsa."
    if "document may be private" in text or "the document may be private" in text:
        return (
            "private",
            "Dokumen ini privat. Gunakan link share lengkap beserta secret_password.",
        )
    if "redirected to a login page" in text or "require an account" in text:
        return "login_required", "Dokumen ini meminta login akun Scribd."
    if "no printable document pages" in text or "did not load any pages" in text:
        return (
            "no_pages",
            "Viewer Scribd tidak menampilkan halaman. Jaringan mungkin lambat atau akses diblokir.",
        )
    if "timed out" in text or "timeout" in text:
        return "timeout", "Proses melebihi batas waktu. Coba lagi atau gunakan dokumen lain."
    if "err_proxy_auth" in text or "proxy authentication" in text:
        return (
            "proxy_auth",
            "Proxy meminta autentikasi. Periksa SCIBD_PROXY atau gunakan proxy "
            "HTTP dengan username/password.",
        )
    if any(
        marker in text
        for marker in (
            "err_proxy_connection_failed",
            "err_tunnel_connection_failed",
            "err_proxy_certificate",
            "err_socks",
        )
    ):
        return (
            "proxy_error",
            "Tidak bisa terhubung ke proxy. Periksa host/port dan status "
            "SCRIBD_PROXY.",
        )
    if any(
        marker in text
        for marker in (
            "session not created",
            "chrome not reachable",
            "chromedriver",
            "google-chrome",
            "chrome binary",
        )
    ):
        return "browser_error", "Browser headless gagal dijalankan di server."
    if "no such file or directory" in text:
        return "browser_error", "Browser headless gagal dijalankan di server."
    return "failed", "Unduhan gagal. Silakan coba lagi."


def _title_from_info(info: dict) -> str:
    slug = (info.get("slug") or "").strip()
    title = re.sub(r"\s+", " ", slug.replace("_", " ").replace("-", " ")).strip()
    return title or f"Scribd Document {info['doc_id']}"


def _sort_datetime(job: dict) -> datetime:
    return parse_iso(job.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)


class JobManager:
    """Queue one download at a time (by default) and expose live job state."""

    def __init__(
        self,
        data_dir: Path,
        *,
        max_concurrent: int = 1,
        ttl_days: float = 7,
        job_timeout_seconds: float = 3600,
        runner_path: Path | None = None,
    ):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.jobs_dir = self.data_dir / "jobs"
        self.tmp_dir = self.data_dir / "tmp"
        self.store_path = self.data_dir / "jobs.json"
        self.max_concurrent = max(1, int(max_concurrent))
        self.ttl = timedelta(days=max(0.1, float(ttl_days)))
        self.retention_days = float(ttl_days)
        self.job_timeout = max(10.0, float(job_timeout_seconds))
        self.runner_path = (
            Path(runner_path).resolve()
            if runner_path
            else Path(__file__).resolve().with_name("runner.py")
        )

        self.jobs: dict[str, dict] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._cancel_requested: set[str] = set()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._prune_task: asyncio.Task | None = None
        self._started = False

    @classmethod
    def from_env(cls) -> "JobManager":
        return cls(
            data_dir=Path(os.getenv("SCRIBD_DATA_DIR", "/data")),
            max_concurrent=int(os.getenv("SCRIBD_MAX_CONCURRENT", "1")),
            ttl_days=float(os.getenv("SCRIBD_JOB_TTL_DAYS", "7")),
            job_timeout_seconds=float(os.getenv("SCRIBD_JOB_TIMEOUT", "3600")),
        )

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        if self._started:
            return

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

        self._load()
        self._reconcile_stale_jobs()
        self._prune_expired()
        self._cleanup_orphan_dirs()
        self._cleanup_tmp_dir()
        self._save()

        for index in range(self.max_concurrent):
            self._workers.append(
                asyncio.create_task(self._worker(index), name=f"scribd-worker-{index}")
            )
        self._prune_task = asyncio.create_task(self._prune_loop(), name="scribd-prune")
        self._started = True
        logger.info(
            "job manager ready: %s job(s) in store, %s worker(s)",
            len(self.jobs),
            self.max_concurrent,
        )

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False

        for job_id in list(self._processes):
            job = self.jobs.get(job_id)
            if job and job["status"] == "running":
                self._fail_job(
                    job,
                    "Server berhenti sebelum unduhan selesai. Silakan coba lagi.",
                    "server_restart",
                    save=False,
                )
            await self._terminate_process(self._processes[job_id])

        for task in self._workers:
            task.cancel()
        if self._prune_task:
            self._prune_task.cancel()
        await asyncio.gather(*self._workers, self._prune_task, return_exceptions=True)
        self._workers.clear()
        self._prune_task = None
        self._save()
        logger.info("job manager stopped")

    # ------------------------------------------------------------------- store

    def _load(self) -> None:
        if not self.store_path.is_file():
            return
        try:
            payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            logger.warning("could not read job store: %s", error)
            return

        records = payload.get("jobs", []) if isinstance(payload, dict) else payload
        if isinstance(records, dict):
            records = records.values()
        if not isinstance(records, list):
            logger.warning("ignoring job store with unexpected shape")
            return

        now = utcnow()
        for record in records:
            if not isinstance(record, dict) or not record.get("id"):
                continue
            defaults = {
                "url": "",
                "format": "pdf",
                "title": "Scribd Document",
                "base_name": "scribd_document",
                "filename": None,
                "status": "failed",
                "phase": "done",
                "progress": 0.0,
                "pages_done": 0,
                "pages_total": None,
                "message": "",
                "error": None,
                "error_code": None,
                "error_detail": None,
                "size_bytes": None,
                "warnings": [],
                "created_at": iso(now),
                "started_at": None,
                "finished_at": None,
                "expires_at": iso(now + self.ttl),
            }
            for key, value in defaults.items():
                record.setdefault(key, value)

            if record["format"] not in SUPPORTED_FORMATS:
                record["format"] = "pdf"
            if record["status"] not in ACTIVE_STATUSES | TERMINAL_STATUSES:
                record["status"] = "failed"
            record["progress"] = float(record.get("progress") or 0.0)
            record["pages_done"] = int(record.get("pages_done") or 0)
            if record.get("pages_total") is not None:
                record["pages_total"] = int(record["pages_total"])
            if not record.get("expires_at"):
                record["expires_at"] = iso(now + self.ttl)
            self.jobs[record["id"]] = record

    def _save(self) -> None:
        payload = {"version": 1, "jobs": list(self.jobs.values())}
        temporary = self.store_path.with_suffix(".json.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, self.store_path)
            try:
                os.chmod(self.store_path, 0o600)
            except OSError:
                pass
        except OSError as error:
            logger.error("could not persist job store: %s", error)

    def _reconcile_stale_jobs(self) -> None:
        """Jobs left active by a previous server process cannot be resumed."""
        now = utcnow()
        for job in self.jobs.values():
            if job["status"] in ACTIVE_STATUSES:
                job.update(
                    status="failed",
                    phase="done",
                    message="Unduhan terhenti karena server di-restart.",
                    error="Server di-restart sebelum unduhan selesai. Silakan coba lagi.",
                    error_code="server_restart",
                    error_detail=None,
                    finished_at=iso(now),
                )

    def _prune_expired(self) -> int:
        now = utcnow()
        removed = 0
        for job_id, job in list(self.jobs.items()):
            expires = parse_iso(job.get("expires_at"))
            if job["status"] in ACTIVE_STATUSES or expires is None or expires > now:
                continue
            shutil.rmtree(self.jobs_dir / job_id, ignore_errors=True)
            del self.jobs[job_id]
            removed += 1
        if removed:
            logger.info("pruned %s expired job(s)", removed)
        return removed

    def _cleanup_orphan_dirs(self) -> None:
        if not self.jobs_dir.is_dir():
            return
        known = set(self.jobs)
        for path in self.jobs_dir.iterdir():
            if path.is_dir() and path.name not in known:
                shutil.rmtree(path, ignore_errors=True)

    def _cleanup_tmp_dir(self) -> None:
        """Remove leftovers from a previous process (startup only)."""
        if not self.tmp_dir.is_dir():
            return
        for path in self.tmp_dir.iterdir():
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                try:
                    path.unlink()
                except OSError:
                    pass

    async def _prune_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(3600)
                self._prune_expired()
                self._cleanup_orphan_dirs()
                self._save()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep the maintenance loop alive
                logger.exception("periodic cleanup failed")

    # -------------------------------------------------------------------- jobs

    def _public(self, job: dict, queue_position: int | None = None) -> dict:
        data = {
            key: value
            for key, value in job.items()
            if not key.startswith("_")
        }
        file_path = self.jobs_dir / job["id"] / (job.get("filename") or "")
        has_file = job["status"] == "completed" and bool(job.get("filename")) and file_path.is_file()
        data["has_file"] = has_file
        data["download_url"] = f"/api/jobs/{job['id']}/file" if has_file else None
        data["queue_position"] = queue_position
        data["progress"] = round(float(job.get("progress") or 0.0), 1)
        return data

    def _queue_positions(self) -> dict[str, int]:
        queued = sorted(
            (job for job in self.jobs.values() if job["status"] == "queued"),
            key=_sort_datetime,
        )
        return {job["id"]: index + 1 for index, job in enumerate(queued)}

    async def create_job(self, url: str, fmt: str) -> dict:
        url = (url or "").strip()
        if len(url) > 4096:
            raise InvalidURLError("Tautan terlalu panjang.")

        fmt = (fmt or "pdf").strip().lower()
        if fmt not in SUPPORTED_FORMATS:
            raise InvalidFormatError(
                f"Format '{fmt}' tidak didukung. Pilih PDF, DOCX, atau TXT."
            )

        try:
            info = await asyncio.to_thread(backend_bridge.parse_scribd_url, url)
        except RuntimeError as error:
            raise BackendUnavailableError(
                "Backend downloader tidak tersedia di server."
            ) from error

        if not info:
            raise InvalidURLError(
                "Bukan tautan Scribd yang valid — harus link dokumen scribd.com."
            )

        base_name = backend_bridge.get_base_name_from_url(url)
        now = utcnow()
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "url": url,
            "doc_id": info["doc_id"],
            "format": fmt,
            "title": _title_from_info(info),
            "base_name": base_name,
            "filename": f"{base_name}.{fmt}",
            "status": "queued",
            "phase": "queued",
            "progress": 0.0,
            "pages_done": 0,
            "pages_total": None,
            "message": "Menunggu antrean unduhan…",
            "error": None,
            "error_code": None,
            "error_detail": None,
            "size_bytes": None,
            "warnings": [],
            "created_at": iso(now),
            "started_at": None,
            "finished_at": None,
            "expires_at": iso(now + self.ttl),
        }

        (self.jobs_dir / job_id).mkdir(parents=True, exist_ok=True, mode=0o700)
        self.jobs[job_id] = job
        self._save()
        await self._queue.put(job_id)
        logger.info("queued job %s (%s, %s)", job_id, info["doc_id"], fmt)
        return self._public(job, self._queue_positions().get(job_id))

    def list_jobs(self) -> list[dict]:
        positions = self._queue_positions()
        ordered = sorted(self.jobs.values(), key=_sort_datetime, reverse=True)
        return [self._public(job, positions.get(job["id"])) for job in ordered]

    def get_job(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            raise JobNotFoundError("Unduhan tidak ditemukan.")
        return self._public(job, self._queue_positions().get(job_id))

    def get_file(self, job_id: str) -> tuple[Path, str, str]:
        job = self.jobs.get(job_id)
        if not job:
            raise JobNotFoundError("Unduhan tidak ditemukan.")
        if job["status"] != "completed" or not job.get("filename"):
            raise JobConflictError("File belum siap diunduh.")

        job_dir = (self.jobs_dir / job_id).resolve()
        path = (job_dir / job["filename"]).resolve()
        if not path.is_relative_to(job_dir) or not path.is_file():
            raise JobNotFoundError("File sudah dihapus dari server.")
        media_type = MEDIA_TYPES.get(job["format"], "application/octet-stream")
        return path, job["filename"], media_type

    async def cancel_job(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            raise JobNotFoundError("Unduhan tidak ditemukan.")
        if job["status"] not in ACTIVE_STATUSES:
            raise JobConflictError("Unduhan ini sudah selesai.")

        now = utcnow()
        self._cancel_requested.add(job_id)
        job.update(
            status="cancelled",
            phase="done",
            message="Unduhan dibatalkan.",
            finished_at=iso(now),
        )
        self._save()

        process = self._processes.get(job_id)
        if process is not None:
            await self._terminate_process(process)

        shutil.rmtree(self.jobs_dir / job_id, ignore_errors=True)
        self._cancel_requested.discard(job_id)
        logger.info("cancelled job %s", job_id)
        return self._public(job)

    async def delete_job(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job:
            raise JobNotFoundError("Unduhan tidak ditemukan.")
        if job["status"] in ACTIVE_STATUSES:
            raise JobConflictError("Batalkan unduhan sebelum menghapusnya.")
        shutil.rmtree(self.jobs_dir / job_id, ignore_errors=True)
        del self.jobs[job_id]
        self._save()

    async def clear_history(self) -> int:
        removed = 0
        for job_id, job in list(self.jobs.items()):
            if job["status"] in ACTIVE_STATUSES:
                continue
            shutil.rmtree(self.jobs_dir / job_id, ignore_errors=True)
            del self.jobs[job_id]
            removed += 1
        if removed:
            self._save()
            logger.info("cleared %s job(s)", removed)
        return removed

    def stats(self) -> dict:
        counts = Counter(job["status"] for job in self.jobs.values())
        return {
            "jobs": len(self.jobs),
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
        }

    # ------------------------------------------------------------------ worker

    async def _worker(self, index: int) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                job = self.jobs.get(job_id)
                if not job or job["status"] != "queued":
                    continue
                if job_id in self._cancel_requested:
                    self._finish_cancelled(job)
                    continue
                await self._run_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - isolate jobs from each other
                logger.exception("worker %s crashed on job %s", index, job_id)
                job = self.jobs.get(job_id)
                if job and job["status"] not in TERMINAL_STATUSES:
                    self._fail_job(
                        job,
                        "Terjadi kesalahan internal pada server.",
                        "internal",
                        detail=str(error),
                    )
            finally:
                self._queue.task_done()

    async def _run_job(self, job_id: str) -> None:
        job = self.jobs[job_id]
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        job.update(
            status="running",
            phase="starting",
            started_at=iso(utcnow()),
            progress=max(float(job.get("progress") or 0.0), 2.0),
            message="Menyiapkan proses unduhan…",
            error=None,
            error_code=None,
            error_detail=None,
        )
        self._save()

        command = [
            sys.executable,
            "-u",
            str(self.runner_path),
            "--url",
            job["url"],
            "--format",
            job["format"],
            "--output-dir",
            str(job_dir),
        ]
        environment = os.environ.copy()
        environment.setdefault("PYTHONUNBUFFERED", "1")
        environment.setdefault("PYTHONIOENCODING", "utf-8")
        environment["TMPDIR"] = str(self.tmp_dir)

        logger.info("starting job %s (%s)", job_id, job["format"])
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(job_dir),
            env=environment,
            start_new_session=True,
        )
        self._processes[job_id] = process
        logger.info("job %s running as pid %s", job_id, process.pid)

        collected: dict[str, dict | None] = {"result": None, "error": None}
        stdout_tail: deque[str] = deque(maxlen=60)
        stderr_tail: deque[str] = deque(maxlen=80)
        timed_out = False

        async def read_stdout() -> None:
            assert process.stdout is not None
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if not line:
                    continue
                stdout_tail.append(line)

                if line.startswith(RESULT_MARKER):
                    try:
                        collected["result"] = json.loads(line[len(RESULT_MARKER):].strip())
                    except ValueError:
                        logger.warning("invalid result marker for job %s", job_id)
                    continue
                if line.startswith(ERROR_MARKER):
                    try:
                        collected["error"] = json.loads(line[len(ERROR_MARKER):].strip())
                    except ValueError:
                        collected["error"] = {"message": line[len(ERROR_MARKER):].strip()}
                    continue

                update = parse_progress_line(line)
                if update and apply_progress(job, update):
                    self._save()

        async def read_stderr() -> None:
            assert process.stderr is not None
            while True:
                raw = await process.stderr.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line:
                    stderr_tail.append(line)

        try:
            try:
                await asyncio.wait_for(
                    asyncio.gather(read_stdout(), read_stderr()),
                    timeout=self.job_timeout,
                )
            except asyncio.TimeoutError:
                timed_out = True
                logger.warning("job %s exceeded %ss", job_id, self.job_timeout)
                await self._terminate_process(process)
            returncode = await process.wait()
        finally:
            self._processes.pop(job_id, None)

        if job["status"] == "cancelled" or job_id in self._cancel_requested:
            self._finish_cancelled(job)
            return

        if job["status"] == "failed":
            # A shutdown (or another supervisor) already finalised this job.
            self._cancel_requested.discard(job_id)
            return

        if timed_out:
            self._fail_job(
                job,
                "Proses melebihi batas waktu server. Coba lagi atau gunakan dokumen lain.",
                "timeout",
                detail="".join(list(stdout_tail)[-10:]),
            )
            return

        output_path = self._resolve_output(job, collected["result"])
        if collected["error"] is not None:
            payload = collected["error"]
            message = str(payload.get("message") or "Unduhan gagal.")
            code = payload.get("code")
            if code == "invalid_url":
                human_code, human = "invalid_url", "Tautan bukan link dokumen Scribd yang valid."
            else:
                human_code, human = classify_error(
                    message,
                    stderr="\n".join(stderr_tail),
                    stdout_tail="\n".join(stdout_tail),
                )
            self._fail_job(job, human, human_code, detail=message)
            return

        if returncode != 0:
            message = (
                "\n".join(list(stderr_tail)[-12:])
                or "\n".join(list(stdout_tail)[-12:])
                or f"Proses berhenti dengan kode {returncode}."
            )
            code, human = classify_error(
                message,
                stderr="\n".join(stderr_tail),
                stdout_tail="\n".join(stdout_tail),
            )
            self._fail_job(job, human, code, detail=message)
            return

        if output_path is None:
            self._fail_job(
                job,
                "File hasil tidak ditemukan setelah proses selesai.",
                "missing_output",
                detail="".join(list(stdout_tail)[-10:]),
            )
            return

        self._complete_job(job, output_path)

    def _resolve_output(self, job: dict, result: dict | None) -> Path | None:
        job_dir = (self.jobs_dir / job["id"]).resolve()
        candidates: list[Path] = []

        if isinstance(result, dict):
            saved = result.get("saved")
            if isinstance(saved, dict) and saved.get(job["format"]):
                candidates.append(Path(str(saved[job["format"]])))
        if job.get("filename"):
            candidates.append(job_dir / job["filename"])

        for candidate in list(candidates):
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if (
                resolved.is_relative_to(job_dir)
                and resolved.is_file()
                and resolved.stat().st_size > 0
            ):
                return resolved

        try:
            matches = sorted(
                (
                    path
                    for path in job_dir.glob(f"*.{job['format']}")
                    if path.is_file() and path.stat().st_size > 0
                ),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            matches = []
        return matches[0].resolve() if matches else None

    def _pdf_page_count(self, path: Path) -> int | None:
        try:
            from pypdf import PdfReader

            return len(PdfReader(str(path)).pages)
        except Exception:  # noqa: BLE001 - page count is only a fallback
            return None

    def _complete_job(self, job: dict, path: Path) -> None:
        size_bytes = path.stat().st_size
        pages_total = job.get("pages_total")
        if job["format"] == "pdf":
            detected = self._pdf_page_count(path)
            if detected:
                pages_total = detected
        pages_done = pages_total or job.get("pages_done") or 0

        job.update(
            status="completed",
            phase="done",
            progress=100.0,
            pages_total=pages_total,
            pages_done=pages_done,
            filename=path.name,
            size_bytes=size_bytes,
            message="File siap diunduh.",
            error=None,
            error_code=None,
            error_detail=None,
            finished_at=iso(utcnow()),
        )
        self._cancel_requested.discard(job["id"])
        self._save()
        logger.info(
            "job %s completed: %s (%s bytes, %s pages)",
            job["id"],
            path.name,
            size_bytes,
            pages_total,
        )

    def _fail_job(
        self,
        job: dict,
        message: str,
        code: str,
        *,
        detail: str | None = None,
        save: bool = True,
    ) -> None:
        job.update(
            status="failed",
            phase="done",
            message="Unduhan gagal.",
            error=message,
            error_code=code,
            error_detail=(detail or "")[:8000] or None,
            finished_at=iso(utcnow()),
        )
        self._remove_partial_outputs(job)
        self._cancel_requested.discard(job["id"])
        if save:
            self._save()
        logger.warning(
            "job %s failed (%s): %s",
            job["id"],
            code,
            (detail or message).splitlines()[0] if (detail or message) else "",
        )

    def _finish_cancelled(self, job: dict) -> None:
        job.update(
            status="cancelled",
            phase="done",
            message="Unduhan dibatalkan.",
            finished_at=job.get("finished_at") or iso(utcnow()),
        )
        shutil.rmtree(self.jobs_dir / job["id"], ignore_errors=True)
        self._cancel_requested.discard(job["id"])
        self._save()
        logger.info("job %s cancelled", job["id"])

    def _remove_partial_outputs(self, job: dict) -> None:
        job_dir = self.jobs_dir / job["id"]
        if not job_dir.is_dir():
            return
        for path in job_dir.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() in {".pdf", ".txt", ".docx"} or path.name.endswith(".part"):
                try:
                    path.unlink()
                except OSError:
                    pass

    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=8)
            return
        except asyncio.TimeoutError:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            logger.error("process %s did not exit after SIGKILL", process.pid)
