import hashlib
import importlib
import importlib.util
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from email.utils import format_datetime
from pathlib import Path

from support import (SPAWN_ALLOWANCE_SECONDS, SPAWN_WAIT_SECONDS, DownloadHarness, body_receipt, download_harness,
                     fixture_context, fixture_settings, fixture_source, spawn_tolerant_settings, store_bundle,
                     zip_bytes)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("sec_edgar_ingest.download"),
                             "Task 5 requires a bounded sender and durable transport retry client")
        self.download = importlib.import_module("sec_edgar_ingest.download")

    def harness(self, responses, **options):
        harness = DownloadHarness(responses, **options)
        self.addCleanup(harness.close)
        return harness

    def test_archive_original_is_not_replaced_by_decoded_idx(self):
        original = zip_bytes((Path(__file__).parent / "fixtures/raw/quarterly.idx").read_bytes())
        h = self.harness([(200, original, {"Content-Length": str(len(original))})])
        receipt = h.fetch(fixture_source())
        self.assertEqual(receipt.temporary_path.read_bytes(), original)
        self.assertEqual(receipt.sha256, hashlib.sha256(original).hexdigest())
        history = h.state.request_history(h.context, receipt.url)
        self.assertEqual(history[0].value["ordinal"], 1)
        self.assertEqual(history[0].value["outcome"], "received")
        self.assertIsNotNone(history[0].value["permit_next_allowed_at"])

    def test_retry_after_longer_than_local_cap_is_never_shortened(self):
        h = self.harness([(429, b"", {"Retry-After": "180"}), (200, b"valid fixture", {})])
        h.fetch_response_only()
        self.assertGreaterEqual(h.starts[1] - h.starts[0], 180)
        self.assertEqual(h.attempt_count, 2)
        self.assertEqual(h.maximum_active, 1)
        rows = h.state.request_history(h.context, "https://www.sec.gov/Archives/edgar/full-index/2015/QTR1/index.json")
        self.assertEqual(rows[0].value["retry"]["server_delay_seconds"], 180)
        self.assertEqual(rows[0].value["next_allowed_at"], rows[0].value["retry"]["not_before"])
        self.assertTrue(any(event["event"] == "cooldown" for event in h.events))

    def test_retry_after_date_and_invalid_header_are_diagnosed(self):
        now = fixture_context().started_at
        self.assertEqual(self.download.retry_after(format_datetime(now+timedelta(seconds=180), usegmt=True), now), 180)
        for value in (None, "nonsense", "-1", "1.5", "NaN", ""):
            with self.subTest(value=value):
                self.assertIsNone(self.download.retry_after(value, now))
        self.assertEqual(self.download.retry_after("0", now), 0)
        h = self.harness([(503, b"", {"Retry-After": "invalid"}), (200, b"listing", {})])
        h.fetch_response_only()
        row = h.state.request_history(h.context, "https://www.sec.gov/Archives/edgar/full-index/2015/QTR1/index.json")[0]
        self.assertFalse(row.value["retry"]["retry_after_valid"])
        self.assertEqual(row.value["retry"]["retry_after_value"], "invalid")

    def test_retry_delay_jitter_boundaries_preserve_long_server_delay(self):
        settings = fixture_settings()
        self.assertEqual(self.download.retry_delay(1, None, settings, 0), 0)
        self.assertEqual(self.download.retry_delay(5, None, settings, 1), 32)
        self.assertEqual(self.download.retry_delay(5, 180, settings, 0.1), 180)
        for jitter in (-0.01, 1.01, float("nan"), True):
            with self.subTest(jitter=jitter), self.assertRaises(ValueError):
                self.download.retry_delay(1, None, settings, jitter)

    def test_fifth_failure_is_terminal_and_restart_cannot_send_a_sixth(self):
        h = self.harness([(503, b"failure", {}) for _ in range(5)] + [(200, b"sixth", {})])
        for invocation in range(2):
            with self.subTest(invocation=invocation), self.assertRaises(self.download.FetchError) as raised:
                h.fetch_response_only()
            self.assertEqual(raised.exception.error.code, "attempts_exhausted")
            self.assertEqual(h.attempt_count, 5)
        self.assertEqual([row.value["ordinal"] for row in h.state.request_history(h.context, raised.exception.receipt.url)], [1, 2, 3, 4, 5])

    def test_pre_dispatch_crash_consumes_ordinal_after_reopen(self):
        from sec_edgar_ingest.state import AcquisitionState
        h = self.harness([(200, b"listing", {})])
        url = "https://www.sec.gov/Archives/edgar/full-index/2015/QTR1/index.json"
        h.state.begin_attempt(h.context)
        h.state.begin_request(h.context, url, None, "uncertain-crash", 1)
        h.store.close()
        h.leases.close()
        h.store, h.objects, h.leases = store_bundle(h.root, clock=h.clock)
        h.state = AcquisitionState(h.store, clock=h.clock)
        h.client.state = h.state
        h.coordinator.store, h.coordinator.leases = h.store, h.leases
        h.fetch_response_only()
        rows = h.state.request_history(h.context, url)
        self.assertEqual([row.value["ordinal"] for row in rows], [1, 2])
        self.assertIsNone(rows[0].value["receipt"])
        self.assertEqual(rows[0].value["outcome"], "uncertain")

    def test_five_uncertain_crashes_exhaust_budget_and_new_attempt_audits_them(self):
        h = self.harness([(200, b"listing", {})])
        url = "https://www.sec.gov/Archives/edgar/full-index/2015/QTR1/index.json"
        old = h.context
        for ordinal in range(1, 6):
            h.state.begin_request(old, url, None, f"crash-{ordinal}", ordinal)
        with self.assertRaises(self.download.FetchError) as exhausted:
            h.fetch_response_only()
        self.assertEqual(exhausted.exception.error.code, "attempts_exhausted")
        self.assertEqual(h.attempt_count, 0)
        h.context = replace(old, attempt_id="explicit-after-five-crashes")
        receipt = h.fetch_response_only()
        row, = h.state.request_history(h.context, receipt.url)
        self.assertTrue(row.value["prior_exhaustion"], "five uncertain pre-dispatch rows are an exhausted prior budget")
        self.assertEqual(row.value["prior_exhaustion"][0]["attempt_id"], old.attempt_id)

    def test_html_200_fetch_reports_quarantine_outcome_and_preserves_original(self):
        h = self.harness([(200, b"<html>unexpected ordinary page</html>", {})])
        with self.assertRaises(self.download.FetchError) as quarantined:
            h.fetch(fixture_source())
        self.assertEqual(quarantined.exception.error.code, "unexpected_page")
        self.assertEqual(quarantined.exception.error.details.get("outcome"), "quarantined")
        self.assertEqual(quarantined.exception.receipt.temporary_path.read_bytes(), b"<html>unexpected ordinary page</html>")
        row, = h.state.request_history(h.context, fixture_source().canonical_url)
        self.assertEqual(row.value["outcome"], "quarantined")

    def test_new_command_attempt_is_separate_and_audits_prior_exhaustion(self):
        h = self.harness([(503, b"failure", {}) for _ in range(5)]+[(200, b"listing", {})])
        with self.assertRaises(self.download.FetchError):
            h.fetch_response_only()
        old = h.context
        h.context = replace(old, attempt_id="deliberately-new-attempt")
        receipt = h.fetch_response_only()
        row = h.state.request_history(h.context, receipt.url)[0]
        self.assertEqual(row.value["ordinal"], 1)
        self.assertEqual(row.value["prior_exhaustion"][0]["attempt_id"], old.attempt_id)
        self.assertEqual(len(h.state.request_history(old, receipt.url)), 5)

    def test_ordinal_is_durable_before_sender_dispatch(self):
        h = self.harness([(200, b"listing", {})])
        real_send = h.sender.send
        def inspect(url, context, permit, *, cancellation):
            row, = h.state.request_history(context, url)
            self.assertEqual(row.value["request_id"], permit.request_id)
            self.assertIsNone(row.value["receipt"])
            return real_send(url, context, permit, cancellation=cancellation)
        h.sender.send = inspect
        h.fetch_response_only()

    def test_timeout_retry_still_consumes_owner_rate_budget(self):
        h = self.harness([self.download.ResponseSpec(0, b"prefix", {}, "timeout"), (200, b"listing", {})])
        h.client.jitter = lambda: 0.0
        h.fetch_response_only()
        self.assertGreaterEqual(h.starts[1]-h.starts[0], 1/3)
        self.assertEqual(h.maximum_active, 1)
        self.assertEqual(len([event for event in h.events if event["event"] == "reserve"]), 2)

    def test_denial_halts_next_source_and_new_attempt_in_same_run(self):
        denial = (Path(__file__).parent / "fixtures/raw/denial.html").read_bytes()
        for status, body in ((403, b"denied"), (200, denial)):
            with self.subTest(status=status):
                h = self.harness([(status, body, {}), (200, b"unreachable", {})])
                with self.assertRaises(self.download.FetchError) as raised:
                    h.fetch(fixture_source())
                self.assertEqual(raised.exception.error.code, "access_denied")
                h.context = replace(h.context, attempt_id="cannot-evade-denial")
                with self.assertRaises(self.download.FetchError) as stopped:
                    h.fetch(fixture_source("2015Q2"))
                self.assertEqual(stopped.exception.error.code, "run_halted")
                self.assertEqual(h.attempt_count, 1)
                self.assertEqual(h.state.run_halt(h.context).code, "access_denied")

    def test_listed_not_found_is_pending_and_redirect_is_refused(self):
        for status, code in ((404, "listed_missing"), (302, "redirect_refused")):
            with self.subTest(status=status):
                h = self.harness([(status, b"retained body", {"Location": "https://example.com/elsewhere"})])
                with self.assertRaises(self.download.FetchError) as raised:
                    h.fetch(fixture_source())
                self.assertEqual(raised.exception.error.code, code)
                self.assertEqual(raised.exception.receipt.temporary_path.read_bytes(), b"retained body")
                self.assertEqual(h.attempt_count, 1)
                row, = h.state.request_history(h.context, fixture_source().canonical_url)
                self.assertEqual(row.value["outcome"], "pending" if status == 404 else "failed")

    def test_server_delay_past_command_deadline_is_durably_deferred(self):
        context = replace(fixture_context(), deadline=fixture_context().started_at+timedelta(seconds=100))
        h = self.harness([(429, b"", {"Retry-After": "180"}), (200, b"unreachable", {})], context=context)
        with self.assertRaises(self.download.FetchError) as raised:
            h.fetch_response_only()
        self.assertEqual(raised.exception.error.code, "deferred")
        self.assertEqual(h.attempt_count, 1)
        row, = h.state.request_history(context, raised.exception.receipt.url)
        self.assertEqual(row.value["outcome"], "deferred")
        self.assertEqual(row.value["retry"]["server_delay_seconds"], 180)
        self.assertEqual(row.value["next_allowed_at"], row.value["retry"]["not_before"])
        h.sender.responses = [self.download.ResponseSpec(200, b"listing", {})]
        h.context = replace(fixture_context(), execution_id="another-command", attempt_id="fresh", deadline=fixture_context().started_at+timedelta(seconds=1000))
        h.fetch_response_only()
        self.assertGreaterEqual(h.starts[1]-h.starts[0], 180)

    def test_server_clock_offset_cannot_sleep_past_command_deadline(self):
        context = replace(fixture_context(), deadline=fixture_context().started_at+timedelta(seconds=100))
        h = self.harness([(429, b"", {"Retry-After": "180"}), (200, b"unreachable", {})], context=context)
        class OffsetServerClock:
            precision_seconds = 0
            def now(self):
                return h.clock.now()-timedelta(seconds=120)
            def monotonic(self):
                return h.clock.monotonic()
        h.leases.clock = OffsetServerClock()
        with self.assertRaises(self.download.FetchError) as raised:
            h.fetch_response_only()
        self.assertEqual(raised.exception.error.code, "deferred")
        self.assertEqual(h.attempt_count, 1)
        self.assertLess(h.clock.monotonic(), 100, "server UTC offset must not extend the host command lifetime")
        row, = h.state.request_history(context, raised.exception.receipt.url)
        self.assertEqual(row.value["outcome"], "deferred")
        self.assertEqual(row.value["retry"]["server_delay_seconds"], 180)

    def test_final_failed_attempt_retains_server_cooldown(self):
        h = self.harness([(503, b"failure", {}) for _ in range(4)] + [(429, b"", {"Retry-After": "180"})])
        with self.assertRaises(self.download.FetchError) as raised:
            h.fetch_response_only()
        last = h.state.request_history(h.context, raised.exception.receipt.url)[-1]
        self.assertEqual(last.value["outcome"], "exhausted")
        self.assertEqual(last.value["retry"]["server_delay_seconds"], 180)
        self.assertEqual(last.value["next_allowed_at"], last.value["retry"]["not_before"])

    def test_retry_sleep_has_no_active_ownership(self):
        h = self.harness([(503, b"", {}), (200, b"listing", {})])
        original_sleep = h.clock.sleep
        sleeps = []
        def inspect(seconds):
            if seconds >= 2:
                sleeps.append(h.coordinator._active)
            original_sleep(seconds)
        h.clock.sleep = inspect
        h.fetch_response_only()
        self.assertTrue(sleeps)
        self.assertTrue(all(turn is None for turn in sleeps))

    def test_fetch_rejects_untrusted_origin_before_attempt_or_dispatch(self):
        h = self.harness([(200, b"listing", {})])
        with self.assertRaises(ValueError):
            h.fetch_response_only("http://127.0.0.1:1234/index.json")
        self.assertEqual(h.attempt_count, 0)
        self.assertEqual(tuple(h.store.scan("TransportAttempt", {})), ())

    def test_missing_server_time_bounds_never_uses_host_utc_for_retry(self):
        h = self.harness([(429, b"", {"Retry-After": "180"})])
        real_send = h.sender.send
        def remove_bounds(url, context, permit, *, cancellation):
            receipt = real_send(url, context, permit, cancellation=cancellation)
            h.client._retry_time_bounds = lambda: None
            return receipt
        h.sender.send = remove_bounds
        with self.assertRaises(self.download.FetchError) as raised:
            h.fetch_response_only()
        self.assertEqual(raised.exception.error.code, "clock_uncertain")
        self.assertEqual(h.attempt_count, 1)


class PolicyHandoffTests(unittest.TestCase):
    def setUp(self):
        self.download = importlib.import_module("sec_edgar_ingest.download")
        self.first = DownloadHarness([])
        self.addCleanup(self.first.close)

    def successor(self, responses, *, other_run=False):
        context = replace(self.first.context, execution_id="queued-execution", attempt_id="queued-attempt", priority="daily",
                          run_id="independent-run" if other_run else self.first.context.run_id)
        second = DownloadHarness(responses, root=self.first.root, clock=self.first.clock, context=context)
        self.addCleanup(second.close)
        return second

    def test_queued_caller_cannot_dispatch_after_another_client_persists_denial(self):
        import threading
        first = self.first
        first.sender.responses = [self.download.ResponseSpec(403, b"original denial", {})]
        second = self.successor([(200, b"must not dispatch", {})])
        waiting, resume = threading.Event(), threading.Event()
        exchange = second.coordinator.exchange
        outcomes = []
        def queued_exchange(*args, **kwargs):
            waiting.set()
            if not resume.wait(2):
                raise AssertionError("queued fixture was not resumed")
            return exchange(*args, **kwargs)
        second.coordinator.exchange = queued_exchange
        def queued_fetch():
            try:
                second.fetch_response_only()
                outcomes.append("sent")
            except self.download.FetchError as error:
                outcomes.append(error.error.code)
        thread = threading.Thread(target=queued_fetch)
        thread.start()
        try:
            self.assertTrue(waiting.wait(2), "caller must pass its initial halt check before denial")
            with self.assertRaises(self.download.FetchError) as denied:
                first.fetch_response_only()
            self.assertEqual(denied.exception.error.code, "access_denied")
            self.assertIsNotNone(second.state.run_halt(second.context))
            resume.set()
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(second.starts, [], "serialized admission must recheck a durable run halt before ordinal and transport")
            self.assertEqual(outcomes, ["run_halted"])
            self.assertEqual(second.state.request_history(second.context, denied.exception.receipt.url), ())
        finally:
            resume.set()
            thread.join(3)

    def test_retry_after_is_published_before_original_owner_hands_off(self):
        first = self.first
        first.sender.responses = [self.download.ResponseSpec(429, b"original cooldown", {"Retry-After": "180"}),
                                  self.download.ResponseSpec(200, b"listing", {})]
        second = self.successor([(200, b"other listing", {})])
        admitted = []
        def observe(event):
            first.events.append(event)
            if event["event"] == "release" and not admitted:
                admitted.append("next-owner")
                second.fetch_response_only()
        first.coordinator.observer = observe
        first.fetch_response_only()
        self.assertEqual(len(second.starts), 1)
        self.assertGreaterEqual(second.starts[0]-first.starts[0], 180,
                                "already queued next owner must see the server delay at the first release")
        self.assertEqual(first.maximum_active, 1)
        row = first.state.request_history(first.context, "https://www.sec.gov/Archives/edgar/full-index/2015/QTR1/index.json")[0]
        self.assertEqual(row.value["retry"]["server_delay_seconds"], 180)

    def test_unconfirmed_denial_persistence_retains_original_receipt_and_unsafe_guard(self):
        first = self.first
        first.sender.responses = [self.download.ResponseSpec(403, b"original denial without policy acknowledgement", {})]
        def unavailable(*args):
            raise OSError("fixture run-halt write outcome unknown")
        first.state.halt_run = unavailable
        with self.assertRaises(self.download.FetchError) as raised:
            first.fetch_response_only()
        self.assertEqual(raised.exception.error.code, "ownership_lost")
        self.assertEqual(raised.exception.receipt.temporary_path.read_bytes(), b"original denial without policy acknowledgement")
        self.assertFalse(raised.exception.receipt.complete)
        self.assertFalse(any(event["event"] == "release" for event in first.events))
        row, = first.state.request_history(first.context, raised.exception.receipt.url)
        self.assertEqual(row.value["outcome"], "failed")
        self.assertEqual(first.attempt_count, 1)

    def test_unconfirmed_cooldown_write_does_not_claim_a_persisted_next_allowed(self):
        from sec_edgar_ingest.storage.contracts import OwnershipLost
        first = self.first
        first.sender.responses = [self.download.ResponseSpec(429, b"original cooldown without acknowledgement", {"Retry-After": "180"})]
        def unavailable(instant):
            self.assertIsNotNone(first.coordinator._active)
            raise OwnershipLost("fixture sentinel policy write outcome unknown")
        first.coordinator.defer_until = unavailable
        with self.assertRaises(self.download.FetchError) as raised:
            first.fetch_response_only()
        self.assertEqual(raised.exception.error.code, "cooldown_unconfirmed")
        self.assertEqual(raised.exception.receipt.temporary_path.read_bytes(), b"original cooldown without acknowledgement")
        self.assertFalse(raised.exception.receipt.complete)
        self.assertFalse(any(event["event"] == "release" for event in first.events))
        row, = first.state.request_history(first.context, raised.exception.receipt.url)
        self.assertIs(row.value["retry"].get("cooldown_confirmed"), False)
        self.assertEqual(row.value["next_allowed_at"], row.value["permit_next_allowed_at"])

    def test_retry_admission_rechecks_halt_after_sleep_outside_ownership(self):
        first = self.first
        first.sender.responses = [self.download.ResponseSpec(429, b"retry", {}), self.download.ResponseSpec(200, b"must not retry", {})]
        second = self.successor([(403, b"denial during retry sleep", {})])
        sleep = first.clock.sleep
        denied = []
        def while_sleep(seconds):
            if seconds >= 2 and not denied and first.coordinator._active is None:
                denied.append(True)
                with self.assertRaises(self.download.FetchError) as raised:
                    second.fetch_response_only()
                self.assertEqual(raised.exception.error.code, "access_denied")
            sleep(seconds)
        first.clock.sleep = while_sleep
        with self.assertRaises(self.download.FetchError) as halted:
            first.fetch_response_only()
        self.assertEqual(halted.exception.error.code, "run_halted")
        self.assertEqual(first.attempt_count, 1)
        self.assertEqual(len(first.state.request_history(first.context, halted.exception.receipt.url)), 1)

    def test_run_halt_is_visible_at_the_original_response_turn_release(self):
        first = self.first
        first.sender.responses = [self.download.ResponseSpec(403, b"denial before release", {})]
        halt_at_release = []
        def observe(event):
            first.events.append(event)
            if event["event"] == "release":
                halt_at_release.append(first.state.run_halt(first.context))
        first.coordinator.observer = observe
        with self.assertRaises(self.download.FetchError):
            first.fetch_response_only()
        self.assertEqual(len(halt_at_release), 1)
        self.assertEqual(halt_at_release[0].code, "access_denied")

    def test_malformed_durable_policy_latch_fails_before_ordinal_or_dispatch(self):
        first = self.first
        with first.coordinator.turn("fixture-malformed-policy", "backfill", first.context.deadline) as turn:
            row = first.leases.read_journal(turn.handle)
            value = row.to_mapping()["value"]
            value["policy_block"] = {"message": "missing required structured Error fields"}
            first.leases.write_journal(turn.handle, value, row.version)
        second = self.successor([(200, b"must not send", {})], other_run=True)
        with self.assertRaises(self.download.FetchError):
            second.fetch_response_only()
        self.assertEqual(second.starts, [])
        self.assertEqual(tuple(second.store.scan("TransportAttempt", {})), ())

    def test_very_large_valid_numeric_delay_also_blocks_without_local_fallback(self):
        first = self.first
        header = "9"*500
        first.sender.responses = [self.download.ResponseSpec(503, b"original nonfloat delay", {"Retry-After": header})]
        with self.assertRaises(self.download.FetchError) as raised:
            first.fetch_response_only()
        self.assertEqual(raised.exception.error.code, "retry_delay_unrepresentable")
        self.assertEqual(raised.exception.error.details["retry"]["retry_after_value"], header)
        self.assertTrue(raised.exception.error.details["retry"]["retry_after_valid"])
        self.assertEqual(first.attempt_count, 1)
        second = self.successor([(200, b"must not send", {})], other_run=True)
        with self.assertRaises(self.download.FetchError) as blocked:
            second.fetch_response_only()
        self.assertEqual(blocked.exception.error.code, "policy_blocked")
        self.assertEqual(second.attempt_count, 0)

    def test_calendar_overflow_retains_receipt_and_blocks_all_successor_runs(self):
        first = self.first
        header = "1000000000000"
        first.sender.responses = [self.download.ResponseSpec(429, b"original impossible delay", {"Retry-After": header})]
        with self.assertRaises(self.download.FetchError) as deferred:
            first.fetch_response_only()
        self.assertEqual(deferred.exception.error.code, "retry_delay_unrepresentable")
        self.assertEqual(deferred.exception.error.details["outcome"], "deferred")
        self.assertEqual(deferred.exception.receipt.temporary_path.read_bytes(), b"original impossible delay")
        self.assertEqual(deferred.exception.receipt.headers["Retry-After"], header)
        row, = first.state.request_history(first.context, deferred.exception.receipt.url)
        self.assertEqual(row.value["retry"]["retry_after_value"], header)
        self.assertEqual(row.value["outcome"], "deferred")
        second = self.successor([(200, b"must not send", {})], other_run=True)
        with self.assertRaises(self.download.FetchError) as blocked:
            second.fetch_response_only()
        self.assertEqual(blocked.exception.error.code, "policy_blocked")
        self.assertEqual(second.starts, [])
        self.assertEqual(second.state.request_history(second.context, deferred.exception.receipt.url), ())


class BoundedProcessTests(unittest.TestCase):
    def setUp(self):
        self.download = importlib.import_module("sec_edgar_ingest.download")
        self.assertTrue(hasattr(self.download, "BoundedSender"),
                        "a supervised spawn child and independent fatal timer must bound actual transport")
        from sec_edgar_ingest.coordination import Clock
        self.clock = Clock()
        # Every child here is a real spawn, so the coordinator's windows must absorb a slow one.
        self.settings = spawn_tolerant_settings()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def server(self, *args, **kwargs):
        from support import LoopbackServer
        server = LoopbackServer(*args, **kwargs)
        self.addCleanup(server.close)
        return server

    def send(self, server, *, target=None, cancellation=None, seconds=SPAWN_ALLOWANCE_SECONDS + 1,
             start_seconds=SPAWN_ALLOWANCE_SECONDS):
        import multiprocessing
        from support import loopback_sender, real_context, real_permit
        sender = loopback_sender(self.settings, self.clock, server.origin, target=target, spool=self.root/"sender")
        permit = real_permit(self.clock, seconds, start_seconds=start_seconds)
        cancellation = cancellation or multiprocessing.get_context("spawn").Event()
        from support import retain_process_evidence
        try:
            return sender.send(server.url, real_context(self.clock, self.settings), permit, cancellation=cancellation)
        finally:
            retain_process_evidence(self._testMethodName+("-"+target.__name__ if target else ""), self.root/"sender", server)

    def assert_drained(self, receipt):
        import json
        import os
        events = [json.loads(line) for line in (receipt.temporary_path.parent/"transport.jsonl").read_text().splitlines()]
        joined = [event for event in events if event["event"] == "child-joined"]
        self.assertEqual(len(joined), 1)
        self.assertIsNotNone(joined[0]["exitcode"])
        with self.assertRaises(ProcessLookupError):
            os.kill(joined[0]["pid"], 0)
        self.assertEqual(receipt.sha256, hashlib.sha256(receipt.temporary_path.read_bytes()).hexdigest())
        return events

    def test_default_windows_absorb_a_slow_spawn(self):
        from sec_edgar_ingest.coordination import Coordinator
        from support import loopback_sender, real_context, slow_spawn_child_exchange
        with self.subTest(path="direct send"):
            server = self.server(b"sent after a slow spawn")
            receipt = self.send(server, target=slow_spawn_child_exchange)
            self.assertTrue(receipt.complete, receipt.to_mapping())
            self.assertEqual(receipt.temporary_path.read_bytes(), server.body)
            self.assert_drained(receipt)
        with self.subTest(path="coordinator exchange"):
            server = self.server(b"exchanged after a slow spawn")
            store, _, leases = store_bundle(self.root/"state", clock=self.clock)
            self.addCleanup(store.close)
            self.addCleanup(leases.close)
            coordinator = Coordinator(self.settings, store, leases, self.clock)
            sender = loopback_sender(self.settings, self.clock, server.origin, target=slow_spawn_child_exchange,
                                     spool=self.root/"coordinated")
            receipt = coordinator.exchange(real_context(self.clock, self.settings), server.url, sender)
            self.assertTrue(receipt.complete, receipt.to_mapping())
            self.assertEqual(receipt.temporary_path.read_bytes(), server.body)
            self.assert_drained(receipt)

    def test_real_trickle_is_cancelled_by_total_lifetime_with_partial_socket_evidence(self):
        import time
        from sec_edgar_ingest.coordination import Coordinator
        from support import loopback_sender, real_context, retain_process_evidence
        server = self.server(b"fixture-entity-prefix", mode="trickle")
        store, _, leases = store_bundle(self.root/"state", clock=self.clock)
        self.addCleanup(store.close)
        self.addCleanup(leases.close)
        coordinator = Coordinator(self.settings, store, leases, self.clock)
        sender = loopback_sender(self.settings, self.clock, server.origin, spool=self.root/"sender")
        started = time.monotonic()
        receipt = coordinator.exchange(real_context(self.clock, self.settings), server.url, sender)
        elapsed = time.monotonic()-started
        self.assertFalse(receipt.complete)
        self.assertLess(elapsed, self.settings.http.exchange_deadline_seconds + 0.8)
        self.assertTrue(server.closed.wait(SPAWN_WAIT_SECONDS), "terminated child must close its actual socket")
        self.assertGreater(server.sent, 0)
        self.assertGreater(receipt.byte_count, 0, "trickle bytes sent before timeout must survive the original-byte spool")
        self.assertLessEqual(receipt.byte_count, server.sent)
        events = self.assert_drained(receipt)
        child_start = next(event for event in events if event["event"] == "socket-start")
        reserved = next(event for event in events if event["event"] == "supervisor-start")
        self.assertLess(child_start["monotonic"], reserved["start_before_mono"])
        self.assertLessEqual(next(event for event in events if event["event"] == "child-joined")["monotonic"], reserved["deadline_mono"]+0.1)
        retain_process_evidence("trickle-total-lifetime", receipt.temporary_path.parent, server, {"elapsed": elapsed, "receipt": receipt.to_mapping()})

    def test_next_actual_get_waits_for_drain_spacing_after_in_adapter_delay(self):
        from sec_edgar_ingest.coordination import Coordinator
        from support import delayed_adapter_child, loopback_sender, real_context, retain_process_evidence
        first = self.server(b"first bounded response")
        second = self.server(b"second bounded response")
        store, _, leases = store_bundle(self.root/"state", clock=self.clock)
        self.addCleanup(store.close)
        self.addCleanup(leases.close)
        coordinator = Coordinator(self.settings, store, leases, self.clock)
        # Two paced reservations need more than real_context's fixed 10 s run deadline.
        context = replace(real_context(self.clock, self.settings),
                          deadline=self.clock.now() + timedelta(seconds=4 * SPAWN_WAIT_SECONDS))
        first_sender = loopback_sender(self.settings, self.clock, first.origin, target=delayed_adapter_child, spool=self.root/"first")
        second_sender = loopback_sender(self.settings, self.clock, second.origin, spool=self.root/"second")
        try:
            first_receipt = coordinator.exchange(context, first.url, first_sender)
            second_receipt = coordinator.exchange(context, second.url, second_sender)
            self.assertTrue(first_receipt.complete, first_receipt.to_mapping())
            self.assertTrue(second_receipt.complete, second_receipt.to_mapping())
            first_get = next(event["monotonic"] for event in first.events if event["event"] == "request-received")
            second_get = next(event["monotonic"] for event in second.events if event["event"] == "request-received")
            # With spawn-tolerant windows the delayed GET lands inside its charged dispatch window, so this is
            # end-to-end spacing only; test_coordination pins the drain-based pacing with a logical clock.
            self.assertGreaterEqual(second_get-first_get, 1/self.settings.sec.requests_per_second, "the second real GET must start at least one configured interval after the first")
            self.assertTrue(first.closed.wait(SPAWN_WAIT_SECONDS))
            self.assertTrue(second.closed.wait(SPAWN_WAIT_SECONDS))
            self.assert_drained(first_receipt)
            self.assert_drained(second_receipt)
        finally:
            retain_process_evidence("delayed-adapter-first", self.root/"first", first)
            retain_process_evidence("delayed-adapter-second", self.root/"second", second)

    def test_slow_headers_are_bounded_even_without_inactivity_timeout(self):
        import time
        from support import retain_process_evidence
        # The header bytes drip for longer than the exchange deadline, so only the deadline can end the exchange.
        server = self.server(mode="headers", drip_seconds=0.25)
        started = time.monotonic()
        receipt = self.send(server)
        self.assertFalse(receipt.complete)
        self.assertLess(time.monotonic()-started, SPAWN_ALLOWANCE_SECONDS + 1 + 0.8)
        self.assertTrue(server.closed.wait(SPAWN_WAIT_SECONDS))
        self.assert_drained(receipt)
        retain_process_evidence("slow-headers", receipt.temporary_path.parent, server, {"receipt": receipt.to_mapping()})

    def test_spawn_uses_original_identity_bytes_no_proxy_auth_retry_or_redirect(self):
        import os
        from unittest.mock import patch
        from support import retain_process_evidence
        server = self.server(b"original bytes", status=302, headers={"Location": "http://127.0.0.1:1/must-not-follow", "ETag": "fixture-validator"})
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1", "REQUESTS_CA_BUNDLE": "/fixture/nonexistent", "AWS_ACCESS_KEY_ID": "synthetic-fixture-only"}):
            receipt = self.send(server)
        self.assertTrue(receipt.complete, receipt.to_mapping())
        self.assertEqual(receipt.status, 302)
        self.assertEqual(receipt.temporary_path.read_bytes(), b"original bytes")
        self.assertEqual(receipt.headers["ETag"], "fixture-validator")
        self.assertEqual(len(server.requests), 1)
        self.assertIn("User-Agent: Lowell Mason sec-edgar-ingest mason.lowell@mac.com", server.requests[0])
        self.assertIn("Accept-Encoding: identity", server.requests[0])
        self.assertNotIn("Authorization:", server.requests[0])
        events = self.assert_drained(receipt)
        cleared = next(event for event in events if event["event"] == "child-environment-cleared")
        self.assertEqual(cleared["remaining_environment_keys"], 0)
        retain_process_evidence("identity-no-ambient-transport", receipt.temporary_path.parent, server, {"receipt": receipt.to_mapping()})

    def test_content_encoding_is_refused_without_decoding_original_entity(self):
        import gzip
        body = gzip.compress(b"original encoded entity", mtime=0)
        server = self.server(body, headers={"Content-Encoding": "gzip"})
        receipt = self.send(server)
        self.assertFalse(receipt.complete)
        self.assertEqual(receipt.error.code, "unsupported_content_encoding")
        self.assertEqual(receipt.temporary_path.read_bytes(), body)
        self.assert_drained(receipt)

    def test_content_length_mismatch_preserves_actual_partial_prefix(self):
        from support import retain_process_evidence
        server = self.server(b"actual original partial", mode="truncated")
        receipt = self.send(server)
        self.assertFalse(receipt.complete)
        self.assertEqual(receipt.temporary_path.read_bytes(), server.body)
        self.assertIn(receipt.error.code, ("incomplete_body", "content_length_mismatch"))
        self.assert_drained(receipt)
        retain_process_evidence("truncated-original-prefix", receipt.temporary_path.parent, server, {"receipt": receipt.to_mapping()})

    def test_received_cap_refuses_extra_byte_before_spool_write(self):
        self.settings = spawn_tolerant_settings(http={"max_received_bytes": 4})
        for mode in ("complete", "unadvertised"):
            with self.subTest(mode=mode):
                try:
                    server = self.server(b"12345", mode=mode)
                    receipt = self.send(server)
                    self.assertFalse(receipt.complete)
                    self.assertEqual(receipt.error.code, "received_limit")
                    self.assertLessEqual(receipt.byte_count, 4)
                    if mode == "unadvertised":
                        self.assertEqual(receipt.temporary_path.read_bytes(), b"1234")
                    self.assert_drained(receipt)
                finally:
                    # The modes share one spool, so a failed mode must not leave its outcome or trace to the next.
                    for left in ("transport.jsonl", "receipt.json"):
                        (self.root/"sender"/left).unlink(missing_ok=True)

    def test_timer_installation_failure_and_stale_child_start_send_zero_requests(self):
        from support import (retain_process_evidence, slow_spawn_timer_failure_child, stale_preparation_child,
                             stale_start_child, timer_failure_child)
        # Every deadline outlasts a slow spawn. The timer cases also get a start window that absorbs one;
        # the stale cases keep the production 1/3 s start window and overrun it on purpose.
        seconds = SPAWN_ALLOWANCE_SECONDS + 1
        cases = (("timer-installation-failure", timer_failure_child, SPAWN_ALLOWANCE_SECONDS, "hard_timer_unavailable"),
                 ("timer-installation-failure-after-slow-spawn", slow_spawn_timer_failure_child, SPAWN_ALLOWANCE_SECONDS,
                  "hard_timer_unavailable"),
                 ("stale-spawn-start", stale_start_child, 1/3, "permit_expired"),
                 ("stale-prepared-request", stale_preparation_child, 1/3, "permit_expired"))
        for name, target, start_seconds, code in cases:
            with self.subTest(name=name):
                try:
                    server = self.server()
                    receipt = self.send(server, target=target, seconds=seconds, start_seconds=start_seconds)
                    self.assertFalse(receipt.complete)
                    self.assertEqual(receipt.error.code, code)
                    self.assertFalse(server.connected.is_set())
                    self.assertEqual(server.requests, [])
                    self.assert_drained(receipt)
                    retain_process_evidence(name, receipt.temporary_path.parent, server, {"receipt": receipt.to_mapping()})
                finally:
                    # The cases share one spool, so a failed case must not leave its outcome or trace to the next.
                    for left in ("transport.jsonl", "receipt.json"):
                        (self.root/"sender"/left).unlink(missing_ok=True)

    def test_cancelled_sender_returns_only_after_child_join_and_socket_close(self):
        import multiprocessing
        import threading
        from support import retain_process_evidence
        server = self.server(b"prefix", mode="trickle")
        cancellation = multiprocessing.get_context("spawn").Event()
        def cancel_after_prefix():
            if server.prefix_sent.wait(SPAWN_WAIT_SECONDS):
                cancellation.wait(0.04)
                cancellation.set()
        thread = threading.Thread(target=cancel_after_prefix)
        thread.start()
        receipt = self.send(server, cancellation=cancellation)
        thread.join(SPAWN_WAIT_SECONDS)
        self.assertFalse(receipt.complete)
        self.assertEqual(receipt.error.code, "cancelled")
        self.assertTrue(server.closed.wait(SPAWN_WAIT_SECONDS))
        self.assert_drained(receipt)
        retain_process_evidence("lease-cancellation", receipt.temporary_path.parent, server, {"receipt": receipt.to_mapping()})

    def test_unknown_ipc_failure_stops_ownership_and_retains_unsafe_guard(self):
        from sec_edgar_ingest.coordination import Coordinator
        from support import ipc_loss_child, loopback_sender, real_context, retain_process_evidence
        server = self.server(b"retained after IPC loss")
        store, _, leases = store_bundle(self.root/"state", clock=self.clock)
        self.addCleanup(store.close)
        self.addCleanup(leases.close)
        coordinator = Coordinator(self.settings, store, leases, self.clock)
        events = []
        coordinator.observer = events.append
        sender = loopback_sender(self.settings, self.clock, server.origin, target=ipc_loss_child, spool=self.root/"sender")
        with self.assertRaises(self.download.SenderFailure) as raised:
            coordinator.exchange(real_context(self.clock, self.settings), server.url, sender)
        receipt = raised.exception.receipt
        self.assertEqual(receipt.temporary_path.read_bytes(), server.body)
        self.assertTrue(server.closed.wait(SPAWN_WAIT_SECONDS))
        self.assert_drained(receipt)
        self.assertTrue(any(event["event"] == "loss" for event in events))
        self.assertFalse(any(event["event"] == "release" for event in events))
        retain_process_evidence("unconfirmed-ipc-unsafe-guard", receipt.temporary_path.parent, server, {"coordination": events, "receipt": receipt.to_mapping()})

    def test_malformed_result_and_unexpected_child_exception_retain_partial_failure(self):
        from support import malformed_metadata_child, unexpected_failure_child, retain_process_evidence
        for name, target, expected_code in (("malformed-metadata", malformed_metadata_child, "sender_protocol"), ("unexpected-child-exception", unexpected_failure_child, "sender_internal")):
            with self.subTest(name=name):
                server = self.server(b"original even with malformed metadata")
                try:
                    self.send(server, target=target)
                except Exception as error:
                    self.assertIsInstance(error, self.download.SenderFailure, "an invalid child result must still expose its retained receipt")
                    self.assertEqual(error.receipt.error.code, expected_code)
                    self.assertFalse(error.receipt.complete)
                    self.assert_drained(error.receipt)
                    if name == "malformed-metadata":
                        self.assertEqual(error.receipt.temporary_path.read_bytes(), server.body)
                else:
                    self.fail("unknown child result must stop ownership")
                finally:
                    retain_process_evidence(name, self.root/"sender", server)
                    trace = self.root/"sender/transport.jsonl"
                    if trace.exists():
                        trace.unlink()

    def test_production_sender_refuses_loopback_and_logical_clocks(self):
        import multiprocessing
        from sec_edgar_ingest.coordination import ManualClock
        from support import real_context, real_permit
        sender = self.download.BoundedSender(self.settings, self.clock)
        with self.assertRaises(ValueError):
            sender.send("http://127.0.0.1:1234/fixture", real_context(self.clock, self.settings), real_permit(self.clock), cancellation=multiprocessing.get_context("spawn").Event())
        with self.assertRaises(ValueError):
            self.download.BoundedSender(self.settings, ManualClock(fixture_context().started_at))

    def test_independent_fatal_timer_survives_supervisor_death_during_blocking_headers(self):
        import json
        import multiprocessing
        import subprocess
        import time
        from support import crash_supervisor, loopback_sender, real_context, retain_process_evidence
        from sec_edgar_ingest.coordination import Coordinator
        self.settings = spawn_tolerant_settings(coordination={"lease_seconds": 2, "renew_every_seconds": 1})
        server = self.server(mode="blocked-headers")
        spawn = multiprocessing.get_context("spawn")
        cancellation = spawn.Event()
        process = spawn.Process(target=crash_supervisor, args=(str(self.root), server.url, server.origin, cancellation))
        process.start()
        try:
            self.assertTrue(server.connected.wait(SPAWN_WAIT_SECONDS), "spawn child must reach the selected loopback before supervisor crash")
            process.terminate()
            process.join(1)
            self.assertFalse(process.is_alive())
            killed_at = time.monotonic()
            self.assertTrue(server.closed.wait(SPAWN_WAIT_SECONDS), "orphan child must close the blocked socket under its independent OS timer")
            events = [json.loads(line) for line in (self.root/"sender/transport.jsonl").read_text().splitlines()]
            armed = next(event for event in events if event["event"] == "alarm-armed")
            self.assertEqual(armed["alarm_disposition"], "default-fatal")
            self.assertFalse(armed["alarm_blocked"])
            self.assertFalse(any(event["event"] == "child-completed" for event in events))
            closed_at = next(event["monotonic"] for event in server.events if event["event"] == "socket-closed")
            self.assertLessEqual(closed_at, armed["deadline_mono"]+0.1)
            observation = subprocess.run(["ps", "-o", "stat=", "-p", str(armed["pid"])], capture_output=True, text=True, timeout=1)
            self.assertTrue(observation.returncode == 1 or not observation.stdout.strip() or observation.stdout.strip().startswith("Z"), observation.stdout)
            successor = self.server(b"successor bounded response")
            store, _, leases = store_bundle(self.root/"state", clock=self.clock)
            self.addCleanup(store.close)
            self.addCleanup(leases.close)
            coordinator = Coordinator(self.settings, store, leases, self.clock)
            coordination_events = []
            coordinator.observer = coordination_events.append
            sender = loopback_sender(self.settings, self.clock, successor.origin, spool=self.root/"successor")
            # The successor first waits out the dead owner's unsafe interval, so its run deadline is generous.
            context = replace(real_context(self.clock, self.settings), priority="daily",
                              deadline=self.clock.now() + timedelta(seconds=4 * SPAWN_WAIT_SECONDS))
            receipt = coordinator.exchange(context, successor.url, sender)
            self.assertTrue(receipt.complete, receipt.to_mapping())
            self.assert_drained(receipt)
            successor_get = next(event["monotonic"] for event in successor.events if event["event"] == "request-received")
            self.assertGreaterEqual(successor_get, armed["deadline_mono"])
            self.assertGreater(successor_get, closed_at)
            reserve = next(event for event in coordination_events if event["event"] == "reserve")
            self.assertEqual(reserve["epoch"], 2)
            retain_process_evidence("supervisor-crash-independent-timer", self.root/"sender", server, {"supervisor_pid": process.pid, "supervisor_exitcode": process.exitcode, "killed_at": killed_at, "orphan_state": observation.stdout.strip(), "successor": coordination_events})
            retain_process_evidence("supervisor-crash-successor", self.root/"successor", successor, {"receipt": receipt.to_mapping()})
        finally:
            if process.is_alive():
                process.terminate()
                process.join(1)
            retain_process_evidence("supervisor-crash-independent-timer", self.root/"sender", server,
                                    {"supervisor_pid": process.pid, "supervisor_exitcode": process.exitcode,
                                     "killed_at": locals().get("killed_at"),
                                     "orphan_state": locals().get("observation").stdout.strip() if "observation" in locals() else None,
                                     "successor": locals().get("coordination_events", [])})


class PartialExceptionTests(unittest.TestCase):
    def test_nested_incomplete_read_partial_is_preserved_exactly_once(self):
        import http.client
        import requests
        from urllib3.exceptions import ProtocolError
        download = importlib.import_module("sec_edgar_ingest.download")
        self.assertTrue(hasattr(download, "incomplete_read_bytes"), "nested transport exceptions must retain their original partial bytes")
        partial = http.client.IncompleteRead(b"original nested partial", 10)
        nested = requests.ConnectionError(ProtocolError("nested interruption", partial))
        nested.__cause__ = partial
        self.assertEqual(download.incomplete_read_bytes(nested), b"original nested partial")


class ExceptionTextTests(unittest.TestCase):
    """Raw exception text reaches a structured Error only as one safe line, never replacing the original failure."""
    def setUp(self):
        self.download = importlib.import_module("sec_edgar_ingest.download")

    def harness(self, responses):
        harness = DownloadHarness(responses)
        self.addCleanup(harness.close)
        return harness

    def test_unconfirmed_cooldown_records_one_line_exception_text(self):
        from unittest.mock import patch
        from support import exception_texts
        from sec_edgar_ingest.storage.contracts import OwnershipLost
        for text, line in exception_texts("OwnershipLost"):
            with self.subTest(text=text):
                h = self.harness([(429, b"original cooldown", {"Retry-After": "180"})])
                with patch.object(h.coordinator, "defer_until", side_effect=OwnershipLost(text)), \
                        self.assertRaises(self.download.FetchError) as raised:
                    h.fetch_response_only()
                error, loss = raised.exception.error, raised.exception.receipt.error
                self.assertEqual((error.code, error.message), ("cooldown_unconfirmed", "retry cooldown could not be confirmed: "+line))
                self.assertEqual((loss.code, loss.message), ("ownership_lost", "response policy was not confirmed: "+line))

    def test_unconfirmed_exchange_records_one_line_exception_text(self):
        from unittest.mock import patch
        from support import exception_texts
        for text, line in exception_texts("RuntimeError"):
            with self.subTest(text=text):
                h = self.harness([(200, b"never sent", {})])
                with patch.object(h.sender, "send", side_effect=RuntimeError(text)), \
                        self.assertRaises(self.download.FetchError) as raised:
                    h.fetch_response_only()
                error = raised.exception.error
                self.assertEqual((error.code, error.message),
                                 ("sender_unverified", "exchange stopped without a confirmed transport outcome: "+line))
                row, = h.state.request_history(h.context, raised.exception.receipt.url)
                self.assertEqual(row.value["error"]["message"], error.message)

    def test_unconfirmed_supervisor_records_one_line_exception_text(self):
        import threading
        from unittest.mock import MagicMock, patch
        from support import exception_texts, loopback_sender, real_context, real_permit
        from sec_edgar_ingest.coordination import Clock
        clock, settings, origin = Clock(), fixture_settings(), "http://127.0.0.1:9"
        for text, line in exception_texts("RuntimeError"):
            with self.subTest(text=text):
                spool = Path(self.enterContext(tempfile.TemporaryDirectory()))
                sender = loopback_sender(settings, clock, origin, spool=spool)
                # The child never starts (no pid), so the supervisor skips draining and reports its own failure.
                child = MagicMock(pid=None)
                child.start.side_effect = RuntimeError(text)
                with patch.object(self.download.SPAWN, "Process", return_value=child), \
                        self.assertRaises(self.download.SenderFailure) as raised:
                    sender.send(origin+"/fixture", real_context(clock, settings), real_permit(clock),
                                cancellation=threading.Event())
                self.assertEqual(str(raised.exception), "HTTP supervisor could not confirm its child outcome: "+line)
                self.assertEqual(raised.exception.receipt.error.code, "sender_unverified")

    def child_error(self, *patches, arm=None):
        """Run the HTTP child in-process (no spawn, no fatal timer) and rebuild its Error exactly as the parent does."""
        import os
        import threading
        import time
        from contextlib import ExitStack
        from unittest.mock import MagicMock, patch
        from sec_edgar_ingest.coordination import Clock
        spool = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (spool/"body").write_bytes(b"")
        settings, now = fixture_settings(), time.monotonic()
        transport = self.download._Transport(fixture_source().canonical_url, str(spool), settings.sec.user_agent, 1, 1,
                                             settings.http.max_received_bytes, now+60, now+60, None, False)
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ))
            stack.enter_context(patch.object(self.download, "arm_child_deadline", side_effect=arm))
            for item in patches:
                stack.enter_context(item)
            self.download._child_exchange(transport, threading.Event(), MagicMock())
        receipt, _ = self.download.BoundedSender(settings, Clock())._receipt(transport)
        return receipt.error

    def test_child_metadata_carries_one_line_exception_text_to_the_parent(self):
        from unittest.mock import MagicMock, patch
        import requests
        from support import exception_texts
        from sec_edgar_ingest.storage.contracts import OwnershipLost
        def response(read_failure=None):
            fake = MagicMock(status_code=200, headers={})
            fake.raw.read1.side_effect = read_failure
            return fake
        def adapter(**options):
            return patch("requests.adapters.HTTPAdapter.send", **options)
        scenarios = (
            ("sender_internal", "unexpected HTTP child failure: ", RuntimeError,
             lambda error: {"patches": (patch.object(self.download, "_read_http_entity", side_effect=error),)}),
            ("connection_failed", "HTTP connection failed: ", requests.ConnectionError,
             lambda error: {"patches": (adapter(side_effect=error),)}),
            ("incomplete_body", "HTTP stream interrupted: ", OSError,
             lambda error: {"patches": (adapter(return_value=response(error)),)}),
            ("invalid_content_length", "", ValueError,
             lambda error: {"patches": (adapter(return_value=response()), patch.object(self.download, "advertised_length", side_effect=error))}),
            ("hard_timer_unavailable", "", self.download.HardTimerUnavailable, lambda error: {"arm": error}),
            ("permit_expired", "", OwnershipLost, lambda error: {"arm": error}),
        )
        for code, prefix, exception_type, arrange in scenarios:
            for text, line in exception_texts(exception_type.__name__):
                with self.subTest(code=code, text=text):
                    options = arrange(exception_type(text))
                    error = self.child_error(*options.get("patches", ()), arm=options.get("arm"))
                    self.assertEqual((error.code, error.message), (code, prefix+line))


class DurableRequestAuditTests(unittest.TestCase):
    def test_two_independent_state_clients_cannot_consume_the_same_ordinal(self):
        import threading
        from sec_edgar_ingest.state import AcquisitionState
        from sec_edgar_ingest.storage.contracts import Conflict
        from support import fixture_clock
        with tempfile.TemporaryDirectory() as directory:
            root, clock, barrier = Path(directory), fixture_clock(), threading.Barrier(2)
            stores = [store_bundle(root, clock=clock)[0] for _ in range(2)]
            class RacingStore:
                def __init__(self, store):
                    self.store = store
                def __getattr__(self, name):
                    return getattr(self.store, name)
                def insert(self, kind, key, value):
                    if kind == "TransportAttempt":
                        barrier.wait(2)
                    return self.store.insert(kind, key, value)
            states = [AcquisitionState(RacingStore(store), clock=clock) for store in stores]
            context, url, results = fixture_context(), fixture_source().canonical_url, []
            def begin(state, identifier):
                try:
                    state.begin_request(context, url, None, identifier, 1)
                    results.append("inserted")
                except Conflict:
                    results.append("consumed")
            threads = [threading.Thread(target=begin, args=(state, f"racer-{ordinal}")) for ordinal,state in enumerate(states)]
            try:
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(3)
                    self.assertFalse(thread.is_alive())
                self.assertCountEqual(results, ["inserted", "consumed"])
                row, = states[0].request_history(context, url)
                self.assertEqual(row.value["ordinal"], 1)
                self.assertIsNone(row.value["receipt"])
            finally:
                for store in stores:
                    store.close()

    def test_scripted_azure_routes_transport_to_attempts_and_run_halt_to_source_state(self):
        from test_azure_contracts import AzureContractTests, response
        fixture = AzureContractTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        store, transport = fixture.tables([response(204), response(204)])
        store.insert("TransportAttempt", "ordinal", {"outcome": "uncertain"})
        store.insert("RunHalt", "run", {"outcome": "halted"})
        self.assertIn("/Attempts", transport.requests[0].url)
        self.assertIn("/SourceState", transport.requests[1].url)
        self.assertTrue(all(request.method == "POST" for request in transport.requests))
