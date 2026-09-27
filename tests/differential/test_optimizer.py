"""M6: rule isolation, actual counters, safe rewrites, and profiled plans."""
from __future__ import annotations

import json
import subprocess

import pytest

from harness import (BINARY, QUERIES, SCHEMA, Column, compare_results, decode_result,
                     duckdb_multi_result, duckdb_result, generated_rows, quarry_result,
                     run_query, write_catalog, write_multi_catalog)
from test_joins import JOIN_QUERIES, PREFIX, cancellation_join_tables, join_tables

MODES = [("scalar", ("--engine", "scalar")),
         ("vector", ("--engine", "vector", "--batch-size", "7"))]
RULES = {"prune": "column_pruning", "pushdown": "predicate_pushdown",
         "fold": "constant_folding", "join-reorder": "join_build_side"}


def only_rule(rule):
    return ("--optimizer", "on", *[part for name in RULES for part in
            ("--" + name, "on" if name == rule else "off")])


def explain(catalog, sql, *options, analyze=False):
    command = [str(BINARY), "explain", "--catalog", str(catalog), "--sql", sql, *options]
    if analyze:
        command.append("--analyze")
    proc = subprocess.run(command, text=True, capture_output=True, timeout=30)
    result = json.loads(proc.stdout)
    assert proc.returncode == 0 and result["ok"], (proc, result)
    return result


def raw_result(catalog, sql, *options):
    proc, result = run_query(catalog, sql, *options)
    assert proc.returncode == 0 and result["ok"], result
    return result


def join_operator(result):
    return next(op for op in result["stats"]["operators"] if "Join" in op["operator"])


@pytest.mark.parametrize("family", range(len(QUERIES)))
def test_each_optimizer_rule_single_table_equivalence(tmp_path, family):
    rows = generated_rows(7)
    catalog = write_catalog(tmp_path, rows)
    sql, order = QUERIES[family]
    expected = duckdb_result(rows, SCHEMA, sql)
    for _, mode in MODES:
        for rule in RULES:
            compare_results(quarry_result(catalog, sql, *mode, *only_rule(rule)), expected, order)


@pytest.mark.parametrize("family", range(len(JOIN_QUERIES)))
def test_each_optimizer_rule_join_equivalence(tmp_path, family):
    tables = join_tables(5)
    catalog = write_multi_catalog(tmp_path, tables)
    sql, order = JOIN_QUERIES[family]
    expected = duckdb_multi_result(tables, sql)
    for _, mode in MODES:
        for rule in RULES:
            compare_results(quarry_result(catalog, sql, *mode, *only_rule(rule)), expected, order)


@pytest.mark.parametrize(("engine", "mode"), MODES)
def test_pruning_reduces_actual_opened_columns_and_keeps_hidden_dependencies(tmp_path, engine, mode):
    schema = [Column("id", "INT64"), Column("n", "INT64"), Column("b", "BOOL"),
              Column("s", "STRING"), Column("unused_text", "STRING"), Column("unused_double", "DOUBLE")]
    rows = [[i, i, i % 2 == 0, str(i), "unused-" + "界" * 128, i / 4.0] for i in range(16)]
    catalog = write_catalog(tmp_path, rows, schema)
    sql = "SELECT id FROM items WHERE n > 3 ORDER BY id LIMIT 5"
    off = raw_result(catalog, sql, *mode, "--optimizer", "off")
    on = raw_result(catalog, sql, *mode, *only_rule("prune"))
    compare_results(decode_result(on), decode_result(off), (0,))
    opened = lambda result: sum(op["columns_opened"] for op in result["stats"]["operators"])
    assert opened(on) < opened(off), (off["stats"], on["stats"])
    assert on["stats"]["rule_applications"]["column_pruning"] > 0
    assert all(count == 0 for name, count in on["stats"]["rule_applications"].items() if name != "column_pruning")
    plan = explain(catalog, sql, *mode, *only_rule("prune"))
    raw_scan = next(stage for stage in plan["unoptimized_logical"] if stage["operator"].endswith("Scan"))
    optimized_scan = next(stage for stage in plan["optimized_logical"] if stage["operator"].endswith("Scan"))
    assert len(raw_scan["columns"]) == 6
    assert {column["name"] for column in optimized_scan["columns"]} == {"id", "n"}
    assert len(optimized_scan["bound_columns"]) == 2
    # Lazy scalar reads/zero-copy views need not read unused payloads even when
    # pruning is off; values_read is intentionally not required to decrease.


def pushdown_tables():
    schema = [Column("id", "INT64"), Column("k", "INT64"), Column("n", "INT64"), Column("wide", "STRING")]
    left = [[i, 1, None if i % 3 == 0 else i, "left" * 80] for i in range(20)]
    right = [[100 + i, 1, None if i % 4 == 0 else i, "right" * 80] for i in range(20)]
    return {"left_items": (schema, left), "right_items": (schema, right)}


@pytest.mark.parametrize(("engine", "mode"), MODES)
def test_pushdown_reduces_join_candidates_with_nullable_residual(tmp_path, engine, mode):
    tables = pushdown_tables()
    catalog = write_multi_catalog(tmp_path, tables)
    sql = "SELECT l.id AS lid, r.id AS rid " + PREFIX + "l.k = r.k WHERE l.id < 2 AND r.id < 105 AND (l.n IS NULL OR r.n >= 0) ORDER BY lid, rid"
    off = raw_result(catalog, sql, *mode, "--optimizer", "off")
    on = raw_result(catalog, sql, *mode, *only_rule("pushdown"))
    expected = duckdb_multi_result(tables, sql)
    compare_results(decode_result(off), expected, (0, 1))
    compare_results(decode_result(on), expected, (0, 1))
    before, after = join_operator(off), join_operator(on)
    assert before["candidate_rows"] == 400 and after["candidate_rows"] == 10
    assert after["build_rows"] == 5 and after["probe_rows"] == 2
    assert on["stats"]["rule_applications"]["predicate_pushdown"] == 2
    for source, output in (("l", 2), ("r", 5)):
        assert any(op["source"] == source and op["input_rows"] == 20 and op["output_rows"] == output
                   for op in on["stats"]["operators"]), on["stats"]
    plan = explain(catalog, sql, *mode, *only_rule("pushdown"))
    assert any(stage["source"] == "l" and stage["predicates"] for stage in plan["optimized_logical"])
    assert any(stage["source"] == "r" and stage["predicates"] for stage in plan["optimized_logical"])


@pytest.mark.parametrize(("engine", "mode"), MODES)
def test_safe_constant_folding_occurs_but_failing_constants_stay_masked(tmp_path, engine, mode):
    catalog = write_catalog(tmp_path, [[1]], [Column("id", "INT64")])
    result = raw_result(catalog, "SELECT (2 + 3) * 4 AS answer FROM items", *mode, *only_rule("fold"))
    assert result["rows"] == [["20"]]
    assert result["stats"]["rule_applications"]["constant_folding"] > 0
    for expression in ("1 / 0", "9223372036854775807 + 1", "-(-9223372036854775808)"):
        for suffix in ("WHERE id < 0", "WHERE id < 0 LIMIT 0"):
            assert quarry_result(catalog, f"SELECT {expression} AS bad FROM items {suffix}", *mode, "--optimizer", "on")["rows"] == []
        proc, failure = run_query(catalog, f"SELECT {expression} AS bad FROM items LIMIT 0", *mode, "--optimizer", "on")
        assert proc.returncode != 0 and failure["error"]["code"] == "NUMERIC", failure


@pytest.mark.parametrize(("engine", "mode"), MODES)
def test_join_reorder_uses_smaller_build_side_when_safe(tmp_path, engine, mode):
    schema = [Column("id", "INT64"), Column("k", "INT64")]
    tables = {"left_items": (schema, [[i, 1] for i in range(3)]),
              "right_items": (schema, [[100 + i, 1] for i in range(8)])}
    catalog = write_multi_catalog(tmp_path, tables)
    sql = "SELECT l.id AS lid, r.id AS rid " + PREFIX + "l.k = r.k ORDER BY lid, rid"
    off = raw_result(catalog, sql, *mode, "--optimizer", "on", "--join-reorder", "off")
    on = raw_result(catalog, sql, *mode, *only_rule("join-reorder"))
    compare_results(decode_result(off), decode_result(on), (0, 1))
    assert off["stats"]["join"]["build_side"] == "right"
    assert on["stats"]["join"]["build_side"] == "left"
    assert on["stats"]["rule_applications"]["join_build_side"] == 1
    assert join_operator(off)["build_rows"] == 8 and join_operator(on)["build_rows"] == 3


@pytest.mark.parametrize(("engine", "mode"), MODES)
def test_double_aggregate_guard_preserves_exact_input_order(tmp_path, engine, mode):
    catalog = write_multi_catalog(tmp_path, cancellation_join_tables())
    sql = "SELECT SUM(l.d) AS total, AVG(l.d) AS mean_d " + PREFIX + "l.k = r.k"
    result = raw_result(catalog, sql, *mode, "--optimizer", "on")
    assert result["rows"] == [[5.0, 5.0 / 15.0]]
    assert result["stats"]["join"]["build_side"] == "right"
    assert result["stats"]["rule_applications"]["join_build_side"] == 0
    plan = explain(catalog, sql, *mode, "--optimizer", "on")
    assert plan["join"]["build_side"] == "right"
    assert "double" in plan["join"]["reason"].lower(), plan
    proc, failure = run_query(catalog, sql, *mode, "--optimizer", "on", "--build-side", "left")
    assert proc.returncode != 0 and failure["error"]["code"] == "UNSUPPORTED"


@pytest.mark.parametrize(("engine", "mode"), MODES)
def test_optimizer_preserves_numeric_vs_resource_order_guard(tmp_path, engine, mode):
    schema = [Column("id", "INT64"), Column("k", "INT64")]
    catalog = write_multi_catalog(tmp_path, {"left_items": (schema, [[1, 1], [2, 1]]),
                                             "right_items": (schema, [[2, 1], [3, 1], [4, 1]])})
    sql = "SELECT 1 / (l.id - r.id) AS ratio " + PREFIX + "l.k = r.k"
    proc, failure = run_query(catalog, sql, *mode, "--optimizer", "on", "--result-limit", "2")
    assert proc.returncode != 0 and failure["error"]["code"] == "RESOURCE", failure
    plan = explain(catalog, sql, *mode, "--optimizer", "on")
    assert plan["join"]["build_side"] == "right" and plan["join"]["reason"]


@pytest.mark.parametrize(("engine", "mode"), MODES)
@pytest.mark.parametrize("fold", ["on", "off"])
def test_failing_signed_literal_is_not_pushed_before_unmatched_join(tmp_path, engine, mode, fold):
    schema = [Column("id", "INT64"), Column("k", "INT64")]
    catalog = write_multi_catalog(tmp_path, {"left_items": (schema, [[1, 1]]),
                                             "right_items": (schema, [[2, 9]])})
    sql = "SELECT l.id AS lid " + PREFIX + "l.k = r.k WHERE l.id > -(-9223372036854775808)"
    for optimizer in ("off", "on"):
        assert quarry_result(catalog, sql, *mode, "--optimizer", optimizer, "--fold", fold)["rows"] == []


@pytest.mark.parametrize(("engine", "mode"), MODES)
def test_analyze_returns_results_typed_plans_and_scoped_counters(tmp_path, engine, mode):
    catalog = write_multi_catalog(tmp_path, join_tables(5))
    sql = JOIN_QUERIES[4][0]
    analyzed = explain(catalog, sql, *mode, "--optimizer", "on", analyze=True)
    assert analyzed["optimizer"] == "on"
    assert set(analyzed["rule_applications"]) == set(RULES.values())
    assert set(analyzed["rules"]) == {"prune", "pushdown", "fold", "build_side"}
    for key in ("unoptimized_logical", "optimized_logical", "physical"):
        known_ids = set()
        for stage in analyzed[key]:
            assert stage["id"] not in known_ids
            assert all(input_id in known_ids for input_id in stage["inputs"])
            known_ids.add(stage["id"])
            assert all(field in stage for field in ("operator", "engine", "columns", "source", "bound_columns", "predicates"))
    result = analyzed["result"]
    compare_results(decode_result(result), quarry_result(catalog, sql, *mode, "--optimizer", "on"), (0,))
    stats = result["stats"]
    assert stats["engine"] == engine and stats["batch_size"] > 0
    assert all(stats["timings"][field] >= 0 for field in ("planning_ns", "execution_ns"))
    assert isinstance(stats["timings"]["scope"], str) and stats["timings"]["scope"]
    physical_ids = {stage["id"] for stage in analyzed["physical"]}
    assert {op["id"] for op in stats["operators"]} == physical_ids
    for op in stats["operators"]:
        for field in ("input_rows", "output_rows", "batches", "columns_opened", "columns_read", "values_read",
                      "build_rows", "probe_rows", "candidate_rows", "accounted_allocation_bytes", "elapsed_ns"):
            assert type(op[field]) is int and op[field] >= 0, (field, op)
        assert op["timing_scope"]
    ordinary = raw_result(catalog, sql, *mode)
    assert "timings" not in ordinary["stats"]
    assert all("elapsed_ns" not in op for op in ordinary["stats"]["operators"])


def test_session_optimizer_options_are_isolated_and_profiled_per_request(tmp_path):
    catalog = write_catalog(tmp_path, [[1, 2], [2, None]], [Column("id", "INT64"), Column("n", "INT64")])
    sql = "SELECT id FROM items WHERE n IS NOT NULL"
    requests = [
        {"id": "baseline", "sql": sql},
        {"id": "override", "sql": sql, "options": {"engine": "vector", "batch_size": 1, "optimizer": "on",
                                                          "prune": "on", "pushdown": "off", "fold": "off", "join_reorder": "off", "profile": True}},
        {"id": "invalid", "sql": sql, "options": {"optimizer": True}},
        {"id": "after", "sql": sql},
    ]
    proc = subprocess.run([str(BINARY), "session", "--stdio", "--catalog", str(catalog)],
                          input="".join(json.dumps(request) + "\n" for request in requests),
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc
    first, override, invalid, last = [json.loads(line) for line in proc.stdout.splitlines()]
    assert first["rows"] == override["rows"] == last["rows"] == [["1"]]
    assert first["stats"]["engine"] == last["stats"]["engine"] == "scalar"
    assert override["stats"]["engine"] == "vector" and override["stats"]["batch_size"] == 1
    assert "timings" in override["stats"] and "timings" not in last["stats"]
    assert invalid["ok"] is False and invalid["id"] == "invalid"
    assert all(count == 0 for count in last["stats"]["rule_applications"].values())


def test_session_rejects_invalid_option_types_and_recovers(tmp_path):
    catalog = write_catalog(tmp_path, [[1]], [Column("id", "INT64")])
    invalid_options = [None, [], {"engine": 3}, {"engine": "unknown"},
                       {"batch_size": 1.5}, {"batch_size": -1}, {"batch_size": 2**63},
                       {"prune": True}, {"profile": "true"}, {"join_reorder": "invalid"},
                       {"build_side": "outer"}, {"not_an_option": "on"}]
    requests = [{"id": i, "sql": "SELECT id FROM items", "options": options}
                for i, options in enumerate(invalid_options)]
    requests.append({"id": "after", "sql": "SELECT id FROM items"})
    proc = subprocess.run([str(BINARY), "session", "--stdio", "--catalog", str(catalog)],
                          input="".join(json.dumps(request) + "\n" for request in requests),
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc
    results = [json.loads(line) for line in proc.stdout.splitlines()]
    assert len(results) == len(requests)
    for index, result in enumerate(results[:-1]):
        assert result["id"] == index and result["ok"] is False, (invalid_options[index], result)
        assert result["error"]["code"] in {"PROTOCOL", "CLI", "UNSUPPORTED"}, result
    assert results[-1]["id"] == "after" and results[-1]["rows"] == [["1"]]
    assert results[-1]["stats"]["engine"] == "scalar"
