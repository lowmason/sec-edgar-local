# D5 release build and offline verification (Stage 1a, plan 4 Task 9)

## 1. Release
- **Release ID:** `aa8de1ac09fa8ef1a8f638301b25c370af5222e9ef0b02fd117866c2260a6ab4`
- **Manifest:** `/Users/lowell/Projects/sec-edgar-local/releases/sha256=aa8de1ac09fa8ef1a8f638301b25c370af5222e9ef0b02fd117866c2260a6ab4/release.json`
- **`git_revision`:** `d68787fe8602e9d81a26d2012feec9bfad5c52df` (`main`, after the Task 8 fast-forward merge of `stage1a-bounded-drain`). The tree was clean before the build (`git status --porcelain --untracked-files=all` printed nothing).
- **Build:** `scripts/prepare-native-release.py --offline` from the main checkout, on 2026-10-27. It printed the release path and exited 0.
- **Application wheel SHA-256:** `5d544087e363e4e6b4470ea5e6f7a40a127e1ca831514fef3ebfa1b458d93b4b`. Package version `0.2.0`.

## 2. Identity against `fc68adef…` (B7)
| Check | Result |
|---|---|
| `uv.lock` in the release against `fc68adef…` | `cmp` identical. SHA-256 `e3d3dac9971ed75bdc5864ebd8c422c2e34bd24236a9a77bbadb6a87cddf1bbb` in both manifests. |
| `runtime-requirements.txt` (the `uv export --package sec-edgar-ingest --no-dev --no-emit-workspace` output) | The requirement lines are identical: both files give SHA-256 `def62c21599d615c1945f47a984f6e7e053eeed63130422f8db65ed5a81fcb76` without comment lines. See the deviation below. |
| `git diff --exit-code 3ca50c7 HEAD -- uv.lock pyproject.toml packages/sec-edgar-ingest/pyproject.toml` | Empty. |
| Package version | `0.2.0` in both. |
| Dependencies | `certifi`, `charset-normalizer`, `idna`, `pyarrow`, `requests`, `urllib3`. The same six as `fc68adef…`. No platform package. |
| Manifest identity fields | `application`, `dependencies`, `interpreter` and `uv_lock_sha256` equal. `git_revision` (`d68787f…` against `3ca50c7…`), `package_files` and `application_wheel_sha256` differ, because the code changed. |

> Deviation: `cmp` on `runtime-requirements.txt` fails at line 2. That line is a comment that records the random temporary directory that `uv export` wrote to (`sec-native-setup-<random>`). Every non-comment line is identical. The plan's "export-identical" check is therefore stated on the requirement lines.

## 3. Offline verification and retention
> Deviation: the plan puts the verifier harness under `fixture-data/` and runs the verifier from the checkout. The harness guard refuses any path inside a checkout (`installed proof refuses checkout access`), and the child processes inherit the current directory. So the harness and the evidence directory are under a temporary directory outside the checkout, and the verifier ran with that directory as its working directory (as `docs/runbooks/native-setup.md` and the local-port spec describe). Two earlier attempts failed on exactly that guard and created no release and no evidence.

The verifier ran on the D5 interpreter (`-I -B -X pycache_prefix=/dev/null`) with `--harness` and `--evidence` outside the checkout. Its output:

```json
{"exit": 0, "release_id": "aa8de1ac09fa8ef1a8f638301b25c370af5222e9ef0b02fd117866c2260a6ab4", "evidence": "/var/folders/3m/6f8zc0l14dn8yz2x8yy2_3mw0000gn/T/d5-proof.P1PiJc/evidence"}
```

The evidence was copied to `/Users/lowell/Projects/sec-edgar-local/fixture-data/d5-verify-evidence/` (git-ignored, because the temporary directory is not durable). `report.json` has SHA-256 `6bd617b140d646dc968acd6f591e28c0b4f6f9b81fbb111a021efb21fbf285be` and `command.json` has `c6956ad3d468d3b2c1d9fd3c15b492b8414bb4709cc8e480d645764767a3ecb4`.

`preflight_current` on the D5 interpreter printed `aa8de1ac09fa8ef1a8f638301b25c370af5222e9ef0b02fd117866c2260a6ab4`.

`releases/` holds `sha256=49b7a2ed…`, `sha256=900952a8…`, `sha256=d718ae5f…`, `sha256=fc68adef…` and `sha256=aa8de1ac…`. `fc68adef…` and the older releases are kept.

## 4. Network
No SEC request was sent in Tasks 2–9. Measurement and verification used fixture acquisition only.
