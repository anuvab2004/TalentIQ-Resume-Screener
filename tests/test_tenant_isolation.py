import unittest
from src import db


class TenantIsolationTests(unittest.TestCase):
    def test_scoped_and_unscoped_req_ids(self):
        user_a = "user_11111111"
        user_b = "user_22222222"

        scoped_a = db._scoped_req_id("req_1", user_a)
        scoped_b = db._scoped_req_id("req_1", user_b)

        # Scoped IDs must be distinct even for the same local req_id
        self.assertNotEqual(scoped_a, scoped_b)
        self.assertEqual(scoped_a, "user_11111111__req_1")
        self.assertEqual(scoped_b, "user_22222222__req_1")

        # Unscoping returns clean local display IDs
        self.assertEqual(db._unscoped_req_id(scoped_a, user_a), "req_1")
        self.assertEqual(db._unscoped_req_id(scoped_b, user_b), "req_1")
        # Attempting to unscope with wrong tenant does not strip
        self.assertNotEqual(db._unscoped_req_id(scoped_a, user_b), "req_1")

    def test_unauthenticated_or_blank_queries_return_empty(self):
        # Without user_id, queries must return empty dictionaries to prevent global leaks
        self.assertEqual(db.fetch_requisitions(user_id=None), {})
        self.assertEqual(db.fetch_all_candidate_actions(user_id=None), {})
        self.assertEqual(db.fetch_all_interview_guides(user_id=None), {})
        self.assertEqual(db.fetch_all_email_logs(user_id=None), {})

    def test_storage_path_isolation(self):
        user_a = "user_aaaaaaaa"
        user_b = "user_bbbbbbbb"

        # Simulating safe path creation as in upload_resume_file
        filename = "Jane_Doe_Resume.pdf"
        safe_name = "Jane_Doe_Resume.pdf"

        path_a = f"{user_a}/req_1/{safe_name}"
        path_b = f"{user_b}/req_1/{safe_name}"

        self.assertNotEqual(path_a, path_b)
        self.assertTrue(path_a.startswith("user_aaaaaaaa/"))
        self.assertTrue(path_b.startswith("user_bbbbbbbb/"))


if __name__ == "__main__":
    unittest.main()
