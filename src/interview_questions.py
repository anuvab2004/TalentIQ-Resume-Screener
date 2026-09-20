"""
Interview question generator.

Rule-based (curated question bank + templates), same dependency-light spirit
as the rest of TalentIQ — no external LLM call required. Builds a short,
structured interview guide per candidate from the same evidence the matcher
already produced: matched skills (verify depth), missing skills (probe the
gap), years of experience, and the role title.
"""
from .skills_taxonomy import SKILL_TO_CATEGORY

# skill (lowercase) -> list of targeted technical questions
SKILL_QUESTIONS = {
    "python": [
        "Walk me through a Python project where performance mattered — what did you profile and change?",
        "How do you typically structure error handling in a Python service?",
    ],
    "java": [
        "Tell me about a time you had to debug a tricky concurrency issue in Java.",
        "How do you approach memory/performance tuning on the JVM?",
    ],
    "javascript": [
        "How do you handle asynchronous flows in JavaScript — promises, async/await, callbacks?",
        "Describe a bug you tracked down that came from JavaScript's type coercion or scoping.",
    ],
    "sql": [
        "Write out loud how you'd optimize a slow-running SQL query on a large table.",
        "Tell me about a time a JOIN or index choice significantly changed query performance.",
    ],
    "react": [
        "How do you manage state in a mid-to-large React app — and why that approach?",
        "Tell me about a rendering-performance problem you solved in React.",
    ],
    "node.js": [
        "How do you handle backpressure or error propagation in a Node.js service?",
        "Describe how you'd structure a Node.js API for maintainability at scale.",
    ],
    "aws": [
        "Walk me through the AWS services you'd use to deploy a production web app, and why.",
        "Tell me about a time you had to debug or optimize cost on AWS infrastructure.",
    ],
    "azure": [
        "Which Azure services have you used in production, and what was your role in deploying them?",
    ],
    "google cloud platform": [
        "Which GCP services have you used in production, and what was your role in deploying them?",
    ],
    "docker": [
        "Walk me through how you'd containerize an existing application from scratch.",
        "Tell me about a Docker networking or image-size issue you've had to solve.",
    ],
    "kubernetes": [
        "Describe how you'd debug a pod that's crash-looping in production.",
        "How do you approach scaling and resource limits in a Kubernetes deployment?",
    ],
    "machine learning": [
        "Walk me through how you'd frame a business problem as a machine learning problem end to end.",
        "Tell me about a model that underperformed in production — how did you diagnose it?",
    ],
    "deep learning": [
        "How do you decide when a problem actually needs deep learning vs. a simpler model?",
        "Tell me about a training issue (overfitting, vanishing gradients, etc.) you've had to fix.",
    ],
    "natural language processing": [
        "Tell me about an NLP project — what was the data quality like and how did you handle it?",
    ],
    "data science": [
        "Walk me through your end-to-end process on a recent data science project, from raw data to a decision made.",
        "Tell me about a time your analysis changed a stakeholder's mind — how did you present it?",
    ],
    "data analysis": [
        "Tell me about a messy dataset you had to clean — what was wrong with it and how did you fix it?",
    ],
    "tensorflow": [
        "Tell me about a model you built in TensorFlow and a specific tuning decision you made.",
    ],
    "pytorch": [
        "Tell me about a model you built in PyTorch and a specific tuning decision you made.",
    ],
    "django": [
        "How do you structure a Django project as it grows past a single app?",
    ],
    "flask": [
        "How do you structure a Flask app for production — blueprints, config, error handling?",
    ],
    "project management": [
        "Tell me about a project that started slipping its timeline — what did you do?",
        "How do you handle a stakeholder who keeps changing scope mid-project?",
    ],
    "agile": [
        "Tell me about a time your team's agile process broke down — what did you change?",
    ],
    "product management": [
        "Walk me through how you prioritize a roadmap when engineering capacity is limited.",
    ],
    "ui/ux design": [
        "Walk me through your design process from a rough problem statement to a shipped screen.",
        "Tell me about a time user research changed a design you were confident about.",
    ],
    "figma": [
        "How do you organize a Figma file/design system for a team of multiple designers?",
    ],
    "salesforce": [
        "Tell me about a Salesforce customization or integration you built and why.",
    ],
    "financial analysis": [
        "Walk me through a financial model you built — what were the key assumptions and how did you stress-test them?",
    ],
    "accounting": [
        "Tell me about a time you found and resolved a discrepancy during a close or audit.",
    ],
}

# category-level fallback, used when a matched skill has no specific bank entry
CATEGORY_FALLBACK_QUESTIONS = {
    "Programming Languages": "Tell me about the most complex thing you've built with {skill}, and one decision you'd make differently now.",
    "Web & Frameworks": "Walk me through a project where you used {skill} — what tradeoffs did you make?",
    "Data & AI": "Tell me about a project where {skill} was central — what was the hardest part to get right?",
    "Cloud & DevOps": "Describe how you've used {skill} in a production environment.",
    "Databases": "Tell me about a performance or data-integrity issue you solved involving {skill}.",
    "Mobile": "Walk me through an app you shipped using {skill} — what was the biggest challenge?",
    "Design": "Tell me about how you've used {skill} in your design process.",
    "Project & Business": "Tell me about a time you applied {skill} to keep a project or initiative on track.",
    "Finance & Accounting": "Walk me through how you've used {skill} in your day-to-day work.",
    "HR & Recruiting": "Tell me about a situation where {skill} made a real difference in an outcome.",
    "Sales & Marketing": "Tell me about a campaign or deal where {skill} was the key lever.",
    "Healthcare": "Tell me about a situation where {skill} was critical to patient/process outcomes.",
    "Engineering & Manufacturing": "Walk me through a project where {skill} was central to the solution.",
    "Soft Skills": "Tell me about a specific situation where you demonstrated {skill}.",
    "Languages": "Tell me about a time working in {skill} made a difference with a client or colleague.",
}
GENERIC_FALLBACK = "Tell me about your hands-on experience with {skill} — a specific project, not a summary."

GAP_PROBE_TEMPLATE = (
    "The role calls for {skill}, which we didn't see clearly on your resume — "
    "what exposure have you had to it, formally or informally?"
)

EXPERIENCE_QUESTIONS = [
    "Walk me through your career path and how it's led you to apply for this {title} role.",
    "What's the most significant thing you've owned end-to-end in your last role?",
]

BEHAVIORAL_QUESTIONS = [
    "Tell me about a time you disagreed with a decision at work — what did you do?",
    "Describe a project that failed or fell short. What did you learn from it?",
    "Tell me about a time you had to learn something new quickly to get a job done.",
    "Describe how you've handled a tight deadline with competing priorities.",
    "Tell me about a time you had to give a colleague difficult feedback.",
]


def _question_for_skill(skill: str) -> str:
    bank = SKILL_QUESTIONS.get(skill.lower())
    if bank:
        return bank[0]
    category = SKILL_TO_CATEGORY.get(skill.lower())
    template = CATEGORY_FALLBACK_QUESTIONS.get(category, GENERIC_FALLBACK)
    return template.format(skill=skill)


def generate_interview_questions(result, req_title: str) -> list:
    """Build a structured interview guide for one candidate.
    `result` is a matcher.MatchResult. Returns a list of
    {"category": str, "question": str} dicts."""
    questions = []

    top_matched = result.matched_skills[:4] if result.matched_skills else result.extra_skills[:3]
    for skill in top_matched:
        questions.append({"category": f"Technical — {skill}", "question": _question_for_skill(skill)})

    for skill in result.missing_skills[:2]:
        questions.append({"category": f"Gap probe — {skill}", "question": GAP_PROBE_TEMPLATE.format(skill=skill)})

    questions.append({
        "category": "Experience",
        "question": EXPERIENCE_QUESTIONS[0].format(title=req_title or "this"),
    })
    questions.append({"category": "Experience", "question": EXPERIENCE_QUESTIONS[1]})

    # Rotate through the behavioral bank based on candidate name so different
    # candidates for the same req don't all get the identical two questions.
    seed = sum(ord(c) for c in (result.candidate_name or "x")) % len(BEHAVIORAL_QUESTIONS)
    for i in range(2):
        questions.append({
            "category": "Behavioral",
            "question": BEHAVIORAL_QUESTIONS[(seed + i) % len(BEHAVIORAL_QUESTIONS)],
        })

    return questions


def format_questions_text(candidate_name: str, req_title: str, questions: list) -> str:
    lines = [
        f"Interview Guide — {candidate_name}",
        f"Role: {req_title}",
        "=" * 40,
        "",
    ]
    for i, q in enumerate(questions, start=1):
        lines.append(f"{i}. [{q['category']}]")
        lines.append(f"   {q['question']}")
        lines.append("")
    return "\n".join(lines)
