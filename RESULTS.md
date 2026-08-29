# RESULTS

Every measurement this project produces, including the ones that come out
badly. A chart showing where it fell over is more credible than one showing it
never did.

## Ledger

| Date | Measurement | Verdict | Chart |
|---|---|---|---|
| — | Throughput vs. worker count (1..32) | pending Phase 3 | — |
| — | p50/p95/p99 vs. offered load, knee | pending Phase 3 | — |
| — | Overload: admission on vs. off (ADR-0004) | pending Phase 3 | — |
| — | Scale-up lag: spike → first pod → first node | pending Phase 3 | — |
| — | Cold-start breakdown (node/image/pod/poll) | pending Phase 3 | — |
| — | Recovery time: pod kill / node kill / partition | pending Phase 5 | — |
| — | Naive TTL lock vs. fenced lease under TimeChaos | pending Phase 5 | — |
| — | Cost per 1,000 jobs: spot vs. on-demand, STZ on/off | pending Phase 4 | — |
| — | Nightly chaos pass/fail history | pending Phase 5 | — |

## Method notes

Load generation: k6. Metrics: Prometheus/Mimir with exemplars. Cost: OpenCost
(measured, not the pricing calculator). Each entry links its raw run data
under `results/` and states the fleet shape, so every chart is reproducible.
