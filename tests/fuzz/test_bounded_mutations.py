"""Deterministic bounded protocol/parser/CSV mutation checks, not coverage claims."""
import json
import os
from pathlib import Path
import random
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "differential"))
from harness import Column, decode_result, run_query, run_session, write_catalog

PROFILE = os.environ.get("QUARRY_TEST_PROFILE", "core")
MUTATIONS = {"smoke": 24, "core": 128, "extended": 384}[PROFILE]
CSV_CASES = {"smoke": 8, "core": 48, "extended": 96}[PROFILE]
ALLOWED_ERRORS = {"PARSE", "BIND", "TYPE", "UNSUPPORTED", "NUMERIC", "RESOURCE"}


def mutated_sql():
    rng = random.Random(7092026)
    bases = ["SELECT n FROM items", "SELECT SUM(n) AS total FROM items WHERE n > 0",
             "SELECT n, COUNT(*) FROM items GROUP BY n ORDER BY n LIMIT 2",
             "SELECT 1 / n AS ratio FROM items", "SELECT (n + 1) * 2 AS value FROM items"]
    fragments = ["(", ")", "'", "--", ";", "NULL", "é", "\x00", ",", " + ", " / 0 ", "9223372036854775808", " "]
    seen = set()
    while len(seen) < MUTATIONS:
        sql = rng.choice(bases)
        at = rng.randrange(len(sql) + 1)
        end = min(len(sql), at + rng.randrange(5))
        sql = sql[:at] + rng.choice(fragments) + sql[end:]
        if sql not in seen:
            seen.add(sql)
            yield sql


@pytest.mark.parametrize("engine", ["scalar", "vector"])
@pytest.mark.parametrize("optimizer", ["off", "on"])
def test_parser_mutations_are_bounded_and_session_recovers(tmp_path, engine, optimizer):
    catalog = write_catalog(tmp_path, [[0], [1], [None], [-2]], [Column("n", "INT64")])
    mutations = list(mutated_sql())
    assert len(set(mutations)) == MUTATIONS and max(map(len, mutations)) < 256
    (tmp_path / "mutations.json").write_text(json.dumps({"seed": 7092026, "sql": mutations}, ensure_ascii=True))
    requests = []
    for index, sql in enumerate(mutations):
        requests += [{"id": f"mutation-{index}", "sql": sql},
                     {"id": f"recovery-{index}", "sql": "SELECT COUNT(*) AS n FROM items"}]
    responses = run_session(catalog, requests, "--engine", engine, "--optimizer", optimizer, "--batch-size", "7")
    for index in range(0, len(responses), 2):
        mutated, recovery = responses[index:index + 2]
        assert mutated["id"] == requests[index]["id"]
        if mutated["ok"]:
            decode_result(mutated)
        else:
            assert mutated["error"]["code"] in ALLOWED_ERRORS and "rows" not in mutated
        assert recovery["ok"] and recovery["id"] == requests[index + 1]["id"] and recovery["rows"] == [["4"]]
        assert recovery["stats"]["current_accounted_bytes"] == responses[1]["stats"]["current_accounted_bytes"]


@pytest.mark.parametrize("seed", range(CSV_CASES))
def test_csv_byte_mutations_return_structured_bounded_results(tmp_path, seed):
    rng = random.Random(17092026 + seed)
    kind = ["INT64", "DOUBLE", "BOOL", "STRING"][seed % 4]
    catalog = write_catalog(tmp_path, [], [Column("n", kind)])
    atoms = [b"\\N", b'"', b",", b"\r", b"\n", b"0", b"1", b"true", b"false", b"-", b"+",
             b"\xff", b"\x00", "é".encode(), b"1e309", b'"escaped""quote"']
    body = b"n\n" + b"".join(rng.choice(atoms) for _ in range(rng.randrange(1, 40))) + b"\n"
    assert len(body) < 1024
    (tmp_path / "data.csv").write_bytes(body)
    proc, result = run_query(catalog, "SELECT n FROM items")
    assert proc.returncode >= 0, "native process terminated by signal"
    if result["ok"]:
        assert proc.returncode == 0
        decode_result(result)
        assert len(result["rows"]) <= len(body)
    else:
        assert proc.returncode != 0 and result["error"]["code"] == "CSV" and "rows" not in result
