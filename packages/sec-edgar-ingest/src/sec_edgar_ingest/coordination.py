"""One leased sentinel authorizes bounded exchanges and durable owner-wide pacing."""
from __future__ import annotations

import math
import multiprocessing
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from .config import Settings
from .models import (BodyReceipt, Error, Permit, QueueTicket, RunContext, Versioned, error_text, require_number,
                     require_text, require_utc)
from .storage.contracts import ClockUncertain, Conflict, LeaseHandle, LeaseStore, OwnershipLost, StateStore, TimeBounds

JOURNAL_VERSION = "sec-lease-journal-v1"
QUEUE_POLL_SECONDS = 0.25
STORAGE_CALL_BOUND_SECONDS = 15
RENEWAL_PREPARATION_CALLS = 5
MANUAL_WATCH_STEP_SECONDS = 1
SPAWN = multiprocessing.get_context("spawn")


class Clock:
    precision_seconds = 0.000001

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        require_number(seconds, "sleep seconds")
        time.sleep(seconds)


class ManualClock(Clock):
    """A deterministic fixture clock; advancing it also runs registered renewal checks."""
    precision_seconds = 0
    def __init__(self, instant: datetime):
        require_utc(instant, "manual instant")
        self._instant, self._elapsed = instant, 0.0
        self._lock = threading.RLock()
        self._watchers = []

    def now(self) -> datetime:
        with self._lock:
            return self._instant

    def monotonic(self) -> float:
        with self._lock:
            return self._elapsed

    def advance(self, seconds: float) -> None:
        require_number(seconds, "advance seconds")
        remaining = seconds
        while remaining > 0:
            with self._lock:
                step = min(remaining, MANUAL_WATCH_STEP_SECONDS) if self._watchers else remaining
                self._instant += timedelta(seconds=step)
                self._elapsed += step
                watchers = tuple(self._watchers)
            for watcher in watchers:
                watcher()
            remaining -= step

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def subscribe(self, callback):
        with self._lock:
            self._watchers.append(callback)
        def unsubscribe():
            with self._lock:
                if callback in self._watchers:
                    self._watchers.remove(callback)
        return unsubscribe


class PolicyBlocked(RuntimeError):
    """A confirmed durable sentinel latch forbids any further request in this issuer namespace."""
    def __init__(self, reason: Error):
        self.reason = reason
        super().__init__(reason.message)


class Sender(Protocol):
    """A returned receipt proves positive transport drain, including partial failure receipts."""
    def send(self, url: str, context: RunContext, permit: Permit, *, cancellation) -> BodyReceipt: ...


def utc_value(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("journal time must be a UTC ISO string")
    instant = datetime.fromisoformat(value)
    require_utc(instant, "journal time")
    return instant


def takeover_time(previous_unsafe: datetime, acquired_upper: datetime,
                  exchange_seconds: float, uncertainty_seconds: float, clean_release: bool) -> datetime:
    if clean_release:
        return previous_unsafe
    return max(previous_unsafe, acquired_upper + timedelta(seconds=exchange_seconds + uncertainty_seconds))


def reservation_guard(ownership_until: datetime, exchange_seconds: float, uncertainty_seconds: float) -> datetime:
    return ownership_until + timedelta(seconds=exchange_seconds + uncertainty_seconds)


def next_start(last_start: datetime | None, not_before: datetime, earliest_safe: datetime, rate: float) -> datetime:
    if last_start is None:
        return max(not_before, earliest_safe)
    # datetime has microsecond precision; round upward so 3/s never becomes 333333 microseconds.
    interval = timedelta(microseconds=math.ceil(1_000_000 / rate))
    return max(not_before, earliest_safe, last_start + interval)


def _journal(value, bounds: TimeBounds) -> dict[str, object]:
    if not value:
        return {"journal_version": JOURNAL_VERSION, "owner_id": "unowned", "epoch": 0,
                "ownership_until": bounds.upper.isoformat(), "unsafe_until": bounds.upper.isoformat(),
                "last_start": None, "not_before": bounds.upper.isoformat(), "request_id": None,
                "clean_release": True, "policy_block": None}
    result = dict(value)
    if result.get("journal_version") != JOURNAL_VERSION:
        raise Conflict("unknown sentinel journal version")
    require_text(result.get("owner_id"), "journal owner")
    require_number(result.get("epoch"), "journal epoch", integer=True)
    for name in ("ownership_until", "unsafe_until", "not_before"):
        utc_value(result.get(name))
    if result.get("last_start") is not None:
        utc_value(result["last_start"])
    if result.get("request_id") is not None:
        require_text(result["request_id"], "journal request")
    if type(result.get("clean_release")) is not bool:
        raise Conflict("journal clean_release must be boolean")
    result.setdefault("policy_block", None)
    if result["policy_block"] is not None:
        Error.from_mapping(result["policy_block"])
    return result


class Coordinator:
    def __init__(self, settings: Settings, store: StateStore, leases: LeaseStore, clock: Clock):
        self.settings = Settings.from_mapping(settings.to_mapping())
        if not self.settings.coordination.lease_seconds.is_integer():
            raise ValueError("coordination requires whole finite lease seconds")
        self.store, self.leases, self.clock = store, leases, clock
        self.observer = None
        self._active = None
        self._wall_origin, self._mono_origin = clock.now(), clock.monotonic()

    def _trace(self, event: str, **details) -> None:
        if self.observer is not None:
            self.observer({"event": event, "at": self.clock.now().isoformat(),
                           "mono": self.clock.monotonic(), **details})

    def _time(self, handle: LeaseHandle | None = None) -> TimeBounds:
        mono = self.clock.monotonic()
        require_number(mono, "clock.monotonic")
        wall_elapsed = (self.clock.now() - self._wall_origin).total_seconds()
        if abs(wall_elapsed - (mono - self._mono_origin)) > self.settings.coordination.clock_uncertainty_seconds:
            raise ClockUncertain("process wall time diverged from its monotonic clock")
        bounds = self.leases.observe_time(handle)
        if not isinstance(bounds, TimeBounds) or (bounds.upper - bounds.lower).total_seconds() > self.settings.coordination.clock_uncertainty_seconds:
            raise ClockUncertain("server observation exceeds configured uncertainty")
        return bounds.at(self.clock.monotonic())

    def _ticket_status(self, row: Versioned, status: str) -> Versioned:
        value = row.to_mapping()["value"]
        value["status"] = status
        return self.store.replace("QueueTicket", value["ticket_id"], value, row.version)

    def _select(self, bounds: TimeBounds) -> str | None:
        valid = []
        for row in self.store.scan("QueueTicket", {"status": "waiting"}):
            value = row.value
            ticket = QueueTicket.from_mapping({name: value[name] for name in QueueTicket.__dataclass_fields__})
            if ticket.expires_at <= bounds.upper:
                try:
                    self._ticket_status(row, "expired")
                    self._trace("queue-expired", owner=ticket.owner_id, ticket_id=ticket.ticket_id)
                except Conflict:
                    continue
            else:
                valid.append(ticket)
        if not valid:
            return None
        chosen = min(valid, key=lambda ticket: (ticket.priority != "daily", ticket.enqueued_at, ticket.ticket_id))
        self._trace("queue-choice", owner=chosen.owner_id, priority=chosen.priority, ticket_id=chosen.ticket_id)
        return chosen.ticket_id

    @contextmanager
    def turn(self, owner_id: str, priority: str, deadline: datetime):
        require_text(owner_id, "owner_id")
        require_utc(deadline, "deadline")
        if self._active is not None:
            raise ValueError("a coordinator can have one active turn")
        mono = self.clock.monotonic()
        remaining = (deadline - self.clock.now()).total_seconds()
        if remaining <= 0:
            raise TimeoutError("turn deadline has expired")
        deadline_mono = mono + remaining
        bounds = self._time()
        ticket = QueueTicket(uuid.uuid4().hex, owner_id, priority, bounds.upper,
                             bounds.lower + timedelta(seconds=remaining))
        self.store.insert("QueueTicket", ticket.ticket_id, {**ticket.to_mapping(), "status": "waiting"})
        self._trace("enqueue", owner=owner_id, priority=priority, ticket_id=ticket.ticket_id)
        current = None
        try:
            while current is None:
                if self.clock.monotonic() >= deadline_mono:
                    raise TimeoutError("queue wait exhausted turn deadline")
                bounds = self._time()
                if self._select(bounds) == ticket.ticket_id:
                    try:
                        handle = self.leases.acquire(owner_id, int(self.settings.coordination.lease_seconds))
                    except Conflict:
                        handle = None
                    if handle is not None:
                        try:
                            # The lease serializes this second queue choice with every admission.
                            if self._select(self._time(handle)) != ticket.ticket_id:
                                self.leases.release(handle)
                            else:
                                current = Turn(self, handle, ticket, deadline_mono)
                        except BaseException:
                            # A finite acquired lease with an uncertain journal outcome is allowed to expire.
                            self._trace("loss", owner=owner_id, reason="turn initialization failed")
                            raise
                if current is None:
                    self.clock.sleep(min(QUEUE_POLL_SECONDS, max(0, deadline_mono-self.clock.monotonic())))
            self._active = current
            current._start_monitor()
            try:
                yield current
            except BaseException:
                current._lose("turn exited with an unconfirmed exchange outcome")
                raise
            finally:
                current._finish()
                self._active = None
        finally:
            try:
                latest = self.store.get("QueueTicket", ticket.ticket_id)
                if latest is not None and latest.value["status"] == "waiting":
                    self._ticket_status(latest, "finished")
            except Exception as error:
                if current is not None:
                    current._lose("queue cleanup outcome unknown: " + error_text(error))
                else:
                    self._trace("loss", owner=owner_id, reason="queue cleanup outcome unknown: " + error_text(error))

    def defer_until(self, instant: datetime) -> None:
        require_utc(instant, "not_before")
        if self._active is not None:
            self._active._defer(instant)
        else:
            deadline = self.clock.now() + timedelta(seconds=self.settings.http.exchange_deadline_seconds + 2*self.settings.coordination.lease_seconds)
            with self.turn("cooldown-"+uuid.uuid4().hex, "daily", deadline) as turn:
                turn._defer(instant)

    def block_requests(self, reason: Error) -> None:
        if self._active is None:
            raise OwnershipLost("a shared policy block requires the current issuer turn")
        self._active._block(reason)

    def exchange(self, context: RunContext, url: str, sender: Sender, *,
                 on_response: Callable[[BodyReceipt, Permit], None] | None = None) -> BodyReceipt:
        owner = context.execution_id + ":" + context.attempt_id + ":" + uuid.uuid4().hex
        with self.turn(owner, context.priority, context.deadline) as turn:
            permit = turn.reserve(uuid.uuid4().hex)
            turn.assert_current(permit)
            self._trace("request-start", owner=owner, epoch=permit.epoch, request_id=permit.request_id)
            receipt = sender.send(url, context, permit, cancellation=turn.cancelled)
            if not isinstance(receipt, BodyReceipt):
                raise ValueError("Sender must return a drained BodyReceipt")
            self._trace("request-end", owner=owner, epoch=permit.epoch, request_id=permit.request_id)
            try:
                if on_response is not None:
                    turn._response_policy(receipt, permit, on_response)
                turn.complete(permit, drained=True)
            except OwnershipLost:
                pass
        # Release/journal failures happen on context exit and must also retain the returned partial.
        if turn.loss_reason is not None:
            error = Error("ownership_lost", turn.loss_reason, True, None,
                          {"request_id": permit.request_id, "epoch": permit.epoch,
                           "next_allowed_at": turn.next_allowed_at.isoformat()})
            return replace(receipt, complete=False, error=error)
        return receipt


class Turn:
    def __init__(self, coordinator: Coordinator, handle: LeaseHandle, ticket: QueueTicket, deadline_mono: float):
        self.coordinator, self.handle, self.ticket, self.deadline_mono = coordinator, handle, ticket, deadline_mono
        self.cancelled, self._stop = SPAWN.Event(), threading.Event()
        self._wake = threading.Event()
        self._lock = threading.RLock()
        self._unsubscribe = None
        self._monitor = None
        self._permit = None
        self._dispatched = self._completed = self._closed = False
        self._drained = True
        self.loss_reason = None
        settings = coordinator.settings
        self.exchange_seconds = settings.http.exchange_deadline_seconds
        self.uncertainty = settings.coordination.clock_uncertainty_seconds
        if handle.acquired_upper is None or handle.ownership_until_upper is None or handle.observation is None:
            raise ClockUncertain("coordinator requires confirmed server upper acquisition/expiry bounds")
        bounds = coordinator._time(handle)
        self._row = coordinator.leases.read_journal(handle)
        previous = _journal(self._row.value, bounds)
        self.epoch = previous["epoch"] + 1
        self.earliest_safe = takeover_time(utc_value(previous["unsafe_until"]), handle.acquired_upper,
                                           self.exchange_seconds, self.uncertainty, previous["clean_release"])
        self._value = {**previous, "owner_id": handle.owner_id, "epoch": self.epoch,
                       "ownership_until": handle.ownership_until_upper.isoformat(),
                       "unsafe_until": max(utc_value(previous["unsafe_until"]), self._future_guard()).isoformat(),
                       "clean_release": False, "request_id": None}
        self._row = coordinator.leases.write_journal(handle, self._value, self._row.version)
        self._renew_at = coordinator.clock.monotonic() + settings.coordination.renew_every_seconds
        self._valid_until_mono = self._validity_mono(handle)
        coordinator._trace("acquire", owner=handle.owner_id, epoch=self.epoch, lease_id=handle.lease_id,
                           ownership_until=handle.ownership_until_upper.isoformat())
        coordinator._trace("takeover", owner=handle.owner_id, epoch=self.epoch, earliest_safe=self.earliest_safe.isoformat())

    @property
    def next_allowed_at(self) -> datetime:
        last = utc_value(self._value["last_start"]) if self._value["last_start"] is not None else None
        return next_start(last, utc_value(self._value["not_before"]), self.earliest_safe,
                          self.coordinator.settings.sec.requests_per_second)

    def _future_guard(self) -> datetime:
        return reservation_guard(self.handle.ownership_until_upper, self.exchange_seconds, self.uncertainty)

    def _validity_mono(self, handle: LeaseHandle) -> float:
        bounds = handle.observation.at(self.coordinator.clock.monotonic())
        return bounds.monotonic_at + (handle.observed_until-bounds.upper).total_seconds()

    def _lose(self, reason: str) -> None:
        with self._lock:
            if self.loss_reason is None:
                self.loss_reason = reason
                self.coordinator._trace("loss", owner=self.handle.owner_id, epoch=self.epoch, reason=reason)
            self.cancelled.set()
            self._stop.set()
            self._wake.set()

    def _require_live(self) -> None:
        if self._closed or self.cancelled.is_set():
            raise OwnershipLost(self.loss_reason or "turn is closed")
        mono = self.coordinator.clock.monotonic()
        require_number(mono, "clock.monotonic")
        request_deadline = self._permit.deadline_mono if self._permit is not None else self.deadline_mono
        if mono >= min(self.deadline_mono, request_deadline, self._valid_until_mono):
            raise OwnershipLost("turn/lease/exchange monotonic window expired")

    def _refresh(self) -> TimeBounds:
        self._require_live()
        bounds = self.coordinator._time(self.handle)
        self._row = self.coordinator.leases.read_journal(self.handle)
        value = _journal(self._row.value, bounds)
        if value["owner_id"] != self.handle.owner_id or value["epoch"] != self.epoch:
            raise OwnershipLost("sentinel epoch belongs to another turn")
        self._value = value
        self._require_live()
        return bounds.at(self.coordinator.clock.monotonic())

    def _write(self) -> None:
        self._row = self.coordinator.leases.write_journal(self.handle, self._value, self._row.version)
        self._require_live()

    def _tick(self) -> None:
        with self._lock:
            if self._closed or self.cancelled.is_set():
                return
            try:
                self._require_live()
                if self.coordinator.clock.monotonic() >= self._renew_at:
                    bounds = self._refresh()
                    possible_expiry = bounds.upper + timedelta(seconds=self.coordinator.settings.coordination.lease_seconds + RENEWAL_PREPARATION_CALLS*STORAGE_CALL_BOUND_SECONDS)
                    self._value["unsafe_until"] = max(utc_value(self._value["unsafe_until"]),
                        reservation_guard(possible_expiry, self.exchange_seconds, self.uncertainty)).isoformat()
                    self._write()
                    renewed = self.coordinator.leases.renew(self.handle)
                    if renewed.lease_id != self.handle.lease_id or renewed.ownership_until_upper is None or renewed.observation is None:
                        raise OwnershipLost("renewal did not confirm same lease and server upper bound")
                    self.handle = renewed
                    self._valid_until_mono = self._validity_mono(renewed)
                    self._value["ownership_until"] = renewed.ownership_until_upper.isoformat()
                    self._value["unsafe_until"] = max(utc_value(self._value["unsafe_until"]), self._future_guard()).isoformat()
                    self._write()
                    self._renew_at = self.coordinator.clock.monotonic() + self.coordinator.settings.coordination.renew_every_seconds
                    self.coordinator._trace("renew", owner=self.handle.owner_id, epoch=self.epoch,
                                           ownership_until=self.handle.ownership_until_upper.isoformat())
            except Exception as error:
                self._lose(error_text(error))

    def _start_monitor(self) -> None:
        clock = self.coordinator.clock
        if hasattr(clock, "subscribe"):
            self._unsubscribe = clock.subscribe(self._tick)
            return
        def monitor():
            while not self._stop.is_set():
                # Clear before reading deadlines so a concurrent reservation cannot lose its wake.
                self._wake.clear()
                if self._stop.is_set():
                    return
                deadline = self._permit.deadline_mono if self._permit is not None else self.deadline_mono
                wait = max(0, min(self._renew_at, deadline, self._valid_until_mono)-clock.monotonic())
                if self._wake.wait(wait):
                    continue
                self._tick()
        self._monitor = threading.Thread(target=monitor, name="sec-lease-renewal", daemon=True)
        self._monitor.start()

    def reserve(self, request_id: str) -> Permit:
        require_text(request_id, "request_id")
        with self._lock:
            try:
                if self._permit is not None:
                    raise OwnershipLost("each finite turn reserves one exchange")
                while True:
                    self._tick()
                    bounds = self._refresh()
                    if self._value["policy_block"] is not None:
                        raise PolicyBlocked(Error.from_mapping(self._value["policy_block"]))
                    target = self.next_allowed_at
                    delay = (target-bounds.lower).total_seconds()
                    if delay <= 0:
                        break
                    remaining = min(self.deadline_mono-self.coordinator.clock.monotonic(),
                                    self._renew_at-self.coordinator.clock.monotonic())
                    if remaining <= 0:
                        self._require_live()
                        continue
                    self.coordinator.clock.sleep(min(delay, remaining))
                mono = self.coordinator.clock.monotonic()
                bounds = bounds.at(mono)
                # Charge the latest admissible dispatch, not just the reservation instant.
                dispatch_seconds = 1 / self.coordinator.settings.sec.requests_per_second
                deadline_mono = min(self.deadline_mono, mono+self.exchange_seconds)
                start_before_mono = min(mono+dispatch_seconds, deadline_mono)
                dispatch_upper = bounds.upper + timedelta(microseconds=math.ceil((start_before_mono-mono)*1_000_000))
                if start_before_mono <= mono:
                    raise OwnershipLost("no positive dispatch window remains")
                end_upper = min(bounds.upper+timedelta(seconds=deadline_mono-mono), dispatch_upper+timedelta(seconds=self.exchange_seconds))
                self._value.update(last_start=dispatch_upper.isoformat(), request_id=request_id, clean_release=False,
                                   unsafe_until=max(utc_value(self._value["unsafe_until"]), self._future_guard(), end_upper+timedelta(seconds=self.uncertainty)).isoformat())
                self._drained = False
                self._write()
                permit = Permit(self.handle.owner_id, self.epoch, request_id, dispatch_upper, end_upper,
                                utc_value(self._value["unsafe_until"]), start_before_mono, deadline_mono,
                                self.next_allowed_at)
                self._permit = permit
                self._wake.set()
                self._require_live()
                self.coordinator._trace("reserve", owner=permit.owner_id, epoch=permit.epoch, request_id=request_id,
                                       next_allowed_at=permit.next_allowed_at.isoformat(),
                                       start_before_mono=permit.start_before_mono)
                return permit
            except PolicyBlocked as error:
                self._lose(error_text(error))
                raise
            except Exception as error:
                self._lose(error_text(error))
                raise OwnershipLost(error_text(error)) from error

    def assert_current(self, permit: Permit) -> None:
        with self._lock:
            try:
                self._tick()
                self._refresh()
                if permit != self._permit or self._completed or self._dispatched:
                    raise OwnershipLost("permit is stale, consumed, or from another epoch")
                if self.coordinator.clock.monotonic() >= permit.start_before_mono:
                    raise OwnershipLost("permit dispatch window expired")
                self._dispatched = True
            except Exception as error:
                self._lose(error_text(error))
                raise OwnershipLost(error_text(error)) from error

    def _response_policy(self, receipt: BodyReceipt, permit: Permit, callback) -> None:
        with self._lock:
            try:
                self._tick()
                self._refresh()
                if permit != self._permit or self._completed:
                    raise OwnershipLost("response policy does not match the held request turn")
                callback(receipt, permit)
                self._require_live()
            except Exception as error:
                self._lose("response policy was not confirmed: "+error_text(error))
                raise OwnershipLost(self.loss_reason) from error

    def _block(self, reason: Error) -> None:
        with self._lock:
            try:
                self._tick()
                self._refresh()
                if self._value["policy_block"] is None:
                    self._value["policy_block"] = reason.to_mapping()
                    self._write()
                self.coordinator._trace("policy-block", owner=self.handle.owner_id, epoch=self.epoch,
                                        reason=self._value["policy_block"])
            except Exception as error:
                self._lose("shared policy block was not confirmed: "+error_text(error))
                raise OwnershipLost(self.loss_reason) from error

    def complete(self, permit: Permit, drained: bool) -> None:
        if type(drained) is not bool:
            raise ValueError("drained must be boolean")
        with self._lock:
            if permit != self._permit or self._completed:
                self._lose("completion does not match the active permit")
                raise OwnershipLost(self.loss_reason)
            self._drained, self._completed = drained, True
            try:
                bounds = self._refresh()
                if not drained:
                    raise OwnershipLost("sender drain was not positively confirmed")
                # DNS/TLS/connect may delay wire activity beyond reservation; positive drain bounds it above.
                interval = timedelta(microseconds=math.ceil(1_000_000/self.coordinator.settings.sec.requests_per_second))
                self._value["not_before"] = max(utc_value(self._value["not_before"]), bounds.upper+interval).isoformat()
                self._write()
                self.coordinator._trace("drain-pacing", owner=self.handle.owner_id, epoch=self.epoch,
                                        not_before=self._value["not_before"])
            except Exception as error:
                self._lose(error_text(error))
                raise OwnershipLost(error_text(error)) from error

    def _defer(self, instant: datetime) -> None:
        with self._lock:
            try:
                self._tick()
                self._refresh()
                self._value["not_before"] = max(utc_value(self._value["not_before"]), instant).isoformat()
                self._write()
                self.coordinator._trace("cooldown", owner=self.handle.owner_id, epoch=self.epoch, not_before=self._value["not_before"])
            except Exception as error:
                self._lose(error_text(error))
                raise OwnershipLost(error_text(error)) from error

    def _finish(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                if self._drained and not self.cancelled.is_set():
                    bounds = self._refresh()
                    # Stop the turn irrevocably before any release operation, including an uncertain one.
                    self._closed = True
                    self._stop.set()
                    self._wake.set()
                    self.cancelled.set()
                    finalize = getattr(self.coordinator.leases, "release_clean", None)
                    if callable(finalize):
                        clean = {**self._value, "clean_release": True, "unsafe_until": bounds.upper.isoformat()}
                        self._row = finalize(self.handle, clean, self._row.version)
                        self._value = clean
                    else:
                        # Azure cannot atomically update this journal and acknowledge lease release.
                        self.coordinator.leases.release(self.handle)
                    self.coordinator._trace("release", owner=self.handle.owner_id, epoch=self.epoch,
                                            unsafe_until=self._value["unsafe_until"], drained=True,
                                            clean_release=self._value["clean_release"])
            except Exception as error:
                self._lose(error_text(error))
            finally:
                self._closed = True
                self._stop.set()
                self._wake.set()
                if self._unsubscribe is not None:
                    self._unsubscribe()
                self.cancelled.set()
        if self._monitor is not None and self._monitor is not threading.current_thread():
            self._monitor.join(STORAGE_CALL_BOUND_SECONDS)
