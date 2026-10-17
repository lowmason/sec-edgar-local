"""Trusted SEC listing traversal with durable evidence and conservative boundaries."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from .config import Settings, pin_context
from .download import HTTP_OK, FetchError, RequestClient
from .models import (BodyReceipt, DirectoryOutcome, Error, RunContext, Source, SourceWorkset,
                     canonical_json, error_text, parse_json, quarter_for, quarter_value, require_text)
from .state import AcquisitionState
from .storage.contracts import Conflict, ObjectStore
from .urls import SEC_ORIGIN, canonical_listing_url, child_url, source_id
from .worksets import encode_workset, make_source_workset

INDEX_BASE = SEC_ORIGIN + '/Archives/edgar/'
QUARTERS_PER_YEAR = 4
MONTHS_PER_QUARTER = 3
DAILY_FILENAME = re.compile(r'master\.([0-9]{8})\.idx\Z')


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    name: str
    href: str
    kind: Literal['dir', 'file']
    size_label: str
    modified_label: str


def parse_listing(url: str, body: bytes) -> tuple[DirectoryEntry, ...]:
    """Decode the retained JSON family; parent-dir is metadata and never followed."""
    if canonical_listing_url(url) != url or not isinstance(body, bytes):
        raise ValueError('listing requires a canonical URL and original bytes')
    value = parse_json(body)
    directory = value.get('directory') if isinstance(value, dict) else None
    if not isinstance(directory, dict):
        raise ValueError('listing requires a directory object')
    expected_name = url[len(INDEX_BASE):-len('index.json')]
    if directory.get('name') != expected_name or not isinstance(directory.get('parent-dir'), str):
        raise ValueError('directory metadata differs from the requested index path')
    items = directory.get('item')
    if not isinstance(items, list):
        raise ValueError('directory item must be a list, including for valid empty listings')
    entries = {}
    for item in items:
        fields = ('name', 'href', 'type', 'size', 'last-modified')
        if not isinstance(item, dict) or any(not isinstance(item.get(field), str) for field in fields):
            raise ValueError('every listing entry requires string name/href/type/size/last-modified')
        name, href, kind = item['name'], item['href'], item['type']
        if (not name or name in ('.', '..') or any(c in name for c in '/\\%?#:')
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in name)):
            raise ValueError('listing child name must be an immediate safe descendant')
        if kind not in ('dir', 'file'):
            raise ValueError('listing type must be dir or file')
        suffix = name + ('/' if kind == 'dir' else '')
        expected_url = url.rsplit('/', 1)[0] + '/' + suffix
        if href not in (suffix, expected_url):
            raise ValueError('listing child href must match its exact immediate name and parent')
        if name in entries:
            raise ValueError('duplicate listing child name')
        entries[name] = DirectoryEntry(name, href, kind, item['size'], item['last-modified'])
    return tuple(entries[name] for name in sorted(entries))


def quarter_of(day: date) -> str:
    if type(day) is not date:
        raise ValueError('day must be an explicit date')
    return quarter_for(day)


def quarter_span(start: str, end: str) -> tuple[str, ...]:
    first_year, first_quarter = quarter_value(start)
    last_year, last_quarter = quarter_value(end)
    first, last = first_year * QUARTERS_PER_YEAR + first_quarter - 1, last_year * QUARTERS_PER_YEAR + last_quarter - 1
    if first > last:
        raise ValueError('quarter range is reversed')
    return tuple(f'{ordinal // QUARTERS_PER_YEAR}Q{ordinal % QUARTERS_PER_YEAR + 1}' for ordinal in range(first, last + 1))


def _previous_quarter(period: str) -> str:
    year, quarter = quarter_value(period)
    return f'{year}Q{quarter - 1}' if quarter > 1 else f'{year - 1}Q{QUARTERS_PER_YEAR}'


def _quarter_start(period: str) -> date:
    year, quarter = quarter_value(period)
    return date(year, (quarter - 1) * MONTHS_PER_QUARTER + 1, 1)


def required_daily_quarters(today: date, handoff: date, boundary: date | None,
                            pending_periods: tuple[str, ...]) -> tuple[str, ...]:
    open_quarter = quarter_of(today)
    if type(handoff) is not date or (boundary is not None and type(boundary) is not date):
        raise ValueError('handoff and boundary must be dates')
    if handoff > today or (boundary is not None and boundary > today):
        raise ValueError('daily discovery dates cannot be in the future')
    start = quarter_of(handoff if boundary is None else boundary)
    quarters = set(quarter_span(start, open_quarter))
    quarters.update((open_quarter, _previous_quarter(open_quarter)))
    for period in pending_periods:
        quarter_value(period)
        if quarter_value(period) > quarter_value(open_quarter):
            raise ValueError('pending quarter cannot be in the future')
        quarters.add(period)
    return tuple(sorted(quarters, key=quarter_value))


def advance_daily_boundary(previous: date | None, today: date,
                           outcomes: tuple[DirectoryOutcome, ...]) -> date | None:
    if not outcomes or any(item.outcome == 'discovery_failed' for item in outcomes):
        return previous
    return today if previous is None else max(previous, today)


def _required_units(families: dict[str, set[str]]) -> tuple[dict[str, str], ...]:
    units = {}
    for family, quarters in families.items():
        root = INDEX_BASE + family + '/index.json'
        units[root] = {'url': root, 'period': family, 'role': 'root'}
        for period in quarters:
            year, quarter = quarter_value(period)
            year_url = INDEX_BASE + f'{family}/{year}/index.json'
            quarter_url = INDEX_BASE + f'{family}/{year}/QTR{quarter}/index.json'
            # Expected directory addresses account for gaps; requests still follow actual children.
            units[year_url] = {'url': year_url, 'period': str(year), 'role': 'year'}
            units[quarter_url] = {'url': quarter_url, 'period': period, 'role': 'quarter'}
    return tuple(units[url] for url in sorted(units))


def _inventory(settings: Settings, state: AcquisitionState, mode: str, today: date,
               end: str) -> tuple[tuple[dict[str, str], ...], date]:
    pending = state.pending_sources()
    failed = state.failed_directories()
    families = {'daily-index' if mode == 'daily' else 'full-index': set()}
    if mode == 'daily':
        old_periods = tuple(quarter_of(date.fromisoformat(s.period)) if s.kind == 'daily' else s.period for s in pending)
        failed_periods = tuple(d.period for d in failed if re.fullmatch(r'[1-9][0-9]{3}Q[1-4]', d.period))
        required = required_daily_quarters(today, settings.daily.start_date, state.daily_boundary(), old_periods + failed_periods)
        families['daily-index'].update(required)
        overlap = min(settings.daily.start_date, _quarter_start(_previous_quarter(quarter_of(today))))
    else:
        families['full-index'].update(quarter_span(settings.backfill.start_quarter, end))
        overlap = _quarter_start(settings.backfill.start_quarter)
    for source in pending:
        family = 'daily-index' if source.kind == 'daily' else 'full-index'
        period = quarter_of(date.fromisoformat(source.period)) if source.kind == 'daily' else source.period
        families.setdefault(family, set()).add(period)
    for outcome in failed:
        family = outcome.url[len(INDEX_BASE):].split('/')[0]
        if re.fullmatch(r'[1-9][0-9]{3}Q[1-4]', outcome.period):
            families.setdefault(family, set()).add(outcome.period)
        else:
            families.setdefault(family, set())
    units = {unit['url']: unit for unit in _required_units(families)}
    for outcome in failed:
        if outcome.url not in units:
            parts = outcome.url[len(INDEX_BASE):].split('/')[:-1]
            role = 'root' if len(parts) == 1 else 'year' if len(parts) == 2 else 'quarter'
            units[outcome.url] = {'url': outcome.url, 'period': outcome.period, 'role': role}
    if quarter_of(today) in families.get('full-index', set()):
        units[INDEX_BASE + 'full-index/index.json']['bridge_period'] = quarter_of(today)
    return tuple(units[url] for url in sorted(units)), overlap


class _SelectionError(ValueError):
    pass


def _select(url: str, period: str, role: str, entries: tuple[DirectoryEntry, ...], *, bridge_period: str | None = None):
    if role != 'quarter':
        selection = {'ignored': []}
        if role == 'root' and bridge_period is not None and '/full-index/' in url:
            bridge = next((entry for entry in entries if entry.kind == 'file' and entry.name == 'master.zip'), None)
            selection['ignored'] = [
                {'name': entry.name, 'reason': 'root master representations are not independent quarter inputs'}
                for entry in entries if entry.kind == 'file' and entry.name.startswith('master.')
                and (bridge is None or entry.name != bridge.name)
            ]
            if bridge is not None:
                selection['alternative'] = {'url': url.rsplit('/', 1)[0] + '/master.zip', 'period': bridge_period,
                    'reason': 'root bridge alternative to the discovered open-quarter child; no byte equality or independent coverage'}
        return (), selection
    members, master_entries = [], []
    quarterly = '/full-index/' in url
    for entry in entries:
        if entry.kind != 'file' or not entry.name.startswith('master.'):
            continue
        master_entries.append(entry)
        supported = entry.name == 'master.zip' if quarterly else DAILY_FILENAME.fullmatch(entry.name) is not None
        if supported:
            source_url = child_url(url, entry.href, entry.name, False)
            source_period = period if quarterly else date(int(entry.name[7:11]), int(entry.name[11:13]), int(entry.name[13:15])).isoformat()
            members.append(Source(source_id(source_url), source_url, 'quarterly' if quarterly else 'daily',
                                  source_period, 'zip' if quarterly else 'idx'))
    if master_entries and not members:
        raise _SelectionError('only unsupported master representations are advertised')
    selected_names = {source.canonical_url.rsplit('/', 1)[1] for source in members}
    ignored = [{'name': entry.name, 'reason': 'unselected alternate master representation; selected ZIP/plain IDX only'}
               for entry in master_entries if entry.name not in selected_names]
    return tuple(sorted(members, key=lambda source: source.source_id)), {'ignored': ignored}


def _persist_receipt(objects: ObjectStore, receipt: BodyReceipt, context: RunContext, *, failed=False):
    body = receipt.temporary_path.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    if digest != receipt.sha256 or len(body) != receipt.byte_count:
        raise Conflict('original listing receipt no longer matches its retained bytes')
    namespace = 'quarantine/discovery' if failed else 'worksets/discovery/listings'
    body_path = f'{namespace}/sha256={digest}/listing.body'
    objects.put_once(body_path, body)
    objects.verify(body_path, digest, len(body))
    metadata = canonical_json({'receipt': receipt.to_mapping(), 'context': context.to_mapping(), 'body_path': body_path})
    metadata_hash = hashlib.sha256(metadata).hexdigest()
    receipt_path = f'{namespace}/receipts/sha256={metadata_hash}.json'
    objects.put_once(receipt_path, metadata)
    objects.verify(receipt_path, metadata_hash, len(metadata))
    return {'body_path': body_path, 'sha256': digest, 'byte_count': len(body),
            'receipt_path': receipt_path, 'receipt_sha256': metadata_hash, 'receipt_byte_count': len(metadata)}


def _verify_receipt_context(value: object, frozen_context: RunContext) -> None:
    try:
        transport_context = RunContext.from_mapping(value)
        settings = Settings.from_mapping(transport_context.to_mapping()['effective_config'])
        if transport_context.pinned_on is None:
            raise ValueError('receipt transport context requires its actual pinning date')
        pin_context(settings, transport_context, transport_context.pinned_on)
    except ValueError as error:
        raise Conflict('cached listing receipt has invalid transport context') from error
    provenance_fields = ('run_id', 'command', 'config_sha256', 'image_digest', 'parser_version', 'schema_version')
    if (any(getattr(transport_context, field) != getattr(frozen_context, field) for field in provenance_fields)
            or transport_context.effective_config != frozen_context.effective_config):
        raise Conflict('cached listing receipt has conflicting frozen transport provenance')


def reopen_listing(objects: ObjectStore, value: dict, unit: dict, frozen_context: RunContext):
    outcome = DirectoryOutcome.from_mapping(value['outcome'])
    if outcome.url != unit['url'] or outcome.period != unit['period']:
        raise Conflict('cached directory progress differs from the requested directory metadata')
    evidence = value['evidence']
    objects.verify(evidence['body_path'], evidence['sha256'], evidence['byte_count'])
    objects.verify(evidence['receipt_path'], evidence['receipt_sha256'], evidence['receipt_byte_count'])
    metadata = parse_json(objects.read(evidence['receipt_path']))
    _verify_receipt_context(metadata.get('context'), frozen_context)
    receipt = BodyReceipt.from_mapping(metadata['receipt'])
    if (not receipt.complete or receipt.status != HTTP_OK or receipt.error is not None or receipt.url != unit['url']
            or receipt.sha256 != outcome.listing_sha256 or receipt.byte_count != evidence['byte_count']
            or metadata['body_path'] != evidence['body_path'] or outcome.listing_sha256 != evidence['sha256']):
        raise Conflict('successful directory progress lacks its exact original receipt')
    entries = parse_listing(unit['url'], objects.read(evidence['body_path']))
    members, selection = _select(unit['url'], unit['period'], unit['role'], entries, bridge_period=unit.get('bridge_period'))
    if ([member.to_mapping() for member in members] != value['members'] or selection != value['selection']
            or outcome.source_ids != tuple(sorted(member.source_id for member in members))):
        raise Conflict('directory progress differs from its validated immediate listing children')
    return outcome, members, entries, receipt.received_at


def _missing(unit: dict, parent: DirectoryOutcome) -> DirectoryOutcome:
    code = 'ancestor_failed' if parent.outcome == 'discovery_failed' else 'missing_directory'
    details = {'parent_url': parent.url, 'parent_listing_sha256': parent.listing_sha256}
    return DirectoryOutcome(unit['url'], unit['period'], 'discovery_failed', None, (),
                            Error(code, 'required child directory is unresolved in its actual parent listing', True, None, details))


def discover(settings: Settings, context: RunContext, mode: Literal['quarterly', 'daily'],
             discovery_id: str, client: RequestClient, state: AcquisitionState,
             objects: ObjectStore, today: date, refresh: bool = False) -> SourceWorkset:
    if mode not in ('quarterly', 'daily') or type(refresh) is not bool:
        raise ValueError('discovery requires quarterly/daily mode and a boolean refresh')
    require_text(discovery_id, 'discovery_id')
    request_context, end = pin_context(settings, context, today)
    if client.settings != settings:
        raise ValueError('discovery and RequestClient require the same effective settings')
    old = state.discovery_session(discovery_id)
    if old is None and mode == 'daily' and end != quarter_of(today):
        raise ValueError('daily discovery endpoint must include the current quarter')
    state.begin_attempt(request_context)
    if old is None:
        units, overlap = _inventory(settings, state, mode, today, end)
        frozen = {'context': request_context.to_mapping(), 'today': today.isoformat(), 'end': end,
                  'mode': mode, 'acquisition_mode': 'refresh' if refresh else 'reuse_accepted',
                  'units': list(units), 'overlap_from': overlap.isoformat()}
    else:
        frozen = old.to_mapping()['value']['frozen']
    session = state.begin_discovery(discovery_id, frozen, request_context, mode,
                                    'refresh' if refresh else 'reuse_accepted').to_mapping()['value']
    frozen = session['frozen']
    pinned_context = RunContext.from_mapping(frozen['context'])
    outcomes, members, listings = {}, {}, {}
    # Root, then year, then quarter: every actual request must be authorized by its parent.
    units = sorted(frozen['units'], key=lambda unit: (unit['url'].count('/'), unit['url']))
    for unit in units:
        url, role = unit['url'], unit['role']
        cached = state.directory_progress(discovery_id, url)
        if cached is not None and cached.value['outcome']['outcome'] != 'discovery_failed':
            saved = cached.to_mapping()['value']
            outcome, selected, entries, discovered_at = reopen_listing(objects, saved, unit, pinned_context)
            state.record_directory(discovery_id, outcome, selected, evidence=saved['evidence'],
                                   selection=saved['selection'], expected_gap=saved['observed_gap_token'])
        else:
            parent_url = url.rsplit('/', 2)[0] + '/index.json'
            if role != 'root':
                parent = outcomes[parent_url]
                wanted_name = url.rsplit('/', 2)[1]
                entry = next((entry for entry in listings.get(parent_url, ())
                              if entry.name == wanted_name and entry.kind == 'dir'), None)
                if parent.outcome == 'discovery_failed' or entry is None:
                    outcome = _missing(unit, parent)
                    state.record_directory(discovery_id, outcome, ())
                    outcomes[url] = outcome
                    continue
                actual_url = child_url(parent_url, entry.href, entry.name, True) + 'index.json'
                if actual_url != url:
                    raise Conflict('validated child differs from required directory accounting')
            expected_gap = state.directory_gap(url)
            receipt = None
            try:
                receipt = client.fetch(url, request_context)
                entries = parse_listing(url, receipt.temporary_path.read_bytes())
                selected, selection = _select(url, unit['period'], role, entries, bridge_period=unit.get('bridge_period'))
            except (FetchError, ValueError) as failure:
                if isinstance(failure, FetchError):
                    receipt, error = failure.receipt, failure.error
                else:
                    code = 'unsupported_source' if isinstance(failure, _SelectionError) else 'listing_invalid'
                    error = Error(code, error_text(failure), True, None, {})
                evidence = _persist_receipt(objects, receipt, request_context, failed=True) if receipt is not None else None
                error = Error(error.code, error.message, error.retryable, None,
                              {**error.to_mapping()['details'], 'evidence': evidence})
                outcome = DirectoryOutcome(url, unit['period'], 'discovery_failed', None, (), error)
                state.record_directory(discovery_id, outcome, ())
                outcomes[url] = outcome
                continue
            evidence = _persist_receipt(objects, receipt, request_context)
            discovered_at = receipt.received_at
            outcome = DirectoryOutcome(url, unit['period'], 'available' if selected else 'no_new_sources',
                                       receipt.sha256, tuple(source.source_id for source in selected), None)
            state.record_directory(discovery_id, outcome, selected, evidence=evidence,
                                   selection=selection, expected_gap=expected_gap)
        outcomes[url], listings[url] = outcome, entries
        for source in selected:
            state.observe(source, discovered_at, 'available')
            members[source.source_id] = source
    directories = tuple(outcomes.values())
    workset = make_source_workset(pinned_context, frozen['end'], discovery_id, tuple(members.values()), directories,
                                  date.fromisoformat(frozen['overlap_from']), acquisition_mode=frozen['acquisition_mode'])
    objects.put_once(f'worksets/sec/source/sha256={workset.workset_id}/workset.json', encode_workset(workset))
    state.finish_discovery(discovery_id, workset.workset_id, request_context)
    if frozen['mode'] == 'daily':
        candidate = advance_daily_boundary(state.daily_boundary(), date.fromisoformat(frozen['today']), directories)
        if candidate is not None and workset.discovery_complete:
            state.advance_boundary(date.fromisoformat(frozen['today']), discovery_id, directories)
    return workset
