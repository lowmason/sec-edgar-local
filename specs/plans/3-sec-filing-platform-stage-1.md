# Platform Stage 1: Package and Envelope Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: implement this plan task-by-task via subagent-driven-development (the default) — or executing-plans when your human partner chose inline execution at the handoff. Steps use checkbox (`- [ ]`) syntax for tracking.

> Roadmap: specs/sec-filing-platform-roadmap.md, Stage 1 — on plan completion, tick the stage and re-validate later stages against what shipped.

**Status:** Approved by the owner, 2026-10-21, with defaults DF1–DF7 as recommended (D1 below). Nothing is executed. This plan authorizes no SEC request.

**Goal:** Add the platform workspace package `sec-edgar-filings` with a draft P3 envelope parser ($\nu_E$) that passes hand-built fixtures in both serializations, an import-direction test, and a recorded ingest export diff, with no SEC request.

**Architecture:** The package is pure functions over bytes. Two small lexers, one per serialization, turn the header into one block tree. The tree uses canonical keys from a grammar table, and each entry of that table names its source. One shared document-block parser splits payloads at line-initial closing tags. One classifier assigns the R16 classes. An assembly step builds $\Sigma_y$, $\mathcal{D}_y$, the R9 header state and the gaps. It also gives a round-trip check that re-derives every parsed field from the bytes. A separate step cross-checks the header against a plain catalog record (R8).

**Tech Stack:** CPython 3.14 (stdlib only: `xml.etree.ElementTree` pull parser, `zoneinfo`, `binascii`, `hashlib`). Build backend `uv_build>=0.12.15,<0.13.0` (the ingest package's pin). Stdlib `unittest`, run through `packages/sec-edgar-ingest/tests/network_guard.py`, which denies sockets.

**Spec:** [specs/sec-filing-platform.md](../sec-filing-platform.md), through the roadmap's Stage 1 entry ([specs/sec-filing-platform-roadmap.md:189-196](../sec-filing-platform-roadmap.md)). Its `Spec` line cites R1 (M P3), R8 (P3 cross-check), R9 (header state), R15, R16, and ADR 0001 Decision and Consequences. This plan covers only that entry's `Gap closed`, `Produces` and `Exit`. The spec is shared by all 13 stages. Retiring this plan leaves the spec in place (roadmap Completion).

## Owner gates (read first)

This plan has two owner stops: the plan review, and the DF3 fallback in Task 1. The review must settle **DF6** before execution starts. DF6 is a planning finding: the member's lock change reaches the D5 release even though the export is byte-identical.

1. **F1's check passes, but the lock still couples the member to D5.** The planning probe (2026-10-21, a temporary copy of the workspace, no change to the checkout) found two things:
   - Adding an empty `sec-edgar-filings` member leaves `uv export --frozen --package sec-edgar-ingest --no-dev --no-emit-workspace` byte-identical. Its SHA-256 is `961af48bd159ec2cb2680a9f9218978420acf9faa9fc4b89291ebc83c763ab48` before and after.
   - The member changes `uv.lock` (SHA-256 `e3d3dac9…` becomes `9d04ced2…`, with 6 added lines).
2. **The whole-lock hash is load-bearing in the catalog's release machinery.**
   - `build_release` records `uv_lock_sha256` in the release identity (`packages/sec-edgar-ingest/src/sec_edgar_ingest/release.py:274`).
   - The artifact-cache inventory is keyed to the same hash (`release.py:86-90`). With the new lock, `prepare_artifact_cache(..., offline=True)` against `releases/artifact-cache` raises `artifact cache lock/interpreter identity differs; run explicit setup` (probe, 2026-10-21).
   - A prepared cache is never rewritten in place (`release.py:119-121`).
   - `scripts/check-sec-edgar-ingest.sh` runs that offline check (verified by reading the script and by the probe's refusal).
   - Nine ingest test modules reference the same path through `proof_releases` or `prepare_artifact_cache`. This was found by search and not run. `proof_releases` returns before the cache check when a proof catalog is set (`packages/sec-edgar-ingest/tests/support_release.py`). The nine are `test_acceptance_selection`, `test_launcher_process`, `test_local_launcher`, `test_native_dispatch`, `test_runtime_preflight`, `test_local_modes`, `test_release_upgrade`, `test_release` and `test_workflow_installed_lock`.
3. **Consequence.** If the member joins `main` before the D5 build, three things follow until someone prepares a new artifact cache online:
   - the catalog's check script fails on `main`;
   - the D5 build's cache check fails;
   - the D5 release identity records a lock that names the platform package.
   F1's answer used the export as the test of "changes the locked inputs of the release". The probe shows that the test misses this effect.

Under the recommended DF6 default, every task runs on a worktree branch. The branch merges to `main` only after the D5 release is built and the owner has chosen how the catalog's artifact cache follows the new lock. See "Merge gate" after Task 8.

## Global Constraints

- Python `requires-python = ">=3.14"`. Build backend exactly `requires = ["uv_build>=0.12.15,<0.13.0"]`, `build-backend = "uv_build"` (copied from `packages/sec-edgar-ingest/pyproject.toml`).
- `dependencies = []` for `sec-edgar-filings`. Add no `[dependency-groups]` (ADR 0001 safeguard, DF3).
- No SEC request (roadmap D2). Platform runtime code imports no network module. The boundary test enforces this. Every test run goes through `packages/sec-edgar-ingest/tests/network_guard.py`, which denies sockets.
- The only network access in this plan is `uv lock` in Task 1, which reads package metadata from PyPI (`pypi.org`). It sends no SEC request (DF7).
- Platform runtime code imports no `sec_edgar_ingest` module (DF1). There is one test-only coupling: the platform suite runs the ingest guard script by its path. That is not an import.
- Run every task in a git worktree on branch `platform-stage1`, created from `main` at or after the commit that records the owner's approval of this plan (using-git-worktrees). Do not edit, stage or commit in the shared `main` checkout. Commit by pathspec only. Do not push. Do not merge until the Merge gate.
- In the worktree, run only `uv run --package sec-edgar-filings`, `uv lock` (Task 1) and `uv export --frozen`. Do not run `uv sync` or `uv run --package sec-edgar-ingest` there. That environment needs the pyarrow wheel, which is not in the uv cache offline (planning probe, 2026-10-21).
- Test command (from the worktree root), used by every task:

  ```bash
  UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never uv run --offline --locked --package sec-edgar-filings \
    python packages/sec-edgar-ingest/tests/network_guard.py discover \
    -s packages/sec-edgar-filings/tests -t packages/sec-edgar-filings/tests
  ```

- Style: stdlib `unittest`, `from __future__ import annotations`, frozen slotted dataclasses, single-quoted strings. This matches `packages/sec-edgar-ingest`.
- Grammar provenance: every label, tag and fixed string of the grammar lives in `src/sec_edgar_filings/grammar.py` with a `Source`. `assumed` entries rest on no repository source. `methodology` entries rest only on the methodology's reading and are unconfirmed. Stage 7 confirms both against the PDS spec, its DTD and the retained sample (roadmap Q2 answer). `<TIMESTAMP>` never supplies $t^{\mathrm{acc}}$.
- Scope: Stage 1 only. Add no task for the protocol-version guard, validator reuse, multi-application releases or ADR 0002 (Stage 4). Add none for the R15 comparison of formats on the V1 sample (Stages 6–7), the "Real files" criterion (Stages 6–7), stored read-back (Stages 5 and 8) or a $\nu_I$ crosswalk (Stage 9).
- Leave alone: `specs/sec-filing-platform-roadmap.md`, `specs/sec-filing-platform.md`, `specs/sec-filing-platform-methodology.md`, `specs/sec-filing-platform-critique.md`, ADR 0001, `specs/sec-filing-index-ingestion-roadmap.md`, `specs/sec-filing-index-ingestion-spec.md`, plan 2, `data/`, `releases/`, and every file under `packages/sec-edgar-ingest/`.

## Decisions

- **roadmap D2** (owner, brief, 2026-10-21): "No exception": no SEC request goes outside the governor. Stage 1 sends none: the governor admits no platform URL before Stage 4, and the Q2 answer covers documentation reads. Applied in: Global Constraints, Task 1 (boundary test), Task 8.
- **roadmap F1** (owner, brief, 2026-10-21): the member joins the workspace before the D5 build only if `uv export --package sec-edgar-ingest --no-dev --no-emit-workspace` is byte-identical before and after. Otherwise it joins after the D5 build. Applied in: Task 1, Task 8, Merge gate (with DF3 and DF6).
- **roadmap Q2** (owner, brief, 2026-10-21): D2 covers SEC documentation reads. Stage 1 drafts the R15 grammar from the spec, the methodology's reading, the critique's PDS fragments and the Feed tags in the findings. Stage 6 fetches the PDS spec and DTD through Stage 4's documentation URL class, and Stage 7 confirms the grammar. Applied in: Global Constraints (grammar provenance), Tasks 2–6.

- **D1** (owner, plan review, 2026-10-21): DF1–DF7 accepted as recommended. That settles: no `sec_edgar_ingest` import in platform runtime code (DF1); the name `sec-edgar-filings` (DF2); the export diff as the Task 1 gate with stop-and-restore on a difference (DF3); verbatim item lines with an empty $\nu_I$ (DF4); pathspec commits of the plan (DF5); DF6 option (a), so Stage 1 runs on branch `platform-stage1` and merges only through the Merge gate; and one online `uv lock` to PyPI in Task 1 (DF7). Owner's words: "Approve plan 3 with the recommended defaults DF1–DF7, including DF6 (a): Stage 1 runs on the platform-stage1 branch and merges only after the D5 build and the artifact-cache decision." Applied in: Global Constraints, Tasks 1, 6 and 7, Merge gate.

"The D5 release" in F1 is plan 2's D5 (`specs/plans/2-sec-filing-index-ingestion-spec.md:82`), not a platform decision.

## Defaults for owner review

Each default below is applied in the task it names. The owner's answers go into `## Decisions` as plan-review entries.

- **DF1 (brief) — Stage 1 imports nothing from `sec_edgar_ingest`.** ADR 0001's Decision lets the platform import shared code (ADR `:41-42`). Its Positive third bullet says only that the first platform work "needs no ingest change" (ADR `:55-56`). Recommended: platform runtime code imports no `sec_edgar_ingest` module. The P3 cross-checks take catalog values through the platform's own `CatalogSubmission` record. The boundary test reads ingest source by AST scan only. Why: ingest internals hold an import cycle (ADR `:35-36`), and ADR 0002 (Stage 4) decides how shared code is reached. Effect if wrong: the platform repeats catalog checks, such as the accession pattern at `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/contracts.py:82`, and the copies can drift until ADR 0002. Applied in: Task 1, Task 7.
- **DF2 (brief) — Package name.** Recommended: `sec-edgar-filings`, import name `sec_edgar_filings` (ADR `:78`, the working suggestion). Effect if wrong: before the first platform release, a rename moves files and edits the workspace members, `uv.lock` and the boundary test. After releases, it changes producer identities (ADR `:96-101`). Applied in: Task 1.
- **DF3 (brief) — F1 fallback.** Recommended: the export diff is Task 1 and gates every later task. The platform's runtime dependencies stay empty. If the export differs, the stage stops at Task 1, restores the root `pyproject.toml` and `uv.lock`, and reports to the owner. Effect if wrong: either the stage waits on an unplanned release, or parser code lands outside the workspace without the owner choosing that. Applied in: Task 1 Step 8.
- **DF4 (brief) — The unmapped item label case.** The "Example files" criterion includes "an unmapped item label (gap)" (methodology `:559`). That case needs $\nu_I$, which R25 defines and Stage 9 builds. Recommended: Stage 1 keeps item lines verbatim with an empty $\nu_I$. So each item line is a counted gap (`unmapped-item`), and that is an assumption for Stage 9. Effect if wrong: Stage 1 drafts a crosswalk that Stage 9 rebuilds, or drops a P3 example case. Applied in: Task 6.
- **DF5 (brief) — Commit timing.** Recommended: the planning session commits this plan by pathspec before the owner's review, and commits each review change the same way. Effect if wrong: an unreviewed draft sits on the shared `main`, or an uncommitted file sits in a checkout that other sessions use. Applied in: planning (this file's commit).
- **DF6 (plan, new finding) — When the member reaches `main`.** See Owner gates. The options:
  - (a) **Recommended.** Run Stage 1 on branch `platform-stage1` in its own worktree. The member joins the workspace on that branch only. The branch merges to `main` only after the D5 release is built and the owner chooses how the catalog's artifact cache follows the new lock (Merge gate). This applies F1's "otherwise" branch, because the lock change does reach D5. Work starts now, and D5 builds on today's lock.
  - (b) Develop the package on `main` outside the workspace: it is not a member, and tests run with `PYTHONPATH`. A last task adds the member after the D5 build. The brief named this as an outcome needing the owner's choice.
  - (c) Join `main` now, as F1's literal test allows. `main`'s catalog check script and the D5 build's cache check then fail until a new artifact cache is prepared online, and the D5 release identity records a lock that names the platform package.

  Effect if wrong: (a) delays Stage 1's merge, and so the start of Stages 2–4 from `main`, until the D5 build. (c) breaks the catalog's checks on `main` while the D5 work runs there. Applied in: Global Constraints, Task 1, Merge gate.
- **DF7 (plan) — `uv lock` reads PyPI.** An offline `uv lock` fails because pyarrow's metadata is not in the uv cache (probe, 2026-10-21). Recommended: Task 1 runs one online `uv lock`, which reads `pypi.org` only. That is not an SEC request, so D2 holds. Alternative: the member does not join until a cached or vendored resolution exists. Effect if wrong: a PyPI read the owner did not want, or no workspace member. Applied in: Task 1 Step 6.

## Grammar assumptions for Stage 7

The grammar sources are spec R15 and R16 (spec `:225-243`), the methodology's P3 layout (methodology `:464-530`, unconfirmed), the critique's PDS fragments (critique `:25`, `:27`, `:114-118`, `:128`, `:401`, `:442`), and the Feed tags observed on 2026-10-15 (findings `:109-112`, `:118`, `:151`, `:156`, `:174`). `grammar.py` tags every label and tag with one of these sources, or `assumed`. The structural choices below are not table entries. Each rests on no repository source unless the row names one. Stage 7 confirms or revises each one.

| # | Choice | Basis | Who settles it |
|---|---|---|---|
| G1 | A payload is the bytes from the first byte after the `<TEXT>` line to the first byte of the line-initial `</TEXT>` line. It keeps its last line's terminator. Both serializations use this rule. | R15 (line-initial close); boundary assumed | V1 (Stage 6) compares payload hashes across serializations |
| G2 | A line ends at LF. A CR before the LF is dropped from line text but kept in payload bytes. | assumed | Stage 7 |
| G3 | The labeled header nests by leading tabs. A label with an empty value opens a block when the next entry is deeper. | methodology (blocks); tab rule assumed | Stage 7 |
| G4 | In the tagged header, a bare `<NAME>` opens a block when a `</NAME>` line follows later in the header. Otherwise it is an empty field (for example `<PRIVATE-TO-PUBLIC>`). An unknown container is kept as an unknown block. | findings (tags); rule assumed | Stage 7 (PDS DTD) |
| G5 | `<SUBMISSION>` encloses the documents. `</SUBMISSION>` is the last non-blank line. | findings (`<SUBMISSION>` opens); close assumed | Stage 7 |
| G6 | The tagged acceptance tag is `<ACCEPTANCE-DATETIME>`. No source names it. `<TIMESTAMP>` is kept as its own field and never read as $t^{\mathrm{acc}}$ (critique `:401` describes it as a dissemination date-time for corrections only). If G6 is wrong, every real Feed member is refused with `missing required field acceptance-datetime`. That failure is loud, not silent. | assumed | V7 and Stage 7 |
| G7 | Values are the same across serializations (for example the SIC as a code and items as titles), so header states agree. | assumed | V1 (Stage 6) |
| G8 | The header state leaves out unknown entries and serialization metadata (`sec-document`, `sec-header`, `timestamp`, `private-to-public`). | R9 ("parsed header field values"); exclusions assumed | Stage 8 (revision counting) |
| G9 | R8 "the header confirms": the catalog's form types are a subset of the submission type plus each role block's filing-values form type. | assumed | V5 (Stage 6) |
| G10 | A header line that is neither `LABEL:value` nor a tag line refuses the submission. Header lines must be ASCII. | methodology `:508` (ASCII) | Stage 7 |
| G11 | Document metadata lines are tag lines. `TYPE` and `SEQUENCE` are required. `FILENAME` and `DESCRIPTION` are optional. | methodology `:513-514` | Stage 7 |
| G12 | The root namespaces of XBRL 2.1 instance, schema and linkbase, XHTML, and inline XBRL 1.1 (`http://www.xbrl.org/2013/inlineXBRL`). Inline XBRL 1.0 is not recognized. | assumed (published standards) | Stage 7 |
| G13 | The class order: `IDEA: XBRL DOCUMENT` first, then uuencoded, then the root. A type/root disagreement is `unclassified`, which is a gap. | R16; order assumed | V10 (Stage 6) |
| G14 | Eastern time to UTC uses the system `zoneinfo` table. An ambiguous local time takes `fold=0`. The table version is not recorded. | methodology XA9 | R14 (Stage 7) |
| G15 | The public document count is compared with all document blocks, SEC-generated ones included. | critique `:118` (open question) | V10 (Stage 6) |

---

## File structure

All new files are under `packages/sec-edgar-filings/`, except the root workspace edit and the evidence files.

| File | Responsibility | Task |
|---|---|---|
| `pyproject.toml`, `README.md`, `src/sec_edgar_filings/__init__.py`, `src/sec_edgar_filings/py.typed` | The workspace member | 1, 8 |
| `tests/test_boundary.py` | ADR 0001 import direction, DF1, no network modules | 1 |
| `src/sec_edgar_filings/errors.py` | `EnvelopeRefusal`, `DocumentGap` | 2 |
| `src/sec_edgar_filings/lines.py` | `Line`, `LineReader`, `Field`, tag-line helpers | 2 |
| `src/sec_edgar_filings/grammar.py` | Source-tagged grammar tables (grows in Tasks 2–6) | 2–6 |
| `src/sec_edgar_filings/documents.py` | `DocumentBlock`, `parse_documents` (shared by both serializations) | 2 |
| `src/sec_edgar_filings/classify.py` | R16 `DocumentClass`, `Classification`, `Document`, `classify`, `decode_uuencoded` | 3 |
| `src/sec_edgar_filings/tree.py` | `Block`, `BlockBuilder`, tree walkers | 4 |
| `src/sec_edgar_filings/header_labeled.py` | Labeled-line header lexer | 4 |
| `src/sec_edgar_filings/header_tagged.py` | Tagged header lexer | 5 |
| `src/sec_edgar_filings/record.py` | $\Sigma_y$ records, `HeaderState`, `Envelope` | 6 |
| `src/sec_edgar_filings/envelope.py` | `parse_envelope`, `header_state`, `rederive_mismatches` | 6 |
| `src/sec_edgar_filings/crosscheck.py` | `CatalogSubmission`, `cross_check` (R8) | 7 |
| `tests/support_*.py`, `tests/test_*.py` | Hand-built fixtures and tests | 2–7 |
| `pyproject.toml` (root), `uv.lock` | Workspace member line and lock | 1 |
| `specs/evidence/platform-stage1/` | Export before/after and the stage evidence note | 1, 8 |

---

### Task 1: Workspace member, boundary test and export diff

**Files:**
- Create: `packages/sec-edgar-filings/pyproject.toml`, `packages/sec-edgar-filings/README.md`, `packages/sec-edgar-filings/src/sec_edgar_filings/__init__.py`, `packages/sec-edgar-filings/src/sec_edgar_filings/py.typed`
- Create: `packages/sec-edgar-filings/tests/test_boundary.py`
- Create: `specs/evidence/platform-stage1/ingest-export-before.txt`, `specs/evidence/platform-stage1/ingest-export.md`
- Modify: `pyproject.toml:20` (workspace members), `uv.lock`

**Interfaces:**
- Consumes: nothing.
- Produces: the importable package `sec_edgar_filings`, and the test command in Global Constraints. In `tests/test_boundary.py`: `imported_modules(path: Path) -> set[str]` and `hits(root: Path, banned) -> list[str]`.

- [ ] **Step 1: Check the starting point**

Run from the worktree root on branch `platform-stage1`:

```bash
git status --short && git log --oneline -1 && shasum -a 256 uv.lock
```

Expected: no status lines. The lock hash was `e3d3dac9971ed75bdc5864ebd8c422c2e34bd24236a9a77bbadb6a87cddf1bbb` at planning. If `main`'s lock changed since then, record the new hash in Step 10. The gate in Step 8 is the byte comparison, not this constant.

- [ ] **Step 2: Record the export before the member joins**

```bash
mkdir -p specs/evidence/platform-stage1
UV_OFFLINE=1 uv export --frozen --package sec-edgar-ingest --no-dev --no-emit-workspace \
  > specs/evidence/platform-stage1/ingest-export-before.txt
shasum -a 256 specs/evidence/platform-stage1/ingest-export-before.txt
```

Expected: SHA-256 `961af48bd159ec2cb2680a9f9218978420acf9faa9fc4b89291ebc83c763ab48` (planning probe, 124 lines). Write to stdout, never with `-o`, because `-o` puts the output file name into the header comment.

- [ ] **Step 3: Write the failing boundary test**

Create `packages/sec-edgar-filings/tests/test_boundary.py`:

```python
"""ADR 0001 boundary checks: import direction, no ingest imports, no network modules."""
import ast
import tempfile
import unittest
from pathlib import Path

PACKAGES = Path(__file__).resolve().parents[2]
INGEST = PACKAGES / 'sec-edgar-ingest'
PLATFORM_SRC = PACKAGES / 'sec-edgar-filings' / 'src'
NETWORK_MODULES = frozenset({'socket', 'ssl', 'http', 'urllib.request', 'requests', 'httpx',
                             'ftplib', 'smtplib', 'xmlrpc', 'asyncio', 'subprocess'})


def imported_modules(path: Path) -> set[str]:
    """Every module a file imports, plus string constants that name a module."""
    tree = ast.parse(path.read_bytes(), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f'{node.module}.{alias.name}' for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
    return names


def hits(root: Path, banned) -> list[str]:
    """`file: module` for each banned module that a file under root imports or names."""
    found = []
    for path in sorted(root.rglob('*.py')):
        for name in sorted(imported_modules(path)):
            if any(name == item or name.startswith(item + '.') for item in banned):
                found.append(f'{path.relative_to(root)}: {name}')
    return found


class BoundaryTests(unittest.TestCase):
    def test_scanner_sees_both_packages(self):
        self.assertGreater(len(list((INGEST / 'src').rglob('*.py'))), 10)
        self.assertGreater(len(list(PLATFORM_SRC.rglob('*.py'))), 0)

    def test_scanner_detects_a_planted_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'a.py').write_text('from sec_edgar_filings.envelope import parse_envelope\n')
            (root / 'b.py').write_text("import importlib\nimportlib.import_module('sec_edgar_filings')\n")
            (root / 'c.py').write_text('import urllib.request\n')
            self.assertEqual(hits(root, {'sec_edgar_filings'}), [
                'a.py: sec_edgar_filings.envelope',
                'a.py: sec_edgar_filings.envelope.parse_envelope',
                'b.py: sec_edgar_filings'])
            self.assertEqual(hits(root, NETWORK_MODULES), ['c.py: urllib.request'])

    def test_no_ingest_module_imports_the_platform(self):
        self.assertEqual(hits(INGEST / 'src', {'sec_edgar_filings'}), [])
        self.assertEqual(hits(INGEST / 'tests', {'sec_edgar_filings'}), [])

    def test_platform_runtime_imports_no_ingest_module(self):
        self.assertEqual(hits(PLATFORM_SRC, {'sec_edgar_ingest'}), [])

    def test_platform_runtime_imports_no_network_module(self):
        self.assertEqual(hits(PLATFORM_SRC, NETWORK_MODULES), [])

```

- [ ] **Step 4: Run it to see it fail**

The member does not exist yet, so run without the project:

```bash
UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never uv run --offline --no-project --python 3.14 \
  python packages/sec-edgar-ingest/tests/network_guard.py discover \
  -s packages/sec-edgar-filings/tests -t packages/sec-edgar-filings/tests
```

Expected: `FAILED (failures=1)`. `test_scanner_sees_both_packages` fails with `AssertionError: 0 not greater than 0`. The other four pass, because nothing is there to scan yet.

- [ ] **Step 5: Create the package**

`packages/sec-edgar-filings/pyproject.toml`:

```toml
[project]
name = "sec-edgar-filings"
version = "0.1.0"
description = "SEC filing platform: envelope parsing over retained submission bytes"
readme = "README.md"
requires-python = ">=3.14"
dependencies = []

[build-system]
requires = ["uv_build>=0.12.15,<0.13.0"]
build-backend = "uv_build"
```

`packages/sec-edgar-filings/README.md` (Task 8 replaces it):

```markdown
# sec-edgar-filings

The SEC filing platform package (ADR 0001). Stage 1 of `specs/sec-filing-platform-roadmap.md` is in progress.
```

`packages/sec-edgar-filings/src/sec_edgar_filings/__init__.py`:

```python
"""SEC filing platform: the draft envelope parser over retained submission bytes."""
```

Create the empty marker `packages/sec-edgar-filings/src/sec_edgar_filings/py.typed`.

In the root `pyproject.toml`, replace line 20:

```toml
members = ["packages/sec-edgar-ingest"]
```

with:

```toml
members = ["packages/sec-edgar-ingest", "packages/sec-edgar-filings"]
```

Do not add the package to the root `dependencies` or `[tool.uv.sources]`.

- [ ] **Step 6: Lock (reads PyPI, DF7)**

```bash
uv lock
shasum -a 256 uv.lock
git diff --stat uv.lock
```

Expected: `Added sec-edgar-filings v0.1.0`, SHA-256 `9d04ced2e909fb0f0f2066eecd7d464806173d67f9ea2143d967836011687698` (planning probe), `1 file changed, 6 insertions(+)`.

- [ ] **Step 7: Check that the lock changed only by the member**

```bash
git diff -U0 uv.lock
```

Expected: exactly these added lines, and no removed line:

```text
+    "sec-edgar-filings",
+name = "sec-edgar-filings"
+version = "0.1.0"
+source = { editable = "packages/sec-edgar-filings" }
+
+[[package]]
```

Any other change is a stop: go to the Step 8 failure path.

- [ ] **Step 8: Compare the export (F1 gate, DF3)**

```bash
UV_OFFLINE=1 uv export --frozen --package sec-edgar-ingest --no-dev --no-emit-workspace \
  > /tmp/platform-stage1-ingest-export-after.txt
cmp specs/evidence/platform-stage1/ingest-export-before.txt /tmp/platform-stage1-ingest-export-after.txt \
  && echo IDENTICAL
shasum -a 256 /tmp/platform-stage1-ingest-export-after.txt
```

Expected: `IDENTICAL` and the Step 2 hash.

Failure path, if the output is not identical or Step 7 found another change. This is an owner stop:

```bash
git restore pyproject.toml uv.lock
rm -r packages/sec-edgar-filings specs/evidence/platform-stage1
```

Report the `diff` of the two exports to the owner and stop the stage. Run no later task.

- [ ] **Step 9: Run the boundary test**

Run the test command from Global Constraints.

Expected: `Ran 5 tests` and `OK`.

- [ ] **Step 10: Record the evidence**

Create `specs/evidence/platform-stage1/ingest-export.md`, filling in the values that Steps 1–8 printed:

```markdown
# Platform Stage 1: ingest export diff (F1)

- Date: <YYYY-MM-DD>. Branch `platform-stage1`, base commit `<git log --oneline -1 from Step 1>`.
- Command, run before and after the member joined, output to stdout:
  `UV_OFFLINE=1 uv export --frozen --package sec-edgar-ingest --no-dev --no-emit-workspace`
- Before: `ingest-export-before.txt`, SHA-256 `<Step 2 hash>`.
- After: SHA-256 `<Step 8 hash>`. `cmp`: identical.
- `uv.lock`: SHA-256 `<Step 1 hash>` before, `<Step 6 hash>` after. The diff adds only the
  `sec-edgar-filings` entry and its manifest member line (6 lines).
- F1: met (byte-identical export). DF6: the member stays on this branch until the Merge gate,
  because the whole-lock hash keys the catalog's artifact cache and release identity.
- No SEC request was sent. `uv lock` read PyPI metadata only (DF7).
```

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml uv.lock packages/sec-edgar-filings/pyproject.toml packages/sec-edgar-filings/README.md \
  packages/sec-edgar-filings/src/sec_edgar_filings/__init__.py packages/sec-edgar-filings/src/sec_edgar_filings/py.typed \
  packages/sec-edgar-filings/tests/test_boundary.py specs/evidence/platform-stage1/ingest-export-before.txt \
  specs/evidence/platform-stage1/ingest-export.md
git commit -m "feat(filings): add the platform workspace package with its boundary test"
```

---

### Task 2: Lines and document blocks

**Files:**
- Create: `packages/sec-edgar-filings/src/sec_edgar_filings/errors.py`, `lines.py`, `grammar.py`, `documents.py`
- Test: `packages/sec-edgar-filings/tests/support_documents.py`, `packages/sec-edgar-filings/tests/test_documents.py`

**Interfaces:**
- Consumes: Task 1's package.
- Produces:
  - `errors.EnvelopeRefusal(line: int | None, reason: str)`, with `.line` and `.reason`; `errors.DocumentGap(ValueError)`.
  - `lines.Line(number, start, end, next, text)`; `lines.LineReader(data, offset=0, number=1)` with `.peek()`, `.read()`, `.skip_blank()` and `.jump(offset)`.
  - `lines.Field(name, key, value, line, start, end)`; `lines.field_from(line, name, key, value_offset) -> Field`; `lines.tag_field(line, names) -> Field | None`; `lines.TAG_LINE`; `lines.CLOSE_LINE`.
  - `grammar.Source`, `grammar.Name(key, source)`, `grammar.Token(text, source)`, `grammar.DOCUMENT_TAGS`, `grammar.DOCUMENT_BLOCK`, `grammar.PAYLOAD`.
  - `documents.DocumentBlock(line, fields, type, sequence, filename, description, start, end, sha256)`; `documents.parse_documents(reader: LineReader, closing: bytes) -> tuple[DocumentBlock, ...]`; `documents.DOCUMENT_OPEN`.
  - Tests: `support_documents.document(sequence, doc_type, payload, *, filename=None, description=None) -> bytes`; `support_documents.PRESS_RELEASE`.

- [ ] **Step 1: Write the failing tests**

`packages/sec-edgar-filings/tests/support_documents.py`:

```python
"""Document blocks for hand-built submissions."""
from __future__ import annotations


def document(sequence: int, doc_type: str, payload: bytes, *, filename: str | None = None,
             description: str | None = None) -> bytes:
    lines = [b'<DOCUMENT>', f'<TYPE>{doc_type}'.encode(), f'<SEQUENCE>{sequence}'.encode()]
    if filename is not None:
        lines.append(f'<FILENAME>{filename}'.encode())
    if description is not None:
        lines.append(f'<DESCRIPTION>{description}'.encode())
    return b'\n'.join(lines) + b'\n<TEXT>\n' + payload + b'</TEXT>\n</DOCUMENT>\n'


PRESS_RELEASE = (b'<html><body>\n'
                 b'<p>Press release. Quoted markup such as </TEXT> or </DOCUMENT> stays inside the payload.</p>\n'
                 b'</body></html>\n')
```

`packages/sec-edgar-filings/tests/test_documents.py`:

```python
import hashlib
import unittest

from sec_edgar_filings.documents import parse_documents
from sec_edgar_filings.errors import EnvelopeRefusal
from sec_edgar_filings.lines import LineReader
from support_documents import PRESS_RELEASE, document

CLOSING = b'</SUBMISSION>'


def parse(body: bytes):
    data = body + CLOSING + b'\n'
    return data, parse_documents(LineReader(data), CLOSING)


class DocumentBlockTests(unittest.TestCase):
    def test_payload_is_the_bytes_between_the_text_lines(self):
        data, (block,) = parse(document(1, '8-K', b'line one\nline two\n', filename='a.htm', description='8-K'))
        self.assertEqual(data[block.start:block.end], b'line one\nline two\n')
        self.assertEqual(block.sha256, hashlib.sha256(b'line one\nline two\n').hexdigest())
        self.assertEqual((block.line, block.type, block.sequence, block.filename, block.description),
                         (1, '8-K', 1, 'a.htm', '8-K'))
        self.assertEqual([(field.name, field.key, field.line) for field in block.fields],
                         [('TYPE', 'type', 2), ('SEQUENCE', 'sequence', 3),
                          ('FILENAME', 'filename', 4), ('DESCRIPTION', 'description', 5)])

    def test_closing_tags_inside_a_line_do_not_close_the_payload(self):
        data, (block,) = parse(document(1, 'EX-99.1', PRESS_RELEASE))
        self.assertEqual(data[block.start:block.end], PRESS_RELEASE)

    def test_a_line_initial_text_close_must_be_followed_by_the_document_close(self):
        body = document(1, 'EX-99.1', b'<p>quoted\n</TEXT>\n<p>more</p>\n')
        with self.assertRaises(EnvelopeRefusal) as caught:
            parse(body)
        self.assertEqual((caught.exception.line, caught.exception.reason),
                         (7, 'the line after </TEXT> is not </DOCUMENT>'))

    def test_missing_line_initial_text_close_refuses(self):
        body = b'<DOCUMENT>\n<TYPE>8-K\n<SEQUENCE>1\n<TEXT>\nno close </TEXT>\n'
        with self.assertRaises(EnvelopeRefusal) as caught:
            parse(body)
        self.assertEqual(caught.exception.reason, 'document block has no line-initial </TEXT>')

    def test_description_and_filename_are_optional(self):
        _, (block,) = parse(document(1, 'GRAPHIC', b'x\n'))
        self.assertIsNone(block.filename)
        self.assertIsNone(block.description)

    def test_unknown_document_tag_is_retained(self):
        body = b'<DOCUMENT>\n<TYPE>8-K\n<SEQUENCE>1\n<PAGES>3\n<TEXT>\nx\n</TEXT>\n</DOCUMENT>\n'
        _, (block,) = parse(body)
        self.assertEqual([(field.name, field.key, field.value) for field in block.fields][-1], ('PAGES', None, '3'))

    def test_sequence_must_be_a_unique_positive_integer(self):
        cases = {b'0': 'document sequence is not a positive integer',
                 b'x1': 'document sequence is not a positive integer'}
        for sequence, reason in cases.items():
            with self.subTest(sequence=sequence), self.assertRaises(EnvelopeRefusal) as caught:
                parse(b'<DOCUMENT>\n<TYPE>8-K\n<SEQUENCE>' + sequence + b'\n<TEXT>\nx\n</TEXT>\n</DOCUMENT>\n')
            self.assertEqual(caught.exception.reason, reason)
        with self.assertRaises(EnvelopeRefusal) as caught:
            parse(document(1, '8-K', b'x\n') + document(1, 'EX-99', b'y\n'))
        self.assertEqual(caught.exception.reason, 'duplicate document sequence 1')

    def test_type_and_sequence_are_required(self):
        with self.assertRaises(EnvelopeRefusal) as caught:
            parse(b'<DOCUMENT>\n<SEQUENCE>1\n<TEXT>\nx\n</TEXT>\n</DOCUMENT>\n')
        self.assertEqual(caught.exception.reason, 'document block has no type')

    def test_a_submission_needs_a_document_and_nothing_after_its_closing_line(self):
        with self.assertRaises(EnvelopeRefusal) as caught:
            parse(b'')
        self.assertEqual(caught.exception.reason, 'submission has no document block')
        data = document(1, '8-K', b'x\n') + CLOSING + b'\ntrailing\n'
        with self.assertRaises(EnvelopeRefusal) as caught:
            parse_documents(LineReader(data), CLOSING)
        self.assertEqual(caught.exception.reason, 'content follows the closing line')

    def test_crlf_lines_keep_their_bytes_in_the_payload(self):
        body = b'<DOCUMENT>\r\n<TYPE>8-K\r\n<SEQUENCE>1\r\n<TEXT>\r\na\r\nb\r\n</TEXT>\r\n</DOCUMENT>\r\n'
        data, (block,) = parse(body)
        self.assertEqual(data[block.start:block.end], b'a\r\nb\r\n')

    def test_an_empty_payload_is_allowed(self):
        data, (block,) = parse(document(1, '8-K', b''))
        self.assertEqual(block.start, block.end)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run the test command. Expected: `FAILED (errors=1)` with `ModuleNotFoundError: No module named 'sec_edgar_filings.documents'`.

- [ ] **Step 3: Implement**

`packages/sec-edgar-filings/src/sec_edgar_filings/errors.py`:

```python
"""Refusals and document gaps of the envelope parser (methodology P3)."""
from __future__ import annotations


class EnvelopeRefusal(ValueError):
    """The whole submission is refused, with the first failing line and its reason."""

    def __init__(self, line: int | None, reason: str):
        super().__init__(f'line {line}: {reason}' if line is not None else reason)
        self.line = line
        self.reason = reason


class DocumentGap(ValueError):
    """One document cannot be decoded; the submission stays parsed."""
```

`packages/sec-edgar-filings/src/sec_edgar_filings/grammar.py` (Tasks 3–6 append to it):

```python
"""Draft grammar tables of the envelope parser, each entry with its source.

Sources, from strongest to weakest:
- spec: specs/sec-filing-platform.md, R15 and R16.
- critique: PDS spec fragments quoted in specs/sec-filing-platform-critique.md.
- findings: tags observed in the 2026-10-15 Feed archive
  (specs/findings/sec-filing-submissions-findings.md).
- methodology: the design's reading in specs/sec-filing-platform-methodology.md, P3.
  Unconfirmed.
- assumed: no repository source. Stage 7 confirms or revises it against the PDS spec,
  its DTD and the retained sample.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Source(StrEnum):
    SPEC = 'spec'
    CRITIQUE = 'critique'
    FINDINGS = 'findings'
    METHODOLOGY = 'methodology'
    ASSUMED = 'assumed'


@dataclass(frozen=True, slots=True)
class Name:
    """A label or tag of the header, mapped to its canonical key."""
    key: str
    source: Source


@dataclass(frozen=True, slots=True)
class Token:
    """A fixed string of the grammar outside the name tables."""
    text: str
    source: Source


S, C, F, M, A = Source.SPEC, Source.CRITIQUE, Source.FINDINGS, Source.METHODOLOGY, Source.ASSUMED


# Tags of a document block, the same in both serializations.
DOCUMENT_TAGS: dict[str, Name] = {
    'TYPE': Name('type', F),
    'SEQUENCE': Name('sequence', M),
    'FILENAME': Name('filename', M),
    'DESCRIPTION': Name('description', C),
}

# Document structure lines, the same in both serializations.
DOCUMENT_BLOCK = Token('DOCUMENT', F)
PAYLOAD = Token('TEXT', F)
```

`packages/sec-edgar-filings/src/sec_edgar_filings/lines.py`:

```python
"""Physical lines of retained bytes, with their numbers and byte offsets."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .grammar import Name


@dataclass(frozen=True, slots=True)
class Line:
    number: int  # 1-based physical line number
    start: int   # offset of the first byte of the line
    end: int     # offset after the content, before the LF or CR LF terminator
    next: int    # offset of the first byte of the next line
    text: bytes  # content without the terminator


@dataclass(frozen=True, slots=True)
class Field:
    """One labeled line or tag line, tied to its line and the byte range of its value."""
    name: str        # label or tag as written; a tag line in the labeled header keeps its brackets
    key: str | None  # canonical key from the grammar table; None when the name is unknown
    value: str       # the value with surrounding whitespace removed
    line: int
    start: int
    end: int


class LineReader:
    """Reads lines forward from an offset and keeps the physical line number."""

    def __init__(self, data: bytes, offset: int = 0, number: int = 1):
        self.data = data
        self.offset = offset
        self.number = number

    def peek(self) -> Line | None:
        if self.offset >= len(self.data):
            return None
        newline = self.data.find(b'\n', self.offset)
        following = len(self.data) if newline < 0 else newline + 1
        end = len(self.data) if newline < 0 else newline
        if end > self.offset and self.data[end - 1] == 0x0D:
            end -= 1
        return Line(self.number, self.offset, end, following, self.data[self.offset:end])

    def read(self) -> Line | None:
        line = self.peek()
        if line is not None:
            self.offset = line.next
            self.number += 1
        return line

    def skip_blank(self) -> None:
        while (line := self.peek()) is not None and not line.text.strip():
            self.read()

    def jump(self, offset: int) -> None:
        """Move forward to the start of a line at `offset`, counting the lines passed."""
        if offset < self.offset:
            raise ValueError('a line reader moves forward only')
        self.number += self.data.count(b'\n', self.offset, offset)
        self.offset = offset


TAG_LINE = re.compile(rb'<([A-Z0-9][A-Z0-9-]*)>(.*)')
CLOSE_LINE = re.compile(rb'</([A-Z0-9][A-Z0-9-]*)>')
_BLANK = b' \t'


def field_from(line: Line, name: str, key: str | None, value_offset: int) -> Field:
    """The field whose value is line.text[value_offset:] with surrounding blanks removed."""
    raw = line.text[value_offset:]
    lead = len(raw) - len(raw.lstrip(_BLANK))
    value = raw.strip(_BLANK)
    start = line.start + value_offset + lead
    return Field(name, key, value.decode('ascii'), line.number, start, start + len(value))


def tag_field(line: Line, names: Mapping[str, Name]) -> Field | None:
    """A `<NAME>value` line as a field; None when the line is not a tag line."""
    match = TAG_LINE.fullmatch(line.text)
    if match is None:
        return None
    name = match[1].decode('ascii')
    known = names.get(name)
    return field_from(line, name, known.key if known else None, len(name) + 2)
```

`packages/sec-edgar-filings/src/sec_edgar_filings/documents.py`:

```python
"""Document blocks, shared by both serializations (methodology P3 step 4, spec R15).

A payload is the bytes from the first byte after the <TEXT> line up to the first byte of
the line-initial </TEXT> line. It keeps the terminator of its last line. A </TEXT> that
does not fill its own line does not close the payload.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .errors import EnvelopeRefusal
from .grammar import DOCUMENT_BLOCK, DOCUMENT_TAGS, PAYLOAD
from .lines import Field, Line, LineReader, tag_field

DOCUMENT_OPEN = f'<{DOCUMENT_BLOCK.text}>'.encode()
DOCUMENT_CLOSE = f'</{DOCUMENT_BLOCK.text}>'.encode()
TEXT_OPEN = f'<{PAYLOAD.text}>'.encode()
TEXT_CLOSE = f'</{PAYLOAD.text}>'.encode()
SEQUENCE = re.compile(r'[1-9][0-9]*')


@dataclass(frozen=True, slots=True)
class DocumentBlock:
    """One document block: metadata lines and the payload byte range."""
    line: int                  # the <DOCUMENT> line
    fields: tuple[Field, ...]  # metadata lines before <TEXT>, known and unknown
    type: str
    sequence: int
    filename: str | None
    description: str | None
    start: int                 # payload: first byte after the <TEXT> line
    end: int                   # payload: first byte of the line-initial </TEXT> line
    sha256: str                # h_delta over data[start:end]


def parse_documents(reader: LineReader, closing: bytes) -> tuple[DocumentBlock, ...]:
    """Every document block up to the file's closing line, which must end the file."""
    documents: list[DocumentBlock] = []
    sequences: set[int] = set()
    reader.skip_blank()
    while True:
        line = reader.peek()
        if line is None:
            raise EnvelopeRefusal(reader.number, f'missing closing line {closing.decode()}')
        if line.text == closing:
            reader.read()
            reader.skip_blank()
            if reader.peek() is not None:
                raise EnvelopeRefusal(reader.number, 'content follows the closing line')
            break
        if line.text != DOCUMENT_OPEN:
            raise EnvelopeRefusal(line.number, 'expected a <DOCUMENT> line or the closing line')
        document = _document(reader)
        if document.sequence in sequences:
            raise EnvelopeRefusal(document.line, f'duplicate document sequence {document.sequence}')
        sequences.add(document.sequence)
        documents.append(document)
        reader.skip_blank()
    if not documents:
        raise EnvelopeRefusal(reader.number - 1, 'submission has no document block')
    return tuple(documents)


def _document(reader: LineReader) -> DocumentBlock:
    opening = reader.read()
    fields = []
    while True:
        line = reader.read()
        if line is None:
            raise EnvelopeRefusal(opening.number, 'document block has no <TEXT> line')
        if line.text == TEXT_OPEN:
            break
        if not line.text.isascii():
            raise EnvelopeRefusal(line.number, 'document metadata line is not ASCII')
        field = tag_field(line, DOCUMENT_TAGS)
        if field is None:
            raise EnvelopeRefusal(line.number, 'document metadata line is not a tag line')
        fields.append(field)
    start = line.next
    end = _payload_end(reader.data, start, opening)
    reader.jump(end)
    reader.read()  # the </TEXT> line
    after = reader.read()
    if after is None or after.text != DOCUMENT_CLOSE:
        raise EnvelopeRefusal(after.number if after else reader.number,
                              'the line after </TEXT> is not </DOCUMENT>')
    values = {}
    for field in fields:
        if field.key is None:
            continue
        if field.key in values:
            raise EnvelopeRefusal(field.line, f'duplicate document tag {field.name}')
        values[field.key] = field
    for key in ('type', 'sequence'):
        if key not in values or not values[key].value:
            raise EnvelopeRefusal(opening.number, f'document block has no {key}')
    if SEQUENCE.fullmatch(values['sequence'].value) is None:
        raise EnvelopeRefusal(values['sequence'].line, 'document sequence is not a positive integer')
    optional = {key: values[key].value if key in values else None for key in ('filename', 'description')}
    return DocumentBlock(opening.number, tuple(fields), values['type'].value, int(values['sequence'].value),
                         optional['filename'], optional['description'], start, end,
                         hashlib.sha256(reader.data[start:end]).hexdigest())


def _payload_end(data: bytes, start: int, opening: Line) -> int:
    """Offset of the first line that is exactly </TEXT>, at or after `start`."""
    position = start - 1
    while True:
        newline = data.find(b'\n' + TEXT_CLOSE, position)
        if newline < 0:
            raise EnvelopeRefusal(opening.number, 'document block has no line-initial </TEXT>')
        candidate = newline + 1
        line_end = data.find(b'\n', candidate)
        text = data[candidate:len(data) if line_end < 0 else line_end].removesuffix(b'\r')
        if text == TEXT_CLOSE:
            return candidate
        position = candidate
```

- [ ] **Step 4: Run the tests**

Run the test command. Expected: `Ran 16 tests` and `OK`.

- [ ] **Step 5: Commit**

```bash
git add packages/sec-edgar-filings/src/sec_edgar_filings/errors.py packages/sec-edgar-filings/src/sec_edgar_filings/lines.py \
  packages/sec-edgar-filings/src/sec_edgar_filings/grammar.py packages/sec-edgar-filings/src/sec_edgar_filings/documents.py \
  packages/sec-edgar-filings/tests/support_documents.py packages/sec-edgar-filings/tests/test_documents.py
git commit -m "feat(filings): split document blocks at line-initial closing tags"
```

---

### Task 3: R16 document classes

**Files:**
- Create: `packages/sec-edgar-filings/src/sec_edgar_filings/classify.py`
- Modify: `packages/sec-edgar-filings/src/sec_edgar_filings/grammar.py` (append)
- Test: `packages/sec-edgar-filings/tests/support_payloads.py`, `packages/sec-edgar-filings/tests/test_classify.py`

**Interfaces:**
- Consumes: `documents.DocumentBlock`, `documents.parse_documents`, `lines.LineReader`, `errors.DocumentGap`, `support_documents.document`.
- Produces:
  - `classify.DocumentClass`, with the values `inline-xbrl`, `xbrl-instance`, `xbrl-schema`, `xbrl-linkbase`, `sec-generated`, `sec-extracted-instance`, `xml`, `uuencoded`, `text` and `unclassified`.
  - `classify.Classification(document_class, wrapper, root, content_start, content_end, reason)`; `classify.Document(block, classification)`.
  - `classify.classify(data: bytes, block: DocumentBlock) -> Classification`; `classify.decode_uuencoded(data: bytes, document: Document) -> bytes`, which raises `DocumentGap`.
  - Tests: `support_payloads.DOCUMENTS` (nine documents, one per non-`unclassified` class), `GRAPHIC`, `uuencode(data, name)`, `INLINE`, `INSTANCE`.

- [ ] **Step 1: Write the failing tests**

`packages/sec-edgar-filings/tests/support_payloads.py`:

```python
"""Payloads of each R16 class, and the nine-document set shared by both serializations."""
from __future__ import annotations

import binascii

from support_documents import PRESS_RELEASE, document

GRAPHIC = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,' \
          b'\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'


def uuencode(data: bytes, name: str) -> bytes:
    lines = [f'begin 644 {name}\n'.encode('ascii')]
    lines += [binascii.b2a_uu(data[offset:offset + 45], backtick=True) for offset in range(0, len(data), 45)]
    return b''.join(lines) + b'`\nend\n'


INLINE = (b'<XBRL>\n<?xml version="1.0" encoding="utf-8"?>\n'
          b'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"'
          b' xmlns:dei="http://xbrl.sec.gov/dei/2024">\n'
          b'<body><ix:nonNumeric name="dei:DocumentType" contextRef="c1">8-K</ix:nonNumeric></body>\n'
          b'</html>\n</XBRL>\n')
SCHEMA = (b'<XBRL>\n<?xml version="1.0" encoding="utf-8"?>\n'
          b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="http://example.com/20261015"/>\n'
          b'</XBRL>\n')
LINKBASE = (b'<XBRL>\n<?xml version="1.0" encoding="utf-8"?>\n'
            b'<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"/>\n</XBRL>\n')
INSTANCE = (b'<XBRL>\n<?xml version="1.0" encoding="utf-8"?>\n'
            b'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"/>\n</XBRL>\n')
R_FILE = b'<XBRL>\n<html><body><p>R1</p></body></html>\n</XBRL>\n'
REPORT = b'<XML>\n<?xml version="1.0"?>\n<report xmlns="http://example.com/report"/>\n</XML>\n'

DOCUMENTS = b''.join((
    document(1, '8-K', INLINE, filename='example-20261015.htm', description='8-K'),
    document(2, 'EX-99.1', PRESS_RELEASE, filename='ex99-1.htm', description='PRESS RELEASE'),
    document(3, 'GRAPHIC', uuencode(GRAPHIC, 'logo.gif'), filename='logo.gif'),
    document(4, 'EX-101.SCH', SCHEMA, filename='example-20261015.xsd', description='XBRL SCHEMA FILE'),
    document(5, 'EX-101.LAB', LINKBASE, filename='example-20261015_lab.xml', description='XBRL LABEL FILE'),
    document(6, 'EX-101.INS', INSTANCE, filename='example-20261015.xml', description='XBRL INSTANCE FILE'),
    document(7, 'XML', R_FILE, filename='R1.htm', description='IDEA: XBRL DOCUMENT'),
    document(8, 'XML', INSTANCE, filename='example-20261015_htm.xml', description='IDEA: XBRL DOCUMENT'),
    document(9, 'EX-99.2', REPORT, filename='report.xml', description='STRUCTURED REPORT'),
))
```

`packages/sec-edgar-filings/tests/test_classify.py`:

```python
import unittest

from sec_edgar_filings.classify import Document, DocumentClass, classify, decode_uuencoded
from sec_edgar_filings.documents import parse_documents
from sec_edgar_filings.errors import DocumentGap
from sec_edgar_filings.lines import LineReader
from support_documents import document
from support_payloads import DOCUMENTS, GRAPHIC, INLINE, INSTANCE, uuencode

CLOSING = b'</SUBMISSION>'


def documents(body: bytes):
    data = body + CLOSING + b'\n'
    return data, [Document(block, classify(data, block)) for block in parse_documents(LineReader(data), CLOSING)]


class ClassificationTests(unittest.TestCase):
    def test_each_fixture_document_gets_its_r16_class(self):
        _, found = documents(DOCUMENTS)
        self.assertEqual([(item.block.sequence, item.classification.document_class,
                           item.classification.wrapper) for item in found], [
            (1, DocumentClass.INLINE_XBRL, 'XBRL'),
            (2, DocumentClass.TEXT, None),
            (3, DocumentClass.UUENCODED, None),
            (4, DocumentClass.XBRL_SCHEMA, 'XBRL'),
            (5, DocumentClass.XBRL_LINKBASE, 'XBRL'),
            (6, DocumentClass.XBRL_INSTANCE, 'XBRL'),
            (7, DocumentClass.SEC_GENERATED, 'XBRL'),
            (8, DocumentClass.SEC_EXTRACTED_INSTANCE, 'XBRL'),
            (9, DocumentClass.XML, 'XML'),
        ])
        self.assertEqual(found[8].classification.root, '{http://example.com/report}report')

    def test_unwrapped_content_excludes_the_wrapper_lines(self):
        data, (item,) = documents(document(1, '8-K', INLINE))
        content = data[item.classification.content_start:item.classification.content_end]
        self.assertTrue(content.startswith(b'<?xml'))
        self.assertTrue(content.endswith(b'</html>\n'))

    def test_type_and_root_disagreements_are_unclassified(self):
        cases = [
            (document(1, 'EX-101.INS', INLINE), 'inline XBRL root under type EX-101.INS'),
            (document(1, 'EX-99.1', INSTANCE), 'traditional XBRL root under type EX-99.1'),
            (document(1, 'EX-101.PRE', b'<html><body>x</body></html>\n'),
             'type EX-101.PRE without a traditional XBRL root'),
        ]
        for body, reason in cases:
            with self.subTest(reason=reason):
                _, (item,) = documents(body)
                self.assertEqual((item.classification.document_class, item.classification.reason),
                                 (DocumentClass.UNCLASSIFIED, reason))

    def test_html_without_inline_namespace_is_text(self):
        xhtml = b'<?xml version="1.0"?>\n<html xmlns="http://www.w3.org/1999/xhtml"><body/></html>\n'
        for payload in (xhtml, b'<!DOCTYPE html>\n<HTML><BODY><P>x<BR></BODY></HTML>\n', b'plain text\n'):
            with self.subTest(payload=payload[:20]):
                _, (item,) = documents(document(1, 'EX-99.1', payload))
                self.assertEqual(item.classification.document_class, DocumentClass.TEXT)

    def test_uuencoded_graphic_decodes_to_its_bytes(self):
        data, (item,) = documents(document(1, 'GRAPHIC', uuencode(GRAPHIC, 'logo.gif')))
        self.assertEqual(decode_uuencoded(data, item), GRAPHIC)

    def test_pdf_wrapper_holds_a_uuencoded_payload(self):
        payload = b'<PDF>\n' + uuencode(b'%PDF-1.4 fixture', 'a.pdf') + b'</PDF>\n'
        data, (item,) = documents(document(1, 'EX-99.1', payload))
        self.assertEqual((item.classification.document_class, item.classification.wrapper),
                         (DocumentClass.UUENCODED, 'PDF'))
        self.assertEqual(decode_uuencoded(data, item), b'%PDF-1.4 fixture')

    def test_decode_failures_are_document_gaps(self):
        good = uuencode(GRAPHIC, 'logo.gif')
        cases = {
            'uuencoded payload has no end line': good.replace(b'end\n', b''),
            'line 6: uuencoded line is shorter than its length character':
                good.replace(good.splitlines()[1], good.splitlines()[1][:-8]),
            'uuencoded payload has no terminator line': good.replace(b'`\nend\n', b'end\n'),
        }
        for reason, payload in cases.items():
            with self.subTest(reason=reason):
                data, (item,) = documents(document(1, 'GRAPHIC', payload))
                with self.assertRaises(DocumentGap) as caught:
                    decode_uuencoded(data, item)
                self.assertEqual(str(caught.exception), reason)
        data, (item,) = documents(document(1, 'EX-99.1', b'plain text\n'))
        with self.assertRaises(DocumentGap):
            decode_uuencoded(data, item)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run the test command. Expected: `FAILED (errors=1)` with `ModuleNotFoundError: No module named 'sec_edgar_filings.classify'`.

- [ ] **Step 3: Implement**

Append to `packages/sec-edgar-filings/src/sec_edgar_filings/grammar.py`, after one blank line:

```python
# Payload wrappers: a payload whose first and last non-blank lines are <NAME> and </NAME>.
WRAPPERS = (Token('XBRL', C), Token('PDF', C), Token('XML', A))
SEC_GENERATED_DESCRIPTION = Token('IDEA: XBRL DOCUMENT', C)
TRADITIONAL_XBRL_TYPE_PREFIX = Token('EX-101.', S)
XBRL_INSTANCE_ROOT = Token('{http://www.xbrl.org/2003/instance}xbrl', A)
XBRL_SCHEMA_ROOT = Token('{http://www.w3.org/2001/XMLSchema}schema', A)
XBRL_LINKBASE_ROOT = Token('{http://www.xbrl.org/2003/linkbase}linkbase', A)
XHTML_ROOT = Token('{http://www.w3.org/1999/xhtml}html', A)
INLINE_XBRL_NAMESPACE = Token('http://www.xbrl.org/2013/inlineXBRL', A)
UUENCODE_BEGIN = Token('begin ', M)
```

`packages/sec-edgar-filings/src/sec_edgar_filings/classify.py`:

```python
"""R16 document classes: the declared type plus the root element after unwrapping.

The root is read with an XML pull parser that stops at the first start tag, so a large
payload is not parsed. Expat does not fetch external entities.
"""
from __future__ import annotations

import binascii
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from enum import StrEnum

from .errors import DocumentGap
from .grammar import (
    INLINE_XBRL_NAMESPACE, SEC_GENERATED_DESCRIPTION, TRADITIONAL_XBRL_TYPE_PREFIX, UUENCODE_BEGIN,
    WRAPPERS, XBRL_INSTANCE_ROOT, XBRL_LINKBASE_ROOT, XBRL_SCHEMA_ROOT, XHTML_ROOT,
)
from .documents import DocumentBlock
from .lines import LineReader


class DocumentClass(StrEnum):
    """R16 classes: declared type plus root element after unwrapping."""
    INLINE_XBRL = 'inline-xbrl'
    XBRL_INSTANCE = 'xbrl-instance'
    XBRL_SCHEMA = 'xbrl-schema'
    XBRL_LINKBASE = 'xbrl-linkbase'
    SEC_GENERATED = 'sec-generated'
    SEC_EXTRACTED_INSTANCE = 'sec-extracted-instance'
    XML = 'xml'
    UUENCODED = 'uuencoded'
    TEXT = 'text'
    UNCLASSIFIED = 'unclassified'


@dataclass(frozen=True, slots=True)
class Classification:
    document_class: DocumentClass
    wrapper: str | None      # 'XBRL', 'PDF' or 'XML' when the payload is wrapped
    root: str | None         # '{namespace}local' of the unwrapped content, None if not XML
    content_start: int       # unwrapped content range inside the payload
    content_end: int
    reason: str | None       # why a document is unclassified


@dataclass(frozen=True, slots=True)
class Document:
    block: DocumentBlock
    classification: Classification


TRADITIONAL_ROOTS = {
    XBRL_INSTANCE_ROOT.text: DocumentClass.XBRL_INSTANCE,
    XBRL_SCHEMA_ROOT.text: DocumentClass.XBRL_SCHEMA,
    XBRL_LINKBASE_ROOT.text: DocumentClass.XBRL_LINKBASE,
}
BEGIN = re.compile(re.escape(UUENCODE_BEGIN.text.encode()) + rb'[0-7]{3,4} \S.*')
_CHUNK = 1 << 16


def classify(data: bytes, block: DocumentBlock) -> Classification:
    start, end, wrapper = block.start, block.end, None
    first, last = _first_line(data, start, end), _last_line(data, start, end)
    if first is not None and last is not None and first[0] < last[0]:
        for token in WRAPPERS:
            if first[1] == f'<{token.text}>'.encode() and last[1] == f'</{token.text}>'.encode():
                wrapper, start, end = token.text, first[2], last[0]
                break
    content_first = _first_line(data, start, end)
    uuencoded = content_first is not None and BEGIN.fullmatch(content_first[1]) is not None
    root, namespaces = (None, frozenset()) if uuencoded else _root(data, start, end)
    traditional = block.type.startswith(TRADITIONAL_XBRL_TYPE_PREFIX.text)
    html = root is not None and root.rsplit('}', 1)[-1].lower() == 'html'
    reason = None
    if block.description == SEC_GENERATED_DESCRIPTION.text:
        document_class = (DocumentClass.SEC_EXTRACTED_INSTANCE if root == XBRL_INSTANCE_ROOT.text
                          else DocumentClass.SEC_GENERATED)
    elif uuencoded:
        document_class = DocumentClass.UUENCODED
    elif root in TRADITIONAL_ROOTS:
        document_class = TRADITIONAL_ROOTS[root] if traditional else DocumentClass.UNCLASSIFIED
        reason = None if traditional else f'traditional XBRL root under type {block.type}'
    elif root == XHTML_ROOT.text and INLINE_XBRL_NAMESPACE.text in namespaces:
        document_class = DocumentClass.UNCLASSIFIED if traditional else DocumentClass.INLINE_XBRL
        reason = f'inline XBRL root under type {block.type}' if traditional else None
    elif traditional:
        document_class, reason = DocumentClass.UNCLASSIFIED, f'type {block.type} without a traditional XBRL root'
    elif root is not None and not html:
        document_class = DocumentClass.XML
    else:
        document_class = DocumentClass.TEXT
    return Classification(document_class, wrapper, root, start, end, reason)


def decode_uuencoded(data: bytes, document: Document) -> bytes:
    """Decode a uuencoded payload with its begin and end lines and line lengths verified."""
    content = document.classification
    if content.document_class is not DocumentClass.UUENCODED:
        raise DocumentGap('document is not uuencoded')
    first = data.count(b'\n', 0, content.content_start) + 1
    reader, lines = LineReader(data, content.content_start, first), []
    while reader.offset < content.content_end:
        lines.append(reader.read())
    while lines and not lines[-1].text.strip():
        lines.pop()
    if len(lines) < 2 or lines[-1].text != b'end':
        raise DocumentGap('uuencoded payload has no end line')
    decoded, finished = bytearray(), False
    for line in lines[1:-1]:
        if finished:
            raise DocumentGap(f'line {line.number}: data after the uuencode terminator line')
        if not line.text:
            raise DocumentGap(f'line {line.number}: empty uuencoded line')
        count = (line.text[0] - 32) & 0x3F
        if count == 0:
            finished = True
            continue
        needed = 1 + 4 * ((count + 2) // 3)
        if len(line.text) < needed:
            raise DocumentGap(f'line {line.number}: uuencoded line is shorter than its length character')
        try:
            decoded += binascii.a2b_uu(line.text[:needed])
        except binascii.Error as error:
            raise DocumentGap(f'line {line.number}: {error}') from None
    if not finished:
        raise DocumentGap('uuencoded payload has no terminator line')
    return bytes(decoded)


def _first_line(data: bytes, start: int, end: int) -> tuple[int, bytes, int] | None:
    """(start, text, next) of the first non-blank line inside [start, end)."""
    reader = LineReader(data, start)
    while reader.offset < end:
        line = reader.read()
        if line.text.strip():
            return line.start, line.text, min(line.next, end)
    return None


def _last_line(data: bytes, start: int, end: int) -> tuple[int, bytes] | None:
    """(start, text) of the last non-blank line inside [start, end)."""
    stop = end
    while stop > start:
        newline = data.rfind(b'\n', start, stop - 1)
        line_start = start if newline < 0 else newline + 1
        text = data[line_start:stop].rstrip(b'\r\n')
        if text.strip():
            return line_start, text
        stop = line_start
    return None


def _root(data: bytes, start: int, end: int) -> tuple[str | None, frozenset[str]]:
    while start < end and data[start] in b' \t\r\n':
        start += 1
    parser = ElementTree.XMLPullParser(events=('start-ns', 'start'))
    namespaces = set()
    try:
        for offset in range(start, end, _CHUNK):
            parser.feed(data[offset:min(offset + _CHUNK, end)])
            for event, value in parser.read_events():
                if event == 'start-ns':
                    namespaces.add(value[1])
                else:
                    return value.tag, frozenset(namespaces)
    except ElementTree.ParseError:
        pass
    return None, frozenset()
```

- [ ] **Step 4: Run the tests**

Run the test command. Expected: `Ran 23 tests` and `OK`.

- [ ] **Step 5: Commit**

```bash
git add packages/sec-edgar-filings/src/sec_edgar_filings/classify.py packages/sec-edgar-filings/src/sec_edgar_filings/grammar.py \
  packages/sec-edgar-filings/tests/support_payloads.py packages/sec-edgar-filings/tests/test_classify.py
git commit -m "feat(filings): classify documents by declared type and unwrapped root (R16)"
```

---

### Task 4: Labeled-line header

**Files:**
- Create: `packages/sec-edgar-filings/src/sec_edgar_filings/tree.py`, `packages/sec-edgar-filings/src/sec_edgar_filings/header_labeled.py`
- Modify: `packages/sec-edgar-filings/src/sec_edgar_filings/grammar.py` (append)
- Test: `packages/sec-edgar-filings/tests/support_headers.py`, `packages/sec-edgar-filings/tests/test_header_labeled.py`

**Interfaces:**
- Consumes: `lines.Field`, `lines.Line`, `lines.LineReader`, `lines.TAG_LINE`, `lines.field_from`, `errors.EnvelopeRefusal`.
- Produces:
  - `tree.Block(name, key, line, start, fields, blocks)`; `tree.BlockBuilder`; `tree.walk_fields(block)`; `tree.walk_blocks(block)`; `tree.unknown_entries(block) -> int`.
  - `header_labeled.lex_labeled(reader: LineReader) -> Block`, whose root has name `SEC-HEADER` and key `header`.
  - `grammar.LABELED: dict[str, Name]`, `grammar.LABELED_FILE`, `grammar.LABELED_HEADER`.
  - Tests: `support_headers.LABELED_HEADER: bytes`; `support_headers.shape(block) -> list`.

- [ ] **Step 1: Write the failing tests**

`packages/sec-edgar-filings/tests/support_headers.py` (Task 5 appends to it):

```python
"""Headers of one hand-built submission in both serializations."""
from __future__ import annotations

LABELED_HEADER = (
    '<SEC-DOCUMENT>0000990001-26-000123.txt : 20261015\n'
    '<SEC-HEADER>0000990001-26-000123.hdr.sgml : 20261015\n'
    '<ACCEPTANCE-DATETIME>20261015163015\n'
    'ACCESSION NUMBER:\t\t0000990001-26-000123\n'
    'CONFORMED SUBMISSION TYPE:\t8-K\n'
    'PUBLIC DOCUMENT COUNT:\t\t9\n'
    'CONFORMED PERIOD OF REPORT:\t20261014\n'
    'ITEM INFORMATION:\t\tResults of Operations and Financial Condition\n'
    'ITEM INFORMATION:\t\tFinancial Statements and Exhibits\n'
    'FILED AS OF DATE:\t\t20261015\n'
    'DATE AS OF CHANGE:\t\t20261015\n'
    'LEGAL ENTITY IDENTIFIER:\t5493001EXAMPLE000001\n'
    '\n'
    'FILER:\n'
    '\n'
    '\tCOMPANY DATA:\t\n'
    '\t\tCOMPANY CONFORMED NAME:\t\t\tEXAMPLE HOLDINGS INC\n'
    '\t\tCENTRAL INDEX KEY:\t\t\t0000990001\n'
    '\t\tSTANDARD INDUSTRIAL CLASSIFICATION:\t3571\n'
    '\t\tIRS NUMBER:\t\t\t\t123456789\n'
    '\t\tSTATE OF INCORPORATION:\t\t\tDE\n'
    '\t\tFISCAL YEAR END:\t\t\t1231\n'
    '\n'
    '\tFILING VALUES:\n'
    '\t\tFORM TYPE:\t\t8-K\n'
    '\t\tSEC ACT:\t\t1934 Act\n'
    '\t\tSEC FILE NUMBER:\t001-00001\n'
    '\t\tFILM NUMBER:\t\t261234567\n'
    '\n'
    '\tBUSINESS ADDRESS:\t\n'
    '\t\tSTREET 1:\t\t1 EXAMPLE PLAZA\n'
    '\t\tCITY:\t\t\tNEW YORK\n'
    '\t\tSTATE:\t\t\tNY\n'
    '\t\tZIP:\t\t\t10001\n'
    '\t\tBUSINESS PHONE:\t\t2125550100\n'
    '\n'
    '\tMAIL ADDRESS:\t\n'
    '\t\tSTREET 1:\t\t1 EXAMPLE PLAZA\n'
    '\t\tCITY:\t\t\tNEW YORK\n'
    '\t\tSTATE:\t\t\tNY\n'
    '\t\tZIP:\t\t\t10001\n'
    '\n'
    '\tFORMER COMPANY:\t\n'
    '\t\tFORMER CONFORMED NAME:\tEXAMPLE CORP\n'
    '\t\tDATE OF NAME CHANGE:\t20190301\n'
    '\n'
    'FILER:\n'
    '\n'
    '\tCOMPANY DATA:\t\n'
    '\t\tCOMPANY CONFORMED NAME:\t\t\tEXAMPLE FUNDING LLC\n'
    '\t\tCENTRAL INDEX KEY:\t\t\t990002\n'
    '\t\tSTATE OF INCORPORATION:\t\t\tDE\n'
    '\n'
    '\tFILING VALUES:\n'
    '\t\tFORM TYPE:\t\t8-K\n'
    '\t\tSEC ACT:\t\t1934 Act\n'
    '\t\tSEC FILE NUMBER:\t333-00002\n'
    '\t\tFILM NUMBER:\t\t261234568\n'
    '</SEC-HEADER>\n'
).encode('ascii')


def shape(block):
    """[key, field keys, child shapes] of a header block, for compact tree assertions."""
    return [block.key, [field.key for field in block.fields], [shape(child) for child in block.blocks]]
```

`packages/sec-edgar-filings/tests/test_header_labeled.py`:

```python
import unittest

from sec_edgar_filings.errors import EnvelopeRefusal
from sec_edgar_filings.header_labeled import lex_labeled
from sec_edgar_filings.lines import LineReader
from support_headers import LABELED_HEADER, shape


def lex(header: bytes = LABELED_HEADER):
    return lex_labeled(LineReader(header))


class LabeledHeaderTests(unittest.TestCase):
    def test_header_tree_follows_tab_depth(self):
        root = lex()
        self.assertEqual((root.name, root.key, root.line), ('SEC-HEADER', 'header', 2))
        self.assertEqual([field.key for field in root.fields], [
            'sec-document', 'sec-header', 'acceptance-datetime', 'accession-number', 'submission-type',
            'public-document-count', 'period-of-report', 'item-information', 'item-information',
            'filing-date', 'date-of-change', None])
        self.assertEqual(shape(root.blocks[0]), ['filer', [], [
            ['company-data', ['conformed-name', 'cik', 'assigned-sic', 'irs-number',
                              'state-of-incorporation', 'fiscal-year-end'], []],
            ['filing-values', ['form-type', 'act', 'file-number', 'film-number'], []],
            ['business-address', ['street1', 'city', 'state', 'zip', 'phone'], []],
            ['mail-address', ['street1', 'city', 'state', 'zip'], []],
            ['former-company', ['former-conformed-name', 'date-changed'], []]]])
        self.assertEqual([block.key for block in root.blocks], ['filer', 'filer'])

    def test_values_are_stripped_and_located(self):
        root = lex()
        accession = root.fields[3]
        self.assertEqual((accession.name, accession.value, accession.line), ('ACCESSION NUMBER', '0000990001-26-000123', 4))
        self.assertEqual(LABELED_HEADER[accession.start:accession.end], b'0000990001-26-000123')
        acceptance = root.fields[2]
        self.assertEqual((acceptance.name, acceptance.value), ('<ACCEPTANCE-DATETIME>', '20261015163015'))

    def test_unknown_label_is_retained_verbatim(self):
        unknown = lex().fields[-1]
        self.assertEqual((unknown.name, unknown.key, unknown.value, unknown.line),
                         ('LEGAL ENTITY IDENTIFIER', None, '5493001EXAMPLE000001', 12))

    def test_empty_value_without_deeper_lines_is_a_field(self):
        header = LABELED_HEADER.replace(b'DATE AS OF CHANGE:\t\t20261015\n', b'DATE AS OF CHANGE:\n')
        field = [field for field in lex(header).fields if field.key == 'date-of-change'][0]
        self.assertEqual(field.value, '')

    def test_malformed_lines_refuse(self):
        cases = {
            b'FILED AS OF DATE:\t\t20261015\n': (b'FILED AS OF DATE 20261015\n', 10,
                                                   'header line is neither a labeled line nor a tag line'),
            b'\t\tCITY:\t\t\tNEW YORK\n': (b'\t\tCITY:\t\t\tNEW Y\xc3\x96RK\n', 32, 'header line is not ASCII'),
            b'</SEC-HEADER>\n': (b'', 59, 'header has no </SEC-HEADER> line'),
        }
        for old, (new, line, reason) in cases.items():
            with self.subTest(reason=reason), self.assertRaises(EnvelopeRefusal) as caught:
                lex(LABELED_HEADER.replace(old, new, 1))
            self.assertEqual((caught.exception.line, caught.exception.reason), (line, reason))

    def test_the_first_two_lines_are_the_document_and_header_lines(self):
        with self.assertRaises(EnvelopeRefusal) as caught:
            lex(LABELED_HEADER.replace(b'<SEC-HEADER>', b'<SEC-HEADERS>', 1))
        self.assertEqual((caught.exception.line, caught.exception.reason), (2, 'expected the <SEC-HEADER> line'))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run the test command. Expected: `FAILED (errors=1)` with `ModuleNotFoundError: No module named 'sec_edgar_filings.header_labeled'`.

- [ ] **Step 3: Implement**

Append to `packages/sec-edgar-filings/src/sec_edgar_filings/grammar.py`, after one blank line:

```python
# Labels of the complete submission file. A name in angle brackets is a tag line
# inside the labeled header; every other name is a label before the first colon.
LABELED: dict[str, Name] = {
    '<SEC-DOCUMENT>': Name('sec-document', A),
    '<SEC-HEADER>': Name('sec-header', A),
    '<ACCEPTANCE-DATETIME>': Name('acceptance-datetime', A),
    'ACCESSION NUMBER': Name('accession-number', M),
    'CONFORMED SUBMISSION TYPE': Name('submission-type', M),
    'PUBLIC DOCUMENT COUNT': Name('public-document-count', C),
    'CONFORMED PERIOD OF REPORT': Name('period-of-report', M),
    'ITEM INFORMATION': Name('item-information', M),
    'FILED AS OF DATE': Name('filing-date', C),
    'DATE AS OF CHANGE': Name('date-of-change', C),
    'FILER': Name('filer', M),
    'FILED BY': Name('filed-by', M),
    'FILED FOR': Name('filed-for', M),
    'SUBJECT COMPANY': Name('subject-company', M),
    'REPORTING-OWNER': Name('reporting-owner', A),
    'ISSUER': Name('issuer', M),
    'COMPANY DATA': Name('company-data', M),
    'OWNER DATA': Name('owner-data', M),
    'FILING VALUES': Name('filing-values', M),
    'BUSINESS ADDRESS': Name('business-address', M),
    'MAIL ADDRESS': Name('mail-address', M),
    'FORMER COMPANY': Name('former-company', A),
    'FORMER NAME': Name('former-name', A),
    'COMPANY CONFORMED NAME': Name('conformed-name', A),
    'CENTRAL INDEX KEY': Name('cik', A),
    'STANDARD INDUSTRIAL CLASSIFICATION': Name('assigned-sic', M),
    'IRS NUMBER': Name('irs-number', M),
    'STATE OF INCORPORATION': Name('state-of-incorporation', M),
    'FISCAL YEAR END': Name('fiscal-year-end', M),
    'FORM TYPE': Name('form-type', M),
    'SEC ACT': Name('act', A),
    'SEC FILE NUMBER': Name('file-number', A),
    'FILM NUMBER': Name('film-number', M),
    'STREET 1': Name('street1', A),
    'STREET 2': Name('street2', A),
    'CITY': Name('city', A),
    'STATE': Name('state', A),
    'ZIP': Name('zip', A),
    'BUSINESS PHONE': Name('phone', A),
    'FORMER CONFORMED NAME': Name('former-conformed-name', A),
    'DATE OF NAME CHANGE': Name('date-changed', M),
}

# Structure lines of the complete submission file.
LABELED_FILE = Token('SEC-DOCUMENT', A)
LABELED_HEADER = Token('SEC-HEADER', A)
```

`packages/sec-edgar-filings/src/sec_edgar_filings/tree.py`:

```python
"""Header blocks: the frozen tree, the builder used while lexing, and walkers."""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from .lines import Field


@dataclass(frozen=True, slots=True)
class Block:
    """A header block (the root, a role block or a sub-block) with its entries in file order."""
    name: str
    key: str | None
    line: int
    start: int  # offset of the block's opening line
    fields: tuple[Field, ...]
    blocks: tuple[Block, ...]


@dataclass(slots=True)
class BlockBuilder:
    name: str
    key: str | None
    line: int
    start: int
    fields: list[Field] = dataclass_field(default_factory=list)
    blocks: list[BlockBuilder] = dataclass_field(default_factory=list)

    def freeze(self) -> Block:
        return Block(self.name, self.key, self.line, self.start, tuple(self.fields),
                     tuple(child.freeze() for child in self.blocks))


def unknown_entries(block: Block) -> int:
    return (sum(1 for field in block.fields if field.key is None)
            + sum(unknown_entries(child) + (child.key is None) for child in block.blocks))


def walk_fields(block: Block):
    """Every field of a block and its descendants, in file order within each block."""
    yield from block.fields
    for child in block.blocks:
        yield from walk_fields(child)


def walk_blocks(block: Block):
    yield block
    for child in block.blocks:
        yield from walk_blocks(child)
```

`packages/sec-edgar-filings/src/sec_edgar_filings/header_labeled.py`:

```python
"""Header of the complete submission file: labeled lines nested by leading tabs.

Draft grammar (methodology P3, unconfirmed):
- Line 1 is the <SEC-DOCUMENT> tag line and line 2 the <SEC-HEADER> tag line.
- The header ends at the line that is exactly </SEC-HEADER>.
- A labeled line is LABEL:value, split at its first colon. Its depth is its count of
  leading tabs. A tag line <NAME>value inside the header has depth 0.
- A labeled line with an empty value opens a block when the next non-blank entry is deeper.
- Blank lines carry no entry. Every header line must be ASCII.
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import EnvelopeRefusal
from .grammar import LABELED, LABELED_FILE, LABELED_HEADER
from .lines import TAG_LINE, Field, Line, LineReader, field_from
from .tree import Block, BlockBuilder

HEADER_CLOSE = f'</{LABELED_HEADER.text}>'.encode()


@dataclass(frozen=True, slots=True)
class _Entry:
    depth: int
    line: Line
    name: str
    value_offset: int
    tag: bool


def lex_labeled(reader: LineReader) -> Block:
    file_line = _opening(reader, LABELED_FILE.text)
    header_line = _opening(reader, LABELED_HEADER.text)
    root = BlockBuilder(LABELED_HEADER.text, 'header', header_line.number, header_line.start)
    root.fields.append(_tag_line(file_line, LABELED_FILE.text))
    root.fields.append(_tag_line(header_line, LABELED_HEADER.text))
    entries = _entries(reader)
    stack: list[tuple[int, BlockBuilder]] = [(-1, root)]
    for index, entry in enumerate(entries):
        known = LABELED.get(entry.name)
        key = known.key if known else None
        value = entry.line.text[entry.value_offset:].strip(b' \t')
        following = entries[index + 1] if index + 1 < len(entries) else None
        opens = (not entry.tag and not value and following is not None
                 and following.depth > entry.depth)
        while stack[-1][0] >= entry.depth:
            stack.pop()
        parent = stack[-1][1]
        if opens:
            child = BlockBuilder(entry.name, key, entry.line.number, entry.line.start)
            parent.blocks.append(child)
            stack.append((entry.depth, child))
        else:
            parent.fields.append(field_from(entry.line, entry.name, key, entry.value_offset))
    return root.freeze()


def _tag_line(line: Line, name: str) -> Field:
    bracketed = f'<{name}>'
    known = LABELED.get(bracketed)
    return field_from(line, bracketed, known.key if known else None, len(bracketed))


def _opening(reader: LineReader, tag: str) -> Line:
    line = reader.read()
    if line is None or not line.text.startswith(f'<{tag}>'.encode()):
        raise EnvelopeRefusal(line.number if line else reader.number, f'expected the <{tag}> line')
    if not line.text.isascii():
        raise EnvelopeRefusal(line.number, 'header line is not ASCII')
    return line


def _entries(reader: LineReader) -> list[_Entry]:
    entries = []
    while True:
        line = reader.read()
        if line is None:
            raise EnvelopeRefusal(reader.number, f'header has no {HEADER_CLOSE.decode()} line')
        if line.text == HEADER_CLOSE:
            return entries
        if not line.text.strip():
            continue
        if not line.text.isascii():
            raise EnvelopeRefusal(line.number, 'header line is not ASCII')
        match = TAG_LINE.fullmatch(line.text)
        if match is not None:
            name = match[1].decode('ascii')
            entries.append(_Entry(0, line, f'<{name}>', len(name) + 2, True))
            continue
        depth = len(line.text) - len(line.text.lstrip(b'\t'))
        colon = line.text.find(b':', depth)
        label = line.text[depth:colon].strip(b' \t') if colon >= 0 else b''
        if not label:
            raise EnvelopeRefusal(line.number, 'header line is neither a labeled line nor a tag line')
        entries.append(_Entry(depth, line, label.decode('ascii'), colon + 1, False))
```

- [ ] **Step 4: Run the tests**

Run the test command. Expected: `Ran 29 tests` and `OK`.

- [ ] **Step 5: Commit**

```bash
git add packages/sec-edgar-filings/src/sec_edgar_filings/tree.py packages/sec-edgar-filings/src/sec_edgar_filings/header_labeled.py \
  packages/sec-edgar-filings/src/sec_edgar_filings/grammar.py packages/sec-edgar-filings/tests/support_headers.py \
  packages/sec-edgar-filings/tests/test_header_labeled.py
git commit -m "feat(filings): lex the labeled-line header of the complete submission file"
```

---

### Task 5: Tagged header and the shared key vocabulary

**Files:**
- Create: `packages/sec-edgar-filings/src/sec_edgar_filings/header_tagged.py`
- Modify: `packages/sec-edgar-filings/src/sec_edgar_filings/grammar.py` (append), `packages/sec-edgar-filings/tests/support_headers.py` (append)
- Test: `packages/sec-edgar-filings/tests/test_header_tagged.py`, `packages/sec-edgar-filings/tests/test_grammar.py`

**Interfaces:**
- Consumes: `tree.Block`, `tree.BlockBuilder`, `lines.CLOSE_LINE`, `lines.TAG_LINE`, `lines.field_from`, `documents.DOCUMENT_OPEN`, `support_headers.shape`.
- Produces:
  - `header_tagged.lex_tagged(reader: LineReader) -> Block`, whose root has name `SUBMISSION` and key `header`. The reader is left at the first `<DOCUMENT>` line.
  - `grammar.TAGGED: dict[str, Name]`, `grammar.TAGGED_FILE`, `grammar.ENVELOPE_ONLY_KEYS`.
  - Tests: `support_headers.TAGGED_HEADER: bytes`, the same submission as `LABELED_HEADER`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/sec-edgar-filings/tests/support_headers.py`, after one blank line:

```python
TAGGED_HEADER = (
    '<SUBMISSION>\n'
    '<ACCESSION-NUMBER>0000990001-26-000123\n'
    '<TYPE>8-K\n'
    '<PUBLIC-DOCUMENT-COUNT>9\n'
    '<PERIOD>20261014\n'
    '<ITEMS>Results of Operations and Financial Condition\n'
    '<ITEMS>Financial Statements and Exhibits\n'
    '<FILING-DATE>20261015\n'
    '<DATE-OF-FILING-DATE-CHANGE>20261015\n'
    '<ACCEPTANCE-DATETIME>20261015163015\n'
    '<LEGAL-ENTITY-IDENTIFIER>5493001EXAMPLE000001\n'
    '<FILER>\n'
    '<COMPANY-DATA>\n'
    '<CONFORMED-NAME>EXAMPLE HOLDINGS INC\n'
    '<CIK>0000990001\n'
    '<ASSIGNED-SIC>3571\n'
    '<IRS-NUMBER>123456789\n'
    '<STATE-OF-INCORPORATION>DE\n'
    '<FISCAL-YEAR-END>1231\n'
    '</COMPANY-DATA>\n'
    '<FILING-VALUES>\n'
    '<FORM-TYPE>8-K\n'
    '<ACT>1934 Act\n'
    '<FILE-NUMBER>001-00001\n'
    '<FILM-NUMBER>261234567\n'
    '</FILING-VALUES>\n'
    '<BUSINESS-ADDRESS>\n'
    '<STREET1>1 EXAMPLE PLAZA\n'
    '<CITY>NEW YORK\n'
    '<STATE>NY\n'
    '<ZIP>10001\n'
    '<PHONE>2125550100\n'
    '</BUSINESS-ADDRESS>\n'
    '<MAIL-ADDRESS>\n'
    '<STREET1>1 EXAMPLE PLAZA\n'
    '<CITY>NEW YORK\n'
    '<STATE>NY\n'
    '<ZIP>10001\n'
    '</MAIL-ADDRESS>\n'
    '<FORMER-COMPANY>\n'
    '<FORMER-CONFORMED-NAME>EXAMPLE CORP\n'
    '<DATE-CHANGED>20190301\n'
    '</FORMER-COMPANY>\n'
    '</FILER>\n'
    '<FILER>\n'
    '<COMPANY-DATA>\n'
    '<CONFORMED-NAME>EXAMPLE FUNDING LLC\n'
    '<CIK>990002\n'
    '<STATE-OF-INCORPORATION>DE\n'
    '</COMPANY-DATA>\n'
    '<FILING-VALUES>\n'
    '<FORM-TYPE>8-K\n'
    '<ACT>1934 Act\n'
    '<FILE-NUMBER>333-00002\n'
    '<FILM-NUMBER>261234568\n'
    '</FILING-VALUES>\n'
    '</FILER>\n'
).encode('ascii')
```

`packages/sec-edgar-filings/tests/test_header_tagged.py`:

```python
import unittest

from sec_edgar_filings.errors import EnvelopeRefusal
from sec_edgar_filings.header_tagged import lex_tagged
from sec_edgar_filings.lines import LineReader
from support_headers import TAGGED_HEADER, shape


def lex(header: bytes = TAGGED_HEADER):
    return lex_tagged(LineReader(header + b'<DOCUMENT>\n'))


class TaggedHeaderTests(unittest.TestCase):
    def test_closed_tags_open_blocks(self):
        root = lex()
        self.assertEqual((root.name, root.key, root.line), ('SUBMISSION', 'header', 1))
        self.assertEqual([field.key for field in root.fields], [
            'accession-number', 'submission-type', 'public-document-count', 'period-of-report',
            'item-information', 'item-information', 'filing-date', 'date-of-change',
            'acceptance-datetime', None])
        self.assertEqual(shape(root.blocks[0]), ['filer', [], [
            ['company-data', ['conformed-name', 'cik', 'assigned-sic', 'irs-number',
                              'state-of-incorporation', 'fiscal-year-end'], []],
            ['filing-values', ['form-type', 'act', 'file-number', 'film-number'], []],
            ['business-address', ['street1', 'city', 'state', 'zip', 'phone'], []],
            ['mail-address', ['street1', 'city', 'state', 'zip'], []],
            ['former-company', ['former-conformed-name', 'date-changed'], []]]])

    def test_unclosed_bare_tag_is_an_empty_field(self):
        header = TAGGED_HEADER.replace(b'<LEGAL-ENTITY', b'<TIMESTAMP>20261015170000\n<PRIVATE-TO-PUBLIC>\n<LEGAL-ENTITY')
        fields = {field.key: field for field in lex(header).fields}
        self.assertEqual((fields['private-to-public'].value, fields['private-to-public'].line), ('', 12))
        self.assertEqual(fields['timestamp'].value, '20261015170000')

    def test_unknown_tags_and_containers_are_retained(self):
        header = TAGGED_HEADER.replace(b'<FILER>\n', b'<FUTURE-BLOCK>\n<FUTURE-FIELD>x\n</FUTURE-BLOCK>\n<FILER>\n', 1)
        root = lex(header)
        self.assertEqual((root.fields[-1].name, root.fields[-1].key), ('LEGAL-ENTITY-IDENTIFIER', None))
        future = root.blocks[0]
        self.assertEqual((future.name, future.key, [field.name for field in future.fields]),
                         ('FUTURE-BLOCK', None, ['FUTURE-FIELD']))
        self.assertEqual([block.key for block in root.blocks], [None, 'filer', 'filer'])

    def test_unbalanced_or_malformed_lines_refuse(self):
        cases = [
            (b'</MAIL-ADDRESS>\n', b'</BUSINESS-ADDRESS>\n', 39, '</BUSINESS-ADDRESS> does not close the open block'),
            (b'</FILER>\n', b'', 12, '<FILER> is not closed'),
            (b'<CITY>NEW YORK\n', b'CITY NEW YORK\n', 29, 'tagged header line is not a tag line'),
            (b'<SUBMISSION>\n', b'<SUBMISSIONS>\n', 1, 'expected the <SUBMISSION> line'),
        ]
        for old, new, line, reason in cases:
            with self.subTest(reason=reason), self.assertRaises(EnvelopeRefusal) as caught:
                lex(TAGGED_HEADER.replace(old, new, 1))
            self.assertEqual((caught.exception.line, caught.exception.reason), (line, reason))


if __name__ == '__main__':
    unittest.main()
```

`packages/sec-edgar-filings/tests/test_grammar.py`:

```python
import unittest

from sec_edgar_filings import grammar
from sec_edgar_filings.grammar import LABELED, TAGGED, Name, Source, Token


class GrammarTableTests(unittest.TestCase):
    def test_every_entry_names_its_source(self):
        entries = [*LABELED.values(), *TAGGED.values(), *grammar.DOCUMENT_TAGS.values(), *grammar.WRAPPERS]
        entries += [value for value in vars(grammar).values() if isinstance(value, Token)]
        self.assertGreater(len(entries), 90)
        for entry in entries:
            self.assertIsInstance(entry, Name | Token)
            self.assertIsInstance(entry.source, Source)

    def test_both_serializations_share_one_key_vocabulary(self):
        labeled_keys = {name.key for name in LABELED.values()} - {'sec-document', 'sec-header'}
        tagged_keys = {name.key for name in TAGGED.values()} - {'timestamp', 'private-to-public'}
        self.assertEqual(labeled_keys, tagged_keys)

    def test_each_name_maps_to_one_key(self):
        for table in (LABELED, TAGGED):
            keys = [name.key for name in table.values()]
            self.assertEqual(len(keys), len(set(keys)))

    def test_acceptance_never_comes_from_timestamp(self):
        self.assertEqual(TAGGED['TIMESTAMP'].key, 'timestamp')
        self.assertIn('timestamp', grammar.ENVELOPE_ONLY_KEYS)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run the test command. Expected: `FAILED (errors=2)` with `ImportError: cannot import name 'TAGGED' from 'sec_edgar_filings.grammar'`.

- [ ] **Step 3: Implement**

Append to `packages/sec-edgar-filings/src/sec_edgar_filings/grammar.py`, after one blank line:

```python
# Tags of the Feed member (tagged dissemination format).
TAGGED: dict[str, Name] = {
    'ACCESSION-NUMBER': Name('accession-number', F),
    'TYPE': Name('submission-type', F),
    'FILING-DATE': Name('filing-date', F),
    'TIMESTAMP': Name('timestamp', F),
    'PRIVATE-TO-PUBLIC': Name('private-to-public', F),
    'ACCEPTANCE-DATETIME': Name('acceptance-datetime', A),
    'PUBLIC-DOCUMENT-COUNT': Name('public-document-count', A),
    'PERIOD': Name('period-of-report', A),
    'ITEMS': Name('item-information', A),
    'DATE-OF-FILING-DATE-CHANGE': Name('date-of-change', A),
    'FILER': Name('filer', A),
    'FILED-BY': Name('filed-by', A),
    'FILED-FOR': Name('filed-for', A),
    'SUBJECT-COMPANY': Name('subject-company', A),
    'REPORTING-OWNER': Name('reporting-owner', A),
    'ISSUER': Name('issuer', A),
    'COMPANY-DATA': Name('company-data', A),
    'OWNER-DATA': Name('owner-data', A),
    'FILING-VALUES': Name('filing-values', A),
    'BUSINESS-ADDRESS': Name('business-address', A),
    'MAIL-ADDRESS': Name('mail-address', A),
    'FORMER-COMPANY': Name('former-company', A),
    'FORMER-NAME': Name('former-name', A),
    'CONFORMED-NAME': Name('conformed-name', A),
    'CIK': Name('cik', A),
    'ASSIGNED-SIC': Name('assigned-sic', A),
    'IRS-NUMBER': Name('irs-number', A),
    'STATE-OF-INCORPORATION': Name('state-of-incorporation', A),
    'FISCAL-YEAR-END': Name('fiscal-year-end', A),
    'FORM-TYPE': Name('form-type', A),
    'ACT': Name('act', A),
    'FILE-NUMBER': Name('file-number', A),
    'FILM-NUMBER': Name('film-number', A),
    'STREET1': Name('street1', A),
    'STREET2': Name('street2', A),
    'CITY': Name('city', A),
    'STATE': Name('state', A),
    'ZIP': Name('zip', A),
    'PHONE': Name('phone', A),
    'FORMER-CONFORMED-NAME': Name('former-conformed-name', A),
    'DATE-CHANGED': Name('date-changed', A),
}

TAGGED_FILE = Token('SUBMISSION', F)

# Serialization metadata: retained in the tree, never part of the header state.
ENVELOPE_ONLY_KEYS = frozenset({'sec-document', 'sec-header', 'timestamp', 'private-to-public'})
```

`packages/sec-edgar-filings/src/sec_edgar_filings/header_tagged.py`:

```python
"""Header of a Feed member: tag lines from <SUBMISSION> up to the first <DOCUMENT> line.

Draft grammar (findings section 4.4 for the tags it names; the rest is assumed):
- Line 1 is exactly <SUBMISSION>. Its closing line follows the last document block.
- <NAME>value with a non-empty value is a field.
- A bare <NAME> opens a block when a </NAME> line follows later in the header. Otherwise it
  is a field with an empty value, such as the <PRIVATE-TO-PUBLIC> flag. This rule needs no
  table, so an unknown container is kept as an unknown block.
- A </NAME> line must close the innermost open block. Every header line must be ASCII.
"""
from __future__ import annotations

from .errors import EnvelopeRefusal
from .grammar import TAGGED, TAGGED_FILE
from .lines import CLOSE_LINE, TAG_LINE, LineReader, field_from
from .documents import DOCUMENT_OPEN
from .tree import Block, BlockBuilder

FILE_OPEN = f'<{TAGGED_FILE.text}>'.encode()


def lex_tagged(reader: LineReader) -> Block:
    first = reader.read()
    if first is None or first.text != FILE_OPEN:
        raise EnvelopeRefusal(1, f'expected the {FILE_OPEN.decode()} line')
    root = BlockBuilder(TAGGED_FILE.text, 'header', first.number, first.start)
    lines = []
    while (line := reader.peek()) is not None and line.text != DOCUMENT_OPEN:
        reader.read()
        if not line.text.strip():
            continue
        if not line.text.isascii():
            raise EnvelopeRefusal(line.number, 'header line is not ASCII')
        lines.append(line)
    if line is None:
        raise EnvelopeRefusal(reader.number, 'tagged header has no <DOCUMENT> line')
    closes: dict[str, list[int]] = {}
    for index, line in enumerate(lines):
        if (match := CLOSE_LINE.fullmatch(line.text)) is not None:
            closes.setdefault(match[1].decode('ascii'), []).append(index)
    stack = [root]
    for index, line in enumerate(lines):
        if (match := CLOSE_LINE.fullmatch(line.text)) is not None:
            name = match[1].decode('ascii')
            if len(stack) == 1 or stack[-1].name != name:
                raise EnvelopeRefusal(line.number, f'</{name}> does not close the open block')
            stack.pop()
            continue
        match = TAG_LINE.fullmatch(line.text)
        if match is None:
            raise EnvelopeRefusal(line.number, 'tagged header line is not a tag line')
        name = match[1].decode('ascii')
        known = TAGGED.get(name)
        key = known.key if known else None
        if not match[2].strip(b' \t') and any(later > index for later in closes.get(name, ())):
            child = BlockBuilder(name, key, line.number, line.start)
            stack[-1].blocks.append(child)
            stack.append(child)
        else:
            stack[-1].fields.append(field_from(line, name, key, len(name) + 2))
    if len(stack) != 1:
        raise EnvelopeRefusal(stack[-1].line, f'<{stack[-1].name}> is not closed')
    return root.freeze()
```

- [ ] **Step 4: Run the tests**

Run the test command. Expected: `Ran 37 tests` and `OK`.

- [ ] **Step 5: Commit**

```bash
git add packages/sec-edgar-filings/src/sec_edgar_filings/header_tagged.py packages/sec-edgar-filings/src/sec_edgar_filings/grammar.py \
  packages/sec-edgar-filings/tests/support_headers.py packages/sec-edgar-filings/tests/test_header_tagged.py \
  packages/sec-edgar-filings/tests/test_grammar.py
git commit -m "feat(filings): lex the tagged Feed member header with retained unknown tags"
```

---

### Task 6: Envelope assembly, header state and round trip

**Files:**
- Create: `packages/sec-edgar-filings/src/sec_edgar_filings/record.py`, `packages/sec-edgar-filings/src/sec_edgar_filings/envelope.py`
- Modify: `packages/sec-edgar-filings/src/sec_edgar_filings/grammar.py` (append)
- Test: `packages/sec-edgar-filings/tests/support_envelopes.py`, `packages/sec-edgar-filings/tests/test_envelope.py`

**Interfaces:**
- Consumes: `lex_labeled`, `lex_tagged`, `parse_documents`, `classify`, `Document`, `DocumentClass`, `tree.walk_fields`, `tree.walk_blocks`, `tree.unknown_entries`.
- Produces:
  - `record.Serialization` (`complete-submission`, `feed-member`) and `record.Gap(code, line, detail)`.
  - `record.DateValue(field, value)`, `record.Acceptance(field, eastern, utc)`, `record.ItemLine(field, item)`, `record.RoleBlock(block, role, cik)`.
  - `record.Submission(accession_number, submission_type, filing_date, acceptance, items, roles, private_to_public)`.
  - `record.HeaderState(canonical, sha256)`; `record.Envelope(serialization, parser_version, header, submission, documents, header_state, gaps)` with `.counts() -> dict[str, int]`.
  - `envelope.parse_envelope(data: bytes, *, received_at: datetime) -> Envelope`; `envelope.header_state(header: Block) -> HeaderState`; `envelope.rederive_mismatches(data: bytes, envelope: Envelope) -> tuple[str, ...]`; `envelope.parse_date`; `envelope.parse_acceptance`; `envelope.ACCESSION`; `envelope.EASTERN`.
  - `grammar.ENVELOPE_PARSER_VERSION = 'sec-envelope-draft-1'`, `grammar.ROLE_KEYS`, `grammar.ENTITY_KEYS`.
  - Tests: `support_envelopes.RECEIVED`, `labeled(documents=DOCUMENTS) -> bytes`, `tagged(documents=DOCUMENTS) -> bytes`.

- [ ] **Step 1: Write the failing tests**

`packages/sec-edgar-filings/tests/support_envelopes.py`:

```python
"""Hand-built submissions in both serializations, describing the same submission.

The documents part is byte-identical in both, so payload hashes agree across them.
"""
from __future__ import annotations

from datetime import UTC, datetime

from support_headers import LABELED_HEADER, TAGGED_HEADER
from support_payloads import DOCUMENTS

RECEIVED = datetime(2026, 10, 16, tzinfo=UTC)


def labeled(documents: bytes = DOCUMENTS) -> bytes:
    """A complete submission file (labeled-line serialization)."""
    return LABELED_HEADER + documents + b'</SEC-DOCUMENT>\n'


def tagged(documents: bytes = DOCUMENTS) -> bytes:
    """A Feed member (tagged serialization) of the same submission."""
    return TAGGED_HEADER + documents + b'</SUBMISSION>\n'
```

`packages/sec-edgar-filings/tests/test_envelope.py`:

```python
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime

from sec_edgar_filings.envelope import parse_envelope, rederive_mismatches
from sec_edgar_filings.errors import EnvelopeRefusal
from sec_edgar_filings.grammar import ENVELOPE_PARSER_VERSION
from sec_edgar_filings.record import Serialization
from support_envelopes import RECEIVED, labeled, tagged


def parse(data: bytes):
    return parse_envelope(data, received_at=RECEIVED)


class EnvelopeTests(unittest.TestCase):
    def test_both_serializations_yield_the_same_record(self):
        for build, serialization in ((labeled, Serialization.COMPLETE_SUBMISSION),
                                     (tagged, Serialization.FEED_MEMBER)):
            with self.subTest(serialization=serialization):
                envelope = parse(build())
                submission = envelope.submission
                self.assertEqual((envelope.serialization, envelope.parser_version),
                                 (serialization, ENVELOPE_PARSER_VERSION))
                self.assertEqual(submission.accession_number.value, '0000990001-26-000123')
                self.assertEqual(submission.submission_type.value, '8-K')
                self.assertEqual(submission.filing_date.value, date(2026, 10, 15))
                self.assertEqual(submission.acceptance.field.value, '20261015163015')
                self.assertEqual(submission.acceptance.utc, datetime(2026, 10, 15, 20, 30, 15, tzinfo=UTC))
                self.assertEqual([(role.role, role.cik) for role in submission.roles],
                                 [('filer', '0000990001'), ('filer', '0000990002')])
                self.assertEqual([(item.field.value, item.item) for item in submission.items],
                                 [('Results of Operations and Financial Condition', None),
                                  ('Financial Statements and Exhibits', None)])
                self.assertIsNone(submission.private_to_public)

    def test_header_state_and_payload_hashes_agree_across_serializations(self):
        complete, member = parse(labeled()), parse(tagged())
        self.assertEqual(complete.header_state, member.header_state)
        self.assertEqual([document.block.sha256 for document in complete.documents],
                         [document.block.sha256 for document in member.documents])

    def test_header_state_ignores_unknown_entries_and_feed_metadata(self):
        base = parse(tagged()).header_state
        flagged = tagged().replace(b'<LEGAL-ENTITY', b'<TIMESTAMP>20261015170000\n<PRIVATE-TO-PUBLIC>\n<LEGAL-ENTITY')
        envelope = parse(flagged)
        self.assertEqual(envelope.header_state, base)
        self.assertEqual(envelope.submission.private_to_public.line, 12)
        self.assertEqual(envelope.submission.acceptance.field.value, '20261015163015')
        without_unknown = parse(tagged().replace(b'<LEGAL-ENTITY-IDENTIFIER>5493001EXAMPLE000001\n', b''))
        self.assertEqual(without_unknown.header_state, base)

    def test_a_changed_header_value_is_a_new_header_state(self):
        base = parse(labeled()).header_state
        moved = parse(labeled().replace(b'FILED AS OF DATE:\t\t20261015', b'FILED AS OF DATE:\t\t20261016'))
        self.assertNotEqual(moved.header_state.sha256, base.sha256)
        reordered = parse(labeled().replace(
            b'ITEM INFORMATION:\t\tResults of Operations and Financial Condition\n'
            b'ITEM INFORMATION:\t\tFinancial Statements and Exhibits\n',
            b'ITEM INFORMATION:\t\tFinancial Statements and Exhibits\n'
            b'ITEM INFORMATION:\t\tResults of Operations and Financial Condition\n'))
        self.assertEqual(reordered.header_state, base)

    def test_counts_and_gaps(self):
        envelope = parse(labeled())
        counts = envelope.counts()
        self.assertEqual({key: counts[key] for key in ('documents', 'role_blocks', 'unknown_entries',
                                                        'unmapped_items', 'gaps')},
                         {'documents': 9, 'role_blocks': 2, 'unknown_entries': 1, 'unmapped_items': 2, 'gaps': 2})
        self.assertEqual([(gap.code, gap.line) for gap in envelope.gaps],
                         [('unmapped-item', 8), ('unmapped-item', 9)])
        self.assertEqual(counts['class:inline-xbrl'], 1)
        self.assertEqual(sum(value for key, value in counts.items() if key.startswith('class:')), 9)

    def test_every_role_kind(self):
        labels = {'FILED BY': 'filed-by', 'FILED FOR': 'filed-for', 'SUBJECT COMPANY': 'subject-company',
                  'REPORTING-OWNER': 'reporting-owner', 'ISSUER': 'issuer'}
        for label, role in labels.items():
            with self.subTest(label=label):
                data = labeled().replace(b'FILER:\n', label.encode() + b':\n', 1)
                self.assertEqual([item.role for item in parse(data).submission.roles], [role, 'filer'])
        tags = {'FILED-BY': 'filed-by', 'FILED-FOR': 'filed-for', 'SUBJECT-COMPANY': 'subject-company',
                'REPORTING-OWNER': 'reporting-owner', 'ISSUER': 'issuer'}
        for tag, role in tags.items():
            with self.subTest(tag=tag):
                data = tagged().replace(b'<FILER>\n', f'<{tag}>\n'.encode(), 1).replace(
                    b'</FILER>\n', f'</{tag}>\n'.encode(), 1)
                self.assertEqual([item.role for item in parse(data).submission.roles], [role, 'filer'])

    def test_owner_data_carries_the_reporting_owner_cik(self):
        data = labeled().replace(b'FILER:\n\n\tCOMPANY DATA:', b'REPORTING-OWNER:\n\n\tOWNER DATA:', 1)
        self.assertEqual(parse(data).submission.roles[0].cik, '0000990001')

    def test_required_fields_refuse(self):
        cases = [
            (b'<ACCEPTANCE-DATETIME>20261015163015\n', b'', 2, 'missing required field acceptance-datetime'),
            (b'ACCESSION NUMBER:\t\t0000990001-26-000123', b'ACCESSION NUMBER:\t\t990001-26-123', 4,
             'malformed accession number'),
            (b'FILED AS OF DATE:\t\t20261015', b'FILED AS OF DATE:\t\t20261315', 10, 'malformed filing date'),
            (b'<ACCEPTANCE-DATETIME>20261015163015', b'<ACCEPTANCE-DATETIME>2026101516', 3,
             'malformed acceptance instant'),
            (b'<ACCEPTANCE-DATETIME>20261015163015', b'<ACCEPTANCE-DATETIME>20261017090000', 3,
             'acceptance is later than receipt'),
            (b'CONFORMED SUBMISSION TYPE:\t8-K\n', b'CONFORMED SUBMISSION TYPE:\t8-K\nCONFORMED SUBMISSION TYPE:\t8-K/A\n',
             6, 'duplicate required field submission-type'),
        ]
        for old, new, line, reason in cases:
            with self.subTest(reason=reason), self.assertRaises(EnvelopeRefusal) as caught:
                parse(labeled().replace(old, new, 1))
            self.assertEqual((caught.exception.line, caught.exception.reason), (line, reason))
        with self.assertRaises(EnvelopeRefusal) as caught:
            parse(tagged().replace(b'<ACCEPTANCE-DATETIME>20261015163015\n', b''))
        self.assertEqual(caught.exception.reason, 'missing required field acceptance-datetime')

    def test_unknown_serialization_refuses(self):
        with self.assertRaises(EnvelopeRefusal) as caught:
            parse(b'<HTML>\n')
        self.assertEqual((caught.exception.line, caught.exception.reason), (1, 'snapshot opens with neither serialization'))
        with self.assertRaises(ValueError):
            parse_envelope(labeled(), received_at=datetime(2026, 10, 16))

    def test_malformed_optional_fields_are_gaps(self):
        envelope = parse(labeled().replace(b'CONFORMED PERIOD OF REPORT:\t20261014', b'CONFORMED PERIOD OF REPORT:\t2026'))
        self.assertIn(('malformed-optional-field', 7), [(gap.code, gap.line) for gap in envelope.gaps])

    def test_unclassified_documents_are_gaps(self):
        data = labeled().replace(b'<TYPE>EX-99.2', b'<TYPE>EX-101.CAL')
        self.assertIn('document-unclassified', [gap.code for gap in parse(data).gaps])

    def test_every_field_re_derives_from_the_retained_bytes(self):
        for build in (labeled, tagged):
            with self.subTest(build=build.__name__):
                data = build()
                envelope = parse(data)
                self.assertEqual(rederive_mismatches(data, envelope), ())

    def test_round_trip_detects_changed_values(self):
        data = labeled()
        envelope = parse(data)
        accession = replace(envelope.submission.accession_number, value='0000990001-26-000124')
        changed = replace(envelope, submission=replace(envelope.submission, accession_number=accession))
        self.assertEqual(rederive_mismatches(data, changed), ('accession number is not a parsed header field',))
        moved = replace(envelope.header.fields[0], line=99)
        shifted = replace(envelope, header=replace(envelope.header, fields=(moved,) + envelope.header.fields[1:]))
        self.assertEqual(rederive_mismatches(data, shifted), ('<SEC-DOCUMENT>: line 99 differs from 1',))
        tampered = data.replace(b'Press release.', b'Press-release.')
        self.assertEqual(rederive_mismatches(tampered, envelope), ('document 2: payload hash differs',))

if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run the test command. Expected: `FAILED (errors=1)` with `ModuleNotFoundError: No module named 'sec_edgar_filings.envelope'`.

- [ ] **Step 3: Implement**

Append to `packages/sec-edgar-filings/src/sec_edgar_filings/grammar.py`, after one blank line:

```python
ENVELOPE_PARSER_VERSION = 'sec-envelope-draft-1'
ROLE_KEYS = frozenset({'filer', 'filed-by', 'filed-for', 'subject-company', 'reporting-owner', 'issuer'})
ENTITY_KEYS = frozenset({'company-data', 'owner-data'})
```

`packages/sec-edgar-filings/src/sec_edgar_filings/record.py`:

```python
"""Records of one parsed snapshot: Sigma_y, the header state and the envelope."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from .classify import Document, DocumentClass
from .lines import Field
from .tree import Block, unknown_entries


class Serialization(StrEnum):
    COMPLETE_SUBMISSION = 'complete-submission'  # labeled-line format of the archive .txt file
    FEED_MEMBER = 'feed-member'                  # tagged format of a daily Feed member


@dataclass(frozen=True, slots=True)
class Gap:
    code: str
    line: int | None
    detail: str


@dataclass(frozen=True, slots=True)
class DateValue:
    field: Field
    value: date


@dataclass(frozen=True, slots=True)
class Acceptance:
    field: Field        # the original fourteen-digit Eastern string
    eastern: datetime   # aware, America/New_York
    utc: datetime       # t_acc


@dataclass(frozen=True, slots=True)
class ItemLine:
    field: Field
    item: str | None  # the nu_I mapping; None in Stage 1 (DF4)


@dataclass(frozen=True, slots=True)
class RoleBlock:
    block: Block
    role: str
    cik: str | None  # zero-padded to ten digits


@dataclass(frozen=True, slots=True)
class Submission:
    """Sigma_y: required header fields, items, role blocks and the late-public tag."""
    accession_number: Field
    submission_type: Field
    filing_date: DateValue
    acceptance: Acceptance
    items: tuple[ItemLine, ...]
    roles: tuple[RoleBlock, ...]
    private_to_public: Field | None


@dataclass(frozen=True, slots=True)
class HeaderState:
    """R9 header state: the parsed known header values in canonical order, and its hash."""
    canonical: str
    sha256: str


@dataclass(frozen=True, slots=True)
class Envelope:
    serialization: Serialization
    parser_version: str
    header: Block
    submission: Submission
    documents: tuple[Document, ...]
    header_state: HeaderState
    gaps: tuple[Gap, ...]

    def counts(self) -> dict[str, int]:
        counts = {'documents': len(self.documents), 'role_blocks': len(self.submission.roles),
                  'unknown_entries': unknown_entries(self.header) + sum(
                      1 for document in self.documents for field in document.block.fields
                      if field.key is None),
                  'unmapped_items': sum(1 for item in self.submission.items if item.item is None),
                  'gaps': len(self.gaps)}
        for document_class in DocumentClass:
            counts[f'class:{document_class}'] = sum(
                1 for document in self.documents
                if document.classification.document_class is document_class)
        return counts
```

`packages/sec-edgar-filings/src/sec_edgar_filings/envelope.py`:

```python
"""Envelope(x_y; nu_E, nu_I): the draft P3 parser over the bytes of one snapshot."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from .classify import Document, DocumentClass, classify
from .documents import parse_documents
from .errors import EnvelopeRefusal
from .grammar import (
    ENTITY_KEYS, ENVELOPE_ONLY_KEYS, ENVELOPE_PARSER_VERSION, LABELED_FILE, ROLE_KEYS, TAGGED_FILE,
)
from .header_labeled import lex_labeled
from .header_tagged import lex_tagged
from .lines import Field, LineReader
from .record import (
    Acceptance, DateValue, Envelope, Gap, HeaderState, ItemLine, RoleBlock, Serialization, Submission,
)
from .tree import Block, walk_blocks, walk_fields

EASTERN = ZoneInfo('America/New_York')
ACCESSION = re.compile(r'[0-9]{10}-[0-9]{2}-[0-9]{6}')
CIK = re.compile(r'[0-9]{1,10}')


def parse_envelope(data: bytes, *, received_at: datetime) -> Envelope:
    """Parse one snapshot, or raise EnvelopeRefusal with the first failing line."""
    if received_at.tzinfo is None:
        raise ValueError('received_at must be an aware instant')
    reader = LineReader(data)
    first = reader.peek()
    if first is not None and first.text.startswith(f'<{LABELED_FILE.text}>'.encode()):
        serialization, header = Serialization.COMPLETE_SUBMISSION, lex_labeled(reader)
        closing = f'</{LABELED_FILE.text}>'.encode()
    elif first is not None and first.text == f'<{TAGGED_FILE.text}>'.encode():
        serialization, header = Serialization.FEED_MEMBER, lex_tagged(reader)
        closing = f'</{TAGGED_FILE.text}>'.encode()
    else:
        raise EnvelopeRefusal(1, 'snapshot opens with neither serialization')
    documents = tuple(Document(block, classify(data, block)) for block in parse_documents(reader, closing))
    gaps: list[Gap] = []
    submission = _submission(header, received_at, gaps)
    gaps.extend(Gap('document-unclassified', document.block.line, document.classification.reason)
                for document in documents
                if document.classification.document_class is DocumentClass.UNCLASSIFIED)
    return Envelope(serialization, ENVELOPE_PARSER_VERSION, header, submission, documents,
                    header_state(header), tuple(gaps))


def header_state(header: Block) -> HeaderState:
    """R9: known header values in canonical order, without serialization metadata."""
    canonical = _dump(_canonical(header))
    return HeaderState(canonical, hashlib.sha256(canonical.encode('ascii')).hexdigest())


def parse_date(value: str) -> date | None:
    if re.fullmatch(r'[0-9]{8}', value) is None:
        return None
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except ValueError:
        return None


def parse_acceptance(value: str) -> datetime | None:
    """The Eastern instant of a fourteen-digit acceptance string, or None."""
    if re.fullmatch(r'[0-9]{14}', value) is None:
        return None
    try:
        return datetime.strptime(value, '%Y%m%d%H%M%S').replace(tzinfo=EASTERN)
    except ValueError:
        return None


def rederive_mismatches(data: bytes, envelope: Envelope) -> tuple[str, ...]:
    """Round trip: every parsed field and range re-derives from the retained bytes."""
    problems: list[str] = []
    fields = list(walk_fields(envelope.header))
    fields += [field for document in envelope.documents for field in document.block.fields]
    blocks = list(walk_blocks(envelope.header))
    numbers = _line_numbers(data, [field.start for field in fields] + [block.start for block in blocks])
    for field in fields:
        if data[field.start:field.end] != field.value.encode('ascii'):
            problems.append(f'{field.name} on line {field.line}: value bytes differ')
        if numbers[field.start] != field.line:
            problems.append(f'{field.name}: line {field.line} differs from {numbers[field.start]}')
    for block in blocks:
        line_end = data.find(b'\n', block.start)
        if numbers[block.start] != block.line or block.name.encode() not in data[block.start:line_end]:
            problems.append(f'block {block.name} on line {block.line} does not re-derive')
    for document in envelope.documents:
        problems.extend(_document_mismatches(data, document))
    problems.extend(_submission_mismatches(envelope))
    return tuple(problems)


def _submission(header: Block, received_at: datetime, gaps: list[Gap]) -> Submission:
    top: dict[str, list[Field]] = {}
    for field in header.fields:
        if field.key is not None:
            top.setdefault(field.key, []).append(field)

    def required(key: str) -> Field:
        found = top.get(key, [])
        if not found:
            raise EnvelopeRefusal(header.line, f'missing required field {key}')
        if len(found) > 1:
            raise EnvelopeRefusal(found[1].line, f'duplicate required field {key}')
        if not found[0].value:
            raise EnvelopeRefusal(found[0].line, f'empty required field {key}')
        return found[0]

    accession = required('accession-number')
    if ACCESSION.fullmatch(accession.value) is None:
        raise EnvelopeRefusal(accession.line, 'malformed accession number')
    submission_type = required('submission-type')
    filing = required('filing-date')
    filing_date = parse_date(filing.value)
    if filing_date is None:
        raise EnvelopeRefusal(filing.line, 'malformed filing date')
    accepted = required('acceptance-datetime')
    eastern = parse_acceptance(accepted.value)
    if eastern is None:
        raise EnvelopeRefusal(accepted.line, 'malformed acceptance instant')
    if eastern.astimezone(UTC) > received_at:
        raise EnvelopeRefusal(accepted.line, 'acceptance is later than receipt')
    for field in top.get('public-document-count', ()):
        if not field.value.isdigit():
            gaps.append(Gap('malformed-optional-field', field.line, field.name))
    for key in ('period-of-report', 'date-of-change'):
        for field in top.get(key, ()):
            if parse_date(field.value) is None:
                gaps.append(Gap('malformed-optional-field', field.line, field.name))
    items = tuple(ItemLine(field, None) for field in top.get('item-information', ()))
    gaps.extend(Gap('unmapped-item', item.field.line, item.field.value) for item in items)
    roles = tuple(_role(block, gaps) for block in header.blocks if block.key in ROLE_KEYS)
    private = top.get('private-to-public', [None])[0]
    return Submission(accession, submission_type, DateValue(filing, filing_date),
                      Acceptance(accepted, eastern, eastern.astimezone(UTC)), items, roles, private)


def _role(block: Block, gaps: list[Gap]) -> RoleBlock:
    found = [field for child in block.blocks if child.key in ENTITY_KEYS
             for field in child.fields if field.key == 'cik']
    if len(found) != 1 or CIK.fullmatch(found[0].value) is None:
        reason = 'role-cik-missing' if not found else 'role-cik-malformed'
        gaps.append(Gap(reason, block.line, block.name))
        return RoleBlock(block, block.key, None)
    return RoleBlock(block, block.key, found[0].value.zfill(10))


def _canonical(block: Block) -> list:
    children: list = [[field.key, field.value] for field in block.fields
                      if field.key is not None and field.key not in ENVELOPE_ONLY_KEYS]
    children += [_canonical(child) for child in block.blocks if child.key is not None]
    return [block.key, sorted(children, key=_dump)]


def _dump(value) -> str:
    return json.dumps(value, separators=(',', ':'), ensure_ascii=True)


def _line_numbers(data: bytes, offsets: list[int]) -> dict[int, int]:
    numbers, position, number = {}, 0, 1
    for offset in sorted(set(offsets)):
        number += data.count(b'\n', position, offset)
        numbers[offset], position = number, offset
    return numbers


def _document_mismatches(data: bytes, document: Document) -> list[str]:
    block, content, problems = document.block, document.classification, []
    where = f'document {block.sequence}'
    if hashlib.sha256(data[block.start:block.end]).hexdigest() != block.sha256:
        problems.append(f'{where}: payload hash differs')
    if not (data[:block.start].endswith(b'<TEXT>\n') or data[:block.start].endswith(b'<TEXT>\r\n')):
        problems.append(f'{where}: payload does not start after a <TEXT> line')
    if not data[block.end:].startswith(b'</TEXT>'):
        problems.append(f'{where}: payload does not end at a </TEXT> line')
    if not block.start <= content.content_start <= content.content_end <= block.end:
        problems.append(f'{where}: content range is outside the payload')
    values = {field.key: field.value for field in block.fields if field.key is not None}
    expected = {'type': block.type, 'sequence': str(block.sequence),
                'filename': block.filename, 'description': block.description}
    if any(values.get(key) != value for key, value in expected.items()):
        problems.append(f'{where}: typed metadata differs from its fields')
    return problems


def _submission_mismatches(envelope: Envelope) -> list[str]:
    submission, problems = envelope.submission, []
    parsed = set(walk_fields(envelope.header))
    typed = [('accession number', submission.accession_number), ('submission type', submission.submission_type),
             ('filing date', submission.filing_date.field), ('acceptance', submission.acceptance.field)]
    typed += [('item', item.field) for item in submission.items]
    if submission.private_to_public is not None:
        typed.append(('private-to-public', submission.private_to_public))
    problems.extend(f'{name} is not a parsed header field' for name, field in typed if field not in parsed)
    if parse_date(submission.filing_date.field.value) != submission.filing_date.value:
        problems.append('filing date differs from its field')
    if parse_acceptance(submission.acceptance.field.value) != submission.acceptance.eastern:
        problems.append('acceptance differs from its field')
    for role in submission.roles:
        found = [field.value for child in role.block.blocks if child.key in ENTITY_KEYS
                 for field in child.fields if field.key == 'cik']
        if role.cik is not None and (len(found) != 1 or found[0].zfill(10) != role.cik):
            problems.append(f'role {role.role} on line {role.block.line}: CIK differs from its field')
    return problems
```

- [ ] **Step 4: Run the tests**

Run the test command. Expected: `Ran 50 tests` and `OK`.

- [ ] **Step 5: Commit**

```bash
git add packages/sec-edgar-filings/src/sec_edgar_filings/record.py packages/sec-edgar-filings/src/sec_edgar_filings/envelope.py \
  packages/sec-edgar-filings/src/sec_edgar_filings/grammar.py packages/sec-edgar-filings/tests/support_envelopes.py \
  packages/sec-edgar-filings/tests/test_envelope.py
git commit -m "feat(filings): assemble the envelope with header state and round trip"
```

---

### Task 7: Catalog cross-checks (R8)

**Files:**
- Create: `packages/sec-edgar-filings/src/sec_edgar_filings/crosscheck.py`
- Test: `packages/sec-edgar-filings/tests/test_crosscheck.py`

**Interfaces:**
- Consumes: `record.Envelope`, `record.Gap`, `envelope.ACCESSION`, `envelope.parse_envelope`, `errors.EnvelopeRefusal`.
- Produces: `crosscheck.CatalogSubmission(accession_number: str | None, filing_date: date, form_types: frozenset[str], ciks: frozenset[str])`; `crosscheck.header_form_types(envelope) -> frozenset[str]`; `crosscheck.cross_check(envelope, catalog) -> tuple[Gap, ...]`, which raises `EnvelopeRefusal` on an accession mismatch.

- [ ] **Step 1: Write the failing tests**

`packages/sec-edgar-filings/tests/test_crosscheck.py`:

```python
import unittest
from datetime import date

from sec_edgar_filings.crosscheck import CatalogSubmission, cross_check, header_form_types
from sec_edgar_filings.envelope import parse_envelope
from sec_edgar_filings.errors import EnvelopeRefusal
from support_envelopes import RECEIVED, labeled, tagged

CATALOG = CatalogSubmission('0000990001-26-000123', date(2026, 10, 15), frozenset({'8-K'}),
                            frozenset({'0000990001', '0000990002'}))


def check(data: bytes, catalog: CatalogSubmission = CATALOG):
    return [(gap.code, gap.detail) for gap in cross_check(parse_envelope(data, received_at=RECEIVED), catalog)]


class CrossCheckTests(unittest.TestCase):
    def test_matching_catalog_has_no_gaps(self):
        self.assertEqual(check(labeled()), [])
        self.assertEqual(check(tagged()), [])

    def test_accession_mismatch_refuses(self):
        catalog = CatalogSubmission('0000990001-26-000999', CATALOG.filing_date, CATALOG.form_types, CATALOG.ciks)
        with self.assertRaises(EnvelopeRefusal) as caught:
            check(labeled(), catalog)
        self.assertEqual((caught.exception.line, caught.exception.reason),
                         (4, 'header accession differs from the catalog'))

    def test_path_keyed_catalog_row_takes_the_header_accession(self):
        catalog = CatalogSubmission(None, CATALOG.filing_date, CATALOG.form_types, CATALOG.ciks)
        self.assertEqual(check(labeled(), catalog), [])

    def test_header_disagreements_are_gaps(self):
        catalog = CatalogSubmission(CATALOG.accession_number, date(2026, 10, 14), frozenset({'8-K', '8-K/A'}),
                                    CATALOG.ciks | {'0000990003'})
        data = labeled().replace(b'PUBLIC DOCUMENT COUNT:\t\t9', b'PUBLIC DOCUMENT COUNT:\t\t8')
        self.assertEqual(check(data, catalog), [
            ('filing-date-differs', 'header 2026-10-15, catalog 2026-10-14'),
            ('form-type-not-in-header', '8-K/A'),
            ('catalog-cik-not-in-header', '0000990003'),
            ('document-count-differs', 'declared 8, blocks 9'),
        ])

    def test_a_combined_filing_confirmed_by_the_header_is_not_a_gap(self):
        data = labeled().replace(b'CONFORMED SUBMISSION TYPE:\t8-K', b'CONFORMED SUBMISSION TYPE:\tSC TO-T').replace(
            b'\t\tFORM TYPE:\t\t8-K\n', b'\t\tFORM TYPE:\t\tSC 13E3\n', 1)
        envelope = parse_envelope(data, received_at=RECEIVED)
        self.assertEqual(header_form_types(envelope), frozenset({'SC TO-T', 'SC 13E3', '8-K'}))
        catalog = CatalogSubmission(CATALOG.accession_number, CATALOG.filing_date,
                                    frozenset({'SC TO-T', 'SC 13E3'}), CATALOG.ciks)
        self.assertEqual(check(data, catalog), [])

    def test_catalog_record_validates_its_values(self):
        for args in ((' 990001-26-1', CATALOG.filing_date, CATALOG.form_types, CATALOG.ciks),
                     (None, CATALOG.filing_date, frozenset(), CATALOG.ciks),
                     (None, CATALOG.filing_date, CATALOG.form_types, frozenset({'990001'}))):
            with self.subTest(args=args), self.assertRaises(ValueError):
                CatalogSubmission(*args)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run the test command. Expected: `FAILED (errors=1)` with `ModuleNotFoundError: No module named 'sec_edgar_filings.crosscheck'`.

- [ ] **Step 3: Implement**

`packages/sec-edgar-filings/src/sec_edgar_filings/crosscheck.py`:

```python
"""P3 step 5 cross-checks against the catalog, with R8's form-type set.

The catalog values come in as a plain record: platform runtime code imports no
sec_edgar_ingest module (DF1). envelope.ACCESSION repeats the catalog's accession rule
(packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/contracts.py:82).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .envelope import ACCESSION
from .errors import EnvelopeRefusal
from .record import Envelope, Gap


@dataclass(frozen=True, slots=True)
class CatalogSubmission:
    """The catalog's view of one submission y: a_y (None for a path-keyed row), d_y, f_y and the CIKs of R_y."""
    accession_number: str | None
    filing_date: date
    form_types: frozenset[str]
    ciks: frozenset[str]

    def __post_init__(self):
        if self.accession_number is not None and ACCESSION.fullmatch(self.accession_number) is None:
            raise ValueError('invalid catalog accession number')
        if not self.form_types or not all(self.form_types):
            raise ValueError('catalog form types must be a non-empty set of names')
        if not self.ciks or any(re.fullmatch(r'[0-9]{10}', cik) is None for cik in self.ciks):
            raise ValueError('catalog CIKs must be zero-padded ten-digit identifiers')


def header_form_types(envelope: Envelope) -> frozenset[str]:
    """R8 draft rule: the submission type plus each role block's filing-values form type."""
    forms = {envelope.submission.submission_type.value}
    for role in envelope.submission.roles:
        for child in role.block.blocks:
            if child.key == 'filing-values':
                forms.update(field.value for field in child.fields if field.key == 'form-type' and field.value)
    return frozenset(forms)


def cross_check(envelope: Envelope, catalog: CatalogSubmission) -> tuple[Gap, ...]:
    """Gaps between header and catalog. An accession mismatch refuses the submission."""
    submission = envelope.submission
    if catalog.accession_number is not None and catalog.accession_number != submission.accession_number.value:
        raise EnvelopeRefusal(submission.accession_number.line, 'header accession differs from the catalog')
    gaps = []
    if submission.filing_date.value != catalog.filing_date:
        gaps.append(Gap('filing-date-differs', submission.filing_date.field.line,
                        f'header {submission.filing_date.value}, catalog {catalog.filing_date}'))
    forms = header_form_types(envelope)
    gaps.extend(Gap('form-type-not-in-header', submission.submission_type.line, form)
                for form in sorted(catalog.form_types - forms))
    ciks = {role.cik for role in submission.roles}
    gaps.extend(Gap('catalog-cik-not-in-header', None, cik) for cik in sorted(catalog.ciks - ciks))
    counts = [field for field in envelope.header.fields if field.key == 'public-document-count']
    if len(counts) == 1 and counts[0].value.isdigit() and int(counts[0].value) != len(envelope.documents):
        gaps.append(Gap('document-count-differs', counts[0].line,
                        f'declared {counts[0].value}, blocks {len(envelope.documents)}'))
    return tuple(gaps)
```

- [ ] **Step 4: Run the tests**

Run the test command. Expected: `Ran 56 tests` and `OK`.

- [ ] **Step 5: Commit**

```bash
git add packages/sec-edgar-filings/src/sec_edgar_filings/crosscheck.py packages/sec-edgar-filings/tests/test_crosscheck.py
git commit -m "feat(filings): cross-check the header against the catalog record (R8)"
```

---

### Task 8: Stage exit check and evidence

**Files:**
- Modify: `packages/sec-edgar-filings/README.md`
- Create: `specs/evidence/platform-stage1/stage-exit.md`

**Interfaces:**
- Consumes: every earlier task.
- Produces: the Stage 1 exit record for the plan's Handoff section.

- [ ] **Step 1: Replace the package README**

`packages/sec-edgar-filings/README.md`:

```markdown
# sec-edgar-filings

The SEC filing platform package. It sits above the filing-index catalog in
`packages/sec-edgar-ingest` (see `specs/adr/0001-build-the-filing-platform-as-its-own-workspace-package.md`).

Stage 1 of `specs/sec-filing-platform-roadmap.md` holds one component: the draft
envelope parser (methodology P3). It reads the bytes of one retained submission, in
either serialization, and returns the submission record, the document set, the header
state and the R16 document classes. It sends no request and imports no
`sec_edgar_ingest` module.

The grammar is a draft. `src/sec_edgar_filings/grammar.py` names the source of each
label and tag. Entries marked `assumed` or `methodology` are unconfirmed until Stage 7
fixes the grammar against the retained sample.

Run the tests from the repository root:

    UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never uv run --offline --locked --package sec-edgar-filings \
      python packages/sec-edgar-ingest/tests/network_guard.py discover \
      -s packages/sec-edgar-filings/tests -t packages/sec-edgar-filings/tests
```

- [ ] **Step 2: Run the full suite and the scale check**

Run the test command. Expected: `Ran 56 tests` and `OK`.

Then run this scale check. It is not a committed test:

```bash
UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never uv run --offline --locked --package sec-edgar-filings python - <<'PY'
import sys, time
sys.path.insert(0, 'packages/sec-edgar-filings/tests')
from support_documents import document
from support_envelopes import RECEIVED, labeled
from support_payloads import DOCUMENTS
from sec_edgar_filings.envelope import parse_envelope, rederive_mismatches
big = b''.join(document(10 + i, 'EX-99', b'<p>line of text </TEXT> inside</p>\n' * 400_000) for i in range(20))
data = labeled(DOCUMENTS + big)
start = time.time(); envelope = parse_envelope(data, received_at=RECEIVED)
print(len(data) // 10**6, 'MB', len(envelope.documents), 'documents', round(time.time() - start, 2), 's')
print(rederive_mismatches(data, envelope))
PY
```

Expected: `280 MB 29 documents` in under 5 s (0.27 s at planning), then `()`.

- [ ] **Step 3: Repeat the export diff**

```bash
UV_OFFLINE=1 uv export --frozen --package sec-edgar-ingest --no-dev --no-emit-workspace \
  | cmp - specs/evidence/platform-stage1/ingest-export-before.txt && echo IDENTICAL
git diff --stat main -- packages/sec-edgar-ingest
```

Expected: `IDENTICAL`, and no output from `git diff`, because no ingest file changed.

- [ ] **Step 4: Write the exit record**

Create `specs/evidence/platform-stage1/stage-exit.md`, filling in the values that Steps 2–3 printed:

```markdown
# Platform Stage 1: exit record

- Date: <YYYY-MM-DD>. Branch `platform-stage1` at `<git rev-parse --short HEAD>`.
- Suite: `Ran 56 tests`, `OK`, under `packages/sec-edgar-ingest/tests/network_guard.py`.
- Roadmap Exit:
  - Fixture tests pass for both serializations: `test_envelope`, `test_header_labeled`,
    `test_header_tagged`, `test_crosscheck`.
  - Line-initial closing tags: `test_documents`.
  - Retained unknown tags: `test_documents` (document tag), `test_header_labeled` (label),
    `test_header_tagged` (tag and container), `test_envelope` (counts).
  - Each R16 class: `test_classify`.
  - Import-direction test: `test_boundary`.
  - Ingest export diff: identical at Task 1 and again here (`ingest-export.md`). F1 met. The member
    stays on this branch until the Merge gate (DF6).
  - No SEC request: platform source imports no network module (`test_boundary`), and every run
    used the socket guard. The only network access was `uv lock` to PyPI in Task 1 (DF7).
- Scale: <MB> MB, <n> documents, <s> s, round trip `()`.
- Draft parser version: `sec-envelope-draft-1`. Grammar entries by source: <output of the command below>.
```

Count the grammar entries by source for that record:

```bash
UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never uv run --offline --locked --package sec-edgar-filings python -c \
  "from collections import Counter; from sec_edgar_filings import grammar as g; print(Counter(str(n.source) for n in [*g.LABELED.values(), *g.TAGGED.values(), *g.DOCUMENT_TAGS.values()]))"
```

- [ ] **Step 5: Commit**

```bash
git add packages/sec-edgar-filings/README.md specs/evidence/platform-stage1/stage-exit.md
git commit -m "docs(filings): record the Stage 1 exit evidence"
```

---

## Merge gate (owner, DF6)

Do not merge `platform-stage1` into `main` until all of these hold:

1. The D5 release is built and owner-reviewed (plan 2 D5).
2. The owner has chosen how the catalog's artifact cache follows the new lock. For example, prepare a new cache directory online with `scripts/prepare-native-release.py --prepare-cache-only` and point `SEC_LOCAL_PROOF_CACHE` at it, or replace `releases/artifact-cache` after archiving it. This is an ingest operation outside this plan.
3. After `main` has moved, rebase or merge `main` into the branch, then rerun `uv lock` and Task 1 Steps 2 and 6–8 against `main`'s current lock. The export must still be identical, and the lock diff must still add only the member.
4. With the new artifact cache in place, the owner runs or approves `scripts/check-sec-edgar-ingest.sh` on the merge candidate, and it passes. The planning probe proved only the cache refusal. It did not run the ingest suite against a two-member workspace. The check script, `releases/` and `dist/` belong to the catalog, so this step stays owner-gated.

When items 1–4 hold, and in this order:

1. Run the Plan Completion Protocol on `platform-stage1`. It writes `## Handoff to later stages` (Stages 2, 3, 4, 5, 7, 8 and 9 consume this stage), ticks Stage 1 and retires this plan. Running it after item 3 keeps the Handoff current with the rebased branch.
2. Run finishing-a-development-branch, so the merge carries the protocol's commits.

## Spec coverage

| Roadmap Stage 1 item | Task |
|---|---|
| ADR 0001 row: platform package | 1 |
| ADR 0001 row: import direction and export diff | 1, 8 |
| Draft $\nu_E$ yielding $\Sigma_y$ and $\mathcal{D}_y$, both serializations (R15) | 2, 4, 5, 6 |
| Header state (R9 draft) | 6 |
| R16 classes | 3 |
| R8 P3 cross-check (combined filings) | 7 |
| Line-initial closing tags (R15) | 2 |
| Retained unknown labels and tags (R15) | 2, 4, 5 |
| Required fields as M P3.p2 (R15) | 6 |
| M P3.e Round trip (fixture bytes only) | 6 |
| M P3.e Example files: every role kind, several filers, uuencoded graphic, inline XBRL and traditional instance, missing acceptance (refused), unknown label, unmapped item (DF4), documents with and without description, a path-keyed legacy row | 6, 3, 2, 7 |
| No SEC request | 1, 8 |

Not covered here, by design: the R15 comparison on the V1 sample and "Real files" (Stages 6–7); stored read-back (Stages 5 and 8); $\nu_I$ (Stage 9); every Stage 4 item.
