import stat
import time

import pytest

from auth import (
    AuthManager,
    InvalidPasswordError,
    InvalidUsernameError,
    UsernameExistsError,
    hash_password,
    verify_password,
)


def make_auth(tmp_path, **kwargs):
    auth = AuthManager(tmp_path, **kwargs)
    auth.initialize()
    return auth


def test_seed_default_user_and_verify(tmp_path):
    auth = make_auth(tmp_path)

    assert auth.verify_credentials("ditok", "tokditok") == "ditok"
    assert auth.verify_credentials("DITOK", "tokditok") == "ditok"
    assert auth.verify_credentials("ditok", "wrong") is None
    assert auth.verify_credentials("tidak-ada", "tokditok") is None

    users = auth.list_users()
    assert len(users) == 1
    assert users[0]["username"] == "ditok"
    assert "password_hash" not in users[0]


def test_password_hashes_are_salted_and_verifiable():
    first = hash_password("tokditok")
    second = hash_password("tokditok")

    assert first != second
    assert verify_password("tokditok", first)
    assert not verify_password("salah", first)
    assert not verify_password("tokditok", "bukan-hash")


def test_files_are_private_and_contain_no_plaintext(tmp_path):
    auth = make_auth(tmp_path)

    users_text = (tmp_path / "users.json").read_text(encoding="utf-8")
    assert "tokditok" not in users_text
    assert "password_hash" in users_text
    assert stat.S_IMODE((tmp_path / "users.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "session.key").stat().st_mode) == 0o600


def test_added_users_persist_and_can_log_in(tmp_path):
    auth = make_auth(tmp_path)
    created = auth.create_user("budi", "rahasia123", "ditok")
    assert created["created_by"] == "ditok"

    reloaded = make_auth(tmp_path)
    assert reloaded.verify_credentials("budi", "rahasia123") == "budi"
    assert len(reloaded.list_users()) == 2


def test_every_user_can_add_another_user(tmp_path):
    auth = make_auth(tmp_path)
    auth.create_user("budi", "rahasia123", "ditok")
    created = auth.create_user("siti", "password123", "budi")

    assert created["created_by"] == "budi"
    assert auth.verify_credentials("siti", "password123") == "siti"


def test_duplicate_username_is_case_insensitive(tmp_path):
    auth = make_auth(tmp_path)

    with pytest.raises(UsernameExistsError):
        auth.create_user("DITOK", "password123", "ditok")
    with pytest.raises(UsernameExistsError):
        auth.create_user("ditok", "password123", "ditok")


@pytest.mark.parametrize("username", ["", "ab", "spasi ada", "tanda!", "a" * 33])
def test_invalid_usernames_rejected(tmp_path, username):
    auth = make_auth(tmp_path)
    with pytest.raises(InvalidUsernameError):
        auth.create_user(username, "password123", "ditok")


@pytest.mark.parametrize("password", ["", "12345", "x" * 129])
def test_invalid_passwords_rejected(tmp_path, password):
    auth = make_auth(tmp_path)
    with pytest.raises(InvalidPasswordError):
        auth.create_user("budi", password, "ditok")


def test_session_roundtrip_and_tampering(tmp_path):
    auth = make_auth(tmp_path)
    token = auth.create_session("ditok")

    assert auth.session_username(token) == "ditok"
    assert auth.session_username(token + "x") is None
    assert auth.session_username("bukan.token") is None
    assert auth.session_username(None) is None


def test_session_expiry(tmp_path):
    auth = make_auth(tmp_path, session_days=1)
    token = auth.create_session("ditok")

    assert auth.session_username(token) == "ditok"
    assert auth.session_username(
        token, now=time.time() + auth.session_seconds + 5
    ) is None


def test_sessions_survive_restart(tmp_path):
    auth = make_auth(tmp_path)
    token = auth.create_session("ditok")

    restarted = make_auth(tmp_path)
    assert restarted.session_username(token) == "ditok"


def test_custom_default_credentials(tmp_path):
    auth = make_auth(
        tmp_path,
        default_username="admin",
        default_password="secret123",
    )

    assert auth.verify_credentials("admin", "secret123") == "admin"
    assert auth.verify_credentials("ditok", "tokditok") is None


def test_login_throttle(tmp_path, monkeypatch):
    auth = make_auth(tmp_path)
    key = auth.throttle_key("127.0.0.1", "ditok")

    monkeypatch.setattr("auth.time.monotonic", lambda: 1000.0)
    for _ in range(5):
        auth.record_failure(key)
    assert auth.retry_after(key) == 60

    monkeypatch.setattr("auth.time.monotonic", lambda: 1061.0)
    assert auth.retry_after(key) == 0

    auth.record_failure(key)
    auth.clear_failures(key)
    assert auth.retry_after(key) == 0
