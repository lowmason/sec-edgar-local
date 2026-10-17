"""Validated, side-effect-free settings for the acquisition boundary.

Configuration files use JSON syntax, a subset of YAML 1.2; general YAML is unsupported.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from .models import (FORMAT_VERSION, IMAGE_PATTERN, SCHEMA_VERSION, Record, RunContext,
                     canonical_json, parse_json, quarter_for, quarter_value, record_from_mapping,
                     require_number, require_text, safe_relative_path, validate_record_fields)

ACCOUNT_NAME = "secedgardevb8617"
COORDINATION_NAMESPACE = "sec-owner-lowell-mason"
LOCK_BLOB = COORDINATION_NAMESPACE + "/sentinel.json"
BINDING_REGISTRY_BLOB = COORDINATION_NAMESPACE + "/binding.json"
OWNER_USER_AGENT = "Lowell Mason sec-edgar-ingest mason.lowell@mac.com"
REQUEST_BUDGET_PER_SECOND = 3
ACTIVE_COLLECTOR_LIMIT = 1
HTTP_ATTEMPT_LIMIT = 5
CLOCK_UNCERTAINTY_LIMIT_SECONDS = 2
AZURE_LEASE_MIN_SECONDS = 15
AZURE_LEASE_MAX_SECONDS = 60
TRANSIENT_REPLAY_LIMIT = 1
WORKER_ALLOWANCE_SECONDS = 3600
MAX_EXCHANGE_SECONDS = 90
MAX_RECEIVED_BYTES = 67108864
MAX_EXPANDED_BYTES = 536870912


@dataclass(frozen=True, slots=True)
class BackfillSettings(Record):
    start_quarter: str
    end_quarter: str


@dataclass(frozen=True, slots=True)
class DailySettings(Record):
    start_date: date


@dataclass(frozen=True, slots=True)
class SecSettings(Record):
    user_agent: str
    requests_per_second: float
    max_active_collectors: int


@dataclass(frozen=True, slots=True)
class HttpSettings(Record):
    max_attempts: int
    retry_base_seconds: float
    retry_cap_seconds: float
    connect_timeout_seconds: float
    read_timeout_seconds: float
    exchange_deadline_seconds: float
    max_received_bytes: int
    max_expanded_bytes: int


@dataclass(frozen=True, slots=True)
class CoordinationSettings(Record):
    lease_seconds: float
    renew_every_seconds: float
    namespace: str
    clock_uncertainty_seconds: float


@dataclass(frozen=True, slots=True)
class StorageSettings(Record):
    backend: Literal["local-fixture", "azure"]
    source_table: str
    attempt_table: str
    blob_api_version: str
    table_api_version: str
    root: str | None = None
    account_name: str | None = None
    blob_endpoint: str | None = None
    table_endpoint: str | None = None
    raw_container: str = "raw"
    workset_container: str = "worksets"
    quarantine_container: str = "quarantine"
    lock_container: str = "locks"
    lock_blob: str = LOCK_BLOB
    binding_registry_blob: str = BINDING_REGISTRY_BLOB


@dataclass(frozen=True, slots=True)
class EtlSettings(Record):
    parser_version: str
    schema_version: str


@dataclass(frozen=True, slots=True)
class WorkerSettings(Record):
    image_digest: str
    provenance: str


@dataclass(frozen=True, slots=True)
class JobsSettings(Record):
    replica_retry_limit: int


@dataclass(frozen=True, slots=True)
class OrchestrationSettings(Record):
    transient_replays: int


@dataclass(frozen=True, slots=True)
class ReconciliationSettings(Record):
    require_withdrawal_approval: bool


@dataclass(frozen=True, slots=True)
class FixtureOverrides(Record):
    allow_clock_override: bool = False
    allow_deadline_override: bool = False


@dataclass(frozen=True, slots=True)
class Settings(Record):
    config_version: str
    backfill: BackfillSettings
    daily: DailySettings
    sec: SecSettings
    http: HttpSettings
    coordination: CoordinationSettings
    storage: StorageSettings
    etl: EtlSettings
    worker: WorkerSettings
    jobs: JobsSettings
    orchestration: OrchestrationSettings
    reconciliation: ReconciliationSettings
    fixture: FixtureOverrides | None = None

    def __post_init__(self):
        validate_record_fields(self)
        if self.config_version != FORMAT_VERSION:
            raise ValueError("unsupported config_version")
        start = quarter_value(self.backfill.start_quarter)
        if self.backfill.end_quarter != "open" and quarter_value(self.backfill.end_quarter) < start:
            raise ValueError("backfill quarters are reversed")
        if type(self.daily.start_date) is not date:
            raise ValueError("daily.start_date must be an ISO date")
        require_text(self.sec.user_agent, "sec.user_agent")
        if self.sec.user_agent != OWNER_USER_AGENT:
            raise ValueError("sec.user_agent must use the accepted owner identity")
        require_number(self.sec.requests_per_second, "sec.requests_per_second", positive=True)
        if self.sec.requests_per_second > REQUEST_BUDGET_PER_SECOND:
            raise ValueError("sec.requests_per_second exceeds the accepted shared request budget")
        if type(self.sec.max_active_collectors) is not int or self.sec.max_active_collectors != ACTIVE_COLLECTOR_LIMIT:
            raise ValueError("sec.max_active_collectors must equal 1")
        for label in ("max_attempts", "max_received_bytes", "max_expanded_bytes"):
            require_number(getattr(self.http, label), "http." + label, positive=True, integer=True)
        for label in ("retry_base_seconds", "retry_cap_seconds", "connect_timeout_seconds",
                      "read_timeout_seconds", "exchange_deadline_seconds"):
            require_number(getattr(self.http, label), "http." + label, positive=True)
        if self.http.max_attempts > HTTP_ATTEMPT_LIMIT or self.http.retry_cap_seconds < self.http.retry_base_seconds:
            raise ValueError("http retry settings exceed the accepted attempts or reverse the delay bounds")
        if self.http.exchange_deadline_seconds > MAX_EXCHANGE_SECONDS or self.http.max_received_bytes > MAX_RECEIVED_BYTES or self.http.max_expanded_bytes > MAX_EXPANDED_BYTES:
            raise ValueError("http guard settings exceed accepted acquisition bounds")
        for label in ("lease_seconds", "renew_every_seconds"):
            require_number(getattr(self.coordination, label), "coordination." + label, positive=True)
        require_number(self.coordination.clock_uncertainty_seconds, "coordination.clock_uncertainty_seconds")
        if self.coordination.clock_uncertainty_seconds > CLOCK_UNCERTAINTY_LIMIT_SECONDS:
            raise ValueError("coordination.clock_uncertainty_seconds exceeds accepted bound")
        if self.coordination.renew_every_seconds >= self.coordination.lease_seconds:
            raise ValueError("coordination requires 0 < renew_every_seconds < lease_seconds")
        if self.coordination.namespace != COORDINATION_NAMESPACE:
            raise ValueError("coordination.namespace must use the one deployment binding")
        _validate_storage(self.storage)
        require_text(self.etl.parser_version, "etl.parser_version")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", self.etl.parser_version) is None or self.etl.parser_version.lower() in ("latest", "open"):
            raise ValueError("etl.parser_version must be explicit immutable provenance")
        if self.etl.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported etl.schema_version")
        if not isinstance(self.worker.image_digest, str) or IMAGE_PATTERN.fullmatch(self.worker.image_digest) is None:
            raise ValueError("worker.image_digest must be an immutable sha256 digest")
        require_text(self.worker.provenance, "worker.provenance")
        if type(self.jobs.replica_retry_limit) is not int or self.jobs.replica_retry_limit != 0:
            raise ValueError("jobs.replica_retry_limit must equal 0")
        if type(self.orchestration.transient_replays) is not int or not 0 <= self.orchestration.transient_replays <= TRANSIENT_REPLAY_LIMIT:
            raise ValueError("orchestration.transient_replays must be at most 1")
        if self.reconciliation.require_withdrawal_approval is not True:
            raise ValueError("reconciliation.require_withdrawal_approval must be true")
        if self.storage.backend == "azure":
            _validate_azure_policy(self)

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> Settings:
        if isinstance(value, dict) and isinstance(value.get("storage"), dict) and value["storage"].get("backend") == "azure":
            required = {"account_name", "blob_endpoint", "table_endpoint", "raw_container", "workset_container",
                        "quarantine_container", "lock_container", "lock_blob", "binding_registry_blob",
                        "source_table", "attempt_table", "blob_api_version", "table_api_version"}
            if required - value["storage"].keys():
                raise ValueError(f"azure storage missing explicit bindings: {sorted(required - value['storage'].keys())}")
        return record_from_mapping(cls, value, require_all=False)

    @property
    def config_sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.to_mapping())).hexdigest()


def _validate_storage(storage: StorageSettings) -> None:
    if storage.source_table != "SourceState" or storage.attempt_table != "Attempts":
        raise ValueError("storage tables must use the accepted SourceState/Attempts binding")
    if storage.blob_api_version != "2026-04-06" or storage.table_api_version != "2020-12-06":
        raise ValueError("unsupported storage data-plane API versions")
    for label, expected in (("raw_container", "raw"), ("workset_container", "worksets"),
                            ("quarantine_container", "quarantine"), ("lock_container", "locks"),
                            ("lock_blob", LOCK_BLOB), ("binding_registry_blob", BINDING_REGISTRY_BLOB)):
        if getattr(storage, label) != expected:
            raise ValueError(f"storage.{label} must use the one deployment binding")
    if storage.backend == "local-fixture":
        safe_relative_path(storage.root, "storage.root")
        if any(getattr(storage, label) is not None for label in ("account_name", "blob_endpoint", "table_endpoint")):
            raise ValueError("local-fixture storage cannot include Azure account endpoints")
    elif storage.backend == "azure":
        if storage.root is not None or storage.account_name != ACCOUNT_NAME:
            raise ValueError("azure storage must use the accepted account binding")
        for kind, endpoint in (("blob", storage.blob_endpoint), ("table", storage.table_endpoint)):
            require_text(endpoint, f"storage.{kind}_endpoint")
            parsed = urlsplit(endpoint)
            if parsed.scheme != "https" or parsed.netloc != f"{ACCOUNT_NAME}.{kind}.core.windows.net" or parsed.path not in ("", "/") or parsed.query or parsed.fragment or "?" in endpoint or "#" in endpoint:
                raise ValueError(f"storage.{kind}_endpoint must be the accepted credential-free HTTPS endpoint")
    else:
        raise ValueError("unsupported storage.backend")


def _validate_azure_policy(settings: Settings) -> None:
    if settings.fixture is not None:
        raise ValueError("fixture overrides are permitted only for local-fixture storage")
    if settings.sec.requests_per_second != REQUEST_BUDGET_PER_SECOND:
        raise ValueError("azure request budget must match the deployment binding")
    if "fixture" in settings.worker.provenance.lower() or "synthetic" in settings.worker.provenance.lower() or settings.worker.image_digest == "sha256:" + "0" * 64:
        raise ValueError("synthetic fixture image is forbidden for Azure")
    if "fixture" in settings.etl.parser_version.lower():
        raise ValueError("fixture parser provenance is forbidden for Azure")
    if (settings.http.exchange_deadline_seconds != MAX_EXCHANGE_SECONDS
            or settings.http.max_received_bytes != MAX_RECEIVED_BYTES
            or settings.http.max_expanded_bytes != MAX_EXPANDED_BYTES):
        raise ValueError("lower HTTP guard overrides are fixture-only")
    if not AZURE_LEASE_MIN_SECONDS <= settings.coordination.lease_seconds <= AZURE_LEASE_MAX_SECONDS:
        raise ValueError("azure finite lease_seconds must be in the supported 15..60 second range")


def parse_config(text: str) -> Settings:
    try:
        value = parse_json(text)
    except ValueError as error:
        raise ValueError("configuration requires strict JSON syntax (YAML 1.2 subset)") from error
    return Settings.from_mapping(value)


def load_config(path: Path) -> Settings:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("configuration requires strict JSON syntax (YAML 1.2 subset)") from error
    return parse_config(text)


def load_config_env(name: str, environ: Mapping[str, str]) -> Settings:
    """The same strict configuration, carried by one environment variable (the Azure job secret)."""
    if not isinstance(name, str) or re.fullmatch(r"[A-Z][A-Z0-9_]*", name) is None:
        raise ValueError("--config-env must name an upper-case environment variable")
    text = environ.get(name)
    if not text:
        raise ValueError(f"configuration environment variable {name} is unset or empty")
    return parse_config(text)


def pin_context(settings: Settings, context: RunContext, today: date) -> tuple[RunContext, str]:
    if type(today) is not date:
        raise ValueError("today must be an explicit date")
    if today != context.started_at.date() and not (settings.fixture and settings.fixture.allow_clock_override):
        raise ValueError("fixture clock override must be explicitly labelled")
    expected = {"image_digest": settings.worker.image_digest, "parser_version": settings.etl.parser_version,
                "schema_version": settings.etl.schema_version, "config_sha256": settings.config_sha256}
    for label, value in expected.items():
        if getattr(context, label) != value:
            raise ValueError(f"context {label} does not match the effective configuration")
    duration = (context.deadline - context.started_at).total_seconds()
    if duration > WORKER_ALLOWANCE_SECONDS and not (settings.fixture and settings.fixture.allow_deadline_override):
        raise ValueError("context deadline exceeds the accepted 3600-second worker allowance")
    end = quarter_for(today) if settings.backfill.end_quarter == "open" else settings.backfill.end_quarter
    if quarter_value(end) > quarter_value(quarter_for(today)):
        raise ValueError("backfill endpoint is in a future quarter")
    if quarter_value(end) < quarter_value(settings.backfill.start_quarter):
        raise ValueError("pinned backfill endpoint precedes start_quarter")
    return replace(context, effective_config=settings.to_mapping(), pinned_on=today), end
