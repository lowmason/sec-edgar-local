# Stage 1c diagnosis: the `processing.py:96` conflict

**Date:** 2026-10-29. **Run diagnosed:** invocation 1, run `8305a3d9-54a1-46ae-863c-af8227118417`.
**Code:** release `9fa189a0…` (its own venv, `python -I`). **Store:** a byte-identical scratch copy of
`data/` at `/tmp/stage1c-diag-20261029/data`. No SEC request was sent. Nothing was written under `data/`:
`outputs/live-data-before.sha256` and `outputs/live-data-after.sha256` are identical (326 files).

## Cause

The completion check failed on its own repair inventory, not on the published data.

1. `evaluate_member` calls `_obligations`, which calls `_publish_calls` (`workflows/completion.py:536`).
2. The legacy loop (`:551–566`) calls `_legacy_publish_call` on every `publish` Attempt that is not a
   checked child call. It does this before it looks at `value['result']`.
3. `_legacy_publish_call` refuses an input workset that is not complete (`:472–473`).
4. The L12 acceptance run (`accept-38bf7c024e0fd5ac`, 2026-10-18) left a finished publish Attempt,
   `2024Q1-publish-attempt-000`. Its input is the 2024Q1 transformed workset, with `complete=False` and
   0 observations, because the 2024Q1 transform was quarantined (conflicting duplicate key).
5. So the loop raises "ordinary publication authority inventory uncertain: legacy unfinished publication
   has no complete publishable input". `evaluate_member` turns it into a `state_conflict` gap.
6. `process_member` (`workflows/processing.py:95–96`) sees a complete publish and an incomplete evaluation.
   It raises a generic `Conflict` and drops the gap text. That is why the logs show only the stock message.

Evidence: `outputs/diag2-evaluate-member.txt` (the hidden gap), `outputs/diag3-publish-attempts.txt`
(the one refused Attempt).

## The refused Attempt is harmless

`outputs/diag5-obligations-pointers.txt` and its `result.json`:

- Outcome `incomplete`, `quarters: []`, `published: 0`. It moved no pointer. No 2024Q1 pointer exists.
- No `WorkflowRepairObligation` row exists. No `worksets/sec/workflow-repair-authority/` exists.

## The nine generations are sound

- With that one finished Attempt hidden from the inventory, `evaluate_member` returns complete, with
  nine quarter captures and no obligations (`outputs/diag4-without-finished-attempt.txt`).
- An independent full-path rebuild of each quarter (`catalog._load_observations`, `_load_active`,
  `_resolve` over the stored sources and base) equals the stored data rows in all nine quarters
  (`outputs/diag6-full-rebuild.txt`). Eight are incremental on `fc68adef…` bases, one is a first
  publication. Limit: the change rows were not compared, only the data rows.

## Scope

- The refusal and the loop order arrived with the imported baseline (`9fcb4f6`, 2026-10-17). Every
  release since the port carries them. The trigger is store state: the L12 run wrote the 2024Q1 Attempt
  on 2026-10-18, after the port gate. Stage 1a and 1b gates ran on fixture stores without such an Attempt.
- On this store, every member whose publish completes fails the same way.
- `process_member` already runs `evaluate_member` before it dispatches (`processing.py:31`). It reads
  only `obligations` and ignores the non-retryable gap, so it dispatched and moved nine pointers.

## Open observation, not the cause

The discovery child's request for `https://www.sec.gov/Archives/edgar/daily-index/index.json` was refused
at 13:40:42Z with `permit_expired` ("child refused a stale dispatch window"), status 0, empty body
(`quarantine/discovery/sha256=e3b0c442…`). This is the one failed attempt in the audit. It is not
explained here.

## Spike of the proposed rule

`scripts/diag7.py` patches `_legacy_publish_call` in memory so it builds the call without the complete-input
refusal. The inventory keeps 1 call (the checked publish of invocation 1) and no call with an incomplete
input. The 2024Q1 Attempt passes `_transformed_input`, is built, and is not kept. `evaluate_member`
returns complete with no obligations and no gaps (`outputs/diag7-core-rule-spike.txt`).

## Scripts

`scripts/diag2.py`–`diag8.py`. `diag8.py` runs `diag7.py` and counts the members that then evaluate complete with no `WorkflowMemberResult` receipt: three, the halted member and the L12 members for 2026-10-14 and 2026-10-15 (`outputs/diag8-complete-without-receipt.txt`). Each opens the scratch copy with its stored binding and takes the root
as its first argument.
