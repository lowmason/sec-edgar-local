# Locality of an eligible addition (Stage 1b, plan 5)

Source: plan 5, section "Locality proof"; spec §4.3 item 4 as amended (A1).

## Locality proof (spec §4.3 item 4; written before C5)

Notation. `A` is the active generation, and its gate is `clear`. `S` is the selected source set: `A.sources` plus the delta sources `D`, whose `source_id` values are new (C4). `M` is the membership authority. C4 makes it the same reference in `A` and in `S`, or absent from both. For a key `k`, `O_A(k)` is its observations in the quarter over `A.sources`, and `O_S(k)` is the same over `S`. `T` is the set of keys of `D`'s observations in the quarter (the touched keys). `U_A` is the set of keys of `A`'s `unresolved_absence` change rows. `best(·)` is `_load_observations`' ranking: preference, period and receipt descending, then `source_id` ascending.

A full rebuild over `S`, with `A`'s rows as `active`, resolves each key by `_resolve`. For `k ∉ T`, `O_S(k) = O_A(k)`. Mode and membership are unchanged. Take each case of `k` in `A`'s own build:

1. **`k ∈ U_A`.** `k` was absent in `A`'s build: no proposed row, or open mode with `M` and `k` not a member. Both conditions still hold, so `k` is absent again. In closed mode with `M`, an absent key is withdrawn, and gate `clear` means `A` withdrew nothing. So this case is open mode, or closed mode without `M`. The full rebuild re-emits `unresolved_absence` with `before = after =` the `A` row, which is the row in `A`'s change file.
2. **`k` is in `A`'s data, `k ∉ U_A`, and `k` was in `A`'s own base.** `A`'s row is `best(O_A(k))`, and `k` was not absent. The rebuild proposes the same row, membership is unchanged, and so there is no change and no provenance refresh.
3. **`k` is in `A`'s data and `A`'s change row for `k` is `added`.** The rebuild proposes the same row. `k` is now in `active`. It is absent only in open mode with `M` and `k` not a member. **This is the one exception (A1):** the rebuild emits `unresolved_absence` for `k` and keeps the `A` row. In every other mode there is no change.
4. **`k` is not in `A`'s data.** `A` proposed nothing for `k`, or closed mode with `M` deleted it as a non-member. Both hold again, so `k` is not in the output.

So for untouched keys the full rebuild gives `A`'s data rows. Its change rows are the rows of `U_A \ T`, re-emitted, plus, in open mode with `M`, one `unresolved_absence` row for each key of an `A` `added` row that is untouched and not a member.

For a touched key `k ∈ T`, `O_S(k) = O_A(k) ∪ O_D(k)`:

- If `k` is in `A`'s data and `k ∉ U_A`, `A`'s row is `best(O_A(k))` (cases 2 and 3). So `best(O_S(k))` is the best of `A`'s row and `O_D(k)`. The `A` row is ranked by the source that its `source_id` names in `A.sources`.
- If `k ∈ U_A`, then `O_A(k)` is empty, or open mode with `M` and `k` not a member. In the first case `best(O_S(k)) = best(O_D(k))`. In the second, `k` stays absent whatever the ranking gives. So the `A` row is never ranked.
- If `k` is not in `A`'s data, then `O_A(k)` is empty, or closed mode with `M` deleted `k`. In the second case the same filter deletes it again. So ranking `O_D(k)` alone gives the full rebuild's result.

The closed-quarter filter, the open-quarter absence rule and the change rules then apply to `k` exactly as `_resolve` applies them. The inputs per touched key are its `A` row, whether `k ∈ U_A`, its delta rows and its membership flag. The untouched exception adds one input: the membership flags of the keys of `A`'s `added` rows. Also, `A`'s data keys are all members in closed mode with `M`, so an eligible build never withdraws, and its gate is `clear`.

## Probe

- **F3 — Locality probe (basis of A1).** `fixture-data/s1b-plan-probes/locality.py`, run on the main checkout's `.venv`: generation N has `added 1, unresolved 0` with change `[('added', …000002.txt)]`. Generation N+1 has `added 1, unresolved 1, retained True` with changes `[('unresolved_absence', …000002.txt), ('added', …000003.txt)]`.
