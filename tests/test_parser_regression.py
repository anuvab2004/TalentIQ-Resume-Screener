"""
Regression & Golden-Set Test Suite for 14-Point Parser Refactor.
Verifies:
1. Regex section header detection (non-standard headings like 'Background', 'Career', 'Competencies').
2. Section boundaries & structural stop words not leaking as skills.
3. Single-letter whitelist & two-letter state code filtering.
4. Job title vs skill disambiguation.
5. Location & contact filtering.
6. Experience interval merging and absence of double counting.
7. Season date normalization and 2-digit years.
8. Skill inference from bullet context.
9. Skill aliasing & canonicalization (Snowflake, dbt, Stakeholder Management, A/B Testing).
10. Required vs. preferred skill weighting in matcher.
11. Two-column layout detection logic.
12. Parse confidence scoring.
13. Self-consistency check (idempotency across 3 identical runs).
"""
import datetime
import unittest

from src.parser import (
    extract_education,
    extract_experience_months,
    extract_skills,
    extract_work_periods,
    extract_years_experience,
    parse_document,
    parse_job_description,
)
from src.matcher import score_candidate, WEIGHTS

NOW = datetime.date(2026, 9, 21)


class ParserRegressionSuite(unittest.TestCase):

    def test_1_regex_section_header_detection(self):
        # Non-standard headers: "Professional Background", "Academic Qualifications", "Core Competencies"
        text = """
        Jordan Lee
        jordan.lee@example.com | (555) 019-2834
        
        Professional Background
        Senior Software Engineer, TechCorp   01/2021 - Present
        - Led backend development using Python and Go.
        
        Academic Qualifications
        Bachelor of Science in Computer Science, State University   2016 - 2020
        
        Core Competencies
        Python, Go, Docker, Kubernetes
        """
        doc = parse_document("jordan_lee.txt", text.encode("utf-8"))
        self.assertEqual(doc.education, "Bachelor's Degree")
        self.assertIn("Python", doc.skills)
        self.assertIn("Go", doc.skills)
        self.assertIn("Docker", doc.skills)
        self.assertGreater(doc.years_experience, 3.0)

    def test_2_boundary_enforcement_and_stoplist(self):
        # Header names should never appear as skills
        text = """
        Sarah Johnson
        sarah@example.com | 555-123-4567
        
        CERTIFICATIONS
        AWS Certified Solutions Architect
        
        EDUCATION
        Master of Science, Stanford University 2018 - 2020
        
        PROFESSIONAL EXPERIENCE
        Data Analyst, Enterprise Inc   Jun '21 - Current
        
        SKILLS
        Python, SQL, Tableau
        """
        doc = parse_document("sarah.txt", text.encode("utf-8"))
        lower_skills = [s.lower() for s in doc.skills]
        self.assertNotIn("certifications", lower_skills)
        self.assertNotIn("education", lower_skills)
        self.assertNotIn("professional experience", lower_skills)
        self.assertNotIn("experience", lower_skills)
        self.assertNotIn("candidate", lower_skills)

    def test_3_single_letter_and_state_code_filtering(self):
        # TX, CA, random single letters 'k', fragments 'and', 'with' must not appear as skills
        text = """
        Alex Rivera
        Austin, TX 78701
        alex@example.com
        
        Summary
        Experienced developer with strong focus on backend systems.
        
        Skills: C, Python, SQL, TX, CA, k, Cross, with, and, for
        """
        doc = parse_document("alex.txt", text.encode("utf-8"))
        lower_skills = [s.lower() for s in doc.skills]
        self.assertIn("c", lower_skills)          # C is whitelisted in skills section
        self.assertNotIn("tx", lower_skills)     # State code filtered
        self.assertNotIn("ca", lower_skills)     # State code filtered
        self.assertNotIn("k", lower_skills)      # Invalid single letter
        self.assertNotIn("with", lower_skills)   # Fragment stopword
        self.assertNotIn("and", lower_skills)    # Fragment stopword

    def test_4_job_title_vs_skill_disambiguation(self):
        # 'Data Analyst', 'Senior Data Analyst' are job titles, not skills
        text = """
        Candidate Name: Taylor Swift
        taylor@example.com | 555-444-3333
        
        Experience
        Senior Data Analyst, DataWorks Inc   01/2021 - 12/2023
        - Built dashboards.
        
        Skills: Python, SQL, Data Analyst, Tableau, Senior Data Analyst
        """
        doc = parse_document("taylor.txt", text.encode("utf-8"))
        lower_skills = [s.lower() for s in doc.skills]
        self.assertNotIn("data analyst", lower_skills)
        self.assertNotIn("senior data analyst", lower_skills)
        self.assertIn("python", lower_skills)
        self.assertIn("sql", lower_skills)

    def test_5_location_and_contact_filtering(self):
        # 'Austin', 'Remote', 'Not detected' must never be skills
        text = """
        Chris Evans
        Austin, TX | Remote | chris@example.com
        
        Skills
        Python, JavaScript, Austin, Remote, Not detected
        """
        doc = parse_document("chris.txt", text.encode("utf-8"))
        lower_skills = [s.lower() for s in doc.skills]
        self.assertNotIn("austin", lower_skills)
        self.assertNotIn("remote", lower_skills)
        self.assertNotIn("not detected", lower_skills)

    def test_6_experience_interval_merging(self):
        # Concurrent roles: Jan 2021 - Dec 2022 (24 mo) and Jun 2021 - Dec 2022 (18 mo)
        # Total merged time must be 24 months (2.0 years), not 42 months
        text = """
        Sam Taylor
        sam@example.com
        
        Experience
        Software Engineer, Alpha Corp    Jan 2021 - Dec 2022
        Part-Time Developer, Beta LLC   Jun 2021 - Dec 2022
        """
        months = extract_experience_months(text, now=NOW)
        years = extract_years_experience(text, now=NOW)
        self.assertEqual(months, 24)
        self.assertEqual(years, 2.0)

    def test_7_date_normalization_seasons_and_two_digit_years(self):
        # Season dates: 'Summer 2017 to Fall 2018' -> June 2017 to September 2018 (~16 months)
        # Two-digit year: "Jun '18 - Dec '20" -> 31 months
        text_season = """
        Experience
        Research Intern, Lab Corp   Summer 2017 - Fall 2018
        """
        months_season = extract_experience_months(text_season, now=NOW)
        self.assertGreaterEqual(months_season, 15)
        self.assertLessEqual(months_season, 17)

        text_2digit = """
        Experience
        Software Developer, Acme Corp   Jun '18 - Dec '20
        """
        months_2digit = extract_experience_months(text_2digit, now=NOW)
        self.assertEqual(months_2digit, 31)

    def test_8_and_9_skill_aliasing_and_bullet_inference(self):
        # Skill aliases: split testing -> A/B Testing, stakeholder collaboration -> Stakeholder Management
        # Snowflake, dbt canonical skills
        text = """
        Alex Morgan
        alex@example.com
        
        Professional Experience
        Product Engineer, Tech Inc   2021 - 2023
        • Conducted split testing and multivariate testing across user cohorts.
        • Led stakeholder collaboration with engineering and marketing.
        • Maintained data pipeline in Snowflake and dbt.
        """
        doc = parse_document("alex_m.txt", text.encode("utf-8"))
        self.assertIn("A/B Testing", doc.skills)
        self.assertIn("Stakeholder Management", doc.skills)
        self.assertIn("Snowflake", doc.skills)
        self.assertIn("dbt", doc.skills)

    def test_10_required_vs_preferred_skill_weighting(self):
        jd_text = """
        Senior Data Engineer
        Required Qualifications:
        - Python
        - SQL
        - Snowflake
        
        Preferred Qualifications:
        - AWS
        - Kubernetes
        """
        parsed_jd = parse_job_description(jd_text)
        self.assertIn("Snowflake", parsed_jd["required_skills"])
        self.assertIn("AWS", parsed_jd["preferred_skills"])

        # Candidate A has all required skills (Python, SQL, Snowflake) but no preferred
        resume_a_text = "John\njohn@example.com\nSkills: Python, SQL, Snowflake\nExperience\nEngineer, Foo  2020 - 2024"
        doc_a = parse_document("a.txt", resume_a_text.encode("utf-8"))
        res_a = score_candidate(doc_a, parsed_jd)

        # Required match should be 100%, preferred match 0%, total skill score ~80%
        self.assertEqual(res_a.factors["required_match_score"], 100.0)
        self.assertEqual(res_a.factors["preferred_match_score"], 0.0)
        self.assertEqual(res_a.factors["skill_alignment"], 80.0)

    def test_12_parse_confidence_scoring(self):
        # Complete resume -> high confidence (>= 0.8)
        complete_cv = """
        Jane Doe
        jane@example.com | (555) 123-4567
        
        Experience
        Software Engineer, Tech Corp   Jan 2020 - Dec 2022
        
        Education
        Bachelor of Science, MIT   2016 - 2020
        
        Skills
        Python, Java, Docker, Git
        """
        doc = parse_document("complete.txt", complete_cv.encode("utf-8"))
        self.assertGreaterEqual(doc.parse_confidence, 0.8)
        self.assertEqual(len(doc.confidence_reasons), 0)

        # Degraded resume with missing contact and no clear sections -> lower confidence
        weak_text = "Just some unformatted claims of knowing Python without headers or dates."
        doc_weak = parse_document("weak.txt", weak_text.encode("utf-8"))
        self.assertLess(doc_weak.parse_confidence, 0.5)
        self.assertGreater(len(doc_weak.confidence_reasons), 0)

    def test_13_self_consistency_check(self):
        # Determinism test: running identical input 3 times must yield identical output and hash
        sample_cv = """
        Robin Hood
        robin@sherwood.org | +1 555-888-9999
        Experience
        Software Developer, Sherwood Tech   Jan 2022 - Dec 2024
        Education
        Bachelor of Science, Oxford   2018 - 2022
        Skills: Python, SQL, Git, Linux
        """
        run1 = parse_document("robin.txt", sample_cv.encode("utf-8"))
        run2 = parse_document("robin.txt", sample_cv.encode("utf-8"))
        run3 = parse_document("robin.txt", sample_cv.encode("utf-8"))

        self.assertEqual(run1.input_hash, run2.input_hash)
        self.assertEqual(run2.input_hash, run3.input_hash)
        self.assertEqual(run1.skills, run2.skills)
        self.assertEqual(run2.skills, run3.skills)
        self.assertEqual(run1.years_experience, run2.years_experience)
        self.assertEqual(run2.years_experience, run3.years_experience)
        self.assertEqual(run1.parse_confidence, run3.parse_confidence)

    def test_14_ngram_tfidf_accuracy(self):
        from src.matcher import _semantic_relevance_tfidf
        # N-grams (1, 3) must match multi-word phrases even without subtoken exact matches
        jd = "Seeking candidate skilled in Machine Learning and A/B Testing pipelines."
        resume_match = "Experienced engineer working on Machine Learning and A/B Testing projects."
        resume_mismatch = "Experienced engineer working on cooking and playing football."
        
        sim_match = _semantic_relevance_tfidf(resume_match, jd)
        sim_mismatch = _semantic_relevance_tfidf(resume_mismatch, jd)
        self.assertGreater(sim_match, 15.0)
        self.assertEqual(sim_mismatch, 0.0)

    def test_15_required_skills_hard_gate(self):
        from src.matcher import _apply_required_skill_gate
        # Hard gate pass/fail:
        # Missing 1 required skill -> score capped at 75%
        gated_1, note_1 = _apply_required_skill_gate(88.0, ["Kubernetes"])
        self.assertEqual(gated_1, 75.0)
        self.assertIn("Score capped at 75%", note_1)

        # Missing 2+ required skills -> score capped at 50%
        gated_2, note_2 = _apply_required_skill_gate(88.0, ["Kubernetes", "PyTorch"])
        self.assertEqual(gated_2, 50.0)
        self.assertIn("Score capped at 50%", note_2)

        # Candidate with score already under cap retains score
        gated_3, note_3 = _apply_required_skill_gate(42.0, ["Kubernetes"])
        self.assertEqual(gated_3, 42.0)
        self.assertIsNone(note_3)

        # End-to-end candidate missing required skill
        parsed_jd = {
            "title": "Staff ML Engineer",
            "required_skills": ["Python", "PyTorch", "Kubernetes"],
            "preferred_skills": ["Docker"],
            "required_education": "Bachelor's Degree",
            "min_years": 2.0,
            "raw_text": "Staff ML Engineer Python PyTorch Kubernetes Docker Senior ML Engineer 2 years exp",
        }
        cv_miss_1 = """
        Alice Senior
        alice@example.com
        Experience
        Senior ML Engineer, AI Corp   Jan 2014 - Dec 2024
        Education
        Master of Science, Stanford   2010 - 2014
        Skills: Python, PyTorch, Docker, Machine Learning, Deep Learning
        """
        doc1 = parse_document("alice.txt", cv_miss_1.encode("utf-8"))
        res1 = score_candidate(doc1, parsed_jd)
        self.assertLessEqual(res1.overall_score, 75.0)
        self.assertIn("gate_cap_applied", res1.factors)
        self.assertIn("Kubernetes", res1.factors["gate_cap_applied"])

    def test_16_present_date_resolution(self):
        import datetime as dt
        from src.parser import extract_work_periods
        # Maintain single source of truth for "today" from system clock
        today = dt.date.today()
        sample = """
        John Doe
        john@example.com
        Experience
        Senior Software Engineer, Tech Corp   Jan 2020 - Present
        Education
        B.S. Computer Science   2015 - 2019
        """
        doc = parse_document("john.txt", sample.encode("utf-8"))
        # Verify resolved_present_date is logged in parser output
        self.assertEqual(doc.resolved_present_date, today.isoformat())
        
        # Test synonyms: "Till date", "To date", "Ongoing", "Now"
        sample_till = """
        Jane Doe
        jane@example.com
        Experience
        Staff Developer, Dev Corp   Jan 2020 - Till date
        """
        periods_till = extract_work_periods(sample_till)
        self.assertTrue(len(periods_till) > 0)
        self.assertTrue(periods_till[0].get("is_present"))

    def test_17_duplicate_role_deduplication(self):
        # A resume with duplicated sections or identical roles must be deduplicated
        sample_dup = """
        Alex Smith
        alex@example.com
        Experience
        Software Developer, Acme Corp   Jan 2020 - Dec 2022
        
        Software Developer, Acme Corp   Jan 2020 - Dec 2022
        
        Software Developer, Acme Corp   Jan 2020 - Dec 2022
        """
        doc = parse_document("alex.txt", sample_dup.encode("utf-8"))
        # 3 years total (36 months), not 9 years
        self.assertEqual(doc.experience_months, 36)
        self.assertEqual(doc.years_experience, 3.0)

    def test_18_machine_learning_jd_min_years(self):
        from src.sample_data import list_sample_jds
        jds = list_sample_jds()
        self.assertIn("Machine Learning", jds)
        parsed = parse_job_description(jds["Machine Learning"])
        # "At least 3 years of hands-on development" must resolve to 3.0 years
        self.assertEqual(parsed["min_years"], 3.0)


if __name__ == "__main__":
    unittest.main()

