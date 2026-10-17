import hashlib
import importlib
import importlib.util
import unittest


ORIGIN = "https://www.sec.gov/Archives/edgar/"


class UrlTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("sec_edgar_ingest.urls"),
                             "Unsafe URLs must be refused before acquisition")
        self.urls = importlib.import_module("sec_edgar_ingest.urls")

    def test_source_shapes_and_stable_identity(self):
        quarterly = ORIGIN + "full-index/2015/QTR1/master.zip"
        daily = ORIGIN + "daily-index/2024/QTR1/master.20240229.idx"
        self.assertEqual(self.urls.canonical_source_url(quarterly, "quarterly"), quarterly)
        self.assertEqual(self.urls.canonical_source_url(daily, "daily"), daily)
        self.assertEqual(self.urls.source_id(quarterly), hashlib.sha256(quarterly.encode()).hexdigest())
        self.assertEqual(self.urls.source_id(quarterly), self.urls.source_id(quarterly))
        self.assertEqual(self.urls.canonical_source_url(quarterly.replace("www.sec.gov", "WWW.SEC.GOV"), "quarterly"), quarterly)

    def test_unsafe_source_matrix(self):
        path = "full-index/2015/QTR1/master.zip"
        cases = [
            ("http", ORIGIN.replace("https", "http") + path, "quarterly"),
            ("foreign host", ORIGIN.replace("www.sec.gov", "evil.sec.gov") + path, "quarterly"),
            ("userinfo", ORIGIN.replace("www.sec.gov", "user:password@www.sec.gov") + path, "quarterly"),
            ("port", ORIGIN.replace("www.sec.gov", "www.sec.gov:443") + path, "quarterly"),
            ("query", ORIGIN + path + "?q=1", "quarterly"),
            ("fragment", ORIGIN + path + "#x", "quarterly"),
            ("dot", ORIGIN + "full-index/2015/./QTR1/master.zip", "quarterly"),
            ("encoded parent", ORIGIN + "full-index/2015/%2e%2e/QTR1/master.zip", "quarterly"),
            ("encoded slash", ORIGIN + "full-index/2015%2fQTR1/master.zip", "quarterly"),
            ("encoded backslash", ORIGIN + "full-index/2015%5cQTR1/master.zip", "quarterly"),
            ("control", ORIGIN + "full-index/2015/QTR1/master.zip%00", "quarterly"),
            ("newline", ORIGIN + "full-index/2015/QTR1/\nmaster.zip", "quarterly"),
            ("filing content", ORIGIN + "data/123/abc.txt", "daily"),
            ("case sensitive", ORIGIN + path.replace("QTR1", "qtr1"), "quarterly"),
            ("wrong kind", ORIGIN + path, "daily"),
            ("wrong file", ORIGIN + path.replace("master.zip", "company.zip"), "quarterly"),
            ("invalid quarter", ORIGIN + path.replace("QTR1", "QTR5"), "quarterly"),
            ("invalid day", ORIGIN + "daily-index/2023/QTR1/master.20230229.idx", "daily"),
            ("day outside quarter", ORIGIN + "daily-index/2024/QTR2/master.20240229.idx", "daily"),
            ("double encoding", ORIGIN + "full-index/2015/%252e%252e/QTR1/master.zip", "quarterly"),
        ]
        for name, url, kind in cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.urls.canonical_source_url(url, kind)

    def test_listing_hierarchy_and_immediate_children(self):
        root = ORIGIN + "full-index/index.json"
        year = self.urls.child_url(root, "2015/", "2015", True)
        self.assertEqual(year, ORIGIN + "full-index/2015/")
        quarter = self.urls.child_url(year + "index.json", "QTR1/", "QTR1", True)
        self.assertEqual(quarter, ORIGIN + "full-index/2015/QTR1/")
        source = self.urls.child_url(quarter + "index.json", "master.zip", "master.zip", False)
        self.assertEqual(source, quarter + "master.zip")
        self.assertEqual(self.urls.canonical_listing_url(root), root)
        self.assertEqual(self.urls.canonical_listing_url(quarter + "index.json"), quarter + "index.json")

    def test_conflicting_or_escaping_child_is_refused(self):
        parent = ORIGIN + "full-index/2015/QTR1/index.json"
        cases = [
            ("parent metadata", "../", "..", True),
            ("foreign absolute", "https://evil.test/master.zip", "master.zip", False),
            ("escape absolute", ORIGIN + "full-index/2016/QTR1/master.zip", "master.zip", False),
            ("escape relative", "../QTR2/master.zip", "master.zip", False),
            ("name conflict", "company.zip", "master.zip", False),
            ("encoded name", "%6daster.zip", "master.zip", False),
            ("nested child", "nested/master.zip", "master.zip", False),
            ("query", "master.zip?q=1", "master.zip", False),
            ("name separator", "master.zip", "nested/master.zip", False),
            ("directory flag", "master.zip", "master.zip", True),
            ("file flag", "QTR1/", "QTR1", False),
            ("filing content", "/Archives/edgar/data/1/a.txt", "a.txt", False),
        ]
        for name, href, child, directory in cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.urls.child_url(parent, href, child, directory)
