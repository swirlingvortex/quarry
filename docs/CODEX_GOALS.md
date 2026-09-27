# Continuation goals

Current authorization covers GOAL 3, M7–M9, after revalidating the accepted M0–M6
baseline. GOAL 2 and GOAL 3 are complete with verdict CORE_VERIFIED_LOCAL.
Implementation and handoff stop at M9; extensions
require separate authorization. CHECKPOINT.md and VERIFICATION.md own current
acceptance status and observed evidence. The original goal wording is preserved
below.

GOAL 2:
Read AGENTS.md, IMPLEMENTATION_PLAN.md, CHECKPOINT.md, and
VERIFICATION.md. Inspect actual source state and rerun relevant
M0-M3 smoke gates. Implement M4-M6 only, preserving contracts and
fixing regressions. Review semantics and lifetimes, update evidence,
and stop at M6.

GOAL 3:
Read the same files, inspect current state, and verify M0-M6
foundations. Complete M7-M9 only. Prioritize adversarial correctness
checks and reproducible measurements over new features. Produce
the final audit and learning guide. Do not publish, push, tag,
or add extensions.

The M7–M9 boundary includes the 1,008-case core corpus, bounded mutation and
allocation-failure checks, configured Linux/macOS CI, reusable prepared plans,
native resident/prepared benchmark tracks, the declared 10k/100k study, a clean
installation check, and the final audit/learning handoff. It adds no SQL dialect
features or external query backend. Correctness checks and measurements must
run separately; performance claims require matching frozen provenance and raw
records. Configured or pending checks are not reported as observed passes.

The named plan/checkpoint/verification files are under `docs/`; AGENTS.md is at
the repository root. Extensions require separate authorization after M9. First
consider per-chunk statistics/zone-map pruning, then dictionary encoding or a
top-k operator, each with an isolated experiment and full regressions.
