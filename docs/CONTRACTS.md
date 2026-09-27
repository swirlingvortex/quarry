# M0 contracts

Historical M0–M3 baseline contracts (superseded in authorization by the continuation below). The full roadmap is preserved verbatim in
IMPLEMENTATION_PLAN.md. Current M4–M6 authorization is recorded below.

## Interfaces frozen for tests

`quarry query|explain --catalog PATH (--sql SQL | --sql-file PATH)`.
`query` accepts `--format json|table` (default table), `--engine scalar`
(default), `--optimizer off` (default), `--memory-limit BYTES` (default 536870912),
`--result-limit ROWS` (default 100000). `--batch-size` is reserved and rejected
until M4. Vector, optimizer on, join, and bench are unsupported in this phase.
`quarry demo` runs the repository's deterministic single-table example.
`quarry session --stdio --catalog PATH` uses the same resource flags and one JSON
request per line: `{"id":optional_json,"sql":"SELECT ..."}`. Responses echo id.
Each response is a complete query result or error; query failures keep the session
alive. EOF closes it. No multiline transport or network service.

Catalog schema: `{"tables":[{"name":"sales","path":"sales.csv","columns":
[{"name":"id","type":"INT64","nullable":false}, ...]}]}`.
Paths must be relative to the manifest directory. Type spellings are INT64,
DOUBLE, BOOL, STRING. Header names match schema case-insensitively in order.

Success JSON: `{"ok":true,"columns":[{"name":"id","type":"INT64"}],
"rows":[["9223372036854775807"]],"stats":{"peak_accounted_bytes":123}}`.
Every non-null INT64 cell is a decimal string. DOUBLE cells are JSON numbers,
BOOL cells are booleans, STRING cells are strings, all nulls are JSON null.
Errors: `{"ok":false,"error":{"code":"PARSE|BIND|TYPE|NUMERIC|CSV|CATALOG|RESOURCE|UNSUPPORTED|IO|PROTOCOL|CLI|INTERNAL","message":"..."}}`.
One-shot errors exit nonzero and never contain partial result rows. Session
request errors are JSON responses; startup/catalog errors exit nonzero.

## Ownership and bounded work

The engine owns an immutable catalog; numeric columns use contiguous typed
buffers, booleans use bytes, validity uses packed bits. M1 strings are owning
PMR strings. A tracking memory_resource charges actual requested capacities for
table value/validity buffers and query operator/result buffers, including strings
and hash buckets/nodes. Results retain a shared owner of that resource and can
outlive the engine. Borrowed table/bound-plan references do not escape queries.
Failed table/catalog loads publish no partial state. Query temporaries unwind on
errors; session catalog allocations remain. Peak accounting is scoped to the
engine lifetime, including catalog loading, with current bytes also reported.

This is not an RSS cap. Parser/plan/schema metadata, bounded CSV/token scratch,
JSON DOM/rendering, allocator bookkeeping, standard-library/runtime overhead,
and stack are not engine-accounted. They are independently input-bounded. Results
are bounded both by engine-accounted memory and a configurable output row cap.
Default SQL/request limits are 64 KiB/128 KiB; expression depth is at most 128,
token count at most 4096; CSV fields at most 1 MiB and records at most 8 MiB;
manifest size at most 1 MiB. JSON nesting is at most 128 before DOM parsing. Materialized intermediate output/group rows also
obey the result cap. LIMIT cannot rescue a query exceeding that cap.

Scalar traversal is scan -> filter -> project OR hash aggregate -> project ->
sort -> limit. Predicates use SQL three-valued logic. Both boolean operands are
evaluated (WHERE has no arithmetic/casts). Row projections and aggregate arguments are
evaluated for every WHERE-surviving input row. Aggregate result projections run
once per completed group (including the empty global group), before ORDER BY and LIMIT,
including LIMIT 0. Rejected rows never evaluate projection payloads. This common
evaluation domain must remain fixed for M4. Nulls propagate before arithmetic;
nonfinite values, zero division, and checked integer overflow are errors.
DOUBLE aggregation accumulates in input order. INT64 SUM uses checked signed
128-bit accumulation and checked INT64 final conversion.

Parser produces AST; binder resolves ordinal column identifiers and types;
logical plan describes immutable bound stages; scalar executor performs row
traversal. Explain reports raw logical, identical optimized logical (off), and
physical operator stages with ids/schema/mode. M6 adds profiling/rule controls.
Group hash state retains keys/aggregate states; sort retains complete projected
rows. There is no streaming early-LIMIT behavior in M3.

Future M4 batches will have explicit row_count (zero selected rows is not EOF),
typed views/validity/selection indices and query-owned lifetimes. No batch
implementation or SIMD claim is made in M3.

Query and EXPLAIN share plan_query; typed physical stages compile into the
scalar pipeline controls. Optional process_peak_rss_bytes measures a process
lifetime high-water mark through result JSON construction and is separate from
engine accounting. LeakSanitizer is unavailable on the verified macOS runtime;
ASan and UBSan are supported and were executed.


## M4–M6 continuation contracts (2026-09-20)

The user separately authorized M4–M6. The original roadmap remains unchanged.
Baseline smoke gates passed before execution edits; evidence is
`build/verification/20260920T042430.801551Z-smoke/summary.json`.

C++ execution settings live in a separate `ExecutionOptions`, passed to query
and explain, so the catalog/resource owner does not change per query. CLI flags
are `--engine scalar|vector` (scalar default), `--batch-size N` (1024 default;
1..65536), `--optimizer on|off` (off default). M6 adds `--prune on|off`,
`--pushdown on|off`, `--fold on|off`, `--join-reorder on|off`,
`--build-side auto|left|right` and
`--profile`. Rule flags gate individual rules only when optimizer is on;
explicit build-side requests are physical test controls in either mode and
must reject unsafe order changes. `explain --analyze` executes and returns plans,
results and scoped counters/timings. Session defaults come from CLI; requests may
supply an `options` object with engine, batch_size, optimizer, prune, pushdown,
fold, join_reorder, build_side and profile. Invalid options are request errors; they never
mutate session defaults or the catalog.

Batch traversal uses explicit row counts, a separate EOF signal, typed vectors
and selection indices. Scalar remains independent. Borrowed string views refer
only to immutable catalog strings or query-owned expression/group/result storage;
only the final shared result sink creates owning Values. Blocking vector sort
retains typed columns and sorts row indices, then LIMIT slices the permutation.
Vector aggregate arguments are evaluated in typed loops and state is updated in
input order; completed group projections are evaluated as typed batches.

Join binding uses stable flattened column ids plus table-side/local provenance.
The default join builds the right input and emits left probe rows in input order,
with build matches in input order. Both modes use the same hash algorithm; a
stateful probe cursor resumes matches across output batches. No joined table is
materialized. Nullable INT64/BOOL/STRING composite keys are supported; any null
key does not match. DOUBLE keys and other join forms are rejected.

Optimizer pushdown moves only total single-input top-level conjuncts (never
arithmetic/error-producing expressions); residual predicates retain bound ids.
Pruning retains all columns used by predicates, joins, groups, aggregates and
output expressions. Folding replaces only successfully evaluated literal-only
subtrees; potentially failing constants remain at their original evaluation
site. Join swaps are disabled for any DOUBLE SUM/AVG to preserve accumulation
order, with the reason exposed. Rule application counts and actual scan/filter/
join/batch counters must substantiate changes. Profiling reports one overall
execution scope and clearly labeled operator scopes, never summed as total.

### M6 implemented rule and observability details

Pushdown applies below the one inner join, splitting only top-level AND terms
whose bound source set contains at most one input. Both inputs remain streaming.
Any potentially failing WHERE subtree disables all pushdown, including otherwise
total sibling terms, because boolean evaluation is eager. Signed literal negation
can fail even under the restricted WHERE grammar. Cross-input terms stay residual;
NULL retains SQL three-valued behavior. A single-table filter is already directly
above its scan and is not counted as a pushdown application.

Pruning compacts the query's actual opened typed ColumnView descriptors and scan
schemas. Scalar reads and join keys consume those views; vector gathers use
compiled compact slots. Bound column ids remain stable. Both optimizer settings
already use lazy payload access, so pruning can reduce columns_opened without
reducing values_read. No extra payload reads are added to the baseline.

Automatic join selection compares base table cardinalities (before predicates),
chooses the smaller build input and prefers right on ties. It records a decision
as one application even when right remains selected. Explicit requests override
automatic selection. DOUBLE SUM/AVG or potentially failing WHERE/projection/
aggregate argument expressions retain right build; unsafe explicit left requests
fail UNSUPPORTED. Successful folding may remove a conservative arithmetic guard.
The optimizer does not reorder arithmetic, simplify nullable boolean expressions,
or push LIMIT. Folding counts successfully replaced literal-only operator nodes;
pruning counts descriptors removed; pushdown counts moved conjuncts.

Every physical stage reports observed input_rows, output_rows and batches. Scalar
batches are row calls; vector batches are bounded chunks or blocking operator
passes. Join build_rows/probe_rows count filtered source rows consumed, including
NULL-key rows; candidate_rows counts emitted equal-key pairs before the residual
filter. Scan columns_opened counts actual constructed descriptors, columns_read
counts distinct accessed columns, values_read counts logical cell requests
(including validity checks and repeated expression references). These are not
storage I/O bytes. Scanned_rows counts base rows visited and filtered_rows counts
join/scan output surviving all predicates.

accounted_allocation_bytes counts cumulative PMR allocation requests inside each
operator's active scopes, not retained or peak bytes. Parent/child scopes overlap;
setup/teardown and bounded metadata can sit outside operator scopes. Engine peak
and current memory and process RSS remain separately labeled. Profile elapsed_ns
uses inclusive active scopes: join pulls include child scan/filter time, scans
cover descriptor setup and row-reference traversal, and consumer expressions own
payload-read time. Aggregate scopes include state updates/finalization; Project
includes the final owning sink. The separately measured execution_ns includes
executor setup/teardown. No timing or allocation sum is a total-runtime or
whole-process memory metric. EXPLAIN ANALYZE includes the ordinary result with
profiling enabled; plain EXPLAIN does not execute.

Multiple independent NUMERIC faults may report different diagnostic text across
batch sizes; the promised invariant is error category and evaluation domain,
including explicit row/group-cap precedence. Working-memory exhaustion can depend
on batch size and optimizer settings; successful-result equivalence is tested
with sufficient memory. Resource failures must unwind and leave the session
reusable. No performance improvement is claimed by M4–M6.


## M7–M9 continuation contracts (2026-09-20)

The user separately authorized M7–M9. Baseline smoke passed before edits:
`build/verification/20260920T055529.700797Z-smoke/summary.json`.
Primary owns C++/CMake, unit/fuzz native code, integration, checkpoint/verification.
Worker one owns Python differential/integration/fuzz verification, tools/verify.py,
and .github CI. Worker two owns benchmarks/, tools/generate_benchmarks.py,
tools/benchmark.py, tools/benchmark_report.py, tests/benchmark/, and BENCHMARKS.md.
No timed benchmark runs may overlap any Quarry builds/tests or other benchmarks.

M7 keeps the existing exact/approximate comparison policy. Core has at least
1,000 distinct bounded query/data cases, with stable case identity and content
hashes, separately counted from engine/rule repetitions. Fuzzing is deterministic
and bounded; any optional unsupported instrumentation is reported explicitly.
Allocation injection targets the accounted PMR resource and must unwind safely;
it does not claim coverage of global/runtime allocations.

PreparedQuery is opaque, move-only, and owns its plan and AST allocation owner.
Engine::prepare(sql,options) binds once; Engine::execute(prepared) creates fresh
operator state and resets query counters. Execution rejects a different engine,
a successfully replaced catalog, or a moved-from plan. Failed catalog loads do
not invalidate existing plans. Plans may be destroyed after the engine safely.
The engine remains single-threaded. Result ownership semantics are unchanged.

Native command: `quarry bench --manifest PATH [--validate-only]`. JSONL goes to
stdout. Manifest version1 contains catalog (relative to manifest), seed,
warmups>=2, repetitions>=7, memory_limit, result_limit, and cases. Each case has
id, workload, sql_file (relative to manifest), options (CLI session option names),
and order_keys for the Python comparator. Tracks are resident and prepared.
Unknown/invalid fields or profile=true are rejected; bounded manifests/case counts
prevent accidental unbounded runs. Tiny smoke fixtures use the same protocol.

Validation mode emits a header followed by one record per case and track:
`kind=validation`, case_id, track, result={ok,columns,rows}. INT64 remains decimal
strings. Python validates every complete resident and prepared result against
independently typed DuckDB input before timing. A digest is not validation.

Timing mode loads the catalog once, prepares each configuration outside timing,
and uses seeded shuffled configuration order per warmup/repetition. Each trial
emits kind=measurement, case_id, track, phase=warmup|recorded, repeat, order_index,
planning_ns, execution_ns, resident_ns, rendering_ns, output_rows, output_bytes,
digest, peak_accounted_bytes, current_accounted_bytes. The header records native
compiler/build type, ingestion_ns, seed, counts and per-case preparation_ns.
Resident trials include parse/bind/plan and execution through the owning result
sink; prepared trials execute an existing plan with fresh operator state. The
common owning Result sink fully materializes output. Typed digest traversal and
full result JSON rendering occur after execution timing, with rendering measured
separately. Results are released between trials. Ordinary timing disables profile
clocks; always-on default counters remain common to both executors. Peak bytes
remain explicitly engine-lifetime high-water marks, not per-trial deltas.

The Python runner freezes query/data/configuration/provenance hashes before
measurement, invokes only the native runner for timing, preserves failures and
all raw records, and verifies final hashes. Required study uses10,000/100,000
sales-row profiles, approximately12 predeclared queries and a finite declared
configuration/sweep list. Optional million-row profile remains disabled. Reports
regenerate medians/IQR and paired comparisons directly from raw JSONL, including
slowdowns and overlapping-IQR/inconclusive observations. No DuckDB timings or
speed targets. A later timed-code/flags/data change invalidates affected runs.
