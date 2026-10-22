"""Tests for ocr_guard.py.

Two properties matter more than the rules themselves:

1. A match must never write the matched text anywhere. The whole point of the
   filter is that the secret does not leave the machine, and "we logged it
   instead" is the same failure with extra steps.
2. Failing to run must, by default, refuse the capture rather than wave it
   through: an unreadable scan is not a clean scan.
"""

import os
import shutil
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

import ocr_guard as og  # noqa: E402

_app = None
_HAS_TESSERACT = shutil.which("tesseract") is not None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication([])


def render(lines, width=900, height=None, size=16):
    """A fake screen: white background, black text, like a real UI."""
    height = height or (40 * len(lines) + 40)
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    painter.setPen(QColor(20, 20, 20))
    painter.setFont(QFont("DejaVu Sans Mono", size))
    for index, line in enumerate(lines):
        painter.drawText(20, 40 + index * 40, line)
    painter.end()
    return image


class TestScanText(unittest.TestCase):
    def test_plain_text_passes(self):
        verdict = og.scan_text("def main():\n    return 0\nhello there\n")
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.reason, "")

    def test_password_context_is_caught(self):
        verdict = og.scan_text("Password: hunter2")
        self.assertFalse(verdict.ok)
        self.assertIn("password field", verdict.hits)

    def test_the_bare_word_password_is_not_enough(self):
        # Documentation, code and config templates say "password" constantly.
        # Blocking those would cost the user every capture they wanted.
        self.assertTrue(og.scan_text("set the password field to a value").ok)
        self.assertTrue(og.scan_text("password = os.environ['PASSWORD']").ok)

    def test_recovery_phrases_are_caught(self):
        verdict = og.scan_text("write down your seed phrase: apple banana cherry")
        self.assertFalse(verdict.ok)
        self.assertIn("keyword: seed phrase", verdict.hits)

    def test_api_key_formats_are_caught(self):
        samples = {
            "GROQ_API_KEY=gsk_" + "a" * 24: "Groq key",
            "token sk-" + "b" * 24: "OpenAI-style key",
            "aws AKIAIOSFODNN7EXAMPLE": "AWS access key id",
            "bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0.abcdef": "JSON Web Token",
            "ghp_" + "c" * 24: "GitHub token",
        }
        for text, rule in samples.items():
            with self.subTest(text=text):
                verdict = og.scan_text(text)
                self.assertFalse(verdict.ok)
                self.assertIn(rule, verdict.hits)

    def test_private_key_block_is_caught(self):
        verdict = og.scan_text("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n")
        self.assertFalse(verdict.ok)
        self.assertIn("private key block", verdict.hits)

    def test_card_numbers_need_a_valid_checksum(self):
        self.assertFalse(og.scan_text("card 4111 1111 1111 1111").ok)
        # Same shape, bad checksum: a build id or an order number.
        self.assertTrue(og.scan_text("card 4111 1111 1111 1112").ok)

    def test_iban_needs_a_valid_checksum(self):
        self.assertFalse(og.scan_text("acct DE89370400440532013000").ok)
        self.assertTrue(og.scan_text("acct DE00370400440532013000").ok)

    def test_social_security_number_is_caught(self):
        self.assertFalse(og.scan_text("ssn 123-45-6789").ok)

    def test_nothing_sensitive_is_ever_returned(self):
        secret = "hunter2-correct-horse-battery-staple"
        verdict = og.scan_text("master password: %s" % secret)
        self.assertFalse(verdict.ok)
        blob = repr(verdict) + repr(verdict.hits) + verdict.reason
        self.assertNotIn(secret, blob)
        self.assertNotIn("hunter2", blob)

    def test_allowed_keywords_exempt_a_line(self):
        cfg = {"allowed_keywords": ["docs/security.md"]}
        text = "docs/security.md: password: example"
        self.assertTrue(og.scan_text(text, cfg).ok)
        # ...but not from the value rules: a real key is still a real key.
        self.assertFalse(og.scan_text(
            "docs/security.md: AKIAIOSFODNN7EXAMPLE", cfg).ok)

    def test_extra_keywords_are_honoured(self):
        cfg = {"extra_keywords": ["project codename"]}
        self.assertFalse(og.scan_text("the project codename is bluebird", cfg).ok)
        self.assertTrue(og.scan_text("the project is bluebird", cfg).ok)

    def test_custom_rule_lists_replace_the_defaults(self):
        cfg = {"keywords": [], "context_keywords": [],
               "patterns": [["internal host", r"db-prod-\d+"]]}
        self.assertTrue(og.scan_text("Password: hunter2", cfg).ok)
        verdict = og.scan_text("connect to db-prod-07", cfg)
        self.assertFalse(verdict.ok)
        self.assertIn("internal host", verdict.hits)

    def test_code_that_names_a_secret_is_not_a_secret(self):
        # These are how settings files and source code look. Flagging them
        # would throw away most developer screenshots.
        for text in ("password = os.environ['PASSWORD']",
                     "token = getenv(\"TOKEN\")",
                     "db_password: ${DB_PASSWORD}",
                     "secret: null"):
            with self.subTest(text=text):
                self.assertTrue(og.scan_text(text).ok)

    def test_bad_custom_regex_is_ignored_not_fatal(self):
        cfg = {"patterns": [["broken", "("], ["ok", "secret-token"]]}
        self.assertFalse(og.scan_text("my secret-token here", cfg).ok)


class TestConfig(unittest.TestCase):
    def test_defaults_merge(self):
        cfg = og.normalize_config({"timeout_seconds": 3})
        self.assertEqual(cfg["timeout_seconds"], 3)
        self.assertTrue(cfg["fail_closed"])
        self.assertTrue(cfg["keywords"])

    def test_garbage_values_are_clamped(self):
        cfg = og.normalize_config({"timeout_seconds": "soon", "max_width": -5,
                                   "psm": object()})
        self.assertEqual(cfg["timeout_seconds"], 6.0)
        self.assertEqual(cfg["max_width"], 1600)
        self.assertEqual(cfg["psm"], 3)

    def test_describe_mentions_the_engine_and_the_mode(self):
        text = og.describe({"enabled": True, "fail_closed": False})
        self.assertIn("fail open", text)
        self.assertIn("rules", text)
        self.assertEqual(og.describe({"enabled": False}), "off")


class TestFailClosed(unittest.TestCase):
    def setUp(self):
        import io

        og._no_engine_warned = False
        self.err = io.StringIO()
        patcher = patch.object(og.sys, "stderr", self.err)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_engine_refuses_by_default(self):
        with patch.object(og, "find_engine", return_value=None):
            verdict = og.scan_image(render(["hello"]))
        self.assertFalse(verdict.ok)
        self.assertIn("no OCR engine", verdict.reason)

    def test_the_missing_engine_is_announced_once(self):
        with patch.object(og, "find_engine", return_value=None):
            og.scan_image(render(["hello"]))
            og.scan_image(render(["hello"]), {"fail_closed": False})
        text = self.err.getvalue()
        self.assertIn("[ocr_guard]", text)
        self.assertIn("tesseract", text)
        self.assertEqual(text.count("[ocr_guard]"), 1, msg=text)

    def test_a_working_engine_is_not_announced(self):
        og.scan_image(render(["hello"]))
        self.assertEqual(self.err.getvalue(), "")

    def test_no_engine_can_be_told_to_wave_things_through(self):
        with patch.object(og, "find_engine", return_value=None):
            verdict = og.scan_image(render(["hello"]), {"fail_closed": False})
        self.assertTrue(verdict.ok)

    def test_unreadable_image_refuses(self):
        with patch.object(og, "run_engine", return_value=None):
            verdict = og.scan_image(render(["hello"]),
                                    {"engine": "tesseract"})
        self.assertFalse(verdict.ok)
        self.assertIn("could not read", verdict.reason)

    def test_disabled_filter_allows_everything(self):
        with patch.object(og, "find_engine", return_value=None):
            verdict = og.scan_image(render(["password: x"]), {"enabled": False})
        self.assertTrue(verdict.ok)


@unittest.skipUnless(_HAS_TESSERACT, "tesseract is not installed")
class TestScanImageWithTesseract(unittest.TestCase):
    def setUp(self):
        og.reset_engine_cache()

    def tearDown(self):
        og.reset_engine_cache()

    def test_engine_is_found(self):
        self.assertIsNotNone(og.find_engine())
        self.assertIn("tesseract", og.engine_status()["name"].lower())

    def test_clean_screen_passes(self):
        image = render(["def main():", "    return 0", "buy milk and bread"])
        self.assertTrue(og.scan_image(image).ok)

    def test_password_on_screen_is_refused(self):
        image = render(["Settings", "Password: hunter2", "Cancel   OK"])
        verdict = og.scan_image(image)
        self.assertFalse(verdict.ok)
        self.assertTrue(verdict.hits)

    def test_a_real_looking_key_is_refused(self):
        image = render(["$ cat .env",
                        "GROQ_API_KEY=gsk_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890"])
        self.assertFalse(og.scan_image(image).ok)

    def test_scan_is_bounded(self):
        # A 4K capture must be downscaled before OCR, not after.
        image = render(["hello world"], width=3840, height=2160, size=48)
        self.assertTrue(og.scan_image(image, {"max_width": 800}).ok)


if __name__ == "__main__":
    unittest.main()
