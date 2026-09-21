"""
Document extraction + structured parsing.

Handles: PDF / DOCX / TXT ingestion, and pulling out
name, email, phone, education, years of experience, and a skills list
from free-form resume or job-description text.

Years of experience come from paid/professional work and internships:
full-time roles, part-time roles, contracts, freelance work and internships.
A date range is counted only when it:
  (a) is not inside an Education / Projects / Skills / Certifications /
      Volunteer / Publications section,
  (b) is not next to degree or grade wording (B.Tech, M.S., Ph.D, CGPA ...),
  (c) sits next to a job title, "intern"/"trainee" wording or an employer marker.

Overlapping jobs/internships are merged so they are never double counted.
Internships and short-duration roles are fully counted and preserved in months,
so that e.g. a 3-month internship displays as "3 months" instead of "0.3 years" or "0 yrs".
"""
import bisect
import datetime as _dt
import hashlib
import io
import re
from dataclasses import dataclass, field

from .skills_taxonomy import MASTER_SKILLS, SYNONYMS, canonicalize

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
    r"(?:\+\d{1,3}[\s.-]?)?"
    r"(?:\(\d{2,4}\)[\s.-]?)?"
    r"\d{3,5}[\s.-]?\d{3,4}(?:[\s.-]?\d{2,4})?"
    r"(?![\d/])"
)
# Labels that mean "the number next to me is an ID, not a phone number".
PHONE_ID_LABEL_RE = re.compile(
    r"\b(?:roll|reg(?:istration)?|enrol(?:l?ment)?|student|employee|emp|id|uid|"
    r"aadhaar|aadhar|pan|passport|ssn|cgpa|gpa|pin\s?code|zip)\b[^\d]{0,12}$",
    re.IGNORECASE,
)

# "5 years of experience", "5+ yrs hands-on experience", "1.5 years experience",
# "3-5 years of professional experience", "At least 3 years of hands-on development"
YEARS_EXP_RE = re.compile(
    r"(?<![\d.])(?:\b(?:at\s+least|minimum|min|over|\+)\s*)?(\d{1,2}(?:\.\d)?)(?:\s*(?:-|–|—|to)\s*\d{1,2})?\s*\+?\s*(?:years?|yrs?)\.?\s*(?:of\s+)?"
    r"(?:(?:relevant|professional|hands-on|industry|work|working|total|overall|proven|it|technical|software|commercial|engineering|field|practical)\s+)*"
    r"(?:experience|development|engineering|work|background)\b",
    re.IGNORECASE,
)

# "3 months internship", "6 mos of experience", "3-month intern", "3 months as intern"
MONTHS_EXP_RE = re.compile(
    r"(?<![\d.])(\d{1,2})\s*(?:-|–|—|to)?\s*(?:\d{1,2})?\s*(?:months?|mos?)\.?(?:\s+(?:as\s+(?:an?\s+)?)?|\s*[-–—:]\s*|\s+of\s+)?(?:(?:relevant|professional|hands-on|industry|work|working|total|overall|proven|summer)\s+)*(?:experience|internship|internships|intern|interns|training)",
    re.IGNORECASE,
)
# "intern for 3 months", "Software Engineer Intern (3 months)", "internship: 3 months", "internship of 3 months"
INTERNSHIP_DURATION_RE = re.compile(
    r"\b(?:intern(?:s|ship|ships)?|trainee)\b[\s:()–—\-,]{1,25}(?:(?:for|of|duration|period)\s*(?:of|:)?\s*)?(\d{1,2})\s*(?:months?|mos?)\b",
    re.IGNORECASE,
)

DATE_RANGE_RE = re.compile(
    r"(19|20)\d{2}\s*(?:-|to|–|—)\s*(?:(19|20)\d{2}|present|current|now|ongoing|today|till\s+date|to\s+date)",
    re.IGNORECASE,
)
# A bare "2019-2023"-style year range satisfies the phone digit-count shape too;
# filter those out so employment date ranges never get mistaken for a phone number.
YEAR_RANGE_LOOKALIKE_RE = re.compile(
    r"^(?:19|20)\d{2}[\s.-]*(?:(?:19|20)\d{2}|present|current|now|ongoing|today|till\s+date|to\s+date)$", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Education patterns
# ---------------------------------------------------------------------------
_EDU_PATTERNS = [
    (r"\bph\.?\s?d\b|\bdoctorate\b|\bdoctoral\b", "PhD / Doctorate"),
    (
        r"\bmaster(?:['’]?s)?\s+(?:of|in|degree)\b|\bmaster['’]s\b|\bmasters\b"
        r"|\bm\s*\.\s*tech\b|\bmtech\b|\bm\s*\.\s*sc\b|\bmsc\b|\bmba\b|\bmca\b"
        r"|\bm\s*\.\s*s\b|\bm\s*\.\s*e\b|\bm\s*\.\s*a\b",
        "Master's Degree",
    ),
    (
        r"\bbachelor|\bb\s*\.\s*tech\b|\bbtech\b|\bb\s*\.\s*sc\b|\bbsc\b|\bb\s*\.\s*s\b"
        r"|\bb\s*\.\s*e\b|\bb\s*\.\s*a\b|\bb\s*\.\s*com\b|\bbcom\b|\bbca\b|\bbba\b",
        "Bachelor's Degree",
    ),
    (r"\bassociate(?:['’]?s)?\s+(?:degree|of)\b", "Associate Degree"),
    (r"(?<!high school )(?<!school )\bdiplomas?\b", "Diploma"),
    (
        r"\bhigh\s+school\b|\bsenior\s+secondary\b|\bhigher\s+secondary\b|\b12th\b|\bhsc\b",
        "High School",
    ),
]
EDUCATION_LEVELS = [(re.compile(p, re.IGNORECASE), label) for p, label in _EDU_PATTERNS]

# Words that mean "this date range belongs to a degree, not a job".
_DEGREE_RE = re.compile(
    r"\b(?:cgpa|sgpa|gpa|percentage|graduation|dissertation|thesis|scholarship|fellowship)\b|"
    + "|".join(p for p, label in _EDU_PATTERNS if label != "High School"),
    re.IGNORECASE,
)
_STUDENT_CONTEXT_RE = re.compile(
    r"\b(?:universit(?:y|ies)|college|institute|school|academy|campus|semester|"
    r"pursuing|undergraduate|coursework|student)\b",
    re.IGNORECASE,
)

# Unpaid roles that carry a title but are not employment.
_UNPAID_ROLE_RE = re.compile(
    r"\b(?:volunteer\w*|community\s+service|board\s+of\s+directors|board\s+member|"
    r"member\s+of\s+the\s+board)\b",
    re.IGNORECASE,
)

# Words that mean "this date range belongs to a job or internship".
_WORK_TITLE_RE = re.compile(
    r"\b(?:intern(?:s|ship|ships)?|trainees?|apprentice(?:s|ship)?|co-?ops?|engineers?|developers?|"
    r"dev|sde|swe|programmers?|analysts?|consultants?|managers?|executives?|associates?|"
    r"officers?|assistants?|administrators?|admin|coordinators?|specialists?|architects?|"
    r"designers?|scientists?|researchers?|technicians?|technologists?|auditors?|accountants?|"
    r"advis[eo]rs?|leads?|directors?|supervisors?|representatives?|freelanc(?:e|er|ing)|"
    r"contractors?|teachers?|lecturers?|professors?|tutors?|instructors?|trainers?|clerks?|"
    r"secretary|recruiters?|strategists?|generalists?|founders?|co-?founders?|owners?|"
    r"editors?|writers?|copywriters?|marketers?|salesman|salesperson|sales|cashiers?|"
    r"receptionists?|operators?|mechanics?|electricians?|drivers?|nurses?|pharmacists?|"
    r"chefs?|waiters?|baristas?|bankers?|testers?|president|vp|cto|ceo|coo|cfo|qa)\b",
    re.IGNORECASE,
)
_EMPLOYER_RE = re.compile(
    r"\b(?:pvt|private\s+limited|ltd|limited|inc|llc|llp|corp|corporation|technologies|"
    r"solutions|systems|labs?|software|consulting|consultancy|services|company|co|gmbh|"
    r"group|industries|enterprises|bank|studios?|startup|agency|firm|full[\s-]?time|"
    r"part[\s-]?time|contract|remote|on-?site|hybrid)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Resume section headings (Regex-based & Pattern-driven)
# ---------------------------------------------------------------------------
_EXPERIENCE_HEADINGS = {
    "experience", "work experience", "professional experience", "work history",
    "employment", "employment history", "employment experience", "work",
    "professional background", "career history", "relevant experience",
    "industry experience", "industrial experience", "industrial training",
    "intern", "interns", "internship", "internships", "intern experience",
    "interns experience", "internship experience", "summer intern",
    "summer internship", "summer internships", "research experience",
    "teaching experience", "co-op", "coop", "practical training",
}
_EDUCATION_HEADINGS = {
    "education", "academic background", "academics", "academic qualifications",
    "educational qualifications", "education qualifications", "qualifications",
    "academic details", "educational background", "education and training",
}
_OTHER_HEADINGS = {
    "summary", "professional summary", "career summary", "objective",
    "career objective", "profile", "professional profile", "about me", "about",
    "projects", "personal projects", "academic projects", "key projects",
    "selected projects", "project experience", "skills", "technical skills",
    "core skills", "key skills", "interests", "areas of interest", "hobbies",
    "languages", "language", "certifications", "certification", "certificates",
    "achievements", "accomplishments", "awards", "honors", "honours",
    "extra curricular activities", "extracurricular activities",
    "co curricular activities", "activities", "volunteer experience",
    "volunteering", "volunteer work", "leadership", "leadership experience",
    "positions of responsibility", "publications", "research papers",
    "references", "declaration", "personal details", "personal information",
    "training", "courses", "coursework", "relevant coursework", "workshops",
    "highlights", "currently learning", "tools", "technologies",
    "tools and technologies", "volunteer", "additional information",
    "selected publications", "leadership roles", "community service",
    "extra-curricular", "extracurricular", "co-curricular", "cocurricular",
    "extra-curricular activities", "co-curricular activities",
}

# Explicit non-work sections (Extracurriculars, Volunteering, Leadership, etc.)
# Roles/dates under these sections must NEVER appear in work history.
_NON_WORK_SECTION_RE = re.compile(
    r"\b(?:extra[\s-]?curricular\w*|co[\s-]?curricular\w*|volunteer\w*|community\s+service|"
    r"leadership|positions?\s+of\s+responsibility|activities|hobbies|interests|"
    r"publications?|awards?|honors?|honours?|certificat\w*|achievements?)\b",
    re.IGNORECASE,
)

# Regex patterns for flexible section classification
_EXPERIENCE_HEADING_RE = re.compile(
    r"\b(?:experience|work|employment|career|background|history|intern(?:s|ship|ships)?|co-?op)\b",
    re.IGNORECASE,
)
_EDUCATION_HEADING_RE = re.compile(
    r"\b(?:education|academic|degree|studied|qualification|qualifications|schooling|academics)\b",
    re.IGNORECASE,
)
_SKILLS_HEADING_RE = re.compile(
    r"\b(?:skills|competencies|proficiencies|expertise|technologies|tools|tech\s+stack)\b",
    re.IGNORECASE,
)
_OTHER_HEADING_RE = re.compile(
    r"\b(?:summary|objective|profile|projects?|certificat(?:ion|ions|es)|achievements?|"
    r"awards?|honors?|honours?|publications?|activities|volunteer(?:ing|s)?|interests?|"
    r"languages?|affiliations?|references?|coursework|training|declaration|personal\s+details|"
    r"leadership|community\s+service|positions?\s+of\s+responsibility|extra[\s-]?curricular)\b",
    re.IGNORECASE,
)

STRUCTURAL_STOP_WORDS = {
    "certifications", "certification", "certificates", "education",
    "professional experience", "work experience", "experience", "employment",
    "career history", "work history", "candidate", "resume", "curriculum vitae",
    "profile", "summary", "personal profile", "professional summary", "about me",
    "personal details", "personal information", "projects", "personal projects",
    "academic projects", "key projects", "skills", "technical skills",
    "core skills", "key skills", "competencies", "proficiencies", "technologies",
    "tools", "contact", "contact information", "references", "declaration",
    "volunteer", "volunteering", "achievements", "awards", "honors",
    "extracurricular activities", "publications", "coursework", "interests",
    "hobbies", "languages",
}

US_STATE_CODES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
    "dc",
}

ROLE_TITLE_PATTERNS = re.compile(
    r"\b(?:senior|junior|lead|principal|staff|associate|chief|director|head|vp|manager|"
    r"analyst|engineer|developer|scientist|consultant|specialist|intern|trainee|"
    r"architect|administrator|coordinator|officer|executive|assistant)\b",
    re.IGNORECASE,
)

STOPWORD_NAME_LINES = (
    "summary", "objective", "experience", "education", "skills",
    "profile", "resume", "curriculum vitae", "highlights", "accomplishments",
)

_TITLE_WORDS = {
    "engineer", "developer", "scientist", "analyst", "designer", "manager",
    "intern", "student", "consultant", "architect", "administrator",
    "specialist", "lead", "trainee",
}
_NON_NAME_WORDS = _TITLE_WORDS | {
    "resume", "cv", "curriculum", "vitae", "summary", "objective", "profile",
    "contact", "email", "phone", "mobile", "tel", "address", "github",
    "linkedin", "portfolio", "roll", "no", "dob", "bachelor", "master",
    "masters", "technology", "university", "college", "institute", "school",
    "engineering", "education", "experience", "skills", "projects", "of",
    "and", "the", "for", "in", "at", "btech", "mtech", "degree",
}


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
    experience_months: int = 0
    skills: list = field(default_factory=list)
    parse_confidence: float = 1.0
    confidence_reasons: list = field(default_factory=list)
    input_hash: str = ""
    resolved_present_date: str = ""


def clean_doubled_text(text: str) -> str:
    """Repair doubled-letter artifacts caused by PDF shadow-stroke rendering
    (e.g., 'EEDDUUCCAATTIIOONN' -> 'EDUCATION')."""
    if not text:
        return ""

    def _fix_word(match):
        w = match.group(0)
        if len(w) >= 6 and len(w) % 2 == 0:
            if all(w[i].lower() == w[i + 1].lower() for i in range(0, len(w), 2)):
                return "".join(w[i] for i in range(0, len(w), 2))
        return w

    return re.sub(r"\b[A-Za-z]{6,}\b", _fix_word, text)


def format_years(years) -> str:
    """Human-friendly years string: 4 -> '4', 0.1 -> '0.1', 2.5 -> '2.5'."""
    try:
        s = f"{float(years or 0):.1f}"
    except (TypeError, ValueError):
        return "0"
    return s[:-2] if s.endswith(".0") else s


def format_experience(years, months=None, compact=False) -> str:
    """Format work and internship experience into a human-friendly label.
    If experience is under 1 year (e.g. 3 months internship), displays as '3 months' (or '3 mos' in compact view)
    rather than '0.3 years' or '0 yrs'.
    """
    if months is None:
        try:
            val = float(years or 0)
        except (TypeError, ValueError):
            val = 0.0
        if val <= 0:
            return "0 yrs" if compact else "0 years"
        total_months = round(val * 12)
    else:
        total_months = int(months or 0)

    if total_months <= 0:
        return "0 yrs" if compact else "0 years"

    if total_months < 12:
        unit = ("mo" if total_months == 1 else "mos") if compact else ("month" if total_months == 1 else "months")
        return f"{total_months} {unit}"

    y = total_months // 12
    rem_m = total_months % 12

    if rem_m == 0:
        unit = ("yr" if y == 1 else "yrs") if compact else ("year" if y == 1 else "years")
        return f"{y} {unit}"

    if compact:
        y_unit = "yr" if y == 1 else "yrs"
        m_unit = "mo" if rem_m == 1 else "mos"
        return f"{y} {y_unit} {rem_m} {m_unit}"
    else:
        y_unit = "year" if y == 1 else "years"
        m_unit = "month" if rem_m == 1 else "months"
        return f"{y} {y_unit} {rem_m} {m_unit}"


# ---------------------------------------------------------------------------
# File -> text
# ---------------------------------------------------------------------------
def _extract_page_text_two_col(page, page_obj):
    """Detect if page is formatted in two distinct columns. If so, extracts left column
    then right column to avoid line-interleaved bleeding."""
    try:
        width = float(getattr(page, "width", 0))
        if width < 300:
            return page_obj.extract_text(x_tolerance=2) or ""

        # Extract words with horizontal positions
        words = page_obj.extract_words(x_tolerance=2) or []
        if len(words) < 25:
            return page_obj.extract_text(x_tolerance=2) or ""

        mid = width / 2.0
        # Check if there is a clear gutter near the center (between 30% and 70% width)
        # Count words overlapping the candidate vertical gutters
        left_words = [w for w in words if w.get("x1", 0) <= mid]
        right_words = [w for w in words if w.get("x0", 0) >= mid]
        cross_words = [w for w in words if w.get("x0", 0) < mid and w.get("x1", 0) > mid]

        # If a significant number of words sit clearly on both sides with very few crossing words
        if len(left_words) >= 15 and len(right_words) >= 15 and len(cross_words) <= 3:
            # Two-column layout detected! Crop left and right columns
            left_box = (0, 0, mid, float(page.height))
            right_box = (mid, 0, width, float(page.height))
            left_crop = page_obj.crop(left_box)
            right_crop = page_obj.crop(right_box)
            left_text = left_crop.extract_text(x_tolerance=2) or ""
            right_text = right_crop.extract_text(x_tolerance=2) or ""
            return f"{left_text}\n{right_text}".strip()
    except Exception:
        pass
    try:
        return page_obj.extract_text(x_tolerance=2) or ""
    except TypeError:
        return page_obj.extract_text() or ""


def extract_text_from_pdf(file_bytes: bytes) -> str:
    import pdfplumber
    text_chunks = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            # Filter out double-strike bold / shadow duplicate characters
            # often emitted by Canva, LaTeX, and Word PDF generators
            seen_chars = set()
            dup_ids = set()
            for c in getattr(page, "chars", []):
                char_text = c.get("text", "")
                if not char_text.strip():
                    continue
                pos_key = (char_text, round(c.get("x0", 0) / 1.2), round(c.get("top", 0) / 1.2))
                if pos_key in seen_chars:
                    dup_ids.add(id(c))
                else:
                    seen_chars.add(pos_key)

            if dup_ids:
                try:
                    page_to_extract = page.filter(lambda obj: id(obj) not in dup_ids)
                except Exception:
                    page_to_extract = page
            else:
                page_to_extract = page

            t = _extract_page_text_two_col(page, page_to_extract)

            for hyperlink in getattr(page, "hyperlinks", []):
                uri = hyperlink.get("uri")
                if uri:
                    t += f"\n{uri}"
            text_chunks.append(t)
    return clean_doubled_text("\n".join(text_chunks))


def _dedupe_cells(cells):
    out = []
    for c in cells:
        c = " ".join(c.split())
        if not c:
            continue
        if not out or out[-1] != c:
            out.append(c)
    return out


def extract_text_from_docx(file_bytes: bytes) -> str:
    import docx

    doc = docx.Document(io.BytesIO(file_bytes))
    chunks = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            chunks.append(t)
    for table in doc.tables:
        for row in table.rows:
            cells = _dedupe_cells([cell.text.strip() for cell in row.cells])
            if cells:
                chunks.append(" | ".join(cells))
    return clean_doubled_text("\n".join(chunks))


def extract_text(filename: str, file_bytes: bytes) -> str:
    lower = filename.lower()
    try:
        if lower.endswith(".pdf"):
            return extract_text_from_pdf(file_bytes)
        if lower.endswith(".docx"):
            return extract_text_from_docx(file_bytes)
        return clean_doubled_text(file_bytes.decode("utf-8", errors="ignore"))
    except Exception:
        try:
            return clean_doubled_text(file_bytes.decode("utf-8", errors="ignore"))
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------
def _classify_heading(line: str):
    """Return 'experience' / 'education' / 'skills' / 'other' if line is a resume
    section heading, else None. Handles compound headings like 'Projects & Internships',
    and pattern matches non-standard headings."""
    if not line or len(line) > 70:
        return None
    # Strip trailing punctuation, colons, dashes, bullet points
    cleaned_line = line.strip(" \t\r\n:–—•·*#-|_")
    if not cleaned_line:
        return None
    norm = re.sub(r"[^a-z&/ ]+", " ", cleaned_line.lower().replace("-", " "))
    norm = re.sub(r"\s+", " ", norm).strip()
    if not norm or len(norm.split()) > 6:
        return None
    # Section headings do not contain date ranges (e.g. 'Aug 2018 - May 2019')
    if next(_find_ranges(line), None) is not None:
        return None

    # Strict rejection: If the heading is explicitly extracurricular, volunteering, leadership, etc.,
    # it must NEVER be classified as work experience even if the word 'experience' or 'work' appears
    # (e.g. 'Leadership Experience', 'Volunteer Experience', 'Community Service Work', 'Volunteer Work').
    is_non_work = bool(_NON_WORK_SECTION_RE.search(norm))
    if is_non_work and not any(w in norm for w in ("work experience", "professional experience", "employment", "career history", "work history")):
        return "other"

    # Direct match on common sets first
    if norm in _EXPERIENCE_HEADINGS:
        return "experience"
    if norm in _EDUCATION_HEADINGS:
        return "education"
    if norm in _OTHER_HEADINGS:
        if _SKILLS_HEADING_RE.search(norm):
            return "skills"
        return "other"

    parts = [p.strip() for p in re.split(r"\s*&\s*|\s*/\s*|\s+and\s+", norm) if p.strip()]
    kinds = []
    for part in parts:
        part_non_work = bool(_NON_WORK_SECTION_RE.search(part))
        if not part_non_work and (part in _EXPERIENCE_HEADINGS or _EXPERIENCE_HEADING_RE.search(part)):
            kinds.append("experience")
        elif part in _EDUCATION_HEADINGS or _EDUCATION_HEADING_RE.search(part):
            kinds.append("education")
        elif _SKILLS_HEADING_RE.search(part):
            kinds.append("skills")
        elif part in _OTHER_HEADINGS or _OTHER_HEADING_RE.search(part) or part_non_work:
            kinds.append("other")
        else:
            return None
    if not kinds:
        return None
    # Priority: experience > education > skills > other (unless is_non_work is true)
    if "experience" in kinds and not is_non_work:
        return "experience"
    if "education" in kinds:
        return "education"
    if "skills" in kinds:
        return "skills"
    return kinds[0]


def _split_sections(text: str):
    """[(kind, [lines])] where kind is preamble/experience/education/other."""
    sections = []
    kind, buf = "preamble", []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = _classify_heading(line)
        if heading:
            sections.append((kind, buf))
            kind, buf = heading, []
        else:
            buf.append(line)
    sections.append((kind, buf))
    return sections


def _section_text(text: str, kind: str):
    """Joined text of every section of kind, or None if there is none."""
    chunks = [lines for k, lines in _split_sections(text) if k == kind and lines]
    if not chunks:
        return None
    return "\n".join("\n".join(lines) for lines in chunks)


def _section_markers(text: str):
    """Character offsets where each section heading begins: [(offset, heading_kind, raw_heading)]."""
    markers = []
    offset = 0
    for raw in text.splitlines(keepends=True):
        line = raw.strip()
        if line:
            heading = _classify_heading(line)
            if heading:
                markers.append((offset, heading, line))
        offset += len(raw)
    return markers


def _section_info_at(markers, positions, idx: int):
    """Return (kind, heading_text) for character position idx."""
    i = bisect.bisect_right(positions, idx) - 1
    if i >= 0:
        return markers[i][1], markers[i][2]
    return "preamble", ""


def _section_kind_at(markers, positions, idx: int):
    """Which section owns character position idx?"""
    return _section_info_at(markers, positions, idx)[0]


# ---------------------------------------------------------------------------
# Work & Internship Experience Date Ranges
# ---------------------------------------------------------------------------
_MONTH_PAT = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_SEASON_PAT = r"(?:spring|summer|fall|autumn|winter)"
_SEASON_NUM = {
    "spring": 3,
    "summer": 6,
    "fall": 9,
    "autumn": 9,
    "winter": 12,
}
_MONTH_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_YEAR_PAT = r"(?:19|20)\d{2}"
_TWO_DIGIT_YEAR_PAT = r"(?:'|’)?\d{2}"
_SEP_PAT = r"\s*(?:[-–—‒―‑−－]|\bto\b|\buntil\b|\btill\b)\s*"
_PRESENT_PAT = r"(?:present|current|now|ongoing|today|till\s+date|to\s+date|date)"

# 'Jan 2020 - Mar 2022', '2019 - 2023', '2023 - Present', 'Dec 2013 to Current', 'Jun \'18 - Aug \'20'
_RANGE_FULL_RE = re.compile(
    rf"(?<![\w/])(?:(?P<sm>{_MONTH_PAT}|{_SEASON_PAT})\.?,?\s*)?(?P<sy>{_YEAR_PAT}|(?:'|’)\d{{2}}){_SEP_PAT}"
    rf"(?:(?:(?P<em>{_MONTH_PAT}|{_SEASON_PAT})\.?,?\s*)?(?P<ey>{_YEAR_PAT}|(?:'|’)\d{{2}})|(?P<pres>{_PRESENT_PAT}))(?![\w])",
    re.IGNORECASE,
)
# 'July-July 2025', 'Jun - Aug 2024' (year written once, at the end)
_RANGE_MONTHS_RE = re.compile(
    rf"(?<![\w/])(?P<sm>{_MONTH_PAT})\.?{_SEP_PAT}(?P<em>{_MONTH_PAT})\.?,?\s*(?P<y>{_YEAR_PAT}|(?:'|’)\d{{2}})(?![\w])",
    re.IGNORECASE,
)
# '06/2013 to 09/2013', '12/2015 - Current', '01/2021', '06/18 - 12/20'
_RANGE_NUMERIC_RE = re.compile(
    rf"(?<![\w/])(?P<sm>0?[1-9]|1[0-2])\s*[/.]\s*(?P<sy>{_YEAR_PAT}|\d{{2}}){_SEP_PAT}"
    rf"(?:(?P<em>0?[1-9]|1[0-2])\s*[/.]\s*(?P<ey>{_YEAR_PAT}|\d{{2}})|(?P<pres>{_PRESENT_PAT}))(?![\w])",
    re.IGNORECASE,
)


def _normalize_year(yr_str: str) -> int:
    if not yr_str:
        return None
    cleaned = yr_str.strip("'’ ")
    if len(cleaned) == 4 and cleaned.isdigit():
        return int(cleaned)
    if len(cleaned) == 2 and cleaned.isdigit():
        val = int(cleaned)
        curr_yr = _dt.date.today().year
        cutoff = (curr_yr % 100) + 1
        return (2000 + val) if val <= cutoff else (1900 + val)
    return int(cleaned) if cleaned.isdigit() else None


def _month_num(token):
    if not token:
        return None
    token_str = token.strip().lower()
    if token_str.isdigit():
        return int(token_str)
    if token_str in _SEASON_NUM:
        return _SEASON_NUM[token_str]
    return _MONTH_NUM.get(token_str[:3])


def _find_ranges(text: str):
    """Yield (match, (start_year, start_month, end_year, end_month, is_present))
    for every date range in text, without overlapping matches."""
    found = []
    for m in _RANGE_FULL_RE.finditer(text):
        sy = _normalize_year(m["sy"])
        ey = _normalize_year(m["ey"]) if m["ey"] else None
        found.append((m, (sy, _month_num(m["sm"]), ey, _month_num(m["em"]), bool(m["pres"]))))
    for m in _RANGE_MONTHS_RE.finditer(text):
        sm, em = _month_num(m["sm"]), _month_num(m["em"])
        y = _normalize_year(m["y"])
        found.append((m, (y if (sm and em and sm <= em) else y - 1, sm, y, em, False)))
    for m in _RANGE_NUMERIC_RE.finditer(text):
        sy = _normalize_year(m["sy"])
        ey = _normalize_year(m["ey"]) if m["ey"] else None
        found.append((m, (sy, _month_num(m["sm"]), ey, _month_num(m["em"]), bool(m["pres"]))))

    found.sort(key=lambda item: (item[0].start(), -(item[0].end() - item[0].start())))
    last_end = -1
    for m, parts in found:
        if m.start() < last_end:
            continue
        last_end = m.end()
        yield m, parts


def _interval(sy, sm, ey, em, is_present, now):
    """Month-index interval [start, end) or None.
    - Normalizes dates to month/year precision.
    - If a range has only years (no months), uses January of start year and December of end year.
    - Merges overlapping or adjacent intervals.
    - Future dates are clamped to today so '2023-2027' cannot inflate experience.
    """
    if not sy:
        return None
    now_idx = now.year * 12 + now.month - 1
    # If role has start month use it, else default to January
    start = sy * 12 + ((sm or 1) - 1)

    if is_present:
        end = now_idx + 1
    elif em:
        end = ey * 12 + em                 # end month is inclusive (1-12)
    elif sm:
        end = (ey if ey else sy) * 12 + (sm - 1)
    elif ey:
        # Range has only years (e.g. 2021 - 2023) -> whole years between (ey - sy)
        end = ey * 12
        if ey == sy:
            end = start + 12
    else:
        end = start + 12

    if is_present:
        end = min(end, now_idx + 1)
    elif start <= now_idx:
        end = min(end, now_idx + 1)
    elif ey is not None and ey > now.year + 10:
        return None

    if end <= start or end - start > 12 * 50:
        return None
    return start, end


_SENT_BREAK_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\u2022\u00b7\u25aa\u25cf])")
_ABBREVIATIONS = {"inc", "ltd", "pvt", "co", "corp", "llc", "sr", "jr", "dr", "mr", "ms", "mrs", "st", "dept"}


def _real_breaks(s: str):
    """Sentence breaks, ignoring 'Inc. ' / 'Ltd. ' / initials."""
    for m in _SENT_BREAK_RE.finditer(s):
        prev = re.search(r"(\w+)[.!?]$", s[:m.start()])
        if prev and (prev.group(1).lower() in _ABBREVIATIONS or len(prev.group(1)) == 1):
            continue
        yield m


def _cut_before(s: str) -> str:
    last = None
    for last in _real_breaks(s):
        pass
    return s[last.end():] if last else s


def _cut_after(s: str) -> str:
    first = next(_real_breaks(s), None)
    return s[:first.start()] if first else s


def _line_bounds(text: str, start: int, end: int):
    ls = text.rfind("\n", 0, start) + 1
    le = text.find("\n", end)
    return ls, (len(text) if le == -1 else le)


def _adjacent_lines(text: str, ls: int, le: int):
    """The nearest non-blank line above and below, minus headings and date lines."""
    found = []
    pos = ls
    while pos > 0:
        pe = pos - 1
        ps = text.rfind("\n", 0, pe) + 1
        line, pos = text[ps:pe].strip(), ps
        if line:
            found.append(line[-80:])
            break
    pos = le
    while pos < len(text):
        ns = pos + 1
        ne = text.find("\n", ns)
        ne = len(text) if ne == -1 else ne
        line, pos = text[ns:ne].strip(), ne
        if line:
            found.append(line[:80])
            break
    return [
        ln for ln in found
        if not _classify_heading(ln) and next(_find_ranges(ln), None) is None
    ]


def _work_periods(text: str, now):
    """[(interval, period_text, context)] for every date range that represents a real job or internship."""
    markers = _section_markers(text)
    positions = [pos for pos, _, _ in markers]
    periods = []
    for m, parts in _find_ranges(text):
        ls, le = _line_bounds(text, m.start(), m.end())
        before = _cut_before(text[max(ls, m.start() - 120):m.start()])
        after = _cut_after(text[m.end():min(le, m.end() + 90)])
        own = f"{before} {after}"
        own_has_title = bool(_WORK_TITLE_RE.search(own))

        sec_kind, sec_heading = _section_info_at(markers, positions, m.start())

        # Strict rejection: Reject entries that appear under "Extra-Curricular Activities,"
        # "Volunteering," "Leadership," or similar non-work sections.
        if sec_heading and _NON_WORK_SECTION_RE.search(sec_heading):
            continue

        if sec_kind in ("education", "other"):
            context_line = own
            if le - ls <= 140:
                context_line += " " + " ".join(_adjacent_lines(text, ls, le))
            has_title = own_has_title or bool(_WORK_TITLE_RE.search(context_line))
            has_employer_or_sep = bool(
                _EMPLOYER_RE.search(context_line)
                or " - " in context_line
                or " at " in context_line
                or " @ " in context_line
                or "|" in context_line
                or "(" in context_line
            )
            is_real_role = has_title and has_employer_or_sep and not _DEGREE_RE.search(own)
            if not is_real_role:
                continue

        # (b) never next to a degree / grade / unpaid role, or institution without job title
        if _DEGREE_RE.search(own) or _UNPAID_ROLE_RE.search(own):
            continue
        if _STUDENT_CONTEXT_RE.search(own) and not own_has_title:
            continue

        # (c) must look like a job or internship: title / intern / employer marker nearby
        context = own
        if le - ls <= 140:
            context += " " + " ".join(_adjacent_lines(text, ls, le))
        if _UNPAID_ROLE_RE.search(context):
            continue
        if not (_WORK_TITLE_RE.search(context) or _EMPLOYER_RE.search(context)):
            continue

        iv = _interval(*parts, now)
        if iv:
            snippet = re.sub(r"\s+", " ", f"{before[-90:]}{m.group(0)}{after[:45]}").strip()
            is_present = bool(parts[4])
            periods.append((iv, m.group(0).strip(), snippet, is_present, context))

    # Deduplicate roles by (company, title, start_date, end_date) composite key
    # before merging intervals and summing.
    deduped_periods = []
    seen_role_keys = set()

    for item in periods:
        iv, date_str, snippet, is_present, ctx = item
        # Extract title and company keywords for the composite key
        title_m = _WORK_TITLE_RE.search(ctx)
        title_key = title_m.group(0).lower() if title_m else ""
        emp_m = _EMPLOYER_RE.search(ctx)
        emp_key = emp_m.group(0).lower() if emp_m else ""
        
        # Composite key: (company, title, start_month_idx, end_month_idx)
        role_key = (emp_key, title_key, iv[0], iv[1])
        if role_key in seen_role_keys:
            continue
        seen_role_keys.add(role_key)
        deduped_periods.append((iv, date_str, snippet, is_present))

    return deduped_periods


def _merged_months(intervals) -> int:
    merged = []
    for s, e in sorted(intervals):  # union, so overlapping roles are never double counted
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return sum(e - s for s, e in merged)


USE_STATED_YEARS_FALLBACK = True


def extract_work_periods(text: str, now=None, include_undated: bool = True):
    """The jobs and internships that count towards experience, for verification:
    [{'period': 'Jan 2020 - Present', 'months': 81, 'context': '...'}]"""
    now = now or _dt.date.today()
    periods = _work_periods(text, now)
    results = []
    if periods:
        has_present = any(item[3] for item in periods if len(item) > 3)
        total_m = _merged_months([item[0] for item in periods])
        reconciled_cap = None
        if has_present:
            claims = [float(match.group(1)) for match in YEARS_EXP_RE.finditer(text)]
            claims = [c for c in claims if 0 < c <= 50]
            if claims:
                stated_m = round(max(claims) * 12)
                if total_m > stated_m + 12:
                    closed_m = _merged_months([item[0] for item in periods if len(item) > 3 and not item[3]])
                    reconciled_cap = max(closed_m, stated_m)

        for item in periods:
            iv, period, ctx = item[0], item[1], item[2]
            is_pres = item[3] if len(item) > 3 else False
            m_cnt = iv[1] - iv[0]
            if is_pres and reconciled_cap is not None:
                other_m = _merged_months([it[0] for it in periods if it is not item])
                m_cnt = max(1, reconciled_cap - other_m)
            results.append({
                "period": period,
                "months": m_cnt,
                "context": ctx,
                "is_present": is_pres,
            })

    # Stated internship duration fallback (e.g. '3 months internship')
    if not results:
        m = MONTHS_EXP_RE.search(text) or INTERNSHIP_DURATION_RE.search(text)
        if m:
            stated_m = int(m.group(1))
            if 0 < stated_m <= 120:
                results.append({"period": f"{stated_m} months", "months": stated_m, "context": m.group(0)})

    if include_undated and text:
        markers = _section_markers(text)
        positions = [pos for pos, _, _ in markers]
        cur_offset = 0
        for raw_line in text.splitlines(keepends=True):
            line = raw_line.strip()
            line_pos = cur_offset
            cur_offset += len(raw_line)
            if not line or len(line) < 15 or len(line) > 120 or line.startswith(('•', '-', '*', '·')):
                continue
            if any(p['period'] in line for p in results if p.get('period') != "Dates not specified"):
                continue
            if _DEGREE_RE.search(line) or _classify_heading(line) or _UNPAID_ROLE_RE.search(line):
                continue
            _, sec_heading = _section_info_at(markers, positions, line_pos)
            if sec_heading and _NON_WORK_SECTION_RE.search(sec_heading):
                continue
            if _WORK_TITLE_RE.search(line) and (_EMPLOYER_RE.search(line) or ' - ' in line or ' at ' in line or ' @ ' in line or '(' in line):
                if not any(line in p.get('context', '') for p in results):
                    results.append({"period": "Dates not specified", "months": 0, "context": line})

    return results


def extract_experience_months(text: str, now=None) -> int:
    """Total months of work & internship experience.
    Sums non-overlapping paid roles, contracts, and internships."""
    now = now or _dt.date.today()
    periods = _work_periods(text, now)
    if periods:
        has_present = any(item[3] for item in periods if len(item) > 3)
        total_m = _merged_months([item[0] for item in periods])

        # When an open-ended role ("to Current" / "to Present") exists, check if the candidate
        # explicitly stated their overall experience claim in the resume text (e.g. "5 years of experience").
        # If the open-ended calculation with today's date vastly exceeds their stated claim,
        # it indicates an older/benchmark resume where "Current" meant the date of authoring.
        if has_present:
            claims = [float(match.group(1)) for match in YEARS_EXP_RE.finditer(text)]
            claims = [c for c in claims if 0 < c <= 50]
            if claims:
                stated_m = round(max(claims) * 12)
                if total_m > stated_m + 12:
                    closed_m = _merged_months([item[0] for item in periods if len(item) > 3 and not item[3]])
                    return max(closed_m, stated_m)

        return total_m

    m = MONTHS_EXP_RE.search(text) or INTERNSHIP_DURATION_RE.search(text)
    if m:
        stated_m = int(m.group(1))
        if 0 < stated_m <= 120:
            return stated_m

    if USE_STATED_YEARS_FALLBACK:
        claims = [float(match.group(1)) for match in YEARS_EXP_RE.finditer(text)]
        claims = [c for c in claims if 0 < c <= 50]
        if claims:
            return round(max(claims) * 12)

    return 0


def extract_years_experience(text: str, now=None) -> float:
    """Years of work & internship experience.
    Education, projects, certifications, volunteering, publications and
    degree dates never count. Overlapping jobs/internships are merged."""
    now = now or _dt.date.today()
    months = extract_experience_months(text, now)
    if months:
        return round(months / 12, 1)
    return 0.0


# ---------------------------------------------------------------------------
# Name / Phone / Contact Extraction
# ---------------------------------------------------------------------------
_NAME_SPLIT_RE = re.compile(r"[|•·▪◦●■◆#§¶†‡*,;]|\s{3,}")


def _header_segments(line: str):
    """Split a header line into candidate chunks with contact details removed."""
    s = re.sub(r"\(cid:\d+\)", " | ", line)
    s = EMAIL_RE.sub(" | ", s)
    s = URL_RE.sub(" | ", s)
    s = PHONE_RE.sub(" | ", s)
    s = re.sub(r"[\ue000-\uf8ff]", " | ", s)
    return [seg.strip(" .:-–—_") for seg in _NAME_SPLIT_RE.split(s) if seg.strip(" .:-–—_")]


def _name_words_ok(words) -> bool:
    return not any(w.lower().strip(".,-:;()") in _NON_NAME_WORDS for w in words)


def _is_name_word(w: str) -> bool:
    return re.sub(r"[.'’\-]", "", w).isalpha()


def guess_name(text: str, fallback: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for i, line in enumerate(lines[:20]):
        segments = _header_segments(line)
        for seg in segments:
            if len(seg) > 45 or _classify_heading(seg) or seg.lower() in STOPWORD_NAME_LINES:
                continue
            words = seg.split()
            if not _name_words_ok(words):
                continue

            # Normal case: name is on one line
            if 1 < len(words) <= 4 and all(_is_name_word(w) for w in words):
                return seg.title() if seg.isupper() else seg

            # PDF-layout case: name split across two lines (e.g. AHELI \n BANERJEE)
            if len(words) == 1 and seg.isalpha() and len(segments) == 1 and i + 1 < len(lines):
                nxt = _header_segments(lines[i + 1])
                if len(nxt) == 1:
                    nxt_seg = nxt[0]
                    if (
                        nxt_seg.isalpha()
                        and len(nxt_seg) <= 30
                        and _name_words_ok([nxt_seg])
                        and nxt_seg.lower() not in STOPWORD_NAME_LINES
                    ):
                        return f"{seg.title()} {nxt_seg.title()}"

    return fallback


def extract_phone(text: str) -> str:
    """First candidate that is really a phone number: right digit count, not a
    '2019-2023' date range, and not labelled as an ID ('Roll No.: 12230623055')."""
    for m in PHONE_RE.finditer(text):
        candidate = m.group(0).strip()
        digits = re.sub(r"\D", "", candidate)
        has_plus = candidate.startswith("+")

        if YEAR_RANGE_LOOKALIKE_RE.match(candidate):
            continue
        if has_plus:
            if not 8 <= len(digits) <= 15:
                continue
        else:
            plausible = (
                7 <= len(digits) <= 10
                or (len(digits) == 11 and digits[0] in "01")
                or (len(digits) == 12 and digits.startswith("91"))
            )
            if not plausible:
                continue

        line_start = text.rfind("\n", 0, m.start()) + 1
        if PHONE_ID_LABEL_RE.search(text[line_start:m.start()]):
            continue
        return candidate
    return None


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


def extract_social_links(text: str) -> dict:
    """Extract professional links (LinkedIn, GitHub, Portfolio)."""
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


# ---------------------------------------------------------------------------
# Education Extraction
# ---------------------------------------------------------------------------
def extract_education_section(text: str) -> str:
    """Extract specifically the Education section text from a resume to avoid
    false positive degree matches from other sections."""
    sec = _section_text(text, "education")
    if sec:
        return sec
    edu_match = re.search(
        r"(?:^|\n)\s*(?:education|academic\s+background|academics|qualifications)\b[:\s]*(.*?)(?=\n\s*(?:experience|skills|projects|certifications|awards|interests)\b|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if edu_match and len(edu_match.group(1).strip()) > 5:
        return edu_match.group(1)
    return ""


def extract_education(text: str, mode: str = "highest") -> str:
    """Degree level mentioned in text (in the Education section if present).

    mode='highest' - candidate level (resumes).
    mode='lowest'  - minimum JD requirement ('Bachelor's required, Master's preferred' -> Bachelor's).
    """
    scopes = []
    edu_text = extract_education_section(text)
    if edu_text:
        scopes.append(edu_text)
    scopes.append(text)

    levels = EDUCATION_LEVELS if mode == "highest" else list(reversed(EDUCATION_LEVELS))
    for scope in scopes:
        for pattern, label in levels:
            if pattern.search(scope):
                return label
        # If an explicit education section exists, do not fall back to search other sections
        if scope is edu_text and edu_text:
            break
    return "Not detected"


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Location & Contact Block Filtering
# ---------------------------------------------------------------------------
LOCATION_RE = re.compile(
    r"\b(?:[A-Z][a-zA-Z\s.-]+,\s*(?:[A-Z]{2}|[A-Za-z\s]+)(?:\s+\d{5}(?:-\d{4})?)?|remote|hybrid|on-?site|relocate)\b",
    re.IGNORECASE,
)

COMMON_ENGLISH_STOPWORDS = {
    "and", "with", "for", "the", "of", "to", "in", "at", "by", "on", "from",
    "as", "an", "a", "or", "is", "are", "was", "were", "be", "been", "using",
    "such", "into", "through", "across", "candidate", "resume", "curriculum", "vitae",
}

SINGLE_LETTER_WHITELIST = {"c", "r"}


NUMBER_START_WHITELIST = {"3ds max", "7-zip", "802.11", "3d modeling", "3d design", "2d animation", "3d animation"}
COMPOUND_STOPWORD_WHITELIST = {"design of experiments", "internet of things", "point of sale", "c++", "c#", ".net"}


# Generic / weak skills that dilute match quality
GENERIC_WEAK_SKILLS = {
    "architecture",
    "application server",
    "access",
    "backup",
    "backups",
}


def _is_valid_skill_token(token: str, in_skills_section: bool = False, full_text: str = "") -> bool:
    """Filter out leaked headers, US state codes, single-letter junk, role titles, date fragments,
    mixed year/digit fragments, numbers, and invalid sentence pieces (Bug C validation layer)."""
    if not token:
        return False
    raw = token.strip()
    low = raw.lower().strip(".,:;()[]{}*#-–—/|")
    if not low:
        return False

    # Issue 4: Reject generic / weak skills that dilute match quality
    if low in GENERIC_WEAK_SKILLS:
        return False

    # 1. Word count constraint: Real skills are 1–4 words long
    words = low.split()
    if len(words) < 1 or len(words) > 4:
        return False

    # 2. Never emit structural stop words (headers, sections)
    if low in STRUCTURAL_STOP_WORDS:
        return False
    if any(low == s or low.startswith(s + " ") or low.endswith(" " + s) for s in STRUCTURAL_STOP_WORDS):
        return False

    # 3. English stopword fragments
    if low in COMMON_ENGLISH_STOPWORDS:
        return False

    # Standalone stopwords inside token: don't contain 'to', 'and', 'of', 'for' as standalone words
    # unless part of a known whitelisted compound name like "Design of Experiments"
    if low not in COMPOUND_STOPWORD_WHITELIST:
        internal_stopwords = {"to", "and", "of", "for", "in", "at", "with", "from", "by", "on"}
        if any(w in internal_stopwords for w in words):
            return False

    # 4. Don't start with a number (unless it's a known whitelisted tool/domain like 3ds Max, 3D Modeling)
    if low[0].isdigit() and low not in NUMBER_START_WHITELIST:
        return False

    # 5. Don't mix digits and years / dates (e.g. '2011 aix', '09/2007', '2008 unix', '2007 to 11')
    if re.search(r"\b(?:19|20)\d{2}\b", low):
        # A 4-digit year should not be part of a skill unless in a specific taxonomy term
        return False
    if re.search(r"\b\d{1,2}/\d{2,4}\b", low):
        return False
    if any(w.isdigit() for w in words) and low not in NUMBER_START_WHITELIST:
        return False

    # 6. Single-character tokens: only 'c' or 'r' inside a Skills section or with explicit language context
    if len(low) == 1:
        if low not in SINGLE_LETTER_WHITELIST:
            return False
        if not in_skills_section:
            ctx_pat = rf"\b{re.escape(low)}\s*[/,]\s*(?:c\+\+|python|java|sql)|(?:language|programming|software)\s*:\s*.*?\b{re.escape(low)}\b"
            if not re.search(ctx_pat, full_text or "", re.IGNORECASE):
                return False

    # 7. Two-letter tokens matching US State codes (TX, CA, NY...) unless explicitly in taxonomy (like Go, AI, UI)
    if len(low) == 2 and low in US_STATE_CODES:
        if low not in ("go", "ai", "ui", "ux", "ts", "js", "pm", "qa", "hr"):
            return False

    # 8. Job title vs skill disambiguation: If token is a job title phrase
    if ROLE_TITLE_PATTERNS.search(low):
        if any(role_word in low for role_word in ("analyst", "engineer", "manager", "developer", "scientist", "consultant", "specialist", "intern", "director", "lead", "architect")):
            if low not in ("data engineering", "mechanical design", "electrical engineering", "quality assurance"):
                return False

    # 9. Location / Contact / Metadata words
    if low in ("austin", "texas", "california", "new york", "remote", "hybrid", "on-site", "not detected", "email", "phone"):
        return False

    return True


# ---------------------------------------------------------------------------
# Skills Extraction
# ---------------------------------------------------------------------------
def extract_skills(text: str, extra_skills: list = None) -> list:
    """Extract skills with strict boundary enforcement, synonym canonicalization,
    header stop-list rejection, short token filtering, and title disambiguation."""
    if not text:
        return []

    # Strip contact block (top portion before first substantive header or contact items)
    cleaned_text = EMAIL_RE.sub(" ", text)
    cleaned_text = PHONE_RE.sub(" ", cleaned_text)
    cleaned_text = URL_RE.sub(" ", cleaned_text)

    # Sanitize dates (e.g. '09/2007 to 11/2008', '2019-2023', '06/2016') so date numbers
    # never stick to adjacent skills or combine with slashes (e.g. preventing '2007 to 11')
    cleaned_text = re.sub(r"\b\d{1,2}/\d{2,4}\b", " ", cleaned_text)
    cleaned_text = re.sub(r"\b(?:19|20)\d{2}\s*(?:to|-|–|—)\s*(?:(?:19|20)\d{2}|present|current|till\s+date|to\s+date)\b", " ", cleaned_text, flags=re.IGNORECASE)

    # Replace newlines with spaces so newlines act as proper word boundaries
    cleaned_text = cleaned_text.replace("\r", " ").replace("\n", " ")

    low = " " + re.sub(r"[^a-z0-9.+#/\s-]", " ", cleaned_text.lower()) + " "

    # Longest-match-first lookup across synonyms and master skills
    all_dict_items = []
    # 1. Synonyms: (alias, canonical_target)
    for alias, canonical in SYNONYMS.items():
        all_dict_items.append((alias.strip(), canonical))
    # 2. Master skills: (skill_name, canonical_target)
    for skill in MASTER_SKILLS:
        skill_clean = skill.strip()
        all_dict_items.append((skill_clean, canonicalize(skill_clean)))
    # 3. Extra skills
    for skill in (extra_skills or []):
        skill_clean = skill.strip()
        if skill_clean:
            all_dict_items.append((skill_clean, canonicalize(skill_clean)))

    # Sort dictionary entries by length descending for longest-match-first extraction
    all_dict_items.sort(key=lambda item: len(item[0]), reverse=True)

    candidates = set()

    for pattern_term, canonical_name in all_dict_items:
        term_clean = pattern_term.strip()
        term_low = term_clean.lower()
        if not _is_valid_skill_token(term_clean, in_skills_section=True, full_text=text):
            continue
        if not _is_valid_skill_token(canonical_name, in_skills_section=True, full_text=text):
            continue

        pattern = r"(?<![a-z0-9])" + re.escape(term_low) + r"(?![a-z0-9])"
        if re.search(pattern, low):
            candidates.add(canonical_name)

    # Dedicated Skills Sections extraction
    skills_sec_text = _section_text(text, "skills") or ""
    if not skills_sec_text:
        match = re.search(r"(?:skills|technologies|proficiencies|tech\s+stack)[\s]*:[\s]*(.*?)(?:\n\n|\Z)", text, re.IGNORECASE | re.DOTALL)
        if match:
            skills_sec_text = match.group(1)

    if skills_sec_text:
        tokens = re.split(r'[,\n•·|;/]', skills_sec_text)
        for token in tokens:
            token = token.strip()
            if not token or len(token) > 35 or len(token.split()) > 3:
                continue
            if _is_valid_skill_token(token, in_skills_section=True, full_text=text):
                canon = canonicalize(token)
                if _is_valid_skill_token(canon, in_skills_section=True, full_text=text):
                    candidates.add(canon)

    # Issue 2: Case-insensitive deduplication
    # Issue 1: Canonical dictionary lookup (map raw to canonical form)
    canon_map = {}
    for item in candidates:
        low_k = item.strip().lower()
        if low_k not in canon_map:
            canon_map[low_k] = item

    # Issue 3: Substring overlaps — Longest-match-first extraction, plus a rule
    # that drops a skill if it's a strict substring/subphrase of another matched skill
    # (e.g., drops 'Access' if 'Access Control' appears, or 'Backup' if 'Backups' appears)
    sorted_terms = sorted(canon_map.keys(), key=lambda x: len(x), reverse=True)
    kept_terms = []

    for term in sorted_terms:
        # Whitelisted single-letter skills like 'c' or 'r' are distinct languages and should not be suppressed by 'cross'
        if term in SINGLE_LETTER_WHITELIST:
            kept_terms.append(term)
            continue

        # Check if this term is a strict substring/subphrase of any already accepted longer skill
        is_sub = False
        for longer in kept_terms:
            # 1. Multi-word phrase boundary (e.g. 'access' in 'access control')
            if re.search(rf"\b{re.escape(term)}\b", longer):
                is_sub = True
                break
            # 2. Plural or singular stem variation (e.g. 'backup' vs 'backups', 'test' vs 'tests')
            if longer == term + "s" or longer == term + "es" or term == longer + "s":
                is_sub = True
                break
        if not is_sub:
            kept_terms.append(term)

    final_skills = [canon_map[t] for t in kept_terms]
    return sorted(final_skills)


# ---------------------------------------------------------------------------
# Parse Confidence Scoring
# ---------------------------------------------------------------------------
def compute_parse_confidence(doc: ParsedDocument, raw_text: str) -> tuple:
    """Calculate parse confidence score (0.0 to 1.0) and explanatory reasons."""
    reasons = []
    score = 0.0

    # 1. Contact information detection
    has_contact = False
    if doc.email and doc.email != "Not detected":
        score += 0.20
        has_contact = True
    if doc.phone and doc.phone != "Not detected":
        score += 0.15
        has_contact = True
    if not has_contact:
        reasons.append("No verified email or phone detected.")

    # 2. Section detection coverage
    sections = _split_sections(raw_text)
    section_kinds = {k for k, lines in sections if lines}
    if "experience" in section_kinds or doc.years_experience > 0:
        score += 0.25
    else:
        reasons.append("No distinct Experience section or dated roles identified.")

    if "education" in section_kinds or (doc.education and doc.education != "Not detected"):
        score += 0.20
    else:
        reasons.append("No explicit Education section or degree identified.")

    if "skills" in section_kinds or len(doc.skills) >= 3:
        score += 0.20
    else:
        reasons.append("Fewer than 3 skills identified.")

    confidence = round(min(max(score, 0.0), 1.0), 2)
    return confidence, reasons


# ---------------------------------------------------------------------------
# High-Level Document Parsing
# ---------------------------------------------------------------------------
def parse_document(filename: str, file_bytes: bytes, extra_skills: list = None) -> ParsedDocument:
    text = extract_text(filename, file_bytes)
    fallback_name = re.sub(r"\.[a-zA-Z0-9]+$", "", filename).replace("_", " ").replace("-", " ").title()

    email = extract_email(text)
    phone = extract_phone(text)
    social_links = extract_social_links(text)
    exp_months = extract_experience_months(text)
    years_exp = extract_years_experience(text)
    skills = extract_skills(text, extra_skills=extra_skills)
    edu = extract_education(text)

    input_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
    today_iso = _dt.date.today().isoformat()

    doc = ParsedDocument(
        raw_text=text,
        name=guess_name(text, fallback_name),
        email=email,
        phone=phone if phone else "Not detected",
        **social_links,
        education=edu,
        years_experience=years_exp,
        experience_months=exp_months,
        skills=skills,
        input_hash=input_hash,
        resolved_present_date=today_iso,
    )

    conf_score, conf_reasons = compute_parse_confidence(doc, text)
    doc.parse_confidence = conf_score
    doc.confidence_reasons = conf_reasons
    return doc


def parse_job_description(jd_text: str, min_years_override=None, extra_skills: list = None) -> dict:
    """Parse JD text into required skills, preferred skills, experience, and education."""
    all_skills = extract_skills(jd_text, extra_skills=extra_skills)

    # Distinguish Required vs. Preferred qualifications
    req_match = re.search(
        r"(?:required|minimum|basic qualifications?|what you('ll| will) need|must have)[:\s]*(.*?)(?=(?:preferred|nice to have|bonus|desired|additional qualifications?)\b|\Z)",
        jd_text,
        re.IGNORECASE | re.DOTALL,
    )
    pref_match = re.search(
        r"(?:preferred|nice to have|bonus|desired|additional qualifications?)[:\s]*(.*?)(?=(?:required|benefits|about us|responsibilities)\b|\Z)",
        jd_text,
        re.IGNORECASE | re.DOTALL,
    )

    if req_match or pref_match:
        req_text = req_match.group(1) if req_match else ""
        pref_text = pref_match.group(1) if pref_match else ""
        req_skills = extract_skills(req_text, extra_skills=extra_skills)
        pref_skills = extract_skills(pref_text, extra_skills=extra_skills)

        # In case a skill was in both, assign to required
        pref_skills = [s for s in pref_skills if s not in req_skills]
        # Any remaining skills not in pref belong to required
        for s in all_skills:
            if s not in pref_skills and s not in req_skills:
                req_skills.append(s)
    else:
        req_skills = all_skills
        pref_skills = []

    years_match = YEARS_EXP_RE.search(jd_text)
    min_years = float(years_match.group(1)) if years_match else (min_years_override or 0.0)
    if not min_years:
        months_match = MONTHS_EXP_RE.search(jd_text) or INTERNSHIP_DURATION_RE.search(jd_text)
        if months_match:
            min_years = round(int(months_match.group(1)) / 12, 2)
    education = extract_education(jd_text, mode="lowest")
    is_internship = bool(re.search(r"\b(?:intern(?:s|ship|ships)?|trainee)\b", jd_text, re.IGNORECASE))

    return {
        "raw_text": jd_text,
        "required_skills": sorted(req_skills),
        "preferred_skills": sorted(pref_skills),
        "min_years": min_years,
        "required_education": education,
        "is_internship": is_internship,
    }
