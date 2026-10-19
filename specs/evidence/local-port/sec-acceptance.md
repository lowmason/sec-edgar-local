# Bounded genuine SEC native acceptance

**L12: pass, established by the reviewed offline adjudication of the original genuine SEC attempt.** The original driver run and original verification both remain **incomplete, exit 12**. The supplemental analyzer completed **exit 0**, with independently derived status `pass` and no reasons. No acquisition was repeated and the selection/window was never reset. Final independent Task16 evidence review is pending; this record does not claim complete historical coverage.

The exact frozen [selection](sec-acceptance-selection.json) has SHA256 `38bf7c024e0fd5ac3bd9724e7c05a7f8876308ae90b79e42d4391d592f36b6cc`. The [machine evidence](sec-acceptance.json) records every retained command argv/result/stream, transport and admission, source hash, generation/read, normalized config, and the complete observed file inventory. Genuine bodies and durable stores remain in the selected ignored root `/Users/lowell/Projects/sec-edgar-local/data`; external evidence remains in `/private/tmp/sec-local-task16-acceptance-20261018`. Retain both directories for later offline evaluation.

## Native payload and immutable bounds

The selected installed release is `fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec`, payload revision `3ca50c78558bbf072a4eb75412af7d58a9e0f61b`, application wheel SHA256 `6ab438e51085ea35f8d23273a2f879738fd963af9609a1a328faa89b9567fd0f`. Its manifest SHA256 is `99210dd33b3beffb847735385a11d05d4093b223ac9df96784d71458a6ca1a4b`. CPython 3.14.0 on macOS arm64 used the non-editable native venv, Requests 2.34.2 and PyArrow 25.0.1. The external harness correction did not relabel or change this release. Task15 recorded uv 0.13.1 and uv_build 0.12.24; exact release dependency identity is retained in the machine evidence.

Both normalized live configs use that release, the same absolute data/log roots and issuer binding. Quarterly config SHA256 is `32b4da638464758c2926fc9040e207696a081d452b2af3813ddd36d179441740` with start/end 2024Q1; daily config SHA256 is `088403cb55f5b6541502cb07678c5757ffdb13b92fac52a52b6aa663177b7d4d` with open backfill end and daily handoff 2026-10-01. Input config bytes have SHA256 `2a940f236b2bf37dc1fb4fbef03d0da3c98f663c311231b225961b0c58c3dbbb`. The preserved untracked default config, SHA256 `5949b1e717565115ecd47a101c8823d0dd7353e9d2eade79e77f887db0b86573`, was never selected.

The original UTC window was **2026-10-18 23:23:15.020920–23:38:15.020920** (900 seconds). The worker ran 23:23:31.646607–23:33:34.032853 UTC; measured monotonic elapsed was 602.384327 seconds within its remaining 883.374256-second budget. Completion occurred 619.011933 seconds after the selection start, with positive drain and no cancelled CLI groups. The run report ended 23:33:33.977201 UTC. The owner confirmed that other project-budget collectors remained stopped throughout this window. Namespace, owner User-Agent, 3 requests/second, one collector, 60-second leases, 20-second renewal and 2-second uncertainty were preserved.

| Bound | Declared maximum | Observed |
| --- | ---: | ---: |
| Distinct canonical URLs | 20 | 10: seven listings and three bodies |
| Charged request admissions | 100 | 10 |
| Actual sent requests | Within charged admissions | 10; no charged-but-unsent admissions |
| Attempts per URL | 5 | 1 each; no retries |
| Received bytes | 134,217,728 | 4,946,565 |
| Expanded validation bytes | 1,073,741,824 | 102,593,106 |
| Quarterly / daily bodies | 1 / 2 | 1 / 2 |

All 19 reservations settled: ten received-byte and nine expanded-byte reservations. Expanded accounting includes repeated real validation, not merely unique bodies. The unchanged per-response ceilings were 67,108,864 received and 536,870,912 expanded bytes. Every retained HTTP receipt is complete with positive drain. There were no uncertain charges or safely expired unsent permits in this particular run; the offline tests cover those cases. Actual sends and admission charges remain distinct fields.

## Actual source outcomes

All three selected sources acquired genuine canonical SEC bytes, persisted matching raw hashes, reopened/reused the same immutable snapshot in a fresh native process, and replayed the exact original result with matching call/config/IDs/intent/deadline. There were 14 distinct frozen low-level calls and 17 fresh launches, including three exact collect replays. All launches positively drained.

| Source | Received bytes | Acquisition / exact replay / reuse | Transform | Publish / validated capture |
| --- | ---: | --- | --- | --- |
| Quarterly 2024Q1 | 4,262,821 | exit 0 / 0 / 0 | exit 7; one quarantined source | exit 3; zero generations |
| Daily 2026-10-14 | 289,582 | exit 0 / 0 / 0 | exit 0; one accepted source | exit 0; six generations / six reads |
| Daily 2026-10-15 | 329,651 | exit 0 / 0 / 0 | exit 0; one accepted source | exit 0; fifteen generations / fifteen reads |

Exact raw SHA256 values are:

- 2024Q1: `ba4aa3d405d4d603c5e881c2db023070b9b9f8eebc80a361dc61d831353453cb`.
- 2026-10-14: `74a2830b81ee2ad818321981b68c15539c86eb6e268f57580d94894ea6e14a02`.
- 2026-10-15: `83bfddd88a0d3880074c479a8559db1d2c6113d82ed33220cf6084064ec2a608`.

Production `sec-index-parser-v1` / `sec-index-v1` rejected quarterly 2024Q1 at line **88043**, reason **conflicting duplicate logical key**. Its durable result retains one detected conflict error and one whole-source quarantine. The parser stops at the first conflict; total source conflicts are not enumerated. The earlier count of 51 conflicting retained observations belongs to different retained specimens and is not this run's count. Publication correctly refused the partial transformed workset. No duplicate winner, force bypass or parser relaxation was applied.

The accepted daily observations contain 3,220 / 3,652 source rows and 3,182 / 3,562 distinct logical keys respectively. Together they produced **21 generations across 16 filing quarters**, each captured once and read through the production validated reader. Every read was nonempty, used the exact ten-field schema, and retained manifest/data/change hashes and matching source/generation counts. The reads sum to **9,917 logical rows across successive generations**; this includes repeated reads of updated quarters. The latest captured generation per quarter sums to **6,744 rows**. These are observed output counts, not historical completeness claims.

| Quarter | Latest captured rows |
| --- | ---: |
| 2021Q1 | 4 |
| 2021Q2 | 5 |
| 2021Q3 | 11 |
| 2021Q4 | 12 |
| 2022Q1 | 14 |
| 2022Q2 | 1 |
| 2023Q3 | 6 |
| 2024Q4 | 2 |
| 2025Q1 | 5 |
| 2025Q2 | 4 |
| 2025Q3 | 15 |
| 2025Q4 | 10 |
| 2026Q1 | 46 |
| 2026Q2 | 9 |
| 2026Q3 | 23 |
| 2026Q4 | 6,577 |

The data root was absent at preparation and the first genuine operation created that exact approved root. Quarterly discovery preceded daily discovery. Daily discovery traversed the production previous/current-quarter scope, 2026Q3 and 2026Q4, discovered 75 sources and projected only the two explicit daily singleton worksets. **73 unselected discovered sources remain pending**, with no failed directories. `daily.start_date` is a handoff/discovery input, not a strict body date range. No subsequent daily/backfill workflow runner collected that remainder.

## Original incomplete result and reviewed supplemental pass

The original driver compared real `RunContext.runtime` (`FrozenMapping`) directly with a plain native-descriptor dictionary. Dataclass equality excluded all ten otherwise matching native admissions, producing false pass-defining fields. The reviewed one-expression correction compares `context.to_mapping()['runtime']` with the same native descriptor. Release/mode/context negatives, conservative budgets, positive drain, exact replay/reuse and selected-source capture linkage remain required.

Before changing the external driver, its original bytes and the child's bytes were frozen and verified against the original selection. Driver archive SHA256 is `ba05e8c53ba83bb80987d16d499915d358958faa74215a008b3008033f3a5f9e`; child archive SHA256 is `ff8e89012d04a0bb0811f90c0260d11eeb3e4797544e150fa97594f5e7c68bb4`. Standard run verification still refuses the old selection with changed current harness bytes. Historical offline adjudication validates the exact archived originals and cannot invoke acquisition.

The correction and separate analyzer in commit `782e40a` received independent approval with no findings before actual adjudication. At **2026-10-18 23:46:17.559239 UTC**, the analyzer derived three genuine native sources, matching persistence/replay/reuse, and 21 qualified published reads. It completed exit 0 and recorded `independent_status: {status: pass, reasons: []}`. The original report, original verification and original watchdog still retain exit 12/incomplete. The supplement records their exact hashes and only changes the six native-classification fields explained by the mapping comparison.

| Retained record | SHA256 |
| --- | --- |
| Original run `run-b0bfc28dcc7d48e686b12b5253d8a414.json` | `8f9db79396e792f70b4d1435c272213a46023619ef27510a4b17b11b059677b1` |
| Original verification `verification-7fee6a8a509a482d949f9cd78cec9a79.json` | `6842f951917b98876b0630279dbdcf9383b2d2c1a14a89c426ecffbb53ca9d8a` |
| Supplemental `adjudications/reviewed-native-runtime.json` | `1e1eff2c426235212c976b047aeb3799be317b067da730bfe9f2f0d3930af252` |
| Exact controller argv/status record `controller-commands.json` | `e966ff6f4b809b09a497b4103575ec0cda94de3d726dcad6abcc7cdba8f94596` |
| Corrected external driver | `6700ea7470ad1ee3b1e774fd03014ddd23d3b458e6c19450bfc43a7a7a37101e` |
| Offline supplemental analyzer | `0a1d6b5b5aa218fc4d8ac09084c54e78fa05d8776ab79891aac306bf025649ab` |

All record filenames above are relative to `/private/tmp/sec-local-task16-acceptance-20261018` except the external scripts. Exact absolute paths, original frozen hashes, command arrays, result/stream refs and file sizes are in the machine evidence. Controller commands use selected native Python with `-I -B -X pycache_prefix=/dev/null`; each low-level child uses the fixed `[selected_python, "-I", absolute_child, "--selection", selection_path, "--call", call_path]` signature and establishes no-bytecode policy before application imports.

The final guarded offline code gate retained **36 tests passing in 15.719 seconds**, zero failures/errors/skips/warnings. It used synthetic fixture/process boundaries and real native context types; genuine L12 was evaluated separately from the actual retained attempt. No production code/dependency/lock/release edit was made for Task16. The current output inventory records **257 evidence files / 6,175,866 bytes** and **155 live-root files / 12,203,317 bytes**, with exact hashes. Response cookie headers are retained only in raw immutable evidence; this summary contains references and hashes. Final Task16 evidence review remains the next gate.

The approved input spec and plan were later retired to their `specs/completed/` and `specs/plans/completed/` locations under the completion protocol. Their exact acceptance-time bytes from baseline revision `3c40471ac99df091b7660380f6d7ad98e9849ebb` remain archived as [approved spec](approved-inputs/sec-edgar-local-spec.md) and [approved plan](approved-inputs/1-sec-edgar-local-spec.md). The machine record points its two historical preserved-file references to these hash-identical copies and records original/retired paths; observed results and the 412-file output inventory are unchanged.
