"""Independent DuckDB oracle, lossless protocol decoding, and tie-safe comparison.

Generated values are bounded to small integers and quarter-valued doubles.
The 1e-12 relative / 1e-10 absolute tolerance covers normal summation/division
roundoff, while exact SQL comparisons and integer/string/bool/null checks remain
exact. Approximate matching uses a multiplicity-preserving bipartite match.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BINARY = Path(os.environ.get("QUARRY_BINARY", ROOT / "build/debug/quarry"))
DUCKDB_VERSION = "1.2.2"
DUCKDB_SETTINGS = {"threads": 1, "default_null_order": "NULLS_LAST",
                   "disabled_optimizers": "compressed_materialization"}
ABS_TOL = 1e-10
REL_TOL = 1e-12
BATCH_SIZES = (1, 7, 256, 1024, 4096)


def execution_modes():
    """Scalar and every batch size, with all optimizer rules disabled/enabled."""
    modes = []
    for optimizer in ("off", "on"):
        modes.append((f"scalar-{optimizer}", ("--engine", "scalar", "--optimizer", optimizer)))
        modes += [(f"vector-{size}-{optimizer}", ("--engine", "vector", "--batch-size", str(size),
                                                "--optimizer", optimizer)) for size in BATCH_SIZES]
    return modes


def verification_modes():
    """Every generated case also checks each rule alone in both executors."""
    modes = execution_modes()
    rules = ("prune", "pushdown", "fold", "join-reorder")
    for rule in rules:
        flags = ("--optimizer", "on", *[part for name in rules for part in
                 ("--" + name, "on" if name == rule else "off")])
        modes.append((f"scalar-only-{rule}", ("--engine", "scalar", *flags)))
        modes.append((f"vector-7-only-{rule}", ("--engine", "vector", "--batch-size", "7", *flags)))
    return modes


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool = True


SCHEMA = [Column("id", "INT64", False), Column("k", "INT64"),
          Column("n", "INT64"), Column("d", "DOUBLE"),
          Column("b", "BOOL"), Column("s", "STRING")]


def encode_field(value: object) -> str:
    if value is None:
        return "\\N"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace('"', '""') + '"'
    return str(value)


def write_catalog(path: Path, rows: list, columns: list[Column] = SCHEMA,
                  name: str = "items", newline: str = "\n") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    content = [",".join(c.name for c in columns)]
    content += [",".join(encode_field(value) for value in row) for row in rows]
    (path / "data.csv").write_bytes((newline.join(content) + newline).encode())
    catalog = {"tables": [{"name": name, "path": "data.csv",
                           "columns": [vars(c) for c in columns]}]}
    target = path / "catalog.json"
    target.write_text(json.dumps(catalog, ensure_ascii=False))
    return target


def write_multi_catalog(path: Path, tables: dict[str, tuple[list[Column], list]]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    definitions = []
    for name, (columns, rows) in tables.items():
        filename = name + ".csv"
        lines = [",".join(column.name for column in columns)]
        lines += [",".join(encode_field(value) for value in row) for row in rows]
        (path / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")
        definitions.append({"name": name, "path": filename, "columns": [vars(column) for column in columns]})
    target = path / "catalog.json"
    target.write_text(json.dumps({"tables": definitions}, ensure_ascii=False))
    return target


def run_query(catalog: Path, sql: str, *options: str) -> tuple[subprocess.CompletedProcess, dict]:
    proc = subprocess.run([str(BINARY), "query", "--catalog", str(catalog),
                           "--sql", sql, "--format", "json", *options],
                          capture_output=True, text=True, timeout=30)
    try:
        payload = json.loads(proc.stdout)
    except ValueError as exc:
        raise AssertionError(f"Invalid CLI JSON: exit={proc.returncode}; "
                             f"stdout={proc.stdout!r}; stderr={proc.stderr!r}") from exc
    return proc, payload


def quarry_result(catalog: Path, sql: str, *options: str) -> dict:
    proc, payload = run_query(catalog, sql, *options)
    assert proc.returncode == 0 and payload.get("ok") is True, (sql, proc, payload)
    assert isinstance(payload.get("stats", {}).get("peak_accounted_bytes"), int), payload
    return decode_result(payload)


def request_options(flags: tuple[str, ...]) -> dict:
    """Translate test-owned CLI options into the documented session schema."""
    result = {}
    parts = iter(flags)
    for flag in parts:
        name = flag.removeprefix("--").replace("-", "_")
        value = True if name == "profile" else next(parts)
        result[name] = int(value) if name == "batch_size" else value
    return result


def run_session(catalog: Path, requests: list[dict | str], *defaults: str):
    lines = [request if isinstance(request, str) else json.dumps(request) for request in requests]
    proc = subprocess.run([str(BINARY), "session", "--stdio", "--catalog", str(catalog), *defaults],
                          input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert not proc.stderr, proc.stderr
    try:
        responses = [json.loads(line) for line in proc.stdout.splitlines()]
    except ValueError as error:
        raise AssertionError(f"Invalid session JSON: {proc.stdout!r}") from error
    assert len(responses) == len(requests), (len(responses), len(requests), proc.stdout)
    return responses


def mode_responses(catalog: Path, sql: str, modes: list):
    """One process/catalog per case, fresh independent execution per request."""
    requests = [{"id": name, "sql": sql, "options": request_options(options)} for name, options in modes]
    responses = run_session(catalog, requests)
    for (name, _), response in zip(modes, responses):
        assert response.get("id") == name, response
    return responses


def decode_result(payload: dict) -> dict:
    columns = payload["columns"]
    assert isinstance(columns, list) and all(isinstance(c, dict) and
        isinstance(c.get("name"), str) and c.get("type") in {"INT64", "DOUBLE", "BOOL", "STRING"}
        for c in columns), "invalid result schema"
    assert isinstance(payload["rows"], list), "rows must be an array"
    decoded = []
    for row in payload["rows"]:
        assert isinstance(row, list), "row must be an array"
        assert len(row) == len(columns), "row width differs from schema"
        output = []
        for value, column in zip(row, columns):
            kind = column["type"]
            if value is None:
                output.append(None)
            elif kind == "INT64":
                assert isinstance(value, str), "INT64 must be a decimal JSON string"
                assert value == str(int(value)), "INT64 must be canonical decimal"
                integer = int(value)
                assert -(2**63) <= integer < 2**63, "INT64 out of range"
                output.append(integer)
            elif kind == "DOUBLE":
                assert type(value) in (float, int) and math.isfinite(value)
                output.append(float(value))
            elif kind == "BOOL":
                assert type(value) is bool
                output.append(value)
            elif kind == "STRING":
                assert isinstance(value, str)
                output.append(value)
            else:
                raise AssertionError(f"Unknown type {kind}")
        decoded.append(output)
    return {"columns": columns, "rows": decoded}


def duckdb_result(rows: list, columns: list[Column], sql: str) -> dict:
    return duckdb_multi_result({"items": (columns, rows)}, sql)


def duckdb_multi_result(tables: dict[str, tuple[list[Column], list]], sql: str) -> dict:
    import duckdb

    assert duckdb.__version__ == DUCKDB_VERSION, "Run the pinned bootstrap"
    types = {"INT64": "BIGINT", "DOUBLE": "DOUBLE", "BOOL": "BOOLEAN", "STRING": "VARCHAR"}
    output_types = {"BIGINT": "INT64", "INTEGER": "INT64", "DOUBLE": "DOUBLE", "BOOLEAN": "BOOL", "VARCHAR": "STRING"}
    with duckdb.connect(":memory:") as conn:
        conn.execute("SET threads=1")
        conn.execute("SET default_null_order='NULLS_LAST'")
        # Pinned 1.2.2 can order compressed UTF-8 strings incorrectly. Disabling
        # this one oracle optimization executes identical SQL with byte order;
        # raw/adapted/hand-expected evidence lives in the oracle regression.
        conn.execute("SET disabled_optimizers='compressed_materialization'")
        for name, (columns, rows) in tables.items():
            conn.execute(f'CREATE TABLE "{name}" (' + ",".join(
                f'"{c.name}" {types[c.type]}' + ("" if c.nullable else " NOT NULL")
                for c in columns) + ")")
            if rows:
                conn.executemany(f'INSERT INTO "{name}" VALUES (' + ",".join("?" for _ in columns) + ")", rows)
        result = conn.sql(sql)
        # DuckDB 1.2 DB-API description exposes broad NUMBER/STRING categories;
        # relation.types retains exact BIGINT/DOUBLE/BOOLEAN/VARCHAR domains.
        description = list(zip(result.columns, result.types))
        values = result.fetchall()
    schema = []
    for index, (name, kind, *_) in enumerate(description):
        kind = str(kind)
        if kind == "HUGEINT":
            # Declared difference: DuckDB SUM(BIGINT) is wide; Quarry is INT64.
            # Every generated result is checked in range; overflow is tested
            # independently as Quarry NUMERIC, never hidden by this adapter.
            assert all(row[index] is None or -(2**63) <= row[index] < 2**63 for row in values)
            logical = "INT64"
        elif kind.startswith("DECIMAL("):
            # Quarry's decimal-point literals are DOUBLE, whereas DuckDB uses
            # DECIMAL for bare literals. Generated literal outputs are exact
            # quarters. No DECIMAL column/arithmetic dialect is supported.
            logical = "DOUBLE"
        else:
            assert kind in output_types, f"Unadapted oracle type {kind}"
            logical = output_types[kind]
        schema.append({"name": name, "type": logical})
    return {"columns": schema, "rows": [
        [float(value) if value is not None and schema[i]["type"] == "DOUBLE" else value
         for i, value in enumerate(row)] for row in values]}


def cells_equal(left: Any, right: Any, kind: str) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if kind == "DOUBLE":
        return type(left) in (float, int) and type(right) in (float, int) and math.isfinite(left) and math.isfinite(right) and math.isclose(
            left, right, rel_tol=REL_TOL, abs_tol=ABS_TOL)
    return type(left) is type(right) and left == right


def same_row(left: list, right: list, schema: list[dict]) -> bool:
    return len(left) == len(right) == len(schema) and all(
        cells_equal(a, b, column["type"]) for a, b, column in zip(left, right, schema))


def compare_multiset(actual: list, expected: list, schema: list[dict]) -> None:
    assert len(actual) == len(expected), "row count / duplicate multiplicity differs"
    # Exact multisets avoid deep augmenting paths for thousands of duplicate
    # discrete rows. Approximate DOUBLE matching still uses a complete matching,
    # never greedy removal of exact pairs, which could steal a necessary match.
    def exact_counts(rows):
        assert all(len(row) == len(schema) for row in rows), "row width differs from schema"
        for row in rows:
            for value, column in zip(row, schema):
                if value is not None and column["type"] == "DOUBLE":
                    assert type(value) in (int, float) and math.isfinite(value), "invalid DOUBLE"
        return Counter(tuple((type(value).__name__, value) for value in row) for row in rows)

    left_counts, right_counts = exact_counts(actual), exact_counts(expected)
    if left_counts == right_counts:
        return
    if all(column["type"] != "DOUBLE" for column in schema):
        raise AssertionError("exact discrete multiset differs")
    matched: dict[int, int] = {}

    def augment(index: int, visited: set[int]) -> bool:
        for target, row in enumerate(expected):
            if target in visited or not same_row(actual[index], row, schema):
                continue
            visited.add(target)
            if target not in matched or augment(matched[target], visited):
                matched[target] = index
                return True
        return False

    for index in range(len(actual)):
        assert augment(index, set()), f"No multiplicity-preserving match for {actual[index]!r}; expected={expected!r}"


def compare_results(actual: dict, expected: dict, order_keys: tuple[int, ...] = ()) -> None:
    assert actual["columns"] == expected["columns"], "output schema/name/order differs"
    schema = actual["columns"]
    left, right = actual["rows"], expected["rows"]
    assert len(left) == len(right), "row count / duplicate multiplicity differs"
    if not order_keys:
        compare_multiset(left, right, schema)
        return
    # The oracle defines key-group sequence; within an SQL tie, row order is free.
    cursor = 0
    previous_expected_key = previous_actual_key = None
    while cursor < len(right):
        end = cursor + 1
        key = tuple(right[cursor][k] for k in order_keys)
        while end < len(right) and tuple(right[end][k] for k in order_keys) == key:
            end += 1
        compare_multiset(left[cursor:end], right[cursor:end], schema)
        actual_key = tuple(left[cursor][k] for k in order_keys)
        assert all(tuple(row[k] for k in order_keys) == actual_key for row in left[cursor:end]), "ordered tie split"
        if previous_expected_key is not None:
            for old, new, actual_old, actual_new in zip(previous_expected_key, key, previous_actual_key, actual_key):
                if old == new:
                    assert actual_old == actual_new, "earlier ORDER BY key changed within a tie"
                    continue
                if old is not None and new is not None:
                    assert actual_old != actual_new and (actual_old < actual_new) == (old < new), "ORDER BY key direction differs"
                break
        previous_expected_key, previous_actual_key = key, actual_key
        cursor = end


def generated_rows(seed: int) -> list:
    rng = random.Random(712367 + seed)
    size = [0, 1, 2, 7, 19, 33, 47, 64, 9, 27][seed % 10]
    strings = [None, "", "North", "south", "\\N", "café", "東京", "comma,value",
               'quote"value', "line\nbreak", "x" * 257, "O'Brien"]
    return [[i, rng.choice([None, -1, 0, 0, 0, 1, 2]),
             rng.choice([None, -30, -7, -1, 0, 0, 1, 2, 13, 30]),
             rng.choice([None, -7.5, -0.25, 0.0, 0.25, 1.5, 23.75]),
             rng.choice([None, False, True]), rng.choice(strings)] for i in range(size)]


QUERIES: list[tuple[str, tuple[int, ...]]] = [
    ("SELECT * FROM items", ()),
    ("SELECT q.id AS id, q.n AS n, q.s AS s, q.d AS d, q.b AS b FROM items AS q", ()),
    ("SELECT id, (n + 3) * 2 AS arithmetic, -n AS negative, n / 3 AS divided FROM items", ()),
    ("SELECT id, d + 1.25 AS plus, d - 2.5 AS minus, -d * 2.0 / 3.0 AS mixed FROM items", ()),
    ("SELECT id, CAST(n AS DOUBLE) AS converted, n / n AS ratio FROM items WHERE n <> 0", ()),
    ("SELECT id, n + NULL AS null_integer, CAST(NULL AS DOUBLE) AS null_double, CAST(NULL AS BOOLEAN) AS null_bool, CAST(NULL AS VARCHAR) AS null_string FROM items", ()),
    ("SELECT id, n FROM items WHERE (n >= -7 AND n < 13) OR NOT (k = 0 OR k IS NULL)", ()),
    ("SELECT id, s FROM items WHERE s >= 'North' AND s <> 'O''Brien'", ()),
    ("SELECT id, b AND (n > 0) AS both, b OR (n = 0) AS either, NOT b AS opposite FROM items", ()),
    ("SELECT id, n IS NULL AS null_n, s IS NOT NULL AS present_s FROM items WHERE b IS NULL OR b = TRUE", ()),
    ("SELECT COUNT(*) AS rows, COUNT(n) AS count_n, SUM(n) AS sum_n, AVG(n) AS avg_n, MIN(n) AS min_n, MAX(n) AS max_n, SUM(d) AS sum_d, AVG(d) AS avg_d, MIN(s) AS min_s, MAX(s) AS max_s, MIN(b) AS min_b, MAX(b) AS max_b FROM items", ()),
    ("SELECT k, COUNT(*) AS rows, COUNT(d) AS values_d, SUM(n) AS sum_n, AVG(d) AS avg_d FROM items GROUP BY k ORDER BY k ASC NULLS FIRST", (0,)),
    ("SELECT k, b, s, COUNT(*) AS rows, SUM(n) AS sum_n FROM items GROUP BY k, b, s ORDER BY k ASC NULLS LAST, b DESC NULLS FIRST, s ASC NULLS LAST", (0, 1, 2)),
    ("SELECT k, SUM(n * 2 + 1) AS adjusted, AVG(CAST(n AS DOUBLE) / 3.0) AS mean_adjusted, COUNT(n + NULL) AS no_values FROM items GROUP BY k", ()),
    ("SELECT COUNT(*) AS rows, COUNT(n) AS count_n, SUM(n) AS sum_n, AVG(d) AS avg_d, MIN(s) AS min_s, MAX(b) AS max_b FROM items WHERE id < 0", ()),
    ("SELECT k, COUNT(*) AS rows FROM items WHERE id < 0 GROUP BY k", ()),
    ("SELECT k, SUM(d) AS sum_d, COUNT(*) AS rows FROM items WHERE b OR n IS NULL GROUP BY k ORDER BY sum_d DESC NULLS FIRST, k DESC NULLS LAST", (1, 0)),
    ("SELECT id, n, s, b FROM items ORDER BY 2 DESC NULLS LAST, 3 ASC NULLS FIRST, 4 DESC NULLS FIRST, 1 ASC", (1, 2, 3, 0)),
    ("SELECT id, s FROM items ORDER BY id DESC LIMIT 5", (0,)),
    ("SELECT id, 'O''Brien' AS literal_s, TRUE AS literal_b, 42 AS literal_n, 1.25 AS literal_d FROM items ORDER BY id LIMIT 0", (0,)),
    ("-- tokenizer comment\n SeLeCt Q.ID AS ident, Q.S AS text_value FrOm ITEMS AS Q WhErE Q.N != 0 ORDER BY ident; -- ending", (0,)),
    ("SELECT id FROM items WHERE (b OR NULL) AND NOT (FALSE AND b)", ()),
    ("SELECT k AS category, COUNT(*) AS orders FROM items GROUP BY k ORDER BY orders DESC", (1,)),
    ("SELECT s, b, n FROM items WHERE id >= 0 ORDER BY s ASC NULLS LAST", (0,)),
]


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    for base in ("include", "src", "tests", "tools", "benchmarks", ".github", "examples"):
        for path in sorted((ROOT / base).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes())
    for name in ("CMakeLists.txt", "CMakePresets.json", "pytest.ini", "requirements-dev.lock", "dependencies.lock.json"):
        path = ROOT / name
        if path.exists():
            digest.update(name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def save_failure(case: str, catalog: Path, sql: str, seed: int, actual: object, expected: object,
                 options: tuple[str, ...] = ()) -> Path:
    destination = ROOT / "build/verification/failures" / case
    destination.mkdir(parents=True, exist_ok=True)
    names = ["catalog.json"] + [table["path"] for table in json.loads(catalog.read_text())["tables"]]
    for name in names:
        (destination / name).parent.mkdir(parents=True, exist_ok=True)
        (destination / name).write_bytes((catalog.parent / name).read_bytes())
    (destination / "query.sql").write_text(sql + "\n")
    try:
        plan = subprocess.run([str(BINARY), "explain", "--catalog", str(catalog), "--sql", sql, *options],
                              capture_output=True, text=True, timeout=10)
        plan_evidence = {"exit_code": plan.returncode, "stdout": plan.stdout, "stderr": plan.stderr}
    except Exception as error:
        plan_evidence = {"error": str(error)}
    evidence = {"seed": seed, "actual": actual, "expected": expected,
                "options": list(options), "binary": str(BINARY),
                "binary_sha256": hashlib.sha256(BINARY.read_bytes()).hexdigest() if BINARY.exists() else None,
                "source_fingerprint": source_fingerprint(), "plan": plan_evidence,
                "duckdb": DUCKDB_VERSION, "duckdb_threads": 1, "duckdb_settings": DUCKDB_SETTINGS,
                "abs_tolerance": ABS_TOL, "relative_tolerance": REL_TOL}
    (destination / "failure.json").write_text(json.dumps(evidence, indent=2, default=str))
    return destination
