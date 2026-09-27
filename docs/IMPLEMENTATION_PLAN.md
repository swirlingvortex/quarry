QUARRY — IMPLEMENTATION BRIEF

CURRENT AUTHORIZATION: Implement M0 through M3, including tests,
review, and a runnable demo. Save the entire roadmap. Do not begin
M4 or extensions until separately authorized. Do not stop after
merely writing a plan.


1. MISSION AND BOUNDARIES

Build Quarry: an original, single-process, single-threaded,
in-memory analytical SQL engine in C++20, with Python verification
and experiment tooling.

The finished core must have its own:
- Parser and binder.
- Column storage.
- Scalar and batch executors.
- Aggregation and inner hash joins.
- Conservative optimizer.
- Explain/profiling interface.
- Reproducible performance study.

Quarry is a separate project, not a MarketForge module. Do not
alter MarketForge, Arbiter, Quant Options Lab, or sibling
repositories. Do not add trading, pricing, prediction-market,
prompt-optimization, or machine-learning functionality.

The central question is:

How do execution granularity, column pruning, and safe predicate
pushdown affect analytical queries while preserving results?

Python may generate datasets, run differential tests, and produce
reports. It must not execute Quarry queries.

DuckDB is an external test oracle, not Quarry's backend. The core
library and normal CLI must run without DuckDB installed.

V1 excludes persistent database files, transactions, updates,
deletes, indexes, concurrent queries, distributed execution,
networking, cloud services, a GUI, LLVM/JIT compilation, GPU
execution, handwritten SIMD, Parquet, and Arrow.

Use standard containers and small supporting libraries where
appropriate. Do not build a custom hash-table framework before
demonstrating a bottleneck.

Do not promise to outperform DuckDB or present this as
production-ready infrastructure.


2. EXECUTION AGREEMENT

The user is initially selecting Astra with ultra and fast. Do not
change or invent model settings. The implementation must remain
resumable after a model change.

First inspect:
- Actual working directory and repository state.
- Applicable AGENTS.md instructions.
- OS, CPU architecture, and available memory.
- Compiler, CMake, and Python.
- Network and dependency-installation restrictions.

Do not assume the cloud environment is the user's Mac or that
laptop paths are accessible.

Work only in the selected Quarry repository. Preserve unrelated
files and user changes. Do not publish, push, tag, rewrite history,
or run destructive cleanup.

Use repository-local dependencies. No sudo or global package
changes. Platform-required task snapshots are not permission to
publish.

Proceed autonomously through authorized milestones. Choose the
narrowest correct implementation for routine ambiguities and
record material decisions.

Stop at the authorized boundary or a genuine blocker. Never
convert a missing capability into a fabricated pass.

One owner controls core interfaces and integration. When the
runtime supports subagents, use at most two additional workers
for disjoint tests, documentation, or read-only adversarial review
after contracts are defined.

Do not assign multiple writers to the same core files. Without
subagents, perform separate review passes and report that
accurately.

After meaningful tested increments, update:
- docs/CHECKPOINT.md
- docs/VERIFICATION.md

Record the milestone, source fingerprint, commands, exit codes,
log locations, remaining failures, and next action.

Create a short repository AGENTS.md containing scope, commands,
evidence requirements, and ownership rules. Point it to the full
plan in docs/IMPLEMENTATION_PLAN.md rather than duplicating the
entire specification.


3. TOOLCHAIN AND REPOSITORY

Use:
- C++20.
- CMake with Debug, Release, and ASan/UBSan presets.
- Catch2 or an equivalent established C++ testing framework.
- Python 3.12 when available.
- pytest, Hypothesis, and pinned DuckDB for verification.

Pin dependency versions or commits after successful bootstrap.
Record compiler and interpreter versions.

A small JSON library is allowed for the CLI/catalog boundary.
SQL parsing and CSV parsing remain Quarry's responsibility.
Do not embed another SQL parser or query engine.

Fetch dependencies only during documented bootstrap. Subsequent
ordinary builds and tests should work offline from the provisioned
environment.

Suggested layout:

quarry/
  CMakeLists.txt
  CMakePresets.json
  AGENTS.md
  README.md
  include/quarry/
  src/common/
  src/storage/
  src/sql/
  src/planner/
  src/execution/scalar/
  src/execution/vector/
  src/optimizer/
  src/cli/
  tests/unit/
  tests/integration/
  tests/differential/
  tests/regressions/
  tests/fuzz/
  tools/
  benchmarks/queries/
  benchmarks/manifests/
  examples/
  docs/

Provide a reusable quarry_core library and a quarry executable.
Keep Python test dependencies outside the core build.

Ignore build directories, virtual environments, large generated
datasets, and transient logs. Preserve compact canonical fixtures,
benchmark definitions, and regression cases.

Provide:
- Bootstrap script.
- tools/verify.py with smoke, core, and extended profiles.
- Deterministic dataset generator.
- Benchmark runner.
- Report generator.

The verification script orchestrates existing tools; it should not
become a custom build system.


4. EXACT SQL SURFACE

Implement this explicit subset:

SELECT select_item [, select_item ...]
FROM table [AS alias]
[INNER JOIN table [AS alias]
   ON left_column = right_column
   [AND left_column = right_column ...]]
[WHERE predicate]
[GROUP BY column [, column ...]]
[ORDER BY output_name_or_position [ASC|DESC]
   [NULLS FIRST|NULLS LAST] [, ...]]
[LIMIT nonnegative_integer]

Support:
- SELECT * and qualified columns.
- Explicit AS aliases.
- Literals and parentheses.
- Unary minus and numeric +, -, *, /.
- Comparisons.
- AND, OR, NOT.
- IS NULL and IS NOT NULL.
- COUNT(*), COUNT(expr), SUM, AVG, MIN, MAX.

Allow numeric arithmetic in SELECT expressions and aggregate
arguments.

Keep WHERE predicates to typed column/literal comparisons, null
tests, and boolean composition in v1. Reject arithmetic and casts
inside WHERE.

JOIN conditions are conjunctions of column-equality predicates.
Support at most one join per query.

GROUP BY accepts column references, not aliases or arbitrary
expressions. Group/join keys support INT64, BOOL, and STRING,
including composite keys. DOUBLE keys are excluded in v1.

Require nonaggregate output columns to be grouping columns.
Reject nested aggregates.

ORDER BY resolves output names or positive output positions only.
Reject ambiguous output-name references.

Identifiers are ASCII and case-insensitive. String values are
case-sensitive UTF-8.

Support single-quoted strings with doubled-quote escaping,
whitespace, line comments, and an optional terminal semicolon.
Reject multiple statements.

A FROM clause is required in v1. Use a one-row fixture for
constant-expression tests.

Use a real tokenizer and recursive-descent/Pratt parser. Bind
names and types before execution. Do not perform name lookups
inside per-row hot loops.

Explicitly reject:
DISTINCT, HAVING, OFFSET, subqueries, CTEs, UNION, window functions,
outer/cross/non-equality joins, multiple joins, quoted identifiers,
arbitrary SQL functions, dates/timestamps, DDL, and DML.

Unsupported syntax produces a structured error, never a
best-effort reinterpretation or external-engine fallback.


5. TYPES AND SEMANTICS

Internal types:
INT64, DOUBLE, BOOL, STRING.

Every type supports NULL. SQL CAST type names are BIGINT, DOUBLE,
BOOLEAN, and VARCHAR.

Numeric operations require matching operand types, except integer
division produces DOUBLE.

Support explicit CAST(INT64 AS DOUBLE), plus
CAST(NULL AS one_of_the_four_types) for typed nulls.
Other casts are out of scope.

NULL literals may inherit types from context. Reject genuinely
ambiguous types rather than guessing.

Do not introduce implicit string, boolean, or cross-numeric
coercions.

Integer addition, subtraction, multiplication, and unary negation
are checked for overflow. Division by zero produces a structured
numeric error.

Reject NaN and infinity in input and reject nonfinite computed
results. Do not enable fast-math. Propagate nulls before applying
numeric operations to their payloads.

SUM(INT64) uses a checked wide internal accumulator and checked
final conversion to INT64. Isolate any compiler-specific 128-bit
implementation behind one wrapper and verify compiler support.

AVG returns DOUBLE.
SUM(DOUBLE) returns DOUBLE.
COUNT returns INT64.
MIN/MAX preserve supported input types.

Document the narrower integer SUM result as an intentional
difference from DuckDB. Do not hide it in the comparator.

Comparisons involving NULL return UNKNOWN. WHERE retains only
TRUE. Implement complete TRUE/FALSE/UNKNOWN truth tables for
AND, OR, and NOT.

NULL = NULL is not TRUE.
IS NULL and IS NOT NULL produce non-null boolean results.

COUNT(*) includes every row.
COUNT(expr) ignores null expression values.
SUM/AVG/MIN/MAX ignore null arguments and return NULL when no
non-null values exist.

A global aggregate over empty input returns one row.
Grouped aggregation over empty input returns no rows.

Null grouping keys belong to the same group.
Null join keys do not match.

Default ordering is ASC NULLS LAST. NULLS LAST remains the default
for DESC. Implement explicit alternatives.

Compare strings by unsigned UTF-8 bytes without locale collation.
Preserve duplicate rows. Do not promise output order without
ORDER BY or a specific order within ties.

Numeric-error behavior must not depend on batch size. Specify a
common evaluation domain for scalar/vector expressions, including
masked-out rows and LIMIT.

Do not evaluate invalid payloads or extra vector lanes merely
because they share a batch. Use a conservative materializing path
for potentially failing projections when necessary for consistent
semantics.

Floating-point result comparison uses documented tolerances,
never approximate SQL equality.

Use bounded generated numeric domains for differential tests and
high-precision references for targeted cancellation/overflow cases.
Never loosen tolerances merely to make failures disappear.

Document these decisions in docs/SQL_SUBSET.md with supported
examples, rejected examples, return types, and a compatibility
matrix. Do not advertise full SQL or DuckDB compatibility.


6. INGESTION, OWNERSHIP, AND RESOURCE LIMITS

Load tables from a JSON catalog manifest containing relative CSV
paths and explicit column names, types, and nullability.
Do not infer schemas.

Implement this CSV dialect:
- Comma delimiter.
- Mandatory header.
- LF and CRLF records.
- Double-quoted fields and doubled double-quotes.
- Embedded commas/newlines inside quoted fields.
- Unquoted \N represents NULL.
- Quoted "\N" is a string.
- Empty string is not NULL.

Reject malformed records, duplicate columns, wrong field counts,
invalid UTF-8, overflow, and invalid typed values with
file/record/column diagnostics.

Explicitly define numeric whitespace and boolean-token policies.

Load into a temporary table and publish it to the catalog only
after successful validation. Failed loading leaves no partial
table.

Use contiguous typed numeric buffers, byte-valued booleans,
validity bitmaps, and owned string storage.

Offsets-plus-byte-buffer string storage is preferred, but a
simpler owning representation is acceptable for M1 when clearly
documented.

Never leave string views referencing reused CSV or execution
buffers.

Tables are immutable after loading. Query contexts own temporary
allocations. Batches carry explicit row counts, typed column views,
validity information, and selection indices.

Define ownership and view lifetimes before implementing operators.
Distinguish end-of-stream from a filtered batch with no surviving
rows.

Track Quarry-owned table, operator, and result-buffer allocations.
Start with a configurable 512 MiB engine-accounted memory budget.

This is not a hard operating-system RSS cap. Document untracked
library/runtime overhead. Record peak accounted bytes and report
RSS separately when available.

Test cleanup after success and failure.

Bound SQL length/nesting, CSV field size, and materialized results.
Default result cap: 100,000 rows, configurable.

Exceeding a cap returns an error, not silently truncated results.
CLI JSON errors must not masquerade as successful partial results.

Larger workloads require an explicit profile and resource
preflight.


7. ARCHITECTURE AND OPERATOR CONTRACTS

Pipeline:

SQL
 -> tokens
 -> AST
 -> bound query
 -> logical plan
 -> optional optimizer
 -> physical plan
 -> executor
 -> result sink

Scalar and vector execution share the catalog, immutable column
data, bound types, and logical semantics.

They must have distinct row-at-a-time versus batch operator
traversal. A vector executor with batch size one is not the scalar
implementation.

The scalar baseline must be competent. No artificial sleeps,
unnecessary parsing, deliberately inefficient containers, or
special handicaps.

Match physical algorithms when comparing execution granularity.
Compare scalar hash join with vector hash join, not nested-loop
join with hash join and call the difference vectorization.

Use a pull-based batch interface or similarly simple contract.
Start with flat typed batches and selections.

Default batch size: 1,024, configurable.
Test sizes: 1, 7, 256, 1,024, 4,096, and partial final batches.

Batching is not evidence of SIMD. Claim CPU-vector instructions
only when inspected.

Implement:
Scan, Filter, Project, HashAggregate, Sort, Limit, InnerHashJoin.

Aggregation, sorting, and join building are blocking. Document
what they retain.

Scan/filter/project should not copy entire tables or allocate a
generic boxed Value for every cell in vector hot paths.

Hash joins preserve many-to-many multiplicity and resume correctly
when one probe row's matches span multiple output batches.

Use an independent tiny nested-loop implementation only as a
correctness oracle. Standard hash containers are acceptable.

Operators expose identifiers, output schemas, execution modes,
input/output row counts, and relevant buffer accounting.

EXPLAIN returns unoptimized logical, optimized logical, and
physical plans.

Profiling adds observed counters and clearly labeled timing
scopes. Do not sum inclusive parent/child times and call that total
runtime.

The optimizer starts off. Later implement:
- Column pruning.
- Safe predicate pushdown.
- Safe literal constant folding.
- Transparent join build-side selection.

Use bound column identifiers and provenance, not name guessing.

Preserve columns needed by joins, filters, sorting, and aggregates
even when not directly projected.

Never apply two-valued boolean simplification to nullable
expressions, reorder floating-point arithmetic, or move potentially
error-producing expressions across filters/limits.

Do not push LIMIT through joins or aggregation.

Treat DOUBLE SUM/AVG as order-sensitive and potentially failing.
Preserve accumulation order across scalar/vector paths. Disable
join-side changes that alter that order unless an explicitly
specified, tested accumulation policy makes them safe.

Maintain rule-level toggles and plan tests.
Performance gains never excuse semantic changes.


8. USER AND TEST INTERFACES

Required commands, with precise flags finalized at M0:

quarry query --catalog examples/catalog.json \
  --sql-file examples/query.sql

quarry explain --catalog examples/catalog.json \
  --sql-file examples/query.sql

quarry demo

quarry session --stdio --catalog examples/catalog.json

quarry bench --manifest benchmarks/manifests/smoke.json

query supports:
--engine scalar|vector
--optimizer on|off
--batch-size
memory/result limits
--format table|json

Expose only implemented modes. Requesting an unimplemented mode
is an error.

The stdio session is a local JSON-lines protocol that loads a
catalog once and executes multiple read-only queries.
It is not an HTTP service.

Bound request sizes and recover from individual query errors.
Keep results on stdout and diagnostics on stderr.

JSON results contain output names, logical types, and row arrays.
Preserve INT64 exactly, preferably using decimal strings with
schema-aware decoding.

Do not compare human-readable tables or rounded floating text.

The native benchmark command executes Quarry repeatedly in one
process with data already loaded. Python orchestrates but does not
enter the per-row hot path.

Canonical final demo:

SELECT c.region, COUNT(*) AS orders, SUM(s.amount) AS revenue
FROM sales AS s
INNER JOIN customers AS c ON s.customer_id = c.customer_id
WHERE s.amount >= 50.0
GROUP BY c.region
ORDER BY revenue DESC NULLS LAST, region ASC
LIMIT 10;

Use original deterministic retail datasets, not financial data
from existing projects.

Include nullable fields, duplicate keys, unmatched keys, skew,
low/high cardinality, and long strings.

Save seeds, schemas, generator versions, and file hashes.


9. MILESTONES AND ACCEPTANCE GATES

M0 — BOOTSTRAP AND CONTRACTS

Inspect the environment, create the build skeleton, record scope
and semantics, specify ownership/error/result contracts, provision
pinned dependencies, and produce working CLI help plus a real
compiled/running test.

Gate:
A clean Debug build and test invocation pass. Environment evidence
and initial checkpoint exist.

Do not spend the run producing speculative diagrams or empty
class scaffolding.


M1 — COLUMN STORAGE AND CSV

Implement types, validity masks, owning tables, catalog loading,
checked scalar primitives, and resource-tracking foundations.

Gate:
Hand-checked tests cover null/empty distinctions, quoting/newlines,
malformed files, integer bounds, failed-load cleanup, and buffer
lifetimes.

Test empty, one-row, and multi-batch-sized tables.


M2 — FIRST END-TO-END SQL EXECUTION

Implement tokenizer/parser/binder, logical plans, scalar
scan/filter/project, structured output, and query/explain CLI.

Gate:
SQL text produces correct results from actual CSV tables.

Validate precedence, qualification, ambiguous names, type errors,
unsupported syntax, boolean truth tables, and lossless output.

Add the DuckDB harness now, not at the end.


M3 — COMPLETE SCALAR SINGLE-TABLE CORE

Add global/grouped aggregation, sorting, LIMIT, the stdio session,
deterministic fixtures, and a single-table demo.

Implement the supported single-table surface rather than
parser-only promises.

Gate:
Run relevant C++ tests and at least 200 bounded, deterministic
generated query/data cases against DuckDB.

Cover every supported single-table operator and edge category.
Test counts do not substitute for coverage.

Also check explicit hand-computed fixtures. Run supported
sanitizers and record missing capabilities accurately.

Perform an adversarial review of types, nulls, aggregation,
ordering, and ownership. Fix findings and rerun affected tests.

STOP THE INITIAL TASK HERE.

Leave a runnable demo, verification evidence, and the M4
continuation goal. Do not label Quarry fully complete.


M4 — GENUINE BATCH EXECUTION

Implement vector scan/filter/project/aggregate/sort/limit using
typed loops, selections, and correct lifetimes.

Gate:
Scalar, vector, and DuckDB agree under documented comparisons
across batch sizes and empty/partial/all-filtered batches.

Demonstrate that vector execution is not a wrapper around the
scalar row executor.

Do not require a speedup to pass correctness.


M5 — INNER HASH JOINS

Implement binding and execution for the exact one-join subset in
both modes.

Use matched hash-join algorithms and the independent tiny
nested-loop oracle.

Gate:
Cover composite/null/duplicate keys, empty inputs, many-to-many
joins, unmatched rows, swapped build sides, string lifetimes, and
output continuation across batch boundaries.

Enforce memory/result caps without corrupting subsequent session
queries.

The canonical joined demo must now run.


M6 — CONSERVATIVE OPTIMIZER AND OBSERVABILITY

Add safe rules, individual toggles, pruning/pushdown counters, and
explain/analyze output.

Keep raw and optimized plans accessible.

Gate:
The same cases pass with each rule individually enabled and with
all rules on/off in both executors.

Plan/counter tests prove that pruning and pushdown occur.

Review nullable predicates and hidden-column preservation.


M7 — ADVERSARIAL VERIFICATION AND PORTABILITY

Expand the core differential profile to at least 1,000 bounded
query/data cases. Add a separately bounded extended profile.

Keep generated join inputs small to prevent quadratic explosions.
Shrink failing examples into permanent regressions.

Add parser/CSV fuzz targets where supported, allocator-failure
tests, and malformed-request recovery tests.

Gate:
Debug, Release, and supported ASan/UBSan suites pass.

Distinguish failures from unsupported checks.

Configure Linux and macOS CI, but do not mark remote jobs passed
without observing them.

Test clean builds and core CLI execution without Python or DuckDB
runtime dependencies.


M8 — REPRODUCIBLE PERFORMANCE STUDY

Create predeclared workloads, measurement scripts, raw records,
and a report explaining both wins and losses.

Gate:
Every timed configuration passes result validation.
Summary numbers regenerate from raw records.
Build/source fingerprints match the measured binary.

Include cases where optimization offers little benefit.

No fabricated speedup targets.
No machine-dependent speed requirement in CI.


M9 — FINAL REVIEW AND LEARNING HANDOFF

Freshly review SQL semantics, memory/lifetimes, join multiplicity,
optimizer safety, reference-test independence, benchmark fairness,
and scope compliance.

Fix findings and rerun affected/full gates.

Make installation and demo work from a clean directory.

Gate:
Produce FINAL_AUDIT.md, LEARNING_GUIDE.md, a capability matrix,
limitations, benchmark report, and final checkpoint.

Use one evidence-backed verdict:
CORE_VERIFIED_LOCAL
CORE_WITH_UNVERIFIED_CHECKS
INCOMPLETE

Explain the verdict.
Do not claim production readiness or publish automatically.


10. DIFFERENTIAL AND METAMORPHIC TEST RULES

Create DuckDB tables with explicit types and insert the same
logical data. Do not use independent CSV/schema inference that
changes the test.

Pin DuckDB, use one thread, and record settings.

Maintain an explicit compatibility adapter only for declared
dialect/type differences.

Compare schemas, row counts, values, nullness, and duplicate
multiplicities.

Without ORDER BY, compare multisets, not sets.

With total ordering, compare sequences.

For ordering ties, compare equivalent tie groups rather than
assuming stability.

For LIMIT without total ordering, verify valid cardinality and
membership constraints or use a total-order test. Do not report
arbitrary row differences as bugs.

Use exact integer/string/boolean comparisons.

State and justify floating-point tolerances for generated domains.
Check numerical stress cases independently.

Match approximate rows without discarding duplicate multiplicity.
Do not round all results to conceal errors.

Metamorphic checks:
- Optimizer on/off equivalence.
- Scalar/vector equivalence.
- Batch-size invariance.
- Qualified/unqualified equivalent names.
- COUNT(*) versus materialized row count.
- Safe predicate decomposition.

Only use transformations whose preconditions hold under null and
numeric-error policies.

Test the comparator itself with deliberately corrupted results:
a missing duplicate, swapped columns, altered NULL, truncated
INT64, and significant numeric error must all fail.

Preserve failing SQL, schema, data, seed, plan, engine options,
and build fingerprint.


11. BENCHMARK SCIENCE

Primary comparisons:

A. Scalar versus vector:
Same column storage, optimizer settings, physical algorithms,
and result sink.

B. Optimizer off versus on:
Same executor.

C. Selected batch sizes:
Everything else fixed.

Never conflate row-at-a-time execution with row-oriented storage.
A row-store baseline is not part of the core.

Exclude metadata-only COUNT shortcuts from the primary scan study
unless both paths use them and they are explicitly labeled.

Freeze approximately 12 query definitions before examining
results. Cover:
- Selective/nonselective numeric scans.
- Narrow projections over wide tables.
- Null-heavy predicates.
- Low/high-cardinality grouping.
- String grouping.
- Sorting with LIMIT.
- Duplicate/skewed-key joins.

This is an original microbenchmark suite, not a full TPC-H result.

Use small correctness fixtures, 10,000/100,000-row routine
performance profiles, and an opt-in 1,000,000-row profile subject
to memory preflight.

Sweep selectivity/cardinality/skew on a declared subset. Avoid an
uncontrolled Cartesian product of configurations.

Separate ingestion, parse/bind/plan, execution/result consumption,
and rendering.

Publish:
1. Resident-data query latency including parse/plan/execute/drain.
2. Prepared-plan execution with fresh execution state each repeat.

Never report CSV loading or process startup as vector-kernel speed.

Use Release builds, a monotonic clock, one execution thread, two
warmups, and at least seven recorded repetitions per default case.

Interleave configuration order with a saved seed.

Fully consume output through the same sink. Record row counts
and typed digests outside timing where appropriate.

Perform complete result comparison outside timing.
A digest alone is not correctness proof.

Save every measurement, not just averages.

Report median and interquartile range, input/output sizes,
accounted allocation peaks, and optional RSS with its scope.

Exclude profiling overhead from ordinary timing.

Record machine, OS, compiler/flags, dependencies, query/data
hashes, source fingerprint, settings, warmups, repeats, and failures.

Require reproducible inputs, procedure, and report arithmetic,
not identical wall-clock values.

DuckDB is mandatory for correctness but optional for external
performance comparisons.

Never compare native Quarry timings directly against Python
DuckDB-call timings as though overheads were identical.

A DuckDB performance track requires a separate native C/C++ runner
with aligned loading, threading, query phases, result consumption,
and documented materialization differences.

Do not link DuckDB into normal quarry_core or CLI targets.

Without that runner, publish internal measurements only and
explain the limitation.

Rerun measurements after changes to timed code, compiler flags,
or datasets.

Generate reports from raw records. Do not hand-edit conclusions
or omit losing cases.


12. DOCUMENTATION, COMPLETION, AND CONTINUATION

Required final artifacts:

docs/SQL_SUBSET.md
docs/ARCHITECTURE.md
docs/CHECKPOINT.md
docs/VERIFICATION.md
docs/BENCHMARKS.md
docs/FINAL_AUDIT.md
docs/LEARNING_GUIDE.md
docs/CODEX_GOALS.md

Also preserve deterministic examples, compact regression fixtures,
and report-generation scripts.

The learning guide must explain:
- One query from SQL text to results.
- Binding versus parsing.
- Column buffers and validity masks.
- Selection vectors.
- Hash aggregation.
- Duplicate-preserving joins.
- Blocking operators.
- Safe optimization.
- Measurement limitations.
- Intentional differences from DuckDB.

Include small exercises and debugging walkthroughs so the owner
can explain the project beyond generated code.

Completion requires working code and observed acceptance evidence,
not a large line count, assertion count, or attractive documentation.

Distinguish test cases, generated examples, skipped checks, and
assertions.

At handoff report completed milestones, known defects, executed
commands/counts, verification limitations, source state, a runnable
next command, and the exact next goal.

Do not start extensions while core failures remain.

Save these continuation goals in docs/CODEX_GOALS.md:

GOAL 2:
Read AGENTS.md, IMPLEMENTATION_PLAN.md, CHECKPOINT.md, and
VERIFICATION.md. Inspect actual source state and rerun relevant
M0-M3 smoke gates. Implement M4-M6 only, preserving contracts and
fixing regressions. Review semantics and lifetimes, update evidence,
and stop at M6.

GOAL 3:
Read the same files, inspect current state, and verify M0-M6
foundations. Complete M7-M9 only. Prioritize adversarial correctness
checks and reproducible measurements over new features. Produce
the final audit and learning guide. Do not publish, push, tag,
or add extensions.

Extensions require separate authorization after M9. First consider
per-chunk statistics/zone-map pruning, then dictionary encoding
or a top-k operator, each with an isolated experiment and full
regressions.

Do not silently add extensions to the initial project.

START NOW WITH M0-M3.

Bootstrap, implement, test, review, and leave a working single-table
engine. Record genuine blockers without faking evidence or asking
for decisions already specified above.