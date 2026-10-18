# Task16 offline harness implementation report

Status: **offline implementation ready for independent controller review; L12 not_run**. No real preparation, real run, SEC HTTP, accepted-root mutation, scheduling, or production code changes occurred. This report does not close the Task16 live acceptance gate.

## Scope and baseline

Implemented on the already authorized `codex/local-design` branch from `71c97d5`. Read the Task16 brief, exact Global Constraints, implementation review, and the APIs needed by this task; did not read the whole plan. Owned changes are the two external scripts, focused acceptance test module, three requested evidence records/templates, and this report. The untracked default config remains byte-identical, SHA256 `5949b1e717565115ecd47a101c8823d0dd7353e9d2eade79e77f887db0b86573`, and is never selected. `/Users/lowell/Projects/sec-edgar-local/data` still does not exist. The candidate config was read for intent/context only; real prepare/run was not invoked.

Selected reviewed native manifest remains `/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec/release.json`, payload `3ca50c78558bbf072a4eb75412af7d58a9e0f61b`. The native child test executes that actual installed interpreter with the required signature, verifies native runtime/config/harness, then deliberately refuses an invalid closed call before ledger/root creation. This is offline bootstrap evidence, not acquisition.

## Implemented behavior

- `scripts/accept-sec-native.py`: explicit prepare/run/verify interfaces. Prepare additionally requires `--config` and `--sole-issuer-confirmed`, avoiding any implicit selection of the old default config. Stdlib bootstrap re-execs into the selected installed interpreter before any application import. Prepare inventories missing or existing root state without creation/HTTP, freezes normalized quarterly/daily configs, the exact three source identities, full required listing scope, original 900-second UTC window, root/issuer/release/config/harness hashes, operating declaration, and a separate immutable prepared-selection hash receipt. Canonical edits before first run therefore refuse.
- `scripts/sec-acceptance-child.py`: fixed `[-I, absolute_child, --selection, ..., --call, ...]`; sets `sys.dont_write_bytecode=True` and `sys.pycache_prefix=os.devnull` before application imports. Verifies prepared selection, selected installed runtime, closed call and exact configs before creating the budget. Calls the actual installed `cli.main(argv)` with retained real sender and validator objects. No source path injection, fixture transport, fixture clock, URL rewrite, permit extension, parser exception, retry-policy replacement, or production flags.
- SQLite budget uses the five specified tables, exact selection/limit metadata, `BEGIN IMMEDIATE`, bounded two-second busy handling, selection checks before/after transactions, and durable global admissions. Every send reserves one attempt plus full 67,108,864-byte received ceiling; five total admissions per URL and 20 URLs apply across restarts. Complete positively drained returns settle to actual bytes. Incomplete receipts, exceptions, stale permits and crashes retain full charge. Expanded validation reserves 536,870,912 bytes on each real call, settles only successful validator counts, and retains failed charges. No crash recovery refunds uncertain reservations.
- Sender identity is read from the production `TransportAttempt` admission written by `_AuditedSender` before wrapper dispatch: exact permit request ID, `state.attempt_key(context)`, and production ordinal. Harness-only fake boundaries use injected identities in offline tests. Actual known socket-start traces, receipts and entity bytes are retained separately from charged admissions; unavailable uncertain crash traces are disclosed and never grant admissions.
- Run rechecks live discovery quarter/backlog scope before ledger/root mutation and again before each discovery. Quarterly discovery/selected collection precede daily discovery. Production `read_parent` validates complete retained listing ancestry; production `project_member` creates exact singleton immutable worksets. No broad workflow runner is called. Each selected accepted body is reopened in a fresh process, exact result replay is checked, then normal transform/publication runs. Captures/read evidence assert nonempty exact schema, unique canonical keys, source hashes/counts and generation counts. Pending discoveries and unaccepted/approval/quarantine outcomes remain separately visible.
- Every dispatch freezes exact public argv before launch, then retains independent stdout/stderr, exit/drain/PID/argv, and durable result hashes. Existing completed calls replay unchanged IDs/config/intent/deadline. A safely ended unfinished invocation may use a new attempt on restart; ambiguous/no-receipt or uncertain drain refuses automatic retry. UTC boundary never resets. Per-process elapsed watchdog uses remaining original duration; cancellation/forced reaping never claims positive drain.
- Verify is offline: it reopens retained command results, streams, every archived frozen capture and validated rows, and budget evidence. L12 status requires genuine native acquisition/persistence/restart/reuse/exact replay plus at least one accepted genuine publication/capture/nonempty read. A successful download or offline fixture cannot pass L12.

## Owner-approved scope clarification

The exact prescribed original two validator aliases would undercount real expansion. `collection.py:207` passes a non-None Source to `client.fetch`; `download.py:195` calls its imported `validate_envelope`; then `collection.py:209` validates again. The controller asked the owner, and the owner explicitly approved **“Add the third wrapper (Recommended)”**. The external bootstrap therefore wraps `download.validate_envelope`, `collection.validate_envelope`, and `etl.transform.validate_envelope` with the same retained real `validation.validate_envelope`. No approved spec/plan bytes or production modules were edited. The focused tests exercise all three real references against one synthetic valid body and assert three expanded-byte charges.

The controller also specified conservative retention for every incomplete returned receipt even after a positive child join. This implementation retains that full reservation; the stricter choice cannot increase admissions. Sole-issuer confirmation was already authorized by the owner; it was not re-requested.

## Invariants and TDD evidence

Before implementation, planned structural invariants (closed selection/call schemas), relational invariants (same release/config/root/issuer and exact durable result), bounds (full-ceiling admission, global concurrency/retry/window limits), and reproducibility (same ledger/window/IDs across fresh processes). Offline maps, fake receipts, local child processes and synthetic fixture bodies falsify these invariants; no live network is needed.

Exact focused command, from repository root, with the existing offline cache selected because the default home cache is sandbox read-only:

```sh
UV_CACHE_DIR=/private/tmp/sec-edgar-local-uv-cache uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p test_acceptance_selection.py -v
```

Retained streams are in `/Users/lowell/Projects/sec-edgar-local/.sdd/1-sec-edgar-local-spec/task16-offline-logs/`:

| Log | Actual result and interpretation |
| --- | --- |
| `01-red.log` | Setup-only refusal: uv could not create temporary cache lock under `~/.cache/uv`; not counted as intended RED. |
| `02-red.log` | Intended initial RED: 15 assertion failures, each identifying missing acceptance-only selection/reservation harness. |
| `03-green-core.log` | Intermediate failure: temporary test paths used macOS `/var` alias instead of normalized `/private/var`; fixed test setup. |
| `04-green-core.log` | 15 tests passed; exposed SQLite ResourceWarnings, which were corrected by closing connections explicitly. Not final pristine verification. |
| `05-red-process.log` | Missing supervisor contract plus native executable path normalization issue; native `venv/bin/python` must retain its exact executable spelling, not dereference its symlink. |
| `06-green-process.log` | 18 tests passed, including native child refusal and local process exit/drain propagation. |
| `07-red-integration.log` | Setup-only missing synthetic fixture directory; corrected before intended integration RED. |
| `08-red-integration.log` | Intended integration RED: read verifier incorrectly treated nested `ObservationRef` fields as flat. Real production fixture publication reached the verifier and exposed it. |
| `09-green-integration.log` | 21 tests passed in 7.559 seconds. Production fixture discover/project/collect/replay/reuse/transform/publish/capture/read completes for all three selected source identities. |
| `10-red-preparation.log` | Missing prepared hash receipt contract exposed. |
| `11-green-preparation.log` | 25 tests passed in 9.792 seconds, including independent processes crashing immediately after budget reservation; charges survive and remain unsent. |
| `12-red-scope.log` | Missing recheck before daily dispatch exposed; it reached the fake invocation when it should refuse widened backlog scope first. |
| `13-green-scope.log` | 27 tests passed in 9.910 seconds, including stale-scope refusal and timeout never claiming safe drain. |
| `14-red-request-identity.log` | Wrapper lacked production identity injection; intended exact request identity/ordinal contract failed. |
| `15-green-request-identity.log` | 29 tests passed in 10.006 seconds, including read-only lookup of actual durable production TransportAttempt and safely expired unsent admission. |
| `16-final-focused.log` | **29 tests passed in 9.917 seconds; zero failures/errors/skips/warnings.** Final focused verification after report/template integration code changes. |

The shell wrappers captured streams using redirection and then `tail`, so their shell completion code alone is not test authority. The retained unittest summaries and complete streams above establish each actual result. The final command's complete output ends `Ran 29 tests in 9.917s` / `OK`.

Additional fresh verification: AST parsing of both scripts/test module; both JSON evidence templates parse; `git diff --check`; default config hash and absent approved root checked. No whole approximately 56-minute suite was repeated because production files, dependencies, lock, runtime payload and default checker were unchanged. No genuine acceptance driver was added to the default invocation.

## Self-review and limitations

Applied clean-code judgments in owned new code: named immutable policy ceilings/limits (G25), explicit selection/request/reservation names (N1/N4), separate selection validation, atomic budget authority, process supervision, production-result checks, orchestration and captured reads (G30/G34), and crash/last-response/concurrency/replay boundaries (T1/T5/T6). No adjacent production refactor or out-of-scope tidy was performed. The driver is intentionally one external file, with a small bootstrap child; its roughly 1,000 lines reflect the mandated durable budget, exact native call supervision and evidence workflow. No module splitting outside assigned ownership was introduced.

Self-review caught and corrected native executable symlink normalization, SQLite connection lifetime warnings, ObservationRef nesting, preparation-before-first-run hash authority, daily scope rechecking, and exact production request identity. Source changes remain wholly external. Strict runtime preflight supplies installed-origin verification; no path injection is used.

The native child integration deliberately refuses before calling genuine CLI acquisition. The end-to-end source/projection/publication flow uses the existing explicit fixture acquisition and real production APIs with a fake invocation boundary. This proves harness orchestration and invariants offline; it does **not** prove genuine transport behavior or L12. Known actual sends are trace-based; a crash can leave unavailable traces, conservatively represented by full charged reservations. Independent review must assess the full external harness and these limits before preparation/live execution.

## Handoff

Review these committed files and the final focused stream. Do not run actual prepare/run until review findings are resolved. Then prepare a fresh actual record using the explicit selected manifest/candidate config/approved root and owner sole-issuer declaration, inspect it, and only then execute its original 900-second bounded window. Replace the non-executable selection template and not-run checkpoint only with actual immutable references/status. Keep all earlier evidence, release payloads, default config and original source repository unchanged.

## Independent review round 1 corrections

The independent review in `task-16-harness-review.md` identified two Important implementation defects in commit `2b64551`: direct driver operations were outside the watchdog, and offline verification trusted pass-defining report booleans and omitted failed/limited launches. Both findings were reproduced and isolated before corrections using receiving-code-review, systematic-debugging and the existing TDD workflow. No genuine preparation/run/HTTP or production edit occurred.

The full acquisition phase now executes in a fresh selected native driver process under the outer stdlib supervisor. The outer process establishes the immutable remaining UTC and monotonic budget before dispatch; the worker performs native preflight/config verification, inventory, projection, acquisition supervision, captures, validated reads, evidence derivation and final inventory within that same boundary. Runtime preflight is inside this worker rather than an unbounded parent operation. Its internal immutable worker request binds selection/hash/path and the actual supervisor PID. The public low-level child signature is unchanged. A blocked C/IO operation in the worker can be terminated by the OS supervisor even when a Python signal handler could not run. Cancellation and forced cleanup are retained as unconfirmed drain, with known unfinished CLI groups cancelled and all uncertain ledger charges preserved. Watchdog receipts retain argv/PID, streams/hashes, original-window timestamps, elapsed monotonic duration and remaining budget. Restarts never reset the selected window.

Each CLI launch now freezes a dispatch record and a separate immutable dispatch-registry reference **before launch**, then records PID, independent streams and actual exit/drain regardless of whether the command produces a durable result. Limited/failed attempts therefore remain in the filesystem-derived inventory; missing launches, streams, dispatch references or result copies refuse verification. Original first-attempt receipts are checked against the complete launch inventory.

Offline verification reconstructs the latest evidence snapshot from all frozen calls/launches and historical report references. It reads SQLite in read-only mode and reconciles selection/limits, request URLs/ordinals, actual production TransportAttempt identities, every full-ceiling reservation, successful expanded-validation settlement receipts, positively drained complete received-byte refunds, transport file hashes/counts and known socket starts. It recomputes charged totals from reservations and refuses unconfirmed recovery refunds. Frozen production contexts are rebound through the actual selected effective config. No verifier recovery refunds or ledger mutations were added.

Pass-defining selected facts are derived from production `read_member`/`read_parent`, exact singleton snapshots and verified raw hashes, independent matching replay PIDs/results, a distinct reuse call with identical retained snapshots, and normal transform/publish results bound to the same selected snapshot workset. Captures must match the exact published quarter/generation/manifest, source snapshot provenance and validated frozen read. Capture inventory rejects unrelated valid artifacts. A published read can satisfy L12 only for a selected source that also has matching native live transport bytes, persistence, replay and reuse. Report flags/status must equal these independently derived facts; they are no longer evidence authority. Complete fixture evidence remains explicitly L12-incomplete.

The exact guarded command remains the command quoted above. New retained streams:

| Log | Result |
| --- | --- |
| `17-review-round1-red.log` | **31 tests, six intended failures.** Blocking C capture took `0.7518843750003725` seconds under 0.1 seconds remaining, violating the test's 0.5-second upper bound. Five report-only/missing-evidence variants incorrectly returned 0. |
| `18-review-round1-initial-green.log` | Intermediate verification exposed malformed registry lookup returning KeyError rather than a deliberate closed-schema refusal; corrected before the next gate. |
| `19-review-round1-integration.log` | 31 tests passed in 11.035 seconds; complete real fixture flow now inventories all 17 frozen launches and derives three selected acquisitions/reuses/replays/publications. Removing replay/reuse removes the corresponding derived facts. |
| `20-review-round1-audit.log` | 34 tests passed in 11.083 seconds, with two ResourceWarnings from test-owned SQLite corruption probes. Closed those test connections explicitly; this was not the final pristine gate. |
| `21-review-round1-full-verifier.log` | 34 tests passed in 12.922 seconds. Added a complete fixture-backed independent-verifier run returning L12-incomplete plus omitted replay/reuse, altered budget, missing execution, and unrelated valid capture negatives. |
| `22-review-round1-final-focused.log` | **34 tests passed in 12.712 seconds, zero failures/errors/skips/warnings.** This is the final test run after all correction code changes, including exact config rebinding and distinct replay PID checks. |

Self-review focused on full-boundary cancellation and every evidence relationship from frozen call through transport admission, raw snapshot, reuse/replay, transform, publication and capture. Additional focused tests prove failed/limited launch inventory, conservative crash charges, rejected unconfirmed refunds and tampered transport hashes. The full verifier's positive offline case remains incomplete because its explicit fixture transports cannot establish genuine native acquisition. No new live features, provider integration, production flags, parser allowances or timing relaxation were introduced. The driver grew to hold the required external supervision and evidence readers; no production/module split was introduced during this correction.

L12 remains **not_run**, and the harness remains pending scoped independent re-review. The selected release/payload, original window policy, preserved default config and absent approved data root remain unchanged. No full default suite was repeated because only external harness/test/evidence files changed. Fresh AST/JSON checks, `git diff --check`, default-config hash and absent-root checks accompany the final focused gate.
