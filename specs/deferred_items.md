# Deferred items

## 4-sec-filing-index-bounded-drain — 2026-10-27
- [ ] Per-member cost (owner decision D2, plan 4): the owner does not accept the measured
      per-member cost. Full-size quarterly members took more than 9,000 s, and no reserve fits
      them under the 3,300 s launcher default. A per-member-cost roadmap stage goes before
      Stage 2. Plan 4 did not place it. Inputs: specs/evidence/d5-release/measurement.md and
      finish-measurement.json. See specs/plans/completed/4-sec-filing-index-bounded-drain.md,
      Decisions D2 and Handoff. Size: design. Done when: derive-roadmap places the stage in
      specs/sec-filing-index-ingestion-roadmap.md and a plan for it completes.
- [ ] Unmeasured drain costs (plan 4 Task 2): the full measurement run reached its deadline, so
      measure 1 (a closed-quarter rebuild by one back-dated daily row), the 14-quarter fan-out,
      and the 40- and 80-source open-quarter publish marks were never measured.
      scripts/measure-d5-drain.py holds the scenarios. Size: plan. Done when: the per-member-cost
      stage measures them, or its spec records that they are not needed.
- [ ] Provisional live reserve (owner decisions D2 and D4): conf/sec-edgar-local.json sets
      execution.dispatch_reserve_seconds to 1800 without a measured basis. It covers a daily
      member with up to about 18 sources already in its quarter, not full-size quarterly
      members. Size: design. Done when: the owner approves a reserve set from measured member
      costs, or approves 1800 as final.
- [ ] B4 single-candidate limit (final-review note): runner.sibling_completion in
      packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/runner.py never skips a source
      with two or more historical snapshots, so those sources keep F10's repeated child
      sequence. A refused skip also costs an extra inventory scan and evaluate_member before
      process_member repeats it. Size: plan. Revisit if: the per-member-cost stage or Stage 2
      shows repeated child sequences or refused-skip scans as a material share of run time.
- [ ] Order-aware two-release proofs (owner decision R2): member order is not pinnable because
      member_id hashes wall-clock and per-build inputs. In about half the runs of the pending
      scenario in packages/sec-edgar-ingest/tests/test_release_upgrade.py, and one run in four
      of the first test in test_release_origin.py, no child runs on the origin release. See
      specs/evidence/d5-release/two-release.md, "Limits of the proof". Size: plan. Revisit if:
      member ordering becomes deterministic, or an origin-release regression escapes these tests.
- [ ] Test-hygiene Minors from plan 4 task reviews (all triaged to ship by the whole-branch
      review), in packages/sec-edgar-ingest/tests/:
      test_workflow_cli.py engine admission test has a vacuous assertFalse(live data exists),
      a comment that says "missing manifest" for a case that reaches the isolation refusal, and
      covers backfill only; stale comment near test_workflow_cli.py:72.
      test_workflow_drain.py: a comment near :174 overclaims; the missing-key test is weak; no
      test reuses a receipt after a cutoff; the P8 test compares () == () because fixture
      children emit no gaps; the tamper set is thin; replay checks are near-vacuous.
      test_release_upgrade.py has a tautological assertion near :203; the repair probe's
      both-B-first fallback was proven once, by a reverted local edit.
      Production: the contract-level B4 branch in workflows/contracts.py is looser than the full
      B4 shape (processing._validate_sibling_completion enforces it); a refusal message has a
      cosmetic order issue. Size: quick-fix. Done when: one test-hygiene pass over these files
      lands with the full gate green.
