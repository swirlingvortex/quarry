#!/usr/bin/env python3
"""Regenerate every benchmark summary and comparison from preserved native JSONL."""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics

TIMINGS = ("planning_ns", "execution_ns", "resident_ns", "rendering_ns")

def distribution(values: list[int | float]) -> dict:
    if len(values) < 7: raise ValueError("at least seven recorded observations required")
    if any(type(x) not in (int, float) or x < 0 for x in values): raise ValueError("invalid duration")
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return {"n": len(values), "median": statistics.median(values), "q1": q1, "q3": q3,
            "iqr": q3 - q1, "min": min(values), "max": max(values)}

def summarize_records(records: list[dict], manifest: dict) -> dict:
    if not records or records[0].get("kind") != "header": raise ValueError("native header must be first")
    header = records[0]
    if header.get("mode") != "timing": raise ValueError("not a native timing run")
    for key in ("seed", "warmups", "repetitions"):
        if header.get(key) != manifest[key]: raise ValueError(f"header {key} does not match manifest")
    if header.get("case_count") != len(manifest["cases"]): raise ValueError("header case count differs")
    if header.get("build_type", "").lower() != "release": raise ValueError("study requires Release")
    if manifest["warmups"] < 2 or manifest["repetitions"] < 7: raise ValueError("insufficient repetitions")
    cases = {case["id"]: case for case in manifest["cases"]}
    if len(cases) != len(manifest["cases"]): raise ValueError("duplicate manifest case id")
    preparations = header.get("preparation_ns", {})
    if set(preparations) != set(cases) or any(type(n) is not int or n < 0 for n in preparations.values()):
        raise ValueError("incomplete or invalid per-case preparation durations")
    if type(header.get("ingestion_ns")) is not int or header["ingestion_ns"] < 0:
        raise ValueError("missing ingestion duration")
    observed = {}; trials = defaultdict(list); outputs = defaultdict(set)
    wanted = {(case, track, phase, repeat) for case in cases for track in ("resident", "prepared")
              for phase, count in (("warmup", manifest["warmups"]), ("recorded", manifest["repetitions"]))
              for repeat in range(count)}
    for sequence, record in enumerate(records[1:]):
        if record.get("kind") != "measurement": raise ValueError("failure or unexpected native record")
        key = tuple(record.get(name) for name in ("case_id", "track", "phase", "repeat"))
        if key not in wanted or key in observed: raise ValueError("unknown or duplicate trial")
        if record.get("order_index") != sequence: raise ValueError("missing/nonmonotonic order index")
        for field in (*TIMINGS, "output_rows", "output_bytes", "peak_accounted_bytes", "current_accounted_bytes"):
            if type(record.get(field)) is not int or record[field] < 0: raise ValueError(f"invalid native {field}")
        if not isinstance(record.get("digest"), str) or not record["digest"]: raise ValueError("missing typed digest")
        if record["peak_accounted_bytes"] < record["current_accounted_bytes"]: raise ValueError("peak below current memory")
        if key[1] == "prepared" and record["planning_ns"] != 0: raise ValueError("prepared trial replanned")
        if record["resident_ns"] != record["planning_ns"] + record["execution_ns"]:
            raise ValueError("resident duration differs from planning plus execution")
        observed[key] = record
        outputs[key[:2]].add((record["output_rows"], record["digest"]))
        if key[2] == "recorded": trials[key[:2]].append(record)
    if set(observed) != wanted: raise ValueError("missing trial records")
    if any(len(values) != 1 for values in outputs.values()): raise ValueError("row count/digest changed between repetitions")
    summaries = []
    for (case_id, track), rows in sorted(trials.items()):
        rows.sort(key=lambda row: row["repeat"])
        case = cases[case_id]; metric = "resident_ns" if track == "resident" else "execution_ns"
        summaries.append({"case_id": case_id, "workload": case["workload"], "options": case["options"],
                          "track": track, "primary_metric": metric,
                          "timings": {key: distribution([row[key] for row in rows]) for key in TIMINGS},
                          "primary_by_repeat_ns": [row[metric] for row in rows],
                          "output_rows": rows[0]["output_rows"],
                          "output_bytes": {"min": min(r["output_bytes"] for r in rows), "max": max(r["output_bytes"] for r in rows)},
                          "peak_accounted_bytes": max(r["peak_accounted_bytes"] for r in rows),
                          "current_accounted_bytes": {"min": min(r["current_accounted_bytes"] for r in rows), "max": max(r["current_accounted_bytes"] for r in rows)}})
    return {"header": header, "summaries": summaries, "recorded_trials": len(cases) * 2 * manifest["repetitions"],
            "warmup_trials": len(cases) * 2 * manifest["warmups"],
            "quantiles": "statistics.quantiles(n=4,method='inclusive'); median of all recorded repetitions",
            "memory_scope": "engine-lifetime accounted high-water mark, including catalog and retained plans; not per-trial peak or RSS",
            "comparisons": comparisons(summaries)}

def comparisons(summaries: list[dict]) -> list:
    index = {(r["workload"], r["track"], r["options"]["engine"], r["options"]["batch_size"], r["options"]["optimizer"]): r for r in summaries}
    result = []
    def pair(kind, base, candidate):
        b = base["timings"][base["primary_metric"]]; c = candidate["timings"][candidate["primary_metric"]]
        if b["median"] <= 0 or c["median"] <= 0: raise ValueError("zero duration cannot support a timing ratio")
        ratios = [x / y for x, y in zip(base["primary_by_repeat_ns"], candidate["primary_by_repeat_ns"])]
        status = "faster" if c["q3"] < b["q1"] else "slower" if c["q1"] > b["q3"] else "inconclusive (IQR overlap)"
        result.append({"kind": kind, "workload": base["workload"], "track": base["track"],
                       "baseline": base["case_id"], "candidate": candidate["case_id"],
                       "baseline_median_ns": b["median"], "candidate_median_ns": c["median"],
                       "ratio_of_medians": b["median"] / c["median"], "paired_ratios": ratios,
                       "paired_ratio_distribution": distribution(ratios), "observation": status})
    for key, row in sorted(index.items()):
        workload, track, engine, batch, opt = key
        if engine == "vector" and batch == 1024:
            base = index.get((workload, track, "scalar", 1024, opt))
            if base: pair("scalar_vs_vector", base, row)
        if opt == "on":
            base = index.get((workload, track, engine, batch, "off"))
            if base: pair("optimizer_off_vs_on", base, row)
        if engine == "vector" and batch in (256, 4096):
            base = index.get((workload, track, engine, 1024, opt))
            if base: pair("batch_1024_vs_selected", base, row)
    return result

def load_run(path: Path) -> dict:
    from generate_benchmarks import digest
    status = json.loads((path / "status.json").read_text())
    if status.get("status") != "PASS" or not status.get("measure_requested") or not status.get("hashes_unchanged"):
        raise ValueError(f"run was not successfully validated/frozen/measured: {path}")
    artifacts = status.get("artifact_sha256", {})
    required = {"manifest.json", "validation.jsonl", "validation-summary.json", "validation-process.json",
                "provenance-before.json", "provenance-after.json", "measurements.jsonl", "measurements-process.json", "verification-summary.json"}
    if not required.issubset(artifacts): raise ValueError("missing frozen artifact hashes")
    for name, expected in artifacts.items():
        if digest(path / name) != expected: raise ValueError(f"saved run artifact changed: {name}")
    if status.get("verification_gate", {}).get("status") != "PASS": raise ValueError("no matching verified Release build")
    before = json.loads((path / "provenance-before.json").read_text()); after = json.loads((path / "provenance-after.json").read_text())
    if before != after: raise ValueError("run provenance changed")
    gate = json.loads((path / "verification-summary.json").read_text())
    if gate.get("status") != "PASS" or not gate.get("source_unchanged_during_run") or gate.get("source_after", {}).get("sha256") != before["source"]["sha256"] or gate.get("binary_sha256", {}).get("release") != before["binary_sha256"]:
        raise ValueError("archived verification gate does not match measured source/binary")
    validation = json.loads((path / "validation-summary.json").read_text())
    if validation.get("status") != "PASS": raise ValueError("missing complete correctness validation")
    manifest = json.loads((path / "manifest.json").read_text())
    canonical = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    if canonical != before["manifest_canonical_sha256"]: raise ValueError("archived manifest differs from frozen input")
    if validation.get("validated_case_tracks") != len(manifest["cases"]) * 2: raise ValueError("incomplete validation count")
    raw = path / "measurements.jsonl"
    records = [json.loads(line) for line in raw.read_text().splitlines() if line.strip()]
    result = summarize_records(records, manifest)
    result.update(run_directory=str(path.resolve()), sales_rows=manifest["metadata"]["sales_rows"],
                  source_sha256=before["source"]["sha256"], binary_sha256=before["binary_sha256"],
                  raw_sha256=digest(raw), hardware=status["hardware"], input_hashes=before["input_sha256"], input_bytes=before["input_bytes"])
    return result

def markdown(runs: list[dict]) -> str:
    lines = ["# Quarry performance study", "",
             "This report is generated from preserved native records. It compares Quarry with itself; it is not a TPC-H result or a DuckDB performance comparison.", "",
             "The twelve original query definitions were frozen before timing. The finite design pairs 1%/90% numeric selectivity, 10%/90% null density, 16/2,048 grouping keys, narrow/wide projection, string grouping, sort with LIMIT, and uniform/skewed joins with at most three dimension matches per key. Each profile runs scalar/vector1024 × optimizer off/on; only scan_selective and group_high add vector256/4096. All joins force the same right build. This is 56 configurations per profile, not a full parameter Cartesian product.", "",
             "Each native Release run uses one execution thread, two warmups and seven recorded repetitions, with a saved seeded interleaving. Complete resident/prepared outputs were compared with explicitly typed DuckDB before timing. No digest substitutes for validation. Resident time includes parse/bind/plan and execution through the owning Result sink; prepared time executes the retained plan with fresh state. Loading, digest traversal, rendering, record output and result/temporary-plan destruction are excluded from execution timing. Rendering is measured separately. Both engines retain ordinary counters; optional profiling is off.", "",
             "The pinned DuckDB 1.2.2 correctness connection uses one thread, NULLS LAST, and disabled_optimizers='compressed_materialization'. A minimized independent regression exposed incorrect short UTF-8 sorting in that optional oracle optimization. The same SQL runs with the setting applied; results are not post-sorted to hide differences. This setting affects correctness validation only, never native Quarry timing.", "",
             "Medians and inclusive-quartile IQRs use all seven recorded observations. Ratios greater than one favor the candidate; paired ratios compare the same repeat number. ‘Inconclusive’ means the observed IQRs overlap, not a statistical equivalence test. All cases, including slowdowns, are retained. Allocation peaks are engine-lifetime high-water marks including retained plans and earlier trials, not isolated per-query peaks or RSS. No general hardware-independent speed claim follows.", "",
             "Reproduce after coordinating a build/test freeze:", "", "```sh",
             ".venv/bin/python tools/generate_benchmarks.py --rows 10000 --output data/benchmarks/10000",
             ".venv/bin/python tools/generate_benchmarks.py --rows 100000 --output data/benchmarks/100000",
             ".venv/bin/python tools/benchmark.py --manifest data/benchmarks/10000/manifest.json --output reports/benchmarks/10000 --measure --verification PATH_TO_PASSING_CORE_SUMMARY",
             ".venv/bin/python tools/benchmark.py --manifest data/benchmarks/100000/manifest.json --output reports/benchmarks/100000 --measure --verification PATH_TO_PASSING_CORE_SUMMARY",
             ".venv/bin/python tools/benchmark_report.py --runs reports/benchmarks/10000 reports/benchmarks/100000 --output docs/BENCHMARKS.md --json-output evidence/m8-report.json",
             "```", "", "Output directories must be new. The activity lock and process preflight reject overlapping builds/tests/benchmarks; normal runs are offline. Million-row inputs remain disabled. Rerun affected measurements after timed code, flags or data change.", ""]
    for run in runs:
        observations = defaultdict(int)
        for comparison in run["comparisons"]: observations[comparison["observation"]] += 1
        lines += [f"## {run['sales_rows']:,} sales rows", "",
                  f"Source `{run['source_sha256']}`; binary `{run['binary_sha256']}`.", "",
                  f"Raw records: `{run['run_directory']}/measurements.jsonl`, SHA256 `{run['raw_sha256']}`. Hardware: {run['hardware']['platform']}, {run['hardware']['machine']}, {run['hardware'].get('machdep.cpu.brand_string', run['hardware'].get('processor', 'unknown CPU'))}.", "",
                  f"Recorded trials: {run['recorded_trials']}; warmups: {run['warmup_trials']}. Observed comparisons: " + ", ".join(f"{k}: {v}" for k, v in sorted(observations.items())) + ".", "",
                  "| Case | Track | Median ms | IQR ms | Rows | Output bytes min–max | Accounted lifetime peak bytes |", "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
        for row in run["summaries"]:
            metric = row["timings"][row["primary_metric"]]; size = row["output_bytes"]
            lines.append(f"| {row['case_id']} | {row['track']} | {metric['median']/1e6:.6f} | {metric['iqr']/1e6:.6f} | {row['output_rows']} | {size['min']}–{size['max']} | {row['peak_accounted_bytes']} |")
        lines += ["", "| Comparison | Track | Baseline → candidate | Median ratio | Paired ratio median [Q1, Q3] | Observation |", "| --- | --- | --- | ---: | ---: | --- |"]
        for row in run["comparisons"]:
            ratio = row["paired_ratio_distribution"]
            lines.append(f"| {row['kind']} | {row['track']} | {row['baseline']} → {row['candidate']} | {row['ratio_of_medians']:.3f} | {ratio['median']:.3f} [{ratio['q1']:.3f}, {ratio['q3']:.3f}] | {row['observation']} |")
        lines += [""]
    lines += ["## Interpretation limits", "",
              "These workloads measure the whole stated scope, not isolated SIMD kernels. Narrow/wide projections include different owning sink and rendering volumes; sorting remains blocking; pruning removes scan descriptors without necessarily reducing lazy payload reads. Join pushdown can reduce pairs before aggregation, while ordered DOUBLE accumulation constrains build-side changes. Batch sizes can add allocation/materialization overhead, and small/selective workloads may show little benefit. The tables retain those losses and overlapping-IQR cases rather than selecting only favorable runs.", "",
              "The JSON report also preserves planning, execution, resident and rendering distributions for every case. Raw records and provenance retain loading/preparation metadata, configuration options, input/query hashes, compiler/cache flags, failures, and every repetition. Python DuckDB calls provide correctness only and have no timing comparison here.", ""]
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args(); runs = [load_run(path) for path in args.runs]
    if sorted(run["sales_rows"] for run in runs) != [10000, 100000]: raise ValueError("complete study requires exactly 10k and 100k profiles")
    if len({(run["source_sha256"], run["binary_sha256"]) for run in runs}) != 1: raise ValueError("profiles must share frozen source and binary")
    args.json_output.parent.mkdir(parents=True, exist_ok=True); args.output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps({"generated_from_raw": True, "runs": runs}, indent=2) + "\n")
    args.output.write_text(markdown(runs))
    print(json.dumps({"report": str(args.output), "json": str(args.json_output), "case_track_summaries": sum(len(r['summaries']) for r in runs)}))

if __name__ == "__main__": main()
