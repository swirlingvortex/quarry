"""Bounded deterministic Hypothesis cases complement the content-addressed corpus."""
import os

from hypothesis import given, settings, strategies as st

from harness import (Column, compare_results, duckdb_result, quarry_result,
                     save_failure, write_catalog)

EXAMPLES = {"smoke": 5, "core": 40, "extended": 120}[os.environ.get("QUARRY_TEST_PROFILE", "core")]
TRUTH_SCHEMA = [Column("id", "INT64", False), Column("a", "BOOL"), Column("b", "BOOL")]
nullable_bool = st.one_of(st.none(), st.booleans())


def compare_property(catalog, rows, schema, sql, name):
    actual = expected = None
    options = ()
    try:
        expected = duckdb_result(rows, schema, sql)
        for options in (("--optimizer", "off"), ("--optimizer", "on"),
                        ("--engine", "vector", "--batch-size", "7", "--optimizer", "off"),
                        ("--engine", "vector", "--batch-size", "7", "--optimizer", "on")):
            actual = quarry_result(catalog, sql, *options)
            compare_results(actual, expected, (0,))
    except Exception:
        # The final shrunken failure overwrites this artifact. Inputs are saved
        # verbatim; seed=-1 denotes Hypothesis derandomize=True, database=None.
        artifact = save_failure(name, catalog, sql, -1, actual, expected, options)
        print(f"Hypothesis reproducer preserved at {artifact}")
        raise


@settings(max_examples=EXAMPLES, derandomize=True, database=None, deadline=None)
@given(pairs=st.lists(st.tuples(nullable_bool, nullable_bool), min_size=0, max_size=16))
def test_generated_three_valued_logic(pairs, tmp_path_factory):
    rows = [[i, a, b] for i, (a, b) in enumerate(pairs)]
    catalog = write_catalog(tmp_path_factory.mktemp("truth"), rows, TRUTH_SCHEMA)
    sql = "SELECT id, a AND b AS both, a OR b AS either, NOT a AS opposite FROM items ORDER BY id"
    compare_property(catalog, rows, TRUTH_SCHEMA, sql, "hypothesis-three-valued-logic")


@settings(max_examples=EXAMPLES, derandomize=True, database=None, deadline=None)
@given(values=st.lists(st.one_of(st.none(), st.text(alphabet=["a", "Z", "é", "東", ",", '"', "\n", "\\", "N"], max_size=32)), max_size=12))
def test_generated_csv_round_trip(values, tmp_path_factory):
    schema = [Column("id", "INT64", False), Column("s", "STRING")]
    rows = [[i, value] for i, value in enumerate(values)]
    catalog = write_catalog(tmp_path_factory.mktemp("csv"), rows, schema, newline="\r\n")
    sql = "SELECT id, s FROM items ORDER BY id"
    compare_property(catalog, rows, schema, sql, "hypothesis-csv-roundtrip")
