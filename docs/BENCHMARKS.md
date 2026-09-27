# Quarry performance study

This report is generated from preserved native records. It compares Quarry with itself; it is not a TPC-H result or a DuckDB performance comparison.

The twelve original query definitions were frozen before timing. The finite design pairs 1%/90% numeric selectivity, 10%/90% null density, 16/2,048 grouping keys, narrow/wide projection, string grouping, sort with LIMIT, and uniform/skewed joins with at most three dimension matches per key. Each profile runs scalar/vector1024 × optimizer off/on; only scan_selective and group_high add vector256/4096. All joins force the same right build. This is 56 configurations per profile, not a full parameter Cartesian product.

Each native Release run uses one execution thread, two warmups and seven recorded repetitions, with a saved seeded interleaving. Complete resident/prepared outputs were compared with explicitly typed DuckDB before timing. No digest substitutes for validation. Resident time includes parse/bind/plan and execution through the owning Result sink; prepared time executes the retained plan with fresh state. Loading, digest traversal, rendering, record output and result/temporary-plan destruction are excluded from execution timing. Rendering is measured separately. Both engines retain ordinary counters; optional profiling is off.

The pinned DuckDB 1.2.2 correctness connection uses one thread, NULLS LAST, and disabled_optimizers='compressed_materialization'. A minimized independent regression exposed incorrect short UTF-8 sorting in that optional oracle optimization. The same SQL runs with the setting applied; results are not post-sorted to hide differences. This setting affects correctness validation only, never native Quarry timing.

Medians and inclusive-quartile IQRs use all seven recorded observations. Ratios greater than one favor the candidate; paired ratios compare the same repeat number. ‘Inconclusive’ means the observed IQRs overlap, not a statistical equivalence test. All cases, including slowdowns, are retained. Allocation peaks are engine-lifetime high-water marks including retained plans and earlier trials, not isolated per-query peaks or RSS. No general hardware-independent speed claim follows.

Reproduce after coordinating a build/test freeze:

```sh
.venv/bin/python tools/generate_benchmarks.py --rows 10000 --output data/benchmarks/10000
.venv/bin/python tools/generate_benchmarks.py --rows 100000 --output data/benchmarks/100000
.venv/bin/python tools/benchmark.py --manifest data/benchmarks/10000/manifest.json --output reports/benchmarks/10000 --measure --verification PATH_TO_PASSING_CORE_SUMMARY
.venv/bin/python tools/benchmark.py --manifest data/benchmarks/100000/manifest.json --output reports/benchmarks/100000 --measure --verification PATH_TO_PASSING_CORE_SUMMARY
.venv/bin/python tools/benchmark_report.py --runs reports/benchmarks/10000 reports/benchmarks/100000 --output docs/BENCHMARKS.md --json-output evidence/m8-report.json
```

Output directories must be new. The activity lock and process preflight reject overlapping builds/tests/benchmarks; normal runs are offline. Million-row inputs remain disabled. Rerun affected measurements after timed code, flags or data change.

## 10,000 sales rows

Source `993bef547cee6f56657330eafcd606b4c8d535760e9e97e04bd4242e4bc1b553`; binary `4bb67a95d79b66d09811158e0cce9d3a4411b21dc5e32bc43687f9b2e0ede9ad`.

Raw records: `/Users/goktugbas/Major_Projects/quarry/reports/benchmarks/final-10000/measurements.jsonl`, SHA256 `5a90d5cba2afec390e227898d3fcfee19dcbd423d63c830d8ad29cb18d7d5e4f`. Hardware: macOS-15.7.1-arm64-arm-64bit, arm64, Apple M1 Pro.

Recorded trials: 784; warmups: 224. Observed comparisons: faster: 58, inconclusive (IQR overlap): 46, slower: 16.

| Case | Track | Median ms | IQR ms | Rows | Output bytes min–max | Accounted lifetime peak bytes |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| group_high.scalar.b1024.off | prepared | 1.615625 | 0.002479 | 2048 | 35883–35883 | 15419616 |
| group_high.scalar.b1024.off | resident | 1.637666 | 0.006000 | 2048 | 35883–35883 | 15419616 |
| group_high.scalar.b1024.on | prepared | 1.620875 | 0.007499 | 2048 | 35883–35883 | 15419616 |
| group_high.scalar.b1024.on | resident | 1.636417 | 0.011125 | 2048 | 35883–35883 | 15419616 |
| group_high.vector.b1024.off | prepared | 1.317208 | 0.004937 | 2048 | 35883–35883 | 15419616 |
| group_high.vector.b1024.off | resident | 1.341291 | 0.024355 | 2048 | 35883–35883 | 15419616 |
| group_high.vector.b1024.on | prepared | 1.328166 | 0.051916 | 2048 | 35883–35883 | 15419616 |
| group_high.vector.b1024.on | resident | 1.354417 | 0.017375 | 2048 | 35883–35883 | 15419616 |
| group_high.vector.b256.off | prepared | 1.339125 | 0.007541 | 2048 | 35883–35883 | 15419616 |
| group_high.vector.b256.off | resident | 1.354750 | 0.028855 | 2048 | 35883–35883 | 15419616 |
| group_high.vector.b256.on | prepared | 1.339042 | 0.015313 | 2048 | 35883–35883 | 15419616 |
| group_high.vector.b256.on | resident | 1.353709 | 0.013438 | 2048 | 35883–35883 | 15419616 |
| group_high.vector.b4096.off | prepared | 1.313209 | 0.044021 | 2048 | 35883–35883 | 15419616 |
| group_high.vector.b4096.off | resident | 1.331916 | 0.010292 | 2048 | 35883–35883 | 15419616 |
| group_high.vector.b4096.on | prepared | 1.309000 | 0.008812 | 2048 | 35883–35883 | 15419616 |
| group_high.vector.b4096.on | resident | 1.326333 | 0.010521 | 2048 | 35883–35883 | 15419616 |
| group_low.scalar.b1024.off | prepared | 0.932792 | 0.005791 | 16 | 438–438 | 15419616 |
| group_low.scalar.b1024.off | resident | 0.939459 | 0.003209 | 16 | 438–438 | 15419616 |
| group_low.scalar.b1024.on | prepared | 0.925250 | 0.000646 | 16 | 438–438 | 15419616 |
| group_low.scalar.b1024.on | resident | 0.939167 | 0.002000 | 16 | 438–438 | 15419616 |
| group_low.vector.b1024.off | prepared | 0.726375 | 0.007103 | 16 | 438–438 | 15419616 |
| group_low.vector.b1024.off | resident | 0.743834 | 0.009291 | 16 | 438–438 | 15419616 |
| group_low.vector.b1024.on | prepared | 0.724291 | 0.003041 | 16 | 438–438 | 15419616 |
| group_low.vector.b1024.on | resident | 0.738500 | 0.002479 | 16 | 438–438 | 15419616 |
| group_string.scalar.b1024.off | prepared | 1.260250 | 0.003333 | 9 | 362–362 | 15419616 |
| group_string.scalar.b1024.off | resident | 1.273084 | 0.006271 | 9 | 362–362 | 15419616 |
| group_string.scalar.b1024.on | prepared | 1.260917 | 0.011646 | 9 | 362–362 | 15419616 |
| group_string.scalar.b1024.on | resident | 1.272875 | 0.003041 | 9 | 362–362 | 15419616 |
| group_string.vector.b1024.off | prepared | 0.911458 | 0.009541 | 9 | 362–362 | 15419616 |
| group_string.vector.b1024.off | resident | 0.932000 | 0.009625 | 9 | 362–362 | 15419616 |
| group_string.vector.b1024.on | prepared | 0.920250 | 0.015834 | 9 | 362–362 | 15419616 |
| group_string.vector.b1024.on | resident | 0.926209 | 0.007521 | 9 | 362–362 | 15419616 |
| join_skew.scalar.b1024.off | prepared | 2.414625 | 0.006104 | 8 | 306–306 | 15419616 |
| join_skew.scalar.b1024.off | resident | 2.435584 | 0.010875 | 8 | 306–306 | 15419616 |
| join_skew.scalar.b1024.on | prepared | 1.863417 | 0.004250 | 8 | 306–306 | 15419616 |
| join_skew.scalar.b1024.on | resident | 1.883459 | 0.017063 | 8 | 306–306 | 15419616 |
| join_skew.vector.b1024.off | prepared | 1.506083 | 0.007979 | 8 | 306–306 | 15419616 |
| join_skew.vector.b1024.off | resident | 1.528792 | 0.020459 | 8 | 306–306 | 15419616 |
| join_skew.vector.b1024.on | prepared | 1.109042 | 0.008230 | 8 | 306–306 | 15419616 |
| join_skew.vector.b1024.on | resident | 1.137500 | 0.012500 | 8 | 306–306 | 15419616 |
| join_uniform.scalar.b1024.off | prepared | 2.424750 | 0.005791 | 8 | 306–306 | 15419616 |
| join_uniform.scalar.b1024.off | resident | 2.450500 | 0.012500 | 8 | 306–306 | 15419616 |
| join_uniform.scalar.b1024.on | prepared | 1.874416 | 0.003187 | 8 | 306–306 | 15419616 |
| join_uniform.scalar.b1024.on | resident | 1.904500 | 0.018437 | 8 | 306–306 | 15419616 |
| join_uniform.vector.b1024.off | prepared | 1.501375 | 0.012334 | 8 | 306–306 | 15419616 |
| join_uniform.vector.b1024.off | resident | 1.538458 | 0.003021 | 8 | 306–306 | 15419616 |
| join_uniform.vector.b1024.on | prepared | 1.112959 | 0.006834 | 8 | 306–306 | 15419616 |
| join_uniform.vector.b1024.on | resident | 1.140917 | 0.011395 | 8 | 306–306 | 15419616 |
| null_heavy.scalar.b1024.off | prepared | 0.474417 | 0.001229 | 1 | 164–164 | 15419616 |
| null_heavy.scalar.b1024.off | resident | 0.489417 | 0.009542 | 1 | 164–164 | 15419616 |
| null_heavy.scalar.b1024.on | prepared | 0.474958 | 0.001375 | 1 | 164–164 | 15419616 |
| null_heavy.scalar.b1024.on | resident | 0.491458 | 0.004980 | 1 | 164–164 | 15419616 |
| null_heavy.vector.b1024.off | prepared | 0.191708 | 0.002354 | 1 | 164–164 | 15419616 |
| null_heavy.vector.b1024.off | resident | 0.209375 | 0.014063 | 1 | 164–164 | 15419616 |
| null_heavy.vector.b1024.on | prepared | 0.195000 | 0.006417 | 1 | 164–164 | 15419616 |
| null_heavy.vector.b1024.on | resident | 0.207375 | 0.006687 | 1 | 164–164 | 15419616 |
| null_light.scalar.b1024.off | prepared | 0.525875 | 0.003270 | 1 | 175–175 | 15419616 |
| null_light.scalar.b1024.off | resident | 0.539167 | 0.006208 | 1 | 175–175 | 15419616 |
| null_light.scalar.b1024.on | prepared | 0.525000 | 0.001062 | 1 | 175–175 | 15419616 |
| null_light.scalar.b1024.on | resident | 0.545083 | 0.004397 | 1 | 175–175 | 15419616 |
| null_light.vector.b1024.off | prepared | 0.278709 | 0.003834 | 1 | 175–175 | 15419616 |
| null_light.vector.b1024.off | resident | 0.293500 | 0.004583 | 1 | 175–175 | 15419616 |
| null_light.vector.b1024.on | prepared | 0.278708 | 0.008604 | 1 | 175–175 | 15419616 |
| null_light.vector.b1024.on | resident | 0.293000 | 0.006687 | 1 | 175–175 | 15419616 |
| projection_narrow.scalar.b1024.off | prepared | 0.857833 | 0.051499 | 10000 | 134492–134492 | 15419616 |
| projection_narrow.scalar.b1024.off | resident | 0.813917 | 0.020292 | 10000 | 134492–134492 | 15419616 |
| projection_narrow.scalar.b1024.on | prepared | 0.826792 | 0.014646 | 10000 | 134492–134492 | 15419616 |
| projection_narrow.scalar.b1024.on | resident | 0.838917 | 0.007250 | 10000 | 134492–134492 | 15419616 |
| projection_narrow.vector.b1024.off | prepared | 0.692791 | 0.035979 | 10000 | 134492–134492 | 15419616 |
| projection_narrow.vector.b1024.off | resident | 0.713750 | 0.028146 | 10000 | 134492–134492 | 15419616 |
| projection_narrow.vector.b1024.on | prepared | 0.678250 | 0.034250 | 10000 | 134492–134492 | 15419616 |
| projection_narrow.vector.b1024.on | resident | 0.685625 | 0.025271 | 10000 | 134492–134492 | 15419616 |
| projection_wide.scalar.b1024.off | prepared | 3.509291 | 0.054958 | 10000 | 1824145–1824145 | 15419616 |
| projection_wide.scalar.b1024.off | resident | 3.526083 | 0.044709 | 10000 | 1824145–1824145 | 15419616 |
| projection_wide.scalar.b1024.on | prepared | 3.503958 | 0.068875 | 10000 | 1824145–1824145 | 15419616 |
| projection_wide.scalar.b1024.on | resident | 3.541084 | 0.029354 | 10000 | 1824145–1824145 | 15419616 |
| projection_wide.vector.b1024.off | prepared | 3.728250 | 0.064542 | 10000 | 1824145–1824145 | 15419616 |
| projection_wide.vector.b1024.off | resident | 3.750625 | 0.101855 | 10000 | 1824145–1824145 | 15419616 |
| projection_wide.vector.b1024.on | prepared | 3.748292 | 0.176271 | 10000 | 1824145–1824145 | 15419616 |
| projection_wide.vector.b1024.on | resident | 3.750209 | 0.134375 | 10000 | 1824145–1824145 | 15419616 |
| scan_broad.scalar.b1024.off | prepared | 1.043084 | 0.001000 | 1 | 115–115 | 15419616 |
| scan_broad.scalar.b1024.off | resident | 1.057000 | 0.002979 | 1 | 115–115 | 15419616 |
| scan_broad.scalar.b1024.on | prepared | 1.043209 | 0.001729 | 1 | 115–115 | 15419616 |
| scan_broad.scalar.b1024.on | resident | 1.056500 | 0.003125 | 1 | 115–115 | 15419616 |
| scan_broad.vector.b1024.off | prepared | 0.273292 | 0.001917 | 1 | 115–115 | 15419616 |
| scan_broad.vector.b1024.off | resident | 0.293041 | 0.005875 | 1 | 115–115 | 15419616 |
| scan_broad.vector.b1024.on | prepared | 0.272417 | 0.001708 | 1 | 115–115 | 15419616 |
| scan_broad.vector.b1024.on | resident | 0.288583 | 0.009291 | 1 | 115–115 | 15419616 |
| scan_selective.scalar.b1024.off | prepared | 0.739584 | 0.002292 | 1 | 112–112 | 15419616 |
| scan_selective.scalar.b1024.off | resident | 0.756333 | 0.006479 | 1 | 112–112 | 15419616 |
| scan_selective.scalar.b1024.on | prepared | 0.738958 | 0.001291 | 1 | 112–112 | 15419616 |
| scan_selective.scalar.b1024.on | resident | 0.752958 | 0.003146 | 1 | 112–112 | 15419616 |
| scan_selective.vector.b1024.off | prepared | 0.189750 | 0.001855 | 1 | 112–112 | 15419616 |
| scan_selective.vector.b1024.off | resident | 0.205084 | 0.009166 | 1 | 112–112 | 15419616 |
| scan_selective.vector.b1024.on | prepared | 0.188917 | 0.002021 | 1 | 112–112 | 15419616 |
| scan_selective.vector.b1024.on | resident | 0.204625 | 0.012813 | 1 | 112–112 | 15419616 |
| scan_selective.vector.b256.off | prepared | 0.210416 | 0.003104 | 1 | 112–112 | 15419616 |
| scan_selective.vector.b256.off | resident | 0.225250 | 0.001999 | 1 | 112–112 | 15419616 |
| scan_selective.vector.b256.on | prepared | 0.213500 | 0.003541 | 1 | 112–112 | 15419616 |
| scan_selective.vector.b256.on | resident | 0.225084 | 0.001146 | 1 | 112–112 | 15419616 |
| scan_selective.vector.b4096.off | prepared | 0.195833 | 0.026229 | 1 | 112–112 | 15419616 |
| scan_selective.vector.b4096.off | resident | 0.213875 | 0.030772 | 1 | 112–112 | 15419616 |
| scan_selective.vector.b4096.on | prepared | 0.224834 | 0.025041 | 1 | 112–112 | 15419616 |
| scan_selective.vector.b4096.on | resident | 0.234958 | 0.041188 | 1 | 112–112 | 15419616 |
| sort_limit.scalar.b1024.off | prepared | 2.530625 | 0.050042 | 1000 | 16543–16543 | 15419616 |
| sort_limit.scalar.b1024.off | resident | 2.619584 | 0.093896 | 1000 | 16543–16543 | 15419616 |
| sort_limit.scalar.b1024.on | prepared | 2.617167 | 0.053188 | 1000 | 16543–16543 | 15419616 |
| sort_limit.scalar.b1024.on | resident | 2.564583 | 0.049876 | 1000 | 16543–16543 | 15419616 |
| sort_limit.vector.b1024.off | prepared | 1.401208 | 0.029604 | 1000 | 16543–16543 | 15419616 |
| sort_limit.vector.b1024.off | resident | 1.433125 | 0.039624 | 1000 | 16543–16543 | 15419616 |
| sort_limit.vector.b1024.on | prepared | 1.384875 | 0.015146 | 1000 | 16543–16543 | 15419616 |
| sort_limit.vector.b1024.on | resident | 1.384083 | 0.044479 | 1000 | 16543–16543 | 15419616 |

| Comparison | Track | Baseline → candidate | Median ratio | Paired ratio median [Q1, Q3] | Observation |
| --- | --- | --- | ---: | ---: | --- |
| optimizer_off_vs_on | prepared | group_high.scalar.b1024.off → group_high.scalar.b1024.on | 0.997 | 0.996 [0.994, 1.000] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | group_high.vector.b1024.off → group_high.vector.b256.off | 0.984 | 0.983 [0.978, 0.987] | slower |
| optimizer_off_vs_on | prepared | group_high.vector.b256.off → group_high.vector.b256.on | 1.000 | 0.998 [0.992, 1.001] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | group_high.vector.b1024.on → group_high.vector.b256.on | 0.992 | 0.983 [0.975, 1.022] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | group_high.scalar.b1024.off → group_high.vector.b1024.off | 1.227 | 1.224 [1.223, 1.229] | faster |
| scalar_vs_vector | prepared | group_high.scalar.b1024.on → group_high.vector.b1024.on | 1.220 | 1.217 [1.184, 1.229] | faster |
| optimizer_off_vs_on | prepared | group_high.vector.b1024.off → group_high.vector.b1024.on | 0.992 | 0.998 [0.989, 1.002] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | group_high.vector.b1024.off → group_high.vector.b4096.off | 1.003 | 1.001 [0.974, 1.008] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | prepared | group_high.vector.b4096.off → group_high.vector.b4096.on | 1.003 | 1.004 [0.993, 1.037] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | group_high.vector.b1024.on → group_high.vector.b4096.on | 1.015 | 1.010 [1.003, 1.043] | faster |
| optimizer_off_vs_on | resident | group_high.scalar.b1024.off → group_high.scalar.b1024.on | 1.001 | 0.999 [0.995, 1.005] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | resident | group_high.vector.b1024.off → group_high.vector.b256.off | 0.990 | 0.991 [0.955, 0.997] | slower |
| optimizer_off_vs_on | resident | group_high.vector.b256.off → group_high.vector.b256.on | 1.001 | 1.001 [1.000, 1.014] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | resident | group_high.vector.b1024.on → group_high.vector.b256.on | 1.001 | 1.002 [0.988, 1.011] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | group_high.scalar.b1024.off → group_high.vector.b1024.off | 1.221 | 1.227 [1.213, 1.239] | faster |
| scalar_vs_vector | resident | group_high.scalar.b1024.on → group_high.vector.b1024.on | 1.208 | 1.204 [1.193, 1.224] | faster |
| optimizer_off_vs_on | resident | group_high.vector.b1024.off → group_high.vector.b1024.on | 0.990 | 0.979 [0.977, 0.987] | slower |
| batch_1024_vs_selected | resident | group_high.vector.b1024.off → group_high.vector.b4096.off | 1.007 | 1.004 [0.994, 1.011] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | group_high.vector.b4096.off → group_high.vector.b4096.on | 1.004 | 1.002 [0.996, 1.012] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | resident | group_high.vector.b1024.on → group_high.vector.b4096.on | 1.021 | 1.029 [1.021, 1.037] | faster |
| optimizer_off_vs_on | prepared | group_low.scalar.b1024.off → group_low.scalar.b1024.on | 1.008 | 1.009 [1.004, 1.010] | faster |
| scalar_vs_vector | prepared | group_low.scalar.b1024.off → group_low.vector.b1024.off | 1.284 | 1.283 [1.274, 1.288] | faster |
| scalar_vs_vector | prepared | group_low.scalar.b1024.on → group_low.vector.b1024.on | 1.277 | 1.277 [1.275, 1.280] | faster |
| optimizer_off_vs_on | prepared | group_low.vector.b1024.off → group_low.vector.b1024.on | 1.003 | 1.002 [0.997, 1.004] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | group_low.scalar.b1024.off → group_low.scalar.b1024.on | 1.000 | 1.001 [1.000, 1.004] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | group_low.scalar.b1024.off → group_low.vector.b1024.off | 1.263 | 1.265 [1.255, 1.271] | faster |
| scalar_vs_vector | resident | group_low.scalar.b1024.on → group_low.vector.b1024.on | 1.272 | 1.272 [1.271, 1.277] | faster |
| optimizer_off_vs_on | resident | group_low.vector.b1024.off → group_low.vector.b1024.on | 1.007 | 1.007 [1.000, 1.015] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | prepared | group_string.scalar.b1024.off → group_string.scalar.b1024.on | 0.999 | 0.999 [0.994, 1.001] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | group_string.scalar.b1024.off → group_string.vector.b1024.off | 1.383 | 1.385 [1.375, 1.386] | faster |
| scalar_vs_vector | prepared | group_string.scalar.b1024.on → group_string.vector.b1024.on | 1.370 | 1.369 [1.358, 1.383] | faster |
| optimizer_off_vs_on | prepared | group_string.vector.b1024.off → group_string.vector.b1024.on | 0.990 | 1.001 [0.976, 1.004] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | group_string.scalar.b1024.off → group_string.scalar.b1024.on | 1.000 | 1.002 [0.997, 1.005] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | group_string.scalar.b1024.off → group_string.vector.b1024.off | 1.366 | 1.367 [1.363, 1.370] | faster |
| scalar_vs_vector | resident | group_string.scalar.b1024.on → group_string.vector.b1024.on | 1.374 | 1.375 [1.373, 1.385] | faster |
| optimizer_off_vs_on | resident | group_string.vector.b1024.off → group_string.vector.b1024.on | 1.006 | 1.005 [1.004, 1.014] | faster |
| optimizer_off_vs_on | prepared | join_skew.scalar.b1024.off → join_skew.scalar.b1024.on | 1.296 | 1.294 [1.292, 1.297] | faster |
| scalar_vs_vector | prepared | join_skew.scalar.b1024.off → join_skew.vector.b1024.off | 1.603 | 1.602 [1.600, 1.603] | faster |
| scalar_vs_vector | prepared | join_skew.scalar.b1024.on → join_skew.vector.b1024.on | 1.680 | 1.680 [1.676, 1.685] | faster |
| optimizer_off_vs_on | prepared | join_skew.vector.b1024.off → join_skew.vector.b1024.on | 1.358 | 1.357 [1.356, 1.361] | faster |
| optimizer_off_vs_on | resident | join_skew.scalar.b1024.off → join_skew.scalar.b1024.on | 1.293 | 1.292 [1.284, 1.297] | faster |
| scalar_vs_vector | resident | join_skew.scalar.b1024.off → join_skew.vector.b1024.off | 1.593 | 1.593 [1.583, 1.598] | faster |
| scalar_vs_vector | resident | join_skew.scalar.b1024.on → join_skew.vector.b1024.on | 1.656 | 1.658 [1.647, 1.669] | faster |
| optimizer_off_vs_on | resident | join_skew.vector.b1024.off → join_skew.vector.b1024.on | 1.344 | 1.342 [1.334, 1.355] | faster |
| optimizer_off_vs_on | prepared | join_uniform.scalar.b1024.off → join_uniform.scalar.b1024.on | 1.294 | 1.293 [1.291, 1.296] | faster |
| scalar_vs_vector | prepared | join_uniform.scalar.b1024.off → join_uniform.vector.b1024.off | 1.615 | 1.621 [1.606, 1.622] | faster |
| scalar_vs_vector | prepared | join_uniform.scalar.b1024.on → join_uniform.vector.b1024.on | 1.684 | 1.678 [1.677, 1.688] | faster |
| optimizer_off_vs_on | prepared | join_uniform.vector.b1024.off → join_uniform.vector.b1024.on | 1.349 | 1.342 [1.336, 1.356] | faster |
| optimizer_off_vs_on | resident | join_uniform.scalar.b1024.off → join_uniform.scalar.b1024.on | 1.287 | 1.291 [1.285, 1.292] | faster |
| scalar_vs_vector | resident | join_uniform.scalar.b1024.off → join_uniform.vector.b1024.off | 1.593 | 1.595 [1.587, 1.601] | faster |
| scalar_vs_vector | resident | join_uniform.scalar.b1024.on → join_uniform.vector.b1024.on | 1.669 | 1.669 [1.653, 1.680] | faster |
| optimizer_off_vs_on | resident | join_uniform.vector.b1024.off → join_uniform.vector.b1024.on | 1.348 | 1.348 [1.337, 1.359] | faster |
| optimizer_off_vs_on | prepared | null_heavy.scalar.b1024.off → null_heavy.scalar.b1024.on | 0.999 | 1.000 [0.996, 1.000] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | null_heavy.scalar.b1024.off → null_heavy.vector.b1024.off | 2.475 | 2.471 [2.451, 2.474] | faster |
| scalar_vs_vector | prepared | null_heavy.scalar.b1024.on → null_heavy.vector.b1024.on | 2.436 | 2.436 [2.405, 2.477] | faster |
| optimizer_off_vs_on | prepared | null_heavy.vector.b1024.off → null_heavy.vector.b1024.on | 0.983 | 0.999 [0.981, 1.001] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | null_heavy.scalar.b1024.off → null_heavy.scalar.b1024.on | 0.996 | 1.007 [0.990, 1.012] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | null_heavy.scalar.b1024.off → null_heavy.vector.b1024.off | 2.338 | 2.333 [2.239, 2.380] | faster |
| scalar_vs_vector | resident | null_heavy.scalar.b1024.on → null_heavy.vector.b1024.on | 2.370 | 2.360 [2.340, 2.384] | faster |
| optimizer_off_vs_on | resident | null_heavy.vector.b1024.off → null_heavy.vector.b1024.on | 1.010 | 1.005 [1.000, 1.027] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | prepared | null_light.scalar.b1024.off → null_light.scalar.b1024.on | 1.002 | 1.003 [1.002, 1.006] | faster |
| scalar_vs_vector | prepared | null_light.scalar.b1024.off → null_light.vector.b1024.off | 1.887 | 1.899 [1.870, 1.908] | faster |
| scalar_vs_vector | prepared | null_light.scalar.b1024.on → null_light.vector.b1024.on | 1.884 | 1.886 [1.841, 1.898] | faster |
| optimizer_off_vs_on | prepared | null_light.vector.b1024.off → null_light.vector.b1024.on | 1.000 | 1.004 [0.971, 1.013] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | null_light.scalar.b1024.off → null_light.scalar.b1024.on | 0.989 | 0.993 [0.983, 1.007] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | null_light.scalar.b1024.off → null_light.vector.b1024.off | 1.837 | 1.845 [1.838, 1.876] | faster |
| scalar_vs_vector | resident | null_light.scalar.b1024.on → null_light.vector.b1024.on | 1.860 | 1.860 [1.813, 1.877] | faster |
| optimizer_off_vs_on | resident | null_light.vector.b1024.off → null_light.vector.b1024.on | 1.002 | 1.002 [0.970, 1.012] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | prepared | projection_narrow.scalar.b1024.off → projection_narrow.scalar.b1024.on | 1.038 | 1.023 [1.007, 1.041] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | projection_narrow.scalar.b1024.off → projection_narrow.vector.b1024.off | 1.238 | 1.201 [1.166, 1.240] | faster |
| scalar_vs_vector | prepared | projection_narrow.scalar.b1024.on → projection_narrow.vector.b1024.on | 1.219 | 1.221 [1.184, 1.238] | faster |
| optimizer_off_vs_on | prepared | projection_narrow.vector.b1024.off → projection_narrow.vector.b1024.on | 1.021 | 1.025 [0.992, 1.078] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | projection_narrow.scalar.b1024.off → projection_narrow.scalar.b1024.on | 0.970 | 0.989 [0.974, 0.998] | slower |
| scalar_vs_vector | resident | projection_narrow.scalar.b1024.off → projection_narrow.vector.b1024.off | 1.140 | 1.164 [1.110, 1.191] | faster |
| scalar_vs_vector | resident | projection_narrow.scalar.b1024.on → projection_narrow.vector.b1024.on | 1.224 | 1.205 [1.194, 1.233] | faster |
| optimizer_off_vs_on | resident | projection_narrow.vector.b1024.off → projection_narrow.vector.b1024.on | 1.041 | 1.041 [1.000, 1.065] | faster |
| optimizer_off_vs_on | prepared | projection_wide.scalar.b1024.off → projection_wide.scalar.b1024.on | 1.002 | 1.003 [0.994, 1.010] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | projection_wide.scalar.b1024.off → projection_wide.vector.b1024.off | 0.941 | 0.940 [0.936, 0.946] | slower |
| scalar_vs_vector | prepared | projection_wide.scalar.b1024.on → projection_wide.vector.b1024.on | 0.935 | 0.935 [0.917, 0.942] | slower |
| optimizer_off_vs_on | prepared | projection_wide.vector.b1024.off → projection_wide.vector.b1024.on | 0.995 | 0.989 [0.965, 0.998] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | projection_wide.scalar.b1024.off → projection_wide.scalar.b1024.on | 0.996 | 0.994 [0.985, 1.004] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | projection_wide.scalar.b1024.off → projection_wide.vector.b1024.off | 0.940 | 0.935 [0.916, 0.946] | slower |
| scalar_vs_vector | resident | projection_wide.scalar.b1024.on → projection_wide.vector.b1024.on | 0.944 | 0.940 [0.939, 0.943] | slower |
| optimizer_off_vs_on | resident | projection_wide.vector.b1024.off → projection_wide.vector.b1024.on | 1.000 | 0.998 [0.992, 1.002] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | prepared | scan_broad.scalar.b1024.off → scan_broad.scalar.b1024.on | 1.000 | 1.000 [1.000, 1.002] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | scan_broad.scalar.b1024.off → scan_broad.vector.b1024.off | 3.817 | 3.815 [3.802, 3.827] | faster |
| scalar_vs_vector | prepared | scan_broad.scalar.b1024.on → scan_broad.vector.b1024.on | 3.829 | 3.829 [3.807, 3.832] | faster |
| optimizer_off_vs_on | prepared | scan_broad.vector.b1024.off → scan_broad.vector.b1024.on | 1.003 | 1.000 [0.997, 1.003] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | scan_broad.scalar.b1024.off → scan_broad.scalar.b1024.on | 1.000 | 1.001 [1.000, 1.001] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | scan_broad.scalar.b1024.off → scan_broad.vector.b1024.off | 3.607 | 3.603 [3.591, 3.671] | faster |
| scalar_vs_vector | resident | scan_broad.scalar.b1024.on → scan_broad.vector.b1024.on | 3.661 | 3.675 [3.591, 3.711] | faster |
| optimizer_off_vs_on | resident | scan_broad.vector.b1024.off → scan_broad.vector.b1024.on | 1.015 | 1.015 [0.990, 1.032] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | prepared | scan_selective.scalar.b1024.off → scan_selective.scalar.b1024.on | 1.001 | 1.001 [0.999, 1.004] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | scan_selective.vector.b1024.off → scan_selective.vector.b256.off | 0.902 | 0.897 [0.896, 0.906] | slower |
| optimizer_off_vs_on | prepared | scan_selective.vector.b256.off → scan_selective.vector.b256.on | 0.986 | 0.990 [0.977, 1.000] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | scan_selective.vector.b1024.on → scan_selective.vector.b256.on | 0.885 | 0.890 [0.887, 0.893] | slower |
| scalar_vs_vector | prepared | scan_selective.scalar.b1024.off → scan_selective.vector.b1024.off | 3.898 | 3.902 [3.895, 3.919] | faster |
| scalar_vs_vector | prepared | scan_selective.scalar.b1024.on → scan_selective.vector.b1024.on | 3.912 | 3.912 [3.876, 3.920] | faster |
| optimizer_off_vs_on | prepared | scan_selective.vector.b1024.off → scan_selective.vector.b1024.on | 1.004 | 0.999 [0.995, 1.012] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | scan_selective.vector.b1024.off → scan_selective.vector.b4096.off | 0.969 | 0.962 [0.890, 0.991] | slower |
| optimizer_off_vs_on | prepared | scan_selective.vector.b4096.off → scan_selective.vector.b4096.on | 0.871 | 0.973 [0.889, 0.986] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | scan_selective.vector.b1024.on → scan_selective.vector.b4096.on | 0.840 | 0.851 [0.810, 0.905] | slower |
| optimizer_off_vs_on | resident | scan_selective.scalar.b1024.off → scan_selective.scalar.b1024.on | 1.004 | 1.003 [1.001, 1.012] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | resident | scan_selective.vector.b1024.off → scan_selective.vector.b256.off | 0.910 | 0.916 [0.893, 0.948] | slower |
| optimizer_off_vs_on | resident | scan_selective.vector.b256.off → scan_selective.vector.b256.on | 1.001 | 1.006 [0.998, 1.012] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | resident | scan_selective.vector.b1024.on → scan_selective.vector.b256.on | 0.909 | 0.908 [0.896, 0.950] | slower |
| scalar_vs_vector | resident | scan_selective.scalar.b1024.off → scan_selective.vector.b1024.off | 3.688 | 3.698 [3.542, 3.718] | faster |
| scalar_vs_vector | resident | scan_selective.scalar.b1024.on → scan_selective.vector.b1024.on | 3.680 | 3.692 [3.503, 3.741] | faster |
| optimizer_off_vs_on | resident | scan_selective.vector.b1024.off → scan_selective.vector.b1024.on | 1.002 | 1.000 [0.981, 1.017] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | resident | scan_selective.vector.b1024.off → scan_selective.vector.b4096.off | 0.959 | 0.955 [0.850, 0.999] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | scan_selective.vector.b4096.off → scan_selective.vector.b4096.on | 0.910 | 0.930 [0.920, 1.048] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | resident | scan_selective.vector.b1024.on → scan_selective.vector.b4096.on | 0.871 | 0.871 [0.841, 0.967] | slower |
| optimizer_off_vs_on | prepared | sort_limit.scalar.b1024.off → sort_limit.scalar.b1024.on | 0.967 | 0.969 [0.961, 0.973] | slower |
| scalar_vs_vector | prepared | sort_limit.scalar.b1024.off → sort_limit.vector.b1024.off | 1.806 | 1.795 [1.793, 1.836] | faster |
| scalar_vs_vector | prepared | sort_limit.scalar.b1024.on → sort_limit.vector.b1024.on | 1.890 | 1.908 [1.875, 1.932] | faster |
| optimizer_off_vs_on | prepared | sort_limit.vector.b1024.off → sort_limit.vector.b1024.on | 1.012 | 1.021 [0.995, 1.035] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | sort_limit.scalar.b1024.off → sort_limit.scalar.b1024.on | 1.021 | 1.016 [1.004, 1.031] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | sort_limit.scalar.b1024.off → sort_limit.vector.b1024.off | 1.828 | 1.841 [1.803, 1.865] | faster |
| scalar_vs_vector | resident | sort_limit.scalar.b1024.on → sort_limit.vector.b1024.on | 1.853 | 1.859 [1.812, 1.865] | faster |
| optimizer_off_vs_on | resident | sort_limit.vector.b1024.off → sort_limit.vector.b1024.on | 1.035 | 1.005 [0.997, 1.041] | inconclusive (IQR overlap) |

## 100,000 sales rows

Source `993bef547cee6f56657330eafcd606b4c8d535760e9e97e04bd4242e4bc1b553`; binary `4bb67a95d79b66d09811158e0cce9d3a4411b21dc5e32bc43687f9b2e0ede9ad`.

Raw records: `/Users/goktugbas/Major_Projects/quarry/reports/benchmarks/final-100000/measurements.jsonl`, SHA256 `f28a51bb400cb7945afc2c7c971002a7402515ebe908deef846d32c8bc7549c3`. Hardware: macOS-15.7.1-arm64-arm-64bit, arm64, Apple M1 Pro.

Recorded trials: 784; warmups: 224. Observed comparisons: faster: 57, inconclusive (IQR overlap): 49, slower: 14.

| Case | Track | Median ms | IQR ms | Rows | Output bytes min–max | Accounted lifetime peak bytes |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| group_high.scalar.b1024.off | prepared | 9.970375 | 0.183605 | 2048 | 39979–39979 | 140419616 |
| group_high.scalar.b1024.off | resident | 9.883500 | 0.313292 | 2048 | 39979–39979 | 140419616 |
| group_high.scalar.b1024.on | prepared | 9.904792 | 0.147313 | 2048 | 39979–39979 | 140419616 |
| group_high.scalar.b1024.on | resident | 10.036167 | 0.229750 | 2048 | 39979–39979 | 140419616 |
| group_high.vector.b1024.off | prepared | 8.218375 | 0.285291 | 2048 | 39979–39979 | 140419616 |
| group_high.vector.b1024.off | resident | 7.950375 | 0.205833 | 2048 | 39979–39979 | 140419616 |
| group_high.vector.b1024.on | prepared | 7.923958 | 0.286292 | 2048 | 39979–39979 | 140419616 |
| group_high.vector.b1024.on | resident | 7.982334 | 0.108687 | 2048 | 39979–39979 | 140419616 |
| group_high.vector.b256.off | prepared | 8.117333 | 0.236729 | 2048 | 39979–39979 | 140419616 |
| group_high.vector.b256.off | resident | 8.261375 | 0.239251 | 2048 | 39979–39979 | 140419616 |
| group_high.vector.b256.on | prepared | 7.910500 | 0.125958 | 2048 | 39979–39979 | 140419616 |
| group_high.vector.b256.on | resident | 8.062208 | 0.305937 | 2048 | 39979–39979 | 140419616 |
| group_high.vector.b4096.off | prepared | 7.787833 | 0.263605 | 2048 | 39979–39979 | 140419616 |
| group_high.vector.b4096.off | resident | 7.962458 | 0.080250 | 2048 | 39979–39979 | 140419616 |
| group_high.vector.b4096.on | prepared | 7.926916 | 0.539250 | 2048 | 39979–39979 | 140419616 |
| group_high.vector.b4096.on | resident | 7.826750 | 0.085126 | 2048 | 39979–39979 | 140419616 |
| group_low.scalar.b1024.off | prepared | 9.148292 | 0.004958 | 16 | 470–470 | 140419616 |
| group_low.scalar.b1024.off | resident | 9.159125 | 0.083229 | 16 | 470–470 | 140419616 |
| group_low.scalar.b1024.on | prepared | 9.143292 | 0.022229 | 16 | 470–470 | 140419616 |
| group_low.scalar.b1024.on | resident | 9.165166 | 0.011022 | 16 | 470–470 | 140419616 |
| group_low.vector.b1024.off | prepared | 7.063250 | 0.022333 | 16 | 470–470 | 140419616 |
| group_low.vector.b1024.off | resident | 7.076833 | 0.038354 | 16 | 470–470 | 140419616 |
| group_low.vector.b1024.on | prepared | 7.062042 | 0.015874 | 16 | 470–470 | 140419616 |
| group_low.vector.b1024.on | resident | 7.063000 | 0.022188 | 16 | 470–470 | 140419616 |
| group_string.scalar.b1024.off | prepared | 12.510250 | 0.013938 | 9 | 380–380 | 140419616 |
| group_string.scalar.b1024.off | resident | 12.513667 | 0.135271 | 9 | 380–380 | 140419616 |
| group_string.scalar.b1024.on | prepared | 12.510875 | 0.027771 | 9 | 380–380 | 140419616 |
| group_string.scalar.b1024.on | resident | 12.510458 | 0.028334 | 9 | 380–380 | 140419616 |
| group_string.vector.b1024.off | prepared | 8.915250 | 0.049917 | 9 | 380–380 | 140419616 |
| group_string.vector.b1024.off | resident | 8.922500 | 0.029125 | 9 | 380–380 | 140419616 |
| group_string.vector.b1024.on | prepared | 8.949250 | 0.069334 | 9 | 380–380 | 140419616 |
| group_string.vector.b1024.on | resident | 8.915250 | 0.032792 | 9 | 380–380 | 140419616 |
| join_skew.scalar.b1024.off | prepared | 23.253375 | 0.037417 | 8 | 322–322 | 140419616 |
| join_skew.scalar.b1024.off | resident | 23.592333 | 0.407791 | 8 | 322–322 | 140419616 |
| join_skew.scalar.b1024.on | prepared | 17.810583 | 0.042521 | 8 | 322–322 | 140419616 |
| join_skew.scalar.b1024.on | resident | 17.837625 | 0.095646 | 8 | 322–322 | 140419616 |
| join_skew.vector.b1024.off | prepared | 14.191459 | 0.081667 | 8 | 322–322 | 140419616 |
| join_skew.vector.b1024.off | resident | 14.203583 | 0.132708 | 8 | 322–322 | 140419616 |
| join_skew.vector.b1024.on | prepared | 10.220333 | 0.199709 | 8 | 322–322 | 140419616 |
| join_skew.vector.b1024.on | resident | 10.274667 | 0.085146 | 8 | 322–322 | 140419616 |
| join_uniform.scalar.b1024.off | prepared | 23.363542 | 0.018062 | 8 | 322–322 | 140419616 |
| join_uniform.scalar.b1024.off | resident | 23.419459 | 0.026667 | 8 | 322–322 | 140419616 |
| join_uniform.scalar.b1024.on | prepared | 17.922042 | 0.066104 | 8 | 322–322 | 140419616 |
| join_uniform.scalar.b1024.on | resident | 17.955958 | 0.026875 | 8 | 322–322 | 140419616 |
| join_uniform.vector.b1024.off | prepared | 14.086875 | 0.109146 | 8 | 322–322 | 140419616 |
| join_uniform.vector.b1024.off | resident | 14.156500 | 0.011354 | 8 | 322–322 | 140419616 |
| join_uniform.vector.b1024.on | prepared | 10.281375 | 0.037937 | 8 | 322–322 | 140419616 |
| join_uniform.vector.b1024.on | resident | 10.265917 | 0.043917 | 8 | 322–322 | 140419616 |
| null_heavy.scalar.b1024.off | prepared | 4.706792 | 0.005542 | 1 | 166–166 | 140419616 |
| null_heavy.scalar.b1024.off | resident | 4.729708 | 0.048042 | 1 | 166–166 | 140419616 |
| null_heavy.scalar.b1024.on | prepared | 4.717333 | 0.041750 | 1 | 166–166 | 140419616 |
| null_heavy.scalar.b1024.on | resident | 4.729625 | 0.011208 | 1 | 166–166 | 140419616 |
| null_heavy.vector.b1024.off | prepared | 1.792250 | 0.007291 | 1 | 166–166 | 140419616 |
| null_heavy.vector.b1024.off | resident | 1.813209 | 0.015812 | 1 | 166–166 | 140419616 |
| null_heavy.vector.b1024.on | prepared | 1.803542 | 0.012250 | 1 | 166–166 | 140419616 |
| null_heavy.vector.b1024.on | resident | 1.808583 | 0.019251 | 1 | 166–166 | 140419616 |
| null_light.scalar.b1024.off | prepared | 5.217000 | 0.018707 | 1 | 177–177 | 140419616 |
| null_light.scalar.b1024.off | resident | 5.238500 | 0.010854 | 1 | 177–177 | 140419616 |
| null_light.scalar.b1024.on | prepared | 5.218375 | 0.012958 | 1 | 177–177 | 140419616 |
| null_light.scalar.b1024.on | resident | 5.231542 | 0.020751 | 1 | 177–177 | 140419616 |
| null_light.vector.b1024.off | prepared | 2.656250 | 0.015083 | 1 | 177–177 | 140419616 |
| null_light.vector.b1024.off | resident | 2.672958 | 0.013374 | 1 | 177–177 | 140419616 |
| null_light.vector.b1024.on | prepared | 2.668333 | 0.020375 | 1 | 177–177 | 140419616 |
| null_light.vector.b1024.on | resident | 2.664875 | 0.013437 | 1 | 177–177 | 140419616 |
| projection_narrow.scalar.b1024.off | prepared | 9.106250 | 0.172167 | 100000 | 1443993–1443993 | 140419616 |
| projection_narrow.scalar.b1024.off | resident | 9.128167 | 0.131083 | 100000 | 1443993–1443993 | 140419616 |
| projection_narrow.scalar.b1024.on | prepared | 8.947583 | 0.126291 | 100000 | 1443993–1443993 | 140419616 |
| projection_narrow.scalar.b1024.on | resident | 8.826125 | 0.079001 | 100000 | 1443993–1443993 | 140419616 |
| projection_narrow.vector.b1024.off | prepared | 7.455834 | 0.110770 | 100000 | 1443993–1443993 | 140419616 |
| projection_narrow.vector.b1024.off | resident | 7.657708 | 0.299813 | 100000 | 1443993–1443993 | 140419616 |
| projection_narrow.vector.b1024.on | prepared | 7.712333 | 0.268291 | 100000 | 1443993–1443993 | 140419616 |
| projection_narrow.vector.b1024.on | resident | 7.476083 | 0.137105 | 100000 | 1443993–1443993 | 140419616 |
| projection_wide.scalar.b1024.off | prepared | 37.645834 | 1.037167 | 100000 | 18337687–18337687 | 140419616 |
| projection_wide.scalar.b1024.off | resident | 37.721958 | 0.691063 | 100000 | 18337687–18337687 | 140419616 |
| projection_wide.scalar.b1024.on | prepared | 37.278833 | 0.349000 | 100000 | 18337687–18337687 | 140419616 |
| projection_wide.scalar.b1024.on | resident | 37.120625 | 0.959146 | 100000 | 18337687–18337687 | 140419616 |
| projection_wide.vector.b1024.off | prepared | 40.727166 | 1.834979 | 100000 | 18337687–18337687 | 140419616 |
| projection_wide.vector.b1024.off | resident | 40.571500 | 0.386771 | 100000 | 18337687–18337687 | 140419616 |
| projection_wide.vector.b1024.on | prepared | 40.671083 | 0.930937 | 100000 | 18337687–18337687 | 140419616 |
| projection_wide.vector.b1024.on | resident | 40.615833 | 0.638250 | 100000 | 18337687–18337687 | 140419616 |
| scan_broad.scalar.b1024.off | prepared | 10.396791 | 0.014604 | 1 | 117–117 | 140419616 |
| scan_broad.scalar.b1024.off | resident | 10.410708 | 0.043146 | 1 | 117–117 | 140419616 |
| scan_broad.scalar.b1024.on | prepared | 10.389416 | 0.007105 | 1 | 117–117 | 140419616 |
| scan_broad.scalar.b1024.on | resident | 10.429917 | 0.057605 | 1 | 117–117 | 140419616 |
| scan_broad.vector.b1024.off | prepared | 2.607084 | 0.019395 | 1 | 117–117 | 140419616 |
| scan_broad.vector.b1024.off | resident | 2.639209 | 0.023459 | 1 | 117–117 | 140419616 |
| scan_broad.vector.b1024.on | prepared | 2.625541 | 0.019395 | 1 | 117–117 | 140419616 |
| scan_broad.vector.b1024.on | resident | 2.624583 | 0.024271 | 1 | 117–117 | 140419616 |
| scan_selective.scalar.b1024.off | prepared | 7.358625 | 0.011146 | 1 | 114–114 | 140419616 |
| scan_selective.scalar.b1024.off | resident | 7.395000 | 0.016792 | 1 | 114–114 | 140419616 |
| scan_selective.scalar.b1024.on | prepared | 7.352750 | 0.006918 | 1 | 114–114 | 140419616 |
| scan_selective.scalar.b1024.on | resident | 7.368416 | 0.018624 | 1 | 114–114 | 140419616 |
| scan_selective.vector.b1024.off | prepared | 1.773208 | 0.019459 | 1 | 114–114 | 140419616 |
| scan_selective.vector.b1024.off | resident | 1.794209 | 0.013938 | 1 | 114–114 | 140419616 |
| scan_selective.vector.b1024.on | prepared | 1.777875 | 0.032500 | 1 | 114–114 | 140419616 |
| scan_selective.vector.b1024.on | resident | 1.818709 | 0.023500 | 1 | 114–114 | 140419616 |
| scan_selective.vector.b256.off | prepared | 1.999125 | 0.020021 | 1 | 114–114 | 140419616 |
| scan_selective.vector.b256.off | resident | 2.015792 | 0.023541 | 1 | 114–114 | 140419616 |
| scan_selective.vector.b256.on | prepared | 1.991125 | 0.010854 | 1 | 114–114 | 140419616 |
| scan_selective.vector.b256.on | resident | 2.009333 | 0.016646 | 1 | 114–114 | 140419616 |
| scan_selective.vector.b4096.off | prepared | 1.895750 | 0.110750 | 1 | 114–114 | 140419616 |
| scan_selective.vector.b4096.off | resident | 1.940333 | 0.170937 | 1 | 114–114 | 140419616 |
| scan_selective.vector.b4096.on | prepared | 1.893250 | 0.161687 | 1 | 114–114 | 140419616 |
| scan_selective.vector.b4096.on | resident | 1.945750 | 0.063459 | 1 | 114–114 | 140419616 |
| sort_limit.scalar.b1024.off | prepared | 35.486625 | 0.468645 | 1000 | 17548–17548 | 140419616 |
| sort_limit.scalar.b1024.off | resident | 34.476750 | 1.320646 | 1000 | 17548–17548 | 140419616 |
| sort_limit.scalar.b1024.on | prepared | 35.465750 | 1.026229 | 1000 | 17548–17548 | 140419616 |
| sort_limit.scalar.b1024.on | resident | 34.524792 | 0.243417 | 1000 | 17548–17548 | 140419616 |
| sort_limit.vector.b1024.off | prepared | 18.980375 | 0.179291 | 1000 | 17548–17548 | 140419616 |
| sort_limit.vector.b1024.off | resident | 18.196584 | 0.751271 | 1000 | 17548–17548 | 140419616 |
| sort_limit.vector.b1024.on | prepared | 18.888667 | 0.341334 | 1000 | 17548–17548 | 140419616 |
| sort_limit.vector.b1024.on | resident | 18.666083 | 0.467229 | 1000 | 17548–17548 | 140419616 |

| Comparison | Track | Baseline → candidate | Median ratio | Paired ratio median [Q1, Q3] | Observation |
| --- | --- | --- | ---: | ---: | --- |
| optimizer_off_vs_on | prepared | group_high.scalar.b1024.off → group_high.scalar.b1024.on | 1.007 | 1.000 [0.992, 1.018] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | group_high.vector.b1024.off → group_high.vector.b256.off | 1.012 | 1.005 [0.989, 1.025] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | prepared | group_high.vector.b256.off → group_high.vector.b256.on | 1.026 | 1.000 [0.997, 1.029] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | group_high.vector.b1024.on → group_high.vector.b256.on | 1.002 | 0.980 [0.974, 1.005] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | group_high.scalar.b1024.off → group_high.vector.b1024.off | 1.213 | 1.226 [1.217, 1.244] | faster |
| scalar_vs_vector | prepared | group_high.scalar.b1024.on → group_high.vector.b1024.on | 1.250 | 1.242 [1.234, 1.277] | faster |
| optimizer_off_vs_on | prepared | group_high.vector.b1024.off → group_high.vector.b1024.on | 1.037 | 1.022 [1.008, 1.034] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | group_high.vector.b1024.off → group_high.vector.b4096.off | 1.055 | 1.035 [1.005, 1.055] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | prepared | group_high.vector.b4096.off → group_high.vector.b4096.on | 0.982 | 0.967 [0.932, 1.020] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | group_high.vector.b1024.on → group_high.vector.b4096.on | 1.000 | 0.986 [0.975, 1.019] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | group_high.scalar.b1024.off → group_high.scalar.b1024.on | 0.985 | 1.001 [0.978, 1.016] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | resident | group_high.vector.b1024.off → group_high.vector.b256.off | 0.962 | 0.994 [0.937, 1.003] | slower |
| optimizer_off_vs_on | resident | group_high.vector.b256.off → group_high.vector.b256.on | 1.025 | 1.013 [0.997, 1.047] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | resident | group_high.vector.b1024.on → group_high.vector.b256.on | 0.990 | 0.997 [0.976, 1.006] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | group_high.scalar.b1024.off → group_high.vector.b1024.off | 1.243 | 1.244 [1.234, 1.281] | faster |
| scalar_vs_vector | resident | group_high.scalar.b1024.on → group_high.vector.b1024.on | 1.257 | 1.256 [1.232, 1.269] | faster |
| optimizer_off_vs_on | resident | group_high.vector.b1024.off → group_high.vector.b1024.on | 0.996 | 0.998 [0.981, 1.005] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | resident | group_high.vector.b1024.off → group_high.vector.b4096.off | 0.998 | 0.994 [0.982, 1.011] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | group_high.vector.b4096.off → group_high.vector.b4096.on | 1.017 | 1.018 [1.010, 1.021] | faster |
| batch_1024_vs_selected | resident | group_high.vector.b1024.on → group_high.vector.b4096.on | 1.020 | 1.020 [1.017, 1.032] | faster |
| optimizer_off_vs_on | prepared | group_low.scalar.b1024.off → group_low.scalar.b1024.on | 1.001 | 1.001 [0.999, 1.002] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | group_low.scalar.b1024.off → group_low.vector.b1024.off | 1.295 | 1.295 [1.295, 1.297] | faster |
| scalar_vs_vector | prepared | group_low.scalar.b1024.on → group_low.vector.b1024.on | 1.295 | 1.295 [1.294, 1.296] | faster |
| optimizer_off_vs_on | prepared | group_low.vector.b1024.off → group_low.vector.b1024.on | 1.000 | 1.002 [0.996, 1.002] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | group_low.scalar.b1024.off → group_low.scalar.b1024.on | 0.999 | 0.999 [0.998, 1.007] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | group_low.scalar.b1024.off → group_low.vector.b1024.off | 1.294 | 1.293 [1.289, 1.304] | faster |
| scalar_vs_vector | resident | group_low.scalar.b1024.on → group_low.vector.b1024.on | 1.298 | 1.299 [1.296, 1.300] | faster |
| optimizer_off_vs_on | resident | group_low.vector.b1024.off → group_low.vector.b1024.on | 1.002 | 1.002 [1.001, 1.006] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | prepared | group_string.scalar.b1024.off → group_string.scalar.b1024.on | 1.000 | 1.000 [0.999, 1.002] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | group_string.scalar.b1024.off → group_string.vector.b1024.off | 1.403 | 1.403 [1.402, 1.409] | faster |
| scalar_vs_vector | prepared | group_string.scalar.b1024.on → group_string.vector.b1024.on | 1.398 | 1.401 [1.393, 1.402] | faster |
| optimizer_off_vs_on | prepared | group_string.vector.b1024.off → group_string.vector.b1024.on | 0.996 | 0.996 [0.989, 1.003] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | group_string.scalar.b1024.off → group_string.scalar.b1024.on | 1.000 | 1.002 [0.999, 1.010] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | group_string.scalar.b1024.off → group_string.vector.b1024.off | 1.402 | 1.404 [1.401, 1.414] | faster |
| scalar_vs_vector | resident | group_string.scalar.b1024.on → group_string.vector.b1024.on | 1.403 | 1.402 [1.400, 1.405] | faster |
| optimizer_off_vs_on | resident | group_string.vector.b1024.off → group_string.vector.b1024.on | 1.001 | 1.000 [1.000, 1.004] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | prepared | join_skew.scalar.b1024.off → join_skew.scalar.b1024.on | 1.306 | 1.306 [1.305, 1.307] | faster |
| scalar_vs_vector | prepared | join_skew.scalar.b1024.off → join_skew.vector.b1024.off | 1.639 | 1.641 [1.638, 1.647] | faster |
| scalar_vs_vector | prepared | join_skew.scalar.b1024.on → join_skew.vector.b1024.on | 1.743 | 1.743 [1.737, 1.745] | faster |
| optimizer_off_vs_on | prepared | join_skew.vector.b1024.off → join_skew.vector.b1024.on | 1.389 | 1.385 [1.359, 1.394] | faster |
| optimizer_off_vs_on | resident | join_skew.scalar.b1024.off → join_skew.scalar.b1024.on | 1.323 | 1.321 [1.311, 1.327] | faster |
| scalar_vs_vector | resident | join_skew.scalar.b1024.off → join_skew.vector.b1024.off | 1.661 | 1.658 [1.653, 1.680] | faster |
| scalar_vs_vector | resident | join_skew.scalar.b1024.on → join_skew.vector.b1024.on | 1.736 | 1.739 [1.734, 1.742] | faster |
| optimizer_off_vs_on | resident | join_skew.vector.b1024.off → join_skew.vector.b1024.on | 1.382 | 1.379 [1.378, 1.380] | faster |
| optimizer_off_vs_on | prepared | join_uniform.scalar.b1024.off → join_uniform.scalar.b1024.on | 1.304 | 1.304 [1.301, 1.305] | faster |
| scalar_vs_vector | prepared | join_uniform.scalar.b1024.off → join_uniform.vector.b1024.off | 1.659 | 1.660 [1.655, 1.661] | faster |
| scalar_vs_vector | prepared | join_uniform.scalar.b1024.on → join_uniform.vector.b1024.on | 1.743 | 1.744 [1.737, 1.750] | faster |
| optimizer_off_vs_on | prepared | join_uniform.vector.b1024.off → join_uniform.vector.b1024.on | 1.370 | 1.371 [1.368, 1.378] | faster |
| optimizer_off_vs_on | resident | join_uniform.scalar.b1024.off → join_uniform.scalar.b1024.on | 1.304 | 1.304 [1.303, 1.304] | faster |
| scalar_vs_vector | resident | join_uniform.scalar.b1024.off → join_uniform.vector.b1024.off | 1.654 | 1.654 [1.652, 1.655] | faster |
| scalar_vs_vector | resident | join_uniform.scalar.b1024.on → join_uniform.vector.b1024.on | 1.749 | 1.750 [1.741, 1.752] | faster |
| optimizer_off_vs_on | resident | join_uniform.vector.b1024.off → join_uniform.vector.b1024.on | 1.379 | 1.377 [1.374, 1.380] | faster |
| optimizer_off_vs_on | prepared | null_heavy.scalar.b1024.off → null_heavy.scalar.b1024.on | 0.998 | 0.998 [0.991, 0.999] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | null_heavy.scalar.b1024.off → null_heavy.vector.b1024.off | 2.626 | 2.625 [2.622, 2.633] | faster |
| scalar_vs_vector | prepared | null_heavy.scalar.b1024.on → null_heavy.vector.b1024.on | 2.616 | 2.626 [2.611, 2.657] | faster |
| optimizer_off_vs_on | prepared | null_heavy.vector.b1024.off → null_heavy.vector.b1024.on | 0.994 | 0.995 [0.993, 1.000] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | null_heavy.scalar.b1024.off → null_heavy.scalar.b1024.on | 1.000 | 1.001 [0.998, 1.008] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | null_heavy.scalar.b1024.off → null_heavy.vector.b1024.off | 2.608 | 2.613 [2.590, 2.642] | faster |
| scalar_vs_vector | resident | null_heavy.scalar.b1024.on → null_heavy.vector.b1024.on | 2.615 | 2.613 [2.600, 2.633] | faster |
| optimizer_off_vs_on | resident | null_heavy.vector.b1024.off → null_heavy.vector.b1024.on | 1.003 | 1.005 [0.997, 1.008] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | prepared | null_light.scalar.b1024.off → null_light.scalar.b1024.on | 1.000 | 1.001 [0.999, 1.003] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | null_light.scalar.b1024.off → null_light.vector.b1024.off | 1.964 | 1.963 [1.954, 1.968] | faster |
| scalar_vs_vector | prepared | null_light.scalar.b1024.on → null_light.vector.b1024.on | 1.956 | 1.964 [1.954, 1.971] | faster |
| optimizer_off_vs_on | prepared | null_light.vector.b1024.off → null_light.vector.b1024.on | 0.995 | 1.002 [0.996, 1.003] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | null_light.scalar.b1024.off → null_light.scalar.b1024.on | 1.001 | 1.000 [0.997, 1.002] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | null_light.scalar.b1024.off → null_light.vector.b1024.off | 1.960 | 1.957 [1.949, 1.964] | faster |
| scalar_vs_vector | resident | null_light.scalar.b1024.on → null_light.vector.b1024.on | 1.963 | 1.963 [1.957, 1.968] | faster |
| optimizer_off_vs_on | resident | null_light.vector.b1024.off → null_light.vector.b1024.on | 1.003 | 1.002 [0.998, 1.008] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | prepared | projection_narrow.scalar.b1024.off → projection_narrow.scalar.b1024.on | 1.018 | 1.018 [1.008, 1.019] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | projection_narrow.scalar.b1024.off → projection_narrow.vector.b1024.off | 1.221 | 1.219 [1.183, 1.229] | faster |
| scalar_vs_vector | prepared | projection_narrow.scalar.b1024.on → projection_narrow.vector.b1024.on | 1.160 | 1.150 [1.138, 1.159] | faster |
| optimizer_off_vs_on | prepared | projection_narrow.vector.b1024.off → projection_narrow.vector.b1024.on | 0.967 | 0.968 [0.947, 0.994] | slower |
| optimizer_off_vs_on | resident | projection_narrow.scalar.b1024.off → projection_narrow.scalar.b1024.on | 1.034 | 1.025 [1.017, 1.043] | faster |
| scalar_vs_vector | resident | projection_narrow.scalar.b1024.off → projection_narrow.vector.b1024.off | 1.192 | 1.175 [1.154, 1.191] | faster |
| scalar_vs_vector | resident | projection_narrow.scalar.b1024.on → projection_narrow.vector.b1024.on | 1.181 | 1.183 [1.167, 1.188] | faster |
| optimizer_off_vs_on | resident | projection_narrow.vector.b1024.off → projection_narrow.vector.b1024.on | 1.024 | 1.028 [1.015, 1.047] | faster |
| optimizer_off_vs_on | prepared | projection_wide.scalar.b1024.off → projection_wide.scalar.b1024.on | 1.010 | 1.003 [0.998, 1.033] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | projection_wide.scalar.b1024.off → projection_wide.vector.b1024.off | 0.924 | 0.919 [0.904, 0.929] | slower |
| scalar_vs_vector | prepared | projection_wide.scalar.b1024.on → projection_wide.vector.b1024.on | 0.917 | 0.921 [0.907, 0.933] | slower |
| optimizer_off_vs_on | prepared | projection_wide.vector.b1024.off → projection_wide.vector.b1024.on | 1.001 | 1.009 [0.991, 1.028] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | projection_wide.scalar.b1024.off → projection_wide.scalar.b1024.on | 1.016 | 1.017 [1.000, 1.029] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | projection_wide.scalar.b1024.off → projection_wide.vector.b1024.off | 0.930 | 0.930 [0.916, 0.942] | slower |
| scalar_vs_vector | resident | projection_wide.scalar.b1024.on → projection_wide.vector.b1024.on | 0.914 | 0.914 [0.911, 0.938] | slower |
| optimizer_off_vs_on | resident | projection_wide.vector.b1024.off → projection_wide.vector.b1024.on | 0.999 | 1.008 [0.995, 1.019] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | prepared | scan_broad.scalar.b1024.off → scan_broad.scalar.b1024.on | 1.001 | 1.001 [1.000, 1.002] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | scan_broad.scalar.b1024.off → scan_broad.vector.b1024.off | 3.988 | 3.987 [3.959, 3.992] | faster |
| scalar_vs_vector | prepared | scan_broad.scalar.b1024.on → scan_broad.vector.b1024.on | 3.957 | 3.958 [3.941, 3.971] | faster |
| optimizer_off_vs_on | prepared | scan_broad.vector.b1024.off → scan_broad.vector.b1024.on | 0.993 | 0.995 [0.991, 1.001] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | scan_broad.scalar.b1024.off → scan_broad.scalar.b1024.on | 0.998 | 0.999 [0.995, 1.002] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | scan_broad.scalar.b1024.off → scan_broad.vector.b1024.off | 3.945 | 3.942 [3.927, 3.964] | faster |
| scalar_vs_vector | resident | scan_broad.scalar.b1024.on → scan_broad.vector.b1024.on | 3.974 | 3.972 [3.960, 3.983] | faster |
| optimizer_off_vs_on | resident | scan_broad.vector.b1024.off → scan_broad.vector.b1024.on | 1.006 | 1.008 [0.998, 1.013] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | prepared | scan_selective.scalar.b1024.off → scan_selective.scalar.b1024.on | 1.001 | 1.001 [0.999, 1.002] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | scan_selective.vector.b1024.off → scan_selective.vector.b256.off | 0.887 | 0.888 [0.881, 0.898] | slower |
| optimizer_off_vs_on | prepared | scan_selective.vector.b256.off → scan_selective.vector.b256.on | 1.004 | 1.004 [1.001, 1.010] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | scan_selective.vector.b1024.on → scan_selective.vector.b256.on | 0.893 | 0.897 [0.894, 0.902] | slower |
| scalar_vs_vector | prepared | scan_selective.scalar.b1024.off → scan_selective.vector.b1024.off | 4.150 | 4.148 [4.104, 4.152] | faster |
| scalar_vs_vector | prepared | scan_selective.scalar.b1024.on → scan_selective.vector.b1024.on | 4.136 | 4.136 [4.067, 4.144] | faster |
| optimizer_off_vs_on | prepared | scan_selective.vector.b1024.off → scan_selective.vector.b1024.on | 0.997 | 1.000 [0.997, 1.004] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | scan_selective.vector.b1024.off → scan_selective.vector.b4096.off | 0.935 | 0.954 [0.918, 0.988] | slower |
| optimizer_off_vs_on | prepared | scan_selective.vector.b4096.off → scan_selective.vector.b4096.on | 1.001 | 1.001 [0.935, 1.029] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | prepared | scan_selective.vector.b1024.on → scan_selective.vector.b4096.on | 0.939 | 0.936 [0.890, 0.981] | slower |
| optimizer_off_vs_on | resident | scan_selective.scalar.b1024.off → scan_selective.scalar.b1024.on | 1.004 | 1.005 [1.002, 1.006] | faster |
| batch_1024_vs_selected | resident | scan_selective.vector.b1024.off → scan_selective.vector.b256.off | 0.890 | 0.891 [0.879, 0.893] | slower |
| optimizer_off_vs_on | resident | scan_selective.vector.b256.off → scan_selective.vector.b256.on | 1.003 | 1.005 [0.997, 1.015] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | resident | scan_selective.vector.b1024.on → scan_selective.vector.b256.on | 0.905 | 0.903 [0.893, 0.908] | slower |
| scalar_vs_vector | resident | scan_selective.scalar.b1024.off → scan_selective.vector.b1024.off | 4.122 | 4.122 [4.112, 4.129] | faster |
| scalar_vs_vector | resident | scan_selective.scalar.b1024.on → scan_selective.vector.b1024.on | 4.051 | 4.053 [4.047, 4.095] | faster |
| optimizer_off_vs_on | resident | scan_selective.vector.b1024.off → scan_selective.vector.b1024.on | 0.987 | 0.988 [0.981, 1.005] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | resident | scan_selective.vector.b1024.off → scan_selective.vector.b4096.off | 0.925 | 0.924 [0.879, 0.963] | slower |
| optimizer_off_vs_on | resident | scan_selective.vector.b4096.off → scan_selective.vector.b4096.on | 0.997 | 0.997 [0.961, 1.046] | inconclusive (IQR overlap) |
| batch_1024_vs_selected | resident | scan_selective.vector.b1024.on → scan_selective.vector.b4096.on | 0.935 | 0.941 [0.915, 0.960] | slower |
| optimizer_off_vs_on | prepared | sort_limit.scalar.b1024.off → sort_limit.scalar.b1024.on | 1.001 | 1.001 [0.997, 1.016] | inconclusive (IQR overlap) |
| scalar_vs_vector | prepared | sort_limit.scalar.b1024.off → sort_limit.vector.b1024.off | 1.870 | 1.871 [1.863, 1.911] | faster |
| scalar_vs_vector | prepared | sort_limit.scalar.b1024.on → sort_limit.vector.b1024.on | 1.878 | 1.877 [1.844, 1.907] | faster |
| optimizer_off_vs_on | prepared | sort_limit.vector.b1024.off → sort_limit.vector.b1024.on | 1.005 | 1.005 [0.981, 1.017] | inconclusive (IQR overlap) |
| optimizer_off_vs_on | resident | sort_limit.scalar.b1024.off → sort_limit.scalar.b1024.on | 0.999 | 1.013 [0.996, 1.029] | inconclusive (IQR overlap) |
| scalar_vs_vector | resident | sort_limit.scalar.b1024.off → sort_limit.vector.b1024.off | 1.895 | 1.881 [1.876, 1.894] | faster |
| scalar_vs_vector | resident | sort_limit.scalar.b1024.on → sort_limit.vector.b1024.on | 1.850 | 1.837 [1.830, 1.869] | faster |
| optimizer_off_vs_on | resident | sort_limit.vector.b1024.off → sort_limit.vector.b1024.on | 0.975 | 0.977 [0.967, 0.994] | inconclusive (IQR overlap) |

## Interpretation limits

These workloads measure the whole stated scope, not isolated SIMD kernels. Narrow/wide projections include different owning sink and rendering volumes; sorting remains blocking; pruning removes scan descriptors without necessarily reducing lazy payload reads. Join pushdown can reduce pairs before aggregation, while ordered DOUBLE accumulation constrains build-side changes. Batch sizes can add allocation/materialization overhead, and small/selective workloads may show little benefit. The tables retain those losses and overlapping-IQR cases rather than selecting only favorable runs.

The JSON report also preserves planning, execution, resident and rendering distributions for every case. Raw records and provenance retain loading/preparation metadata, configuration options, input/query hashes, compiler/cache flags, failures, and every repetition. Python DuckDB calls provide correctness only and have no timing comparison here.
