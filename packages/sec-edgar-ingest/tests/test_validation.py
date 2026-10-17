import hashlib
import importlib
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from support import body_receipt, fixture_settings, fixture_source, retained_path, retain_download_evidence, zip_bytes

RAW = Path(__file__).parent / "fixtures/raw"


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("sec_edgar_ingest.validation"),
                             "Task 5 requires strict original-byte acquisition envelopes")
        self.validation = importlib.import_module("sec_edgar_ingest.validation")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.settings = fixture_settings()

    def validate(self, body, *, kind="quarterly", headers=None, complete=True, error=None, settings=None):
        source = fixture_source() if kind == "quarterly" else fixture_source("2026-10-01", "daily")
        receipt = replace(body_receipt(self.root, body, headers=headers, complete=complete, error=error), url=source.canonical_url)
        return self.validation.validate_envelope(source, receipt, settings or self.settings)

    def invalid(self, name, body, code, *, kind="quarterly", **options):
        try:
            self.validate(body, kind=kind, **options)
        except Exception as error:
            self.assertIsInstance(error, self.validation.ValidationError, "invalid envelopes must expose their original receipt")
            self.assertEqual(error.code, code)
            self.assertEqual(error.receipt.temporary_path.read_bytes(), body)
            self.assertEqual(error.receipt.sha256, hashlib.sha256(body).hexdigest())
            retain_download_evidence(name, error.receipt, code)
        else:
            self.fail("invalid envelope was accepted: "+name)

    def test_synthetic_daily_and_archive_original_bytes_validate(self):
        for final_newline in (True, False):
            for kind in ("quarterly", "daily"):
                with self.subTest(kind=kind, final_newline=final_newline):
                    text = (RAW / (kind+".idx")).read_bytes()
                    if not final_newline:
                        text = text.rstrip(b"\r\n")
                    body = zip_bytes(text) if kind == "quarterly" else text
                    valid = self.validate(body, kind=kind, headers={"Content-Length": str(len(body))})
                    self.assertEqual(valid.receipt.temporary_path.read_bytes(), body)
                    self.assertEqual(valid.expanded_byte_count, len(text))
                    self.assertEqual(valid.envelope_version, "sec-"+kind+"-envelope-v1")

    def test_all_ten_hash_checked_retained_originals_validate(self):
        evidence = "specs/evidence/sec-filing-index-ingestion/stage-1"
        audit = json.loads((Path(__file__).parent / "fixtures/retained-manifest.json").read_text())
        self.assertEqual(audit["schema_version"], "sec-retained-fixture-manifest-v1")
        self.assertEqual(len(audit["records"]), 83)
        provenance = audit["provenance"]
        self.assertEqual(provenance["finding"]["sha256"], "939a724eccf22147015a59d5940ed57f02cc4e9fe9d942a9cd78ae73c34615ff")
        self.assertEqual(provenance["accepted_manifest"]["sha256"], "124e96041548daba8216aa495fc69021751555b0f0e4c890ac85e934f512a131")
        for record in provenance.values():
            self.assertEqual(hashlib.sha256(retained_path(record["path"]).read_bytes()).hexdigest(), record["sha256"])
        accepted = json.loads(retained_path(provenance["accepted_manifest"]["path"]).read_text())
        accepted_records = {item["path"]: item for item in accepted["records"]}
        expected = {item["path"]: item for item in audit["records"]}
        for record in audit["records"]:
            self.assertEqual(record, accepted_records[record["path"]])
            raw = retained_path(record["path"]).read_bytes()
            self.assertEqual(len(raw), record["bytes"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), record["sha256"])
        matrix_path = evidence + "/specimens/matrix.json"
        original = retained_path(matrix_path).read_bytes()
        self.assertEqual(hashlib.sha256(original).hexdigest(), expected[matrix_path]["sha256"])
        matrix = json.loads(original)
        retained_hashes = {}
        def find_hashes(value):
            if isinstance(value, dict):
                if "receipt_id" in value and "body_sha256" in value:
                    retained_hashes[value["receipt_id"]] = value["body_sha256"]
                for child in value.values():
                    find_hashes(child)
            elif isinstance(value, list):
                for child in value:
                    find_hashes(child)
        find_hashes(matrix)
        for ordinal in range(141, 151):
            receipt_id = f"SEC-{ordinal:04d}"
            with self.subTest(receipt_id=receipt_id):
                path = evidence + f"/listings/{receipt_id}.body"
                body = retained_path(path).read_bytes()
                digest = hashlib.sha256(body).hexdigest()
                accepted = expected[path]
                self.assertEqual(digest, accepted["sha256"])
                self.assertEqual(len(body), accepted["bytes"])
                self.assertIn(digest, original.decode(), "matrix must name each exact original hash")
                headers_path = evidence + f"/listings/{receipt_id}.headers.json"
                headers_bytes = retained_path(headers_path).read_bytes()
                self.assertEqual(hashlib.sha256(headers_bytes).hexdigest(), expected[headers_path]["sha256"])
                sidecar = json.loads(headers_bytes)
                headers = dict(sidecar["response_headers"] if "response_headers" in sidecar else sidecar["headers"])
                kind = "quarterly" if ordinal <= 145 else "daily"
                valid = self.validate(body, kind=kind, headers=headers)
                self.assertEqual(valid.receipt.sha256, digest)
                self.assertEqual(valid.receipt.temporary_path.read_bytes(), body)

    def test_nonempty_complete_entity_and_length_are_required(self):
        text = (RAW / "daily.idx").read_bytes()
        self.invalid("empty", b"", "empty_body", kind="daily")
        self.invalid("incomplete", text[:-4], "incomplete_transport", kind="daily", complete=False)
        self.invalid("length-mismatch", text, "content_length_mismatch", kind="daily", headers={"Content-Length": str(len(text)+1)})
        self.invalid("length-invalid", text, "invalid_content_length", kind="daily", headers={"Content-Length": "-1"})
        self.invalid("unsupported-encoding", text, "unsupported_content_encoding", kind="daily", headers={"Content-Encoding": "gzip"})
        self.invalid("ambiguous-framing", text, "ambiguous_transfer_framing", kind="daily", headers={"Content-Length": str(len(text)), "Transfer-Encoding": "chunked"})

    def test_html_denial_and_error_pages_never_validate_as_index(self):
        for name, body in (("denial", (RAW / "denial.html").read_bytes()), ("html", b"<html>not an index</html>"), ("error", b"Error: unavailable")):
            with self.subTest(name=name):
                self.invalid(name, body, "unexpected_page" if name != "error" else "missing_header", kind="daily")
        self.invalid("html-content-type", (RAW / "daily.idx").read_bytes(), "unsupported_content_type", kind="daily", headers={"Content-Type": "text/html"})

    def test_selected_header_ascii_and_line_endings_are_exact(self):
        daily = (RAW / "daily.idx").read_bytes()
        quarterly = (RAW / "quarterly.idx").read_bytes()
        cases = [
            ("daily-wrong-header", daily.replace(b"File Name", b"Filename"), "missing_header", "daily"),
            ("quarter-wrong-header", zip_bytes(quarterly.replace(b"Filename", b"File Name")), "missing_header", "quarterly"),
            ("daily-crlf", daily.replace(b"\n", b"\r\n"), "invalid_line_endings", "daily"),
            ("quarter-lf", zip_bytes(quarterly.replace(b"\r\n", b"\n")), "invalid_line_endings", "quarterly"),
            ("daily-nonascii", daily+b"\xff", "non_ascii", "daily"),
            ("quarter-nul", zip_bytes(quarterly+b"\x00"), "invalid_text_control", "quarterly"),
            ("header-only", daily.split(b"\n")[0], "header_without_data", "daily"),
            ("header-separator-only", daily.split(b"\n")[0]+b"\n--------\n", "header_without_data", "daily"),
        ]
        for name, body, code, kind in cases:
            with self.subTest(name=name):
                self.invalid(name, body, code, kind=kind)

    def test_row_syntax_is_left_for_later_parser(self):
        body = b"CIK|Company Name|Form Type|Date Filed|File Name\nthis is not a normalized row"
        self.assertEqual(self.validate(body, kind="daily").expanded_byte_count, len(body))

    def test_archive_shapes_truncation_and_crc_failure_are_retained(self):
        text = (RAW / "quarterly.idx").read_bytes()
        original = zip_bytes(text)
        self.invalid("zip-truncated", original[:-20], "invalid_archive")
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("master.idx", text)
        self.invalid("zip-stored", stream.getvalue(), "unsupported_archive")
        for name in ("../master.idx", "nested/master.idx", "other.idx"):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(name, text)
            self.invalid("zip-name-"+name.replace("/", "-"), stream.getvalue(), "unsupported_archive")
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("master.idx", text)
            archive.writestr("extra.idx", text)
        self.invalid("zip-extra-member", stream.getvalue(), "unsupported_archive")
        corrupted = bytearray(original)
        central = corrupted.index(b"PK\x01\x02")
        corrupted[central+16] ^= 1
        self.invalid("zip-bad-crc", bytes(corrupted), "invalid_archive")
        invalid_deflate = bytearray(original)
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            member = archive.infolist()[0]
            compressed_start = member.header_offset+30+len(member.filename.encode())+len(member.extra)
        invalid_deflate[compressed_start] = 255
        self.invalid("zip-bad-deflate", bytes(invalid_deflate), "invalid_archive")
        encrypted = bytearray(original)
        encrypted[6] |= 1
        encrypted[central+8] |= 1
        self.invalid("zip-encrypted", bytes(encrypted), "unsupported_archive")

    def test_forged_expanded_size_and_prefix_crc_cannot_hide_deflate_suffix(self):
        import zlib
        text = (RAW / "quarterly.idx").read_bytes()
        archive = bytearray(zip_bytes(text+b"hidden expanded suffix"*100))
        central = archive.index(b"PK\x01\x02")
        checksum = zlib.crc32(text).to_bytes(4, "little")
        archive[14:18] = checksum
        archive[22:26] = len(text).to_bytes(4, "little")
        archive[central+16:central+20] = checksum
        archive[central+24:central+28] = len(text).to_bytes(4, "little")
        self.invalid("zip-forged-prefix-crc", bytes(archive), "invalid_archive")

    def test_full_deflate_end_marker_is_required_even_with_matching_size_and_crc(self):
        text = (RAW / "quarterly.idx").read_bytes()
        original = zip_bytes(text)
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            member = archive.infolist()[0]
            start = member.header_offset+30+len(member.filename.encode())+len(member.extra)
        truncated = bytearray(original)
        del truncated[start+member.compress_size-1]
        central = truncated.index(b"PK\x01\x02")
        truncated[18:22] = (member.compress_size-1).to_bytes(4, "little")
        truncated[central+20:central+24] = (member.compress_size-1).to_bytes(4, "little")
        end = truncated.index(b"PK\x05\x06")
        truncated[end+16:end+20] = central.to_bytes(4, "little")
        self.invalid("zip-missing-deflate-eof", bytes(truncated), "invalid_archive")

    def test_received_and_expanded_caps_refuse_one_byte_past_guard(self):
        daily = (RAW / "daily.idx").read_bytes()
        settings = fixture_settings(http={"max_received_bytes": len(daily)})
        self.assertEqual(self.validate(daily, kind="daily", settings=settings).expanded_byte_count, len(daily))
        self.invalid("received-cap-plus-one", daily+b"x", "received_limit", kind="daily", settings=settings)
        quarterly = (RAW / "quarterly.idx").read_bytes()
        settings = fixture_settings(http={"max_expanded_bytes": len(quarterly)})
        self.assertEqual(self.validate(zip_bytes(quarterly), settings=settings).expanded_byte_count, len(quarterly))
        self.invalid("expanded-cap-plus-one", zip_bytes(quarterly+b"x"), "expanded_limit", settings=settings)

    def test_accepted_guard_values_refuse_advertised_limit_plus_one(self):
        daily = (RAW / "daily.idx").read_bytes()
        self.invalid("advertised-64mib-plus-one", daily, "received_limit", kind="daily", headers={"Content-Length": "67108865"})
        archive = bytearray(zip_bytes((RAW / "quarterly.idx").read_bytes()))
        central = archive.index(b"PK\x01\x02")
        archive[central+24:central+28] = (536870913).to_bytes(4, "little")
        self.invalid("declared-expanded-512mib-plus-one", bytes(archive), "expanded_limit")

    def test_receipt_hash_and_file_count_are_checked(self):
        source = fixture_source("2026-10-01", "daily")
        receipt = replace(body_receipt(self.root, (RAW / "daily.idx").read_bytes()), url=source.canonical_url)
        for changed in (replace(receipt, sha256="0"*64), replace(receipt, byte_count=receipt.byte_count+1)):
            with self.subTest(receipt=changed), self.assertRaises(self.validation.ValidationError) as raised:
                self.validation.validate_envelope(source, changed, self.settings)
            self.assertEqual(raised.exception.code, "receipt_mismatch")
            retain_download_evidence("receipt-mismatch-"+("hash" if changed.sha256 != receipt.sha256 else "count"), raised.exception.receipt, "receipt_mismatch")
