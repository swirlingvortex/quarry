"""Deliberate corruptions prove the oracle comparator rejects false passes."""
import copy

import pytest

from harness import compare_results, decode_result

REFERENCE = {
    "columns": [{"name": "n", "type": "INT64"}, {"name": "s", "type": "STRING"},
                {"name": "d", "type": "DOUBLE"}],
    "rows": [[9223372036854775807, "x", 2.25], [9223372036854775807, "x", 2.25],
             [None, "", None]],
}


@pytest.mark.parametrize("corruption", ["duplicate", "columns", "null", "integer", "float"])
def test_comparator_rejects_corrupted_results(corruption):
    actual = copy.deepcopy(REFERENCE)
    if corruption == "duplicate":
        actual["rows"].pop(0)
    elif corruption == "columns":
        actual["columns"].reverse()
    elif corruption == "null":
        actual["rows"][-1][0] = 0
    elif corruption == "integer":
        actual["rows"][0][0] = int(float(9223372036854775807))
    else:
        actual["rows"][0][2] += 1e-4
    with pytest.raises(AssertionError):
        compare_results(actual, REFERENCE)


def test_comparator_preserves_duplicates_and_order_ties():
    reference = {"columns": [{"name": "key", "type": "INT64"},
                             {"name": "value", "type": "STRING"}],
                 "rows": [[1, "a"], [1, "a"], [1, "b"], [2, "z"]]}
    reordered = copy.deepcopy(reference)
    reordered["rows"] = [[1, "b"], [1, "a"], [1, "a"], [2, "z"]]
    compare_results(reordered, reference, (0,))
    reordered["rows"].reverse()
    compare_results(reordered, reference)
    with pytest.raises(AssertionError):
        compare_results(reordered, reference, (0,))


def test_comparator_approximate_matching_does_not_drop_multiplicity():
    reference = {"columns": [{"name": "d", "type": "DOUBLE"}],
                 "rows": [[1.0], [1.0], [2.0]]}
    actual = copy.deepcopy(reference)
    actual["rows"] = [[2.0 + 1e-12], [1.0 + 1e-12], [1.0]]
    compare_results(actual, reference)
    actual["rows"] = [[2.0], [2.0], [1.0]]
    with pytest.raises(AssertionError):
        compare_results(actual, reference)


@pytest.mark.parametrize("cell", [9223372036854775807, "9223372036854775808", "01", "+1"])
def test_protocol_decoder_rejects_lossy_or_noncanonical_int64(cell):
    with pytest.raises(AssertionError):
        decode_result({"columns": [{"name": "n", "type": "INT64"}], "rows": [[cell]]})


@pytest.mark.parametrize(("kind", "value"), [("DOUBLE", True), ("DOUBLE", "1.5"),
    ("DOUBLE", float("nan")), ("DOUBLE", float("inf")), ("DOUBLE", float("-inf")),
    ("BOOL", 0), ("BOOL", "true"), ("STRING", 7), ("UNKNOWN", None)])
def test_decoder_rejects_corrupt_domain_even_for_null(kind, value):
    with pytest.raises(AssertionError):
        decode_result({"columns": [{"name": "x", "type": kind}], "rows": [[value]]})


@pytest.mark.parametrize("rows", [[["1", "extra"]], [[]], ["1"], "1"])
def test_decoder_rejects_corrupt_row_shape(rows):
    with pytest.raises(AssertionError):
        decode_result({"columns": [{"name": "x", "type": "INT64"}], "rows": rows})


@pytest.mark.parametrize("bad", [True, float("inf"), float("nan")])
def test_comparator_rejects_invalid_double_domain(bad):
    schema = [{"name": "x", "type": "DOUBLE"}]
    with pytest.raises(AssertionError):
        compare_results({"columns": schema, "rows": [[bad]]}, {"columns": schema, "rows": [[1.0]]})


def test_approximate_matching_requires_augmenting_path():
    schema = [{"name": "d", "type": "DOUBLE"}]
    # Greedily retaining the exact 1.0 pair would strand the second actual row.
    compare_results({"columns": schema, "rows": [[1.0], [1.0 - 0.8e-10]]},
                    {"columns": schema, "rows": [[1.0], [1.0 + 0.8e-10]]})


def test_large_exact_duplicate_multiset_has_no_recursion_limit():
    schema = [{"name": "i", "type": "INT64"}]
    expected = {"columns": schema, "rows": [[1]] * 1500 + [[None], [2]]}
    actual = {"columns": schema, "rows": list(reversed(expected["rows"]))}
    compare_results(actual, expected)
    actual["rows"][0] = [1]
    with pytest.raises(AssertionError):
        compare_results(actual, expected)


def test_nearby_double_sort_keys_cannot_be_reversed_within_tolerance():
    schema = [{"name": "d", "type": "DOUBLE"}]
    expected = {"columns": schema, "rows": [[1.0], [1.0 + 1e-12]]}
    actual = {"columns": schema, "rows": list(reversed(expected["rows"]))}
    compare_results(actual, expected)
    with pytest.raises(AssertionError):
        compare_results(actual, expected, (0,))


def test_mixed_direction_null_ties_and_secondary_keys():
    schema = [{"name": "a", "type": "INT64"}, {"name": "b", "type": "BOOL"},
              {"name": "s", "type": "STRING"}]
    expected = {"columns": schema, "rows": [[None, True, "a"], [None, True, "b"],
        [None, False, "c"], [3, True, "d"], [1, None, "e"]]}
    actual = copy.deepcopy(expected)
    actual["rows"][:2] = list(reversed(actual["rows"][:2]))
    compare_results(actual, expected, (0, 1))
    actual["rows"][2:4] = list(reversed(actual["rows"][2:4]))
    with pytest.raises(AssertionError):
        compare_results(actual, expected, (0, 1))
