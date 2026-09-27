# Learning guide: execution, verification, and measurement

This guide covers the scalar/batch core, inner join, conservative optimizer,
prepared plans, and the verification/measurement boundaries. Acceptance evidence
is recorded in VERIFICATION.md and CHECKPOINT.md. Start with `build/debug/quarry demo` and
inspect its SQL and catalog in `examples/`.

## Follow one query

```sql
SELECT c.region, COUNT(*) AS orders, SUM(s.amount) AS revenue
FROM sales AS s
INNER JOIN customers AS c ON s.customer_id = c.customer_id
WHERE s.amount >= 50.0
GROUP BY c.region
ORDER BY revenue DESC NULLS LAST, region ASC
LIMIT 10;
```

The tokenizer separates identifiers, punctuation, literals, and operators. The
parser builds an expression/query tree and rejects unsupported syntax. The
binder resolves both tables, assigns stable column identifiers with table-side
provenance, checks matching INT64 join keys and the DOUBLE comparison, confirms
region is a legal grouping key, and resolves output aliases in ORDER BY.
Consequently execution uses resolved column identifiers rather than name lookup.

The default join builds a customer-key hash table, then probes sales rows; every
matching customer row contributes a pair. Scalar traversal consumes one pair
at a time; vector traversal consumes typed batches. WHERE retains TRUE only;
a null amount makes the comparison UNKNOWN and drops that pair. The hash
aggregate associates each surviving region key with COUNT and SUM state. Null
region keys share one group. Aggregate state becomes projected output rows;
sort materializes and orders them; LIMIT selects the final prefix.

Exercise: hand-calculate the output for three already-joined rows `(north, 50.0)`,
`(north, NULL)`, `(south, 70.0)`. Then change WHERE to `amount IS NULL` and explain
why the count and sum differ. Use a compact explicitly typed fixture; do not rely
on schema inference.

## Columns, nulls, and ownership

A typed numeric buffer contains payloads while a packed validity bitmap says
which values exist. A null payload is not meaningful and must not be evaluated.
BOOL is stored as a byte. Current strings own their bytes using PMR strings;
they cannot refer to the CSV reader's next reused field buffer.

Table buffers belong to the immutable catalog. Query buffers belong to query
state; result storage retains its memory resource so a result can safely outlive
the engine. Failed loading and failed execution must unwind temporary buffers.
Engine-accounted memory excludes runtime/JSON/parser overhead and is not RSS.

Exercise: load a string containing a comma, newline, doubled quote, empty value,
and literal `\N`. Explain why quoted `"\N"` differs from unquoted `\N`.

## Parsing is not binding

`SELECT absent FROM sales` can have valid grammar but fail name binding.
`SELECT amount + sale_id FROM sales` can parse yet fail because DOUBLE and INT64 do
not implicitly coerce. `SELECT amount + CAST(sale_id AS DOUBLE) FROM sales` makes
the intended conversion explicit. This separation prevents repeated name/type
checks inside execution.

Exercise: compare parse, bind, type, and numeric error responses using an
incomplete SELECT, an unknown column, mixed numeric arithmetic, and a surviving
division by zero. Re-run a valid query in the same stdio session after each.

## Aggregation and blocking work

COUNT(*) counts rows, COUNT(expr) excludes NULL, and the other aggregates ignore
null values and return NULL if none remain. A global aggregate on empty input
still yields one result; grouped aggregation has no groups. INT64 SUM uses a
checked wide accumulator but returns checked INT64, an intentional difference
from DuckDB. DOUBLE accumulation is ordered and may fail on a nonfinite result.

Hash aggregation and sort are blocking operators: they retain state before
returning the completed answer. Quarry evaluates all surviving expressions
before LIMIT, even LIMIT 0. A cap or numeric failure therefore cannot be hidden
by requesting fewer output rows.

Exercise: compare `SELECT COUNT(*), SUM(amount) FROM sales WHERE FALSE` with
the grouped equivalent. Explain their different row counts. Then construct a
division-by-zero projection on one surviving row and check LIMIT 0's behavior.

## Debugging a mismatch

1. Save SQL, exact schema and CSV, seed, engine options, EXPLAIN output, and the
   source/build fingerprint.
2. Decode JSON by its logical schema: INT64 decimal strings must remain exact.
3. Check output types, row count, nullness, and duplicate multiplicity before
   considering numerical tolerance.
4. Without ORDER BY compare multisets. With ties do not assume stable ordering.
   Make generated LIMIT cases totally ordered when comparing exact sequences.
5. Minimize the failing data/query and preserve it as a regression. Check the
   result by hand or an independent high-precision calculation where appropriate.

Never round every result to hide an error. Bounded generated tests and explicit
overflow/cancellation fixtures answer different questions. A test count does
not establish operator/edge-case coverage by itself.

## Selection vectors and typed batches

Selection vectors hold indices of rows surviving a batch filter while immutable
input buffers remain in place. Zero selected rows is a valid batch, not
end-of-stream. Expression kernels gather only selected values into typed
buffers; nullable lanes have separate validity and numeric-fault information.
The batch executor does not call the scalar expression evaluator for each row.
No SIMD claim follows merely from batching.

Group keys and aggregate extrema own retained state. A STRING expression vector
borrows its bytes from catalog data, a query literal, or completed group state.
The final sink copies retained strings before those owners disappear. Vector
sorting retains projected typed columns and sorts row indices, then applies
LIMIT to those indices. Potentially failing expressions were already evaluated
over the same input domain as scalar execution.

Exercise: generate 4,099 rows into `build/exercise` with the fixture generator.
Filter to only the first and last few sale ids. Compare ordered JSON results
using scalar and vector batch sizes 1, 7, 1,024, and 4,096. Explain why empty
interior batches cannot signal EOF and why the final partial batch cannot read
extra lanes. Then place a zero divisor on a rejected row and on a surviving row;
only the latter must fail, even with LIMIT 0.

## Duplicate-preserving joins

Inner hash joins emit every pair for duplicate matching keys:
two left rows and three right rows with the same non-null key produce six
results. Null keys never match. The hash cursor resumes a probe's matches across
output batch boundaries; it retains row indices rather than a materialized
joined table. A tiny independent nested-loop oracle checks that traversal.

Exercise: make one left row match 5,001 right rows. Compare COUNT(*) and ordered
pair identifiers across batch sizes 1, 7, and 4,096. Then add a duplicate left key
and a null right key; explain why the duplicate doubles matches and NULL adds
none. Force each safe build side and confirm the same multiset.

DOUBLE SUM/AVG may change with input order, so an unsafe left build is rejected.
Potentially failing projections/aggregate arguments also restrict swaps: a
reordered zero divisor must not cross the materialized-row/group cap and change
which structured failure occurs. Ordinary resource consumption can differ by
configuration because each algorithm retains different buffers.

## Reading an optimized plan

Run the example with `explain --engine vector --optimizer on --analyze`. The
unoptimized tree retains the full scan schema and WHERE above the join. The
optimized tree can prune unused scan descriptors and move the amount predicate
to the sales input. Bound identifiers still point to the same source columns.
DOUBLE SUM constrains the join to its original right build to preserve input
accumulation order; inspect the reported reason.

Disable one rule at a time using `--prune off`, `--pushdown off`, `--fold off`,
or `--join-reorder off`. Compare actual `columns_opened` and join
`candidate_rows`, along with the exact result. Pruning need not lower
`values_read`: both executors already avoid unused payload reads, and that
counter includes repeated accesses and null checks. A folded constant has the
same typed value, while a failing constant must stay at its evaluation site.

Exercise: add `1 + 2 AS constant` to a simple projection and inspect its folded
label. Then use `1 / 0` on a query whose WHERE rejects every row. Optimization
must preserve the empty successful result. For joins, explain why moving a
failing predicate onto an unmatched input could introduce an error. Compare
all rules together as well as individually.

Operator time and allocation scopes are inclusive and may overlap. Do not add
them to derive total query time or memory. The separate execution/drain timer
excludes loading and JSON output; it is a diagnostic, not a benchmark result.

## Reuse a plan without reusing execution state

The C++ API separates binding from execution:

```cpp
quarry::Engine engine;
engine.load_catalog("examples/catalog.json");
quarry::ExecutionOptions options;
options.engine = quarry::ExecutionMode::Vector;
options.batch_size = 7;
options.optimizer = true;
auto prepared = engine.prepare("SELECT COUNT(*) AS n FROM sales", options);
auto first = engine.execute(prepared);
auto second = engine.execute(prepared);
```

Both calls allocate fresh groups, joins, batches, counters, and owning results.
Holding `first` does not let `second` overwrite it. The prepared handle owns its
AST/plan and preserves the AST memory resource, but borrowed column references
belong to the originating catalog. A different engine, a successful catalog
replacement, or a moved-from handle fails before those references are used.
Failed loading leaves the old catalog and its plans usable. A plan may be
destroyed after its engine; execution still requires the originating live
engine. Concurrent execution and parameterized SQL are outside this API.

Exercise: compare the counters from two executions, retain the first result,
and explain which allocations survive each scope. Then trace the catalog
identity check in `src/planner/planner.cpp` and the successful publication point
in `src/storage/storage.cpp`. The native ownership tests cover these cases.

## Read the verification evidence

```sh
.venv/bin/python tools/verify.py --profile smoke
.venv/bin/python tools/verify.py --profile core
.venv/bin/python tools/clean_check.py
```

Run these sequentially. The core profile executes Debug, Release, and supported
ASan/UBSan suites. It has 768 single-table and 240 join SQL/data cases; hashes of
the actual SQL and typed data exclude repeated empty datasets from the count.
Each case has 20 engine/rule configurations, yielding 20,160 comparisons per
build. Configuration repeats and repeated builds do not create distinct cases.
Saved `cases.jsonl` and `cases-*-executed.jsonl` files make that distinction
auditable. The separately bounded extended profile contains 2,016 cases.

The oracle uses pinned DuckDB with explicit schemas/inserts, one thread, and a
targeted `compressed_materialization` optimizer disable. This setting corrects a
demonstrated UTF-8 sorting defect without changing the SQL. Read the two-row
regression and its raw/adapted/hand-expected evidence before treating any
reference engine as infallible. Schema, discrete values, nulls, and duplicates
remain exact; only bounded DOUBLE outputs use the documented tolerance.

Native mutation fuzzing runs 512 SQL and 512 CSV mutations by default. Python
core checks 128 distinct SQL mutations in four execution settings plus 48 CSV
byte mutations, including recovery requests. These finite seeded checks are
not coverage-guided or exhaustive fuzzing. Hypothesis properties provide
separate bounded generation and shrinking. PMR injection covers allocation
prefixes of selected paths, not every global allocation.

Inspect exit codes, source-before/source-after hashes, actual case receipts,
and sanitizer availability. A configured Linux/macOS workflow is not evidence
that its remote jobs ran. On the recorded Darwin runtime LeakSanitizer is
unavailable; ASan and UBSan are separate checks. The clean-check command creates
a fresh local source copy and environment, invokes the documented bootstrap,
then builds/installs Release and exercises the installed CLI/library consumer.

## Measure the intended scope

The study declares 12 original retail workloads, 10,000- and 100,000-row
profiles, and 56 configurations per profile. Every configuration uses the same
column storage, hash algorithms, right-side join build, owning result sink,
single thread, and disabled optional profiling. Compare scalar/vector with
optimizer settings fixed, optimizer off/on within an executor, and selected
batch sizes with other options fixed. The million-row profile remains disabled.

For a validation-only example:

```sh
.venv/bin/python tools/generate_benchmarks.py --rows 10000 --output build/study-10000
.venv/bin/python tools/benchmark.py --manifest build/study-10000/manifest.json \
  --binary build/release/quarry --output reports/benchmarks/validation-10000
```

Output directories must be new. Measurement additionally requires `--measure`
and `--verification` pointing to a passing, matching final core summary.
The complete study and report commands are in BENCHMARKS.md. Never overlap
measurements with builds, tests, or another benchmark. The scripts take a shared
activity lock and inspect conflicting processes; machine noise remains a limit.

Resident trials time parse/bind/plan plus execution through the complete owning
Result. Prepared trials execute an existing plan with fresh operator state.
Loading and initial preparation are reported separately. Digest traversal,
JSON rendering, record output, and destruction sit outside execution time;
rendering has its own measurement. The complete results are independently
validated before any timing; a digest alone cannot establish correctness.

Two warmups and seven recorded repetitions use a saved-seed shuffled schedule.
Reports regenerate medians, inclusive-quartile IQRs, and paired ratios from raw
JSONL, retaining slowdowns and overlapping-IQR cases. IQR overlap is a descriptive
inconclusive label, not a statistical significance test. Allocation peaks cover
the engine lifetime, including catalog/plans and earlier trials, rather than a
per-trial memory delta. DuckDB supplies correctness checks, not comparative
performance timings.

Exercise: choose one scan, one high-cardinality group, and one join. Explain the
result sink's cost, inspect all seven measurements, and compare both tracks.
Use counters and the actual plans to explain a difference without claiming that
timing alone proves a CPU-cache or SIMD mechanism. Any later timed-code, build
flag, query, or data change invalidates the affected measurements.
