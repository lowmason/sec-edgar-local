# 0001. Build the filing platform as its own workspace package

- **Status:** Accepted
- **Date:** 2026-10-21
- **Deciders:** Lowell Mason (owner), accepted 2026-10-21
- **Blast radius:** the whole uv workspace: `packages/sec-edgar-ingest`, the new platform package,
  the shared `uv.lock` and the native release machinery

## Context

The workspace has one member, `packages/sec-edgar-ingest` (version 0.2.0, about 13,300 lines of
source). It is the filing-index catalog. It is implemented and tested offline, and its native
releases are owner-reviewed. Stage 2 of the [ingestion roadmap](../sec-filing-index-ingestion-roadmap.md),
the baseline campaign, is in progress.

The [platform spec](../sec-filing-platform.md) (commits `4b0450b` and `580c48f`) defines a second
system above the catalog, with its own roadmap. It shares the catalog's governor, lease record and
stores ([methodology](../sec-filing-platform-methodology.md), cross-component assumptions 2 and
7). It reuses the catalog's publication protocol (spec R26). The spec says nothing about code
layout.

These facts about the code, as of this date, drive the choice:

1. **One governor, one lease, one namespace.** The catalog's config validator pins
   `coordination.namespace` to one constant and `sec.max_active_collectors` to 1. Both systems must
   send every SEC request through that one governor.
2. **The ingest package refuses platform traffic.** `urls.py` accepts only index paths:
   `full-index`, `daily-index` and their `index.json` listings. The configured guards are 64 MiB
   received and a 90 s exchange. One daily Feed archive was 1.6 GB and took 251 s.
3. **The release machinery builds one application.** `runtime._application` rejects any name except
   `sec-edgar-ingest`. `package_files` paths must start with `sec_edgar_ingest/`.
   `release.build_release` requires exactly one application wheel.
4. **One lock for the workspace.** A new member's dependencies resolve into the same `uv.lock`, so
   they can move versions that the ingest release exports.
5. **Shared code is entangled with catalog code.** `config`, `runtime` and `models` import each
   other in a cycle. `config` mixes shared settings with catalog-only ones. `etl.publication` imports
   `etl.catalog` and `etl.transform`.

## Decision

We will build the filing platform as its own uv workspace package under `packages/`. The platform
package may import shared code. No module of `sec-edgar-ingest` imports the platform package.

"Shared code" means the governor, the bounded HTTP exchange, the storage contracts, the shared
models and the release identity. Today all of it lives in `sec-edgar-ingest`. A later ADR decides
whether it moves to a separate core package.

## Consequences

- **Positive:**
  - A platform change does not cut a catalog release, so the catalog's reviewed-release gate keeps
    its scope.
  - The import direction is a structural fact. A test can check that no `sec_edgar_ingest` module
    imports the platform.
  - The first platform work needs no ingest change. Parsers for envelopes, XBRL facts and ownership
    records over hand-built fixtures are pure functions over bytes.
- **Negative:**
  - The release machinery must build and verify more than one application. That changes a reviewed
    component and ships in a catalog release.
  - Until a core package exists, the platform depends on ingest internals that were not designed as
    an API. An ingest refactor can break the platform.
  - The shared lock couples the packages. A platform dependency can force a catalog release. To
    contain this, keep the platform's runtime dependencies few, put evaluation-only tools such as
    Arelle (spec R21) in a dev dependency group, and diff
    `uv export --package sec-edgar-ingest --no-dev --no-emit-workspace` before and after each
    dependency change.
  - A second package with its own config parser could bypass the catalog's namespace and collector
    guards and so double the owner-wide SEC rate. Two safeguards are required. The platform reads
    the governor settings through the catalog's validator and constants, never through a copy. The
    lease record stores a governor protocol version, and a process on another version refuses to
    send.
- **Neutral / follow-on:**
  - One catalog release must come before any platform request. It adds the platform's URL classes,
    the bulk lane and third priority (spec R4), the protocol-version guard and multi-application
    releases.
  - ADR 0002, at that release, decides between importing ingest internals and extracting a shared
    core package.
  - The package name is still open. `sec-edgar-filings` is the working suggestion.

## Alternatives considered

- **Modules inside `sec-edgar-ingest`**, for example a `sec_edgar_ingest.platform` subpackage —
  rejected. Every platform change would then produce a new catalog release for owner review, and
  the import direction would rest on discipline alone. This option does avoid the release-machinery
  and lock costs, and the governor would be one build by construction.
- **A separate repository** — rejected. The platform shares the governor, lease record and stores
  with the catalog. A second repository splits one coordination domain across two locks and two
  release histories, which makes "one governor build" harder to guarantee, not easier.
- **Three packages now, with a shared core extracted first** — deferred to ADR 0002, not rejected.
  Extraction refactors a completed, reviewed package while Stage 2 runs, and it must untangle the
  import cycle and the mixed config. Its natural time is the catalog release that opens the
  governor code for spec R4 anyway.

## Trade-offs & reversibility

This trades release independence and an enforced boundary for release-machinery work and lock
coupling. The door is two-way at first. While the platform holds only offline parsers, folding it
into `sec-edgar-ingest` is a move of files. It turns one-way once the platform has its own
releases, retained run records and published generations. Those name the producing build
(methodology cross-component assumption 6), so moving the code later changes producer
identities.

Revisit if either of these happens:

- Generalizing the release machinery costs more than the platform's release independence is worth.
- Most platform stages need changes to ingest internals, which would show that the boundary is in
  the wrong place and that a shared core is overdue.
