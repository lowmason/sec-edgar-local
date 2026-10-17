"""Real local competing collectors, held sockets, child death and durable takeover."""
import hashlib
import json
import multiprocessing
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

from support import (CollectionHarness, collection_harness, fixture_source, fixture_workset,
                     retain_acquisition_proof, valid_idx_response)
from sec_edgar_ingest.worksets import encode_workset


class AcquisitionProcessTests(unittest.TestCase):
    def test_real_clock_context_pins_actual_day_after_frozen_fixture_date(self):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from support import fixture_settings, real_context
        from sec_edgar_ingest.config import pin_context
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        settings = fixture_settings()
        context = real_context(SimpleNamespace(now=lambda: now), settings)
        try:
            pinned, _ = pin_context(settings, context, context.pinned_on)
        except ValueError as error:
            self.fail(f'real-clock acquisition fixture must pass the actual-date guard: {error}')
        self.assertEqual(pinned, context)
        self.assertEqual(context.pinned_on, now.date())
        self.assertTrue(settings.fixture is None or not settings.fixture.allow_clock_override)

    def test_three_independent_collectors_barrier_request_and_actual_binding_race(self):
        import support
        self.assertTrue(hasattr(support, 'acquisition_race_entry'), 'Task 8 needs three independent collecting processes and request/binding barriers')
        spawn = multiprocessing.get_context('spawn')
        with tempfile.TemporaryDirectory(prefix='sec-acquisition-race-') as temporary:
            root = Path(temporary)
            source = fixture_source('2026-10-01', 'daily')
            workset = fixture_workset((source,))
            h = collection_harness(root, [])
            h.objects.put_once(h.source_workset_path(workset), encode_workset(workset))
            (root / 'input-workset.json').write_bytes(encode_workset(workset))
            h.close()
            request, staged, binding = (spawn.Barrier(3) for _ in range(3))
            output = spawn.Queue()
            processes = [spawn.Process(target=support.acquisition_race_entry, args=(str(root), str(index), request, staged, binding, output)) for index in range(3)]
            try:
                for process in processes: process.start()
                records = [output.get(timeout=25) for _ in processes]
                for process in processes:
                    process.join(5)
                    self.assertEqual(process.exitcode, 0)
                events = sorted((event for record in records for event in record['events']), key=lambda event: event['monotonic_ns'])
                self.assertEqual(len({event['pid'] for event in events}), 3)
                absent = [event for event in events if event['event'] == 'bind_read_absent']
                inserts = [event for event in events if event['event'] == 'bind_insert_attempt']
                self.assertEqual((len(absent), len(inserts)), (3, 3))
                self.assertLess(max(event['monotonic_ns'] for event in absent), min(event['monotonic_ns'] for event in inserts))
                self.assertEqual(sum(event['event'] == 'bind_insert_success' for event in events), 1)
                self.assertEqual(sum(event['event'] == 'bind_insert_conflict' for event in events), 2)
                starts = [event for event in events if event['event'] == 'request-start']
                ends = [event for event in events if event['event'] == 'request-end']
                self.assertEqual(len(starts), 3)
                for previous, current in zip(starts, starts[1:]):
                    self.assertGreaterEqual((current['monotonic_ns'] - previous['monotonic_ns']) / 1e9, 1 / 3)
                    self.assertLess(next(end['monotonic_ns'] for end in ends if end['request_id'] == previous['request_id']), current['monotonic_ns'])
                self.assertEqual(len({record['result']['snapshot_workset_ref'] for record in records}), 1)
                h = collection_harness(root, [])
                h.forbid_fetch = True
                replay = h.collect(workset)
                self.assertEqual(replay.outcome, 'success')
                self.assertEqual(replay.snapshot_workset_ref, records[0]['result']['snapshot_workset_ref'])
                raw = h.snapshot_workset(replay).snapshots[0]
                body = h.objects.read(raw.raw_path)
                self.assertEqual(hashlib.sha256(body).hexdigest(), raw.sha256)
                proof = {'processes': [{'pid': process.pid, 'exit': process.exitcode} for process in processes],
                         'records': records, 'events': events, 'winner': raw.to_mapping(), 'raw_hex': body.hex(),
                         'workset_hex': h.objects.read(replay.snapshot_workset_ref).hex(), 'replay': replay.to_mapping()}
                retain_acquisition_proof('three-collector-race', proof)
                h.close()
            finally:
                for process in processes:
                    if process.is_alive(): process.terminate(); process.join(2)
                output.close(); output.join_thread()

    def test_held_socket_parent_death_zero_successor_unsafe_interval_and_daily_next(self):
        import support
        self.assertTrue(hasattr(support, 'integrated_takeover_proof'), 'Task 8 needs an integrated held-socket takeover trace')
        proof = support.integrated_takeover_proof()
        retain_acquisition_proof('integrated-takeover', proof)
        self.assertEqual(proof['parent_exit'], -15)
        self.assertEqual(proof['successor_exit'], 0)
        self.assertTrue(proof['zero_successor_through_guard'])
        self.assertGreaterEqual(proof['successor_first_start'], proof['unsafe_until_mono'])
        self.assertGreater(proof['successor_first_start'], proof['old_socket_closed'])
        self.assertEqual(proof['ordered_priorities'][0], 'daily')
        self.assertIn('backfill', proof['ordered_priorities'])
        self.assertEqual(len(proof['all_wire_starts']), 4)
        self.assertEqual(proof['child_alarm_disposition'], 'default-fatal')
        self.assertTrue(proof['old_child_drained'])
        retain_acquisition_proof('integrated-takeover', proof)

    def test_stale_sender_awakened_after_allowed_start_sends_zero(self):
        from support import (SPAWN_ALLOWANCE_SECONDS, LoopbackServer, fixture_settings, loopback_sender, real_context,
                             real_permit, stale_start_child)
        from sec_edgar_ingest.coordination import Clock
        import threading
        with tempfile.TemporaryDirectory(prefix='sec-acquisition-stale-') as temporary:
            server = LoopbackServer(b'never requested')
            try:
                clock = Clock()
                settings = fixture_settings()
                sender = loopback_sender(settings, clock, server.origin, target=stale_start_child, spool=Path(temporary) / 'sender')
                # Only the 1/3 s start window is stale; the deadline outlasts a slow spawn.
                permit = real_permit(clock, seconds=SPAWN_ALLOWANCE_SECONDS + 1)
                receipt = sender.send(server.url, real_context(clock, settings), permit, cancellation=multiprocessing.get_context('spawn').Event())
                self.assertFalse(receipt.complete)
                self.assertEqual(len(server.requests), 0)
                trace = (Path(temporary) / 'sender/transport.jsonl').read_text()
                self.assertNotIn('socket-start', trace)
                retain_acquisition_proof('stale-dispatch', {'receipt': receipt.to_mapping(), 'transport': [json.loads(line) for line in trace.splitlines()], 'server': server.events, 'body_hex': receipt.temporary_path.read_bytes().hex()})
            finally:
                server.close()

    def test_independent_child_deadline_records_actual_fatal_exit_and_prefix(self):
        import signal
        from support import (SPAWN_ALLOWANCE_SECONDS, SPAWN_WAIT_SECONDS, LoopbackServer, fixture_settings,
                             loopback_sender, real_context, real_permit, slow_spawn_child_exchange)
        from sec_edgar_ingest.coordination import Clock
        with tempfile.TemporaryDirectory(prefix='sec-acquisition-deadline-') as temporary:
            server = LoopbackServer(b'x' * 7, mode='trickle')
            try:
                clock = Clock()
                settings = fixture_settings()
                # The child always starts late, so every run shows the start window absorbing a slow spawn;
                # the half second after that window leaves time for a trickled prefix before the fatal timer.
                sender = loopback_sender(settings, clock, server.origin, target=slow_spawn_child_exchange,
                                         spool=Path(temporary) / 'sender')
                permit = real_permit(clock, seconds=SPAWN_ALLOWANCE_SECONDS + 0.5, start_seconds=SPAWN_ALLOWANCE_SECONDS)
                from unittest.mock import patch
                def stalled_supervisor(process, cancellation, deadline, clock):
                    # Never terminate the child: only its own fatal timer may end it.
                    process.join(max(0.0, deadline - clock.monotonic()) + SPAWN_WAIT_SECONDS)
                    if process.is_alive():
                        raise AssertionError('independent child timer failed while supervisor was stalled')
                    return True
                with patch('sec_edgar_ingest.download.wait_for_sender', stalled_supervisor):
                    receipt = sender.send(server.url, real_context(clock, settings), permit, cancellation=multiprocessing.get_context('spawn').Event())
                self.assertFalse(receipt.complete)
                self.assertGreater(receipt.byte_count, 0)
                self.assertTrue(server.closed.wait(SPAWN_WAIT_SECONDS))
                trace = [json.loads(line) for line in (Path(temporary) / 'sender/transport.jsonl').read_text().splitlines()]
                joined = next(event for event in trace if event['event'] == 'child-joined')
                self.assertEqual(joined['exitcode'], -signal.SIGALRM)
                body = receipt.temporary_path.read_bytes()
                self.assertEqual(hashlib.sha256(body).hexdigest(), receipt.sha256)
                retain_acquisition_proof('independent-child-deadline', {'receipt': receipt.to_mapping(), 'transport': trace, 'server': server.events,
                    'body_hex': body.hex(), 'body_sha256': hashlib.sha256(body).hexdigest(), 'child_exit': joined})
            finally:
                server.close()
