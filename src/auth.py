"""
Account backend for TalentIQ using Supabase Auth.

Replaces SQLite completely. All authentication (sign-up, sign-in, session management,
and password management) is handled by Supabase Auth (GoTrue).
"""
import re
from typing import Optional, Tuple, Dict, Any

from . import db

MAX_NAME_LEN = 80
MAX_EMAIL_LEN = 254
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 128

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")


def normalize_email(email: Any) -> str:
    return str(email or "").strip().lower()


def validate_email(email: str) -> Optional[str]:
    """Return an error message, or None if the email looks valid."""
    if not email:
        return "Enter your email address."
    if len(email) > MAX_EMAIL_LEN or not _EMAIL_RE.match(email):
        return "That doesn't look like a valid email address."
    return None


def validate_name(name: str) -> Optional[str]:
    if len(name) < 2:
        return "Enter your full name."
    if len(name) > MAX_NAME_LEN:
        return f"Name is too long (max {MAX_NAME_LEN} characters)."
    return None


def validate_password(password: str) -> Optional[str]:
    if len(password) < 6:
        return "Password must be at least 6 characters."
    if len(password) > MAX_PASSWORD_LEN:
        return f"Password is too long (max {MAX_PASSWORD_LEN} characters)."
    return None


def _format_user(user_obj: Any) -> Dict[str, str]:
    """Extract standard user dictionary from a Supabase User object or dict."""
    if not user_obj:
        return {}

    uid = getattr(user_obj, "id", None) or user_obj.get("id", "")
    email = getattr(user_obj, "email", None) or user_obj.get("email", "")
    meta = getattr(user_obj, "user_metadata", None) or user_obj.get("user_metadata", {}) or {}

    name = meta.get("full_name") or meta.get("name") or (email.split("@")[0] if email else "Recruiter")

    return {
        "id": str(uid),
        "email": str(email),
        "name": str(name),
    }


def sign_up(full_name: str, email: str, password: str, confirm: str) -> Tuple[bool, str, Optional[Dict]]:
    """Register a new user through Supabase Auth."""
    name = " ".join(str(full_name or "").split())
    email = normalize_email(email)
    password = str(password or "")

    name_err = validate_name(name)
    if name_err:
        return False, name_err, None

    email_err = validate_email(email)
    if email_err:
        return False, email_err, None

    pw_err = validate_password(password)
    if pw_err:
        return False, pw_err, None

    if password != str(confirm or ""):
        return False, "The two passwords don't match.", None

    client = db.get_client()
    if not client:
        return False, "Supabase client is not configured. Please check SUPABASE_URL and SUPABASE_KEY.", None

    try:
        res = client.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {
                    "full_name": name,
                    "name": name,
                }
            }
        })

        if not res.user:
            return False, "Failed to create account in Supabase.", None

        user_dict = _format_user(res.user)

        # If email confirmation is enabled, session is None
        if not res.session:
            return (
                True,
                "Account created! If confirmation is required by your Supabase project, check your email before signing in.",
                user_dict
            )

        return True, "Account created successfully.", user_dict

    except Exception as e:
        err_msg = str(e)
        if "User already registered" in err_msg or "already exists" in err_msg.lower():
            return False, "An account with this email already exists. Try signing in instead.", None
        return False, f"Sign-up error: {err_msg}", None


def sign_in(email: str, password: str) -> Tuple[bool, str, Optional[Dict]]:
    """Sign in an existing user with Supabase Auth."""
    email = normalize_email(email)
    password = str(password or "")

    if not email or not password:
        return False, "Enter your email and password.", None

    client = db.get_client()
    if not client:
        return False, "Supabase client is not configured. Please check SUPABASE_URL and SUPABASE_KEY.", None

    try:
        res = client.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })

        if not res.user:
            return False, "Incorrect email or password.", None

        user_dict = _format_user(res.user)
        return True, "Signed in successfully.", user_dict

    except Exception as e:
        err_msg = str(e)
        if "Invalid login credentials" in err_msg:
            return False, "Incorrect email or password.", None
        if "Email not confirmed" in err_msg:
            return False, "Email not confirmed. Please check your inbox or disable email confirmation in Supabase.", None
        return False, f"Sign-in error: {err_msg}", None


def sign_out() -> bool:
    """Sign out the current user session from Supabase."""
    client = db.get_client()
    if not client:
        return True
    try:
        client.auth.sign_out()
        return True
    except Exception:
        return True


def get_user(user_id: str) -> Optional[Dict]:
    """Retrieve current user details from Supabase Auth."""
    client = db.get_client()
    if not client:
        return None
    try:
        res = client.auth.get_user()
        if res and res.user:
            return _format_user(res.user)
    except Exception:
        pass
    return None


def change_password(*args, **kwargs) -> Tuple[bool, str]:
    """Update user password via Supabase Auth.
    Accepts either (user_id, current_password, new_password, confirm) or (current_password, new_password, confirm).
    """
    if len(args) == 4:
        _, current_password, new_password, confirm = args
    elif len(args) == 3:
        current_password, new_password, confirm = args
    else:
        current_password = kwargs.get("current_password", "")
        new_password = kwargs.get("new_password", "")
        confirm = kwargs.get("confirm", "")

    new_password = str(new_password or "")
    if new_password != str(confirm or ""):
        return False, "The two new passwords don't match."

    pw_err = validate_password(new_password)
    if pw_err:
        return False, pw_err

    client = db.get_client()
    if not client:
        return False, "Supabase client is not configured."

    try:
        client.auth.update_user({"password": new_password})
        return True, "Password updated successfully."
    except Exception as e:
        return False, f"Could not update password: {e}"


def reset_password_request(email: str) -> Tuple[bool, str]:
    """Send a password reset email via Supabase Auth."""
    email = normalize_email(email)
    email_err = validate_email(email)
    if email_err:
        return False, email_err

    client = db.get_client()
    if not client:
        return False, "Supabase client is not configured."

    try:
        client.auth.reset_password_for_email(email)
        return True, "Password reset instructions have been sent if the email exists."
    except Exception as e:
        return False, f"Password reset failed: {e}"
