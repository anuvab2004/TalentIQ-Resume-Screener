"""Run with:  python -m unittest discover -s tests -v"""
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

_TMP = tempfile.mkdtemp(prefix="talentiq-test-")
os.environ["TALENTIQ_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["TALENTIQ_SECRET_DIR"] = os.path.join(_TMP, "secret")

from src import auth, settings_store  # noqa: E402  (env vars must be set first)

GOOD_PW = "Sunrise42ok"


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


class AuthTests(unittest.TestCase):
    def setUp(self):
        try:
            os.remove(auth.db_path())
        except FileNotFoundError:
            pass
        except PermissionError:  # Windows: file briefly locked -> just empty the table instead
            con = sqlite3.connect(str(auth.db_path()))
            try:
                con.execute("DELETE FROM users")
                con.commit()
            finally:
                con.close()

    def make(self, email="asha@example.com", name="Asha Rao", pw=GOOD_PW):
        ok, msg, user = auth.sign_up(name, email, pw, pw)
        self.assertTrue(ok, msg)
        return user

    # ---- sign up -------------------------------------------------------
    def test_sign_up_then_sign_in(self):
        user = self.make()
        ok, _, signed = auth.sign_in("asha@example.com", GOOD_PW)
        self.assertTrue(ok)
        self.assertEqual(signed, user)
        self.assertEqual(signed["name"], "Asha Rao")

    def test_email_is_case_and_whitespace_insensitive(self):
        self.make(email="Asha@Example.com")
        ok, _, _ = auth.sign_in("  ASHA@example.COM ", GOOD_PW)
        self.assertTrue(ok)
        ok, msg, _ = auth.sign_up("Other", "asha@EXAMPLE.com", GOOD_PW, GOOD_PW)
        self.assertFalse(ok)
        self.assertIn("already exists", msg)

    def test_password_is_not_stored_in_plain_text(self):
        self.make()
        con = sqlite3.connect(str(auth.db_path()))
        try:
            raw = con.execute("SELECT pw_hash FROM users").fetchone()[0]
        finally:
            con.close()  # Windows can't delete a database file that is still open
        self.assertNotIn(GOOD_PW, raw)
        self.assertTrue(raw.startswith("scrypt$"))

    def test_same_password_gets_different_hashes(self):
        self.assertNotEqual(auth.hash_password(GOOD_PW), auth.hash_password(GOOD_PW))

    def test_sign_up_validation(self):
        cases = [
            (("A", "a@b.co", GOOD_PW, GOOD_PW), "full name"),
            (("Asha", "not-an-email", GOOD_PW, GOOD_PW), "valid email"),
            (("Asha", "a@b.co", "short1", "short1"), "at least 8"),
            (("Asha", "a@b.co", "onlyletters", "onlyletters"), "letter and one number"),
            (("Asha", "a@b.co", "password123", "password123"), "easy to guess"),
            (("Asha", "a@b.co", GOOD_PW, GOOD_PW + "x"), "don't match"),
        ]
        for args, fragment in cases:
            ok, msg, user = auth.sign_up(*args)
            self.assertFalse(ok, args)
            self.assertIn(fragment, msg)
            self.assertIsNone(user)

    # ---- sign in -------------------------------------------------------
    def test_wrong_password_and_unknown_email_share_one_message(self):
        self.make()
        _, m1, _ = auth.sign_in("asha@example.com", "WrongPass1")
        _, m2, _ = auth.sign_in("nobody@example.com", "WrongPass1")
        self.assertEqual(m1, m2)

    def test_blank_fields(self):
        ok, msg, _ = auth.sign_in("", "")
        self.assertFalse(ok)

    def test_lockout_after_repeated_failures(self):
        self.make()
        for _ in range(auth.MAX_FAILED_ATTEMPTS):
            ok, _, _ = auth.sign_in("asha@example.com", "WrongPass1")
            self.assertFalse(ok)
        ok, msg, _ = auth.sign_in("asha@example.com", GOOD_PW)  # right password, still locked
        self.assertFalse(ok)
        self.assertIn("Too many", msg)

    def test_lockout_expires(self):
        self.make()
        for _ in range(auth.MAX_FAILED_ATTEMPTS):
            auth.sign_in("asha@example.com", "WrongPass1")
        con = sqlite3.connect(str(auth.db_path()))
        con.execute("UPDATE users SET locked_until = ?", (time.time() - 1,))
        con.commit()
        con.close()
        ok, _, _ = auth.sign_in("asha@example.com", GOOD_PW)
        self.assertTrue(ok)

    def test_success_resets_failure_counter(self):
        self.make()
        for _ in range(auth.MAX_FAILED_ATTEMPTS - 1):
            auth.sign_in("asha@example.com", "WrongPass1")
        self.assertTrue(auth.sign_in("asha@example.com", GOOD_PW)[0])
        for _ in range(auth.MAX_FAILED_ATTEMPTS - 1):
            auth.sign_in("asha@example.com", "WrongPass1")
        self.assertTrue(auth.sign_in("asha@example.com", GOOD_PW)[0])

    # ---- change password ----------------------------------------------
    def test_change_password(self):
        user = self.make()
        self.assertFalse(auth.change_password(user["id"], "nope", "NewPass123", "NewPass123")[0])
        self.assertFalse(auth.change_password(user["id"], GOOD_PW, "NewPass123", "Mismatch123")[0])
        self.assertFalse(auth.change_password(user["id"], GOOD_PW, GOOD_PW, GOOD_PW)[0])
        self.assertTrue(auth.change_password(user["id"], GOOD_PW, "NewPass123", "NewPass123")[0])
        self.assertFalse(auth.sign_in("asha@example.com", GOOD_PW)[0])
        self.assertTrue(auth.sign_in("asha@example.com", "NewPass123")[0])

    def test_verify_password_never_raises_on_garbage(self):
        for junk in ("", "abc", "scrypt$x$y", "md5$1$2$3$4$5", None):
            self.assertFalse(auth.verify_password("x", junk))


class PerUserSettingsTests(unittest.TestCase):
    def test_org_settings_are_isolated_per_user(self):
        settings_store.save_org_settings({"company_name": "Acme", "hr_sender_name": "A", "hr_sender_title": "T"}, user_id=1)
        settings_store.save_org_settings({"company_name": "Globex", "hr_sender_name": "B", "hr_sender_title": "T"}, user_id=2)
        self.assertEqual(settings_store.load_org_settings(1)["company_name"], "Acme")
        self.assertEqual(settings_store.load_org_settings(2)["company_name"], "Globex")
        self.assertEqual(settings_store.load_org_settings(3)["company_name"], "Your Company")

    def test_prefs_are_isolated_per_user(self):
        settings_store.save_app_prefs({"seed_demo_requisition": False}, user_id=1)
        self.assertFalse(settings_store.load_app_prefs(1)["seed_demo_requisition"])
        self.assertTrue(settings_store.load_app_prefs(2)["seed_demo_requisition"])

    def test_smtp_credentials_are_isolated_per_user(self):
        cfg = {"provider": "Gmail", "host": "smtp.gmail.com", "port": 587, "tls": True,
               "sender_email": "one@x.com", "password": "app-pass-one"}
        self.assertTrue(settings_store.save_smtp_config(cfg, user_id=1))
        self.assertEqual(settings_store.load_smtp_config(1)["password"], "app-pass-one")
        self.assertEqual(settings_store.load_smtp_config(2)["password"], "")
        self.assertTrue(settings_store.has_saved_smtp(1))
        self.assertFalse(settings_store.has_saved_smtp(2))
        settings_store.clear_smtp_config(1)
        self.assertFalse(settings_store.has_saved_smtp(1))


if __name__ == "__main__":
    unittest.main()
