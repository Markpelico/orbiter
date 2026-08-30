# RESULTS

Every measurement this project produces, including the ones that come out
badly. A chart showing where it fell over is more credible than one showing it
never did.

## Ledger

| Date | Measurement | Verdict | Chart |
|---|---|---|---|
| 2026-08-30 | **Cold start, empty fleet → first execution: 65s** (submit 12:15:05 → started 12:16:10; covers KEDA activation + Karpenter node purchase + boot + join + image pull + worker start; n=1, first live run, free-tier t3.small on-demand fallback) | measured | pending |
| 2026-08-30 | **Scale-up for a single stranded job: node Ready in 89s**, fleet 0→1 (the KEDA activation-dead-zone fix, verified live) | measured | pending |
| 2026-08-30 | **Full cycle: 21/21 jobs succeeded**; KEDA 0→4→0 pods; Karpenter bought and consolidated away t3.small nodes; spot market refused by the free plan → on-demand fallback pool absorbed 100% of demand | measured | — |
| 2026-08-30 | **One distributed trace spans api → relay → worker** (0ms POST /jobs → 9.5ms relay.publish → 2,438ms job.process attempt 1 — queue wait visible in the gap), verified via Tempo API on the local stack | verified | pending |
| — | Throughput vs. worker count (1..32) | pending Phase 3 load tests | — |
| — | p50/p95/p99 vs. offered load, knee | pending Phase 3 load tests | — |
| — | Overload: admission on vs. off (ADR-0004) | pending Phase 3 load tests | — |
| — | Cold-start breakdown (node/image/pod/poll) | pending (have the total; need the split) | — |
| — | Recovery time: pod kill / node kill / partition | pending Phase 5 | — |
| — | Naive TTL lock vs. fenced lease under TimeChaos | pending Phase 5 | — |
| — | Cost per 1,000 jobs: spot vs. on-demand, STZ on/off | pending Phase 4 | — |
| — | Nightly chaos pass/fail history | pending Phase 5 | — |

## Method notes

Load generation: k6. Metrics: Prometheus/Mimir with exemplars. Cost: OpenCost
(measured, not the pricing calculator). Each entry links its raw run data
under `results/` and states the fleet shape, so every chart is reproducible.
