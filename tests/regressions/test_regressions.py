import json
from pathlib import Path
import sys
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "differential"))
from harness import BINARY, Column, quarry_result, run_query, write_catalog

CASES = json.loads((Path(__file__).parent / "numeric_cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["sql"])
def test_hand_computed_numeric_regressions(tmp_path, case):
    catalog = write_catalog(tmp_path, [[1]], [Column("id", "INT64")])
    assert quarry_result(catalog, case["sql"])["rows"] == case["rows"]


@pytest.mark.parametrize(("kind", "token"), [("INT64", "+-1"), ("DOUBLE", "+-1.5")])
def test_csv_rejects_multiple_signs(tmp_path, kind, token):
    catalog = write_catalog(tmp_path, [], [Column("n", kind)])
    (tmp_path / "data.csv").write_text(f"n\n{token}\n")
    proc, result = run_query(catalog, "SELECT n FROM items")
    assert proc.returncode != 0 and result["error"]["code"] == "CSV", result


@pytest.mark.parametrize("expression", ["(NULL + NULL) = 'x'", "NOT -NULL", "(NULL / NULL) + 1"])
def test_contextual_null_inference_preserves_operator_type_constraints(tmp_path, expression):
    catalog = write_catalog(tmp_path, [[1]], [Column("id", "INT64")])
    proc, result = run_query(catalog, f"SELECT {expression} AS bad FROM items")
    assert proc.returncode != 0 and result["error"]["code"] == "TYPE", result


def test_session_deep_json_request_is_bounded_and_recovers(tmp_path):
    catalog = write_catalog(tmp_path, [[1]], [Column("id", "INT64")])
    deep = '{"id":' + "[" * 10000 + "0" + "]" * 10000 + ',"sql":"SELECT id FROM items"}'
    valid = json.dumps({"id": "after-depth-error", "sql": "SELECT id FROM items"})
    proc = subprocess.run([str(BINARY), "session", "--stdio", "--catalog", str(catalog)],
                          input=deep + "\n" + valid + "\n", text=True,
                          capture_output=True, timeout=30)
    assert proc.returncode == 0, proc
    failure, success = [json.loads(line) for line in proc.stdout.splitlines()]
    assert failure["ok"] is False and failure["error"]["code"] in {"RESOURCE", "PROTOCOL"}, failure
    assert success["id"] == "after-depth-error" and success["rows"] == [["1"]]


def test_deep_catalog_json_is_bounded(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"tables":[],"ignored":' + "[" * 10000 + "0" + "]" * 10000 + "}")
    proc, result = run_query(catalog, "SELECT id FROM items")
    assert proc.returncode > 0 and result["ok"] is False, result
    assert result["error"]["code"] in {"RESOURCE", "CATALOG"}, result
