# Architecture and ownership

The immutable catalog supports independent scalar and typed batch executors,
one inner hash join, and conservative optimization. Prepared execution and the
native benchmark runner reuse those same paths. Consult VERIFICATION.md for
observed gates rather than inferring acceptance from this design description.
The core is a reusable C++20 library; the CLI adapts catalogs, SQL input, table/JSON output,
and a local JSON-lines session. Python orchestrates verification against DuckDB
and generates fixtures. Neither Python nor DuckDB participates in Quarry's query
execution.

## Query path

SQL text → tokenizer → AST → binder → logical plan → physical stages →
owned result. Parsing checks syntax; binding resolves column ordinals, aliases,
types, aggregate/group legality, and output-order references before row loops.
The shared `plan_query` path owns the bound query together with typed logical and
physical stages. The scalar executor compiles the ordered physical stages into
a small pipeline of borrowed bound references, then traverses that pipeline.
EXPLAIN uses the same planning path; its stages are the execution contract.
`ExecutionOptions` selects scalar or vector traversal independently of the
catalog's resource owner. Query-local options do not mutate session defaults.

Scalar execution scans rows, filters with three-valued predicates, and either
projects rows or builds hash aggregation state and projects aggregate results.
Sorting and LIMIT follow materialization. This is an actual row-at-a-time
traversal, with a fused row loop and later blocking phases. EXPLAIN exposes
raw logical, optimized logical, and physical stages with explicit input-stage
identifiers, source aliases, bound columns, and expression labels. With
optimization off, the two logical plans agree.

## Data and lifetime boundaries

Numeric columns own contiguous typed buffers. BOOL uses byte values and validity
uses packed bits. Strings use owning PMR strings, a documented simpler
alternative to offsets plus a byte buffer. Nothing borrows a reused CSV buffer.
The catalog owns immutable tables after successful load; construction uses a
temporary table so errors publish no partial table.

Bound column references have stable flattened identifiers and table-side
provenance. Pruning maps them to compact scan-view slots; it never rebinds by
column name. Scalar payload access and vector gathers consume those opened
typed views. The view array reserves its final capacity before binding pointers
to descriptors. These views borrow from the catalog only during a query. Query
state owns group keys, aggregate state, intermediate projections, sorting
buffers, and results. A result retains shared ownership of its tracking memory
resource and can outlive the engine. Failure unwinds query temporaries while an
existing session catalog stays available. Engine copy and move operations are
deleted so assignment cannot replace its resource before destroying existing
table allocations; moving a standalone Result remains supported.

`Engine::prepare(sql, options)` returns an opaque move-only `PreparedQuery` that
owns the bound AST, physical plan, and shared AST memory-resource owner. It
borrows catalog columns through an identity-checked lifetime boundary.
`Engine::execute(prepared)` creates fresh operator buffers and counters on every
call; it does not cache prior rows, groups, hash tables, or result storage.

Execution rejects a plan from another engine, a successfully replaced catalog,
or a moved-from handle before reading any borrowed column. A failed catalog
load leaves both the previous catalog and its prepared plans usable. Destroying
a prepared plan after its engine is safe because its AST resource remains
owned; it cannot execute without the originating live engine. The engine and
its plans remain single-threaded and do not support concurrent execution.

A PMR memory resource charges requested capacities of table values/validity,
owned strings, and operator/result buffers, including hash nodes/buckets. The
default account budget is 512 MiB. The current and peak accounts cover engine
lifetime, including loading. This is not an RSS cap: most schema/parser/plan metadata,
bounded CSV/token scratch, JSON DOM/rendering, allocator metadata, stack, and
runtime overhead are untracked. PMR-owned AST string literals are accounted.
Input and result limits independently bound
those exposed work surfaces; see SQL_SUBSET.md.
On supported platforms the CLI also reports process peak RSS separately. It is
the process-lifetime high-water mark through result JSON construction, including
earlier session work and unaccounted allocations, not a query-only peak.

## Blocking state and error domain

Hash aggregation retains grouping keys and aggregate states. Scalar sorting
retains projected rows; vector sorting retains typed projected columns and a
permutation of row indices. Results and materialized/group intermediates share the
row cap. LIMIT operates after that work; it does not rescue an over-cap or
numerically invalid projection. Row projections and aggregate arguments run for
all WHERE-surviving input. Aggregate output projections run once for every group,
including the global group on empty input. All precede LIMIT, including LIMIT 0.

Integer primitives check overflow. A single wrapper isolates signed 128-bit SUM
accumulation and final INT64 conversion. DOUBLE accumulation preserves input
order, rejects nonfinite results, and does not use fast-math. Both executors share
the aggregate state/update primitives and preserve per-group input order.

## Batch execution

Batches carry an explicit row count, source row indices, and selection indices.
The scan's EOF signal is separate from a batch with no filter survivors.
Expression vectors own contiguous INT64/DOUBLE/byte-BOOL payloads or string views,
with validity bytes; scan views borrow the immutable table's packed validity
bitmap. Typed loops gather selected input and apply expression kernels without
calling the scalar row evaluator.
Numeric kernels stage per-lane fault flags. Consumers check those flags in input
row order, preserving precedence between an earlier numeric error and a later
materialized-row/group cap. Fault flags are separate from SQL null validity.

String views refer to immutable table values, AST literals, or completed owned
aggregate state. Completed group state stays alive until the final result sink
has copied retained strings. Hash keys and aggregate extrema use owned state at
their blocking boundary. Ordinary scan/filter/project kernels do not allocate a
boxed Value for each cell. Sorting operates on row indices, and LIMIT selects a
prefix before the shared owning result sink. This implementation makes no SIMD
or speedup claim.

## Inner hash joins

Both executors use the same hash-build algorithm and stateful probe cursor.
The hash table owns composite key Values and lists of source row indices.
The default builds the right input and probes left rows in input order; each
match list retains build input order. Null key components never match.

Scalar `next` emits one pair of source row indices. Vector `next_batch` copies
segments of matching indices into a batch and resumes its saved probe/match
offset on the next pull. One probe can therefore produce more matches than the
batch size without losing duplicates. A joined table is never materialized:
bound provenance directs each payload access to its original table and row.
The hash map is immutable during probing, so saved match-list pointers stay
valid. Sorting and final result ownership follow the existing executor paths.
Each input is pulled through a source stream that retains one set of selected
row indices. Scalar source callbacks advance one row; vector callbacks gather
and filter a typed batch. An empty selected batch does not signal EOF. Pushed
filters therefore do not require materializing an additional filtered table.

Forced build-side changes are rejected when DOUBLE SUM/AVG order or potentially
failing expressions require the default traversal. This also preserves whether
a numeric error occurs before a materialized-row/group cap. Safe data-only
COUNT/MIN/MAX and INT64 casts do not require that restriction.

## Conservative optimization

Rules run on the bound query before physical planning. Successful literal-only
subtrees may fold; a NUMERIC failure leaves the expression at its original
evaluation site. Single-input top-level WHERE conjuncts can move below the join
only when the entire WHERE expression is total. This prevents a safe sibling
from suppressing a failing conjunct, and prevents a failing predicate from
executing on unmatched input rows. Residual predicates retain bound identities.

Pruning opens only columns needed by projections, predicates, join keys, group
keys, and aggregate arguments. It reduces real scan descriptors. Both baselines
already read payloads lazily, so prune-only need not reduce payload access counts.
Automatic join-side choice uses base-table cardinality, with ties choosing the
right build; it does not estimate filtered cardinality. DOUBLE SUM/AVG and
potentially failing expressions block a swap, and EXPLAIN reports the reason.
Each rule has a switch gated by `--optimizer on`; explicit build-side requests
remain guarded physical controls. Rule counters count removed column
descriptors, moved conjuncts, folded subtrees, and safe automatic side decisions.

## Counters and timing

Successful JSON results include physical-stage input/output rows, batches,
scan columns opened, distinct source columns accessed, logical column-value
access attempts, and join build/probe/candidate rows. `values_read` includes
null checks and repeated expression accesses; it is not bytes transferred or
unique non-null cells. Different execution granularities can perform different
read counts without changing SQL results.
`scanned_rows` sums visited base rows; `filtered_rows` counts scan/join output
surviving all predicates. Duplicate join matches can therefore make the latter
larger. Join candidates are emitted equal-key pairs before a residual filter;
build/probe counts include consumed rows with null keys.

`--profile` adds steady-clock planning and execution/drain durations. Planning
includes parse/bind/optimization; execution includes setup, owning sink, and
operator teardown, but excludes catalog loading and JSON construction.
Operator timings and requested PMR allocation totals describe inclusive active
scopes, so nested scopes overlap and must not be summed. Scan timing covers
descriptor setup and row traversal; consumer scopes include payload reads.
These counters and timings describe diagnostic scopes. Ordinary benchmark
trials disable optional operator profiling while retaining the same default
counters in both executors.

## Native benchmark boundary

`quarry bench --manifest PATH --validate-only` emits complete resident and
prepared results for independent schema/value/null/multiplicity validation.
Timing mode loads the catalog once, prepares every configuration before trials,
and uses a saved-seed shuffled order for each warmup and recorded repetition.
Resident trials time prepare plus execute; prepared trials time execute with
fresh state. Both materialize the same owning Result sink.

Digest traversal, JSON rendering, record output, and result/plan destruction are
outside execution timing; rendering has its own duration. The catalog and all
cached plans remain resident for both tracks. Reported accounted peaks are
engine-lifetime high-water marks, including earlier trials, not per-query peak
deltas or process RSS. Retained results are released between trials.

The Python runner performs complete DuckDB validation before timing, freezes
source/binary/build/query/data/configuration provenance, and rejects changed
hashes afterward. A shared activity lock and process preflight prevent known
Quarry builds/tests from overlapping measurement. These controls do not provide
CPU isolation or remove thermal, scheduler, and unrelated system noise.
Reports regenerate medians, inclusive-quartile IQRs, and paired ratios from raw
records; overlapping IQRs are labeled inconclusive, not a significance test.

## Adversarial verification boundary

The core corpus contains 768 single-table and 240 joined cases with unique
hashes of their SQL and typed input content. Each runs the same 20 scalar/vector
and optimizer configurations. One stdio process handles a case's requests, but
every request executes afresh and is compared independently with DuckDB.
The verifier checks successful-case receipts against the saved content manifest.

Native fuzzing makes bounded deterministic SQL/CSV mutations. Accounted PMR
failure injection exercises every allocation prefix of selected load/execution
paths through their first successful run, then clears injection and checks
reuse. These checks cover neither every possible input nor global/runtime
allocations. Sanitizer availability, clean installation, and remote CI execution
are separate observations in VERIFICATION.md.
