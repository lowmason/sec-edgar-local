import copy
import importlib
import importlib.util
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from support import fixture_context, fixture_settings, fixture_source, fixture_workset


class WorksetTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("sec_edgar_ingest.worksets"),
                             "Immutable workset identity must be enforced")
        self.worksets = importlib.import_module("sec_edgar_ingest.worksets")
        self.models = importlib.import_module("sec_edgar_ingest.models")

    def snapshot(self, source, digest="b" * 64):
        envelope = (self.models.QUARTERLY_ENVELOPE_VERSION if source.kind == "quarterly"
                    else self.models.DAILY_ENVELOPE_VERSION)
        raw_path = (f"raw/sec/indexes/kind={source.kind}/period={source.period}/"
                    f"sha256={digest}/master.{source.representation}")
        return self.models.Snapshot(source.source_id, digest, raw_path, 12,
                                   fixture_context().started_at, {"etag": "abc"}, source.representation, envelope)

    def tamper(self, workset, edit, decoder=None):
        value = json.loads(self.worksets.encode_workset(workset))
        edit(value)
        value["workset_id"] = self.worksets.workset_digest({key: item for key, item in value.items() if key != "workset_id"})
        with self.assertRaises(ValueError):
            (decoder or self.worksets.decode_source_workset)(self.worksets.canonical_json(value))

    def test_member_order_does_not_change_workset_identity(self):
        a, b = fixture_source("2015Q1"), fixture_source("2015Q2")
        first = fixture_workset((a, b))
        second = fixture_workset((b, a))
        self.assertEqual(first.workset_id, second.workset_id)
        self.assertEqual(self.worksets.decode_source_workset(self.worksets.encode_workset(first)), first)
        changed = replace(first, pinned_end_quarter="2026Q3")
        with self.assertRaisesRegex(ValueError, "identity"):
            self.worksets.decode_source_workset(self.worksets.encode_workset(changed))

    def test_changed_context_or_content_changes_identity(self):
        source = fixture_source()
        first = fixture_workset((source,))
        changed = self.worksets.make_source_workset(replace(first.context, execution_id="different"),
                  first.pinned_end_quarter, first.discovery_id, first.members, first.directories, first.overlap_from)
        self.assertNotEqual(first.workset_id, changed.workset_id)
        refreshed = self.worksets.make_source_workset(first.context,
                  first.pinned_end_quarter, first.discovery_id, first.members, first.directories, first.overlap_from,
                  acquisition_mode="refresh")
        self.assertEqual(refreshed.acquisition_mode, "refresh")
        self.assertNotEqual(first.workset_id, refreshed.workset_id)
        one = self.worksets.make_snapshot_workset(first, (self.snapshot(source),))
        two = self.worksets.make_snapshot_workset(first, (self.snapshot(source, "c" * 64),))
        self.assertNotEqual(one.workset_id, two.workset_id)
        self.assertEqual(self.worksets.decode_snapshot_workset(self.worksets.encode_workset(one)), one)

    def test_detached_serializers_and_deep_immutability(self):
        source = fixture_source()
        workset = fixture_workset((source,))
        context_mapping = workset.context.to_mapping()
        context_mapping["effective_config"]["sec"]["user_agent"] = "mutated"
        self.assertEqual(workset.context.effective_config["sec"]["requests_per_second"], 3)
        with self.assertRaises(TypeError):
            workset.context.effective_config["sec"]["requests_per_second"] = 9
        with self.assertRaises(FrozenInstanceError):
            source.period = "changed"
        error_input = {"nested": {"items": ["first"]}}
        error = self.models.Error("guard", "rejected", False, source.source_id, error_input)
        error_input["nested"]["items"].append("second")
        self.assertEqual(error.details["nested"]["items"], ("first",))
        with self.assertRaises(TypeError):
            error.details["nested"]["new"] = True
        exported = error.to_mapping()
        exported["details"]["nested"]["items"].append("third")
        self.assertEqual(error.details["nested"]["items"], ("first",))
        snapshot = self.snapshot(source)
        with self.assertRaises(TypeError):
            snapshot.validators["etag"] = "changed"

    def test_duplicate_sources_and_directory_identity_are_refused(self):
        source = fixture_source()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            fixture_workset((source, source))
        workset = fixture_workset((source,))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.worksets.make_source_workset(workset.context, workset.pinned_end_quarter, workset.discovery_id,
                                             workset.members, workset.directories * 2, workset.overlap_from)
        self.tamper(workset, lambda value: value["directories"][0].update(source_ids=[]))
        self.tamper(workset, lambda value: value["members"][0].update(source_id="d" * 64))

    def test_empty_complete_requires_successful_directory_evidence(self):
        empty = fixture_workset(())
        self.assertTrue(empty.discovery_complete)
        self.assertEqual(self.worksets.decode_source_workset(self.worksets.encode_workset(empty)), empty)
        failed = fixture_workset((), discovery_complete=False)
        self.assertFalse(failed.discovery_complete)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.worksets.make_snapshot_workset(failed, ())
        self.tamper(empty, lambda value: value.update(directories=[]))
        self.tamper(failed, lambda value: value.update(discovery_complete=True))

    def test_decoder_rejects_versions_unknown_fields_timestamps_and_hashes(self):
        workset = fixture_workset((fixture_source(),))
        cases = [
            ("version", lambda value: value.update(format_version="sec-acquisition-v2")),
            ("unknown", lambda value: value.update(latest="current")),
            ("naive UTC", lambda value: value["context"].update(started_at="2026-10-06T00:00:00")),
            ("offset UTC", lambda value: value["context"].update(started_at="2026-10-06T01:00:00+01:00")),
            ("schema", lambda value: value["context"].update(schema_version="sec-index-v2")),
            ("config SHA", lambda value: value["context"].update(config_sha256="f" * 64)),
            ("nonhex", lambda value: value["directories"][0].update(listing_sha256="Z" * 64)),
            ("unpinned", lambda value: value.update(pinned_end_quarter="open")),
            ("future", lambda value: value.update(pinned_end_quarter="2027Q1")),
            ("mutable config", lambda value: value["context"]["effective_config"]["sec"].update(requests_per_second=8)),
        ]
        for name, edit in cases:
            with self.subTest(name=name):
                self.tamper(workset, edit)
        body = self.worksets.encode_workset(workset)
        with self.assertRaises(ValueError):
            self.worksets.decode_source_workset(body.replace(b'"format_version":', b'"format_version":"sec-acquisition-v1","format_version":'))
        with self.assertRaises(ValueError):
            self.worksets.decode_source_workset(b'{"value":NaN}')

    def test_snapshot_requires_exact_members_and_immutable_raw_reference(self):
        a, b = fixture_source("2015Q1"), fixture_source("2015Q2")
        source = fixture_workset((a, b))
        with self.assertRaisesRegex(ValueError, "member"):
            self.worksets.make_snapshot_workset(source, (self.snapshot(a),))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.worksets.make_snapshot_workset(source, (self.snapshot(a), self.snapshot(a)))
        with self.assertRaises(ValueError):
            self.snapshot(a, "not-a-hash")
        with self.assertRaises(ValueError):
            replace(self.snapshot(a), raw_path="raw/latest/master.zip")
        with self.assertRaises(ValueError):
            replace(self.snapshot(a), raw_path="../raw/" + "b" * 64)
        with self.assertRaises(ValueError):
            replace(self.snapshot(a), representation="idx")
        snapshot = self.worksets.make_snapshot_workset(source, (self.snapshot(b), self.snapshot(a)))
        self.assertEqual(snapshot.source_workset_id, source.workset_id)
        self.assertEqual(snapshot.directories, source.directories)
        self.assertEqual(snapshot.overlap_from, source.overlap_from)
        self.assertEqual(snapshot.pinned_end_quarter, source.pinned_end_quarter)
        self.tamper(snapshot, lambda value: value["snapshots"].pop(), self.worksets.decode_snapshot_workset)
        self.tamper(snapshot, lambda value: value["snapshots"][0].update(raw_path="raw/latest"), self.worksets.decode_snapshot_workset)

    def test_snapshot_decoder_rejects_rehashed_wrong_source_period(self):
        cases = [(fixture_source("2015Q1"), "2015Q1", "2015Q2"),
                 (fixture_source("2026-10-01", "daily"), "2026-10-01", "2026-10-02"),
                 (fixture_source("2026-10-01", "daily"), "2026-10-01", "2026-09-30")]
        for source, original, wrong in cases:
            with self.subTest(kind=source.kind, wrong_period=wrong):
                workset = self.worksets.make_snapshot_workset(fixture_workset((source,)), (self.snapshot(source),))
                self.tamper(workset, lambda value: value["snapshots"][0].update(
                    raw_path=value["snapshots"][0]["raw_path"].replace("period=" + original, "period=" + wrong)),
                    self.worksets.decode_snapshot_workset)

    def test_snapshot_decoder_rejects_rehashed_wrong_directory_or_source_identity(self):
        source = fixture_source("2015Q1")
        other = fixture_source("2015Q2")
        workset = self.worksets.make_snapshot_workset(fixture_workset((source,)), (self.snapshot(source),))
        def wrong_identity(value):
            value["snapshots"][0]["source_id"] = other.source_id
            value["directories"][0]["source_ids"] = [other.source_id]
        cases = [("source identity", wrong_identity),
                 ("directory period", lambda value: value["directories"][0].update(period="2015Q2")),
                 ("directory address", lambda value: value["directories"][0].update(
                     url=value["directories"][0]["url"].replace("QTR1", "QTR2")))]
        for name, edit in cases:
            with self.subTest(name=name):
                self.tamper(workset, edit, self.worksets.decode_snapshot_workset)

    def test_snapshot_decoder_rejects_rehashed_kind_and_envelope_mismatch(self):
        source = fixture_source("2015Q1")
        workset = self.worksets.make_snapshot_workset(fixture_workset((source,)), (self.snapshot(source),))
        cases = [("kind", lambda value: value["snapshots"][0].update(
                    raw_path=value["snapshots"][0]["raw_path"].replace("kind=quarterly", "kind=daily")
                        .replace("period=2015Q1", "period=2015-01-01").replace("master.zip", "master.idx"),
                    representation="idx", envelope_version="sec-daily-envelope-v1")),
                 ("envelope", lambda value: value["snapshots"][0].update(envelope_version="sec-daily-envelope-v1"))]
        for name, edit in cases:
            with self.subTest(name=name):
                self.tamper(workset, edit, self.worksets.decode_snapshot_workset)

    def test_daily_directory_day_label_round_trips_multiple_exact_sources(self):
        sources = (fixture_source("2026-10-01", "daily"), fixture_source("2026-10-02", "daily"))
        try:
            source_workset = fixture_workset(sources)
        except ValueError as error:
            self.fail(f"retained daily directory day label must remain compatible: {error}")
        self.assertEqual(source_workset.directories[0].period, "2026-10-01")
        snapshots = self.worksets.make_snapshot_workset(source_workset, tuple(self.snapshot(source) for source in sources))
        body = self.worksets.encode_workset(snapshots)
        decoded = self.worksets.decode_snapshot_workset(body)
        self.assertEqual(decoded, snapshots)
        self.assertEqual(self.worksets.encode_workset(decoded), body)

    def test_common_records_have_complete_detached_mapping_round_trips(self):
        context = fixture_context()
        source = fixture_source()
        error = self.models.Error("failure", "details", True, source.source_id, {"nested": [1]})
        records = [
            source, context, error, self.snapshot(source),
            self.models.Binding("a" * 64, source.source_id, "b" * 64),
            self.models.Versioned({"nested": {"list": [1]}}, 'W/"actual-etag"'),
            self.models.QueueTicket("ticket", "owner", "daily", context.started_at, context.deadline),
            self.models.Permit("owner", 1, "request", context.started_at, context.deadline,
                               context.deadline + timedelta(seconds=2), 10., 100.),
            self.models.BodyReceipt(source.canonical_url, 200, {"ETag": "abc"}, Path("staging/body"),
                                    context.started_at, 12, "b" * 64, True, None),
            self.models.CommandResult(context, "incomplete", None, None, 1, 0, 0, 1, 0, 0,
                                      (error,), context.started_at, context.deadline),
        ]
        records.append(self.models.ValidatedBody(records[-2], "zip", "sec-quarterly-envelope-v1", 20))
        for record in records:
            with self.subTest(record=type(record).__name__):
                self.assertEqual(type(record).from_mapping(record.to_mapping()), record)
        versioned = records[5]
        with self.assertRaises(TypeError):
            versioned.value["nested"]["list"] = ()

    def test_common_records_reject_mutable_wrong_typed_fields(self):
        context = fixture_context()
        constructors = [
            ("context mapping", lambda: replace(fixture_workset(()), context=context.to_mapping())),
            ("mutable members", lambda: replace(fixture_workset(()), members=({"source_id": "a" * 64},))),
            ("mutable errors", lambda: self.models.CommandResult(context, "failure", None, None,
                                     0, 0, 0, 0, 1, 0, ({"code": "bad"},), context.started_at, context.deadline)),
            ("wrong receipt", lambda: self.models.ValidatedBody({"complete": True}, "zip", "sec-quarterly-envelope-v1", 1)),
        ]
        for name, constructor in constructors:
            with self.subTest(name=name):
                try:
                    constructor()
                except Exception as error:
                    self.assertIsInstance(error, ValueError, "invalid typed record must report a contract error")
                else:
                    self.fail("invalid typed record accepted")
        workset = fixture_workset((fixture_source(),))
        self.assertEqual(copy.deepcopy(workset), workset)

    def test_version_and_directory_content_are_part_of_identity(self):
        first = fixture_workset((fixture_source(),))
        changed_directory = replace(first.directories[0], listing_sha256="d" * 64)
        second = self.worksets.make_source_workset(first.context, first.pinned_end_quarter, first.discovery_id,
                    first.members, (changed_directory,), first.overlap_from)
        self.assertNotEqual(first.workset_id, second.workset_id)
        settings = fixture_settings(etl={"parser_version": "fixture-envelope-v2"})
        context = replace(first.context, parser_version=settings.etl.parser_version,
                          config_sha256=settings.config_sha256)
        config = importlib.import_module("sec_edgar_ingest.config")
        context = config.pin_context(settings, context, context.started_at.date())[0]
        third = self.worksets.make_source_workset(context, first.pinned_end_quarter, first.discovery_id,
                                                 first.members, first.directories, first.overlap_from)
        self.assertNotEqual(first.workset_id, third.workset_id)

    def test_body_receipt_and_snapshot_envelopes_are_explicit(self):
        source = fixture_source()
        snapshot = self.snapshot(source)
        self.assertEqual(snapshot.envelope_version, "sec-quarterly-envelope-v1")
        for name, changes in [
            ("unknown envelope", {"envelope_version": "latest"}),
            ("wrong representation envelope", {"envelope_version": "sec-daily-envelope-v1"}),
            ("wrong timestamp", {"received_at": datetime(2026, 10, 6)}),
        ]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                replace(snapshot, **changes)
        workset = fixture_workset((source,))
        with self.assertRaises(ValueError):
            self.worksets.decode_source_workset(self.worksets.encode_workset(workset).decode().encode("utf-16"))

    def test_approved_raw_layout_round_trips_both_representations(self):
        cases = [
            (fixture_source("2015Q1"), "master.zip", "sec-quarterly-envelope-v1"),
            (fixture_source("2024-02-29", "daily"), "master.idx", "sec-daily-envelope-v1"),
        ]
        for source, filename, envelope in cases:
            with self.subTest(kind=source.kind):
                digest = "b" * 64
                raw_path = (f"raw/sec/indexes/kind={source.kind}/period={source.period}/"
                            f"sha256={digest}/{filename}")
                try:
                    snapshot = self.models.Snapshot(source.source_id, digest, raw_path, 12,
                               fixture_context().started_at, {"etag": "abc"}, source.representation, envelope)
                except ValueError as error:
                    self.fail(f"approved raw path rejected: {error}")
                self.assertEqual(self.models.Snapshot.from_mapping(snapshot.to_mapping()), snapshot)
                workset = self.worksets.make_snapshot_workset(fixture_workset((source,)), (snapshot,))
                self.assertEqual(self.worksets.decode_snapshot_workset(self.worksets.encode_workset(workset)), workset)

    def test_approved_raw_layout_rejects_unsafe_or_mismatched_content_addresses(self):
        source = fixture_source()
        snapshot = self.snapshot(source)
        root = "raw/sec/indexes/kind=quarterly/period=2015Q1/"
        cases = [
            ("different hash", root + "sha256=" + "c" * 64 + "/master.zip"),
            ("nonhex hash", root + "sha256=" + "Z" * 64 + "/master.zip"),
            ("missing hash label", root + "b" * 64 + "/master.zip"),
            ("wrong kind", root.replace("quarterly", "daily") + "sha256=" + "b" * 64 + "/master.zip"),
            ("invalid period", root.replace("2015Q1", "2015Q5") + "sha256=" + "b" * 64 + "/master.zip"),
            ("absolute path", "/" + root + "sha256=" + "b" * 64 + "/master.zip"),
            ("parent escape", "../" + root + "sha256=" + "b" * 64 + "/master.zip"),
            ("encoded escape", root + "sha256=" + "b" * 64 + "/%2e%2e/master.zip"),
            ("mutable latest", root + "sha256=latest/master.zip"),
            ("wrong file", root + "sha256=" + "b" * 64 + "/company.zip"),
        ]
        for name, raw_path in cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                replace(snapshot, raw_path=raw_path)

    def test_discover_freezes_explicit_mode_without_rewriting_command(self):
        source = fixture_source()
        original = fixture_workset((source,))
        context = fixture_context(command="discover")
        try:
            reused = self.worksets.make_source_workset(context, original.pinned_end_quarter,
                      original.discovery_id, original.members, original.directories, original.overlap_from,
                      acquisition_mode="reuse_accepted")
            refreshed = self.worksets.make_source_workset(context, original.pinned_end_quarter,
                         original.discovery_id, original.members, original.directories, original.overlap_from,
                         acquisition_mode="refresh")
        except TypeError as error:
            self.fail(f"discover cannot freeze its explicit acquisition mode: {error}")
        self.assertEqual(reused.context.command, "discover")
        self.assertEqual(refreshed.context.command, "discover")
        self.assertEqual(reused.acquisition_mode, "reuse_accepted")
        self.assertEqual(refreshed.acquisition_mode, "refresh")
        self.assertNotEqual(reused.workset_id, refreshed.workset_id)
        snapshot_worksets = []
        for workset in (reused, refreshed):
            self.assertEqual(self.worksets.decode_source_workset(self.worksets.encode_workset(workset)), workset)
            snapshots = self.worksets.make_snapshot_workset(workset, (self.snapshot(source),))
            self.assertEqual(snapshots.context.command, "discover")
            self.assertEqual(snapshots.acquisition_mode, workset.acquisition_mode)
            self.assertEqual(self.worksets.decode_snapshot_workset(self.worksets.encode_workset(snapshots)), snapshots)
            snapshot_worksets.append(snapshots)
        self.assertNotEqual(snapshot_worksets[0].workset_id, snapshot_worksets[1].workset_id)
        with self.assertRaises(ValueError):
            self.worksets.make_source_workset(context, original.pinned_end_quarter, original.discovery_id,
                       original.members, original.directories, original.overlap_from, acquisition_mode="latest")

    def test_open_endpoint_matches_exact_resolution_in_constructor_and_decoders(self):
        source = fixture_source()
        original = fixture_workset((source,))
        with self.subTest(boundary="constructor"), self.assertRaisesRegex(ValueError, "endpoint"):
            self.worksets.make_source_workset(original.context, "2026Q3", original.discovery_id,
                      original.members, original.directories, original.overlap_from)
        with self.subTest(boundary="source decoder"):
            self.tamper(original, lambda value: value.update(pinned_end_quarter="2026Q3"))
        snapshots = self.worksets.make_snapshot_workset(original, (self.snapshot(source),))
        with self.subTest(boundary="snapshot decoder"):
            self.tamper(snapshots, lambda value: value.update(pinned_end_quarter="2026Q3"),
                        self.worksets.decode_snapshot_workset)

    def test_fixture_clock_override_keeps_exact_auditable_endpoint(self):
        original = fixture_workset((fixture_source(),))
        settings = fixture_settings(fixture={"allow_clock_override": True})
        context = replace(original.context, config_sha256=settings.config_sha256)
        config = importlib.import_module("sec_edgar_ingest.config")
        pinning_date = date(2026, 7, 15)
        context, endpoint = config.pin_context(settings, context, pinning_date)
        self.assertEqual(getattr(context, "pinned_on", None), pinning_date,
                         "worksets must retain the actual fixture pinning date")
        self.assertEqual(context.started_at, original.context.started_at)
        self.assertEqual(endpoint, "2026Q3")
        workset = self.worksets.make_source_workset(context, endpoint, original.discovery_id,
                  original.members, original.directories, original.overlap_from)
        self.assertEqual(self.worksets.decode_source_workset(self.worksets.encode_workset(workset)), workset)
        snapshots = self.worksets.make_snapshot_workset(workset, (self.snapshot(original.members[0]),))
        self.assertEqual(snapshots.context.pinned_on, pinning_date)
        self.assertEqual(self.worksets.decode_snapshot_workset(self.worksets.encode_workset(snapshots)), snapshots)
        for wrong in ("2026Q2", "2026Q4"):
            with self.subTest(boundary="constructor", endpoint=wrong), self.assertRaisesRegex(ValueError, "endpoint"):
                self.worksets.make_source_workset(context, wrong, original.discovery_id,
                          original.members, original.directories, original.overlap_from)
            with self.subTest(boundary="source decoder", endpoint=wrong):
                self.tamper(workset, lambda value: value.update(pinned_end_quarter=wrong))
            with self.subTest(boundary="snapshot decoder", endpoint=wrong):
                self.tamper(snapshots, lambda value: value.update(pinned_end_quarter=wrong),
                            self.worksets.decode_snapshot_workset)
        with self.assertRaisesRegex(ValueError, "pinning date"):
            self.worksets.make_source_workset(replace(context, pinned_on=None), endpoint,
                      original.discovery_id, original.members, original.directories, original.overlap_from)
