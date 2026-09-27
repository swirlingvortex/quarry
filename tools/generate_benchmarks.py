#!/usr/bin/env python3
"""Generate deterministic local benchmark inputs; never execute measurements."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "benchmarks/suite.json"
VERSION = "quarry-retail-bench-v1"
REGIONS = ["North", "South", "West", "East", "café", "東京", "", "\\N"]

def schema(columns):
    return [{"name": name, "type": kind, "nullable": nullable} for name, kind, nullable in columns]

SALES = schema([
    ("sale_id", "INT64", False), ("bucket", "INT64", False),
    ("units", "INT64", False), ("amount", "DOUBLE", True),
    ("sparse_amount", "DOUBLE", True), ("group_low", "INT64", False),
    ("group_high", "INT64", False), ("region", "STRING", True),
    ("product", "STRING", False), ("promoted", "BOOL", True),
    ("note", "STRING", False), ("customer_id", "INT64", True),
    ("skew_customer_id", "INT64", True), ("padding", "STRING", False),
])
CUSTOMERS = schema([("customer_id", "INT64", True), ("region", "STRING", True),
                    ("segment", "STRING", False)])

def logical_rows(table: str, rows: int, seed: int):
    """Exact typed recipe shared by CSV creation and independent typed oracle input."""
    if table == "customers":
        for key in range(1, 257):
            for duplicate in range(3 if key % 8 == 0 else 1):
                yield [key, REGIONS[(key + duplicate) % 8], f"segment-{duplicate}"]
        yield [None, None, "null key never matches"]
        yield [999, "unmatched", "no sales"]
        return
    if table != "sales":
        raise ValueError("unknown logical table")
    for i in range(rows):
        amount = ((i * 73 + seed) % 40000) / 4.0
        key = 1 + (i * 37 + seed) % 256
        hot = 1 + (i // 5) % 8 if i % 5 != 0 else key
        yield [i + 1, i % 1000, 1 + (i * 17 + seed) % 20,
               None if i % 10 == 0 else amount,
               amount if i % 10 == 0 else None, i % 16, i % 2048,
               None if i % 13 == 0 else REGIONS[(i * 17 + seed) % 8],
               f"product-{i % 127:03d}", None if i % 11 == 0 else i % 3 == 0,
               f'order {i % 19}, "retail"\n' + "x" * (i % 33),
               None if i % 29 == 0 else key, None if i % 29 == 0 else hot,
               "wide-unused-" + "p" * 48]

def field(value):
    if value is None: return "\\N"
    if type(value) is bool: return "true" if value else "false"
    if isinstance(value, str): return '"' + value.replace('"', '""') + '"'
    return str(value)

def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""): hasher.update(block)
    return hasher.hexdigest()

def definition_hashes() -> dict:
    suite = json.loads(SUITE.read_text())
    paths = [SUITE, *[SUITE.parent / w["sql_file"] for w in suite["workloads"]]]
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}

def check_design_lock() -> None:
    lock = json.loads((ROOT / "benchmarks/design-lock.json").read_text())
    if lock["sha256"] != definition_hashes():
        raise ValueError("benchmark definitions changed since their pre-measurement freeze")

def make_cases(suite: dict, output: Path) -> list:
    cases = []
    for workload in suite["workloads"]:
        modes = [("scalar", 1024), ("vector", suite["primary_batch_size"])]
        if workload["id"] in suite["batch_sweep_workloads"]:
            modes.extend(("vector", size) for size in suite["extra_batch_sizes"])
        for engine, batch in modes:
            for optimizer in ("off", "on"):
                cases.append({"id": f"{workload['id']}.{engine}.b{batch}.{optimizer}",
                              "workload": workload["id"],
                              "sql_file": os.path.relpath(SUITE.parent / workload["sql_file"], output),
                              "order_keys": workload["order_keys"],
                              "options": {"engine": engine, "batch_size": batch,
                                          "optimizer": optimizer, "build_side": "right",
                                          "join_reorder": "off", "profile": False}})
    return cases

def generate(output: Path, rows: int, seed: int | None = None, smoke: bool = False) -> dict:
    suite = json.loads(SUITE.read_text()); check_design_lock()
    if rows not in suite["profiles"] and not (smoke and 0 <= rows <= 1000):
        raise ValueError("only 10000/100000 rows or explicit bounded --smoke <=1000 are permitted; million disabled")
    seed = suite["seed"] if seed is None else seed
    output = output.resolve(); output.mkdir(parents=True, exist_ok=True)
    tables = []
    for name, columns in (("sales", SALES), ("customers", CUSTOMERS)):
        target = output / f"{name}.csv"
        with target.open("w", encoding="utf-8", newline="") as sink:
            sink.write(",".join(c["name"] for c in columns) + "\n")
            for row in logical_rows(name, rows, seed): sink.write(",".join(map(field, row)) + "\n")
        tables.append({"name": name, "path": target.name, "columns": columns})
    (output / "catalog.json").write_text(json.dumps({"tables": tables}, indent=2) + "\n")
    fixture = {"version": VERSION, "sales_rows": rows, "seed": seed,
               "customer_rows": sum(1 for _ in logical_rows("customers", rows, seed)),
               "schemas": {t["name"]: t["columns"] for t in tables},
               "recipe_source_sha256": digest(Path(__file__)),
               "recipe": "logical_rows in tools/generate_benchmarks.py; exact quarters, periodic nulls, uniform and 80%-hot keys; duplicate dimension fanout <=3",
               "sha256": {n: digest(output / n) for n in ("sales.csv", "customers.csv", "catalog.json")}}
    (output / "fixture.json").write_text(json.dumps(fixture, indent=2) + "\n")
    manifest = {"version": 1, "catalog": "catalog.json", "seed": seed,
                "warmups": suite["warmups"], "repetitions": suite["repetitions"],
                "memory_limit": suite["memory_limit"], "result_limit": suite["result_limit"],
                "tracks": suite["tracks"], "cases": make_cases(suite, output),
                "metadata": {"suite": suite["name"], "sales_rows": rows, "smoke": smoke,
                             "fixture": "fixture.json", "definition_hashes": definition_hashes()}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {"manifest": str(output / "manifest.json"), "sales_rows": rows,
            "cases": len(manifest["cases"]), "fixture": fixture}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    print(json.dumps(generate(args.output, args.rows, args.seed, args.smoke), indent=2))

if __name__ == "__main__": main()
