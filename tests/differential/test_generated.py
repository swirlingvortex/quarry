"""768 distinct deterministic query/data cases in core; 1536 in extended."""
import os

import pytest

from harness import (QUERIES, SCHEMA, compare_results, decode_result, duckdb_result,
                     verification_modes, generated_rows, mode_responses, save_failure, write_catalog)
from corpus import distinct_seeds, record_success

PROFILE = os.environ.get("QUARRY_TEST_PROFILE", "core")
SEEDS = distinct_seeds("single", PROFILE)


@pytest.mark.parametrize("family", range(len(QUERIES)))
@pytest.mark.parametrize("seed", SEEDS)
def test_generated_query_data_case(tmp_path, family, seed):
    sql, order_keys = QUERIES[family]
    rows = generated_rows(seed)
    catalog = write_catalog(tmp_path, rows)
    actual = None
    expected = None
    modes = verification_modes()
    try:
        responses = mode_responses(catalog, sql, modes)
    except Exception as error:
        artifact = save_failure(f"seed-{seed}-family-{family}-session", catalog, sql,
                                seed, {"session_error": repr(error), "modes": modes}, expected)
        print(f"Session reproducer preserved at {artifact}")
        raise
    for (mode, options), response in zip(modes, responses):
        actual = None
        try:
            if expected is None:
                expected = duckdb_result(rows, SCHEMA, sql)
            assert response.get("ok") is True, response
            assert isinstance(response.get("stats", {}).get("peak_accounted_bytes"), int), response
            actual = decode_result(response)
            compare_results(actual, expected, order_keys)
        except Exception:
            artifact = save_failure(f"seed-{seed}-family-{family}-{mode}", catalog, sql,
                                    seed, actual, expected, options)
            print(f"Reproducer preserved at {artifact}")
            raise
    record_success("single", seed, family, len(modes))
