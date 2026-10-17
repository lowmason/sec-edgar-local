"""Strict native-local settings; filesystem paths resolve at the configuration boundary."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Literal

from .models import (SCHEMA_VERSION, Record, RunContext, canonical_json, parse_json, quarter_for,
                     quarter_value, record_from_mapping, require_number, require_text, validate_record_fields)

CONFIG_VERSION = "sec-local-config-v1"
COORDINATION_NAMESPACE = "sec-owner-lowell-mason"
LOCK_BLOB = COORDINATION_NAMESPACE + "/sentinel.json"
BINDING_REGISTRY_BLOB = COORDINATION_NAMESPACE + "/binding.json"
OWNER_USER_AGENT = "Lowell Mason sec-edgar-ingest mason.lowell@mac.com"
REQUEST_BUDGET_PER_SECOND = 3
ACTIVE_COLLECTOR_LIMIT = 1
HTTP_ATTEMPT_LIMIT = 5
CLOCK_UNCERTAINTY_LIMIT_SECONDS = 2
LEASE_SECONDS = 60
RENEW_EVERY_SECONDS = 20
WORKER_ALLOWANCE_SECONDS = 3600
MAX_EXCHANGE_SECONDS = 90
MAX_RECEIVED_BYTES = 67108864
MAX_EXPANDED_BYTES = 536870912
HTTP_POLICY = {
    "max_attempts": HTTP_ATTEMPT_LIMIT, "retry_base_seconds": 2, "retry_cap_seconds": 120,
    "connect_timeout_seconds": 15, "read_timeout_seconds": 60,
    "exchange_deadline_seconds": MAX_EXCHANGE_SECONDS,
    "max_received_bytes": MAX_RECEIVED_BYTES, "max_expanded_bytes": MAX_EXPANDED_BYTES,
}


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
    backend: Literal["local"]
    root: str


@dataclass(frozen=True, slots=True)
class AcquisitionSettings(Record):
    mode: Literal["live", "fixture"]


@dataclass(frozen=True, slots=True)
class NativeRuntimeSettings(Record):
    kind: Literal["native"]
    release_manifest: str


@dataclass(frozen=True, slots=True)
class FixtureRuntimeSettings(Record):
    kind: Literal["fixture"]
    fixture_id: str


RuntimeSettings = NativeRuntimeSettings | FixtureRuntimeSettings


@dataclass(frozen=True, slots=True)
class LoggingSettings(Record):
    root: str


@dataclass(frozen=True, slots=True)
class ExecutionSettings(Record):
    max_run_seconds: int


@dataclass(frozen=True, slots=True)
class EtlSettings(Record):
    parser_version: str
    schema_version: str


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
    acquisition: AcquisitionSettings
    runtime: RuntimeSettings
    logging: LoggingSettings
    execution: ExecutionSettings
    etl: EtlSettings
    reconciliation: ReconciliationSettings
    fixture: FixtureOverrides | None = None

    def __post_init__(self):
        validate_record_fields(self)
        if self.config_version != CONFIG_VERSION:
            raise ValueError("unsupported config_version")
        start = quarter_value(self.backfill.start_quarter)
        if self.backfill.end_quarter != "open" and quarter_value(self.backfill.end_quarter) < start:
            raise ValueError("backfill quarters are reversed")
        if type(self.daily.start_date) is not date:
            raise ValueError("daily.start_date must be an ISO date")
        _validate_issuer(self.sec)
        _validate_http(self.http)
        _validate_coordination(self.coordination)
        require_text(self.storage.root, "storage.root filesystem path")
        require_text(self.logging.root, "logging.root filesystem path")
        if self.runtime.kind == "native":
            _validate_manifest_path(self.runtime.release_manifest)
        else:
            require_text(self.runtime.fixture_id, "runtime.fixture_id")
        require_number(self.execution.max_run_seconds, "execution.max_run_seconds", positive=True, integer=True)
        require_text(self.etl.parser_version, "etl.parser_version")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", self.etl.parser_version) is None or self.etl.parser_version.lower() in ("latest", "open"):
            raise ValueError("etl.parser_version must be explicit immutable provenance")
        if self.etl.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported etl.schema_version")
        if self.reconciliation.require_withdrawal_approval is not True:
            raise ValueError("reconciliation.require_withdrawal_approval must be true")
        if self.acquisition.mode == "live":
            _validate_live_policy(self)

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> Settings:
        if isinstance(value, dict) and "fixture" in value and value["fixture"] is None:
            raise ValueError("fixture must be an explicit object when supplied")
        return record_from_mapping(cls, value, require_all=False)

    def to_mapping(self) -> dict[str, object]:
        mapping = super(Settings, self).to_mapping()
        if self.fixture is None:
            mapping.pop("fixture")
        return mapping

    @property
    def config_sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.to_mapping())).hexdigest()


def _validate_issuer(sec: SecSettings) -> None:
    if sec.user_agent != OWNER_USER_AGENT:
        raise ValueError("sec.user_agent must use the accepted owner identity")
    require_number(sec.requests_per_second, "sec.requests_per_second", positive=True)
    if sec.requests_per_second > REQUEST_BUDGET_PER_SECOND:
        raise ValueError("sec.requests_per_second exceeds the accepted shared request budget")
    if sec.max_active_collectors != ACTIVE_COLLECTOR_LIMIT:
        raise ValueError("sec.max_active_collectors must equal 1")


def _validate_http(http: HttpSettings) -> None:
    for label, maximum in HTTP_POLICY.items():
        value = getattr(http, label)
        require_number(value, "http." + label, positive=True,
                       integer=label in ("max_attempts", "max_received_bytes", "max_expanded_bytes"))
        if value > maximum:
            raise ValueError(f"http.{label} exceeds the accepted acquisition bound")
    if http.retry_cap_seconds < http.retry_base_seconds:
        raise ValueError("http retry settings reverse the delay bounds")


def _validate_coordination(coordination: CoordinationSettings) -> None:
    for label in ("lease_seconds", "renew_every_seconds"):
        require_number(getattr(coordination, label), "coordination." + label, positive=True)
    require_number(coordination.clock_uncertainty_seconds, "coordination.clock_uncertainty_seconds")
    if coordination.clock_uncertainty_seconds > CLOCK_UNCERTAINTY_LIMIT_SECONDS:
        raise ValueError("coordination.clock_uncertainty_seconds exceeds accepted bound")
    if coordination.lease_seconds > LEASE_SECONDS:
        raise ValueError("coordination.lease_seconds exceeds the accepted finite lease")
    if coordination.renew_every_seconds >= coordination.lease_seconds:
        raise ValueError("coordination requires 0 < renew_every_seconds < lease_seconds")
    if coordination.namespace != COORDINATION_NAMESPACE:
        raise ValueError("coordination.namespace must use the one deployment binding")


def _validate_manifest_path(value: str) -> None:
    require_text(value, "runtime.release_manifest filesystem path")
    parts = Path(value).parts
    if (len(parts) < 3 or parts[-3] != "releases" or parts[-1] != "release.json"
            or re.fullmatch(r"sha256=[0-9a-f]{64}", parts[-2]) is None):
        raise ValueError("runtime.release_manifest must name releases/sha256=<release-id>/release.json")


def _validate_live_policy(settings: Settings) -> None:
    if settings.fixture is not None:
        raise ValueError("fixture overrides are permitted only for fixture acquisition")
    if settings.runtime.kind != "native":
        raise ValueError("live acquisition requires native runtime")
    if settings.etl.parser_version != "sec-index-parser-v1":
        raise ValueError("live acquisition requires sec-index-parser-v1")
    if settings.http.to_mapping() != HTTP_POLICY:
        raise ValueError("live HTTP settings must match the accepted acquisition policy")
    if (settings.coordination.lease_seconds != LEASE_SECONDS
            or settings.coordination.renew_every_seconds != RENEW_EVERY_SECONDS
            or settings.coordination.clock_uncertainty_seconds != CLOCK_UNCERTAINTY_LIMIT_SECONDS):
        raise ValueError("live coordination settings must match the accepted finite lease policy")
    if settings.execution.max_run_seconds != WORKER_ALLOWANCE_SECONDS:
        raise ValueError("live execution.max_run_seconds must equal 3600")


def parse_config(text: str) -> Settings:
    try:
        value = parse_json(text)
    except ValueError as error:
        raise ValueError("configuration requires strict JSON syntax (YAML 1.2 subset)") from error
    return Settings.from_mapping(value)


def normalize_paths(settings: Settings, config_parent: Path) -> Settings:
    """Resolve filesystem fields once; absolute archived snapshots replay unchanged."""
    def absolute_field(value: str) -> str:
        require_text(value, "filesystem path")
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = config_parent / candidate
        return str(candidate.resolve())

    validated = Settings.from_mapping(settings.to_mapping())
    runtime = validated.runtime
    if runtime.kind == "native":
        runtime = replace(runtime, release_manifest=absolute_field(runtime.release_manifest))
    return replace(validated, storage=replace(validated.storage, root=absolute_field(validated.storage.root)),
                   logging=replace(validated.logging, root=absolute_field(validated.logging.root)), runtime=runtime)


def load_config(path: Path) -> Settings:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("configuration requires strict JSON syntax (YAML 1.2 subset)") from error
    return normalize_paths(parse_config(text), path.resolve().parent)


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
