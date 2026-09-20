"""
Account backend for TalentIQ: sign-up, sign-in, change password.

No Streamlit imports here -- this module is plain Python so it can be unit
tested (see ``tests/test_auth.py``) and later pointed at Supabase / Postgres by
replacing the few SQL calls in this file.

Storage
    ``<data dir>/users.db`` (SQLite, git-ignored because ``data/`` is ignored).
    The folder can be moved with ``TALENTIQ_DATA_DIR``.

Security choices
    * Passwords are never stored. Only a salted scrypt hash is (stdlib
      ``hashlib.scrypt``, so there is nothing extra to install).
    * Hashes are compared in constant time.
    * Sign-in failures use one generic message, and an unknown email costs the
      same time as a wrong password, so the form doesn't reveal which emails
      have accounts.
    * 5 wrong passwords in a row lock that account for 5 minutes.
    * Emails are case-insensitive (stored lower-cased).
"""
import base64
import hashlib
import hmac
import math
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from . import settings_store

MAX_FAILED_ATTEMPTS = 5
LOCK_SECONDS = 5 * 60
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 128
MAX_NAME_LEN = 80
MAX_EMAIL_LEN = 254

# scrypt cost: ~16 MB RAM, tens of milliseconds -- fine for a login form.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1

_BAD_CREDENTIALS = "Incorrect email or password."
_DB_ERROR = ("Couldn't reach the account database on this server. "
             "Check that the app's data folder is writable (see TALENTIQ_DATA_DIR).")

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")

_COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789", "1234567890",
    "qwerty123", "qwertyuiop", "iloveyou1", "admin123", "welcome1", "letmein123",
    "abc12345", "talentiq1", "talentiq123",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT    NOT NULL UNIQUE,
    full_name       TEXT    NOT NULL,
    pw_hash         TEXT    NOT NULL,
    created_at      REAL    NOT NULL,
    last_login      REAL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    REAL    NOT NULL DEFAULT 0
)
"""


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    b64 = lambda raw: base64.b64encode(raw).decode("ascii")
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """True only if ``password`` matches the stored hash. Never raises."""
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                                n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


# Used so an unknown email takes as long to reject as a wrong password does.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def normalize_email(email) -> str:
    return str(email or "").strip().lower()


def validate_email(email: str):
    """Return an error message, or None if the email looks valid."""
    if not email:
        return "Enter your email address."
    if len(email) > MAX_EMAIL_LEN or not _EMAIL_RE.match(email):
        return "That doesn't look like a valid email address."
    return None


def validate_name(name: str):
    if len(name) < 2:
        return "Enter your full name."
    if len(name) > MAX_NAME_LEN:
        return f"Name is too long (max {MAX_NAME_LEN} characters)."
    return None


def validate_password(password: str, email: str = ""):
    if len(password) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if len(password) > MAX_PASSWORD_LEN:
        return f"Password is too long (max {MAX_PASSWORD_LEN} characters)."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must include at least one letter and one number."
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS or (email and lowered == email.lower()):
        return "That password is too easy to guess. Choose something less common."
    return None


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
def db_path() -> Path:
    return settings_store.data_dir() / "users.db"


@contextmanager
def _db():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute(_SCHEMA)
        try:
            os.chmod(path, 0o600)  # owner-only where the OS supports it
        except OSError:
            pass
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def _public(row) -> dict:
    return {"id": int(row["id"]), "email": row["email"], "name": row["full_name"]}


# --------------------------------------------------------------------------
# Public API -- every function returns plain (ok, message, user) tuples so the
# UI never has to know about SQL or exceptions.
# --------------------------------------------------------------------------
def sign_up(full_name, email, password, confirm):
    name = " ".join(str(full_name or "").split())
    email = normalize_email(email)
    password = str(password or "")
    error = validate_name(name) or validate_email(email) or validate_password(password, email)
    if error:
        return False, error, None
    if password != str(confirm or ""):
        return False, "The two passwords don't match.", None
    pw_hash = hash_password(password)
    try:
        with _db() as con:
            cur = con.execute(
                "INSERT INTO users (email, full_name, pw_hash, created_at) VALUES (?, ?, ?, ?)",
                (email, name, pw_hash, time.time()),
            )
            user = {"id": int(cur.lastrowid), "email": email, "name": name}
    except sqlite3.IntegrityError:
        return False, "An account with this email already exists. Try signing in instead.", None
    except (sqlite3.Error, OSError):
        return False, _DB_ERROR, None
    return True, "Account created.", user


def sign_in(email, password):
    email = normalize_email(email)
    password = str(password or "")
    if not email or not password:
        return False, "Enter your email and password.", None
    try:
        with _db() as con:
            row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            now = time.time()
            if row is None:
                verify_password(password, _DUMMY_HASH)
                return False, _BAD_CREDENTIALS, None
            if row["locked_until"] and row["locked_until"] > now:
                minutes = max(1, math.ceil((row["locked_until"] - now) / 60))
                return False, (f"Too many failed attempts. Try again in {minutes} "
                               f"minute{'s' if minutes != 1 else ''}."), None
            if verify_password(password, row["pw_hash"]):
                con.execute(
                    "UPDATE users SET failed_attempts = 0, locked_until = 0, last_login = ? WHERE id = ?",
                    (now, row["id"]),
                )
                return True, "Signed in.", _public(row)
            failed = row["failed_attempts"] + 1
            if failed >= MAX_FAILED_ATTEMPTS:
                con.execute("UPDATE users SET failed_attempts = 0, locked_until = ? WHERE id = ?",
                            (now + LOCK_SECONDS, row["id"]))
                return False, (f"Too many failed attempts. This account is locked for "
                               f"{LOCK_SECONDS // 60} minutes."), None
            con.execute("UPDATE users SET failed_attempts = ? WHERE id = ?", (failed, row["id"]))
            return False, _BAD_CREDENTIALS, None
    except (sqlite3.Error, OSError):
        return False, _DB_ERROR, None


def get_user(user_id):
    """Fresh user record by id (used to confirm an account still exists)."""
    try:
        with _db() as con:
            row = con.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
            return _public(row) if row else None
    except (sqlite3.Error, OSError, TypeError, ValueError):
        return None


def change_password(user_id, current_password, new_password, confirm):
    current_password, new_password = str(current_password or ""), str(new_password or "")
    try:
        with _db() as con:
            row = con.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
            if row is None:
                return False, "This account no longer exists. Please sign in again."
            if not verify_password(current_password, row["pw_hash"]):
                return False, "Your current password is incorrect."
            error = validate_password(new_password, row["email"])
            if error:
                return False, error
            if new_password != str(confirm or ""):
                return False, "The two new passwords don't match."
            if verify_password(new_password, row["pw_hash"]):
                return False, "Choose a new password that is different from the current one."
            con.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (hash_password(new_password), row["id"]))
            return True, "Password updated."
    except (sqlite3.Error, OSError, TypeError, ValueError):
        return False, _DB_ERROR
