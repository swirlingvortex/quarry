"""Long-lived protocol recovery, resource unwinding, and adapter equivalence."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "differential"))
from harness import (Column, compare_results, decode_result, mode_responses, quarry_result,
                     run_session, verification_modes, write_catalog)


def test_batched_session_adapter_matches_one_shot_for_every_configuration(tmp_path):
    catalog = write_catalog(tmp_path, [[1, "é"], [None, ""], [1, "é"], [2, None]],
                            [Column("k", "INT64"), Column("s", "STRING")])
    sql = "SELECT k, s, COUNT(*) AS n FROM items GROUP BY k, s ORDER BY k DESC NULLS FIRST, s"
    modes = verification_modes()
    for (_, flags), result in zip(modes, mode_responses(catalog, sql, modes)):
        assert result["ok"]
        compare_results(decode_result(result), quarry_result(catalog, sql, *flags), (0, 1))


@pytest.mark.parametrize("engine", ["scalar", "vector"])
def test_resource_failures_between_successes_do_not_leak_or_change_defaults(tmp_path, engine):
    catalog = write_catalog(tmp_path, [[i, "界" * 100 + str(i)] for i in range(11)],
                            [Column("n", "INT64"), Column("s", "STRING")])
    valid = "SELECT COUNT(*) AS n, MIN(s) AS first_s FROM items"
    failures = ["SELECT n, s FROM items LIMIT 0", "SELECT n, COUNT(*) AS nrows FROM items GROUP BY n LIMIT 1",
                "SELECT n, s FROM items ORDER BY s LIMIT 1"]
    requests = [{"id": "first", "sql": valid}]
    for repeat in range(20):
        for sql in failures:
            requests += [{"id": f"bad-{repeat}-{len(requests)}", "sql": sql}, {"id": len(requests), "sql": valid}]
    responses = run_session(catalog, requests, "--engine", engine, "--batch-size", "7", "--result-limit", "2")
    first = responses[0]
    assert first["ok"]
    for request, response in zip(requests, responses):
        assert response["id"] == request["id"]
        if request["sql"] == valid:
            assert response["ok"] and response["rows"] == first["rows"]
            assert response["stats"]["current_accounted_bytes"] == first["stats"]["current_accounted_bytes"]
        else:
            assert not response["ok"] and response["error"]["code"] == "RESOURCE" and "rows" not in response


@pytest.mark.parametrize("engine", ["scalar", "vector"])
def test_malformed_protocol_ids_and_unicode_recover_in_same_session(tmp_path, engine):
    catalog = write_catalog(tmp_path, [[7]], [Column("n", "INT64")])
    malformed = ["", "null", "true", "42", "[]", '"text"', "{", "{}",
                 '{"sql":null}', '{"sql":[]}', '{"sql":"SELECT n FROM items","options":[]}',
                 '{"sql":"SELECT n FROM items","options":{"batch_size":true}}',
                 '{"sql":"SELECT n FROM items","options":{"engine":null}}',
                 '{"sql":"SELECT n FROM items","options":{"optimizer":true}}',
                 '{"sql":"SELECT n FROM items","options":{"profile":"true"}}',
                 '{"sql":"\\ud800"}', '{"sql":"\\udc00"}',
                 '{"id":' + "[" * 130 + "0" + "]" * 130 + ',"sql":"SELECT n FROM items"}',
                 "x" * 131073]
    requests = []
    for index, line in enumerate(malformed):
        requests += [line, {"id": {"index": index, "text": "é東", "opaque": [True, None, 2**63 - 1]},
                            "sql": "SELECT n FROM items"}]
    responses = run_session(catalog, requests, "--engine", engine)
    for index in range(0, len(responses), 2):
        bad, good = responses[index:index + 2]
        assert not bad["ok"] and "rows" not in bad
        assert bad["error"]["code"] in {"PROTOCOL", "RESOURCE", "CLI"}
        assert good["ok"] and good["rows"] == [["7"]] and good["id"] == requests[index + 1]["id"]
