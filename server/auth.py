"""Username/password authentication with signed, HttpOnly session cookies.

The goal is deliberately small and dependency-free: one JSON user store, scrypt
password hashes, and HMAC-signed cookies. Every authenticated user can add more
users (no roles), matching the project's single-team deployment model.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("scribd.auth")

COOKIE_NAME = "scribd_session"
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 128

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32


class AuthError(Exception):
    status_code = 400
    code = "auth_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidCredentialsError(AuthError):
    status_code = 401
    code = "invalid_credentials"


class InvalidUsernameError(AuthError):
    status_code = 400
    code = "invalid_username"


class InvalidPasswordError(AuthError):
    status_code = 400
    code = "invalid_password"


class UsernameExistsError(AuthError):
    status_code = 409
    code = "username_exists"


class TooManyAttemptsError(AuthError):
    status_code = 429
    code = "too_many_attempts"


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Return a self-describing scrypt hash safe to store on disk."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return (
        f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}"
        f"${_b64encode(salt)}${_b64encode(digest)}"
    )


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored scrypt hash without raising."""
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        computed = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_b64decode(digest_b64)),
        )
        return hmac.compare_digest(computed, _b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


def _normalise_username(username: str) -> str:
    username = (username or "").strip()
    if not USERNAME_RE.fullmatch(username):
        raise InvalidUsernameError(
            "Username harus 3–32 karakter: huruf, angka, titik, garis bawah, atau strip."
        )
    return username


def _validate_password(password: str) -> str:
    if not isinstance(password, str) or not (
        PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH
    ):
        raise InvalidPasswordError(
            f"Password harus {PASSWORD_MIN_LENGTH}–{PASSWORD_MAX_LENGTH} karakter."
        )
    return password


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class AuthManager:
    def __init__(
        self,
        data_dir: Path,
        *,
        default_username: str = "ditok",
        default_password: str = "tokditok",
        session_days: int = 7,
        secure_cookie: bool = False,
    ):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.users_path = self.data_dir / "users.json"
        self.secret_path = self.data_dir / "session.key"
        self.default_username = default_username
        self.default_password = default_password
        self.session_days = max(1, int(session_days))
        self.session_seconds = self.session_days * 24 * 60 * 60
        self.secure_cookie = bool(secure_cookie)
        self.cookie_name = COOKIE_NAME

        self._users: dict[str, dict] = {}
        self._secret = b""
        self._dummy_hash = ""
        self._lock = threading.RLock()
        self._failures: dict[str, list[float]] = {}
        self._initialized = False

    @classmethod
    def from_env(cls) -> "AuthManager":
        return cls(
            data_dir=Path(os.getenv("SCRIBD_DATA_DIR", "/data")),
            default_username=os.getenv("SCRIBD_DEFAULT_USERNAME", "ditok"),
            default_password=os.getenv("SCRIBD_DEFAULT_PASSWORD", "tokditok"),
            session_days=int(os.getenv("SCRIBD_SESSION_DAYS", "7")),
            secure_cookie=_env_flag("SCRIBD_COOKIE_SECURE", False),
        )

    # --------------------------------------------------------------- lifecycle

    def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._secret = self._load_or_create_secret()
            self._load_users()
            if not self._users:
                self._seed_default_user()
            self._dummy_hash = hash_password(secrets.token_urlsafe(32))
            self._initialized = True
            logger.info("auth ready: %s user(s)", len(self._users))

    def _load_or_create_secret(self) -> bytes:
        try:
            text = self.secret_path.read_text(encoding="utf-8").strip()
            secret = bytes.fromhex(text)
            if len(secret) >= 32:
                return secret
            logger.warning("session key is too short; generating a new one")
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            logger.warning("could not read session key (%s); generating a new one", error)

        secret = secrets.token_bytes(32)
        self._write_private(self.secret_path, secret.hex().encode("utf-8"))
        return secret

    def _load_users(self) -> None:
        if not self.users_path.is_file():
            return
        try:
            payload = json.loads(self.users_path.read_text(encoding="utf-8"))
            records = payload.get("users", []) if isinstance(payload, dict) else []
            if not isinstance(records, list):
                raise ValueError("users must be a list")
        except (OSError, ValueError) as error:
            backup = self.users_path.with_name(
                f"users.json.corrupt-{int(time.time())}"
            )
            try:
                os.replace(self.users_path, backup)
                logger.error(
                    "users store was corrupt (%s); moved to %s and seeding defaults",
                    error,
                    backup,
                )
            except OSError:
                logger.error("users store was corrupt (%s); seeding defaults", error)
            return

        loaded = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            username = str(record.get("username") or "").strip()
            password_hash = record.get("password_hash")
            if not USERNAME_RE.fullmatch(username) or not isinstance(password_hash, str):
                continue
            self._users[username.lower()] = {
                "username": username,
                "password_hash": password_hash,
                "created_at": record.get("created_at") or _utc_iso(),
                "created_by": record.get("created_by") or "unknown",
            }
            loaded += 1
        logger.info("loaded %s user(s)", loaded)

    def _seed_default_user(self) -> None:
        username = "ditok"
        password = "tokditok"
        try:
            username = _normalise_username(self.default_username)
        except InvalidUsernameError:
            logger.warning(
                "SCRIBD_DEFAULT_USERNAME is invalid; falling back to 'ditok'"
            )
        try:
            password = _validate_password(self.default_password)
        except InvalidPasswordError:
            logger.warning(
                "SCRIBD_DEFAULT_PASSWORD is invalid; falling back to the default"
            )

        record = {
            "username": username,
            "password_hash": hash_password(password),
            "created_at": _utc_iso(),
            "created_by": "system",
        }
        self._users[username.lower()] = record
        self._save_users()
        logger.warning(
            "created initial user '%s'. Set SCRIBD_DEFAULT_USERNAME/"
            "SCRIBD_DEFAULT_PASSWORD before the first start to choose other "
            "credentials, or add users from the USERS page.",
            username,
        )

    def _save_users(self) -> None:
        payload = {
            "version": 1,
            "users": sorted(
                self._users.values(),
                key=lambda record: (record.get("created_at", ""), record["username"]),
            ),
        }
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._write_private(self.users_path, data)

    @staticmethod
    def _write_private(path: Path, data: bytes) -> None:
        temporary = path.with_name(path.name + ".tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    # ------------------------------------------------------------------- users

    def _find(self, username: str) -> dict | None:
        return self._users.get((username or "").strip().lower())

    @staticmethod
    def _public(record: dict) -> dict:
        return {
            "username": record["username"],
            "created_at": record["created_at"],
            "created_by": record["created_by"],
        }

    def list_users(self) -> list[dict]:
        with self._lock:
            return [
                self._public(record)
                for record in sorted(
                    self._users.values(), key=lambda item: item["created_at"]
                )
            ]

    def get_public_user(self, username: str) -> dict | None:
        record = self._find(username)
        return self._public(record) if record else None

    def create_user(self, username: str, password: str, created_by: str) -> dict:
        with self._lock:
            username = _normalise_username(username)
            _validate_password(password)
            key = username.lower()
            if key in self._users:
                raise UsernameExistsError(f"Username '{username}' sudah dipakai.")

            record = {
                "username": username,
                "password_hash": hash_password(password),
                "created_at": _utc_iso(),
                "created_by": created_by,
            }
            self._users[key] = record
            try:
                self._save_users()
            except OSError:
                del self._users[key]
                raise
            logger.info("user '%s' created by '%s'", username, created_by)
            return self._public(record)

    def verify_credentials(self, username: str, password: str) -> str | None:
        """Return the canonical username on success, otherwise None."""
        username = (username or "").strip()
        password = password or ""
        record = self._find(username)

        # Always run scrypt so a missing username does not answer faster.
        stored = record["password_hash"] if record else self._dummy_hash
        if not (
            isinstance(password, str)
            and 0 < len(password) <= PASSWORD_MAX_LENGTH
        ):
            return None
        if not verify_password(password, stored):
            return None
        return record["username"] if record else None

    # ---------------------------------------------------------------- sessions

    def _sign(self, value: str) -> str:
        return _b64encode(
            hmac.new(self._secret, value.encode("ascii"), hashlib.sha256).digest()
        )

    def create_session(self, username: str) -> str:
        record = self._find(username)
        if not record:
            raise InvalidCredentialsError("User tidak ditemukan.")
        payload = {
            "u": record["username"],
            "exp": int(time.time()) + self.session_seconds,
        }
        encoded = _b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        return f"{encoded}.{self._sign(encoded)}"

    def session_username(self, token: str | None, *, now: float | None = None) -> str | None:
        if not token or "." not in token:
            return None
        encoded, signature = token.split(".", 1)
        if not hmac.compare_digest(signature, self._sign(encoded)):
            return None
        try:
            payload = json.loads(_b64decode(encoded))
            username = str(payload["u"])
            expires = int(payload["exp"])
        except (ValueError, KeyError, TypeError):
            return None
        if expires < int(now if now is not None else time.time()):
            return None
        record = self._find(username)
        return record["username"] if record else None

    def set_session_cookie(self, response, token: str) -> None:
        response.set_cookie(
            self.cookie_name,
            token,
            max_age=self.session_seconds,
            httponly=True,
            secure=self.secure_cookie,
            samesite="lax",
            path="/",
        )

    def clear_session_cookie(self, response) -> None:
        response.delete_cookie(
            self.cookie_name,
            path="/",
            secure=self.secure_cookie,
            httponly=True,
            samesite="lax",
        )

    # ---------------------------------------------------------------- throttling

    @staticmethod
    def throttle_key(client_ip: str, username: str) -> str:
        return f"{client_ip or 'unknown'}|{(username or '').strip().lower()}"

    def retry_after(self, key: str) -> int:
        now = time.monotonic()
        attempts = [
            moment
            for moment in self._failures.get(key, [])
            if now - moment < 60
        ]
        self._failures[key] = attempts
        if len(attempts) < 5:
            return 0
        remaining = 60 - (now - attempts[-1])
        return max(1, int(remaining + 0.999))

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        attempts = [
            moment
            for moment in self._failures.get(key, [])
            if now - moment < 60
        ]
        attempts.append(now)
        self._failures[key] = attempts[-10:]

    def clear_failures(self, key: str) -> None:
        self._failures.pop(key, None)
