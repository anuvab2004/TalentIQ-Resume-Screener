"""
Matching engine: scores a parsed candidate against a parsed job description
and returns a fully explainable breakdown (per-factor contribution, matched
vs. missing skills, and a human-readable rationale) — never a bare percentage.

Weighting mirrors the AI Pipeline's published rubric:
    Semantic Relevance   50%
    Skill Alignment      30%
    Experience Evidence  15%
    Education Evidence    5%

Semantic Relevance has two backends:
  - "tfidf"      — TF-IDF cosine similarity. Zero extra dependencies, instant,
                    the default. Rewards close-but-not-identical phrasing at
                    the word level.
  - "embeddings" — sentence-transformer sentence embeddings (cosine
                    similarity in meaning-space, not just wording). Optional:
                    only used if the `sentence-transformers` package is
                    installed (see requirements-embeddings.txt) — otherwise
                    every call transparently falls back to TF-IDF.
"""
import hashlib
from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .skills_taxonomy import SKILL_TO_CATEGORY
from . import bias_checker

WEIGHTS = {
    "semantic_relevance": 0.50,
    "skill_alignment": 0.30,
    "experience_evidence": 0.15,
    "education_evidence": 0.05,
}

EDUCATION_RANK = {
    "not detected": 0,
    "high school": 1,
    "diploma": 2,
    "associate degree": 3,
    "bachelor's degree": 4,
    "master's degree": 5,
    "phd / doctorate": 6,
}

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBEDDING_MODEL = None          # lazy-loaded singleton, only if the lib is present
_EMBEDDINGS_AVAILABLE = None     # tri-state cache: None = not checked yet


@dataclass
class MatchResult:
    candidate_name: str
    overall_score: float
    factors: dict
    matched_skills: list
    missing_skills: list
    extra_skills: list
    status: str
    rationale: str
    filename: str = ""
    email: str = "Not detected"
    phone: str = "Not detected"
    linkedin_url: str = "Not detected"
    github_url: str = "Not detected"
    portfolio_url: str = "Not detected"
    education: str = "Not detected"
    years_experience: float = 0.0
    experience_months: int = 0
    fairness_audit: dict = field(default_factory=dict)
    semantic_engine: str = "tfidf"
    candidate_id: str = ""
    raw_text: str = ""
    resume_path: str = ""   # "bucket/key" of the original file in Supabase Storage ("" = not stored)


def make_candidate_id(filename: str, name: str, email: str, phone: str) -> str:
    """Stable, collision-resistant key for a screened candidate — used instead
    of the raw display name so two "John Smith" resumes (or two resumes that
    both failed name detection) never share state, actions, or logs."""
    basis = f"{filename}|{name}|{email}|{phone}".encode("utf-8", errors="ignore")
    return hashlib.sha1(basis).hexdigest()[:12]


def embeddings_available() -> bool:
    """Whether sentence-transformers is importable in this environment.
    Cached so we only pay the import-probe cost once per process."""
    global _EMBEDDINGS_AVAILABLE
    if _EMBEDDINGS_AVAILABLE is None:
        try:
            import sentence_transformers  # noqa: F401
            _EMBEDDINGS_AVAILABLE = True
        except ImportError:
            _EMBEDDINGS_AVAILABLE = False
    return _EMBEDDINGS_AVAILABLE


def _get_embedding_model():
    global _EMBEDDING_MODEL

    if _EMBEDDING_MODEL is None:
        from sentence_transformers import SentenceTransformer

        _EMBEDDING_MODEL = SentenceTransformer(
            EMBEDDING_MODEL_NAME
        )

    return _EMBEDDING_MODEL


def preload_embedding_model():
    """
    Load the embedding model once when the application starts.
    Later screening calls reuse the same model from memory.
    """
    return _get_embedding_model()


def _chunk_text(text: str, max_words: int = 200) -> list:
    """Sentence-transformer models have a limited context window; split long
    resumes/JDs into word chunks and mean-pool their embeddings rather than
    silently truncating and losing the back half of the document."""
    words = text.split()
    if not words:
        return [""]
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]


def _embed_mean(text: str, model):
    import numpy as np

    chunks = _chunk_text(text)

    vecs = model.encode(
        chunks,
        show_progress_bar=False,
        normalize_embeddings=True,
        batch_size=32,
    )

    return np.mean(vecs, axis=0)

def _embed_documents_batch(texts: list, model, batch_size: int = 32):
    """Encode multiple documents efficiently.

    Long documents are split into chunks. All chunks are encoded in batches,
    then the chunk embeddings belonging to each document are mean-pooled back
    into one vector per document.
    """
    import numpy as np

    if not texts:
        return np.empty((0, 384), dtype="float32")

    all_chunks = []
    chunk_counts = []

    for text in texts:
        chunks = _chunk_text(text)
        all_chunks.extend(chunks)
        chunk_counts.append(len(chunks))

    all_vectors = model.encode(
        all_chunks,
        show_progress_bar=False,
        normalize_embeddings=True,
        batch_size=batch_size,
    )

    document_vectors = []
    start = 0

    for count in chunk_counts:
        end = start + count
        document_vectors.append(
            np.mean(all_vectors[start:end], axis=0)
        )
        start = end

    return np.asarray(document_vectors)


def _semantic_relevance_tfidf(resume_text: str, jd_text: str) -> float:
    """TF-IDF cosine similarity between full resume text and the JD text.
    This is the 'understands skills semantically' layer — it still rewards
    close-but-not-identical phrasing, unlike pure keyword matching."""
    docs = [resume_text or "", jd_text or ""]
    if not docs[0].strip() or not docs[1].strip():
        return 0.0
    try:
        vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
        tfidf = vectorizer.fit_transform(docs)
        sim = cosine_similarity(tfidf[0], tfidf[1])[0][0]
        return round(float(sim) * 100, 1)
    except ValueError:
        return 0.0


def _semantic_relevance_embeddings(resume_text: str, jd_text: str) -> float:
    """Meaning-based similarity via sentence-transformer embeddings. Falls
    back to TF-IDF on any runtime error (e.g. first-use model download
    failed because of no network) so a screening run never hard-crashes."""
    if not (resume_text or "").strip() or not (jd_text or "").strip():
        return 0.0
    try:
        import numpy as np
        model = _get_embedding_model()
        r_vec = _embed_mean(resume_text, model)
        j_vec = _embed_mean(jd_text, model)
        sim = float(np.dot(r_vec, j_vec) / (np.linalg.norm(r_vec) * np.linalg.norm(j_vec) + 1e-9))
        return round(max(sim, 0.0) * 100, 1)
    except Exception:
        return _semantic_relevance_tfidf(resume_text, jd_text)


def semantic_relevance(resume_text: str, jd_text: str, backend: str = "auto") -> tuple:
    """Returns (score_0_to_100, engine_actually_used).
    backend: "auto" (embeddings if installed, else tfidf), "tfidf", or "embeddings"."""
    if backend == "tfidf":
        return _semantic_relevance_tfidf(resume_text, jd_text), "tfidf"
    if backend == "embeddings":
        if embeddings_available():
            return _semantic_relevance_embeddings(resume_text, jd_text), "embeddings"
        return _semantic_relevance_tfidf(resume_text, jd_text), "tfidf (embeddings not installed)"
    # auto
    if embeddings_available():
        return _semantic_relevance_embeddings(resume_text, jd_text), "embeddings"
    return _semantic_relevance_tfidf(resume_text, jd_text), "tfidf"


def _skill_alignment(candidate_skills, required_skills):
    cand_set = {s.lower() for s in candidate_skills}
    req_set = {s.lower() for s in required_skills}
    if not req_set:
        # No explicit skills detected in the JD -> neutral score, don't punish.
        return 100.0, list(candidate_skills), [], list(candidate_skills)
    matched = [s for s in required_skills if s.lower() in cand_set]
    missing = [s for s in required_skills if s.lower() not in cand_set]
    extra = [s for s in candidate_skills if s.lower() not in req_set]
    score = round(len(matched) / len(req_set) * 100, 1)
    return score, matched, missing, extra


def _experience_evidence(candidate_years: float, min_years: float) -> float:
    if min_years <= 0:
        # JD didn't specify a requirement -> score on an absolute curve.
        return round(min(candidate_years / 8.0, 1.0) * 100, 1)
    return round(min(candidate_years / min_years, 1.0) * 100, 1)


def _education_evidence(candidate_education: str, required_education: str) -> float:
    cand_rank = EDUCATION_RANK.get(candidate_education.lower(), 0)
    req_rank = EDUCATION_RANK.get(required_education.lower(), 0)
    if req_rank == 0:
        # JD had no explicit education requirement.
        return 100.0 if cand_rank > 0 else 60.0
    return round(min(cand_rank / req_rank, 1.0) * 100, 1)


def _status_from_score(score: float) -> str:
    if score >= 85:
        return "Strong Match"
    if score >= 70:
        return "Good Match"
    if score >= 50:
        return "Review"
    return "Low Match"


def _build_rationale(candidate_name, matched, missing, factors, status) -> str:
    top_matches = ", ".join(matched[:4]) if matched else "no directly overlapping skills"
    lines = [
        f"{status} — driven primarily by "
        + (
            "strong semantic alignment with the role narrative"
            if factors["semantic_relevance"] >= factors["skill_alignment"]
            else "strong overlap on required skills"
        )
        + "."
    ]
    if matched:
        lines.append(f"Matched on: {top_matches}.")
    if missing:
        lines.append(f"Gaps to probe in screening: {', '.join(missing[:4])}.")
    return " ".join(lines)


def score_candidate(parsed_resume, parsed_jd, filename="", semantic_backend="auto", weights=None) -> MatchResult:
    weights = weights or WEIGHTS
    semantic, engine_used = semantic_relevance(parsed_resume.raw_text, parsed_jd["raw_text"], backend=semantic_backend)
    skill_score, matched, missing, extra = _skill_alignment(
        parsed_resume.skills, parsed_jd["required_skills"]
    )
    exp_score = _experience_evidence(parsed_resume.years_experience, parsed_jd["min_years"])
    edu_score = _education_evidence(parsed_resume.education, parsed_jd["required_education"])

    factors = {
        "semantic_relevance": semantic,
        "skill_alignment": skill_score,
        "experience_evidence": exp_score,
        "education_evidence": edu_score,
    }

    overall = round(
        sum(factors[k] * weights[k] for k in WEIGHTS), 1
    )
    status = _status_from_score(overall)
    rationale = _build_rationale(parsed_resume.name, matched, missing, factors, status)

    # The fairness audit always uses TF-IDF regardless of the chosen semantic
    # engine: it's a fast, stable sanity check on identity-field influence,
    # not the score itself, so it doesn't need — or want — the model download.
    fairness_audit = bias_checker.audit_fairness(
        parsed_resume.raw_text, parsed_jd["raw_text"],
        parsed_resume.name, parsed_resume.email, parsed_resume.phone,
        _semantic_relevance_tfidf(parsed_resume.raw_text, parsed_jd["raw_text"]),
    )

    return MatchResult(
        candidate_name=parsed_resume.name,
        overall_score=overall,
        factors=factors,
        matched_skills=matched,
        missing_skills=missing,
        extra_skills=extra,
        status=status,
        rationale=rationale,
        filename=filename,
        email=parsed_resume.email,
        phone=parsed_resume.phone,
        linkedin_url=parsed_resume.linkedin_url,
        github_url=parsed_resume.github_url,
        portfolio_url=parsed_resume.portfolio_url,
        education=parsed_resume.education,
        years_experience=parsed_resume.years_experience,
        fairness_audit=fairness_audit,
        semantic_engine=engine_used,
        candidate_id=make_candidate_id(filename, parsed_resume.name, parsed_resume.email, parsed_resume.phone),
        raw_text=parsed_resume.raw_text,
    )

def score_candidates_batch(
    parsed_resumes,
    parsed_jd,
    filenames=None,
    semantic_backend="auto",
    weights=None,
):
    """Score many parsed resumes against one JD efficiently.

    The JD embedding is calculated only once and all resume embeddings are
    generated in batches. This is much faster than calling score_candidate()
    separately for every resume.
    """
    import numpy as np

    weights = weights or WEIGHTS
    filenames = filenames or [""] * len(parsed_resumes)

    # ---------------------------------------------------------
    # Decide which semantic engine to use
    # ---------------------------------------------------------
    use_embeddings = (
        semantic_backend in ("auto", "embeddings")
        and embeddings_available()
    )

    model = None
    jd_vector = None
    resume_vectors = None

    if use_embeddings:
        try:
            model = _get_embedding_model()

            # Encode JD ONLY ONCE.
            jd_vector = _embed_mean(
                parsed_jd["raw_text"],
                model
            )

            # Encode ALL resumes in batches.
            resume_vectors = _embed_documents_batch(
                [resume.raw_text for resume in parsed_resumes],
                model,
                batch_size=32,
            )

        except Exception:
            use_embeddings = False

    results = []

    for index, parsed_resume in enumerate(parsed_resumes):

        # -----------------------------------------------------
        # Semantic similarity
        # -----------------------------------------------------
        if use_embeddings:
            resume_vector = resume_vectors[index]

            denominator = (
                np.linalg.norm(resume_vector)
                * np.linalg.norm(jd_vector)
                + 1e-9
            )

            similarity = float(
                np.dot(resume_vector, jd_vector) / denominator
            )

            semantic = round(
                max(similarity, 0.0) * 100,
                1
            )

            engine_used = "embeddings"

        else:
            semantic, engine_used = semantic_relevance(
                parsed_resume.raw_text,
                parsed_jd["raw_text"],
                backend="tfidf",
            )

        # -----------------------------------------------------
        # Skill matching
        # -----------------------------------------------------
        skill_score, matched, missing, extra = _skill_alignment(
            parsed_resume.skills,
            parsed_jd["required_skills"],
        )

        # -----------------------------------------------------
        # Experience
        # -----------------------------------------------------
        exp_score = _experience_evidence(
            parsed_resume.years_experience,
            parsed_jd["min_years"],
        )

        # -----------------------------------------------------
        # Education
        # -----------------------------------------------------
        edu_score = _education_evidence(
            parsed_resume.education,
            parsed_jd["required_education"],
        )

        factors = {
            "semantic_relevance": semantic,
            "skill_alignment": skill_score,
            "experience_evidence": exp_score,
            "education_evidence": edu_score,
        }

        # -----------------------------------------------------
        # Overall score
        # -----------------------------------------------------
        overall = round(
            sum(
                factors[k] * weights[k]
                for k in WEIGHTS
            ),
            1,
        )

        status = _status_from_score(overall)

        rationale = _build_rationale(
            parsed_resume.name,
            matched,
            missing,
            factors,
            status,
        )

        # -----------------------------------------------------
        # Fairness audit
        # -----------------------------------------------------
        fairness_semantic = _semantic_relevance_tfidf(
            parsed_resume.raw_text,
            parsed_jd["raw_text"],
        )

        fairness_audit = bias_checker.audit_fairness(
            parsed_resume.raw_text,
            parsed_jd["raw_text"],
            parsed_resume.name,
            parsed_resume.email,
            parsed_resume.phone,
            fairness_semantic,
        )

        results.append(
            MatchResult(
                candidate_name=parsed_resume.name,
                overall_score=overall,
                factors=factors,
                matched_skills=matched,
                missing_skills=missing,
                extra_skills=extra,
                status=status,
                rationale=rationale,
                filename=filenames[index],
                email=parsed_resume.email,
                phone=parsed_resume.phone,
                linkedin_url=parsed_resume.linkedin_url,
                github_url=parsed_resume.github_url,
                portfolio_url=parsed_resume.portfolio_url,
                education=parsed_resume.education,
                years_experience=parsed_resume.years_experience,
                fairness_audit=fairness_audit,
                semantic_engine=engine_used,
                candidate_id=make_candidate_id(
                    filenames[index],
                    parsed_resume.name,
                    parsed_resume.email,
                    parsed_resume.phone,
                ),
                raw_text=parsed_resume.raw_text,
            )
        )

    return results



"""def _rescale(value, old_min, old_max, new_min=22.0, new_max=98.0):
    if old_max - old_min < 1e-9:
        return new_max if value > 0 else new_min
    ratio = (value - old_min) / (old_max - old_min)
    return round(new_min + ratio * (new_max - new_min), 1)
"""


def rank_candidates(results: list, weights=None) -> list:
    """Recompute final scores and sort candidates best-first.

    Semantic relevance is kept on its original 0-100 scale so that a
    candidate's score does not change just because other candidates
    are added to or removed from the screening pool.
    """
    if not results:
        return results

    weights = weights or WEIGHTS

    for r in results:
        # Keep the original semantic relevance score.
        # Do NOT rescale it based on the other candidates.
        r.overall_score = round(
            sum(r.factors[k] * weights[k] for k in WEIGHTS),
            1
        )

        r.status = _status_from_score(r.overall_score)

        r.rationale = _build_rationale(
            r.candidate_name,
            r.matched_skills,
            r.missing_skills,
            r.factors,
            r.status
        )

    results.sort(key=lambda r: -r.overall_score)

    return results


def skill_category_breakdown(skills: list) -> dict:
    """Group a flat skill list by category, for the skill-gap chart."""
    breakdown = {}
    for s in skills:
        cat = SKILL_TO_CATEGORY.get(s.lower(), "Other")
        breakdown[cat] = breakdown.get(cat, 0) + 1
    return breakdown
