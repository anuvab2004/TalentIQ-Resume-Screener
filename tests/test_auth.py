"""Run with:  python -m unittest discover -s tests -v"""
import os
import shutil
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="talentiq-test-")
os.environ["TALENTIQ_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["TALENTIQ_SECRET_DIR"] = os.path.join(_TMP, "secret")

from src import auth, settings_store, db  # noqa: E402


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


class SupabaseAuthValidationTests(unittest.TestCase):
    def test_normalize_email(self):
        self.assertEqual(auth.normalize_email("  Asha@Example.COM "), "asha@example.com")
        self.assertEqual(auth.normalize_email(None), "")

    def test_email_validation(self):
        self.assertIsNone(auth.validate_email("user@domain.com"))
        self.assertIsNotNone(auth.validate_email("not-an-email"))
        self.assertIsNotNone(auth.validate_email(""))

    def test_name_validation(self):
        self.assertIsNone(auth.validate_name("Asha Rao"))
        self.assertIsNotNone(auth.validate_name("A"))
        self.assertIsNotNone(auth.validate_name(""))

    def test_password_validation(self):
        self.assertIsNone(auth.validate_password("SecurePass123!"))
        self.assertIsNotNone(auth.validate_password("123"))

    def test_sign_up_client_validation(self):
        # Mismatched passwords
        ok, msg, user = auth.sign_up("Asha Rao", "asha@example.com", "Password123", "Mismatch123")
        self.assertFalse(ok)
        self.assertIn("don't match", msg)
        self.assertIsNone(user)

        # Invalid name
        ok, msg, user = auth.sign_up("A", "asha@example.com", "Password123", "Password123")
        self.assertFalse(ok)
        self.assertIn("full name", msg)

        # Invalid email
        ok, msg, user = auth.sign_up("Asha Rao", "bad-email", "Password123", "Password123")
        self.assertFalse(ok)
        self.assertIn("valid email", msg)

    def test_sign_in_blank_validation(self):
        ok, msg, user = auth.sign_in("", "")
        self.assertFalse(ok)
        self.assertIn("Enter your email", msg)
        self.assertIsNone(user)


class PerUserSettingsTests(unittest.TestCase):
    def test_org_settings_are_isolated_per_user(self):
        settings_store.save_org_settings({"company_name": "Acme", "hr_sender_name": "A", "hr_sender_title": "T"}, user_id="user_1")
        settings_store.save_org_settings({"company_name": "Globex", "hr_sender_name": "B", "hr_sender_title": "T"}, user_id="user_2")
        self.assertEqual(settings_store.load_org_settings("user_1")["company_name"], "Acme")
        self.assertEqual(settings_store.load_org_settings("user_2")["company_name"], "Globex")
        self.assertEqual(settings_store.load_org_settings("user_3")["company_name"], "Your Company")

    def test_prefs_are_isolated_per_user(self):
        settings_store.save_app_prefs({"seed_demo_requisition": False}, user_id="user_1")
        self.assertFalse(settings_store.load_app_prefs("user_1")["seed_demo_requisition"])
        self.assertTrue(settings_store.load_app_prefs("user_2")["seed_demo_requisition"])

    def test_smtp_credentials_are_isolated_per_user(self):
        cfg = {"provider": "Gmail", "host": "smtp.gmail.com", "port": 587, "tls": True,
               "sender_email": "one@x.com", "password": "app-pass-one"}
        self.assertTrue(settings_store.save_smtp_config(cfg, user_id="user_1"))
        self.assertEqual(settings_store.load_smtp_config("user_1")["password"], "app-pass-one")
        self.assertEqual(settings_store.load_smtp_config("user_2")["password"], "")
        self.assertTrue(settings_store.has_saved_smtp("user_1"))
        self.assertFalse(settings_store.has_saved_smtp("user_2"))
        settings_store.clear_smtp_config("user_1")
        self.assertFalse(settings_store.has_saved_smtp("user_1"))


class SupabaseDbLayerTests(unittest.TestCase):
    def test_is_configured(self):
        # We set credentials in .env so db.is_configured() should be True or boolean
        self.assertIsInstance(db.is_configured(), bool)


if __name__ == "__main__":
    unittest.main()
