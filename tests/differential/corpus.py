"""Content-addressed deterministic corpus; configuration repetitions are separate."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import random

from harness import Column, QUERIES, SCHEMA, generated_rows

PROFILE_SEED_COUNTS = {"smoke": (1, 1), "core": (32, 20), "extended": (64, 40)}

JOIN_SCHEMA = [Column("id", "INT64", False), Column("k", "INT64"),
               Column("b", "BOOL"), Column("s", "STRING"),
               Column("n", "INT64"), Column("d", "DOUBLE")]


def join_tables(seed):
    rng = random.Random(51032026 + seed)
    left_count, right_count = [(0, 0), (0, 3), (3, 0), (1, 1), (7, 5), (13, 11)][seed % 6]

    def rows(count, offset):
        return [[offset + i, rng.choice([None, 0, 0, 1, 2, 3]),
                 rng.choice([None, False, True]),
                 rng.choice([None, "", "a", "é", "x" * 257]),
                 rng.choice([None, -2, 0, 1, 3]),
                 rng.choice([None, -0.5, 0.25, 1.25, 2.75])]
                for i in range(count)]
    return {"left_items": (JOIN_SCHEMA, rows(left_count, 0)),
            "right_items": (JOIN_SCHEMA, rows(right_count, 100))}


PREFIX = "FROM left_items AS l INNER JOIN right_items AS r ON "
JOIN_QUERIES = [
    ("SELECT l.id AS lid, r.id AS rid, l.n AS left_n, r.s AS right_s " + PREFIX + "l.k = r.k ORDER BY lid, rid", (0, 1)),
    ("SELECT * " + PREFIX + "l.k = r.k", ()),
    ("SELECT l.id AS lid, r.id AS rid, l.n AS left_n, r.s AS right_s " + PREFIX + "l.k = r.k AND l.b = r.b ORDER BY lid, rid", (0, 1)),
    ("SELECT l.id AS lid, r.id AS rid, l.n AS left_n, r.s AS right_s " + PREFIX + "l.s = r.s ORDER BY lid, rid", (0, 1)),
    ("SELECT l.k AS key, COUNT(*) AS rows, SUM(l.n + r.n) AS total, AVG(l.d) AS mean_d, MIN(r.s) AS first_s " + PREFIX + "l.k = r.k GROUP BY l.k ORDER BY key", (0,)),
    ("SELECT l.b AS flag, r.s AS text_value, COUNT(*) AS rows, SUM(r.d) AS total " + PREFIX + "l.k = r.k WHERE l.n > 0 AND r.n IS NOT NULL GROUP BY l.b, r.s ORDER BY flag, text_value", (0, 1)),
    ("SELECT COUNT(*) AS rows, COUNT(r.n) AS values_n, SUM(l.n) AS total, MIN(l.s) AS first_s, MAX(r.b) AS max_b " + PREFIX + "l.k = r.k WHERE l.id < 0", ()),
    ("SELECT r.id AS rid, l.id AS lid, l.d + r.d AS joined_d " + PREFIX + "l.k = r.k WHERE l.n IS NULL OR r.b = TRUE ORDER BY 3 DESC NULLS LAST, 1, 2 LIMIT 7", (2, 0, 1)),
    ("SELECT COUNT(*) + 1 AS rows_plus, SUM(l.n * 2) AS total " + PREFIX + "l.k = r.k LIMIT 0", ()),
    ("SELECT l.id AS lid, r.id AS rid, l.n AS left_n, r.s AS right_s " + PREFIX + "r.k = l.k ORDER BY lid, rid", (0, 1)),
    ("SELECT l.id AS lid, r.id AS rid " + PREFIX + "l.b = r.b WHERE (l.n = 0 OR r.n = 0) AND l.s IS NOT NULL ORDER BY lid, rid", (0, 1)),
    ("SELECT l.id AS lid, r.id AS rid FROM left_items AS l INNER JOIN left_items AS r ON l.k = r.k ORDER BY lid, rid", (0, 1)),
]

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def typed_content(tables):
    return {name: {"columns": [vars(column) for column in columns], "rows": rows}
            for name, (columns, rows) in tables.items()}


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def single_tables(seed):
    return {"items": (SCHEMA, generated_rows(seed))}


def distinct_seeds(kind, profile):
    """Deduplicate data itself, never count repeated empty fixtures as new cases."""
    count = PROFILE_SEED_COUNTS[profile][kind == "join"]
    make = join_tables if kind == "join" else single_tables
    selected, seen = [], set()
    seed = 5 if profile == "smoke" and kind == "join" else 3 if profile == "smoke" else 0
    while len(selected) < count:
        content_hash = digest(typed_content(make(seed)))
        if content_hash not in seen:
            selected.append(seed)
            seen.add(content_hash)
        seed += 1
        assert seed < 10000, "bounded seed search exhausted"
    return selected


def case_record(kind, seed, family):
    sql, order_keys = (JOIN_QUERIES if kind == "join" else QUERIES)[family]
    tables = (join_tables if kind == "join" else single_tables)(seed)
    data = typed_content(tables)
    content = {"sql": sql, "tables": data}
    return {"case_id": f"{kind}-seed-{seed}-family-{family}", "kind": kind,
            "seed": seed, "family": family, "order_keys": list(order_keys),
            "content_sha256": digest(content), "data_sha256": digest(data),
            "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(), "content": content}


def case_records(profile):
    records = [case_record(kind, seed, family)
               for kind, queries in (("single", QUERIES), ("join", JOIN_QUERIES))
               for seed in distinct_seeds(kind, profile) for family in range(len(queries))]
    assert len({record["case_id"] for record in records}) == len(records)
    assert len({record["content_sha256"] for record in records}) == len(records), "duplicate SQL/data case"
    return records


def record_success(kind, seed, family, configurations):
    """Verifier owns a new receipt file per build; append only after all checks pass."""
    destination = os.environ.get("QUARRY_CASE_RECEIPTS")
    if destination:
        case = case_record(kind, seed, family)
        receipt = {key: case[key] for key in ("case_id", "content_sha256")}
        receipt["configurations_passed"] = configurations
        with Path(destination).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, sort_keys=True) + "\n")
