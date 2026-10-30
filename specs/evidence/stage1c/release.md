# 1c release build and offline verification (Stage 1c, plan 6 Task 5)

## Release
- **Release ID:** `c4de77b89bb1d8ecc5d094f0e1dc6f8a5f3a7935e3595a9dd086d1e41a6b8aa7`
- **Manifest:** `/Users/lowell/Projects/sec-edgar-local/releases/sha256=c4de77b89bb1d8ecc5d094f0e1dc6f8a5f3a7935e3595a9dd086d1e41a6b8aa7/release.json`
- **`git_revision`:** `3af121a468fdd6b3ec7d8286d5cf619493992d49` (`main`, after the Task 4 merge). The tree was clean before the build (`git status --porcelain --untracked-files=all` printed nothing).
- **Build:** `scripts/prepare-native-release.py --offline` from the main checkout, on 2026-10-30. It printed the one release path above and exited 0.
- **Application wheel SHA-256:** `52716b7afadfb64ee7efb486368420f041093d9c22e986d58df2ef22fb0cd45c`. Package version `0.2.0`. The 1b wheel was `f5dcef7e…`. The wheel differs because `workflows/completion.py` and `workflows/processing.py` changed.

## Locked inputs (M7)
The 1b release is `9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b`. Its build revision is `50423a404fb50a959b3ca4077301117d32804cc6`.

| Check | Result |
|---|---|
| `cmp` of `uv.lock` in the 1c release and in the 1b release | `lock-identical`. SHA-256 `e3d3dac9971ed75bdc5864ebd8c422c2e34bd24236a9a77bbadb6a87cddf1bbb`. |
| `runtime-requirements.txt` (the `uv export --package sec-edgar-ingest --no-dev --no-emit-workspace` output), without comment lines | `export-lines-identical`. Both files give SHA-256 `def62c21599d615c1945f47a984f6e7e053eeed63130422f8db65ed5a81fcb76`. See the note below. |
| `git diff --exit-code 50423a404fb50a959b3ca4077301117d32804cc6 HEAD -- uv.lock pyproject.toml packages/sec-edgar-ingest/pyproject.toml` | `inputs-identical`. The diff is empty. |
| Package version | `0.2.0` in both releases. |
| `git_revision` in the 1c manifest | `3af121a468fdd6b3ec7d8286d5cf619493992d49`. It equals `HEAD` of the clean tree. |
| Dependencies | `certifi`, `charset-normalizer`, `idna`, `pyarrow`, `requests`, `urllib3`. The same six as the 1b release. No platform package. |

> Note: line 2 of `runtime-requirements.txt` is a comment. It records the random temporary directory that `uv export` used. So the check compares the requirement lines only, as plan 4 and plan 5 did.

## Offline verification
> Note: the harness guard refuses any path inside a checkout, and the verifier children inherit the working directory. So the harness and the evidence directory were created under a temporary directory outside the checkout (`/var/folders/3m/6f8zc0l14dn8yz2x8yy2_3mw0000gn/T/tmp.7ugkkKEcba`). The verifier ran with that directory as its working directory. This is the same method as the 1b release evidence.

The verifier ran on the 1c interpreter (`-I -B -X pycache_prefix=/dev/null`) with `UV_OFFLINE=1` for the harness step. Its output is below. The `evidence` path in it is the temporary directory. The evidence was then copied to the durable evidence directory given below.

```json
{"exit": 0, "release_id": "c4de77b89bb1d8ecc5d094f0e1dc6f8a5f3a7935e3595a9dd086d1e41a6b8aa7", "evidence": "/var/folders/3m/6f8zc0l14dn8yz2x8yy2_3mw0000gn/T/tmp.7ugkkKEcba/evidence"}
```

`preflight_current` on the 1c interpreter printed `c4de77b89bb1d8ecc5d094f0e1dc6f8a5f3a7935e3595a9dd086d1e41a6b8aa7`.

**Evidence directory:** `/Users/lowell/Projects/sec-edgar-local/fixture-data/s1c-verify-evidence/` (git-ignored, because the temporary directory is not durable). `report.json` has SHA-256 `9a66c49241d904610e55dd74d5793bd21dd7cebf199f7c0d3c009aa79bcef139`. `command.json` has `5132bdcd1434076e5131d0538c26ebdb57bc4cad4a5289672a8c4c7c24dc58cb`.

**Retained releases.** `releases/` holds these release directories:
- `sha256=49b7a2ed…`
- `sha256=900952a8…`
- `sha256=d718ae5f…`
- `sha256=fc68adef…`
- `sha256=aa8de1ac…` (D5)
- `sha256=9fa189a0…` (1b)
- `sha256=c4de77b8…` (1c, new)

`releases/` also holds `artifact-cache` and `task14-guard-proofs`. The 1b release, the D5 release, `fc68adef…` and the older releases are all kept. No existing release directory changed.

## Network
No SEC request was sent. Verification used fixture acquisition only.
