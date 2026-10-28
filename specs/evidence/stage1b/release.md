# 1b release build and offline verification (Stage 1b, plan 5 Task 11)

## 1. Release
- **Release ID:** `9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b`
- **Manifest:** `/Users/lowell/Projects/sec-edgar-local/releases/sha256=9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b/release.json`
- **`git_revision`:** `50423a404fb50a959b3ca4077301117d32804cc6` (`main`, after the Task 10 merge). The tree was clean before the build (`git status --porcelain --untracked-files=all` printed nothing).
- **Build:** `scripts/prepare-native-release.py --offline` from the main checkout, on 2026-10-28. It printed the one release path above and exited 0.
- **Application wheel SHA-256:** `f5dcef7e0b54a85052921864be6efe3cea3ec9549577b7f55f7488cb5b1d3cd8`. Package version `0.2.0`.

## 2. Identity against the D5 release (C9)
The D5 release is `aa8de1ac09fa8ef1a8f638301b25c370af5222e9ef0b02fd117866c2260a6ab4`. Its build revision is `d68787fe8602e9d81a26d2012feec9bfad5c52df`.

| Check | Result |
|---|---|
| `cmp` of `uv.lock` in the 1b release and in the D5 release | `lock-identical`. SHA-256 `e3d3dac9971ed75bdc5864ebd8c422c2e34bd24236a9a77bbadb6a87cddf1bbb`. |
| `runtime-requirements.txt` (the `uv export --package sec-edgar-ingest --no-dev --no-emit-workspace` output), without comment lines | `export-lines-identical`. Both files give SHA-256 `def62c21599d615c1945f47a984f6e7e053eeed63130422f8db65ed5a81fcb76`. See the note below. |
| `git diff --exit-code d68787fe8602e9d81a26d2012feec9bfad5c52df HEAD -- uv.lock pyproject.toml packages/sec-edgar-ingest/pyproject.toml` | `inputs-identical`. The diff is empty. |
| Package version | `0.2.0`. |
| Dependencies | `certifi`, `charset-normalizer`, `idna`, `pyarrow`, `requests`, `urllib3`. The same six as the D5 release. No platform package. |

The manifest `git_revision` differs from D5 (`50423a40…` against `d68787fe…`), because the code changed.

> Note: line 2 of `runtime-requirements.txt` is a comment. It records the random temporary directory that `uv export` used. So the check compares the requirement lines only, as plan 4 did.

## 3. Offline verification and retention
> Note: the harness guard refuses any path inside a checkout, and the verifier children inherit the working directory. So the harness and the evidence directory were created under a temporary directory outside the checkout (`/var/folders/3m/6f8zc0l14dn8yz2x8yy2_3mw0000gn/T/tmp.OOWRlKQYRr`). The verifier ran with that directory as its working directory. This is the same method as the D5 release evidence.

The verifier ran on the 1b interpreter (`-I -B -X pycache_prefix=/dev/null`). Its output:

```json
{"exit": 0, "release_id": "9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b", "evidence": "/var/folders/3m/6f8zc0l14dn8yz2x8yy2_3mw0000gn/T/tmp.OOWRlKQYRr/evidence"}
```

`preflight_current` on the 1b interpreter printed `9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b`.

**Evidence directory:** `/Users/lowell/Projects/sec-edgar-local/fixture-data/s1b-verify-evidence/` (git-ignored, because the temporary directory is not durable). `report.json` has SHA-256 `0a7faa320b6f72dd049c0d081416d14a5eb2436abd08fd60d0f4330e6d54c33e`. `command.json` has `18c625410558f6c8c3b9ed6f462c39846d3ee49f55052bd350b00a199bdd0dc6`.

**Retained releases.** `releases/` holds these release directories:
- `sha256=49b7a2ed…`
- `sha256=900952a8…`
- `sha256=d718ae5f…`
- `sha256=fc68adef…`
- `sha256=aa8de1ac…` (D5)
- `sha256=9fa189a0…` (1b, new)

The D5 release, `fc68adef…` and the older releases are all kept. No existing release directory changed.

## 4. Network
No SEC request was sent. Verification used fixture acquisition only.
