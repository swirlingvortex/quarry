#!/usr/bin/env python3
"""Generate Quarry's original, compact deterministic retail fixture (offline)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random

GENERATOR_VERSION = "retail-v2"
DEFAULT_SEED = 19092026
ROOT = Path(__file__).resolve().parents[1]
SCHEMA = [
    {"name": "sale_id", "type": "INT64", "nullable": False},
    {"name": "region", "type": "STRING", "nullable": True},
    {"name": "product", "type": "STRING", "nullable": False},
    {"name": "units", "type": "INT64", "nullable": True},
    {"name": "amount", "type": "DOUBLE", "nullable": True},
    {"name": "promoted", "type": "BOOL", "nullable": True},
    {"name": "note", "type": "STRING", "nullable": True},
    {"name": "customer_id", "type": "INT64", "nullable": True},
]
CUSTOMER_SCHEMA = [
    {"name": "customer_id", "type": "INT64", "nullable": True},
    {"name": "region", "type": "STRING", "nullable": True},
    {"name": "segment", "type": "STRING", "nullable": True},
]
SINGLE_QUERY = """-- Preserved single-table example from the M3 milestone.
SELECT region, COUNT(*) AS orders, SUM(amount) AS revenue
FROM sales
WHERE amount >= 50.0
GROUP BY region
ORDER BY revenue DESC NULLS LAST, region ASC NULLS LAST
LIMIT 10;
"""
QUERY = """SELECT c.region, COUNT(*) AS orders, SUM(s.amount) AS revenue
FROM sales AS s
INNER JOIN customers AS c ON s.customer_id = c.customer_id
WHERE s.amount >= 50.0
GROUP BY c.region
ORDER BY revenue DESC NULLS LAST, region ASC
LIMIT 10;
"""


def csv_field(value: object) -> str:
    if value is None:
        return "\\N"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        # Quote every string: literal backslash-N must remain different from NULL.
        return '"' + value.replace('"', '""') + '"'
    return str(value)


def generate(output: Path, rows: int = 96, seed: int = DEFAULT_SEED) -> dict:
    if not 0 <= rows <= 100_000:
        raise ValueError("fixture generation is bounded to 0..100000 rows")
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    regions = ["North", "North", "North", "South", "West", "東京", None]
    notes = ["", "\\N", "gift, wrapped", 'customer said "thanks"',
             "two\nlines", "café", "long:" + "retail-" * 80, None]
    content = [",".join(column["name"] for column in SCHEMA)]
    customer_keys = [1, 1, 1, 1, 2, 3, 4, 7, 9, 99, None]
    for i in range(rows):
        row = [i + 1, rng.choice(regions), f"product-{i % 41:03}",
               None if i % 11 == 0 else rng.randint(1, 8),
               None if i % 13 == 0 else rng.randint(1, 1600) / 4.0,
               None if i % 7 == 0 else i % 3 == 0, notes[i % len(notes)],
               customer_keys[i % len(customer_keys)]]
        content.append(",".join(csv_field(value) for value in row))
    (output / "sales.csv").write_text("\n".join(content) + "\n", encoding="utf-8")
    customers = [
        [1, "North", "member"], [1, "West", "duplicate-key"], [1, None, "duplicate-key"],
        [2, "South", None], [3, "West", ""], [4, "東京", "café"],
        [7, "North", 'quoted,"segment"'], [9, "South", "long:" + "retail-" * 80],
        [50, "Unmatched", "no-sales"], [51, "North", "no-sales"],
        [None, "Null key", "must-not-match"],
    ]
    customer_lines = [",".join(column["name"] for column in CUSTOMER_SCHEMA)]
    customer_lines += [",".join(csv_field(value) for value in row) for row in customers]
    (output / "customers.csv").write_text("\n".join(customer_lines) + "\n", encoding="utf-8")
    catalog = {"tables": [{"name": "sales", "path": "sales.csv", "columns": SCHEMA},
                           {"name": "customers", "path": "customers.csv", "columns": CUSTOMER_SCHEMA}]}
    (output / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
    (output / "query.sql").write_text(QUERY)
    (output / "query-single.sql").write_text(SINGLE_QUERY)
    manifest = {
        "generator_version": GENERATOR_VERSION, "seed": seed, "rows": rows,
        "scope": "M5 joined retail correctness/demo; no performance claims",
        "schemas": {"sales": SCHEMA, "customers": CUSTOMER_SCHEMA},
        "customer_rows": len(customers),
        "sha256": {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                   for name in ("sales.csv", "customers.csv", "catalog.json", "query.sql", "query-single.sql")},
    }
    (output / "fixture.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "examples")
    parser.add_argument("--rows", type=int, default=96)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    print(json.dumps(generate(args.output, args.rows, args.seed), indent=2))


if __name__ == "__main__":
    main()
