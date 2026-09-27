# Quarry

Quarry is a single-process, single-threaded, in-memory analytical SQL engine in
C++20. It owns its parser, binder, column storage, and scalar and batch executors. Python and
DuckDB provide verification; neither executes Quarry queries inside the engine.

M0–M6 established typed batch execution, one inner hash join, and conservative
optimization/profiling. The authorized M7–M9 continuation adds adversarial
verification, reusable prepared plans, native benchmark tooling, and a learning
handoff. Work stops at M9; extensions require separate authorization.
Quarry is an educational experiment, not production infrastructure or a claim of
full SQL/DuckDB compatibility. See [verification](docs/VERIFICATION.md) for
observed checks and [checkpoint](docs/CHECKPOINT.md) for the exact source state.
The final local verdict is **CORE_VERIFIED_LOCAL**; the [audit](docs/FINAL_AUDIT.md)
records findings, measured wins/losses, and unobserved or unsupported checks.

From this repository:

```sh
python3.12 tools/bootstrap.py
.venv/bin/cmake --preset debug
.venv/bin/cmake --build --preset debug
.venv/bin/ctest --preset debug
build/debug/quarry demo
.venv/bin/python tools/verify.py --profile core
```

Bootstrap provisions pinned repository-local dependencies and is the only
network-enabled build step. Normal builds and tests use those local dependencies.
The compiled CLI does not require a Python process or DuckDB at runtime.
The separate `.venv/bin/python tools/clean_check.py` command creates a fresh
repository-local copy, runs the documented bootstrap, builds and installs
Release, and checks the installed CLI and C++ library consumer. It preserves its
logs under `build/`; it does not replace the working checkout.

```sh
build/debug/quarry query --catalog examples/catalog.json \
  --sql-file examples/query.sql --format json
build/debug/quarry explain --catalog examples/catalog.json \
  --sql-file examples/query.sql --engine vector --optimizer on --analyze
build/debug/quarry session --stdio --catalog examples/catalog.json
```

The session accepts one JSON object per line, for example
`{"id":1,"sql":"SELECT COUNT(*) AS rows FROM sales"}`. It loads the catalog once;
individual query errors produce error responses without ending the session.

Current execution accepts `--engine scalar|vector` (scalar default),
`--batch-size N` (1024 default, 1..65536), and `--optimizer on|off` (off default). The demo uses the
canonical sales/customer inner join. `--build-side auto|left|right` controls the
join build input; unsafe changes are rejected. With optimization on, `--prune`,
`--pushdown`, `--fold`, and `--join-reorder` independently enable or disable
rules using `on|off`. `--profile` adds scoped timings; `explain --analyze` includes
plans, results, and counters. Performance measurements use the separate native
`bench` runner and its validated manifest protocol.
Defaults are a 512 MiB engine-accounted memory budget and a 100,000-row
result/intermediate cap, configurable with `--memory-limit BYTES` and
`--result-limit ROWS`. This budget is not an operating-system RSS limit.

Session requests can override execution settings without changing session
defaults, for example `{"id":2,"sql":"SELECT COUNT(*) AS rows FROM sales",
"options":{"engine":"vector","batch_size":7}}`.

The core verifier runs Debug, Release, and supported ASan/UBSan checks. Its
generated corpus contains 1,008 distinct SQL/data cases, each exercised under
20 engine/rule configurations; manifests and execution receipts distinguish
those counts. Bounded mutation fuzzing, allocation-failure checks, hand cases,
and Hypothesis properties provide complementary coverage. `smoke` uses 36
generated cases; `extended` uses 2,016. Linux/macOS CI is configured, while
observed local and remote results remain explicitly recorded in verification.

The performance study uses 12 declared workloads on 10,000- and 100,000-row
fixtures, with resident-query and prepared-execution tracks. Follow the exact
validation, measurement, and report commands in [BENCHMARKS.md](docs/BENCHMARKS.md).
The scripts require matching verified source and Release binary fingerprints
before measurement. Builds, correctness checks, and measurements run separately.
No speedup follows from the presence of a batch executor; the saved measurements
must support any performance conclusion.

Read [SQL semantics and CSV format](docs/SQL_SUBSET.md),
[architecture and ownership](docs/ARCHITECTURE.md), and the
[learning guide](docs/LEARNING_GUIDE.md). The complete roadmap is preserved in
[IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md). The completed M4–M6 goal and
the authorized M7–M9 continuation are recorded in
[CODEX_GOALS.md](docs/CODEX_GOALS.md).
