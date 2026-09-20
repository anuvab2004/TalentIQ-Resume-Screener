"""
One-off utility (not needed at runtime) used to curate a small, realistic
sample dataset from the provided Resume.csv / job_title_des.csv into
sample_data/. Ships 8 resumes + 3 job descriptions so judges/reviewers can
demo TalentIQ instantly without uploading their own files.

Run once from the repo root:  python scripts/build_sample_data.py
"""
import os
import random
import re

import pandas as pd

random.seed(7)

FIRST_NAMES = ["Ananya", "Rahul", "Priya", "Vikram", "Neha", "Arjun", "Kavya", "Rohan"]
LAST_NAMES = ["Sharma", "Verma", "Singh", "Iyer", "Kapoor", "Rao", "Nair", "Gupta"]

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESUME_CSV = os.path.join(ROOT, "..", "..", "mnt", "user-data", "uploads", "Resume.csv")
JD_CSV = os.path.join(ROOT, "..", "..", "mnt", "user-data", "uploads", "job_title_des.csv")

OUT_RESUMES = os.path.join(ROOT, "sample_data", "resumes")
OUT_JDS = os.path.join(ROOT, "sample_data", "job_descriptions")


def clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Explicit (name -> source row index) picks, chosen so the bundled demo shows
# a realistic score *spread* against the sample Machine Learning / Full Stack /
# DevOps job descriptions -- some strong fits, some deliberate low-match
# examples -- rather than an artificially uniform result. Row indices refer to
# the original Resume.csv.
NAME_PLAN = {
    "Ananya Sharma": (1717, "ENGINEERING"),           # ML tools, Python, C++, MATLAB, SQL
    "Rahul Verma": (1348, "AUTOMOBILE"),               # Python, C, Java, MATLAB, R, SQL
    "Priya Singh": (926, "AGRICULTURE"),               # Software developer: React/Node/JS
    "Vikram Rao": (547, "ADVOCATE"),                   # Cloud / Linux / Solaris platform support
    "Arjun Kapoor": (297, "INFORMATION-TECHNOLOGY"),   # Test automation engineer
    "Kavya Nair": (0, "HR"),
    "Rohan Gupta": (0, "BUSINESS-DEVELOPMENT"),
    "Neha Iyer": (0, "FINANCE"),
}


def build_resumes():
    df = pd.read_csv("/mnt/user-data/uploads/Resume.csv")
    for name, (row_idx, category) in NAME_PLAN.items():
        if row_idx == 0:
            # generic representative for that category (first row)
            row = df[df["Category"] == category].iloc[0]
        else:
            row = df.loc[row_idx]
        email = name.lower().replace(" ", ".") + "@sampledata.dev"
        phone = f"+1-{random.randint(200,999)}-{random.randint(200,999)}-{random.randint(1000,9999)}"
        header = f"{name}\nEmail: {email}\nPhone: {phone}\nRole Focus: {category.replace('-', ' ').title()}\n\n"
        body = clean(row["Resume_str"])
        fname = name.lower().replace(" ", "_") + ".txt"
        with open(os.path.join(OUT_RESUMES, fname), "w", encoding="utf-8") as f:
            f.write(header + body)


def build_jds():
    df = pd.read_csv("/mnt/user-data/uploads/job_title_des.csv")
    targets = ["Machine Learning", "Full Stack Developer", "DevOps Engineer"]
    for title in targets:
        row = df[df["Job Title"] == title].iloc[0]
        fname = title.lower().replace(" ", "_") + ".txt"
        with open(os.path.join(OUT_JDS, fname), "w", encoding="utf-8") as f:
            f.write(f"Job Title: {title}\n\n{clean(row['Job Description'])}")


if __name__ == "__main__":
    os.makedirs(OUT_RESUMES, exist_ok=True)
    os.makedirs(OUT_JDS, exist_ok=True)
    build_resumes()
    build_jds()
    print("Sample data written.")
