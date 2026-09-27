"""Pinned DuckDB string-compression guard; identical SQL, no output rewriting."""
import duckdb
import pytest

from harness import (Column, DUCKDB_VERSION, compare_results, decode_result, duckdb_result,
                     mode_responses, verification_modes, write_catalog)


@pytest.mark.parametrize("direction", ["ASC", "DESC"])
def test_utf8_order_matches_hand_reference_with_oracle_guard(tmp_path, direction):
    assert duckdb.__version__ == DUCKDB_VERSION
    rows = [["comma,value"], ["東京"]]
    sql = f"SELECT s FROM items ORDER BY s {direction}"
    hand = rows if direction == "ASC" else list(reversed(rows))
    # Observe the unmodified pinned engine, but do not require a compiler/host
    # defect to exist on every CI platform. The adapted result is always strict.
    with duckdb.connect() as conn:
        conn.execute("SET threads=1")
        conn.execute("CREATE TABLE items(s VARCHAR)")
        conn.executemany("INSERT INTO items VALUES (?)", rows)
        raw = [list(row) for row in conn.execute(sql).fetchall()]
        assert sorted(raw) == sorted(rows)
        conn.execute("SET disabled_optimizers='compressed_materialization'")
        assert [list(row) for row in conn.execute(sql).fetchall()] == hand
    schema = [Column("s", "STRING")]
    expected = {"columns": [{"name": "s", "type": "STRING"}], "rows": hand}
    compare_results(duckdb_result(rows, schema, sql), expected, (0,))
    catalog = write_catalog(tmp_path, rows, schema)
    for result in mode_responses(catalog, sql, verification_modes()):
        assert result["ok"]
        compare_results(decode_result(result), expected, (0,))
