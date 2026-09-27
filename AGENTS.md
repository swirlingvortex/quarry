# Quarry

Current authorization: implement M7–M9 only, preserving verified M0–M6. The full, authoritative roadmap
is in `docs/IMPLEMENTATION_PLAN.md`. No sibling repositories, external query
backends, publishing, pushes, tags, destructive cleanup, or global installs.

The primary agent owns `include/`, `src/`, CMake, and integration. At most two
additional workers may edit disjoint tests/docs or perform read-only review after
contracts are defined. Do not edit another owner's files without coordination.

Bootstrap: `python3.12 tools/bootstrap.py` (network permitted only here).
Verify: `.venv/bin/python tools/verify.py --profile core`.
Build: `.venv/bin/cmake --preset debug && .venv/bin/cmake --build --preset debug`.
Tests: `.venv/bin/ctest --preset debug`.
Demo: `build/debug/quarry demo`.

After tested increments update `docs/CHECKPOINT.md` and `docs/VERIFICATION.md`:
source fingerprint, exact commands, exit codes, evidence logs, unresolved issues,
and next action. Never claim skipped/unobserved checks passed. Keep normal builds
offline. Stop after M9; extensions require separate authorization. Do not run builds/tests concurrently with benchmark measurement.
