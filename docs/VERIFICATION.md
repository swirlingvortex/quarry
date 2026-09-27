# Verification evidence — final M0–M9 acceptance

Verdict **CORE_VERIFIED_LOCAL**. The required local implementation, clean
installation and internal study passed. Final source fingerprint:
`993bef547cee6f56657330eafcd606b4c8d535760e9e97e04bd4242e4bc1b553`. Final Release binary:
`4bb67a95d79b66d09811158e0cce9d3a4411b21dc5e32bc43687f9b2e0ede9ad`.
All earlier progress records below are historical and superseded by this section.

| Final command/check | Observed result | Exact evidence |
| --- | --- | --- |
| `.venv/bin/python tools/verify.py --profile core` | Exit 0; all 13 steps; unchanged source | `build/verification/20260920T064356.232524Z-core/summary.json`, `evidence/m9-final-gate-v2.json` |
| Debug, Release, ASan/UBSan | Each: 1,378 Python tests; 39 native cases / 5,438 assertions; 512 SQL + 512 CSV mutations | Gate step logs, JUnit files and `native-{debug,release,sanitize}.log` |
| Distinct generated corpus | 1,008 identities, 20,160 comparisons/build, 60,480 across three builds | `cases.jsonl`, per-build `cases-*-executed.jsonl`; manifests/receipts checked exactly |
| Hypothesis | Two properties, 40 observed passing examples each/build | Python step logs; separate from pytest case counts |
| `.venv/bin/python tools/clean_check.py --output build/m9-clean-final-v2` | Exit 0; all 13 steps; original/copied source unchanged; 128 copied files | `build/m9-clean-final-v2/summary.json`, `evidence/m9-clean-check-v2.json` |
| 10k and 100k final studies | Exit 0 each; 224 complete validations, 448 warmups, 1,568 recorded trials | `reports/benchmarks/final-10000/`, `reports/benchmarks/final-100000/`, `evidence/m8-final-study.json` |
| Report generation and independent regeneration | Both exit 0; Markdown and JSON byte-identical | `evidence/m8-report-generation.log`, `evidence/m8-report-regeneration.log`, `evidence/m8-final-study.json` |

No final required local gate failed or skipped. Unsupported: macOS
LeakSanitizer (`detect_leaks=0`); ASan and UBSan passed. Not run: hosted Linux/macOS
CI, the separately bounded 2,016-case extended profile, million-row inputs and
external-engine performance comparison. These exclusions are not passes.

Final benchmark commands (both executed sequentially with exit 0):

```sh
.venv/bin/python tools/benchmark.py --manifest data/benchmarks/10000/manifest.json \
  --output reports/benchmarks/final-10000 --measure \
  --verification build/verification/20260920T064356.232524Z-core/summary.json
.venv/bin/python tools/benchmark.py --manifest data/benchmarks/100000/manifest.json \
  --output reports/benchmarks/final-100000 --measure \
  --verification build/verification/20260920T064356.232524Z-core/summary.json
.venv/bin/python tools/benchmark_report.py \
  --runs reports/benchmarks/final-10000 reports/benchmarks/final-100000 \
  --output docs/BENCHMARKS.md --json-output evidence/m8-report.json
```

Measurement output directories must be new when repeating the study. Regenerating
the report from the retained final directories is safe and needs no new timings.
All input/query/options/build/dependency/source/binary hashes, seeded order,
full validation results, raw measurements, exit codes, stderr and artifact
hashes are retained per run. The report includes all 240 comparisons: 115 faster,
30 slower, 95 overlapping-IQR observations; IQR overlap is not a significance test.
No source, flags, data or query changes occurred during final measurements.

The clean check observed pinned local bootstrap, fresh native builds, installation,
minimal-PATH native core build/demo, installed library consumer, installed
CLI demo/EXPLAIN, and `otool -L` showing libc++ and libSystem only. The native core
and CLI do not require Python/DuckDB runtime execution. Python remains a tooling
and independent correctness-oracle dependency. No Linux runtime result is inferred.

The first M9 gate/studies under fingerprint `9d334b2f...` passed and remain
preserved. A final Darwin process-inventory truncation finding changed tooling
only; platform regressions/live sentinel passed, then full gates, clean copy and
both study profiles were repeated. Earlier raw directories `reports/benchmarks/10000`
and `reports/benchmarks/100000` were not deleted or selected by performance.
See `evidence/m9-process-guard.json` and [FINAL_AUDIT.md](FINAL_AUDIT.md).

---

## Historical M0–M3 acceptance

M0–M3 was accepted locally on 2026-09-19 (2026-09-20 UTC). The environment,
fingerprint and gate records below describe that earlier baseline only.

## Environment and source

- macOS 15.7.1 / Darwin 24.6.0, arm64, Apple M1 Pro, 8 logical CPUs, 16 GiB RAM.
- Apple Clang 17.0.0, Python 3.12.12, repository-local CMake 3.31.6.
- doctest 2.4.11 and nlohmann/json 3.11.3 headers are version/SHA256 pinned in
  `dependencies.lock.json`; pytest 8.3.5, Hypothesis 6.131.9, DuckDB 1.2.2 and
  all Python dependencies are pinned in `requirements-dev.lock`.
- Bootstrap: `python3.12 tools/bootstrap.py`, exit 0, `evidence/bootstrap.log`.
  CMake was absent initially; no global package installation or sudo was used.
  Ordinary configure/build/test commands fetch no dependencies.
- Initial directory was empty with no applicable AGENTS.md or Git history.
  Git was initialized locally. All project files remain uncommitted/untracked;
  there is no configured remote, publication, tag, push, or sibling-repo work.
- Historical M3 source fingerprint: `6f131209dda193afe76111c864ad74cfa05ad0ec3c31f4d03473f1d5a09a36d0`.
  Algorithm: canonical sorted relative-path/content-SHA256 JSON, hashed with
  SHA256. `tools/verify.py` includes source, headers, tests, tools, fixtures,
  CMake files, pytest configuration, and dependency locks; excludes docs,
  evidence, generated build files, caches and virtual environments.

The final core and Release runs both confirmed this fingerprint unchanged.
Full file hashes are preserved in `evidence/m3-core-summary.json` and
`evidence/release-summary.json`. Machine/bootstrap detail is also preserved in
`evidence/foundations.json`. Early M0 metadata is explicitly superseded; the
final stable-tree evidence is authoritative.

## Authorized milestone gates

| Milestone | Observed gate |
| --- | --- |
| M0 | Pinned local bootstrap, actual compiled C++ test, CLI help, Debug build; roadmap/contracts saved |
| M1 | Typed/nullable column buffers, CSV grammar and diagnostics, strict input, bounds, transactional-load cleanup, owned lifetimes; empty/one/4099-row tests |
| M2 | SQL text through tokenization, binding, typed plans and scalar scan/filter/project; type/precedence/name/errors/truth tables; DuckDB harness |
| M3 | Global/grouped aggregation, sort/LIMIT, recoverable session, deterministic demo; 240 generated comparisons; review fixes and supported sanitizers |

## Final core profile

Command: `.venv/bin/python tools/verify.py --profile core`, exit **0**.
Raw summary: `build/verification/20260920T020725.155418Z-core/summary.json`;
compact preserved copy: `evidence/m3-core-summary.json`.

- Debug native: **25 doctest test cases passed**, registered as one CTest test
  executable. The CTest count is not the number of C++ cases or assertions.
- Debug Python: **359 pytest test cases passed**, comprising **240 explicit
  deterministic query/data cases** (10 datasets × 24 query families), 11
  comparator tests, 2 Hypothesis properties, and 106 integration/regressions.
  Each property is configured for at most 40 examples; that maximum is not
  represented as an independently observed pytest case count.
- ASan/UBSan: the same 25 native cases and **106 CLI/integration/regression
  cases passed**. These are configuration reruns, not additional unique tests.
- DuckDB 1.2.2 uses one thread, explicit schemas and inserted logical values.
  Schema, nullness, multiplicity and ordering/ties are compared, with bounded
  DOUBLE tolerance documented in SQL_SUBSET.md. Hand-computed and Decimal
  stress cases are separate from the generated oracle gate.
- Demo passed and produced five region groups. No skipped tests in the passing
  pytest runs; LeakSanitizer is a separately documented unavailable capability.

| Command | Exit | Log |
| --- | --- | --- |
| `/Users/goktugbas/Major_Projects/quarry/.venv/bin/cmake --preset debug` | 0 | `build/verification/20260920T020725.155418Z-core/01-debug-configure.log` |
| `/Users/goktugbas/Major_Projects/quarry/.venv/bin/cmake --build --preset debug` | 0 | `build/verification/20260920T020725.155418Z-core/02-debug-build.log` |
| `/Users/goktugbas/Major_Projects/quarry/.venv/bin/ctest --preset debug` | 0 | `build/verification/20260920T020725.155418Z-core/03-debug-ctest.log` |
| `/Users/goktugbas/Major_Projects/quarry/.venv/bin/python -m pytest -q -ra tests/integration tests/differential tests/regressions --junitxml=/Users/goktugbas/Major_Projects/quarry/build/verification/20260920T020725.155418Z-core/pytest.xml` | 0 | `build/verification/20260920T020725.155418Z-core/04-python-verification.log` |
| `/Users/goktugbas/Major_Projects/quarry/build/debug/quarry demo` | 0 | `build/verification/20260920T020725.155418Z-core/05-demo.log` |
| `/Users/goktugbas/Major_Projects/quarry/.venv/bin/cmake --preset sanitize` | 0 | `build/verification/20260920T020725.155418Z-core/06-sanitize-configure.log` |
| `/Users/goktugbas/Major_Projects/quarry/.venv/bin/cmake --build --preset sanitize` | 0 | `build/verification/20260920T020725.155418Z-core/07-sanitize-build.log` |
| `/Users/goktugbas/Major_Projects/quarry/.venv/bin/ctest --preset sanitize` | 0 | `build/verification/20260920T020725.155418Z-core/08-sanitize-ctest.log` |
| `/Users/goktugbas/Major_Projects/quarry/.venv/bin/python -m pytest -q -ra tests/integration tests/regressions --junitxml=/Users/goktugbas/Major_Projects/quarry/build/verification/20260920T020725.155418Z-core/pytest-sanitize.xml` | 0 | `build/verification/20260920T020725.155418Z-core/09-sanitize-python.log` |

The sanitized CLI invocation uses `QUARRY_BINARY=build/sanitize/quarry`,
`ASAN_OPTIONS=detect_leaks=0`, and
`UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1`; exact absolute paths and
environment overrides are in the JSON summary.

## Release, reproducibility, and standalone runtime

Release was configured into a previously absent build directory, built and
passed 25 native cases plus 106 CLI/integration/regression cases. Source stayed
unchanged. Evidence: `evidence/release-summary.json`.

| Command | Exit | Log |
| --- | --- | --- |
| `.venv/bin/cmake --preset release` | 0 | `evidence/release-configure.log` |
| `.venv/bin/cmake --build --preset release` | 0 | `evidence/release-build.log` |
| `.venv/bin/ctest --preset release` | 0 | `evidence/release-ctest.log` |
| `.venv/bin/python -m pytest -q tests/integration tests/regressions --junitxml=build/release/pytest-cli.xml` | 0 | `evidence/release-cli-tests.log` |
| `build/release/quarry demo` | 0 | `evidence/standalone-demo.log` |
| `otool -L build/release/quarry` | 0 | `evidence/runtime-libraries.log` |

The standalone demo ran with only `PATH=/usr/bin:/bin` and `LC_ALL=C` in its
environment. `otool -L` reports only libc++ and libSystem dependencies: the
compiled CLI links neither Python nor DuckDB. Python remains necessary for the
external differential harness, not for native query execution.

The generator reproduced catalog, CSV, SQL and fixture manifest byte-for-byte:
`evidence/fixture-reproducibility.json`. Seed 19092026, generator `retail-v1`,
96 retail rows; canonical hashes are in `examples/fixture.json`.

Binary SHA256 values:

- debug: `f7a50a75c0d7bc04d396b27f222c21b46927df4b9aebc699affb43d4951547b4`
- sanitize: `dfb7661e4fb25346d402c1144a098335cd1ab8c23182e5b17d77160a853df601`
- release: `32ff1c666784785e57b5c73ab4615bf37121047288d553ebe65e2b4f9f2e1f15`

## Review fixes and limitations

Independent review and tests exposed numeric sign parsing, PMR exception safety,
NULL inference, deep JSON nesting, request-id recovery, WHERE comparison shape,
and the initial executor/EXPLAIN wiring gap. They were corrected, retained as
regressions or exact reproduction evidence, and the final gates were rerun.
See FINAL_AUDIT.md and `evidence/review-*` for review details.

The first sanitizer run exited 8 before tests because this macOS runtime rejects
`detect_leaks=1` with `AddressSanitizer: detect_leaks is not supported on this
platform`. Its summary is retained under
`build/verification/20260920T020434.997557Z-core/summary.json`. LeakSanitizer was
explicitly disabled for the supported ASan/UBSan rerun. Accounted-allocation
cleanup tests do not establish whole-process leak freedom.

Linux, remote CI, full extended/smoke profile orchestration, and full
DuckDB-generated suites under Release/sanitizers were not run. No performance,
vector, join, optimizer, SIMD, or production-readiness claim is made. Engine
accounting excludes documented metadata/runtime/JSON overhead and is not an RSS
cap; optional process peak RSS is separately labeled in result statistics.

## M4–M6 baseline refresh

Before execution edits: `.venv/bin/python tools/verify.py --profile smoke`, exit 0; all five steps passed, source unchanged at M3 fingerprint above. Raw summary `build/verification/20260920T042430.801551Z-smoke/summary.json`, orchestration log `evidence/m4-baseline-smoke.log`. This proves the starting state, not the later milestones.

## M4 targeted gate

Passed Debug build and native CTest (29 cases), logs `evidence/m4-fixed-{build,native}.log`. Full Python rerun `.venv/bin/python -m pytest -q --hypothesis-show-statistics`, exit0:410 cases; log `evidence/m4-final-python.log`. 240 generated cases each compare scalar plus five vector sizes1/7/256/1024/4096 to DuckDB; two Hypothesis properties each observed40 passing examples.49 focused batch/cap/fault cases also passed. Source unchanged at `341e20e74d323a635d854c7467ef035826a500fc73a7c60c2f8e343518a33e2b`; details `evidence/m4-gate.json`. Initial cap/fault category mismatch was reproduced, fixed and retained in regressions; final targeted gate has no failures. Release/sanitizer gates remain scheduled after M6.

## M5 targeted gate

`.venv/bin/python -m pytest -q --hypothesis-show-statistics` passed509 cases before the final swap guard (`evidence/m5-python.log`). After the guard: `.venv/bin/cmake --build --preset debug` and `.venv/bin/ctest --preset debug` exited 0,32 native cases; `.venv/bin/python -m pytest -q tests/differential/test_joins.py` passed109 affected cases in11.24s, exit0. Logs `evidence/m5-guard-{build,native,python}.log`. Source snapshot `evidence/m5-fingerprint.json`: `7bcdecbb148af86cfc6888ba9f2d68570ed57e4a278f00761ed21fe7e961bf14`; dormant M6 draft tests were excluded. Independent review16 checks passed (`evidence/review-m5-multiplicity.json`). Exact commands in the logs govern if path spelling differs. Full final suites remain pending M6.

## M6 targeted gate before final acceptance

First optimizer CLI tests passed 56 cases (`evidence/m6-optimizer-first.log`, exit0).
First full Debug diagnostic suite passed 575 cases in 132.77s, including 312 generated
cases under 20 configurations and 80 observed Hypothesis examples
(`evidence/m6-python-first.log`, exit0). Source-only review edits occurred during
that diagnostic binary run; it is not the final source-frozen acceptance.

Follow-up made scalar and join reads consume the compact typed views, extended
allocation/timing scopes, and added two native optimizer lifetime/recovery cases.
`.venv/bin/cmake --build --preset debug` and `.venv/bin/ctest --preset debug`
then exited 0 with34 native cases (`evidence/m6-view-build.log`,
`evidence/m6-view-native.log`). Final full core orchestration is in progress.

## Final M4–M6 acceptance — 2026-09-20

Command: `.venv/bin/python tools/verify.py --profile core`, exit **0**.
All **13/13** configure/build/native/Python/demo steps passed; no step was skipped.
Orchestration log: `evidence/m6-final-core.log`. Authoritative exact subcommands,
environment overrides, exit codes and per-step logs:
[`summary.json`](../build/verification/20260920T050834.169605Z-core/summary.json).
Consolidated counts and native/Hypothesis evidence: `evidence/m6-final-gate.json`.

| Build | Native cases / assertions | Python tests | Observed Hypothesis examples |
| --- | --- | --- | --- |
| Debug | 34 / 4,500 passed | 575 passed | 40 + 40 passing |
| Release | 34 / 4,500 passed | 575 passed | 40 + 40 passing |
| ASan + UBSan | 34 / 4,500 passed | 575 passed | 40 + 40 passing |

Every build ran all applicable integration, differential and regression suites.
The 312 generated query/data cases (240 single-table, 72 joined) each covered 20
configurations: scalar and vector sizes 1, 7, 256, 1024, 4096 with all rules off/on,
plus each rule alone under scalar and vector 7. Tests also check typed comparison
semantics, independent nested-loop join expectations, empty/partial batches,
NULLs, duplicate multiplicity, faults/caps, string ownership and session recovery.
The observed Python durations were 136.75s Debug, 75.71s Release and 692.97s
sanitized; these are verification durations, not query performance measurements.

Source before and after was identical:
`78bc4040abf09ca0563499b3b25a06998eeb8767489268d209dcfda51bdbb7d4`.
The fingerprint covers implementation, tests, tools, fixtures, build configuration
and dependency locks; documentation/evidence are excluded so acceptance records
can be written after testing. Final executable SHA256 values:

- debug: `6bd9f1ea9ee50832c69fbf5d4b96c2b0ad328c0812bb8aa416e71528b8bff423`
- release: `b065d8d4089c8184e2947b1b2a03c1d92807075047c58aa056fc7febf451c715`
- sanitize: `3abad31faaccc035006747514e6743338603407b52416b181c8f998d171a8e21`

Independent review additionally passed 180 exact result comparisons and 86
error-domain/cap/swap checks (`evidence/review-m6-optimizer.json`). Actual join
hash memory-budget failures and subsequent same-session recovery passed 12
configurations in each build (36 checks total), with restored current allocation
counts (`evidence/m6-join-memory-recovery.json`). Historical discovered faults and
fixes are detailed in FINAL_AUDIT.md; no known unresolved scoped failure remains.

Joined demo, optimized vector query and EXPLAIN ANALYZE commands all exited 0
and returned matching five-group results (`evidence/m6-handoff.json`). The
Release demo also ran with only PATH and LC_ALL set, and `otool -L` showed only
libc++ and libSystem (`evidence/m6-standalone.json`). README query, explain and
session examples were independently executed (`evidence/review-doc-commands.json`).

LeakSanitizer remains **unsupported and not passed** on this macOS runtime.
The successful sanitizer checks use `ASAN_OPTIONS=detect_leaks=0` and
`UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1`. No Linux/remote-CI result,
whole-process leak-freedom claim, extended-profile gate or performance result
is claimed. M7–M9 and extensions remain outside this authorization. Changes are
local and uncommitted; no remote, push, tag or publication was created.

Next action: stop at M6. A later authorized GOAL 3 must re-read the checkpoint
and verify the M0–M6 foundation before starting M7–M9.


## M7–M9 baseline and initial tested increment

Baseline command `.venv/bin/python tools/verify.py --profile smoke` exited0,
all five steps passed; `evidence/m7-baseline-smoke.log` and
`build/verification/20260920T055529.700797Z-smoke/summary.json` preserve the
unchanged M0–M6 source result before execution edits.

Native prepared-state/ownership and PMR failure-prefix tests pass:39 cases,
5,438 assertions. Deterministic mutation fuzz target passes512 parser and512 CSV
mutations with seed1909202607. Commands `.venv/bin/cmake --build --preset debug`
and `.venv/bin/ctest --preset debug` exited0 (`evidence/m7-install-build.log`,
`evidence/m7-prepared-native.log`). Latest working fingerprint and binary hash
are in `evidence/m7-progress.json`, explicitly not a source-frozen full gate.

The first expanded Python run observed1,134 passing tests and3 string-order
failures. Reproducers were preserved under `build/verification/failures/seed-33-*`.
A minimized independent experiment identified the pinned DuckDB optimizer as
the source; exact raw/guarded observations are in
`evidence/m7-duckdb-utf8-order.json`. Follow-up uses identical SQL with only
compressed_materialization disabled, retains full comparator assertions and
records the oracle setting. No expanded rerun or final gate is claimed yet.

Native benchmark validation (no measurement) returned112 full result records
for the56-case smoke manifest, exit0, in `evidence/m8-native-validation-fixed.jsonl`.
The earlier rejected joined benchmark ORDER BY syntax remains recorded in
`evidence/m8-native-validation.jsonl`; query definitions were amended and
refrozen before any measurement. Python independent result validation and
reports remain pending.

## M7 guarded targeted gate and M8 validation

The minimized pinned-oracle correction passed the repeated expanded Debug gate:
1,139 Python tests, all 1,008 distinct content identities and 20 configurations
each (20,160 comparisons). Command, binary hash and receipts are preserved in
`evidence/m7-python-targeted-gate.json`; log `evidence/m7-python-guarded.log`.
No tolerance or SQL-result contract was relaxed.

M8 97-row smoke validation passed 112 complete result comparisons (56 cases by
two tracks) against explicitly typed DuckDB; evidence
`evidence/m8-smoke-validation.json`. No study timings were collected. A later
native review corrected prepared timing arithmetic and aligned resident
validation with fresh prepare/execute; final gates must cover those changes.

## M9 frozen-source gate in progress

Command `.venv/bin/python tools/verify.py --profile core`; current evidence
`build/verification/20260920T062559.123650Z-core/summary.json`. Debug completed
with exit 0 for configure/build/CTest, 1,376 Python tests, and demo. Native test
output contains 39 cases / 5,438 assertions, plus 512 SQL and 512 CSV mutation
cases. The two Hypothesis properties each observed 40 passing generated examples
(separate from the pytest case count). Source fingerprint is
`9d334b2f4873ca91e6a2ec476e098da40579e45e33aaae5625adc7d242f47aaa`.
Later Release/sanitizer steps and overall status are not yet claimed here.

## M9 final core result

The source-frozen core command exited **0**, all **13 steps passed**. Summary:
`build/verification/20260920T062559.123650Z-core/summary.json`; compact observed
evidence `evidence/m9-final-gate.json`. Source unchanged at
`9d334b2f4873ca91e6a2ec476e098da40579e45e33aaae5625adc7d242f47aaa`.

Each of Debug, Release and ASan/UBSan passed 1,376 Python test cases with zero
failures/errors/skips, 39 native cases / 5,438 assertions, and 512 SQL plus 512 CSV
mutation cases. Each build executed all 1,008 content-hashed generated cases
under 20 configurations: 20,160 comparisons per build, 60,480 repeated-config
comparisons total. The number of distinct generated cases remains 1,008. Two
Hypothesis properties observed 40 passing examples each per build. Native
outputs are copied to the gate directory as `native-{debug,release,sanitize}.log`.
LeakSanitizer remains unsupported on this macOS runtime and was disabled;
ASan/UBSan passed. Linux/hosted macOS CI and the separately bounded extended
2,016-case profile were not run. Clean installation and study are pending.

## M9 clean source/build/install result

Command `.venv/bin/python tools/clean_check.py --output build/m9-clean-final`
exited **0**; all 13 steps passed. Full inventory/hashes/commands/exits/logs:
`build/m9-clean-final/summary.json`; compact evidence `evidence/m9-clean-check.json`.
The copy includes all nonignored tracked/untracked source present at start,
uses a new local virtual environment, validates the pinned header cache, and
creates all native products afresh. Both copied source and original source
fingerprint remained unchanged. Bootstrap was the only network-enabled step.

Observed: clean Release configure/build, CTest, local CMake installation, a
separate native CMake core-only build with PATH=/usr/bin:/bin, its demo, an
installed-header/static-library C++ consumer returning COUNT(sales)=96, installed
demo and EXPLAIN ANALYZE, and `otool -L`. Runtime dependencies contain only libc++
and libSystem; no Python/DuckDB library or Python process is required for the
compiled CLI/library. The minimal environment limits PATH, not OS availability
of every interpreter. This is a local macOS observation, not a Linux result.

M8 10,000-row profile passed: command
`.venv/bin/python tools/benchmark.py --manifest data/benchmarks/10000/manifest.json --output reports/benchmarks/10000 --measure --verification build/verification/20260920T062559.123650Z-core/summary.json`
exited 0. All 112 complete case/track validations passed before measurement;
224 warmups and 784 recorded trials were retained. Source/binary/input hashes
remained unchanged; status, exact commands and raw logs are under
`reports/benchmarks/10000/`. The 100,000-row profile and combined report remain
pending; this one profile does not complete M8.

Final review correction: Darwin ps truncated absolute paths in the secondary
overlap guard's comm column. The guard now uses ucomm on Darwin and comm on
Linux. All 24 benchmark-tool tests passed, including platform regressions; a
live Python verifier sentinel was rejected and the cleared inventory passed.
Evidence `evidence/m9-process-guard.json`. The earlier study completed both
profiles under coordinated isolation and is retained, but a new final core gate,
clean copy and study will align all final artifacts with this tooling change.
No timed C++ code, build flags, query or dataset changed.

## Retained M7 diagnostic failures

`evidence/m7-python-targeted.log` records 123 passes and two failures in the
new malformed-session test: invalid execution-option fields correctly return
the documented CLI category, while the new test initially allowed only
PROTOCOL/RESOURCE. The test expectation was corrected to include that documented
category; successful recovery remains required. No engine or SQL-result
comparison behavior changed.

`evidence/m7-python-expanded.log` records 1,134 passes and three UTF-8 ordering
disagreements. The minimized independent oracle regression and targeted optimizer
setting resolve them, as recorded above. These original failures remain visible;
later passing gates do not retroactively turn the diagnostic runs into passes.

Final implementation gate after the process-inventory correction passed all
13 steps with exit 0: `build/verification/20260920T064356.232524Z-core/summary.json`, compact evidence
`evidence/m9-final-gate-v2.json`. Each Debug/Release/ASan+UBSan build passed
1,378 Python tests (zero failures/errors/skips), all 1,008 distinct content
identities × 20 configurations, 39 native cases / 5,438 assertions, and 512 SQL
plus 512 CSV mutation cases. Source was unchanged at
`993bef547cee6f56657330eafcd606b4c8d535760e9e97e04bd4242e4bc1b553`. The Release binary
remains `4bb67a95d79b66d09811158e0cce9d3a4411b21dc5e32bc43687f9b2e0ede9ad`.
The fresh final clean-copy check is running; final study reruns follow it.

The final clean-copy check also passed all 13 steps with exit 0 at unchanged
source fingerprint 993bef547cee6f56657330eafcd606b4c8d535760e9e97e04bd4242e4bc1b553.
Command `.venv/bin/python tools/clean_check.py --output build/m9-clean-final-v2`;
evidence `evidence/m9-clean-check-v2.json`, full inventory and logs
`build/m9-clean-final-v2/summary.json`. The installed demo/EXPLAIN, native
minimal-PATH build, installed C++ consumer and runtime-library inspection passed.
Final benchmark output directories will be `reports/benchmarks/final-10000`
and `reports/benchmarks/final-100000`; earlier runs are retained unchanged.

## Final handoff artifact check

`evidence/m9-handoff.json` records demo and EXPLAIN ANALYZE exit 0 on the final
Debug binary, 24 resolved README/docs relative Markdown file links, unchanged
source and all three binary hashes against the final gate, byte-identical
regenerated reports, and local uncommitted Git state with no HEAD/remote. External
URLs and anchors were not checked. No required local failure remains. Verdict:
CORE_VERIFIED_LOCAL; next action is stop at M9.
