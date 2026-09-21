"""
Persistent settings store.

Streamlit's ``st.session_state`` is wiped every time the browser tab is
refreshed or the server restarts, so anything the organization wants to keep
is saved to disk and loaded back at the start of every new session.

Two separate files are used on purpose:

1. ``<project>/data/settings.json``  (git-ignored)
       org   -> company_name, hr_sender_name, hr_sender_title
       prefs -> seed_demo_requisition

2. ``~/.talentiq/smtp.json``  (in the user's home folder, NOT the project)
       provider, host, port, tls, sender_email, password (the app password)
   Credentials are kept out of the project folder so zipping / committing /
   sharing the project (e.g. for a hackathon submission) can't leak them. The
   file is created owner-read/write only (0600) where the OS supports it.
   The password is stored as plain text — it is protected by file permissions,
   not encryption — so always use an *app password* (revocable at any time
   from the mail provider), never the real login password.

Accounts: every function below takes an optional ``user_id``. When the app
runs with sign-in (see ``src/auth.py``) the signed-in user's id is always
passed, so each account gets its own organization identity, workspace prefs
and its own ``smtp_<id>.json`` -- one recruiter can never send mail from
another recruiter's mailbox. With ``user_id=None`` the legacy single-user
files are used.

Public deployments: credentials are still stored as plain text on the server's
disk. If you would rather not keep them there at all, set the environment
variable ``TALENTIQ_DISABLE_SAVED_SMTP=1`` and credentials will never be
written to or read from disk (they stay session-only).

Supabase-ready: pages only call the public functions below. To move
persistence to a database later, replace ``_read_json`` / ``_write_json`` /
``_delete`` — no page code needs to change.

Environment overrides:
    TALENTIQ_DATA_DIR         folder for settings.json
    TALENTIQ_SECRET_DIR       folder for smtp.json
    TALENTIQ_DISABLE_SAVED_SMTP=1   never persist SMTP credentials
"""
import json
import os
import re
import tempfile
from pathlib import Path

DEFAULT_ORG = {
    "company_name": "Your Company",
    "hr_sender_name": "HR Team",
    "hr_sender_title": "Talent Acquisition",
}

DEFAULT_PREFS = {
    # Start every new session with zero active jobs.
    # Set this to True to auto-seed the demo requisition (ML Engineer).
    "seed_demo_requisition": False,
}

DEFAULT_SMTP = {
    "provider": "Gmail",
    "host": "",
    "port": 587,
    "tls": True,
    "sender_email": "",
    "password": "",
}

_MAX_LEN = 120  # sanity cap on any single text field


# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------
def _data_dir() -> Path:
    override = os.environ.get("TALENTIQ_DATA_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "data"


def _secret_dir() -> Path:
    override = os.environ.get("TALENTIQ_SECRET_DIR")
    if override:
        return Path(override)
    return Path.home() / ".talentiq"


def data_dir() -> Path:
    """Public alias so other modules (auth) can share the same data folder."""
    return _data_dir()


def settings_path() -> Path:
    return _data_dir() / "settings.json"


def smtp_path(user_id=None) -> Path:
    if user_id is None:
        return _secret_dir() / "smtp.json"
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", str(user_id))
    return _secret_dir() / f"smtp_{safe_id}.json"


# --------------------------------------------------------------------------
# Storage backend (swap these three for Supabase later)
# --------------------------------------------------------------------------
def _read_json(path: Path) -> dict:
    """Return the stored dict, or {} if missing / unreadable / corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict, private: bool = False) -> bool:
    """Atomically write the dict. Returns False if the disk isn't writable.
    ``mkstemp`` creates the temp file owner-only (0600), and ``os.replace``
    keeps that mode, so private files never exist with looser permissions."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if private:
            try:
                os.chmod(path.parent, 0o700)
            except OSError:
                pass
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp_name, path)  # atomic: never leaves a half-written file
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return True
    except OSError:
        return False


def _delete(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _read() -> dict:
    return _read_json(settings_path())


def _write(data: dict) -> bool:
    return _write_json(settings_path(), data)


def _scope_read(data: dict, user_id) -> dict:
    """The part of settings.json that belongs to ``user_id`` (or the legacy
    top level when ``user_id`` is None)."""
    if user_id is None:
        return data
    users = data.get("users")
    bucket = users.get(str(user_id)) if isinstance(users, dict) else None
    return bucket if isinstance(bucket, dict) else {}


def _scope_write(data: dict, user_id) -> dict:
    """Same as ``_scope_read`` but creates the user's bucket if needed."""
    if user_id is None:
        return data
    users = data.get("users")
    if not isinstance(users, dict):
        users = data["users"] = {}
    bucket = users.get(str(user_id))
    if not isinstance(bucket, dict):
        bucket = users[str(user_id)] = {}
    return bucket


# --------------------------------------------------------------------------
# Organization identity + workspace prefs
# --------------------------------------------------------------------------
def _clean_text(value, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text[:_MAX_LEN] if text else fallback


def load_org_settings(user_id=None) -> dict:
    """Saved organization identity, with defaults filling any gaps."""
    stored = _scope_read(_read(), user_id).get("org", {})
    if not isinstance(stored, dict):
        stored = {}
    return {key: _clean_text(stored.get(key), default) for key, default in DEFAULT_ORG.items()}


def save_org_settings(org: dict, user_id=None) -> bool:
    """Persist organization identity. Only whitelisted keys are ever written."""
    data = _read()
    _scope_write(data, user_id)["org"] = {key: _clean_text(org.get(key), default) for key, default in DEFAULT_ORG.items()}
    return _write(data)


def load_app_prefs(user_id=None) -> dict:
    stored = _scope_read(_read(), user_id).get("prefs", {})
    if not isinstance(stored, dict):
        stored = {}
    return {
        key: bool(stored.get(key, default)) if isinstance(default, bool) else stored.get(key, default)
        for key, default in DEFAULT_PREFS.items()
    }


def save_app_prefs(prefs: dict, user_id=None) -> bool:
    data = _read()
    _scope_write(data, user_id)["prefs"] = {
        key: bool(prefs.get(key, default)) if isinstance(default, bool) else prefs.get(key, default)
        for key, default in DEFAULT_PREFS.items()
    }
    return _write(data)


# --------------------------------------------------------------------------
# SMTP credentials (email address + app password)
# --------------------------------------------------------------------------
def smtp_saving_enabled() -> bool:
    """False when the deployment has opted out of persisting credentials."""
    return os.environ.get("TALENTIQ_DISABLE_SAVED_SMTP", "").strip().lower() not in {"1", "true", "yes", "on"}


def _clean_smtp(cfg: dict) -> dict:
    cfg = cfg if isinstance(cfg, dict) else {}
    try:
        port = int(cfg.get("port", DEFAULT_SMTP["port"]))
        if not 1 <= port <= 65535:
            port = DEFAULT_SMTP["port"]
    except (TypeError, ValueError):
        port = DEFAULT_SMTP["port"]
    tls = cfg.get("tls", DEFAULT_SMTP["tls"])
    return {
        "provider": _clean_text(cfg.get("provider"), DEFAULT_SMTP["provider"]),
        "host": _clean_text(cfg.get("host"), ""),
        "port": port,
        "tls": bool(tls),
        "sender_email": _clean_text(cfg.get("sender_email"), ""),
        # no length cap / no strip surprises beyond whitespace: app passwords can be 16+ chars
        "password": str(cfg.get("password") or "").strip(),
    }


def has_saved_smtp(user_id=None) -> bool:
    if not smtp_saving_enabled():
        return False
    saved = _read_json(smtp_path(user_id))
    return bool(saved.get("sender_email") or saved.get("password"))


def load_smtp_config(user_id=None) -> dict:
    """Saved SMTP settings (defaults if none saved or saving is disabled)."""
    if not smtp_saving_enabled():
        return dict(DEFAULT_SMTP)
    return _clean_smtp({**DEFAULT_SMTP, **_read_json(smtp_path(user_id))})


def save_smtp_config(cfg: dict, user_id=None) -> bool:
    """Persist SMTP settings to the private credentials file. Returns False
    if saving is disabled for this deployment or the disk isn't writable."""
    if not smtp_saving_enabled():
        return False
    return _write_json(smtp_path(user_id), _clean_smtp(cfg), private=True)


def clear_smtp_config(user_id=None) -> bool:
    """Delete any saved SMTP credentials from disk. A no-op when the deployment
    has disabled credential storage (the disk is never touched in that mode)."""
    if not smtp_saving_enabled():
        return True
    return _delete(smtp_path(user_id))
