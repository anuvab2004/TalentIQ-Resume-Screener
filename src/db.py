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


_HAS_USER_ID_COLUMN = None


def _supports_user_id_column(client) -> bool:
    """Check if public.requisitions has a user_id column in Supabase."""
    global _HAS_USER_ID_COLUMN
    if _HAS_USER_ID_COLUMN is None:
        try:
            client.table("requisitions").select("user_id").limit(1).execute()
            _HAS_USER_ID_COLUMN = True
        except Exception:
            _HAS_USER_ID_COLUMN = False
    return _HAS_USER_ID_COLUMN


def _scoped_req_id(req_id: str, user_id: Optional[str] = None) -> str:
    """Namespace a requisition ID to the tenant so different companies never collide in Postgres."""
    if not user_id or not req_id:
        return req_id
    prefix = f"{user_id}__"
    if req_id.startswith(prefix):
        return req_id
    return f"{prefix}{req_id}"


def _unscoped_req_id(db_req_id: str, user_id: Optional[str] = None) -> str:
    """Strip the tenant prefix from a requisition ID so the UI displays clean local IDs (e.g. 'req_1')."""
    if not user_id or not db_req_id:
        return db_req_id
    prefix = f"{user_id}__"
    if db_req_id.startswith(prefix):
        return db_req_id[len(prefix):]
    return db_req_id


# --------------------------------------------------------------------------
# Requisitions
# --------------------------------------------------------------------------
def fetch_requisitions(user_id: Optional[str] = None) -> Dict[str, dict]:
    """Load requisitions belonging exclusively to user_id from Supabase."""
    client = get_client()
    if not client or not user_id:
        return {}
    try:
        query = client.table("requisitions").select("*")
        if _supports_user_id_column(client):
            query = query.eq("user_id", user_id)
        else:
            query = query.like("id", f"{user_id}__%")
        res = query.order("created_at").execute()
        reqs = {}
        rows: Any = res.data or []
        for r in rows:
            created = r.get("created_at")
            if isinstance(created, str):
                try:
                    created = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except Exception:
                    created = datetime.now()
            local_id = _unscoped_req_id(r["id"], user_id)
            reqs[local_id] = {
                "id": local_id,
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


def save_requisition(req: dict, user_id: Optional[str] = None) -> bool:
    """Insert or update a requisition in Supabase scoped to user_id."""
    client = get_client()
    if not client:
        return False
    try:
        created_at = req.get("created_at")
        if isinstance(created_at, datetime):
            created_str = created_at.isoformat()
        else:
            created_str = datetime.now().isoformat()

        db_id = _scoped_req_id(req["id"], user_id)
        row: Dict[str, Any] = {
            "id": db_id,
            "title": req["title"],
            "department": req["department"],
            "jd_text": req["jd_text"],
            "required_skills": req.get("required_skills") or [],
            "min_years": float(req.get("min_years") or 0),
            "required_education": req.get("required_education") or "Not detected",
            "created_at": created_str,
        }
        if user_id and _supports_user_id_column(client):
            row["user_id"] = user_id

        client.table("requisitions").upsert(row, on_conflict="id").execute()
        return True
    except Exception:
        return False


def delete_requisition(req_id: str, user_id: Optional[str] = None) -> bool:
    """Delete a requisition (and cascades to its candidates/guides/logs) scoped to user_id."""
    client = get_client()
    if not client:
        return False
    try:
        db_id = _scoped_req_id(req_id, user_id)
        client.table("email_logs").delete().eq("req_id", db_id).execute()
        client.table("interview_guides").delete().eq("req_id", db_id).execute()
        client.table("candidates").delete().eq("req_id", db_id).execute()
        client.table("requisitions").delete().eq("id", db_id).execute()
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Candidates & Screening Results
# --------------------------------------------------------------------------
def fetch_results(req_id: str, user_id: Optional[str] = None) -> list:
    """Fetch screening results for a requisition scoped to user_id as MatchResult instances."""
    client = get_client()
    if not client:
        return []
    try:
        from .matcher import MatchResult, make_candidate_id
        db_id = _scoped_req_id(req_id, user_id)
        res = client.table("candidates").select("*").eq("req_id", db_id).order("overall_score", desc=True).execute()
        results = []
        rows: Any = res.data or []
        for idx, row in enumerate(rows, start=1):
            fname = row.get("filename") or ""
            cname = row.get("candidate_name") or ""
            cemail = row.get("email") or ""
            cphone = row.get("phone") or ""
            cid = row.get("candidate_id") or make_candidate_id(fname, cname, cemail, cphone) or f"cand_{idx}"
            factors = row.get("factors") or {}
            raw_text = factors.get("raw_text") or row.get("raw_text") or ""
            if not raw_text and fname:
                try:
                    from .sample_data import list_sample_resumes, load_sample_resume_bytes
                    if fname in list_sample_resumes():
                        raw_text = load_sample_resume_bytes(fname).decode("utf-8", errors="replace")
                except Exception:
                    pass

            mr = MatchResult(
                candidate_id=cid,
                candidate_name=cname,
                overall_score=float(row.get("overall_score") or 0),
                factors=factors,
                matched_skills=row.get("matched_skills") or [],
                missing_skills=row.get("missing_skills") or [],
                extra_skills=row.get("extra_skills") or [],
                status=row.get("status") or "Review",
                rationale=row.get("rationale") or "",
                filename=fname,
                email=cemail or "Not detected",
                phone=cphone or "Not detected",
                education=row.get("education") or "Not detected",
                years_experience=float(row.get("years_experience") or 0),
                experience_months=int(row.get("experience_months") or factors.get("experience_months") or round(float(row.get("years_experience") or 0) * 12)),
                fairness_audit=row.get("fairness_audit") or {},
                semantic_engine=row.get("semantic_engine") or "tfidf",
                raw_text=raw_text,
            )
            results.append(mr)
        return results
    except Exception:
        return []


def upload_resume_file(filename: str, file_bytes: bytes, req_id: str = "general", user_id: Optional[str] = None) -> Optional[str]:
    """Upload a resume file to the Supabase storage bucket isolated by tenant path.
    Returns the storage path / identifier if successful, else None."""
    client = get_client()
    if not client:
        return None

    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
    clean_req = _unscoped_req_id(req_id, user_id)
    if user_id:
        storage_path = f"{user_id}/{clean_req}/{safe_name}"
    else:
        storage_path = f"{clean_req}/{safe_name}"

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


def download_resume_file(filename: str, req_id: str = "general", user_id: Optional[str] = None) -> Optional[bytes]:
    """Download resume file bytes from Supabase storage isolated by tenant path."""
    client = get_client()
    if not client or not filename:
        return None

    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
    clean_req = _unscoped_req_id(req_id, user_id)
    paths_to_try = []
    if user_id:
        paths_to_try.append(f"{user_id}/{clean_req}/{safe_name}")
    paths_to_try.append(f"{clean_req}/{safe_name}")
    paths_to_try.append(safe_name)

    candidate_buckets = ["resumes", "Resumes", "resume", "Resume"]
    for bucket in candidate_buckets:
        for p in paths_to_try:
            try:
                data = client.storage.from_(bucket).download(p)
                if data:
                    return data
            except Exception:
                continue
    return None


def save_results(req_id: str, results: list, existing_actions: Optional[Dict] = None, user_id: Optional[str] = None) -> bool:
    """Batch upsert candidate screening results into Supabase scoped to user_id."""
    client = get_client()
    if not client or not results:
        return False
    try:
        db_id = _scoped_req_id(req_id, user_id)
        has_uid = user_id and _supports_user_id_column(client)
        rows = []
        for r in results:
            hr_status = "—"
            clean_req = _unscoped_req_id(req_id, user_id)
            if existing_actions and (clean_req, r.candidate_name) in existing_actions:
                hr_status = existing_actions[(clean_req, r.candidate_name)]
            elif existing_actions and (req_id, r.candidate_name) in existing_actions:
                hr_status = existing_actions[(req_id, r.candidate_name)]

            factors_dict = dict(r.factors or {})
            if getattr(r, "raw_text", None):
                factors_dict["raw_text"] = r.raw_text
            if getattr(r, "experience_months", None) is not None:
                factors_dict["experience_months"] = r.experience_months

            row: Dict[str, Any] = {
                "req_id": db_id,
                "candidate_name": r.candidate_name,
                "filename": r.filename,
                "email": r.email,
                "phone": r.phone,
                "education": r.education,
                "years_experience": float(r.years_experience or 0),
                "overall_score": float(r.overall_score),
                "status": r.status,
                "rationale": r.rationale,
                "factors": factors_dict,
                "matched_skills": r.matched_skills or [],
                "missing_skills": r.missing_skills or [],
                "extra_skills": r.extra_skills or [],
                "fairness_audit": r.fairness_audit or {},
                "semantic_engine": r.semantic_engine or "tfidf",
                "hr_status": hr_status,
            }
            if has_uid:
                row["user_id"] = user_id
            rows.append(row)
        
        # Upsert in chunks of 50 to respect payload limits
        for i in range(0, len(rows), 50):
            chunk = rows[i:i + 50]
            client.table("candidates").upsert(chunk, on_conflict="req_id,candidate_name").execute()
        return True
    except Exception as e:
        print(f"[Supabase] save_results error: {e}")
        return False


def delete_candidates_for_requisition(req_id: str, user_id: Optional[str] = None) -> bool:
    """Delete all candidate records, interview guides, and email logs for a requisition scoped to user_id."""
    client = get_client()
    if not client:
        return False
    try:
        db_id = _scoped_req_id(req_id, user_id)
        client.table("email_logs").delete().eq("req_id", db_id).execute()
        client.table("interview_guides").delete().eq("req_id", db_id).execute()
        client.table("candidates").delete().eq("req_id", db_id).execute()
        return True
    except Exception as e:
        print(f"[Supabase] delete_candidates_for_requisition error: {e}")
        return False


def delete_candidate(req_id: str, candidate_name: str, user_id: Optional[str] = None) -> bool:
    """Delete a single candidate and associated interview guides and email logs scoped to user_id."""
    client = get_client()
    if not client:
        return False
    try:
        db_id = _scoped_req_id(req_id, user_id)
        client.table("email_logs").delete().eq("req_id", db_id).eq("candidate_name", candidate_name).execute()
        client.table("interview_guides").delete().eq("req_id", db_id).eq("candidate_name", candidate_name).execute()
        client.table("candidates").delete().eq("req_id", db_id).eq("candidate_name", candidate_name).execute()
        return True
    except Exception as e:
        print(f"[Supabase] delete_candidate error: {e}")
        return False


def update_candidate_action(req_id: str, candidate_name: str, action: str, user_id: Optional[str] = None) -> bool:
    """Update HR status (Shortlisted/Review/Rejected) in Supabase scoped to user_id."""
    client = get_client()
    if not client:
        return False
    try:
        db_id = _scoped_req_id(req_id, user_id)
        client.table("candidates").update({"hr_status": action})\
            .eq("req_id", db_id)\
            .eq("candidate_name", candidate_name)\
            .execute()
        return True
    except Exception:
        return False


def update_candidate_experience(req_id: str, candidate_name: str, years_exp: float, exp_months: int, user_id: Optional[str] = None) -> bool:
    """Update verified candidate experience in Supabase scoped to user_id."""
    client = get_client()
    if not client:
        return False
    try:
        db_id = _scoped_req_id(req_id, user_id)
        client.table("candidates").update({
            "years_experience": years_exp,
            "experience_months": exp_months
        })\
            .eq("req_id", db_id)\
            .eq("candidate_name", candidate_name)\
            .execute()
        return True
    except Exception:
        return False


def fetch_all_candidate_actions(user_id: Optional[str] = None) -> Dict[Tuple[str, str], str]:
    """Fetch HR actions mapping (req_id, candidate_name) -> status scoped to user_id."""
    client = get_client()
    if not client or not user_id:
        return {}
    try:
        query = client.table("candidates").select("req_id, candidate_name, hr_status")
        if _supports_user_id_column(client):
            query = query.eq("user_id", user_id)
        else:
            query = query.like("req_id", f"{user_id}__%")
        res = query.execute()
        actions = {}
        rows: Any = res.data or []
        for r in rows:
            st = r.get("hr_status")
            if st and st != "—":
                local_req_id = _unscoped_req_id(r["req_id"], user_id)
                actions[(local_req_id, r["candidate_name"])] = st
        return actions
    except Exception:
        return {}


# --------------------------------------------------------------------------
# Interview Guides
# --------------------------------------------------------------------------
def fetch_all_interview_guides(user_id: Optional[str] = None) -> Dict[Tuple[str, str], list]:
    """Fetch saved interview guides mapping (req_id, candidate_name) -> list of questions scoped to user_id."""
    client = get_client()
    if not client or not user_id:
        return {}
    try:
        query = client.table("interview_guides").select("req_id, candidate_name, questions")
        if _supports_user_id_column(client):
            query = query.eq("user_id", user_id)
        else:
            query = query.like("req_id", f"{user_id}__%")
        res = query.execute()
        guides = {}
        rows: Any = res.data or []
        for r in rows:
            local_req_id = _unscoped_req_id(r["req_id"], user_id)
            guides[(local_req_id, r["candidate_name"])] = r.get("questions") or []
        return guides
    except Exception:
        return {}


def save_interview_guide(req_id: str, candidate_name: str, questions: list, user_id: Optional[str] = None) -> bool:
    """Save an interview guide to Supabase scoped to user_id."""
    client = get_client()
    if not client:
        return False
    try:
        db_id = _scoped_req_id(req_id, user_id)
        row: Dict[str, Any] = {
            "req_id": db_id,
            "candidate_name": candidate_name,
            "questions": questions,
        }
        if user_id and _supports_user_id_column(client):
            row["user_id"] = user_id
        client.table("interview_guides").upsert(row, on_conflict="req_id,candidate_name").execute()
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Email Logs
# --------------------------------------------------------------------------
def fetch_all_email_logs(user_id: Optional[str] = None) -> Dict[Tuple[str, str], list]:
    """Fetch email log status messages mapping (req_id, candidate_name) -> list[str] scoped to user_id."""
    client = get_client()
    if not client or not user_id:
        return {}
    try:
        query = client.table("email_logs").select("req_id, candidate_name, status_message")
        if _supports_user_id_column(client):
            query = query.eq("user_id", user_id)
        else:
            query = query.like("req_id", f"{user_id}__%")
        res = query.order("created_at").execute()
        logs = {}
        rows: Any = res.data or []
        for r in rows:
            local_req_id = _unscoped_req_id(r["req_id"], user_id)
            key = (local_req_id, r["candidate_name"])
            logs.setdefault(key, []).append(r["status_message"])
        return logs
    except Exception:
        return {}


def save_email_log(req_id: str, candidate_name: str, message: str, user_id: Optional[str] = None) -> bool:
    """Record an email sending event in Supabase scoped to user_id."""
    client = get_client()
    if not client:
        return False
    try:
        db_id = _scoped_req_id(req_id, user_id)
        row: Dict[str, Any] = {
            "req_id": db_id,
            "candidate_name": candidate_name,
            "status_message": message,
        }
        if user_id and _supports_user_id_column(client):
            row["user_id"] = user_id
        client.table("email_logs").insert(row).execute()
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Full Reset
# --------------------------------------------------------------------------
def reset_all_data(user_id: Optional[str] = None) -> bool:
    """Deletes all data belonging exclusively to user_id in Supabase."""
    client = get_client()
    if not client or not user_id:
        return False
    try:
        if _supports_user_id_column(client):
            client.table("email_logs").delete().eq("user_id", user_id).execute()
            client.table("interview_guides").delete().eq("user_id", user_id).execute()
            client.table("candidates").delete().eq("user_id", user_id).execute()
            client.table("requisitions").delete().eq("user_id", user_id).execute()
        else:
            prefix = f"{user_id}__%"
            client.table("email_logs").delete().like("req_id", prefix).execute()
            client.table("interview_guides").delete().like("req_id", prefix).execute()
            client.table("candidates").delete().like("req_id", prefix).execute()
            client.table("requisitions").delete().like("id", prefix).execute()
        return True
    except Exception:
        return False

