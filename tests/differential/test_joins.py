"""M5 joins: explicit DuckDB tables plus a separate tiny nested-loop oracle."""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from harness import (BATCH_SIZES, BINARY, Column, compare_results, decode_result, duckdb_multi_result,
                     execution_modes, verification_modes, mode_responses, quarry_result, run_query, save_failure, write_multi_catalog)

from corpus import JOIN_SCHEMA, JOIN_QUERIES, PREFIX, join_tables, distinct_seeds, record_success

PROFILE = os.environ.get("QUARRY_TEST_PROFILE", "core")
SEEDS = distinct_seeds("join", PROFILE)


def nested_loop_pairs(left, right, keys):
    """Independent tiny correctness oracle; never used by Quarry execution."""
    pairs = []
    for lrow in left:
        for rrow in right:
            if all(lrow[li] is not None and rrow[ri] is not None and lrow[li] == rrow[ri]
                   for li, ri in keys):
                pairs.append((lrow, rrow))
    return pairs


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("family", range(len(JOIN_QUERIES)))
def test_generated_join_case(tmp_path, seed, family):
    tables = join_tables(seed)
    catalog = write_multi_catalog(tmp_path, tables)
    sql, order = JOIN_QUERIES[family]
    expected = duckdb_multi_result(tables, sql)
    modes = verification_modes()
    try:
        responses = mode_responses(catalog, sql, modes)
    except Exception as error:
        artifact = save_failure(f"join-seed-{seed}-family-{family}-session", catalog, sql,
                                seed, {"session_error": repr(error), "modes": modes}, expected)
        print(f"Session reproducer preserved at {artifact}")
        raise
    for (name, options), response in zip(modes, responses):
        actual = None
        try:
            assert response.get("ok") is True, response
            assert isinstance(response.get("stats", {}).get("peak_accounted_bytes"), int), response
            actual = decode_result(response)
            compare_results(actual, expected, order)
        except Exception:
            artifact = save_failure(f"join-seed-{seed}-family-{family}-{name}", catalog, sql,
                                    51032026 + seed, actual, expected, options)
            print(f"Join reproducer preserved at {artifact}")
            raise
    record_success("join", seed, family, len(modes))


@pytest.mark.parametrize(("family", "keys"), [(0, [(1, 1)]), (2, [(1, 1), (2, 2)]),
                                             (3, [(3, 3)]), (9, [(1, 1)])])
@pytest.mark.parametrize("seed", [3, 4, 5])
def test_join_matches_independent_nested_loop(tmp_path, family, keys, seed):
    tables = join_tables(seed)
    sql, order = JOIN_QUERIES[family]
    pairs = nested_loop_pairs(tables["left_items"][1], tables["right_items"][1], keys)
    expected = {"columns": [{"name": name, "type": kind} for name, kind in
                            [("lid", "INT64"), ("rid", "INT64"), ("left_n", "INT64"), ("right_s", "STRING")]],
                "rows": [[left[0], right[0], left[4], right[3]] for left, right in pairs]}
    compare_results(duckdb_multi_result(tables, sql), expected, order)
    catalog = write_multi_catalog(tmp_path, tables)
    for _, options in execution_modes():
        compare_results(quarry_result(catalog, sql, *options), expected, order)


def test_null_composite_keys_do_not_match_and_duplicates_multiply(tmp_path):
    schema = [Column("id", "INT64"), Column("k", "INT64"), Column("b", "BOOL"), Column("s", "STRING")]
    left = [[1, 1, True, "x"], [2, 1, True, "x"], [3, None, True, "x"],
            [4, 1, None, "x"], [5, 1, True, None], [6, 9, False, "unmatched"]]
    right = [[11, 1, True, "x"], [12, 1, True, "x"], [13, None, True, "x"],
             [14, 1, None, "x"], [15, 1, True, None]]
    catalog = write_multi_catalog(tmp_path, {"left_items": (schema, left), "right_items": (schema, right)})
    sql = "SELECT l.id AS lid, r.id AS rid " + PREFIX + "l.k = r.k AND l.b = r.b AND l.s = r.s ORDER BY lid, rid"
    for _, options in execution_modes():
        assert quarry_result(catalog, sql, *options)["rows"] == [[1, 11], [1, 12], [2, 11], [2, 12]]


@pytest.mark.parametrize("batch_size", BATCH_SIZES)
def test_one_probe_continues_over_more_than_4096_matches(tmp_path, batch_size):
    schema = [Column("id", "INT64", False), Column("k", "INT64"), Column("s", "STRING")]
    left = [[1, 7, "left-" + "界" * 128]]
    right = [[100 + i, 7, f"right-{i},\n" + '"' * (i % 5)] for i in range(4103)]
    catalog = write_multi_catalog(tmp_path, {"left_items": (schema, left), "right_items": (schema, right)})
    sql = "SELECT l.id AS lid, r.id AS rid, l.s AS left_s, r.s AS right_s " + PREFIX + "l.k = r.k ORDER BY rid"
    options = ("--engine", "vector", "--batch-size", str(batch_size))
    result = quarry_result(catalog, sql, *options)
    assert result["rows"] == [[1, row[0], left[0][2], row[2]] for row in right]
    compare_results(result, quarry_result(catalog, sql, "--engine", "scalar"), (1,))


@pytest.mark.parametrize(("condition", "code"), [("l.d = r.d", "TYPE"), ("l.k < r.k", "UNSUPPORTED"),
                                                ("l.k = r.id OR l.id = r.k", "UNSUPPORTED"),
                                                ("l.k + 1 = r.k", "UNSUPPORTED"),
                                                ("l.k = l.id", "BIND")])
def test_invalid_join_conditions_rejected(tmp_path, condition, code):
    catalog = write_multi_catalog(tmp_path, join_tables(5))
    proc, result = run_query(catalog, "SELECT l.id AS lid " + PREFIX + condition)
    assert proc.returncode != 0 and result["error"]["code"] == code, result


def test_join_binding_requires_unambiguous_names(tmp_path):
    catalog = write_multi_catalog(tmp_path, join_tables(5))
    proc, result = run_query(catalog, "SELECT id " + PREFIX + "l.k = r.k")
    assert proc.returncode != 0 and result["error"]["code"] == "BIND", result


def test_join_session_resource_failure_and_success_cleanup(tmp_path):
    schema = [Column("id", "INT64"), Column("k", "INT64")]
    left, right = [[i, 1] for i in range(4)], [[i + 100, 1] for i in range(4)]
    catalog = write_multi_catalog(tmp_path, {"left_items": (schema, left), "right_items": (schema, right)})
    valid = "SELECT COUNT(*) AS rows " + PREFIX + "l.k = r.k"
    requests = [{"id": 1, "sql": valid},
                {"id": 2, "sql": "SELECT l.id AS lid " + PREFIX + "l.k = r.k LIMIT 1"},
                {"id": 3, "sql": valid}]
    for engine in ("scalar", "vector"):
        proc = subprocess.run([str(BINARY), "session", "--stdio", "--catalog", str(catalog),
                               "--engine", engine, "--batch-size", "7", "--result-limit", "2"],
                              input="".join(json.dumps(request) + "\n" for request in requests),
                              text=True, capture_output=True, timeout=30)
        assert proc.returncode == 0, proc
        first, failed, last = [json.loads(line) for line in proc.stdout.splitlines()]
        assert first["rows"] == last["rows"] == [["16"]]
        assert failed["error"]["code"] == "RESOURCE" and "rows" not in failed
        assert first["stats"]["current_accounted_bytes"] == last["stats"]["current_accounted_bytes"]


def test_join_expression_domain_excludes_unmatched_and_filtered_rows(tmp_path):
    schema = [Column("id", "INT64"), Column("k", "INT64"), Column("n", "INT64")]
    left = [[1, 1, 1], [2, 9, 0], [3, 2, None], [4, 1, 0]]
    right = [[11, 1, 1], [12, 1, 2], [13, 2, 0]]
    catalog = write_multi_catalog(tmp_path, {"left_items": (schema, left), "right_items": (schema, right)})
    safe = "SELECT l.id AS lid, r.id AS rid, 1 / l.n AS ratio " + PREFIX + "l.k = r.k WHERE l.id <> 4 ORDER BY lid, rid"
    bad = "SELECT 1 / l.n AS ratio " + PREFIX + "l.k = r.k WHERE l.id = 4 LIMIT 0"
    empty = "SELECT SUM(1 / l.n) AS total " + PREFIX + "l.k = r.k WHERE l.id < 0"
    for _, options in execution_modes():
        assert quarry_result(catalog, safe, *options)["rows"] == [[1, 11, 1.0], [1, 12, 1.0], [3, 13, None]]
        assert quarry_result(catalog, empty, *options)["rows"] == [[None]]
        proc, result = run_query(catalog, bad, *options)
        assert proc.returncode != 0 and result["error"]["code"] == "NUMERIC", result


def cancellation_join_tables():
    left_schema = [Column("id", "INT64"), Column("k", "INT64"), Column("d", "DOUBLE")]
    right_schema = [Column("id", "INT64"), Column("k", "INT64")]
    return {"left_items": (left_schema, [[1, 1, 1e16], [2, 1, -1e16], [3, 1, 1.0]]),
            "right_items": (right_schema, [[100 + i, 1] for i in range(5)])}


def test_default_join_preserves_declared_double_accumulation_order(tmp_path):
    # Right-build left-probe order gives 5. A left-build traversal gives 1.
    catalog = write_multi_catalog(tmp_path, cancellation_join_tables())
    sql = "SELECT SUM(l.d) AS total, AVG(l.d) AS mean_d " + PREFIX + "l.k = r.k"
    for _, options in execution_modes():
        assert quarry_result(catalog, sql, *options)["rows"] == [[5.0, 5.0 / 15.0]]


@pytest.mark.parametrize("seed", range(6))
def test_safe_forced_build_sides_preserve_results(tmp_path, seed):
    tables = join_tables(seed)
    catalog = write_multi_catalog(tmp_path, tables)
    queries = [JOIN_QUERIES[0],
               ("SELECT l.k AS key, COUNT(*) AS rows, MIN(r.s) AS first_s, SUM(l.n) AS total "
                + PREFIX + "l.k = r.k GROUP BY l.k ORDER BY key", (0,))]
    for sql, order in queries:
        expected = duckdb_multi_result(tables, sql)
        for _, options in execution_modes():
            for side in ("left", "right"):
                compare_results(quarry_result(catalog, sql, *options, "--build-side", side), expected, order)


@pytest.mark.parametrize("engine", ["scalar", "vector"])
def test_unsafe_build_swap_cannot_change_resource_vs_numeric_error(tmp_path, engine):
    schema = [Column("id", "INT64"), Column("k", "INT64")]
    catalog = write_multi_catalog(tmp_path, {
        "left_items": (schema, [[1, 1], [2, 1]]),
        "right_items": (schema, [[2, 1], [3, 1], [4, 1]])})
    sql = "SELECT 1 / (l.id - r.id) AS ratio " + PREFIX + "l.k = r.k"
    for side, code in (("right", "RESOURCE"), ("left", "UNSUPPORTED"), ("auto", "RESOURCE")):
        proc, payload = run_query(catalog, sql, "--engine", engine, "--batch-size", "7",
                                  "--build-side", side, "--result-limit", "2")
        assert proc.returncode != 0 and payload["error"]["code"] == code, (side, payload)


@pytest.mark.parametrize("engine", ["scalar", "vector"])
def test_forced_build_swap_rejects_double_aggregation_order_change(tmp_path, engine):
    catalog = write_multi_catalog(tmp_path, cancellation_join_tables())
    sql = "SELECT SUM(l.d) AS total, AVG(l.d) AS mean_d " + PREFIX + "l.k = r.k"
    proc, payload = run_query(catalog, sql, "--engine", engine, "--build-side", "left")
    assert proc.returncode != 0 and payload["error"]["code"] == "UNSUPPORTED", payload
