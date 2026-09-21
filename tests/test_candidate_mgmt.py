import unittest
from unittest.mock import MagicMock, patch
from src.matcher import MatchResult
from src import db


class CandidateManagementTests(unittest.TestCase):
    def test_raw_text_persistence_in_factors(self):
        # Verify that MatchResult holds raw_text
        mr = MatchResult(
            candidate_name="Test Candidate",
            overall_score=85.0,
            factors={"semantic_relevance": 90.0},
            matched_skills=["Python", "SQL"],
            missing_skills=[],
            extra_skills=["Docker"],
            status="Strong Match",
            rationale="Great fit",
            raw_text="This is the full extracted resume content for testing.",
        )
        self.assertEqual(mr.raw_text, "This is the full extracted resume content for testing.")

    def test_fetch_results_extracts_raw_text_from_factors(self):
        fake_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [
            {
                "id": "1",
                "req_id": "test_user__req_1",
                "candidate_name": "Jane Doe",
                "filename": "jane_doe.pdf",
                "email": "jane@example.com",
                "phone": "555-1234",
                "education": "Bachelor's Degree",
                "years_experience": 4.0,
                "overall_score": 88.0,
                "status": "Strong Match",
                "rationale": "High score",
                "factors": {"raw_text": "Jane Doe experience at Acme Corp"},
                "matched_skills": ["Python"],
                "missing_skills": [],
                "extra_skills": [],
                "fairness_audit": {},
                "semantic_engine": "tfidf",
            }
        ]
        fake_client.table().select().eq().order().execute.return_value = mock_response

        with patch("src.db.get_client", return_value=fake_client):
            results = db.fetch_results("req_1", user_id="test_user")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].candidate_name, "Jane Doe")
            self.assertEqual(results[0].raw_text, "Jane Doe experience at Acme Corp")

    def test_delete_candidates_calls(self):
        fake_client = MagicMock()
        with patch("src.db.get_client", return_value=fake_client):
            success = db.delete_candidates_for_requisition("req_1", user_id="test_user")
            self.assertTrue(success)
            self.assertTrue(fake_client.table.called)

            success_single = db.delete_candidate("req_1", "Jane Doe", user_id="test_user")
            self.assertTrue(success_single)
            self.assertTrue(fake_client.table.called)


if __name__ == "__main__":
    unittest.main()
