# SQL subset and data contract

Current implemented scope: single-table queries or one inner equijoin, scalar or
typed batch execution, and conservative optional optimization. Prepared-query
execution and benchmark tracks use this same SQL contract. This
document describes the implemented contract; observed acceptance results belong
in VERIFICATION.md. M7–M9 add verification and measurement tooling, not a broader
SQL dialect.

## Supported shape

```sql
SELECT select_item [, select_item ...]
FROM table [AS alias]
[INNER JOIN table [AS alias]
  ON left_column = right_column [AND left_column = right_column ...]]
[WHERE predicate]
[GROUP BY column [, column ...]]
[ORDER BY output_name_or_position [ASC|DESC]
  [NULLS FIRST|NULLS LAST] [, ...]]
[LIMIT nonnegative_integer]
```

Select items support `*`, column references, explicit `AS` aliases, literals,
parentheses, unary minus, numeric `+ - * /`, supported casts, and aggregates.
Comparisons, null tests and boolean composition also work in SELECT expressions.
References may be qualified by the table name when no alias exists, or by the
declared alias when one exists; the alias hides the original qualifier.
Identifiers are ASCII and case-insensitive. Strings are
case-sensitive UTF-8, single-quoted in SQL; `''` escapes a quote. Whitespace,
`--` line comments, and one optional terminal semicolon are accepted. A FROM
clause is required; use a one-row table for constant-expression checks.
Column names and explicit output aliases are canonicalized to lowercase in
result schemas. Unaliased expressions receive generated descriptive labels;
use explicit aliases for a stable interface and positional ORDER BY when needed.
DuckDB may preserve alias spelling differently, so reference cases use matching
lowercase aliases when comparing schemas exactly.

WHERE accepts typed column/literal comparisons (`=`, `!=`, `<>`, `<`, `<=`, `>`,
`>=`), `IS NULL`, `IS NOT NULL`, and boolean composition with `AND`, `OR`, `NOT`.
Comparison operands must be columns or literals (including negative numeric
literals). Comparing the results of predicates, as in `(units = 1) = TRUE`, is
outside this subset; combine predicates with boolean operators instead.
Arithmetic, casts, and aggregates in WHERE are rejected. Binding resolves names
and types before row execution. Numeric expressions must use matching operand
types; there is no implicit cross-numeric, string, or boolean conversion.

GROUP BY accepts input column references, not output aliases or arbitrary
expressions. Keys may be INT64, BOOL, or STRING, including multiple columns.
DOUBLE grouping keys are unsupported. Nonaggregate output references must be
grouping columns; arithmetic over grouped columns is allowed. Aggregate results
may participate in arithmetic. Nested aggregates are rejected.

At most one explicit INNER JOIN is supported. Its ON clause must be a conjunction
of equalities between columns from opposite inputs. Composite INT64, BOOL, and
STRING keys require matching types; DOUBLE keys are excluded. A null in any
join-key component prevents a match. Duplicate keys preserve every matching
pair. Unqualified ambiguous column names fail binding; self-joins require
distinct aliases. `*` expands both inputs, and `alias.*` expands that input only.

The default physical join builds the right input, visits left probe rows in input
order, and emits build-side matches in input order. This accumulation policy is
common to both executors; it does not promise SQL output ordering without ORDER
BY. Explicit `--build-side left` is rejected for DOUBLE SUM/AVG and potentially
failing expressions whose reordered evaluation could change numeric-error versus
materialized-cap precedence. Data-only COUNT/MIN/MAX and INT64-to-DOUBLE casts
are total on validated input; SUM/AVG over DOUBLE remain order-sensitive.

ORDER BY accepts output names or positive one-based output positions only.
Ambiguous output names are rejected. Its default is `ASC NULLS LAST`; DESC also
defaults to NULLS LAST. NULLS FIRST and NULLS LAST are explicit alternatives.
Strings compare lexicographically by unsigned UTF-8 bytes, without locale rules.
Duplicate rows are preserved. Output order without ORDER BY and ordering within
ties are unspecified.

## Types and numeric behavior

| Expression | Return type / rule |
| --- | --- |
| Integer literal / integer column | INT64 |
| Floating literal / floating column | DOUBLE |
| Boolean / string | BOOL / STRING |
| `INT64 + - * INT64`, unary integer minus | INT64, checked overflow |
| `DOUBLE + - * DOUBLE`, unary floating minus | DOUBLE, finite result required |
| Integer or floating division | DOUBLE, matching input types; zero divisor errors |
| `CAST(integer_expression AS DOUBLE)` | DOUBLE |
| `CAST(NULL AS BIGINT/DOUBLE/BOOLEAN/VARCHAR)` | Typed NULL |
| `COUNT(*)`, `COUNT(expression)` | INT64 |
| `SUM(INT64)` | INT64, checked wide accumulation and checked final conversion |
| `SUM(DOUBLE)`, `AVG(numeric)` | DOUBLE |
| `MIN(expression)`, `MAX(expression)` | Input type |

All four types are nullable. NULL literals obtain their type from context when
unambiguous; genuinely ambiguous expressions, including a bare output NULL, are
rejected. `COUNT(NULL)`, `NULL IS NULL`, and `NULL = NULL` have unambiguous
semantics and are accepted. Arithmetic still requires resolved numeric operand
types: `(NULL + NULL) + 1` is INT64, while `(NULL / NULL) + 1.0` leaves the
division's input types ambiguous and requires explicit casts. Other casts are
unsupported. NaN/infinity are rejected in input and computed results. Numeric
overflow and division by zero are structured NUMERIC errors. NULL propagates
before payload arithmetic: an invalid placeholder payload in a null cell is not
evaluated.

Integer SUM deliberately returns INT64, unlike DuckDB's wider integer SUM.
DuckDB comparison adapters may normalize the declared return type for bounded
in-range cases, but must not hide Quarry overflow or change returned values.
DOUBLE SUM/AVG retain input accumulation order; approximate comparison is a test
policy, never approximate SQL equality.

The generated differential domain uses small integers and quarter-valued
doubles. Its DOUBLE comparator uses relative tolerance `1e-12` and absolute
tolerance `1e-10`; exact quarter-valued inputs and bounded expression sizes keep
ordinary rounding far below these thresholds. Integer/string/boolean values,
schemas, nullness, and row multiplicity compare exactly. Approximate unordered
rows are matched without losing duplicates; ordered ties compare as multisets.
Generated LIMIT cases use a unique total-order key or LIMIT 0. Targeted numeric
stress cases require independent expected values rather than relaxed tolerance.

The pinned DuckDB 1.2.2 oracle runs with one thread, NULLS LAST, and
`disabled_optimizers='compressed_materialization'`. The last setting addresses
an observed optimizer defect: on the recorded host, default DuckDB ordered
`'東京'` before `'comma,value'` while its comparisons and MIN/MAX agreed with
UTF-8 byte order. The guarded oracle executes identical SQL without rewriting
queries or post-sorting results. A two-row ASC/DESC regression compares the
guarded result and Quarry with a hand-computed reference; raw host behavior is
preserved in `evidence/m7-duckdb-utf8-order.json`.
The oracle creates explicit
typed tables from the same logical data. Declared adapters map INTEGER/BIGINT to
INT64, in-range integer SUM HUGEINT to INT64, and the oracle's DECIMAL literal
outputs to DOUBLE for supported quarter-valued literal cases. They do not admit
implicit casts into Quarry or broaden its SQL surface.

## NULL and evaluation domain

Comparison with NULL produces UNKNOWN, including `NULL = NULL`. WHERE retains
only TRUE. IS NULL and IS NOT NULL always return a non-null BOOL.

| A | B | A AND B | A OR B |
| --- | --- | --- | --- |
| TRUE | TRUE | TRUE | TRUE |
| TRUE | FALSE | FALSE | TRUE |
| TRUE | UNKNOWN | UNKNOWN | TRUE |
| FALSE | TRUE | FALSE | TRUE |
| FALSE | FALSE | FALSE | FALSE |
| FALSE | UNKNOWN | FALSE | UNKNOWN |
| UNKNOWN | TRUE | UNKNOWN | TRUE |
| UNKNOWN | FALSE | FALSE | UNKNOWN |
| UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

NOT maps TRUE to FALSE, FALSE to TRUE, and UNKNOWN to UNKNOWN. Both operands of
boolean expressions are evaluated under the restricted WHERE grammar.

COUNT(*) includes all rows; COUNT(expr) excludes null expression values.
SUM/AVG/MIN/MAX ignore NULL and return NULL if there are no non-null arguments.
A global aggregate on empty input produces one row. Grouped aggregation on empty
input produces no rows. Null keys belong to the same group.

The scalar evaluation domain is scan → filter → project, or scan → filter →
aggregate → project, followed by sort and limit. Ordinary projection expressions
and aggregate arguments are evaluated for every WHERE-surviving input row.
Aggregate result projections are evaluated once for every completed group,
including the global group on empty input. All of this precedes ORDER BY/LIMIT,
including LIMIT 0. Rejected input rows do not evaluate row projection payloads.
A small LIMIT does not suppress numeric errors or allow an intermediate result
to exceed the configured cap. Scalar and batch execution use this common domain.
Invariance covers successful results and the structured failure category. If
multiple independent numeric faults exist, the particular NUMERIC diagnostic
chosen is not an ordering guarantee; one executor may report division by zero
while another reports an independently present overflow. Batching must not
turn a failure into success or change an earlier numeric failure into a later
materialized-row/group-cap failure.

## Examples

```sql
SELECT sale_id, amount * 2.0 AS doubled
FROM sales
WHERE amount >= 50.0 AND region IS NOT NULL
ORDER BY doubled DESC NULLS LAST, sale_id ASC
LIMIT 10;

SELECT region, COUNT(*) AS orders, SUM(amount) AS revenue
FROM sales AS s
GROUP BY region
ORDER BY revenue DESC NULLS LAST, region ASC;

SELECT COUNT(amount) AS present, AVG(amount) AS mean_amount FROM sales;
```

Rejected examples include `SELECT 1` (FROM required), `SELECT DISTINCT region
FROM sales`, `WHERE amount + 1.0 > 50.0`, `WHERE CAST(sale_id AS DOUBLE) > 1.0`,
`GROUP BY amount` when amount is DOUBLE, `ORDER BY amount + 1.0`, and
`SELECT SUM(COUNT(*)) FROM sales`. Outer/cross/non-equality joins and multiple
joins are rejected.

| Feature | Current Quarry | DuckDB / compatibility |
| --- | --- | --- |
| Scalar single-table select/filter/group/sort/limit | Supported subset above | Compare same typed logical input |
| Nullable INT64, DOUBLE, BOOL, STRING | Supported | Explicit oracle types, no inference |
| Integer SUM | Checked INT64 result | DuckDB wider result is intentional difference |
| Implicit numeric casts | Rejected | Use explicit allowed cast |
| GROUP BY DOUBLE | Rejected | Outside Quarry subset |
| Default descending null order | NULLS LAST | Declare ordering explicitly in oracle cases |
| SELECT without FROM | Rejected | One-row fixture for comparison |
| Typed batch execution | Implemented; acceptance in VERIFICATION.md | Same typed values and null/evaluation semantics |
| One inner equijoin | Implemented; nullable/composite keys and duplicates | Exact subset above |
| Optimizer-on | Conservative pruning, pushdown, folding, and safe build choice | Same supported semantics; acceptance in VERIFICATION.md |
| DISTINCT, HAVING, OFFSET, subqueries, CTEs, UNION | Rejected | Outside Quarry subset |
| Windows, quoted identifiers, arbitrary functions | Rejected | Outside Quarry subset |
| Dates/timestamps, DDL, DML | Rejected | Outside Quarry subset |
| Multiple statements | Rejected | No fallback to another engine |
| Reusable prepared C++ query | Move-only handle; fresh state per execution | Same SQL contract; rejects replaced/foreign catalog |
| Native resident/prepared benchmarks | 12 frozen workloads, finite 10k/100k profiles | Internal Quarry comparison; DuckDB correctness only |
| Core differential verification | 1,008 distinct cases × 20 configurations per build | Explicit typed independent oracle plus hand cases |
| Parser/CSV fuzz and allocation injection | Bounded deterministic mutations and accounted-PMR failure prefixes | Not exhaustive, coverage-guided, or global-allocation coverage |
| Portability CI | Linux/macOS workflow configured | Hosted jobs unobserved; local evidence in VERIFICATION.md |

## Catalog and CSV

Catalogs are JSON with explicit schemas and CSV paths relative to the manifest:

```json
{"tables":[{"name":"sales","path":"sales.csv","columns":[
  {"name":"id","type":"INT64","nullable":false},
  {"name":"amount","type":"DOUBLE","nullable":true},
  {"name":"region","type":"STRING","nullable":true}
]}]}
```

CSV requires a header matching declared columns in order, case-insensitively.
Delimiter is comma; LF and CRLF records are supported. Double quotes delimit
quoted fields, doubled double quotes escape a quote, and quoted fields may
contain commas/newlines. Unquoted `\N` is NULL. Quoted `"\N"` is the string `\N`;
empty string is distinct from NULL. Nulls in nonnullable columns, duplicate
columns, wrong field counts, malformed quoting, invalid UTF-8, invalid typed
values, and numeric overflow fail loading with file/record/column diagnostics.
Loading publishes the table only after complete validation.

Numeric tokens permit no leading or trailing whitespace. Integers use signed
decimal syntax; DOUBLE uses finite decimal syntax with an optional exponent.
BOOL accepts case-insensitive `true` and `false` only, not `0`/`1`. STRING
preserves its bytes. Every field must be valid UTF-8. Duplicate table names and
duplicate column names are rejected case-insensitively.

## Errors, output, and limits

CLI JSON succeeds with `ok: true`, columns containing names and logical types,
row arrays, and allocation statistics. Every non-null INT64 is a decimal JSON
string for lossless transport; DOUBLE uses JSON numbers, BOOL JSON booleans,
STRING JSON strings, and NULL JSON null. Consumers must decode by schema.

Errors have `ok: false` and an `error` object with `code` and `message`. They do
not include successful partial rows. One-shot errors exit nonzero. A stdio
session responds to request failures and remains available for later requests.

Default limits: SQL 64 KiB, session request 128 KiB, expression depth 128, 4,096
tokens, CSV field 1 MiB, CSV record 8 MiB, manifest 1 MiB, result/intermediate
rows 100,000, and engine-accounted memory 512 MiB. Exceeding a cap errors rather
than truncating output. Catalog/session JSON nesting is limited to 128 containers
including the root, checked before DOM parsing. Accounting tracks owned table/operator/result capacities;
parser/plan/schema metadata, bounded parsing scratch, JSON DOM/rendering,
allocator bookkeeping, runtime overhead, and stack are outside this budget.
Reported peak bytes cover the engine lifetime, including loading, and are not RSS.
Where supported, JSON stats separately report `process_peak_rss_bytes` and an
explicit `rss_scope`. This is the process-lifetime high-water mark sampled through
result JSON construction, including earlier session queries and unaccounted
runtime/library allocations. It is not a per-query delta or benchmark timing.

Execution settings are separate from catalog/resource ownership: `--engine
scalar|vector` defaults to scalar, and `--batch-size` defaults to 1024 with a
valid range of 1..65536. Batch size affects the vector traversal; scalar remains
an independent row loop. `--optimizer on|off` defaults to off. With it on,
`--prune`, `--pushdown`, `--fold`, and `--join-reorder` accept `on|off` and default
to on. An explicit `--build-side auto|left|right` is a guarded physical control;
auto chooses the smaller base input only when optimization and join reordering
are enabled and order changes are safe. Ties build right.

Pruning retains all expression/key dependencies. Pushdown moves total
single-input top-level WHERE conjuncts below the inner join, but is disabled
when any WHERE subtree can fail numerically. Constant folding replaces only
successful literal-only subtrees; failed constants retain their evaluation
domain. Optimization preserves the null, multiplicity, and error-domain rules
above. Memory-budget outcomes may differ because execution settings retain
different buffers.

`--profile` adds scoped timing to result statistics. `explain --analyze` runs the
query and returns unoptimized/optimized/physical plans plus results and stats.
Operator scopes overlap and must not be summed; timing excludes loading and
JSON output. See ARCHITECTURE.md for counter definitions and accounting scope.
Session `options` may override `engine`, `batch_size`, `build_side`, `optimizer`,
`prune`, `pushdown`, `fold`, `join_reorder`, and boolean `profile` for one request.
Mode/rule values use the same strings as CLI values. Invalid options fail that
request and leave defaults unchanged.

The C++ `prepare`/`execute` API binds these same expressions once and executes
them with fresh state. There is no parameter substitution or new SQL PREPARE
syntax. Plans are move-only and specific to an engine's current catalog;
successful catalog replacement invalidates them, while a failed load preserves
them. Native benchmark resident and prepared tracks share this contract and
the same complete owning result representation.
