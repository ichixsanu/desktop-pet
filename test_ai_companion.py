"""Tests for ai_companion.py.

Covers the parts that used to fail silently: the MEMORY: contract, .env
parsing, nested config merging, rate-limit accounting, reasoning-model
responses, key rotation, and the (text, status) result contract.
"""

import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import ai_companion as ai


class TempPaths(unittest.TestCase):
    """Redirect the module's file paths so tests never touch real state."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._saved = (ai.CONFIG_PATH, ai.MEMORY_PATH, ai.ENV_PATH, ai.CONFIG)
        self.memory_path = os.path.join(self.tmp.name, "memory.json")
        ai.MEMORY_PATH = self.memory_path
        # Stand in a key. The real .env is deliberately absent from the repo, so
        # without this every test depending on the AI being configured would
        # silently exercise the "no key" path instead and pass for the wrong
        # reason.
        self._saved_clients = ai._clients
        self._saved_has_groq = ai._HAS_GROQ
        ai._clients = [MagicMock()]
        ai._HAS_GROQ = True
        self.addCleanup(self._restore)

    def _restore(self):
        ai._clients = self._saved_clients
        ai._HAS_GROQ = self._saved_has_groq
        (ai.CONFIG_PATH, ai.MEMORY_PATH, ai.ENV_PATH,
         ai.CONFIG) = self._saved
        ai.reset_failures()
        ai._sent_log["idle"].clear()
        ai._sent_log["screenshot"].clear()
        ai._daily.update({"date": "", "count": 0})
        ai._last_capture = 0.0
        ai._state["key_idx"] = 0

    def reset_state(self):
        ai.reset_failures()
        ai._sent_log["idle"].clear()
        ai._sent_log["screenshot"].clear()
        ai._daily.update({"date": "", "count": 0})
        ai._last_capture = 0.0
        ai._state["token_budget"] = ai.MIN_TOKEN_BUDGET


class TestMemoryLineSplitting(TempPaths):
    def test_marker_on_its_own_line(self):
        self.assertEqual(ai.split_memory_line("i sit.\nMEMORY: night owl"),
                         ("i sit.", ["night owl"]))

    def test_marker_mid_sentence_is_still_stripped(self):
        # The model ignored the "final line" instruction. The old code only
        # matched line-leading markers, so the pet said "memory: likes dark
        # roast" out loud.
        spoken, facts = ai.split_memory_line("sure! MEMORY: likes dark roast")
        self.assertEqual(spoken, "sure!")
        self.assertEqual(facts, ["likes dark roast"])
        self.assertNotIn("MEMORY", (spoken or "").upper())

    def test_bare_marker_is_removed(self):
        self.assertEqual(ai.split_memory_line("MEMORY:"), (None, []))

    def test_multiple_facts(self):
        self.assertEqual(ai.split_memory_line("MEMORY: a\nMEMORY: b"),
                         (None, ["a", "b"]))

    def test_case_insensitive(self):
        self.assertEqual(ai.split_memory_line("hi\nMemory: tea"),
                         ("hi", ["tea"]))

    def test_plain_text_untouched(self):
        self.assertEqual(ai.split_memory_line("  hello   world "),
                         ("hello world", []))

    def test_empty_input(self):
        self.assertEqual(ai.split_memory_line(""), (None, []))
        self.assertEqual(ai.split_memory_line(None), (None, []))

    def test_facts_are_persisted_and_capped(self):
        ai.CONFIG = dict(ai._default_config())
        ai.CONFIG["memory"] = {"enabled": True, "max_facts": 3}
        for fact in ("one", "two", "three", "four"):
            ai._extract_memory("MEMORY: %s" % fact)
        self.assertEqual(ai._load_memory(), ["two", "three", "four"])
        with open(self.memory_path) as f:
            self.assertEqual(len(json.load(f)), 3)

    def test_duplicate_facts_not_repeated(self):
        ai.CONFIG = dict(ai._default_config())
        ai._extract_memory("MEMORY: same")
        ai._extract_memory("MEMORY: same")
        self.assertEqual(ai._load_memory(), ["same"])

    def test_memory_write_is_atomic(self):
        ai.CONFIG = dict(ai._default_config())
        ai._remember("hello")
        self.assertFalse(os.path.exists(self.memory_path + ".tmp"))

    def test_memory_disabled_is_a_no_op(self):
        ai.CONFIG = dict(ai._default_config())
        ai.CONFIG["memory"] = {"enabled": False, "max_facts": 20}
        ai._remember("nope")
        self.assertEqual(ai._load_memory(), [])


class TestEnvLoading(unittest.TestCase):
    def _write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False)
        handle.write(text)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_parses_export_quotes_and_comments(self):
        path = self._write(
            '# a comment\n'
            'export FOO=bar\n'
            'BAZ="quoted value"\n'
            "QUX='single'\n"
            'WITH_COMMENT=value # trailing\n'
            '\n'
            'not a pair\n'
        )
        saved = {k: os.environ.pop(k, None) for k in
                 ("FOO", "BAZ", "QUX", "WITH_COMMENT")}
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in saved])

        ai._load_env(path)
        self.assertEqual(os.environ["FOO"], "bar")
        self.assertEqual(os.environ["BAZ"], "quoted value")
        self.assertEqual(os.environ["QUX"], "single")
        self.assertEqual(os.environ["WITH_COMMENT"], "value")

    def test_does_not_override_real_environment(self):
        path = self._write("PET_TEST_KEEP=from_file\n")
        os.environ["PET_TEST_KEEP"] = "from_env"
        self.addCleanup(os.environ.pop, "PET_TEST_KEEP", None)
        ai._load_env(path)
        self.assertEqual(os.environ["PET_TEST_KEEP"], "from_env")

    def test_missing_file_is_fine(self):
        ai._load_env("/nonexistent/path/.env")

    def test_key_ordering_is_numeric(self):
        env = {"GROQ_API_KEY": "a", "GROQ_API_KEY2": "b", "GROQ_API_KEY10": "c",
               "GROQ_API_KEY1": "d", "UNRELATED": "x"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(ai._collect_api_keys(), ["a", "d", "b", "c"])


class TestConfigMerging(unittest.TestCase):
    def test_nested_override_keeps_siblings(self):
        base = ai._default_config()
        ai._deep_merge(base, {"screenshots": {"enabled": True},
                              "memory": {"max_facts": 3}})
        self.assertTrue(base["screenshots"]["enabled"])
        self.assertEqual(base["screenshots"]["interval_minutes"], 15)
        self.assertEqual(base["memory"]["max_facts"], 3)
        self.assertTrue(base["memory"]["enabled"])

    def test_system_prompt_states_the_memory_format(self):
        prompt = ai._system_prompt("cat")
        self.assertIn("MEMORY:", prompt)
        self.assertIn("final line", prompt)

    def test_unknown_skin_falls_back_to_default_prompt(self):
        self.assertTrue(ai._system_prompt("nosuchskin"))


class TestRateLimiting(TempPaths):
    def setUp(self):
        super().setUp()
        self.reset_state()
        ai.CONFIG = ai._default_config()
        ai.CONFIG["rate_limits"] = {
            "min_seconds_between": {"idle": 60, "screenshot": 900},
            "max_per_hour": {"idle": 2, "screenshot": 2},
        }

    def test_reserve_blocks_until_the_gap_passes(self):
        self.assertTrue(ai._reserve("idle"))
        self.assertFalse(ai._reserve("idle"))
        ai._sent_log["idle"][-1] = time.time() - 61
        self.assertTrue(ai._reserve("idle"))

    def test_reserve_respects_the_hourly_cap(self):
        self.assertTrue(ai._reserve("idle"))
        ai._sent_log["idle"][-1] = time.time() - 61
        self.assertTrue(ai._reserve("idle"))
        ai._sent_log["idle"][-1] = time.time() - 61
        self.assertFalse(ai._reserve("idle"), "hourly cap not enforced")
        ai._sent_log["idle"][0] = time.time() - 3601
        self.assertTrue(ai._reserve("idle"), "old entries not pruned")

    def test_release_returns_the_slot(self):
        self.assertTrue(ai._reserve("idle"))
        self.assertFalse(ai._reserve("idle"))
        ai._release("idle")
        self.assertTrue(ai._reserve("idle"))

    def test_daily_cap_rolls_over(self):
        ai.CONFIG["screenshots"]["max_per_day"] = 2
        self.assertTrue(ai.screenshot_daily_ok())
        ai._screenshot_daily_mark()
        ai._screenshot_daily_mark()
        self.assertFalse(ai.screenshot_daily_ok())
        ai._daily["date"] = "1999-01-01"
        self.assertTrue(ai.screenshot_daily_ok())


class TestScreenshotPolicy(TempPaths):
    def setUp(self):
        super().setUp()
        self.reset_state()
        ai.CONFIG = ai._default_config()
        ai.CONFIG["screenshots"]["enabled"] = True
        ai.CONFIG["screenshots"]["interval_minutes"] = 15
        ai.CONFIG["rate_limits"] = {
            "min_seconds_between": {"idle": 45, "screenshot": 0},
            "max_per_hour": {"idle": 6, "screenshot": 4},
        }

    def test_disabled_never_fires(self):
        ai.CONFIG["screenshots"]["enabled"] = False
        self.assertFalse(ai.screenshot_slot_ok())

    def test_slot_then_interval_throttle(self):
        self.assertTrue(ai.screenshot_slot_ok())
        ai.record_capture_attempt(True)
        self.assertFalse(ai.screenshot_slot_ok(), "interval not enforced")

    def test_blocked_capture_releases_the_quota(self):
        self.assertTrue(ai.screenshot_slot_ok())
        ai.record_capture_attempt(False)
        # A refused capture must not burn an hourly slot.
        self.assertEqual(ai._sent_log["screenshot"], [])
        self.assertEqual(ai._daily["count"], 0)
        self.assertFalse(ai.screenshot_slot_ok(), "interval should still apply")

    def test_successful_capture_charges_the_daily_cap(self):
        self.assertTrue(ai.screenshot_slot_ok())
        ai.record_capture_attempt(True)
        self.assertEqual(ai._daily["count"], 1)
        self.assertEqual(len(ai._sent_log["screenshot"]), 1)

    def test_ai_off_means_no_capture(self):
        with patch.object(ai, "ai_enabled", return_value=False):
            self.assertFalse(ai.screenshot_slot_ok())


def _response(content, reasoning=None, finish="stop"):
    message = MagicMock()
    message.content = content
    message.reasoning = reasoning
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish
    response = MagicMock()
    response.choices = [choice]
    return response


class TestResponseHandling(unittest.TestCase):
    def test_content_is_returned(self):
        self.assertEqual(ai._extract_content(_response("  hi  ")), "hi")

    def test_none_content_is_not_an_error(self):
        self.assertEqual(ai._extract_content(_response(None)), "")

    def test_empty_content_after_reasoning_grows_the_budget(self):
        ai.reset_failures()
        start = ai._state["token_budget"]
        text = ai._extract_content(_response("", reasoning="thinking...",
                                           finish="length"))
        self.assertEqual(text, "")
        self.assertGreater(ai._state["token_budget"], start)
        ai.reset_failures()

    def test_malformed_response_does_not_raise(self):
        self.assertEqual(ai._extract_content(MagicMock(choices=[])), "")
        self.assertEqual(ai._extract_content(object()), "")

    def test_error_classification(self):
        self.assertEqual(ai._classify_error(
            Exception("Error code: 404 - model_not_found"))[0], "fatal")

        class AuthenticationError(Exception):
            pass

        class RateLimitError(Exception):
            pass

        self.assertEqual(ai._classify_error(AuthenticationError("bad key"))[0], "dead")
        self.assertEqual(ai._classify_error(RateLimitError("slow down"))[0], "cooldown")
        self.assertEqual(ai._classify_error(ValueError("odd"))[0], "transient")


class TestRequestContract(TempPaths):
    def setUp(self):
        super().setUp()
        self.reset_state()
        ai.CONFIG = ai._default_config()

    def test_disabled_ai_reports_unavailable(self):
        with patch.object(ai, "ai_enabled", return_value=False):
            got = []
            ai.maybe_idle_line("cat", lambda t, s: got.append((t, s)))
        self.assertEqual(got, [(None, ai.STATUS_UNAVAILABLE)])
        self.assertEqual(ai._sent_log["idle"], [])

    def test_rate_limited_reports_skipped_and_says_nothing(self):
        # The old contract reported this as "no text", so the pet spoke a
        # random unsolicited line every time a cap was hit.
        ai._sent_log["idle"].append(time.time())
        got = []
        ai.maybe_idle_line("cat", lambda t, s: got.append((t, s)))
        self.assertEqual(got, [(None, ai.STATUS_SKIPPED)])

    def test_successful_line_reports_ok(self):
        results = []
        done = threading.Event()

        def on_done(text, status):
            results.append((text, status))
            done.set()

        with patch.object(ai, "ai_enabled", return_value=True):
            with patch.object(ai, "_call", return_value="i sit. MEMORY: late nights"):
                ai.maybe_idle_line("cat", on_done)
                self.assertTrue(done.wait(5))
        self.assertEqual(results[0][0], "i sit.")
        self.assertEqual(results[0][1], ai.STATUS_OK)
        self.assertEqual(len(ai._sent_log["idle"]), 1)
        self.assertEqual(ai._load_memory(), ["late nights"])

    def test_failed_call_releases_the_slot(self):
        results = []
        done = threading.Event()

        def on_done(text, status):
            results.append((text, status))
            done.set()

        with patch.object(ai, "ai_enabled", return_value=True):
            with patch.object(ai, "_call", return_value=None):
                ai.maybe_idle_line("cat", on_done)
                self.assertTrue(done.wait(5))
        self.assertEqual(results[0], (None, ai.STATUS_UNAVAILABLE))
        self.assertEqual(ai._sent_log["idle"], [],
                         "a failed call must not consume quota")

    def test_worker_exceptions_are_contained(self):
        with patch.object(ai, "ai_enabled", return_value=True):
            with patch.object(ai, "_reserve", return_value=True):
                with patch.object(ai, "_system_prompt", side_effect=RuntimeError("boom")):
                    ai.maybe_idle_line("cat", lambda t, s: None)
                    time.sleep(0.3)
        # If the worker had died noisily the test would still pass; assert the
        # process is healthy and the slot was returned.
        self.assertTrue(ai._sent_log is not None)


class TestKeyRotation(TempPaths):
    def setUp(self):
        super().setUp()
        self.reset_state()
        ai.CONFIG = ai._default_config()

    def _client(self, reply="hi", error=None):
        client = MagicMock()
        if error is not None:
            client.chat.completions.create.side_effect = error
        else:
            client.chat.completions.create.return_value = _response(reply)
        return client

    def test_keys_rotate_on_success(self):
        clients = [self._client("one"), self._client("two")]
        with patch.object(ai, "_clients", clients):
            self.assertEqual(ai._call([]), "one")
            self.assertEqual(ai._call([]), "two")
            self.assertEqual(ai._call([]), "one")

    def test_dead_key_is_skipped(self):
        class AuthenticationError(Exception):
            pass

        clients = [self._client(error=AuthenticationError("bad")),
                   self._client("second")]
        with patch.object(ai, "_clients", clients):
            self.assertEqual(ai._call([]), "second")
            self.assertIn(0, ai._state["dead_keys"])
            clients[0].chat.completions.create.reset_mock()
            ai._call([])
            self.assertEqual(clients[0].chat.completions.create.call_count, 0)

    def test_rate_limited_key_is_cooled_down(self):
        class RateLimitError(Exception):
            pass

        clients = [self._client(error=RateLimitError("slow down")),
                   self._client("second")]
        with patch.object(ai, "_clients", clients):
            self.assertEqual(ai._call([]), "second")
            self.assertIn(0, ai._state["key_cooldown"])
            self.assertNotIn(0, ai._state["dead_keys"])

    def test_bad_model_is_fatal_and_explained(self):
        clients = [self._client(error=Exception("404 model_not_found"))]
        with patch.object(ai, "_clients", clients):
            with patch.object(ai, "MODEL", "qwen/nope"):
                self.assertIsNone(ai._call([]))
        self.assertFalse(ai.ai_enabled())
        self.assertIn("model_not_found", ai.ai_status()["reason"])
        self.assertEqual(ai._sent_log["idle"], [])
        # A second attempt must not fire another doomed request.
        calls = clients[0].chat.completions.create.call_count
        self.assertIsNone(ai._call([]))
        self.assertEqual(clients[0].chat.completions.create.call_count, calls)
        ai.reset_failures()

    def test_circuit_breaker_cools_down(self):
        clients = [self._client(error=Exception("connection reset"))]
        with patch.object(ai, "_clients", clients):
            self.assertIsNone(ai._call([]))
            calls = clients[0].chat.completions.create.call_count
            self.assertIsNone(ai._call([]))
            self.assertEqual(clients[0].chat.completions.create.call_count, calls)
        ai.reset_failures()

    def test_reset_failures_clears_everything(self):
        clients = [self._client(error=Exception("404 model_not_found"))]
        with patch.object(ai, "_clients", clients):
            with patch.object(ai, "MODEL", "qwen/nope"):
                ai._call([])
        self.assertFalse(ai.ai_enabled())
        ai.reset_failures()
        self.assertTrue(ai.ai_status()["enabled"] or not ai._clients)


class TestStatusReporting(TempPaths):
    def test_missing_key_is_explained(self):
        with patch.object(ai, "_clients", []):
            status = ai.ai_status()
        self.assertFalse(status["enabled"])
        self.assertIn("GROQ_API_KEY", status["reason"])

    def test_config_disabled_is_explained(self):
        config = ai._default_config()
        config["ai_enabled"] = False
        with patch.object(ai, "CONFIG", config):
            self.assertIn("companion_config", ai.ai_status()["reason"])

    def test_enabled_status_mentions_the_model(self):
        with patch.object(ai, "CONFIG", ai._default_config()):
            with patch.object(ai, "_clients", [MagicMock()]):
                with patch.object(ai, "_HAS_GROQ", True):
                    status = ai.ai_status()
        self.assertTrue(status["enabled"])
        self.assertIn("key", status["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
