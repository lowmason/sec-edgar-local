"""Validate SEC index origins, selected representations, and listing children."""
import hashlib
import re
from datetime import date
from urllib.parse import unquote, urlsplit

SEC_ORIGIN = "https://www.sec.gov"
INDEX_ROOT = "/Archives/edgar/"
YEAR = r"[1-9][0-9]{3}"
QUARTERLY_SOURCE = re.compile(rf"{INDEX_ROOT}full-index/({YEAR})/QTR([1-4])/master\.zip\Z")
DAILY_SOURCE = re.compile(rf"{INDEX_ROOT}daily-index/({YEAR})/QTR([1-4])/master\.([0-9]{{8}})\.idx\Z")
DIRECTORY = re.compile(rf"{INDEX_ROOT}(?:full-index|daily-index)/(?:{YEAR}/(?:QTR[1-4]/)?)?\Z")


def _safe_url_path(url: str) -> str:
    if not isinstance(url, str) or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url):
        raise ValueError("SEC URL must contain no whitespace or control characters")
    try:
        parsed = urlsplit(url)
        valid_origin = (parsed.scheme == "https" and parsed.hostname == "www.sec.gov"
                        and parsed.username is None and parsed.password is None
                        and parsed.port is None and ":" not in parsed.netloc)
    except ValueError as error:
        raise ValueError("invalid SEC origin") from error
    if not valid_origin or parsed.query or parsed.fragment or "?" in url or "#" in url:
        raise ValueError("SEC URL requires the exact HTTPS origin and no credentials, port, query or fragment")
    path = parsed.path
    if not path.startswith(INDEX_ROOT) or "\\" in path:
        raise ValueError("SEC URL must be beneath an accepted index hierarchy")
    for segment in path.split("/")[1:]:
        try:
            decoded = unquote(segment, errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("invalid path encoding") from error
        if decoded in (".", "..") or any(char in decoded for char in "/\\%") or any(ord(char) < 32 or ord(char) == 127 for char in decoded):
            raise ValueError("unsafe decoded SEC path segment")
    return path


def canonical_source_url(url: str, kind: str) -> str:
    path = _safe_url_path(url)
    if kind == "quarterly":
        valid = QUARTERLY_SOURCE.fullmatch(path) is not None
    elif kind == "daily":
        match = DAILY_SOURCE.fullmatch(path)
        valid = False
        if match is not None:
            try:
                day = date(int(match[3][:4]), int(match[3][4:6]), int(match[3][6:]))
            except ValueError as error:
                raise ValueError("daily source contains an invalid calendar date") from error
            valid = day.year == int(match[1]) and (day.month - 1) // 3 + 1 == int(match[2])
    else:
        raise ValueError("unsupported source kind")
    if not valid:
        raise ValueError("source must be a selected master.zip or master.YYYYMMDD.idx in its matching hierarchy")
    return SEC_ORIGIN + path


def canonical_listing_url(url: str) -> str:
    path = _safe_url_path(url)
    if not path.endswith("index.json") or DIRECTORY.fullmatch(path[:-len("index.json")]) is None:
        raise ValueError("listing must be index.json under an accepted index directory")
    return SEC_ORIGIN + path


def child_url(parent: str, href: str, name: str, is_directory: bool) -> str:
    listing = canonical_listing_url(parent + "index.json" if parent.endswith("/") else parent)
    if type(is_directory) is not bool or not isinstance(name, str) or not name or any(char in name for char in "/\\%?#") or name in (".", ".."):
        raise ValueError("child name must be an immediate safe descendant")
    if not isinstance(href, str) or not href:
        raise ValueError("child href is required")
    parent_path = listing.rsplit("/", 1)[0] + "/"
    suffix = name + ("/" if is_directory else "")
    expected = parent_path + suffix
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or href.startswith("/"):
        child_path = _safe_url_path(href)
        candidate = SEC_ORIGIN + child_path
        if candidate != expected:
            raise ValueError("absolute child href must match its name and immediate parent")
    elif href != suffix:
        raise ValueError("child name and href must agree exactly")
    if is_directory:
        if DIRECTORY.fullmatch(_safe_url_path(expected)) is None:
            raise ValueError("child directory is outside the accepted hierarchy")
        return expected
    kind = "quarterly" if "/full-index/" in expected else "daily"
    return canonical_source_url(expected, kind)


def source_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()
