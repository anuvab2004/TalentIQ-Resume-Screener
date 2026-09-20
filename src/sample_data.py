import os

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample_data")
RESUME_DIR = os.path.join(BASE, "resumes")
JD_DIR = os.path.join(BASE, "job_descriptions")


def list_sample_resumes():
    if not os.path.isdir(RESUME_DIR):
        return []
    return sorted(f for f in os.listdir(RESUME_DIR) if f.endswith(".txt"))


def load_sample_resume_bytes(filename):
    with open(os.path.join(RESUME_DIR, filename), "rb") as f:
        return f.read()


def list_sample_jds():
    if not os.path.isdir(JD_DIR):
        return {}
    jds = {}
    for f in sorted(os.listdir(JD_DIR)):
        if f.endswith(".txt"):
            title = f.replace(".txt", "").replace("_", " ").title()
            with open(os.path.join(JD_DIR, f), encoding="utf-8") as fh:
                jds[title] = fh.read()
    return jds
