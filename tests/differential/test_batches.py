"""M4: real batch boundaries, masked payloads, and scalar/vector parity."""
from __future__ import annotations

import json
import subprocess

import pytest

from harness import (BATCH_SIZES, BINARY, Column, compare_results, duckdb_result,
                     execution_modes, quarry_result, run_query, write_catalog)


@pytest.mark.parametrize("size", [0, 1, 7, 8, 257, 1025, 2051, 4099])
def test_empty_partial_and_multiple_batches(tmp_path, size):
    schema = [Column("id", "INT64", False), Column("n", "INT64"), Column("s", "STRING")]
    rows = [[i, None if i % 9 == 0 else i % 13,
             None if i % 11 == 0 else f"row-{i}-" + "界" * 24] for i in range(size)]
    catalog = write_catalog(tmp_path, rows, schema)
    queries = [
        ("SELECT id, n * 2 AS twice, s FROM items WHERE id < 0", ()),
        # A zero-selected interior batch must not be mistaken for EOF.
        ("SELECT id, s FROM items WHERE id = 0 OR id >= 4096 ORDER BY id", (0,)),
        ("SELECT COUNT(*) AS rows, COUNT(n) AS values_n, SUM(n) AS total FROM items", ()),
        ("SELECT n, COUNT(*) AS rows, MIN(s) AS first_s FROM items GROUP BY n ORDER BY n NULLS FIRST", (0,)),
        ("SELECT id, s FROM items ORDER BY id DESC LIMIT 9", (0,)),
    ]
    for sql, order in queries:
        expected = duckdb_result(rows, schema, sql)
        for _, options in execution_modes():
            compare_results(quarry_result(catalog, sql, *options), expected, order)


@pytest.mark.parametrize("batch_size", BATCH_SIZES)
@pytest.mark.parametrize("expression", ["1 / n", "9223372036854775807 + n", "1e308 * CAST(n AS DOUBLE)"])
def test_batch_numeric_errors_have_scalar_evaluation_domain(tmp_path, batch_size, expression):
    # Place the failure after a successful prefix and beyond a partial batch.
    prefix = 0 if expression.startswith("922337") else 1
    bad = 0 if expression == "1 / n" else 1 if expression.startswith("922337") else 2
    rows = [[i, prefix] for i in range(8)] + [[8, bad], [9, prefix]]
    catalog = write_catalog(tmp_path, rows, [Column("id", "INT64"), Column("n", "INT64")])
    for suffix in ("", " LIMIT 0", " LIMIT 1"):
        sql = f"SELECT {expression} AS result FROM items{suffix}"
        for options in (("--engine", "scalar"), ("--engine", "vector", "--batch-size", str(batch_size))):
            proc, payload = run_query(catalog, sql, *options)
            assert proc.returncode != 0 and payload["error"]["code"] == "NUMERIC", (options, payload)
            assert "rows" not in payload
    safe = f"SELECT {expression} AS result FROM items WHERE id < 8 ORDER BY 1 LIMIT 0"
    assert quarry_result(catalog, safe, "--engine", "vector", "--batch-size", str(batch_size))["rows"] == []


@pytest.mark.parametrize("batch_size", BATCH_SIZES)
def test_batch_nulls_mask_invalid_numeric_payloads(tmp_path, batch_size):
    rows = [[i, None if i % 2 == 0 else 1] for i in range(19)]
    schema = [Column("id", "INT64"), Column("n", "INT64")]
    catalog = write_catalog(tmp_path, rows, schema)
    sql = "SELECT id, n / 0 AS result FROM items WHERE n IS NULL ORDER BY id"
    expected = {"columns": [{"name": "id", "type": "INT64"}, {"name": "result", "type": "DOUBLE"}],
                "rows": [[i, None] for i in range(0, 19, 2)]}
    compare_results(quarry_result(catalog, sql, "--engine", "vector", "--batch-size", str(batch_size)), expected, (0,))


@pytest.mark.parametrize("batch_size", BATCH_SIZES)
def test_vector_materialized_caps_cannot_be_rescued_by_limit(tmp_path, batch_size):
    catalog = write_catalog(tmp_path, [[i] for i in range(19)], [Column("id", "INT64")])
    options = ("--engine", "vector", "--batch-size", str(batch_size), "--result-limit", "2")
    for sql in ("SELECT id FROM items LIMIT 1",
                "SELECT id, COUNT(*) AS n FROM items GROUP BY id LIMIT 1"):
        proc, payload = run_query(catalog, sql, *options)
        assert proc.returncode != 0 and payload["error"]["code"] == "RESOURCE", payload
        assert "rows" not in payload
    assert quarry_result(catalog, "SELECT COUNT(*) AS n FROM items", *options)["rows"] == [[19]]


@pytest.mark.parametrize("batch_size", BATCH_SIZES)
@pytest.mark.parametrize(("values", "code"), [([0, 1], "NUMERIC"), ([1, 0], "RESOURCE")])
def test_group_cap_and_numeric_error_precedence_is_batch_invariant(tmp_path, batch_size, values, code):
    rows = [[index + 1, value] for index, value in enumerate(values)]
    catalog = write_catalog(tmp_path, rows, [Column("k", "INT64"), Column("n", "INT64")])
    sql = "SELECT k, SUM(1 / n) AS total FROM items GROUP BY k"
    for mode in (("--engine", "scalar"), ("--engine", "vector", "--batch-size", str(batch_size))):
        proc, payload = run_query(catalog, sql, *mode, "--result-limit", "1")
        assert proc.returncode != 0 and payload["error"]["code"] == code, (mode, payload)


@pytest.mark.parametrize("expression", ["CAST(NULL AS DOUBLE) * (1 / n)",
                                        "FALSE AND (1 / n > 0.0)", "TRUE OR (1 / n > 0.0)",
                                        "(1 / n) IS NULL", "-(1 / n)"])
def test_child_numeric_fault_survives_outer_null_boolean_or_null_test(tmp_path, expression):
    catalog = write_catalog(tmp_path, [[1], [0]], [Column("n", "INT64")])
    for _, options in execution_modes():
        proc, payload = run_query(catalog, f"SELECT {expression} AS result FROM items LIMIT 0", *options)
        assert proc.returncode != 0 and payload["error"]["code"] == "NUMERIC", (options, payload)


def test_vector_session_reuses_catalog_and_owns_outputs_after_errors(tmp_path):
    long_string = "before\nquoted,\"" + "界" * 256
    rows = [[i, 0 if i == 8 else 1, long_string + str(i)] for i in range(19)]
    catalog = write_catalog(tmp_path, rows, [Column("id", "INT64"), Column("n", "INT64"), Column("s", "STRING")])
    valid = "SELECT id, s FROM items ORDER BY id DESC LIMIT 3"
    requests = [
        {"id": "vector-default", "sql": valid},
        {"id": "scalar-override", "sql": valid, "options": {"engine": "scalar"}},
        {"id": "bad-option", "sql": valid, "options": {"batch_size": 0}},
        {"id": "late-error", "sql": "SELECT 1 / n AS failed FROM items"},
        {"id": "after-errors", "sql": valid},
    ]
    proc = subprocess.run([str(BINARY), "session", "--stdio", "--catalog", str(catalog),
                           "--engine", "vector", "--batch-size", "7"],
                          input="".join(json.dumps(request) + "\n" for request in requests),
                          text=True, capture_output=True, timeout=30)
    assert proc.returncode == 0, proc
    output = [json.loads(line) for line in proc.stdout.splitlines()]
    assert len(output) == len(requests)
    expected = [[str(i), long_string + str(i)] for i in (18, 17, 16)]
    assert output[0]["rows"] == output[1]["rows"] == output[4]["rows"] == expected
    assert output[2]["ok"] is False and output[2]["id"] == "bad-option"
    assert output[3]["error"]["code"] == "NUMERIC"
    assert output[0]["stats"]["current_accounted_bytes"] == output[4]["stats"]["current_accounted_bytes"]
