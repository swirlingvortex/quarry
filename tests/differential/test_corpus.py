"""Counts are tied to actual content, not seed labels or configuration repeats."""
import copy

import pytest

from corpus import case_records, digest


@pytest.mark.parametrize(("profile", "single", "joined"), [("smoke", 24, 12),
    ("core", 768, 240), ("extended", 1536, 480)])
def test_saved_corpus_is_distinct_reproducible_and_bounded(profile, single, joined):
    first = case_records(profile)
    assert first == case_records(profile)
    assert len(first) == single + joined
    assert sum(case["kind"] == "single" for case in first) == single
    assert len({case["content_sha256"] for case in first}) == len(first)
    for case in first:
        assert digest(case["content"]) == case["content_sha256"]
        for table in case["content"]["tables"].values():
            assert len(table["rows"]) <= (13 if case["kind"] == "join" else 64)


def test_case_identity_changes_with_sql_schema_and_data():
    case = next(case for case in case_records("core") if case["content"]["tables"]["items"]["rows"])
    for mutation in ("sql", "schema", "data"):
        content = copy.deepcopy(case["content"])
        if mutation == "sql":
            content["sql"] += " LIMIT 0"
        elif mutation == "schema":
            content["tables"]["items"]["columns"][0]["nullable"] = True
        else:
            content["tables"]["items"]["rows"][0][0] += 1
        assert digest(content) != case["content_sha256"]
