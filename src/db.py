"""
Database persistence layer for TalentIQ using Supabase.

Provides direct cloud PostgreSQL persistence for:
- Requisitions (public.requisitions)
- Candidates / Screening results (public.candidates)
- Interview Guides (public.interview_guides)
- Candidate Email Logs (public.email_logs)
- Resume document files (Supabase Storage)
"""
import os
import re
import mimetypes
from datetime import datetime
from typing import Optional, Tuple, Dict, List, Any

# Attempt to load local .env file if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_CLIENT = None
_CLIENT_CREDS = None


def get_credentials() -> Tuple[str, str]:
    """Retrieve Supabase URL and Key from session state, streamlit secrets,
    or environment variables."""
    url = ""
    key = ""

    # 1. Check Streamlit session_state override
    try:
        import streamlit as st
        if "supabase_url" in st.session_state and st.session_state["supabase_url"]:
            url = st.session_state["supabase_url"].strip()
        if "supabase_key" in st.session_state and st.session_state["supabase_key"]:
            key = st.session_state["supabase_key"].strip()
    except Exception:
        pass

    # 2. Check Streamlit secrets
    if not url or not key:
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                url = url or st.secrets.get("SUPABASE_URL", "")
                key = key or st.secrets.get("SUPABASE_KEY", "")
        except Exception:
            pass

    # 3. Check environment variables
    url = (url or os.environ.get("SUPABASE_URL", "")).strip()
    key = (key or os.environ.get("SUPABASE_KEY", "")).strip()

    return url, key


def is_configured() -> bool:
    """Return True if both URL and Key are provided."""
    url, key = get_credentials()
    return bool(url and key and url.startswith("http"))


def get_client():
    """Returns a cached Supabase client or None if not configured or failed."""
    global _CLIENT, _CLIENT_CREDS
    url, key = get_credentials()
    if not url or not key or not url.startswith("http"):
        return None

    if _CLIENT is not None and _CLIENT_CREDS == (url, key):
        return _CLIENT

    try:
        from supabase import create_client
        _CLIENT = create_client(url, key)
        _CLIENT_CREDS = (url, key)
        return _CLIENT
    except Exception:
        return None


def test_connection() -> Tuple[bool, str]:
    """Test connectivity to Supabase by querying the requisitions table."""
    if not is_configured():
        return False, "Supabase credentials are not set."
    client = get_client()
    if client is None:
        return False, "Could not initialize Supabase client. Check your URL and Key."
    try:
        client.table("requisitions").select("id").limit(1).execute()
        return True, "Successfully connected to Supabase!"
    except Exception as e:
        return False, f"Connection failed: {e}"


# --------------------------------------------------------------------------
# Requisitions
# --------------------------------------------------------------------------
def fetch_requisitions() -> Dict[str, dict]:
    """Load all requisitions from Supabase."""
    client = get_client()
    if not client:
        return {}
    try:
        res = client.table("requisitions").select("*").order("created_at").execute()
        reqs = {}
        rows: Any = res.data or []
        for r in rows:
            created = r.get("created_at")
            if isinstance(created, str):
                try:
                    created = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except Exception:
                    created = datetime.now()
            reqs[r["id"]] = {
                "id": r["id"],
                "title": r["title"],
                "department": r["department"],
                "jd_text": r["jd_text"],
                "required_skills": r.get("required_skills") or [],
                "min_years": float(r.get("min_years") or 0),
                "required_education": r.get("required_education") or "Not detected",
                "created_at": created or datetime.now(),
            }
        return reqs
    except Exception:
        return {}


def save_requisition(req: dict) -> bool:
    """Insert or update a requisition in Supabase."""
    client = get_client()
    if not client:
        return False
    try:
        created_at = req.get("created_at")
        if isinstance(created_at, datetime):
            created_str = created_at.isoformat()
        else:
            created_str = datetime.now().isoformat()

        row = {
            "id": req["id"],
            "title": req["title"],
            "department": req["department"],
            "jd_text": req["jd_text"],
            "required_skills": req.get("required_skills") or [],
            "min_years": float(req.get("min_years") or 0),
            "required_education": req.get("required_education") or "Not detected",
            "created_at": created_str,
        }
        client.table("requisitions").upsert(row, on_conflict="id").execute()
        return True
    except Exception:
        return False


def delete_requisition(req_id: str) -> bool:
    """Delete a requisition (and cascades to its candidates/guides/logs)."""
    client = get_client()
    if not client:
        return False
    try:
        client.table("requisitions").delete().eq("id", req_id).execute()
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Candidates & Screening Results
# --------------------------------------------------------------------------
def fetch_results(req_id: str) -> list:
    """Fetch screening results for a requisition as MatchResult instances."""
    client = get_client()
    if not client:
        return []
    try:
        from .matcher import MatchResult
        res = client.table("candidates").select("*").eq("req_id", req_id).order("overall_score", desc=True).execute()
        results = []
        rows: Any = res.data or []
        for row in rows:
            mr = MatchResult(
                candidate_name=row["candidate_name"],
                overall_score=float(row["overall_score"]),
                factors=row.get("factors") or {},
                matched_skills=row.get("matched_skills") or [],
                missing_skills=row.get("missing_skills") or [],
                extra_skills=row.get("extra_skills") or [],
                status=row.get("status") or "Review",
                rationale=row.get("rationale") or "",
                filename=row.get("filename") or "",
                email=row.get("email") or "Not detected",
                phone=row.get("phone") or "Not detected",
                education=row.get("education") or "Not detected",
                years_experience=float(row.get("years_experience") or 0),
                fairness_audit=row.get("fairness_audit") or {},
                semantic_engine=row.get("semantic_engine") or "tfidf",
            )
            results.append(mr)
        return results
    except Exception:
        return []


def upload_resume_file(filename: str, file_bytes: bytes, req_id: str = "general") -> Optional[str]:
    """Upload a resume file to the Supabase storage bucket ('Resumes' or 'resume').
    Returns the storage path / identifier if successful, else None."""
    client = get_client()
    if not client:
        return None

    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
    storage_path = f"{req_id}/{safe_name}"
    content_type, _ = mimetypes.guess_type(filename)
    if not content_type:
        content_type = "text/plain" if filename.endswith((".txt", ".md")) else "application/octet-stream"

    file_options: Any = {
        "content-type": content_type,
        "upsert": "true",
    }

    # Support common bucket names
    candidate_buckets = ["resumes", "Resumes", "resume", "Resume"]
    for bucket in candidate_buckets:
        try:
            client.storage.from_(bucket).upload(
                path=storage_path,
                file=file_bytes,
                file_options=file_options,
            )
            return storage_path
        except Exception as e:
            err_str = str(e)
            if "Bucket not found" in err_str or "not found" in err_str.lower():
                continue
            # Log failure details for debugging
            print(f"[Supabase Storage] Upload failed for bucket '{bucket}': {err_str}")

    return None


def save_results(req_id: str, results: list, existing_actions: Optional[Dict] = None) -> bool:
    """Batch upsert candidate screening results into Supabase."""
    client = get_client()
    if not client or not results:
        return False
    try:
        rows = []
        for r in results:
            hr_status = "—"
            if existing_actions and (req_id, r.candidate_name) in existing_actions:
                hr_status = existing_actions[(req_id, r.candidate_name)]

            rows.append({
                "req_id": req_id,
                "candidate_name": r.candidate_name,
                "filename": r.filename,
                "email": r.email,
                "phone": r.phone,
                "education": r.education,
                "years_experience": float(r.years_experience or 0),
                "overall_score": float(r.overall_score),
                "status": r.status,
                "rationale": r.rationale,
                "factors": r.factors or {},
                "matched_skills": r.matched_skills or [],
                "missing_skills": r.missing_skills or [],
                "extra_skills": r.extra_skills or [],
                "fairness_audit": r.fairness_audit or {},
                "semantic_engine": r.semantic_engine or "tfidf",
                "hr_status": hr_status,
            })
        
        # Upsert in chunks of 50 to respect payload limits
        for i in range(0, len(rows), 50):
            chunk = rows[i:i + 50]
            client.table("candidates").upsert(chunk, on_conflict="req_id,candidate_name").execute()
        return True
    except Exception as e:
        print(f"[Supabase] save_results error: {e}")
        return False


def update_candidate_action(req_id: str, candidate_name: str, action: str) -> bool:
    """Update HR status (Shortlisted/Review/Rejected) in Supabase."""
    client = get_client()
    if not client:
        return False
    try:
        client.table("candidates").update({"hr_status": action})\
            .eq("req_id", req_id)\
            .eq("candidate_name", candidate_name)\
            .execute()
        return True
    except Exception:
        return False


def fetch_all_candidate_actions() -> Dict[Tuple[str, str], str]:
    """Fetch all HR actions mapping (req_id, candidate_name) -> status."""
    client = get_client()
    if not client:
        return {}
    try:
        res = client.table("candidates").select("req_id, candidate_name, hr_status").execute()
        actions = {}
        rows: Any = res.data or []
        for r in rows:
            st = r.get("hr_status")
            if st and st != "—":
                actions[(r["req_id"], r["candidate_name"])] = st
        return actions
    except Exception:
        return {}


# --------------------------------------------------------------------------
# Interview Guides
# --------------------------------------------------------------------------
def fetch_all_interview_guides() -> Dict[Tuple[str, str], list]:
    """Fetch saved interview guides mapping (req_id, candidate_name) -> list of questions."""
    client = get_client()
    if not client:
        return {}
    try:
        res = client.table("interview_guides").select("req_id, candidate_name, questions").execute()
        guides = {}
        rows: Any = res.data or []
        for r in rows:
            guides[(r["req_id"], r["candidate_name"])] = r.get("questions") or []
        return guides
    except Exception:
        return {}


def save_interview_guide(req_id: str, candidate_name: str, questions: list) -> bool:
    """Save an interview guide to Supabase."""
    client = get_client()
    if not client:
        return False
    try:
        row = {
            "req_id": req_id,
            "candidate_name": candidate_name,
            "questions": questions,
        }
        client.table("interview_guides").upsert(row, on_conflict="req_id,candidate_name").execute()
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Email Logs
# --------------------------------------------------------------------------
def fetch_all_email_logs() -> Dict[Tuple[str, str], list]:
    """Fetch all email log status messages mapping (req_id, candidate_name) -> list[str]."""
    client = get_client()
    if not client:
        return {}
    try:
        res = client.table("email_logs").select("req_id, candidate_name, status_message").order("created_at").execute()
        logs = {}
        rows: Any = res.data or []
        for r in rows:
            key = (r["req_id"], r["candidate_name"])
            logs.setdefault(key, []).append(r["status_message"])
        return logs
    except Exception:
        return {}


def save_email_log(req_id: str, candidate_name: str, message: str) -> bool:
    """Record an email sending event in Supabase."""
    client = get_client()
    if not client:
        return False
    try:
        row = {
            "req_id": req_id,
            "candidate_name": candidate_name,
            "status_message": message,
        }
        client.table("email_logs").insert(row).execute()
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Full Reset
# --------------------------------------------------------------------------
def reset_all_data() -> bool:
    """Deletes all data across all tables in Supabase."""
    client = get_client()
    if not client:
        return False
    try:
        client.table("email_logs").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        client.table("interview_guides").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        client.table("candidates").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        client.table("requisitions").delete().neq("id", "").execute()
        return True
    except Exception:
        return False
