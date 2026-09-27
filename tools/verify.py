#!/usr/bin/env python3
"""Offline M0-M9 correctness gates, separate from performance measurements.

smoke runs Debug and 36 distinct generated cases; core runs Debug, Release,
and ASan/UBSan with 1008 distinct cases (768 single-table + 240 joined).
extended is separately bounded at 2016 cases. Every case has 20 engine/rule
configurations; content identities and successful execution receipts are saved.
All profiles include hand, Hypothesis, fuzz, benchmark-tool and comparator tests.
No profile downloads dependencies or runs the performance study.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import fcntl
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def fingerprint() -> dict:
    paths = []
    for directory in ("include", "src", "tests", "tools", "examples", "benchmarks", ".github"):
        paths.extend(path for path in (ROOT / directory).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts)
    paths.extend(ROOT / name for name in ("CMakeLists.txt", "CMakePresets.json", "pytest.ini",
                                          "requirements-dev.lock", "dependencies.lock.json"))
    files = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(paths) if path.is_file()}
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"algorithm": "sha256-of-sorted-path-content-sha256-json-v1",
            "sha256": hashlib.sha256(encoded).hexdigest(), "files": files}


def verify(profile: str) -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = ROOT / "build/verification" / f"{timestamp}-{profile}"
    output.mkdir(parents=True)
    environment = dict(os.environ, QUARRY_TEST_PROFILE=profile,
                       QUARRY_BINARY=str(ROOT / "build/debug/quarry"),
                       PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1")
    cmake = str(ROOT / ".venv/bin/cmake")
    ctest = str(ROOT / ".venv/bin/ctest")
    steps: list[tuple[str, list[str]]] = [
        ("debug-configure", [cmake, "--preset", "debug"]),
        ("debug-build", [cmake, "--build", "--preset", "debug"]),
        ("debug-ctest", [ctest, "--preset", "debug"]),
        ("python-verification", [sys.executable, "-m", "pytest", "-q", "-ra", "--hypothesis-show-statistics",
                                 "tests/integration", "tests/differential", "tests/regressions", "tests/fuzz", "tests/benchmark",
                                 f"--junitxml={output / 'pytest.xml'}"]),
        ("demo", [str(ROOT / "build/debug/quarry"), "demo"]),
    ]
    if profile in {"core", "extended"}:
        steps.extend([
            ("release-configure", [cmake, "--preset", "release"]),
            ("release-build", [cmake, "--build", "--preset", "release"]),
            ("release-ctest", [ctest, "--preset", "release"]),
            ("release-python", [sys.executable, "-m", "pytest", "-q", "-ra", "--hypothesis-show-statistics",
                                 "tests/integration", "tests/differential", "tests/regressions", "tests/fuzz", "tests/benchmark",
                                 f"--junitxml={output / 'pytest-release.xml'}"]),
            ("sanitize-configure", [cmake, "--preset", "sanitize"]),
            ("sanitize-build", [cmake, "--build", "--preset", "sanitize"]),
            ("sanitize-ctest", [ctest, "--preset", "sanitize"]),
            ("sanitize-python", [sys.executable, "-m", "pytest", "-q", "-ra", "--hypothesis-show-statistics",
                                  "tests/integration", "tests/differential", "tests/regressions", "tests/fuzz", "tests/benchmark",
                                  f"--junitxml={output / 'pytest-sanitize.xml'}"]),
        ])
    report = {
        "scope": "M0-M9", "profile": profile, "started_utc": timestamp,
        "platform": platform.platform(), "machine": platform.machine(),
        "python": sys.version, "interpreter": sys.executable,
        "source_before": fingerprint(), "steps": [],
        "differential": {"single_table_cases_requested": {"smoke": 24, "core": 768, "extended": 1536}[profile],
                         "join_cases_requested": {"smoke": 12, "core": 240, "extended": 480}[profile],
                         "independent_nested_loop_cases": 12,
                         "engines": ["scalar", "vector"], "vector_batch_sizes": [1, 7, 256, 1024, 4096],
                         "optimizer_modes": ["off", "on"],
                         "individual_rules_both_engines": ["prune", "pushdown", "fold", "join-reorder"],
                         "configurations_per_generated_case": 20,
                         "hypothesis_examples_max_per_property": {"smoke": 5, "core": 40, "extended": 120}[profile],
                         "oracle": "duckdb==1.2.2", "threads": 1,
                         "relative_tolerance": 1e-12, "absolute_tolerance": 1e-10},
        "environment_overrides": {key: environment[key] for key in
                                  ("QUARRY_TEST_PROFILE", "QUARRY_BINARY", "PYTHONHASHSEED", "PYTHONDONTWRITEBYTECODE")},
        "leak_sanitizer": {
            "enabled_for_sanitized_cli": platform.system() != "Darwin",
            "note": ("Disabled on Darwin: this host's runtime aborted with 'detect_leaks is not supported on this platform'. ASan and UBSan remain enabled."
                     if platform.system() == "Darwin" else "Leak detection is requested; any unsupported runtime is reported as a failed check."),
        },
    }
    sys.path.insert(0, str(ROOT / "tests/differential"))
    from corpus import case_records
    from harness import DUCKDB_SETTINGS
    cases = case_records(profile)
    manifest = output / "cases.jsonl"
    manifest.write_text("".join(json.dumps(case, sort_keys=True, ensure_ascii=False) + "\n" for case in cases))
    report["differential"].update(
        oracle_settings=DUCKDB_SETTINGS,
        distinct_cases_required=len(cases),
        case_content_manifest=str(manifest.relative_to(ROOT)),
        case_content_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        identity_policy="SHA256 of canonical SQL and typed input schemas/values, excluding seeds and configuration repetitions")
    expected_cases = {case["case_id"]: case["content_sha256"] for case in cases}
    print(f"Evidence directory: {output}", flush=True)
    failed = False
    for index, (name, command) in enumerate(steps, 1):
        log = output / f"{index:02}-{name}.log"
        entry = {"name": name, "command": command, "shell_command": shlex.join(command),
                 "cwd": str(ROOT), "log": str(log.relative_to(ROOT))}
        step_environment = environment
        if name == "release-python":
            overrides = {"QUARRY_BINARY": str(ROOT / "build/release/quarry")}
            step_environment = dict(environment, **overrides)
            entry["environment_overrides"] = overrides
        if name == "sanitize-python":
            overrides = {"QUARRY_BINARY": str(ROOT / "build/sanitize/quarry"),
                         "ASAN_OPTIONS": "detect_leaks=0" if platform.system() == "Darwin" else "detect_leaks=1",
                         "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
            step_environment = dict(environment, **overrides)
            entry["environment_overrides"] = overrides
        if name in {"python-verification", "release-python", "sanitize-python"}:
            preset = {"python-verification": "debug", "release-python": "release", "sanitize-python": "sanitize"}[name]
            receipts = output / f"cases-{preset}-executed.jsonl"
            overrides = dict(entry.get("environment_overrides", {}), QUARRY_CASE_RECEIPTS=str(receipts))
            step_environment = dict(environment, **overrides)
            entry["environment_overrides"] = overrides
        report["steps"].append(entry)
        if failed:
            entry.update(status="NOT_RUN", exit_code=None)
            continue
        print(f"[{index}/{len(steps)}] {shlex.join(command)}", flush=True)
        start = time.monotonic()
        with log.open("w") as handle:
            handle.write(f"cwd: {ROOT}\ncommand: {shlex.join(command)}\n\n")
            handle.flush()
            try:
                process = subprocess.run(command, cwd=ROOT, env=step_environment,
                                         stdout=handle, stderr=subprocess.STDOUT, timeout=1800)
                code = process.returncode
                entry.update(status="PASS" if code == 0 else "FAIL", exit_code=code)
                if code == 0 and name in {"python-verification", "release-python", "sanitize-python"}:
                    executed = [json.loads(line) for line in receipts.read_text().splitlines()] if receipts.exists() else []
                    observed = {case["case_id"]: case["content_sha256"] for case in executed}
                    valid = (len(executed) == len(expected_cases) and observed == expected_cases and
                             all(case["configurations_passed"] == 20 for case in executed))
                    entry["case_execution"] = {"receipt_file": str(receipts.relative_to(ROOT)),
                        "receipt_sha256": hashlib.sha256(receipts.read_bytes()).hexdigest() if receipts.exists() else None,
                        "distinct_cases": len(observed), "configuration_comparisons": sum(c["configurations_passed"] for c in executed),
                        "identities_match_manifest": valid}
                    if not valid:
                        code = 1
                        entry.update(status="FAIL", verification_error="Executed case identities/counts differ from content manifest")
            except (OSError, subprocess.TimeoutExpired, ValueError, KeyError) as error:
                handle.write(f"\nOrchestration error: {error}\n")
                code = 1
                entry.update(status="ERROR", exit_code=None, error=str(error))
        entry["elapsed_seconds"] = time.monotonic() - start
        failed = code != 0
        print(f"  {entry['status']} exit={entry['exit_code']} log={log}", flush=True)
        (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    report["source_after"] = fingerprint()
    report["source_unchanged_during_run"] = report["source_before"] == report["source_after"]
    binary = ROOT / "build/debug/quarry"
    if binary.exists():
        report["debug_binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
    report["binary_sha256"] = {
        preset: hashlib.sha256((ROOT / "build" / preset / "quarry").read_bytes()).hexdigest()
        for preset in ("debug", "release", "sanitize")
        if (ROOT / "build" / preset / "quarry").exists()
    }
    if not report["source_unchanged_during_run"]:
        failed = True
        report["source_change_error"] = "Source changed during verification; rerun against a stable tree."
    report["status"] = "FAIL" if failed else "PASS"
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['status']}: {output / 'summary.json'}", flush=True)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "core", "extended"), default="core")
    args = parser.parse_args()
    lock_path = ROOT / "build/quarry-activity.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as activity:
        try:
            fcntl.flock(activity.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Verification not started: a Quarry benchmark or verifier holds build/quarry-activity.lock", file=sys.stderr)
            return 2
        return verify(args.profile)


if __name__ == "__main__":
    raise SystemExit(main())
