"""Bounded tooling tests; no real benchmark measurement is performed here."""
import copy
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import benchmark as bench
import benchmark_report as report
import generate_benchmarks as generate


@pytest.mark.parametrize("system,name_field", [("Darwin", "ucomm"), ("Linux", "comm")])
def test_process_preflight_uses_untruncated_names(monkeypatch, system, name_field):
    monkeypatch.setattr(bench.platform, "system", lambda: system)
    def inventory(command, **kwargs):
        assert command == ["ps", "-axo", f"pid=,{name_field}=,args="]
        return (f"{os.getpid()} Python /long/path/Python tools/benchmark.py\n"
                "999991 Python /long/path/Python -m pytest tests/benchmark\n"
                "999992 quarry /long/repository/path/build/release/quarry demo\n")
    monkeypatch.setattr(bench.subprocess, "check_output", inventory)
    with pytest.raises(RuntimeError, match="Concurrent") as error:
        bench.process_preflight()
    assert '"pid": 999991' in str(error.value)
    assert '"pid": 999992' in str(error.value)
    assert f'"pid": {os.getpid()}' not in str(error.value)


def tiny_manifest():
    return {"version": 1, "seed": 5, "warmups": 2, "repetitions": 7,
            "tracks": ["resident", "prepared"],
            "cases": [{"id": f"q.{engine}.{opt}", "workload": "q", "sql_file": "q.sql", "order_keys": [0],
                       "options": {"engine": engine, "optimizer": opt, "batch_size": 1024,
                                   "build_side": "right", "join_reorder": "off", "profile": False}}
                      for engine in ("scalar", "vector") for opt in ("off", "on")]}


def synthetic_records(manifest):
    records = [{"kind": "header", "mode": "timing", "build_type": "Release",
                "seed": manifest["seed"], "warmups": manifest["warmups"],
                "repetitions": manifest["repetitions"], "case_count": len(manifest["cases"]),
                "ingestion_ns": 1000, "preparation_ns": {c['id']: 10 for c in manifest['cases']}}]
    for phase, repeats in (("warmup", 2), ("recorded", 7)):
        for repeat in range(repeats):
            for case in reversed(manifest["cases"]):
                for track in ("prepared", "resident"):
                    baseline = 200 if case["options"]["engine"] == "scalar" else 400
                    if case["options"]["optimizer"] == "on": baseline -= 50
                    duration = baseline + repeat
                    records.append({"kind": "measurement", "case_id": case["id"], "track": track,
                                    "phase": phase, "repeat": repeat, "order_index": len(records) - 1,
                                    "planning_ns": 0 if track == "prepared" else 10,
                                    "execution_ns": duration, "resident_ns": duration + (0 if track == "prepared" else 10),
                                    "rendering_ns": 20, "output_rows": 1, "output_bytes": 70,
                                    "digest": "typed-digest", "peak_accounted_bytes": 2000,
                                    "current_accounted_bytes": 1000})
    return records


def test_frozen_generator_reproducible_and_bounded(tmp_path):
    first = generate.generate(tmp_path / "a", 37, smoke=True)
    second = generate.generate(tmp_path / "b", 37, smoke=True)
    assert first["fixture"]["sha256"] == second["fixture"]["sha256"]
    manifest = bench.load_manifest(tmp_path / "a/manifest.json")
    assert len(manifest["cases"]) == 56
    assert Counter(case["workload"] for case in manifest["cases"])["scan_selective"] == 8
    bench.check_fixture(tmp_path / "a/manifest.json", manifest)
    with pytest.raises(ValueError, match="million disabled"):
        generate.generate(tmp_path / "million", 1_000_000)
    with pytest.raises(ValueError): generate.generate(tmp_path / "large-smoke", 1001, smoke=True)


def test_recipe_declared_dimensions_and_bounded_join_fanout():
    rows = list(generate.logical_rows("sales", 10000, 20092026))
    assert sum(row[1] < 10 for row in rows) == 100
    assert sum(row[1] < 900 for row in rows) == 9000
    assert sum(row[3] is None for row in rows) == 1000
    assert sum(row[4] is None for row in rows) == 9000
    assert len({row[5] for row in rows}) == 16
    assert len({row[6] for row in rows}) == 2048
    counts = Counter(row[0] for row in generate.logical_rows("customers", 0, 20092026))
    assert max(counts.values()) == 3
    assert all(len(row) == 14 for row in rows)


def test_oracle_settings_and_independent_utf8_order():
    connection = bench.make_oracle({"schemas": {"sales": generate.SALES}, "sales_rows": 31, "seed": 20092026})
    try:
        assert connection.execute("SELECT current_setting('threads')").fetchone()[0] == 1
        assert connection.execute("SELECT current_setting('disabled_optimizers')").fetchone()[0] == "compressed_materialization"
        expected = sorted({row[7] for row in generate.logical_rows("sales", 31, 20092026) if row[7] is not None}) + [None]
        actual = bench.oracle_result(connection, "SELECT region, COUNT(*) AS n FROM sales GROUP BY region ORDER BY region NULLS LAST")
        assert [row[0] for row in actual["rows"]] == expected
    finally: connection.close()


def test_manifest_and_fixture_mutations_fail(tmp_path):
    generate.generate(tmp_path, 13, smoke=True)
    path = tmp_path / "manifest.json"; manifest = bench.load_manifest(path)
    modified = copy.deepcopy(manifest); modified["cases"][0]["options"]["batch_size"] = 7
    with pytest.raises(ValueError, match="frozen finite design"): bench.check_fixture(path, modified)
    (tmp_path / "sales.csv").write_text("corrupted\n")
    with pytest.raises(ValueError, match="fixture hash changed"): bench.check_fixture(path, manifest)
    manifest["cases"][0]["options"]["build_side"] = "left"; path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="matched right builds"): bench.load_manifest(path)


def test_large_exact_partitions_preserve_complete_values_and_multiplicity():
    schema = [{"name": "id", "type": "INT64"}, {"name": "v", "type": "DOUBLE"}]
    expected = {"columns": schema, "rows": [[i, i / 4] for i in range(2500)]}
    actual = {"columns": schema, "rows": list(reversed(expected["rows"]))}
    bench.compare_complete(actual, expected, [])
    actual["rows"][17] = [actual["rows"][17][0], 99999.0]
    with pytest.raises(AssertionError): bench.compare_complete(actual, expected, [])
    duplicates = {"columns": schema, "rows": [[1, 2.0], [1, 2.0], [2, None]]}
    corrupted = {"columns": schema, "rows": [[1, 2.0], [2, None], [2, None]]}
    with pytest.raises(AssertionError): bench.compare_complete(corrupted, duplicates, [])
    corrupted = {"columns": schema, "rows": [[1, 2.0], [1, None], [2, None]]}
    with pytest.raises(AssertionError): bench.compare_complete(corrupted, duplicates, [])


def test_ordered_complete_comparison_respects_ties_and_sequence():
    schema = [{"name": "k", "type": "INT64"}, {"name": "v", "type": "DOUBLE"}]
    expected = {"columns": schema, "rows": [[1, 3.0], [1, 4.0], [2, 5.0]]}
    bench.compare_complete({"columns": schema, "rows": [[1, 4.0], [1, 3.0], [2, 5.0]]}, expected, [0])
    with pytest.raises(AssertionError):
        bench.compare_complete({"columns": schema, "rows": [[2, 5.0], [1, 3.0], [1, 4.0]]}, expected, [0])


def test_approximate_values_cannot_hide_reversed_or_split_float_order_keys():
    schema = [{"name": "v", "type": "DOUBLE"}]
    expected = {"columns": schema, "rows": [[1.0], [1.0 + 5e-11]]}
    reversed_rows = {"columns": schema, "rows": list(reversed(expected["rows"]))}
    with pytest.raises(AssertionError, match="direction"):
        bench.compare_complete(reversed_rows, expected, [0])
    expected["rows"] = [[1.0], [1.0]]
    with pytest.raises(AssertionError, match="tie split"):
        bench.compare_complete(reversed_rows, expected, [0])


def test_verified_release_gate_rejects_unverified_source_or_binary(tmp_path):
    before = {"source": {"sha256": "source"}, "binary_sha256": "binary"}
    gate = {"status": "PASS", "source_unchanged_during_run": True,
            "source_after": {"sha256": "source"}, "binary_sha256": {"release": "binary"}}
    path = tmp_path / "summary.json"; path.write_text(json.dumps(gate))
    assert bench.verify_build_gate(path, before)["status"] == "PASS"
    with pytest.raises(ValueError, match="requires --verification"): bench.verify_build_gate(None, before)
    with pytest.raises(ValueError, match="source differs"):
        bench.verify_build_gate(path, {**before, "source": {"sha256": "changed"}})
    with pytest.raises(ValueError, match="binary differs"):
        bench.verify_build_gate(path, {**before, "binary_sha256": "stale"})


def test_report_uses_all_recorded_samples_and_retains_slowdowns():
    manifest = tiny_manifest(); records = synthetic_records(manifest)
    summary = report.summarize_records(records, manifest)
    assert summary["recorded_trials"] == 56 and summary["warmup_trials"] == 16
    row = next(r for r in summary["summaries"] if r["case_id"] == "q.scalar.off" and r["track"] == "prepared")
    assert row["timings"]["execution_ns"] == {"n": 7, "median": 203, "q1": 201.5, "q3": 204.5, "iqr": 3.0, "min": 200, "max": 206}
    comparisons = summary["comparisons"]
    assert any(r["kind"] == "scalar_vs_vector" and r["observation"] == "slower" for r in comparisons)
    assert any(r["kind"] == "optimizer_off_vs_on" and r["observation"] == "faster" for r in comparisons)
    assert all(len(r["paired_ratios"]) == 7 for r in comparisons)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "failure", "negative", "digest", "order", "prepared_replan", "header", "debug", "duration_sum", "missing_preparation"])
def test_report_rejects_invalid_or_incomplete_native_records(mutation):
    manifest = tiny_manifest(); records = synthetic_records(manifest)
    if mutation == "missing": records.pop()
    elif mutation == "duplicate": records[-1] = dict(records[-2], order_index=records[-1]["order_index"])
    elif mutation == "failure": records[-1]["kind"] = "failure"
    elif mutation == "negative": records[-1]["execution_ns"] = -1
    elif mutation == "digest": records[-1]["digest"] = "changed"
    elif mutation == "order": records[-1]["order_index"] += 1
    elif mutation == "prepared_replan": records[1]["planning_ns"] = 3
    elif mutation == "header": records[0]["seed"] += 1
    elif mutation == "debug": records[0]["build_type"] = "Debug"
    elif mutation == "duration_sum": records[-1]["resident_ns"] += 1
    elif mutation == "missing_preparation": records[0]["preparation_ns"].popitem()
    with pytest.raises(ValueError): report.summarize_records(records, manifest)


def test_complete_validation_never_accepts_a_digest_or_missing_track(tmp_path, monkeypatch):
    manifest = tiny_manifest(); (tmp_path / "q.sql").write_text("SELECT 1 AS v FROM sales")
    expected = {"columns": [{"name": "v", "type": "INT64"}], "rows": [[1]]}
    monkeypatch.setattr(bench, "oracle_result", lambda connection, sql: expected)
    records = [{"kind": "header", "mode": "validation", "seed": 5,
                "warmups": 2, "repetitions": 7, "case_count": 4}]
    for case in manifest["cases"]:
        for track in manifest["tracks"]:
            records.append({"kind": "validation", "case_id": case["id"], "track": track,
                            "result": {"ok": True, "columns": expected["columns"], "rows": [["1"]]}})
    assert bench.validate_records(records, manifest, None, tmp_path / "manifest.json")["validated_case_tracks"] == 8
    with pytest.raises(ValueError, match="missing"): bench.validate_records(records[:-1], manifest, None, tmp_path / "manifest.json")
    records[-1] = {"kind": "measurement", "digest": "not validation"}
    with pytest.raises(ValueError): bench.validate_records(records, manifest, None, tmp_path / "manifest.json")


def test_native_tiny_timing_protocol_only(tmp_path):
    """Five-row protocol smoke, never a performance-study observation."""
    generate.generate(tmp_path, 5, smoke=True)
    path = tmp_path / "manifest.json"; manifest = json.loads(path.read_text())
    manifest["cases"] = [manifest["cases"][0], manifest["cases"][2]]
    path.write_text(json.dumps(manifest))
    binary = Path(os.environ.get("QUARRY_BINARY", ROOT / "build/debug/quarry"))
    def native_records(validate=False):
        command = [str(binary), "bench", "--manifest", str(path)] + (["--validate-only"] if validate else [])
        completed = subprocess.run(command, text=True, capture_output=True, timeout=30)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return [json.loads(line) for line in completed.stdout.splitlines()]
    validation = native_records(True)
    assert len(validation) == 5
    amount_total = sum(row[3] for row in generate.logical_rows("sales", 5, 20092026) if row[3] is not None)
    assert all(record["result"]["rows"] == [["5", amount_total]] for record in validation[1:])
    first, second = native_records(), native_records()
    header = first[0]
    assert header["kind"] == "header" and header["mode"] == "timing"
    assert set(header["preparation_ns"]) == {case["id"] for case in manifest["cases"]}
    wanted = {(case["id"], track, phase, repeat) for case in manifest["cases"] for track in manifest["tracks"]
              for phase, count in (("warmup", 2), ("recorded", 7)) for repeat in range(count)}
    keys = ("case_id", "track", "phase", "repeat")
    assert len(first) == 37
    assert {tuple(record[key] for key in keys) for record in first[1:]} == wanted
    assert [tuple(record[key] for key in keys) for record in first[1:]] == [tuple(record[key] for key in keys) for record in second[1:]]
    assert [record["order_index"] for record in first[1:]] == list(range(36))
    for record in first[1:]:
        assert record["kind"] == "measurement"
        assert record["resident_ns"] == record["planning_ns"] + record["execution_ns"]
        assert record["output_rows"] == 1 and record["output_bytes"] > 0
        assert record["digest"] == first[1]["digest"]
        assert record["peak_accounted_bytes"] >= record["current_accounted_bytes"]
        if record["track"] == "prepared": assert record["planning_ns"] == 0
