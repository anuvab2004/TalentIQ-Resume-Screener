"""
Bias & fairness module.

Two independent checks, both rule-based (no extra ML dependency, in keeping
with the project's "dependency-light" philosophy):

1. JD Language Scanner — flags gender-coded, age-coded, ableist, and
   exclusionary wording in a job description before it ever goes out, with a
   neutral rewrite suggestion for each hit (the same idea used by tools like
   Textio / Gender Decoder).

2. Blind Scoring Audit — proves, per-candidate, that identity-bearing text
   (name, email, phone) is not moving the semantic-match score. It re-runs
   the same TF-IDF similarity used by the matcher on a copy of the resume
   with those fields redacted and reports the delta. A near-zero delta is
   the evidence backing the app's fairness claim, not just a policy note.
"""
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# --------------------------------------------------------------------------
# 1. JD language scanner
# --------------------------------------------------------------------------
# category -> {term: suggestion}
BIASED_TERMS = {
    "Masculine-coded": {
        "rockstar": "high performer",
        "ninja": "specialist / expert",
        "guru": "specialist / expert",
        "superhero": "high performer",
        "aggressive": "proactive",
        "dominant": "leading",
        "dominate": "lead",
        "competitive spirit": "results-driven",
        "fearless": "confident",
        "assertive": "decisive",
        "ambitious": "motivated",
        "headstrong": "decisive",
        "chairman": "chairperson",
        "manpower": "workforce / staff",
        "salesman": "salesperson",
        "he/his": "they/their",
    },
    "Feminine-coded (can also narrow the pool)": {
        "nurturing": "supportive",
        "compassionate": "empathetic",
        "warm personality": "positive attitude",
        "dependable": "reliable",
        "interpersonal skills a must": "strong interpersonal skills",
    },
    "Age-coded": {
        "young": "(remove — not a job-relevant trait)",
        "energetic": "motivated",
        "digital native": "comfortable with modern digital tools",
        "recent graduate": "early-career candidate",
        "fresh graduate": "early-career candidate",
        "youthful": "(remove — not a job-relevant trait)",
    },
    "Ableist / exclusionary": {
        "must be able to stand for long periods": "role requires extended time on your feet — accommodations available on request",
        "must be able to lift": "role involves physical lifting — accommodations available on request",
        "walk-in only": "on-site or remote application accepted",
        "native english speaker": "fluent in English",
        "native speaker": "fluent speaker",
        "no disabilities": "(remove — illegal to state as a requirement in most jurisdictions)",
        "normal vision": "(remove unless a bona fide occupational requirement, e.g. safety-critical driving)",
    },
    "Exclusionary culture-fit language": {
        "culture fit": "culture add / alignment with team values",
        "work hard play hard": "fast-paced, collaborative environment",
        "bro culture": "(remove)",
        "must be a team player": "collaborates effectively with others",
    },
}

_FLAT_TERMS = [
    (term, category, suggestion)
    for category, terms in BIASED_TERMS.items()
    for term, suggestion in terms.items()
]


def check_jd_bias(jd_text: str) -> dict:
    """Scan a job description for biased/exclusionary wording.

    Returns {"hits": [...], "risk_level": "Low"|"Moderate"|"High",
    "term_count": int, "category_count": int}.
    """
    if not jd_text or not jd_text.strip():
        return {"hits": [], "risk_level": "Low", "term_count": 0, "category_count": 0}

    low = jd_text.lower()
    hits = []
    categories_hit = set()
    for term, category, suggestion in _FLAT_TERMS:
        pattern = r"(?<![a-z])" + re.escape(term) + r"(?![a-z])"
        matches = re.findall(pattern, low)
        if matches:
            hits.append({
                "term": term,
                "category": category,
                "suggestion": suggestion,
                "count": len(matches),
            })
            categories_hit.add(category)

    hits.sort(key=lambda h: -h["count"])
    total = sum(h["count"] for h in hits)

    if total == 0:
        risk = "Low"
    elif total <= 2 and len(categories_hit) <= 1:
        risk = "Low"
    elif total <= 5 or len(categories_hit) <= 2:
        risk = "Moderate"
    else:
        risk = "High"

    return {
        "hits": hits,
        "risk_level": risk,
        "term_count": total,
        "category_count": len(categories_hit),
    }


# --------------------------------------------------------------------------
# 2. Blind scoring audit
# --------------------------------------------------------------------------
def _tfidf_cosine(text_a: str, text_b: str) -> float:
    docs = [text_a or "", text_b or ""]
    if not docs[0].strip() or not docs[1].strip():
        return 0.0
    try:
        vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
        tfidf = vectorizer.fit_transform(docs)
        sim = cosine_similarity(tfidf[0], tfidf[1])[0][0]
        return round(float(sim) * 100, 1)
    except ValueError:
        return 0.0


def redact_identity(resume_text: str, name: str, email: str, phone: str) -> str:
    """Strip name/email/phone tokens from resume text, for a 'blind' re-score."""
    redacted = resume_text or ""
    if email and email != "Not detected":
        redacted = redacted.replace(email, " ")
    if phone and phone != "Not detected":
        redacted = redacted.replace(phone, " ")
    if name and name != "Not detected":
        for part in name.split():
            if len(part) > 1:
                redacted = re.sub(r"(?<![A-Za-z])" + re.escape(part) + r"(?![A-Za-z])", " ", redacted)
    return redacted


def audit_fairness(resume_text: str, jd_text: str, name: str, email: str, phone: str,
                    original_semantic_score: float) -> dict:
    """Re-score the resume with identity fields redacted and compare to the
    original semantic-relevance score. A small delta is the evidence that
    name/email/phone are not influencing the match."""
    blind_text = redact_identity(resume_text, name, email, phone)
    blind_score = _tfidf_cosine(blind_text, jd_text)
    delta = round(original_semantic_score - blind_score, 1)
    if abs(delta) < 1.0:
        note = "No measurable effect from identity fields on this candidate's match score."
    elif abs(delta) < 3.0:
        note = "Negligible effect from identity fields on this candidate's match score."
    else:
        note = "Identity fields shifted this score more than expected — worth a manual look."
    return {
        "blind_score": blind_score,
        "original_score": original_semantic_score,
        "delta": delta,
        "note": note,
    }
