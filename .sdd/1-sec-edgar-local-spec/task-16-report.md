# Task16 offline harness implementation report

Current checkpoint: the original bounded genuine run and original offline verification both ended **incomplete, exit 12**. A native-runtime representation false negative is isolated and corrected offline; the separately versioned supplemental analyzer is implemented but **has not been executed against the actual run**. Scoped review is required before that adjudication. Earlier sections below retain their original checkpoint context.

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


## Offline native-runtime false-negative correction and supplemental analyzer

The original bounded genuine attempt used immutable selection SHA256 `38bf7c024e0fd5ac3bd9724e7c05a7f8876308ae90b79e42d4391d592f36b6cc` and UTC window `2026-10-18T23:23:15.020920+00:00` through `23:38:15.020920+00:00`. Its original report `/private/tmp/sec-local-task16-acceptance-20261018/run-b0bfc28dcc7d48e686b12b5253d8a414.json` remains incomplete, exit 12, SHA256 `8f9db79396e792f70b4d1435c272213a46023619ef27510a4b17b11b059677b1`. The original offline verification completed exit 12 at `/private/tmp/sec-local-task16-acceptance-20261018/verification-7fee6a8a509a482d949f9cd78cec9a79.json`, SHA256 `6842f951917b98876b0630279dbdcf9383b2d2c1a14a89c426ecffbb53ca9d8a`. Neither record nor the original watchdog is rewritten or relabeled as an original success.

Read-only diagnosis found all ten native admissions had matching typed command contexts, complete positively drained receipts and one socket start. All three selected entity hashes matched retained snapshots. The false negative was exactly `context.runtime != native_descriptor(...)`: runtime is the real production `FrozenMapping` dataclass, whose dataclass equality rejects a plain `dict` even with identical values. All ten direct comparisons were false while `context.to_mapping()['runtime']` comparisons were true. The driver correction is exactly that one comparison expression; release/mode/context/drain/budget/publication criteria are unchanged.

Before any driver edit, both original scripts were archived under `/private/tmp/sec-local-task16-acceptance-20261018/harness-original/` and verified against the original selection:

- `accept-sec-native.py`: `ba05e8c53ba83bb80987d16d499915d358958faa74215a008b3008033f3a5f9e`.
- `sec-acceptance-child.py`: `ff8e89012d04a0bb0811f90c0260d11eeb3e4797544e150fa97594f5e7c68bb4`.

The controller confirmed original verification session 53307 had completed before authorizing the driver edit. Original selection bytes, original report bytes, archived script bytes and default config hash were freshly checked after the correction. No new HTTP, selection, acceptance window, attempt, retry or genuine workflow was executed.

The new external `scripts/verify-sec-native-adjudication.py` is a narrow offline analyzer. It requires explicit selection, original report, original verification and a new output beneath the evidence directory's `adjudications/` subdirectory. It establishes native isolated/cache policy and verifies the same installed release/config/root/issuer, while checking historical script bytes at their exact archived paths against their original selected hashes. The temporary historical read-verification map is never serialized as a replacement selection and is never passed to a run/CLI acquisition path. Standard run/child verification continues checking the original selected current-script paths and refuses the changed harness. A native child regression proves that refusal occurs before budget or root creation.

The supplemental analyzer reuses the same independent frozen-call/launch, production-admission, conservative ledger, source snapshot/replay/reuse and selected transform/publication/capture readers. It requires exact original command/budget snapshots, original verification/report hash linkage, unchanged positively drained UTC/monotonic watchdogs and original driver exit 12. Only the six fields affected by native classification may differ: the four native/persistence/reuse/replay booleans, `selected_native`, and qualified `published_reads`. Every other proof field must remain identical. The separate output records original report/verification/status/exit, selected and archived original script hashes, corrected driver and analyzer hashes, unchanged budgets and the independently derived status. The analyzer never silently equates the original exit 12 with exit 0.

TDD used the same exact guarded focused command quoted earlier:

| Log | Result |
| --- | --- |
| `23-native-adjudication-red.log` | **36 tests, three intended failures.** The public `derive_source_proof` returned `selected_native=[]` for actual native `RunContext`/`FrozenMapping` instances and fake complete transport boundaries; two supplemental analyzer contracts were missing. This reproduced the native false negative through the public proof function, not merely a helper equality assertion. |
| `24-native-adjudication-green.log` | 36 tests passed in 14.764 seconds after the one-expression fix and separate analyzer implementation. Native positive classification succeeds; wrong-release, fixture-mode and mismatched-context negatives remain excluded. |
| `25-native-adjudication-integration.log` | **36 tests passed in 15.719 seconds, zero failures/errors/skips/warnings.** Also proves changed-harness refusal in an actual selected native child and a full supplemental analysis over a synthetic original fixture archive. That synthetic supplement retains original exit/status 12/incomplete and derives incomplete, without modifying its original report. |

The original explicit fixture classifier remains false and cannot satisfy L12. The new native positive tests use real production native descriptor/context types with explicitly fake transport boundaries over synthetic fixture publications. They are offline proof of the correction and are not genuine acquisition evidence.

Fresh static checks parse both harness scripts, the new analyzer and the test module; `git diff --check` passes. Corrected driver SHA256 is `6700ea7470ad1ee3b1e774fd03014ddd23d3b458e6c19450bfc43a7a7a37101e`; supplemental analyzer SHA256 is `0a1d6b5b5aa218fc4d8ac09084c54e78fa05d8776ab79891aac306bf025649ab`. The default config remains byte-identical. No production file, dependency, lock or installed release was changed; no full default suite was repeated.

**Review gate remains closed for actual adjudication.** The actual evidence directory still has no `adjudications/` output. After scoped review accepts the corrected reader and analyzer, the controller can run the separately versioned offline command against the original selection/report/verification and save a supplemental record. The original run and original verification remain incomplete regardless of any later supplemental analysis status. Observed 17 launches, 21 publications/captured reads and 73 unselected pending sources describe this bounded attempt; they do not establish historical coverage.


## Actual bounded SEC attempt and final evidence record

The preceding gate was subsequently closed by independent review: commit `782e40a` received Approved/no findings in `task-16-adjudication-review.md`. Only then did the controller execute the separate actual offline adjudication, session 48446. It completed exit **0**, independent status **pass**, reasons `[]`, at `2026-10-18T23:46:17.559239+00:00`. Supplemental SHA256 is `1e1eff2c426235212c976b047aeb3799be317b067da730bfe9f2f0d3930af252`. The earlier paragraph saying no adjudication output exists describes the earlier review checkpoint and is superseded by this actual result.

**L12 passes on the reviewed supplemental analysis of the original genuine acquisition.** Original run session 45878 and original verification session 53307 both remain incomplete, exit 12. Their bytes/status/watchdog were retained unchanged. No second HTTP attempt, selection, window reset, parser relaxation, production change or workflow rerun occurred during correction/adjudication/final evidence assembly. The supplement independently derives all three selected native sources and 21 qualified nonempty published reads under unchanged bounds. Final Task16 evidence review remains pending. No historical completeness or overall final-readiness claim is made here.

The controller's exact retained command record is `/private/tmp/sec-local-task16-acceptance-20261018/controller-commands.json`, SHA256 `e966ff6f4b809b09a497b4103575ec0cda94de3d726dcad6abcc7cdba8f94596`. Shell invocations used the relative release executable with repository cwd; these equivalent absolute argv arrays are recorded there. Low-level per-child argv/result/stream receipts remain the strongest individual launch evidence.

```json
{
  "name": "prepare",
  "argv": [
    "/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec/venv/bin/python",
    "-I",
    "-B",
    "-X",
    "pycache_prefix=/dev/null",
    "/Users/lowell/Projects/sec-edgar-local/scripts/accept-sec-native.py",
    "prepare",
    "--release",
    "/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec/release.json",
    "--root",
    "/Users/lowell/Projects/sec-edgar-local/data",
    "--evidence",
    "/private/tmp/sec-local-task16-acceptance-20261018",
    "--config",
    "/private/tmp/sec-local-task15-renewal/candidate-config.json",
    "--sole-issuer-confirmed"
  ],
  "observed_exit": 0,
  "exec_session": null
}
```

```json
{
  "name": "run",
  "argv": [
    "/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec/venv/bin/python",
    "-I",
    "-B",
    "-X",
    "pycache_prefix=/dev/null",
    "/Users/lowell/Projects/sec-edgar-local/scripts/accept-sec-native.py",
    "run",
    "--selection",
    "/private/tmp/sec-local-task16-acceptance-20261018/selection.json"
  ],
  "observed_exit": 12,
  "exec_session": 45878
}
```

```json
{
  "name": "original_verify",
  "argv": [
    "/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec/venv/bin/python",
    "-I",
    "-B",
    "-X",
    "pycache_prefix=/dev/null",
    "/Users/lowell/Projects/sec-edgar-local/scripts/accept-sec-native.py",
    "verify",
    "--selection",
    "/private/tmp/sec-local-task16-acceptance-20261018/selection.json"
  ],
  "observed_exit": 12,
  "exec_session": 53307
}
```

```json
{
  "name": "offline_adjudication",
  "argv": [
    "/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec/venv/bin/python",
    "-I",
    "-B",
    "-X",
    "pycache_prefix=/dev/null",
    "/Users/lowell/Projects/sec-edgar-local/scripts/verify-sec-native-adjudication.py",
    "--selection",
    "/private/tmp/sec-local-task16-acceptance-20261018/selection.json",
    "--report",
    "/private/tmp/sec-local-task16-acceptance-20261018/run-b0bfc28dcc7d48e686b12b5253d8a414.json",
    "--original-verification",
    "/private/tmp/sec-local-task16-acceptance-20261018/verification-7fee6a8a509a482d949f9cd78cec9a79.json",
    "--output",
    "/private/tmp/sec-local-task16-acceptance-20261018/adjudications/reviewed-native-runtime.json"
  ],
  "observed_exit": 0,
  "exec_session": 48446
}
```

The original UTC window remained `2026-10-18T23:23:15.020920+00:00` to `23:38:15.020920+00:00`. The watchdog records positive drain, completed outcome, original returncode 12, monotonic elapsed 602.3843270420039 within 883.374256 remaining seconds, ending `23:33:34.032853+00:00` (619.011933 seconds from selection start). All 17 native low-level launches drained. There were 14 frozen calls including three exact fresh-process collect replays. Native bootstrap/cache/import policy and owner-confirmed sole-issuer operating declaration remained effective.

Observed global consumption: 10 charged admissions, 10 actual socket starts, 10 distinct canonical URLs (seven listings/three bodies), ordinal 1 for every request, zero retries and zero charged-but-unsent admissions. Received bytes 4,946,565/134,217,728; expanded validation bytes 102,593,106/1,073,741,824. All 19 reservations (ten received/nine expanded) settled; unchanged per-response ceilings applied. All three body raw hashes and immutable snapshot/replay/reuse links are recorded in the machine evidence. These actual observations do not replace offline conservative-crash/expired-permit coverage.

Quarterly 2024Q1 acquisition/replay/reuse exited 0, transform exited 7 with whole-source quarantine for conflicting duplicate logical key at line 88043, and publish exited 3 for incomplete transformed workset. One durable conflict error is retained; total source conflicts are not enumerated because the parser stops at first conflict. The old retained-fixture count 51 is not this source's count. Daily 2026-10-14 and 2026-10-15 acquired/replayed/reused/transformed/published successfully, producing six and fifteen generations respectively. Their source rows/distinct keys are 3,220/3,182 and 3,652/3,562. All 21 captures were validated nonempty with the exact schema and matching source/generation provenance. There are 16 affected quarters; 9,917 summed rows include repeated generations, while latest per-quarter captured generations total 6,744 rows. No broad historical coverage is inferred.

Preparation inventoried absence of the approved live root; the first operation created that exact root. Quarterly work preceded daily discovery. Previous/current daily quarter listings discovered 75 sources; only the two selected singleton body worksets were collected, leaving 73 pending unselected sources and no failed directories. No daily/backfill runner was used afterward. `daily.start_date` remained the handoff input, not a strict selected-body range. The full initial and ending inventories and pending-source identities are recorded.

The committed selection is an exact byte copy of the original frozen selection, including its historical harness hashes. The machine evidence includes release/wheel/interpreter/dependency identity, absolute normalized configs and separate input-byte hash, all command arrays/results/streams, every admission/ordinal/reservation and hashed transport boundary, all raw/snapshot/observation/publication/capture references, quarantine error reference, preserved default config/spec/plan/lock hashes, and complete observed output inventories. Raw headers stay in retained immutable raw references; their values are omitted from the summary.

Fresh finalization check (read-only hashing/static consistency, not another harness verification or adjudication):

```sh
python3 /private/tmp/task16-final-static-check.py > .sdd/1-sec-edgar-local-spec/task16-offline-logs/26-actual-evidence-static.log 2>&1
git diff --check
```

Retained exact output:

```text
evidence: 257 files, 6175866 bytes, every retained hash matched
live_root: 155 files, 12203317 bytes, every retained hash matched
sec-acceptance-selection.json 38bf7c024e0fd5ac3bd9724e7c05a7f8876308ae90b79e42d4391d592f36b6cc 3884
sec-acceptance.json 5bae677e97307e5cf7c73b31f6651310b7420aeaafff2fd7ef255bed77bc1de4 586222
sec-acceptance.md e7ce0e199a58cd480b4d8c9cfb2ad065fda9dd529ca6d5028e4cd3e545c9f42a 10939
PASS: 422 unique file references/hashes; exact selection/archive/config preserved; 17 launches, 10 sends, 19 settlements, 3 native sources, 21 reads, 73 pending; original exit12/incomplete and separate supplemental pass retained; no cookie values in machine summary
```

The check parsed the committed JSON, compared every absolute/logical file reference against actual retained SHA256/size, checked complete file-set inventory equality, exact selection/archive/default-config hashes, all actual totals/counts/status distinctions, and absence of cookie values in machine evidence. It returned 0; `git diff --check` returned 0 without output. Inventory is 257 evidence files/6,175,866 bytes and 155 live-root files/12,203,317 bytes. This records observed outputs at finalization; retained evidence/data are not automatically cleaned.

The final source-code verification remains retained log `25-native-adjudication-integration.log`: 36 guarded offline tests passed in 15.719 seconds, zero failures/errors/skips/warnings. No code changed after that gate; this final commit changes evidence/report/log only. No whole default suite or actual analyzer was repeated for documentation. Static checker SHA256 is `def6274f1ceb263a02fb5005b768f9481d72948e007e86d14191db112e95b71a`.

Self-review checked that original incomplete flags were not overwritten, the supplemental pass is separately identified, all three native sources are linked to reviewed analysis, acquisition and ETL statuses stay separate, quarantine/pending outcomes remain visible, exact budgets/ordinals/drain are retained, and row counts distinguish successive reads from latest captured totals. The selected release/payload/spec/plan/lock/default config remain untouched. Final independent Task16 review is the next gate.
