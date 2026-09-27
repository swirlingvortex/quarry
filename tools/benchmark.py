#!/usr/bin/env python3
"""Validate complete native benchmark results, then optionally collect native timings.

No timing occurs without --measure. Run only after the coordinated build/test
freeze. All outputs, including errors and partial native records, are retained.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys

import generate_benchmarks as generator
from verify import fingerprint

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests/differential"))
from harness import DUCKDB_VERSION, compare_multiset, decode_result, same_row

def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")

@contextmanager
def activity_lock():
    target = ROOT / "build/quarry-activity.lock"
    target.parent.mkdir(exist_ok=True)
    with target.open("a+") as handle:
        try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Quarry verification/benchmark activity lock is held") from error
        try: yield
        finally: fcntl.flock(handle, fcntl.LOCK_UN)

def process_preflight() -> list:
    """Conservative non-timing preflight; the lock covers cooperating runners."""
    # Darwin's comm column truncates absolute executable paths to 16 bytes.
    # ucomm supplies the basename there; Linux comm already supplies that name.
    name_field = "ucomm" if platform.system() == "Darwin" else "comm"
    text = subprocess.check_output(["ps", "-axo", f"pid=,{name_field}=,args="], text=True)
    conflicts = []
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3 or int(parts[0]) == os.getpid(): continue
        pid, command, arguments = parts
        name = Path(command).name.lower()
        native = name in {"quarry", "quarry_tests", "quarry_fuzz", "cmake", "ctest", "ninja", "make", "gmake",
                          "clang", "clang++", "c++", "gcc", "g++", "ld", "ld64"}
        python = "python" in name and any(token in arguments for token in
                 ("tools/verify.py", "tools/benchmark.py", "-m pytest", "/pytest"))
        if native or python: conflicts.append({"pid": int(pid), "executable": name, "command": arguments})
    if conflicts: raise RuntimeError("Concurrent builds/tests/Quarry processes: " + json.dumps(conflicts))
    return conflicts

def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text())
    if manifest.get("version") != 1 or manifest.get("tracks") != ["resident", "prepared"]:
        raise ValueError("manifest version/tracks differ from the frozen study")
    if manifest.get("warmups", 0) < 2 or manifest.get("repetitions", 0) < 7:
        raise ValueError("at least two warmups and seven repetitions are required")
    ids = [case["id"] for case in manifest["cases"]]
    if not ids or len(ids) != len(set(ids)) or len(ids) > 128:
        raise ValueError("cases must have 1..128 unique ids")
    for case in manifest["cases"]:
        options = case["options"]
        if options.get("build_side") != "right" or options.get("join_reorder") != "off" or options.get("profile", False):
            raise ValueError("study requires matched right builds, no join reorder, and profile disabled")
        if any(type(k) is not int or k < 0 for k in case["order_keys"]):
            raise ValueError("order_keys must be zero-based integer indices")
    return manifest

def input_paths(path: Path, manifest: dict) -> list[Path]:
    base = path.parent
    catalog_path = (base / manifest["catalog"]).resolve()
    catalog = json.loads(catalog_path.read_text())
    paths = [path.resolve(), catalog_path, (base / manifest["metadata"]["fixture"]).resolve(),
             ROOT / "benchmarks/design-lock.json"]
    paths.extend((catalog_path.parent / table["path"]).resolve() for table in catalog["tables"])
    paths.extend((base / case["sql_file"]).resolve() for case in manifest["cases"])
    return sorted(set(paths))

def snapshot(binary: Path, path: Path, manifest: dict) -> dict:
    paths = input_paths(path, manifest)
    build = binary.parent
    flags = [build / "CMakeCache.txt", *build.glob("CMakeFiles/*.dir/flags.make"),
             *build.glob("CMakeFiles/*.dir/link.txt")]
    return {"source": fingerprint(), "binary_sha256": generator.digest(binary),
            "input_sha256": {str(p): generator.digest(p) for p in paths},
            "input_bytes": {str(p): p.stat().st_size for p in paths},
            "manifest_canonical_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
            "dependencies": json.loads((ROOT / "dependencies.lock.json").read_text()),
            "python_requirements": (ROOT / "requirements-dev.lock").read_text(),
            "build_files": {str(p): {"sha256": generator.digest(p), "content": p.read_text()}
                            for p in sorted(set(flags)) if p.exists()}}

def check_fixture(path: Path, manifest: dict) -> dict:
    generator.check_design_lock()
    suite = json.loads(generator.SUITE.read_text())
    if manifest["cases"] != generator.make_cases(suite, path.parent):
        raise ValueError("manifest case/query/options differ from the frozen finite design")
    fixture = json.loads((path.parent / manifest["metadata"]["fixture"]).read_text())
    if fixture["version"] != generator.VERSION or fixture["recipe_source_sha256"] != generator.digest(Path(generator.__file__)):
        raise ValueError("fixture recipe differs from current generator; regenerate before validating")
    if fixture["schemas"] != {"sales": generator.SALES, "customers": generator.CUSTOMERS}:
        raise ValueError("fixture schemas differ from explicit oracle schemas")
    if fixture["seed"] != manifest["seed"] or fixture["sales_rows"] != manifest["metadata"]["sales_rows"]:
        raise ValueError("fixture seed/profile differs from manifest")
    for name, digest in fixture["sha256"].items():
        if generator.digest(path.parent / name) != digest: raise ValueError(f"fixture hash changed: {name}")
    if manifest["metadata"]["definition_hashes"] != generator.definition_hashes():
        raise ValueError("manifest definitions differ from predeclared queries")
    return fixture

def make_oracle(fixture: dict):
    import duckdb
    if duckdb.__version__ != DUCKDB_VERSION: raise ValueError("use the pinned DuckDB oracle")
    connection = duckdb.connect(":memory:")
    connection.execute("SET threads=1")
    connection.execute("SET default_null_order='NULLS_LAST'")
    # Pinned DuckDB 1.2.2 misorders short UTF-8 strings in this optional
    # optimization; the independent minimized oracle regression documents it.
    connection.execute("SET disabled_optimizers='compressed_materialization'")
    types = {"INT64": "BIGINT", "DOUBLE": "DOUBLE", "BOOL": "BOOLEAN", "STRING": "VARCHAR"}
    for name, columns in fixture["schemas"].items():
        connection.execute(f'CREATE TABLE "{name}" (' + ",".join(
            f'"{column["name"]}" {types[column["type"]]}' + ("" if column["nullable"] else " NOT NULL")
            for column in columns) + ")")
        batch = []
        for row in generator.logical_rows(name, fixture["sales_rows"], fixture["seed"]):
            batch.append(row)
            if len(batch) == 2048:
                connection.executemany(f'INSERT INTO "{name}" VALUES (' + ",".join("?" for _ in columns) + ")", batch)
                batch = []
        if batch: connection.executemany(f'INSERT INTO "{name}" VALUES (' + ",".join("?" for _ in columns) + ")", batch)
    return connection

def oracle_result(connection, sql: str) -> dict:
    relation = connection.sql(sql)
    names, types = relation.columns, list(map(str, relation.types))
    rows = relation.fetchall()
    mapping = {"BIGINT": "INT64", "INTEGER": "INT64", "HUGEINT": "INT64", "DOUBLE": "DOUBLE", "VARCHAR": "STRING", "BOOLEAN": "BOOL"}
    columns = []
    for index, (name, kind) in enumerate(zip(names, types)):
        if kind not in mapping: raise ValueError(f"undeclared oracle adapter {kind}")
        if kind == "HUGEINT" and any(row[index] is not None and not -(2**63) <= row[index] < 2**63 for row in rows):
            raise ValueError("oracle wide SUM exceeds Quarry INT64")
        columns.append({"name": name, "type": mapping[kind]})
    return {"columns": columns, "rows": [list(row) for row in rows]}

def compare_complete(actual: dict, expected: dict, order_keys: list[int]) -> None:
    """Full values/multiplicity; exact partitions avoid quadratic large matches."""
    if actual["columns"] != expected["columns"]: raise AssertionError("schema mismatch")
    schema = expected["columns"]; left, right = actual["rows"], expected["rows"]
    if len(left) != len(right): raise AssertionError("row count/multiplicity mismatch")
    if any(key >= len(schema) for key in order_keys): raise ValueError("order key outside schema")
    def multiset(a, b):
        exact = [i for i, column in enumerate(schema) if column["type"] != "DOUBLE"]
        partitions_a, partitions_b = defaultdict(list), defaultdict(list)
        for row in a: partitions_a[tuple((type(row[i]).__name__, row[i]) for i in exact)].append(row)
        for row in b: partitions_b[tuple((type(row[i]).__name__, row[i]) for i in exact)].append(row)
        if partitions_a.keys() != partitions_b.keys(): raise AssertionError("exact partition mismatch")
        for key, group in partitions_a.items():
            target = partitions_b[key]
            if len(group) != len(target): raise AssertionError("duplicate multiplicity mismatch")
            if len(exact) == len(schema): continue
            if len(group) == 1:
                if not same_row(group[0], target[0], schema): raise AssertionError("typed value mismatch")
            elif len(group) <= 512: compare_multiset(group, target, schema)
            else: raise ValueError("large approximate bucket requires a unique exact key or total ORDER BY")
    if not order_keys: multiset(left, right); return
    cursor = 0; previous_expected = previous_actual = None
    while cursor < len(right):
        end = cursor + 1; key = tuple(right[cursor][k] for k in order_keys)
        while end < len(right) and tuple(right[end][k] for k in order_keys) == key: end += 1
        multiset(left[cursor:end], right[cursor:end])
        actual_key = tuple(left[cursor][k] for k in order_keys)
        if any(tuple(row[k] for k in order_keys) != actual_key for row in left[cursor:end]):
            raise AssertionError("ORDER BY exact tie split")
        if previous_expected is not None:
            for old, new, actual_old, actual_new in zip(previous_expected, key, previous_actual, actual_key):
                if old == new:
                    if actual_old != actual_new: raise AssertionError("earlier ORDER BY key changed within tie")
                    continue
                if old is not None and new is not None:
                    if actual_old == actual_new or (actual_old < actual_new) != (old < new):
                        raise AssertionError("ORDER BY direction differs despite approximate values")
                break
        previous_expected, previous_actual = key, actual_key; cursor = end

def read_records(path: Path):
    with path.open() as source:
        for line in source:
            if line.strip(): yield json.loads(line)

def validate_records(records, manifest: dict, connection, manifest_path: Path) -> dict:
    cases = {case["id"]: case for case in manifest["cases"]}; seen = set(); cached = {}; header = None
    for record in records:
        if record.get("kind") == "header":
            if header is not None: raise ValueError("duplicate native header")
            if seen or record.get("mode") != "validation": raise ValueError("validation header must be first")
            for field in ("seed", "warmups", "repetitions"):
                if record.get(field) != manifest[field]: raise ValueError(f"validation header {field} differs")
            if record.get("case_count") != len(cases): raise ValueError("validation header case count differs")
            header = record; continue
        if record.get("kind") != "validation": raise ValueError("unexpected native validation record")
        if header is None: raise ValueError("validation header must be first")
        pair = (record["case_id"], record["track"])
        if pair in seen or pair[0] not in cases or pair[1] not in manifest["tracks"]:
            raise ValueError("duplicate or unknown validation case/track")
        case = cases[pair[0]]; sql = (manifest_path.parent / case["sql_file"]).read_text()
        if sql not in cached: cached[sql] = oracle_result(connection, sql)
        if record["result"].get("ok") is not True: raise ValueError("native validation query failed")
        compare_complete(decode_result(record["result"]), cached[sql], case["order_keys"]); seen.add(pair)
    wanted = {(case, track) for case in cases for track in manifest["tracks"]}
    if header is None or seen != wanted: raise ValueError("missing complete native validations")
    return {"status": "PASS", "validated_case_tracks": len(seen), "distinct_queries": len(cached),
            "oracle": DUCKDB_VERSION, "threads": 1, "null_order": "NULLS_LAST",
            "disabled_optimizers": "compressed_materialization",
            "comparison": "complete schema/null/value/multiplicity comparison; rel_tol=1e-12 abs_tol=1e-10 for exact-quarter domain; no digest validation", "header": header}

def native(binary: Path, path: Path, output: Path, validate: bool) -> dict:
    command = [str(binary), "bench", "--manifest", str(path)] + (["--validate-only"] if validate else [])
    stem = "validation" if validate else "measurements"
    result = {"command": command, "exit_code": None, "status": "RUNNING"}
    target = output / f"{stem}-process.json"; write_json(target, result)
    try:
        with (output / f"{stem}.jsonl").open("w") as stdout, (output / f"{stem}.stderr").open("w") as stderr:
            completed = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=7200)
        result.update(exit_code=completed.returncode, status="PASS" if completed.returncode == 0 else "FAIL")
    except Exception as error:
        result.update(status="ERROR", error=f"{type(error).__name__}: {error}"); raise
    finally: write_json(target, result)
    if completed.returncode: raise RuntimeError(f"native {stem} failed; preserved raw records and stderr")
    return result

def hardware() -> dict:
    result = {"platform": platform.platform(), "machine": platform.machine(), "processor": platform.processor(),
              "logical_cpus": os.cpu_count(), "python": sys.version, "single_native_execution_thread": True}
    if platform.system() == "Darwin":
        for key in ("machdep.cpu.brand_string", "hw.memsize", "hw.physicalcpu", "hw.logicalcpu"):
            p = subprocess.run(["sysctl", "-n", key], text=True, capture_output=True)
            result[key] = p.stdout.strip() if p.returncode == 0 else "unavailable"
    return result

def verify_build_gate(path: Path | None, before: dict) -> dict:
    if path is None: raise ValueError("--measure requires --verification with a passing final verifier summary")
    gate = json.loads(path.read_text())
    if gate.get("status") != "PASS" or not gate.get("source_unchanged_during_run"):
        raise ValueError("verification gate did not pass on stable source")
    if gate.get("source_after", {}).get("sha256") != before["source"]["sha256"]:
        raise ValueError("measured source differs from verified source")
    if gate.get("binary_sha256", {}).get("release") != before["binary_sha256"]:
        raise ValueError("measured binary differs from verified Release binary")
    return {"path": str(path.resolve()), "sha256": generator.digest(path), "status": "PASS"}

def run(path: Path, binary: Path, output: Path, measure: bool, verification: Path | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    status = {"status": "RUNNING", "started_utc": datetime.now(timezone.utc).isoformat(),
              "manifest": str(path), "binary": str(binary), "measure_requested": measure,
              "hardware": hardware()}
    write_json(output / "status.json", status)
    try:
        with activity_lock():
            process_preflight()
            status["preflight"] = {"started_utc": datetime.now(timezone.utc).isoformat(), "conflicts": [],
                                   "lock": "build/quarry-activity.lock; exclusive nonblocking flock"}
            manifest = load_manifest(path); fixture = check_fixture(path, manifest)
            write_json(output / "manifest.json", manifest)
            before = snapshot(binary, path, manifest); write_json(output / "provenance-before.json", before)
            if measure:
                status["verification_gate"] = verify_build_gate(verification, before)
                write_json(output / "verification-summary.json", json.loads(verification.read_text()))
            native(binary, path, output, True)
            connection = make_oracle(fixture)
            try: validation = validate_records(read_records(output / "validation.jsonl"), manifest, connection, path)
            finally: connection.close()
            write_json(output / "validation-summary.json", validation)
            if snapshot(binary, path, manifest) != before: raise RuntimeError("source/binary/build/input changed during validation")
            if measure:
                if validation["header"].get("build_type", "").lower() != "release": raise ValueError("measurements require a Release native binary")
                if manifest["metadata"].get("smoke"): raise ValueError("study measurements disallow smoke fixtures")
                process_preflight()
                status["preflight"]["measurement_utc"] = datetime.now(timezone.utc).isoformat()
                native(binary, path, output, False)
                from benchmark_report import summarize_records
                summary = summarize_records(list(read_records(output / "measurements.jsonl")), manifest)
                write_json(output / "summary.json", summary)
            after = snapshot(binary, path, manifest); write_json(output / "provenance-after.json", after)
            if after != before: raise RuntimeError("source/binary/build/input changed during measurements; run invalid")
            status.update(status="PASS", hashes_unchanged=True,
                          scope="validated and measured" if measure else "validated only; no measurement")
            artifacts = ["manifest.json", "validation.jsonl", "validation-summary.json", "validation-process.json",
                         "provenance-before.json", "provenance-after.json"]
            if measure: artifacts += ["measurements.jsonl", "measurements-process.json", "verification-summary.json"]
            status["artifact_sha256"] = {name: generator.digest(output / name) for name in artifacts}
    except Exception as error:
        status.update(status="FAIL", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        status["finished_utc"] = datetime.now(timezone.utc).isoformat(); write_json(output / "status.json", status)
    return status

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--binary", type=Path, default=ROOT / "build/release/quarry")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--verification", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.manifest.resolve(), args.binary.resolve(), args.output.resolve(), args.measure, args.verification), indent=2)); return 0
    except Exception as error:
        print(f"Benchmark failed: {error}; evidence retained in {args.output}", file=sys.stderr); return 1

if __name__ == "__main__": raise SystemExit(main())
