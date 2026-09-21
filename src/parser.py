"""
Document extraction + structured parsing.

Handles: PDF / DOCX / TXT ingestion, and pulling out
name, email, phone, education, years of experience, and a skills list
from free-form resume or job-description text.
"""
import io
import re
import datetime
from dataclasses import dataclass, field

from .skills_taxonomy import MASTER_SKILLS, SYNONYMS, SKILL_TO_CATEGORY, canonicalize

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
URL_RE = re.compile(
    r"(?:https?://[^\s<>\[\]{}\"']+|www\.[^\s<>\[\]{}\"']+|(?:https?://)?(?:linkedin\.com|github\.com)/[^\s<>\[\]{}\"']+)",
    re.IGNORECASE,
)
# International-aware phone matcher:
#   - optional +country code (1-3 digits)
#   - optional parenthesized area/STD code
#   - then 2-4 groups of digits separated by space/dot/dash, 7-12 digits total
# Covers US "(555) 123-4567", Indian "+91 98765 43210" / "+91-9876543210",
# and plain unbroken 10-digit numbers, while still requiring digit boundaries
# so it doesn't grab pieces of longer numeric strings (IDs, years, etc.)
PHONE_RE = re.compile(
    r"(?<![\d/])"
    r"(?:\(\+?\d{1,4}\)[\s.-]?|\+\d{1,3}[\s.-]?)?"
    r"(?:\(\d{2,4}\)[\s.-]?)?"
    r"\d{3,5}[\s.-]?\d{3,4}(?:[\s.-]?\d{2,4})?"
    r"(?![\d/])"
)
YEARS_EXP_RE = re.compile(
    r"(\d{1,2})\+?\s*(?:years|yrs)\.?\s*(?:of)?\s*(?:relevant\s+)?experience",
    re.IGNORECASE,
)
DATE_RANGE_RE = re.compile(
    r"(19|20)\d{2}\s*(?:-|to|–|—)\s*(?:(19|20)\d{2}|present|current)",
    re.IGNORECASE,
)
# A bare "2019-2023"-style year range satisfies the phone digit-count shape too;
# filter those out so employment date ranges never get mistaken for a phone number.
YEAR_RANGE_LOOKALIKE_RE = re.compile(
    r"^(?:19|20)\d{2}[\s.-]*(?:(?:19|20)\d{2}|present|current)$", re.IGNORECASE
)

EDUCATION_LEVELS = [
    ("phd", "PhD / Doctorate"),
    ("doctorate", "PhD / Doctorate"),
    ("master", "Master's Degree"),
    ("mba", "Master's Degree"),
    ("m.s.", "Master's Degree"),
    ("ms", "Master's Degree"),
    ("m.a.", "Master's Degree"),
    ("ma", "Master's Degree"),
    ("bachelor", "Bachelor's Degree"),
    ("b.s.", "Bachelor's Degree"),
    ("b.tech", "Bachelor's Degree"),
    ("bsc", "Bachelor's Degree"),
    ("b.sc", "Bachelor's Degree"),
    ("b.a.", "Bachelor's Degree"),
    ("ba", "Bachelor's Degree"),
    ("associate", "Associate Degree"),
    ("diploma", "Diploma"),
    ("high school", "High School"),
]

STOPWORD_NAME_LINES = (
    "summary", "objective", "experience", "education", "skills",
    "profile", "resume", "curriculum vitae", "highlights", "accomplishments",
)


@dataclass
class ParsedDocument:
    raw_text: str
    name: str = "Not detected"
    email: str = "Not detected"
    phone: str = "Not detected"
    linkedin_url: str = "Not detected"
    github_url: str = "Not detected"
    portfolio_url: str = "Not detected"
    education: str = "Not detected"
    years_experience: float = 0.0
    skills: list = field(default_factory=list)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    import pdfplumber
    text_chunks = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            # Some PDFs store the destination separately from the visible link text.
            for hyperlink in getattr(page, "hyperlinks", []):
                uri = hyperlink.get("uri")
                if uri:
                    t += f"\n{uri}"
            text_chunks.append(t)
    return "\n".join(text_chunks)


def extract_text_from_docx(file_bytes: bytes) -> str:
    import docx
    doc = docx.Document(io.BytesIO(file_bytes))
    text = "\n".join(p.text for p in doc.paragraphs)
    # python-docx exposes hyperlink destinations through the document
    # relationships, while paragraph.text contains only their display text.
    links = []
    for relationship in doc.part.rels.values():
        if relationship.is_external and relationship.target_ref.startswith(("http://", "https://")):
            if relationship.target_ref not in links:
                links.append(relationship.target_ref)
    if links:
        text += "\n" + "\n".join(links)
    return text


def extract_text(filename: str, file_bytes: bytes) -> str:
    lower = filename.lower()
    try:
        if lower.endswith(".pdf"):
            return extract_text_from_pdf(file_bytes)
        if lower.endswith(".docx"):
            return extract_text_from_docx(file_bytes)
        # plain text fallback
        return file_bytes.decode("utf-8", errors="ignore")
    except Exception:
        try:
            return file_bytes.decode("utf-8", errors="ignore")
        except Exception:
            return ""


def guess_name(text: str, fallback: str) -> str:
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    # Look through the first 20 meaningful lines.
    for i, line in enumerate(lines[:20]):
        clean = line.strip()

        if not clean or len(clean) > 45:
            continue

        low = clean.lower()

        # Ignore obvious section headings.
        if any(k == low for k in STOPWORD_NAME_LINES):
            continue

        # Ignore contact information.
        if EMAIL_RE.search(clean) or PHONE_RE.search(clean):
            continue

        words = clean.split()

        # Reject obvious job titles / roles.
        title_words = {
            "engineer",
            "developer",
            "scientist",
            "analyst",
            "designer",
            "manager",
            "intern",
            "student",
            "consultant",
            "architect",
            "administrator",
            "specialist",
            "lead",
            "trainee",
        }

        if any(
            word.lower().strip(".,-") in title_words
            for word in words
        ):
            continue

        # Normal case: name is on one line.
        if (
            1 < len(words) <= 4
            and all(
                w.replace(".", "").isalpha() or w.isupper()
                for w in words
            )
        ):
            return clean.title() if clean.isupper() else clean

        # PDF-layout case:
        # name may be split across two consecutive lines,
        # e.g. "AHELI" followed by "BANERJEE".
        if len(words) == 1 and clean.isalpha():
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()

                if (
                    next_line.isalpha()
                    and len(next_line) <= 30
                    and next_line.lower() not in STOPWORD_NAME_LINES
                    and next_line.lower() not in title_words
                ):
                    return f"{clean.title()} {next_line.title()}"

    return fallback


def extract_phone(text: str) -> str:
    """First PHONE_RE match that isn't actually a "2019-2023"-style date
    range and has enough digits to plausibly be a phone number."""
    for m in PHONE_RE.finditer(text):
        candidate = m.group(0)
        digit_count = sum(ch.isdigit() for ch in candidate)
        if digit_count < 7:
            continue
        if YEAR_RANGE_LOOKALIKE_RE.match(candidate.strip()):
            continue
        return candidate
    return None


def extract_social_links(text: str) -> dict:
    """Extract the main professional links from resume text."""
    links = []
    for match in URL_RE.finditer(text):
        link = match.group(0).rstrip(".,;:)]}")
        if not link.lower().startswith(("http://", "https://")):
            link = "https://" + link
        if link not in links:
            links.append(link)

    social = {"linkedin_url": "Not detected", "github_url": "Not detected", "portfolio_url": "Not detected"}
    remaining = []
    for link in links:
        lower = link.lower()
        if "linkedin.com" in lower and social["linkedin_url"] == "Not detected":
            social["linkedin_url"] = link
        elif "github.com" in lower and social["github_url"] == "Not detected":
            social["github_url"] = link
        else:
            remaining.append(link)
    if remaining:
        social["portfolio_url"] = remaining[0]
    return social


def extract_social_link_labels(text: str) -> dict:
    """Find the resume label associated with each extracted social link."""
    labels = {
        "linkedin_url": "LinkedIn",
        "github_url": "GitHub",
        "portfolio_url": "Portfolio",
    }
    label_re = re.compile(
        r"(linkedin|github|leetcode|portfolio|personal\s+website|website|web|site)\s*(?:and\s+links)?\s*:?\s*$",
        re.IGNORECASE,
    )
    for match in URL_RE.finditer(text):
        link = match.group(0).rstrip(".,;:)]}")
        normalized = link if link.lower().startswith(("http://", "https://")) else "https://" + link
        lower = normalized.lower()
        if "linkedin.com" in lower:
            field = "linkedin_url"
        elif "github.com" in lower:
            field = "github_url"
        else:
            field = "portfolio_url"
        line_start = text.rfind("\n", 0, match.start()) + 1
        prefix = text[line_start:match.start()]
        label_match = label_re.search(prefix)
        if "leetcode.com" in lower:
            labels["portfolio_url"] = "LeetCode"
        elif label_match:
            label = label_match.group(1).strip().lower()
            labels[field] = {
                "linkedin": "LinkedIn",
                "github": "GitHub",
                "leetcode": "LeetCode",
                "portfolio": "Portfolio",
                "personal website": "Personal Website",
                "website": "Website",
                "web": "Web",
                "site": "Site",
            }.get(label, label.title())
    return labels


def extract_years_experience(text: str) -> float:
    """Extract years of professional work experience.
    Avoids mistaking academic study dates (e.g. 2023 - 2027 degree program)
    for professional work experience."""
    m = YEARS_EXP_RE.search(text)
    if m:
        return float(m.group(1))

    # Look specifically within an Experience / Employment section
    section_headers = r"(?:work\s+experience|professional\s+experience|employment\s+history|work\s+history|experience)"
    next_headers = r"(?:education|technical\s+skills|skills|projects|project|certifications|publications|achievements|awards|interests|languages|hobbies)"

    exp_pattern = re.compile(
        rf"(?:^|\n)\s*{section_headers}\b[:\s]*(.*?)(?=\n\s*{next_headers}\b|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    exp_match = exp_pattern.search(text)
    if not exp_match:
        return 0.0

    exp_text = exp_match.group(1)
    if len(exp_text.strip()) < 10:
        return 0.0

    current_year = datetime.date.today().year
    years_found = []
    for match in DATE_RANGE_RE.finditer(exp_text):
        span_text = match.group(0)
        start_match = re.search(r"(19|20)\d{2}", span_text)
        if start_match:
            start_year = int(start_match.group(0))
            if "present" in span_text.lower() or "current" in span_text.lower():
                end_year = current_year
            else:
                all_years = re.findall(r"(?:19|20)\d{2}", span_text)
                end_year = int(all_years[-1]) if len(all_years) > 1 else start_year
            # Future end year is graduation or expected end, not past experience
            if end_year > current_year:
                continue
            if current_year >= end_year >= start_year:
                years_found.append(end_year - start_year)

    if years_found:
        return float(max(years_found))
    return 0.0


def extract_education(text: str) -> str:
    low = text.lower()
    for key, label in EDUCATION_LEVELS:
        if key in low:
            return label
    return "Not detected"


def extract_skills(text: str, extra_skills: list = None) -> list:
    """extra_skills lets callers extend the built-in taxonomy at runtime
    (e.g. org-specific tools like LangGraph or vLLM added via Settings)
    without editing skills_taxonomy.py."""
    low = " " + re.sub(r"[^a-z0-9.+#/\s]", " ", text.lower()) + " "
    found = set()

    for skill in MASTER_SKILLS:
        pattern = r"(?<![a-z0-9])" + re.escape(skill.lower()) + r"(?![a-z0-9])"
        if re.search(pattern, low):
            found.add(skill)

    for alias, canonical in SYNONYMS.items():
        pattern = r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"
        if re.search(pattern, low):
            found.add(canonical)

    for skill in (extra_skills or []):
        skill = skill.strip()
        if not skill:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(skill.lower()) + r"(?![a-z0-9])"
        if re.search(pattern, low):
            found.add(skill)

    # Heuristic: Extract capitalized tokens from "Skills" or "Technologies" sections
    skills_section_re = re.compile(r"(?:skills|technologies)[\s]*:[\s]*(.*?)(?:\n\n|\Z)", re.IGNORECASE | re.DOTALL)
    for match in skills_section_re.finditer(text):
        section_text = match.group(1)
        # split by commas, bullets, or newlines
        tokens = re.split(r'[,\n•·|-]', section_text)
        for token in tokens:
            cleaned = token.strip()
            if cleaned and len(cleaned) <= 30 and len(cleaned.split()) <= 3:
                # only keep it if it has at least one uppercase letter (heuristic for a proper noun/tech)
                if any(c.isupper() for c in cleaned):
                    found.add(cleaned)

    return sorted(found)


def extract_email(text: str) -> str:
    """Robust email extractor handling standard formats, mailto: URIs,
    non-breaking spaces, and spaced-out PDF text artifacts."""
    cleaned = text.replace('\xa0', ' ').replace('\u200b', '').replace('\ufeff', '')
    m = EMAIL_RE.search(cleaned)
    if m:
        return m.group(0).strip()
    mailto_m = re.search(r"mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})", cleaned, re.IGNORECASE)
    if mailto_m:
        return mailto_m.group(1).strip()
    spaced_m = re.search(r"([a-zA-Z0-9._%+\-]+)\s*@\s*([a-zA-Z0-9.\-]+)\s*\.\s*([a-zA-Z]{2,})", cleaned)
    if spaced_m:
        return f"{spaced_m.group(1)}@{spaced_m.group(2)}.{spaced_m.group(3)}".strip()
    return "Not detected"


def parse_document(filename: str, file_bytes: bytes, extra_skills: list = None) -> ParsedDocument:
    text = extract_text(filename, file_bytes)
    fallback_name = re.sub(r"\.[a-zA-Z0-9]+$", "", filename).replace("_", " ").replace("-", " ").title()

    email = extract_email(text)
    phone = extract_phone(text)
    social_links = extract_social_links(text)

    return ParsedDocument(
        raw_text=text,
        name=guess_name(text, fallback_name),
        email=email,
        phone=phone if phone else "Not detected",
        **social_links,
        education=extract_education(text),
        years_experience=extract_years_experience(text),
        skills=extract_skills(text, extra_skills=extra_skills),
    )


def parse_job_description(jd_text: str, min_years_override=None, extra_skills: list = None) -> dict:
    skills = extract_skills(jd_text, extra_skills=extra_skills)
    years_match = YEARS_EXP_RE.search(jd_text)
    min_years = float(years_match.group(1)) if years_match else (min_years_override or 0.0)
    education = extract_education(jd_text)
    return {
        "raw_text": jd_text,
        "required_skills": skills,
        "min_years": min_years,
        "required_education": education,
    }
