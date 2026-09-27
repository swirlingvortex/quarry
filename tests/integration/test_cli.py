"""Hand-computed, protocol, ingestion, rejection, and resource-limit gates."""
from __future__ import annotations

import hashlib
from decimal import Decimal
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "differential"))
from harness import (BINARY, ROOT, Column, compare_results, generated_rows,
                     quarry_result, run_query, write_catalog)


def assert_error(catalog, sql, code, *options):
    proc, payload = run_query(catalog, sql, *options)
    assert proc.returncode != 0, payload
    assert payload.get("ok") is False, payload
    assert payload["error"]["code"] == code, payload
    assert isinstance(payload["error"]["message"], str) and payload["error"]["message"], payload
    assert "rows" not in payload, "failed queries must never return partial success rows"
    return payload


@pytest.fixture
def one(tmp_path):
    return write_catalog(tmp_path, [[1, 2, True, "value"]],
                         [Column("id", "INT64", False), Column("n", "INT64"),
                          Column("b", "BOOL"), Column("s", "STRING")])


def test_int64_json_exactness_and_csv_null_empty_distinction(tmp_path):
    rows = [[2**63 - 1, ""], [-(2**63), None], [0, "\\N"], [7, 'quote"comma,\nnewline']]
    schema = [Column("n", "INT64"), Column("s", "STRING")]
    catalog = write_catalog(tmp_path, rows, schema, newline="\r\n")
    result = quarry_result(catalog, "SELECT * FROM items")
    assert result == {"columns": [{"name": "n", "type": "INT64"}, {"name": "s", "type": "STRING"}], "rows": rows}


def test_complete_boolean_truth_tables_hand_computed(tmp_path):
    values = [False, True, None]
    rows = [[i, a, b] for i, (a, b) in enumerate(itertools.product(values, repeat=2))]
    schema = [Column("id", "INT64", False), Column("a", "BOOL"), Column("b", "BOOL")]
    catalog = write_catalog(tmp_path, rows, schema)
    expected = []
    for i, a, b in rows:
        conjunction = False if a is False or b is False else (None if a is None or b is None else True)
        disjunction = True if a is True or b is True else (None if a is None or b is None else False)
        expected.append([i, conjunction, disjunction, None if a is None else not a])
    result = quarry_result(catalog, "SELECT id, a AND b AS both, a OR b AS either, NOT a AS opposite FROM items ORDER BY id")
    assert result["rows"] == expected
    assert quarry_result(catalog, "SELECT id FROM items WHERE a = NULL")["rows"] == []


def test_hand_aggregation_duplicates_nulls_and_group_expression(tmp_path):
    rows = [[1, 2, "a", True], [1, None, "a", None], [None, 4, "", False],
            [None, 4, "", False], [2, None, None, None]]
    schema = [Column("k", "INT64"), Column("n", "INT64"), Column("s", "STRING"), Column("b", "BOOL")]
    catalog = write_catalog(tmp_path, rows, schema)
    result = quarry_result(catalog, "SELECT k + 1 AS key_plus, COUNT(*) AS rows, COUNT(n) AS values_n, SUM(n) + 1 AS total_plus, AVG(n) AS mean_n, MIN(s) AS min_s, MAX(b) AS max_b FROM items GROUP BY k ORDER BY key_plus NULLS FIRST")
    assert result["rows"] == [[None, 2, 2, 9, 4.0, "", False], [2, 2, 1, 3, 2.0, "a", True], [3, 1, 0, None, None, None, None]]
    assert quarry_result(catalog, "SELECT n FROM items WHERE k IS NULL")["rows"] == [[4], [4]]
    assert quarry_result(catalog, "SELECT COUNT(NULL) AS empty_count FROM items")["rows"] == [[0]]


def test_empty_global_and_grouped_aggregates(tmp_path):
    catalog = write_catalog(tmp_path, [], [Column("k", "INT64"), Column("n", "INT64"), Column("b", "BOOL"), Column("s", "STRING")])
    assert quarry_result(catalog, "SELECT COUNT(*) AS rows, COUNT(n) AS values_n, SUM(n) AS total, AVG(n) AS mean, MIN(b) AS min_b, MAX(s) AS max_s FROM items")["rows"] == [[0, 0, None, None, None, None]]
    assert quarry_result(catalog, "SELECT k, COUNT(*) AS rows FROM items GROUP BY k")["rows"] == []


def test_sum_wide_intermediate_and_checked_final(tmp_path):
    schema = [Column("n", "INT64")]
    catalog = write_catalog(tmp_path, [[2**63 - 1], [2**63 - 1], [-(2**63 - 1)]], schema)
    assert quarry_result(catalog, "SELECT SUM(n) AS total FROM items")["rows"] == [[2**63 - 1]]
    catalog = write_catalog(tmp_path, [[2**63 - 1], [1]], schema)
    assert_error(catalog, "SELECT SUM(n) AS total FROM items", "NUMERIC")


@pytest.mark.parametrize("expression", ["9223372036854775807 + 1", "-9223372036854775808 - 1", "9223372036854775807 * 2", "-(-9223372036854775808)", "1 / 0", "1.0 / 0.0", "1e308 * 1e308"])
def test_checked_numeric_errors_even_with_limit_zero(one, expression):
    assert_error(one, f"SELECT {expression} AS bad FROM items LIMIT 0", "NUMERIC")


def test_filter_masks_failing_projection_and_null_propagates(one):
    assert quarry_result(one, "SELECT 1 / 0 AS bad FROM items WHERE id < 0")["rows"] == []
    assert quarry_result(one, "SELECT CAST(NULL AS BIGINT) / 0 AS n, CAST(NULL AS DOUBLE) * 1e308 AS d FROM items")["rows"] == [[None, None]]


def test_nonfinite_double_aggregation(tmp_path):
    catalog = write_catalog(tmp_path, [[1e308], [1e308]], [Column("d", "DOUBLE")])
    assert_error(catalog, "SELECT SUM(d) AS bad FROM items", "NUMERIC")


def test_int64_sum_cancellation_high_precision(tmp_path):
    # Python's unbounded integer is an independent exact reference, not DuckDB.
    values = [2**63 - 1, -(2**63), 17, -16]
    catalog = write_catalog(tmp_path, [[n] for n in values], [Column("n", "INT64")])
    assert quarry_result(catalog, "SELECT SUM(n) AS total FROM items")["rows"] == [[sum(values)]]


def test_double_cancellation_preserves_declared_input_order(tmp_path):
    values = [1e16, 1.0, -1e16]
    exact = sum(Decimal(str(value)) for value in values)
    ordered_binary64 = 0.0
    for value in values:
        ordered_binary64 += value
    # The high-precision sum is 1. The declared ordinary binary64 input-order
    # accumulation loses that unit and gives 0; no compensated-sum claim is made.
    assert exact == Decimal(1) and ordered_binary64 == 0.0
    catalog = write_catalog(tmp_path, [[value] for value in values], [Column("d", "DOUBLE")])
    assert quarry_result(catalog, "SELECT SUM(d) AS total, AVG(d) AS mean FROM items")["rows"] == [[ordered_binary64, ordered_binary64 / len(values)]]


def test_group_without_aggregate_and_default_desc_null_order(tmp_path):
    catalog = write_catalog(tmp_path, [[None], [2], [1], [2], [None]], [Column("k", "INT64")])
    assert quarry_result(catalog, "SELECT k FROM items GROUP BY k ORDER BY k DESC")["rows"] == [[2], [1], [None]]


def test_unordered_limit_membership_and_cardinality(tmp_path):
    rows = [[1], [1], [2], [3]]
    catalog = write_catalog(tmp_path, rows, [Column("n", "INT64")])
    result = quarry_result(catalog, "SELECT n FROM items LIMIT 3")["rows"]
    assert len(result) == 3
    available = [row[:] for row in rows]
    for row in result:
        assert row in available
        available.remove(row)


@pytest.mark.parametrize("sql", [
    "SELECT DISTINCT id FROM items", "SELECT id FROM items HAVING id > 0",
    "SELECT id FROM items OFFSET 1", "SELECT id FROM items UNION SELECT id FROM items",
    "SELECT id FROM (SELECT id FROM items)", "WITH x AS (SELECT id FROM items) SELECT id FROM x",
    "SELECT ROW_NUMBER() OVER () FROM items", 'SELECT "id" FROM items',
    "SELECT ABS(n) FROM items", "CREATE TABLE x (n BIGINT)", "DELETE FROM items",
    "SELECT items.id FROM items INNER JOIN items AS q ON items.id = q.id INNER JOIN items AS r ON q.id = r.id",
    "SELECT id FROM items CROSS JOIN items AS q", "SELECT id FROM items LEFT JOIN items AS q ON items.id = q.id",
])
def test_out_of_scope_sql_rejected_structurally(one, sql):
    proc, payload = run_query(one, sql)
    assert proc.returncode != 0 and payload.get("ok") is False, payload
    assert payload["error"]["code"] in {"PARSE", "UNSUPPORTED"}, payload
    assert "rows" not in payload


@pytest.mark.parametrize(("sql", "code"), [
    ("SELECT missing FROM items", "BIND"),
    ("SELECT id FROM absent", "BIND"),
    ("SELECT q.id FROM items", "BIND"),
    ("SELECT id AS x, n AS x FROM items ORDER BY x", "BIND"),
    ("SELECT id FROM items ORDER BY 0", "PARSE"),
    ("SELECT id FROM items ORDER BY n", "BIND"),
    ("SELECT id, SUM(n) AS total FROM items", "BIND"),
    ("SELECT SUM(SUM(n)) AS nested FROM items", "BIND"),
    ("SELECT n + 1.0 AS mixed FROM items", "TYPE"),
    ("SELECT s + s AS bad FROM items", "TYPE"),
    ("SELECT n FROM items WHERE n = 1.0", "TYPE"),
    ("SELECT NULL FROM items", "TYPE"),
    ("SELECT SUM(NULL) FROM items", "TYPE"),
    ("SELECT MIN(NULL) FROM items", "TYPE"),
    ("SELECT CAST(s AS BIGINT) FROM items", "TYPE"),
    ("SELECT id FROM items GROUP BY b + 1", "BIND"),
    ("SELECT id FROM items WHERE n + 1 > 0", "UNSUPPORTED"),
    ("SELECT id FROM items WHERE CAST(n AS DOUBLE) > 0.0", "UNSUPPORTED"),
    ("SELECT id FROM items; SELECT id FROM items", "UNSUPPORTED"),
])
def test_binding_types_and_parser_errors(one, sql, code):
    assert_error(one, sql, code)


@pytest.mark.parametrize("predicate", ["(n = 1) = (n = 2)", "b = (n > 1)",
                                        "(NOT b) = TRUE", "(b IS NULL) = TRUE"])
def test_where_comparisons_require_column_or_literal_operands(one, predicate):
    assert_error(one, f"SELECT id FROM items WHERE {predicate}", "UNSUPPORTED")


@pytest.mark.parametrize(("predicate", "rows"), [("b", [[1]]), ("TRUE", [[1]]), ("NULL", []),
                                                  ("(n) > (-1)", [[1]])])
def test_where_boolean_atoms_and_signed_literals(one, predicate, rows):
    assert quarry_result(one, f"SELECT id FROM items WHERE {predicate}")["rows"] == rows


def test_double_grouping_keys_rejected(tmp_path):
    catalog = write_catalog(tmp_path, [[1.5]], [Column("d", "DOUBLE")])
    assert_error(catalog, "SELECT d, COUNT(*) AS n FROM items GROUP BY d", "TYPE")


@pytest.mark.parametrize(("kind", "body"), [
    ("INT64", b"n\n9223372036854775808\n"), ("INT64", b"n\n 1\n"),
    ("INT64", b'n\n"\\N"\n'), ("INT64", b"n\n\xff\n"),
    ("DOUBLE", b"n\nNaN\n"), ("DOUBLE", b"n\ninf\n"),
    ("BOOL", b"n\n1\n"), ("STRING", b'n\n"unclosed\n'),
    ("STRING", b'n\n"value"junk\n'), ("STRING", b"n\na,b\n"),
    ("STRING", b"n\n\xc0\x80\n"), ("STRING", b"wrong\nx\n"),
])
def test_malformed_csv_has_structured_diagnostics(tmp_path, kind, body):
    catalog = write_catalog(tmp_path, [], [Column("n", kind)])
    (tmp_path / "data.csv").write_bytes(body)
    payload = assert_error(catalog, "SELECT * FROM items", "CSV")
    message = payload["error"]["message"].lower()
    assert "data.csv" in message, payload
    assert "record" in message, payload
    assert "column" in message, payload


def test_csv_boolean_policy_and_case_insensitive_header(tmp_path):
    catalog = write_catalog(tmp_path, [], [Column("n", "BOOL")])
    (tmp_path / "data.csv").write_text("N\nTRUE\nfalse\nFaLsE\n\\N\n")
    assert quarry_result(catalog, "SELECT n FROM items")["rows"] == [[True], [False], [False], [None]]


def test_not_null_column_rejects_null(tmp_path):
    catalog = write_catalog(tmp_path, [[None]], [Column("n", "INT64", False)])
    assert_error(catalog, "SELECT * FROM items", "CSV")


def test_duplicate_catalog_columns_and_absolute_paths(tmp_path):
    catalog = write_catalog(tmp_path, [[1, 2]], [Column("n", "INT64"), Column("N", "INT64")])
    assert_error(catalog, "SELECT * FROM items", "CATALOG")
    payload = json.loads(catalog.read_text())
    payload["tables"][0]["columns"] = [{"name": "n", "type": "INT64", "nullable": True}]
    payload["tables"][0]["path"] = str(tmp_path / "data.csv")
    catalog.write_text(json.dumps(payload))
    assert_error(catalog, "SELECT * FROM items", "CATALOG")


def test_table_larger_than_future_default_batch(tmp_path):
    rows = [[i, i % 7] for i in range(2051)]
    catalog = write_catalog(tmp_path, rows, [Column("id", "INT64"), Column("n", "INT64")])
    assert quarry_result(catalog, "SELECT COUNT(*) AS rows, SUM(n) AS total FROM items")["rows"] == [[2051, sum(row[1] for row in rows)]]


@pytest.mark.parametrize("options", [("--engine", "invalid"), ("--optimizer", "invalid"),
                                     ("--batch-size", "0"), ("--batch-size", "65537"),
                                     ("--batch-size", "noninteger")])
def test_invalid_execution_modes_rejected(one, options):
    proc, payload = run_query(one, "SELECT * FROM items", *options)
    assert proc.returncode != 0 and payload["ok"] is False, payload
    assert payload["error"]["code"] in {"CLI", "UNSUPPORTED"}, payload


def test_result_and_accounted_memory_limits(tmp_path):
    catalog = write_catalog(tmp_path, generated_rows(5))
    assert_error(catalog, "SELECT id FROM items LIMIT 1", "RESOURCE", "--result-limit", "2")
    assert_error(catalog, "SELECT COUNT(*) FROM items", "RESOURCE", "--memory-limit", "1")
    assert quarry_result(catalog, "SELECT COUNT(*) AS n FROM items", "--result-limit", "1")["rows"] == [[33]]


def test_group_limit_and_oversized_csv_field(tmp_path):
    catalog = write_catalog(tmp_path, [[1], [2], [3]], [Column("n", "INT64")])
    assert_error(catalog, "SELECT n, COUNT(*) AS count FROM items GROUP BY n LIMIT 1", "RESOURCE", "--result-limit", "2")
    catalog = write_catalog(tmp_path, [["x" * (1024 * 1024 + 1)]], [Column("s", "STRING")])
    proc, payload = run_query(catalog, "SELECT s FROM items")
    assert proc.returncode != 0 and payload["ok"] is False
    assert payload["error"]["code"] in {"RESOURCE", "CSV"}, payload


def test_bounded_sql_length_and_nesting(one):
    for sql in ("SELECT id FROM items -- " + "x" * 65536,
                "SELECT " + "(" * 140 + "id" + ")" * 140 + " FROM items"):
        proc, payload = run_query(one, sql)
        assert proc.returncode != 0 and payload["ok"] is False, payload
        assert payload["error"]["code"] in {"RESOURCE", "PARSE"}, payload


def test_session_recovers_from_queries_protocol_and_oversized_requests(one):
    requests = [
        json.dumps({"id": 1, "sql": "SELECT id FROM items"}),
        json.dumps({"id": "bad", "sql": "SELECT 1 / 0 AS bad FROM items"}),
        "{broken",
        json.dumps({"id": [1, "opaque"], "sql": 99}),
        "x" * 131073,
        json.dumps({"id": {"nested": True}, "sql": "SELECT COUNT(*) AS n FROM items"}),
    ]
    proc = subprocess.run([str(BINARY), "session", "--stdio", "--catalog", str(one)],
                          input="\n".join(requests) + "\n", text=True, capture_output=True, timeout=30)
    assert proc.returncode == 0, proc
    responses = [json.loads(line) for line in proc.stdout.splitlines()]
    assert len(responses) == len(requests), proc
    assert responses[0]["id"] == 1 and responses[0]["rows"] == [["1"]]
    assert responses[1]["id"] == "bad" and responses[1]["error"]["code"] == "NUMERIC"
    for response in responses[2:5]:
        assert response["ok"] is False and "rows" not in response
        assert response["error"]["code"] in {"PROTOCOL", "RESOURCE"}, response
    assert responses[3]["id"] == [1, "opaque"]
    assert responses[-1]["id"] == {"nested": True} and responses[-1]["rows"] == [["1"]]


def test_session_repeated_failures_release_query_memory(tmp_path):
    catalog = write_catalog(tmp_path, [[1, 1], [2, 0]], [Column("id", "INT64"), Column("n", "INT64")])
    # The first input row creates a successful result before the second fails.
    request = json.dumps({"sql": "SELECT 1 / n AS bad FROM items"})
    okay = json.dumps({"sql": "SELECT id FROM items"})
    proc = subprocess.run([str(BINARY), "session", "--stdio", "--catalog", str(catalog), "--memory-limit", "65536"],
                          input="\n".join([okay] + [request] * 80 + [okay, okay]) + "\n",
                          text=True, capture_output=True, timeout=30)
    assert proc.returncode == 0, proc
    results = [json.loads(line) for line in proc.stdout.splitlines()]
    assert len(results) == 83 and results[0]["ok"] and results[-1]["ok"]
    assert all(result["error"]["code"] == "NUMERIC" for result in results[1:-2])
    # Stats represent allocations held by each returned result. Identical later
    # successes must not accumulate per-query allocations over failed requests.
    assert results[0]["stats"]["current_accounted_bytes"] == results[-1]["stats"]["current_accounted_bytes"]


def test_session_recovers_after_result_resource_failure(tmp_path):
    catalog = write_catalog(tmp_path, [[1], [2], [3]], [Column("id", "INT64")])
    requests = [{"id": 1, "sql": "SELECT id FROM items"},
                {"id": 2, "sql": "SELECT COUNT(*) AS n FROM items"}]
    proc = subprocess.run([str(BINARY), "session", "--stdio", "--catalog", str(catalog), "--result-limit", "2"],
                          input="".join(json.dumps(request) + "\n" for request in requests),
                          text=True, capture_output=True, timeout=30)
    assert proc.returncode == 0, proc
    failure, success = [json.loads(line) for line in proc.stdout.splitlines()]
    assert failure["error"]["code"] == "RESOURCE" and "rows" not in failure
    assert success["ok"] and success["id"] == 2 and success["rows"] == [["3"]]


def test_explain_has_three_typed_operator_plans(one):
    sql = "SELECT b, SUM(n) AS total FROM items WHERE n > 0 GROUP BY b ORDER BY total DESC LIMIT 1"
    proc = subprocess.run([str(BINARY), "explain", "--catalog", str(one), "--sql", sql],
                          text=True, capture_output=True, timeout=30)
    assert proc.returncode == 0, proc
    plan = json.loads(proc.stdout)
    assert plan["ok"] and plan["optimizer"] == "off"
    assert plan["unoptimized_logical"] == plan["optimized_logical"]
    kinds = ["Scan", "Filter", "HashAggregate", "Project", "Sort", "Limit"]
    assert [stage["operator"] for stage in plan["unoptimized_logical"]] == kinds
    assert [stage["operator"] for stage in plan["physical"]] == ["Scalar" + kind for kind in kinds]
    for stages in (plan["unoptimized_logical"], plan["optimized_logical"], plan["physical"]):
        assert [stage["id"] for stage in stages] == list(range(len(stages)))
        assert all(stage["engine"] == "scalar" and stage["columns"] for stage in stages)
        assert stages[-1]["columns"] == [{"name": "b", "type": "BOOL"}, {"name": "total", "type": "INT64"}]


@pytest.mark.parametrize("failure", ["missing_catalog", "invalid_catalog", "missing_sql", "invalid_cli"])
def test_boundary_io_catalog_and_cli_errors(tmp_path, one, failure):
    args = [str(BINARY), "query", "--catalog", str(one), "--sql", "SELECT id FROM items", "--format", "json"]
    if failure == "missing_catalog":
        args[3] = str(tmp_path / "absent.json")
        code = "IO"
    elif failure == "invalid_catalog":
        one.write_text("{broken")
        code = "CATALOG"
    elif failure == "missing_sql":
        args[4:6] = ["--sql-file", str(tmp_path / "absent.sql")]
        code = "IO"
    else:
        args += ["--unknown"]
        code = "CLI"
    proc = subprocess.run(args, text=True, capture_output=True, timeout=30)
    payload = json.loads(proc.stdout)
    assert proc.returncode != 0 and payload["error"]["code"] == code, payload
    assert payload["ok"] is False and "rows" not in payload


def test_qualified_and_predicate_metamorphic_equivalence(tmp_path):
    catalog = write_catalog(tmp_path, generated_rows(7))
    plain = quarry_result(catalog, "SELECT id, n FROM items WHERE n > 0 AND b = TRUE")
    qualified = quarry_result(catalog, "SELECT q.id AS id, q.n AS n FROM items AS q WHERE q.b = TRUE AND q.n > 0")
    compare_results(plain, qualified)
    count = quarry_result(catalog, "SELECT COUNT(*) AS n FROM items WHERE n > 0 AND b = TRUE")
    assert count["rows"] == [[len(plain["rows"])]]


def test_demo_and_sql_file_run_without_python_runtime_on_path(tmp_path):
    env = dict(os.environ, PATH="/usr/bin:/bin")
    proc = subprocess.run([str(BINARY), "demo"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0 and proc.stdout.strip(), proc
    proc = subprocess.run([str(BINARY), "query", "--catalog", str(ROOT / "examples/catalog.json"),
                           "--sql-file", str(ROOT / "examples/query.sql"), "--format", "json"],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0 and json.loads(proc.stdout)["ok"] is True, proc


def test_canonical_fixture_manifest_hashes_and_reproduction(tmp_path):
    manifest = json.loads((ROOT / "examples/fixture.json").read_text())
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((ROOT / "examples" / name).read_bytes()).hexdigest() == digest
    proc = subprocess.run([sys.executable, str(ROOT / "tools/generate_data.py"), "--output", str(tmp_path),
                           "--seed", str(manifest["seed"]), "--rows", str(manifest["rows"])],
                          text=True, capture_output=True, timeout=30)
    assert proc.returncode == 0, proc
    for name in [*manifest["sha256"], "fixture.json"]:
        assert (ROOT / "examples" / name).read_bytes() == (tmp_path / name).read_bytes()
