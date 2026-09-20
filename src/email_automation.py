"""
Candidate email automation.

Lets HR send a real email straight from the Candidate Intelligence screen
when a candidate is Shortlisted / moved to Interview / Rejected — using the
recruiter's own SMTP credentials (entered in Settings and, if the user
chooses, remembered in a private file in their home folder — see
src/settings_store.py). If no SMTP is configured, HR can still download a
ready-to-send .eml file and open it in their own mail client.

Uses only the Python standard library (smtplib/email) — no extra dependency.
"""
import smtplib
import ssl
from email.message import EmailMessage

SMTP_PRESETS = {
    "Gmail": {"host": "smtp.gmail.com", "port": 587, "tls": True},
    "Outlook / Office 365": {"host": "smtp.office365.com", "port": 587, "tls": True},
    "Yahoo Mail": {"host": "smtp.mail.yahoo.com", "port": 587, "tls": True},
    "Custom": {"host": "", "port": 587, "tls": True},
}

TEMPLATES = {
    "Selection / Offer": {
        "subject": "You've been selected — {job_title} at {company_name}",
        "body": (
            "Dear {candidate_name},\n\n"
            "Congratulations! We're pleased to let you know that you have been "
            "selected to move forward as our candidate of choice for the "
            "{job_title} position at {company_name}.\n\n"
            "Our team was impressed with your background, and we'd like to "
            "schedule a call to discuss next steps and formalize the offer. "
            "Please let us know a few times that work for you this week.\n\n"
            "Congratulations again — we're looking forward to having you on the team.\n\n"
            "Best regards,\n"
            "{hr_sender_name}\n"
            "{hr_sender_title}, {company_name}"
        ),
    },
    "Interview Invitation": {
        "subject": "Interview invitation — {job_title} at {company_name}",
        "body": (
            "Dear {candidate_name},\n\n"
            "Thank you for applying for the {job_title} role at {company_name}. "
            "After reviewing your application, we'd like to invite you to the "
            "next stage — an interview with our team.\n\n"
            "Could you share a few time windows over the next week that work for you? "
            "We'll confirm a slot and send calendar details.\n\n"
            "Looking forward to speaking with you.\n\n"
            "Best regards,\n"
            "{hr_sender_name}\n"
            "{hr_sender_title}, {company_name}"
        ),
    },
    "Rejection": {
        "subject": "Update on your application — {job_title} at {company_name}",
        "body": (
            "Dear {candidate_name},\n\n"
            "Thank you for taking the time to apply for the {job_title} role at "
            "{company_name}, and for your interest in joining our team.\n\n"
            "After careful review, we've decided to move forward with other "
            "candidates for this particular role. This isn't a reflection of "
            "your qualifications, and we'd encourage you to apply again for "
            "future roles that match your experience.\n\n"
            "We wish you the very best in your job search.\n\n"
            "Best regards,\n"
            "{hr_sender_name}\n"
            "{hr_sender_title}, {company_name}"
        ),
    },
}

ACTION_TO_DEFAULT_TEMPLATE = {
    "Shortlisted": "Selection / Offer",
    "Review": "Interview Invitation",
    "Rejected": "Rejection",
}


def render_template(template_key: str, context: dict) -> tuple:
    """Fill a template with context, tolerating missing keys (left as blanks
    rather than raising) since this is user-facing draft text, not code."""
    tpl = TEMPLATES.get(template_key, TEMPLATES["Selection / Offer"])
    safe_ctx = {
        "candidate_name": context.get("candidate_name") or "Candidate",
        "job_title": context.get("job_title") or "the role",
        "company_name": context.get("company_name") or "our company",
        "hr_sender_name": context.get("hr_sender_name") or "HR Team",
        "hr_sender_title": context.get("hr_sender_title") or "HR Team",
    }
    subject = tpl["subject"].format(**safe_ctx)
    body = tpl["body"].format(**safe_ctx)
    return subject, body


def send_email_smtp(smtp_config: dict, to_email: str, subject: str, body: str) -> tuple:
    """Send via the recruiter's own SMTP account. Returns (success, message).
    Never raises — all failures are caught and surfaced as a message so a
    bad password doesn't crash the screening session."""
    host = (smtp_config or {}).get("host", "").strip()
    port = (smtp_config or {}).get("port", 587)
    use_tls = (smtp_config or {}).get("tls", True)
    sender_email = (smtp_config or {}).get("sender_email", "").strip()
    password = (smtp_config or {}).get("password", "")

    if not host or not sender_email or not password:
        return False, "SMTP isn't fully configured yet — add your email settings in ⚙️ Settings first."
    if not to_email or to_email == "Not detected":
        return False, "This candidate has no detected email address to send to."

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = to_email
    msg.set_content(body)

    try:
        if use_tls:
            with smtplib.SMTP(host, int(port), timeout=20) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(sender_email, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP_SSL(host, int(port), timeout=20, context=ssl.create_default_context()) as server:
                server.login(sender_email, password)
                server.send_message(msg)
        return True, f"Email sent to {to_email}."
    except smtplib.SMTPAuthenticationError:
        return False, "Authentication failed — check your email/app password in Settings."
    except Exception as e:
        return False, f"Couldn't send the email: {e}"


def build_eml_bytes(sender_email: str, to_email: str, subject: str, body: str) -> bytes:
    """Build a standalone .eml file the HR user can open in Outlook/Gmail/Mail
    directly, for when SMTP isn't configured (or as an audit copy)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender_email or "hr@yourcompany.com"
    msg["To"] = to_email if to_email and to_email != "Not detected" else ""
    msg.set_content(body)
    return msg.as_bytes()
